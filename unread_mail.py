"""Read-only JMAP inbox counts and terminal-only mailbox credential setup."""

from concurrent.futures import ThreadPoolExecutor
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urljoin, urlsplit

import requests


ORIGIN = "https://uk.sidephasestudio.com"
CORE = "urn:ietf:params:jmap:core"
MAIL = "urn:ietf:params:jmap:mail"
CREDENTIALS_PATH = Path(__file__).resolve().parent / ".env.mailboxes.json"
DOMAINS = (
    "laytnrbx.com", "streammemes.com", "planecast.live", "lodgerready.uk", "forevertails.pet",
    "craigybabyj.com", "inkbymeg.uk", "beatmyland.ing", "globalvectors.app", "sidephasestudio.com",
)


def load_accounts(path=CREDENTIALS_PATH):
    accounts = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(accounts, list) or len(accounts) > 10:
        raise ValueError("Expected up to ten support inboxes")
    seen = set()
    for account in accounts:
        address = account["address"]
        if (not isinstance(address, str)
                or not re.fullmatch(r"support@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}", address)
                or address in seen):
            raise ValueError("Expected unique support addresses")
        seen.add(address)
        if (not isinstance(account["label"], str) or not 1 <= len(account["label"]) <= 32
                or not account["label"].isprintable()
                or not isinstance(account["password"], str) or not account["password"]):
            raise ValueError("Missing mailbox label or password")
    return accounts


def safe_url(value):
    value = urljoin(ORIGIN, value)
    url = urlsplit(value)
    # Do not forward mailbox credentials to another host or insecure URL.
    if (url.scheme != "https" or url.hostname != urlsplit(ORIGIN).hostname
            or url.port not in (None, 443) or url.username is not None
            or url.password is not None or url.fragment):
        raise ValueError("Unsafe JMAP URL")
    return value


def fetch_inbox(account):
    with requests.Session() as client:
        client.auth = (account["address"], account["password"])
        session_url = ORIGIN + "/.well-known/jmap"
        for _ in range(4):
            response = client.get(session_url, timeout=8, allow_redirects=False)
            if response.status_code not in (301, 302, 303, 307, 308):
                break
            session_url = safe_url(urljoin(session_url, response.headers["Location"]))
        if response.status_code != 200:
            raise ValueError("JMAP session unavailable")
        session = response.json()
        account_id = session["primaryAccounts"][MAIL]
        if (not isinstance(account_id, str) or not account_id
                or MAIL not in session["accounts"][account_id]["accountCapabilities"]):
            raise ValueError("Mail account missing from session")
        api_url = safe_url(session["apiUrl"])
        response = client.post(api_url, json={
            "using": [CORE, MAIL],
            "methodCalls": [["Mailbox/get", {
                "accountId": account_id, "properties": ["role", "unreadEmails"],
            }, "inbox"]],
        }, timeout=8, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError("Mailbox request unavailable")
        method, result, call_id = response.json()["methodResponses"][0]
        if (method != "Mailbox/get" or call_id != "inbox"
                or result["accountId"] != account_id or result.get("notFound")):
            raise ValueError("Mailbox request failed")
        inboxes = [folder for folder in result["list"] if folder.get("role") == "inbox"]
        if len(inboxes) != 1:
            raise ValueError("Expected exactly one inbox")
        count = inboxes[0]["unreadEmails"]
        if type(count) is not int or not 0 <= count <= 9007199254740991:
            raise ValueError("Invalid unread count")
        return count


def _fetch_account(account):
    result = {"address": account["address"], "label": account["label"], "stale": True}
    if not account.get("password"):
        return result
    try:
        result.update(count=fetch_inbox(account), stale=False)
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, AttributeError):
        pass  # Exception text and HTTP bodies may contain private account details.
    return result


def fetch_unread_mail():
    try:
        accounts = load_accounts()
    except (OSError, ValueError, KeyError, TypeError):
        return {"error": True, "inboxes": []}
    configured = {account["address"]: account for account in accounts}
    accounts = [configured.get("support@" + domain, {"address": "support@" + domain, "label": domain})
                for domain in DOMAINS]
    with ThreadPoolExecutor(max_workers=5) as executor:
        return {"error": False, "inboxes": list(executor.map(_fetch_account, accounts))}


def merge_counts(previous, result):
    if result["error"]:
        return [{**row, "stale": True} for row in previous]
    old = {row["address"]: row for row in previous}
    return [{**old.get(row["address"], {}), **row} for row in result["inboxes"]]


def save_accounts(accounts, path=CREDENTIALS_PATH):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".env.mailboxes-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(accounts, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def setup():
    if not sys.stdin.isatty():
        sys.exit("Run in your own terminal for hidden password entry.")
    accounts = load_accounts()
    for index, domain in enumerate(DOMAINS):
        address = "support@" + domain
        existing = next((account for account in accounts if account["address"] == address), None)
        if existing:
            try:
                print(f"{existing['label']}: {fetch_inbox(existing)} unread (verified)")
                continue
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, AttributeError):
                print(f"Mailbox {index + 1}: saved login failed; please re-enter it.")
        while True:
            label = existing["label"] if existing else domain
            print(f"Inbox {index + 1}/10: {address}")
            password = getpass.getpass("Dedicated mailbox password (hidden): ")
            account = {"address": address, "label": label, "password": password}
            trial = [row for row in accounts if row["address"] != address] + [account]
            try:
                if not password:
                    raise ValueError("Password missing")
                count = fetch_inbox(account)
            except (requests.RequestException, ValueError, KeyError, TypeError, IndexError, AttributeError):
                print("Verification failed. Check the mailbox password; nothing saved.")
                continue
            save_accounts(trial)
            accounts = trial
            print(f"{label}: {count} unread (verified; login saved privately)")
            break
    print("All ten inboxes verified. Tell Codex setup is complete; do not share passwords.")


if __name__ == "__main__":
    try:
        setup()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nSetup stopped; previously verified logins remain saved privately.")
