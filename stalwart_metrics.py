"""Stalwart submission counter and private, terminal-only credential setup."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo
import getpass
import os
from pathlib import Path
import re
import sys
import tempfile
from decimal import Decimal, InvalidOperation

import requests


URL = "https://uk.sidephasestudio.com/metrics/prometheus"
PASSWORD_ENV = "STALWART_METRICS_PASSWORD"
DAILY_PATH = Path(__file__).resolve().parent / ".smtp-daily.json"
SAMPLE = re.compile(r'queue_authenticated_message_queued(?:\{.*\})?\s+(\S+)(?:\s+\S+)?')


def parse_submissions(text):
    total = 0
    found = False
    for line in text.splitlines():
        match = SAMPLE.fullmatch(line.strip())
        if not match:
            continue
        value = Decimal(match[1])
        if not value.is_finite() or value < 0 or value != value.to_integral_value():
            raise ValueError("Invalid submission counter")
        total += int(value)
        found = True
    if not found:
        raise ValueError("Submission counter missing")
    return total


def daily_submissions(counter, path=None, now=None):
    path = DAILY_PATH if path is None else path
    now = now or datetime.now(ZoneInfo("Europe/London"))
    day = now.date().isoformat()
    try:
        previous = json.loads(path.read_text())
    except FileNotFoundError:
        previous = None
    if previous is None:
        state = {"day": day, "counter": counter, "sent": 0,
                 "since": now.strftime("%H:%M")}
    else:
        delta = counter - previous["counter"] if counter >= previous["counter"] else counter
        same_day = previous["day"] == day
        state = {"day": day, "counter": counter,
                 "sent": previous["sent"] + delta if same_day else delta,
                 "since": previous["since"] if same_day else ""}
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".smtp-daily-")
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    period = f"Today from {state['since']}" if state["since"] else "Today"
    return {"smtp_sent": state["sent"], "smtp_period": period, "smtp_stale": False}


def fetch_stalwart_submissions(password=None):
    password = os.environ.get(PASSWORD_ENV, "") if password is None else password
    if not password:
        return {"smtp_stale": True}
    try:
        response = requests.get(URL, auth=("stalwart-metrics", password),
                                timeout=10, allow_redirects=False)
        if response.status_code != 200:
            return {"smtp_stale": True}
        return daily_submissions(parse_submissions(response.text))
    except (requests.RequestException, ValueError, InvalidOperation, OSError, KeyError, TypeError):
        # Never log exceptions that could contain authentication details.
        return {"smtp_stale": True}


def save_password(path, password):
    if not password or any(char in password for char in "\r\n\x00"):
        raise ValueError("Password must be nonempty and single-line")
    lines = path.read_text().splitlines() if path.exists() else []
    lines = [line for line in lines if line.partition("=")[0].strip() != PASSWORD_ENV]
    quoted = password.replace("\\", "\\\\").replace('"', '\\"')
    lines.append(f'{PASSWORD_ENV}="{quoted}"')
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".smtp-env-")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


if __name__ == "__main__":
    if not sys.stdin.isatty():
        sys.exit("Run this helper in your own terminal for hidden password entry.")
    password = getpass.getpass("Stalwart metrics password (hidden): ")
    result = fetch_stalwart_submissions(password)
    if result["smtp_stale"]:
        sys.exit("Live verification failed; password was not saved.")
    save_password(Path(__file__).resolve().parent / ".env", password)
    print(f"Verified SMTP sent: {result['smtp_sent']} ({result['smtp_period']}). Password saved privately.")
