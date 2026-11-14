from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
from unittest.mock import Mock, patch

import lcd_therma_stats as lcd
import unread_mail as mail


ACCOUNT = {"address": "support@example.com", "label": "example.com", "password": "test-only"}
SESSION = {"apiUrl": mail.ORIGIN + "/jmap/", "primaryAccounts": {mail.MAIL: "mail-id"},
           "accounts": {"mail-id": {"accountCapabilities": {mail.MAIL: {}}}}}


def response(data, status=200):
    return Mock(status_code=status, json=Mock(return_value=data))


def mailbox_response(count):
    return {"methodResponses": [["Mailbox/get", {"accountId": "mail-id", "list": [
        {"role": "junk", "unreadEmails": 99}, {"role": "trash", "unreadEmails": 42},
        {"role": None, "unreadEmails": 33}, {"role": "inbox", "unreadEmails": count},
    ]}, "inbox"]]}


def check():
    client = Mock()
    with patch.object(mail.requests, "Session") as session:
        session.return_value.__enter__.return_value = client
        client.get.return_value = response(SESSION)
        for count in (0, 3, 102):
            client.post.return_value = response(mailbox_response(count))
            assert mail.fetch_inbox(ACCOUNT) == count
            assert client.auth == (ACCOUNT["address"], "test-only")
            client.post.assert_called_with(mail.ORIGIN + "/jmap/", json={
                "using": [mail.CORE, mail.MAIL], "methodCalls": [["Mailbox/get", {
                    "accountId": "mail-id", "properties": ["role", "unreadEmails"],
                }, "inbox"]],
            }, timeout=8, allow_redirects=False)
        redirect = Mock(status_code=307, headers={"Location": "/jmap/session"})
        client.get.side_effect = [redirect, response(SESSION)]
        assert mail.fetch_inbox(ACCOUNT) == 102
        client.get.assert_called_with(mail.ORIGIN + "/jmap/session", timeout=8, allow_redirects=False)
        for url in ("http://uk.sidephasestudio.com/jmap/", "https://other.example/jmap/",
                    "https://user:password@uk.sidephasestudio.com/jmap/",
                    "https://uk.sidephasestudio.com:8443/jmap/"):
            client.post.reset_mock()
            client.get.side_effect = [Mock(status_code=307, headers={"Location": url})]
            assert mail._fetch_account(ACCOUNT)["stale"]
            client.post.assert_not_called()
            client.get.side_effect = None
            client.get.return_value = response({**SESSION, "apiUrl": url})
            assert mail._fetch_account(ACCOUNT)["stale"]
            client.post.assert_not_called()
        client.get.return_value = response(SESSION)
        for count in (-1, True, "0", None, 2.5):
            client.post.return_value = response(mailbox_response(count))
            assert mail._fetch_account(ACCOUNT) == {
                "address": ACCOUNT["address"], "label": ACCOUNT["label"], "stale": True}
        for data in ({"methodResponses": [["error", {"type": "forbidden"}, "inbox"]]},
                     {"methodResponses": []}, mailbox_response(1)):
            broken = deepcopy(data)
            if broken == mailbox_response(1):
                broken["methodResponses"][0][1]["list"] = [{"role": "junk", "unreadEmails": 5}]
            client.post.return_value = response(broken)
            assert mail._fetch_account(ACCOUNT)["stale"]
        client.get.return_value = response({}, 401)
        assert mail._fetch_account(ACCOUNT)["stale"]
        client.get.side_effect = mail.requests.Timeout("private exception must not be logged")
        assert mail._fetch_account(ACCOUNT)["stale"]

    initial = [{"address": ACCOUNT["address"], "label": ACCOUNT["label"], "count": 3, "stale": False}]
    failed = {"error": False, "inboxes": [{"address": ACCOUNT["address"], "label": "example", "stale": True}]}
    stale = mail.merge_counts(initial, failed)
    assert stale[0]["count"] == 3 and stale[0]["stale"]
    assert initial[0]["stale"] is False
    assert "count" not in mail.merge_counts([], failed)[0]
    assert mail.merge_counts(initial, {"error": True})[0]["stale"]
    fresh = {"error": False, "inboxes": [{**initial[0], "count": 0}]}
    assert mail.merge_counts(stale, fresh)[0] == {**initial[0], "count": 0}
    assert mail.merge_counts(initial, {"error": False, "inboxes": []}) == []
    first = {**ACCOUNT, "address": "support@" + mail.DOMAINS[0]}
    second = {**ACCOUNT, "address": "support@" + mail.DOMAINS[1]}
    with patch.object(mail, "load_accounts", return_value=[first, second]), \
            patch.object(mail, "fetch_inbox", side_effect=lambda account: 0 if account == first else (_ for _ in ()).throw(ValueError())):
        batch = mail.fetch_unread_mail()
        assert len(batch["inboxes"]) == 10
        assert batch["inboxes"][0]["count"] == 0
        assert batch["inboxes"][1]["stale"]
    with patch.object(mail, "load_accounts", side_effect=ValueError()):
        assert mail.fetch_unread_mail() == {"error": True, "inboxes": []}
    with patch.object(mail, "load_accounts", return_value=[]), \
            patch.object(mail, "fetch_inbox") as request:
        batch = mail.fetch_unread_mail()
        assert len(batch["inboxes"]) == 10
        assert all(row["stale"] and "count" not in row for row in batch["inboxes"])
        request.assert_not_called()
    with patch.object(mail.sys.stdin, "isatty", return_value=True), \
            patch.object(mail, "load_accounts", return_value=[]), \
            patch.object(mail.getpass, "getpass", return_value="test-only"), \
            patch.object(mail, "fetch_inbox", return_value=0), \
            patch.object(mail, "save_accounts") as save, \
            patch("builtins.print"):
        mail.setup()
        saved = save.call_args.args[0]
        assert [row["address"] for row in saved] == ["support@" + domain for domain in mail.DOMAINS]
        assert len(saved) == 10

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "credentials"
        assert mail.load_accounts(path) == []
        mail.save_accounts([ACCOUNT], path)
        assert mail.load_accounts(path) == [ACCOUNT]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        for accounts in ([ACCOUNT, ACCOUNT], [{**ACCOUNT, "address": "abuse@example.com"}],
                         [{**ACCOUNT, "address": "postmaster@example.com"}],
                         [{**ACCOUNT, "password": ""}], [{**ACCOUNT, "label": "x" * 33}], {}):
            path.write_text(json.dumps(accounts))
            try:
                mail.load_accounts(path)
            except (ValueError, KeyError, TypeError):
                pass
            else:
                raise AssertionError("Invalid mailbox configuration accepted")

    rows = [{"address": f"support@domain{i}.com", "label": f"domain{i}.com",
             "count": i, "stale": i == 3} for i in range(10)]
    rows[1].pop("count")
    rows[1]["stale"] = True
    rows[9]["label"] = "long-domain-label-for-readability"
    zero = {"label": "empty.com", "count": 0, "stale": False}
    unread = {"label": "unread.com", "count": 4, "stale": False}
    unknown = {"label": "unknown.com", "stale": True}
    stale_zero = {"label": "stale.com", "count": 0, "stale": True}
    assert lcd.visible_unread_inboxes([zero, unread, unknown, stale_zero]) == [unread, unknown, stale_zero]
    with patch.object(lcd.ImageDraw.ImageDraw, "text", autospec=True) as text:
        lcd.render_second_frame({}, [zero, unread, unknown])
        labels = [call.args[2] for call in text.call_args_list]
        assert "empty.com" not in labels
        assert "unread.com" in labels and "4" in labels
        assert "unknown.com" in labels and "\u2014 Stale" in labels
        mail_calls = [call for call in text.call_args_list if call.args[2] in ("unread.com", "unknown.com", "4", "\u2014 Stale")]
        assert all(call.args[1][0] >= 1304 for call in mail_calls)
    frame = lcd.render_second_frame({}, rows)
    assert frame.size == (1920, 462)
    frame.save("/tmp/lcd-unread-preview.png")
    assert lcd.render_second_frame({}, []).size == (1920, 462)


if __name__ == "__main__":
    check()
    print("Unread Mail checks passed")
