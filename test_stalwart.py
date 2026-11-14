from datetime import datetime
import os
from pathlib import Path
import stat
import tempfile
from unittest.mock import Mock, patch

import lcd_therma_stats as lcd
import stalwart_metrics as smtp


def check():
    assert smtp.parse_submissions('''# TYPE queue_authenticated_message_queued counter
queue_authenticated_message_queued{mailbox="one"} 3
queue_authenticated_message_queued{mailbox="two words"} 2e0 123456789
queue_authenticated_message_queued_total 100
''') == 5
    for value, expected in (("0", 0), ("3.0", 3), ("9007199254740993", 9007199254740993)):
        assert smtp.parse_submissions("queue_authenticated_message_queued " + value) == expected
    for text in ("", "queue_authenticated_message_queued_total 3",
                 *("queue_authenticated_message_queued " + value
                   for value in ("NaN", "+Inf", "-1", "2.5", "invalid"))):
        try:
            smtp.parse_submissions(text)
        except (ValueError, smtp.InvalidOperation):
            pass
        else:
            raise AssertionError("Invalid counter accepted")

    response = Mock(status_code=200, text="queue_authenticated_message_queued 3")
    with patch.object(smtp.requests, "get", return_value=response) as request, patch.object(
            smtp, "daily_submissions", side_effect=lambda count: {"smtp_sent": count, "smtp_stale": False}):
        with patch.dict(os.environ, {smtp.PASSWORD_ENV: "test-only"}):
            state = smtp.fetch_stalwart_submissions()
        assert state == {"smtp_sent": 3, "smtp_stale": False}
        request.assert_called_once_with(smtp.URL, auth=("stalwart-metrics", "test-only"),
                                        timeout=10, allow_redirects=False)
        for status in (401, 302, 500):
            response.status_code = status
            state.update(smtp.fetch_stalwart_submissions("test-only"))
            assert state == {"smtp_sent": 3, "smtp_stale": True}
        response.status_code = 200
        response.text = "# Missing metric"
        assert smtp.fetch_stalwart_submissions("test-only") == {"smtp_stale": True}
        request.side_effect = smtp.requests.Timeout("must not log exceptions")
        assert smtp.fetch_stalwart_submissions("test-only") == {"smtp_stale": True}
        request.reset_mock()
        assert smtp.fetch_stalwart_submissions("") == {"smtp_stale": True}
        request.assert_not_called()
        request.side_effect = None
        response.text = "queue_authenticated_message_queued 0"
        state.update(smtp.fetch_stalwart_submissions("test-only"))
        assert state == {"smtp_sent": 0, "smtp_stale": False}

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "daily.json"
        def daily(counter, day=14, hour=12):
            return smtp.daily_submissions(counter, path, datetime(2026, 11, day, hour))
        assert daily(100) == {"smtp_sent": 0, "smtp_period": "Today from 12:00", "smtp_stale": False}
        assert daily(103)["smtp_sent"] == 3
        assert daily(103)["smtp_sent"] == 3  # persisted across repeated calls/restarts
        assert daily(2)["smtp_sent"] == 5  # mail-server reset
        assert daily(4, day=15, hour=0) == {"smtp_sent": 2, "smtp_period": "Today", "smtp_stale": False}
        assert daily(8, day=15)["smtp_sent"] == 6
        path.write_text("broken")
        try:
            daily(9)
        except ValueError:
            pass
        else:
            raise AssertionError("Corrupt state silently reset")

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / ".env"
        path.write_text('OTHER=keep\nSTALWART_METRICS_PASSWORD=old\n')
        smtp.save_password(path, 'fake \\"$secret')
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.read_text() == 'OTHER=keep\nSTALWART_METRICS_PASSWORD="fake \\\\\\"$secret"\n'
        for password in ("", "line\nbreak", "carriage\rreturn", "nul\0byte"):
            before = path.read_bytes()
            try:
                smtp.save_password(path, password)
            except ValueError:
                pass
            else:
                raise AssertionError("Unsafe environment value accepted")
            assert path.read_bytes() == before

    for data, label, value in (({}, "SMTP sent", "\u2014"),
                               ({"smtp_sent": 3}, "SMTP sent", "3"),
                               ({"smtp_sent": 3, "smtp_stale": True}, "SMTP sent (Stale)", "3")):
        with patch.object(lcd, "_stat", wraps=lcd._stat) as render:
            frame = lcd.render_second_frame(data)
            call = next(call for call in render.call_args_list if call.args[4] == label)
            assert call.args[2:6] == (1624, 28, label, value)
            assert frame.size == (1920, 462)
    lcd.render_second_frame({"brevo_sent": "5/300", "smtp_sent": 3}).save("/tmp/lcd-stalwart-preview.png")


if __name__ == "__main__":
    check()
    print("Stalwart checks passed")
