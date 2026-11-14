# Project guidance

Read README.md and the current section of HANDOVER.md before making changes.
The older handover section is historical and includes superseded assumptions.

## Existing structure

- `lcd_therma_stats.py`: USB transport, two panel layouts, background scheduler,
  live feeds and persistent VPS SSH stream.
- `vps_metrics.py`: Linux sampler piped to remote Python; no VPS installation.
- `stalwart_metrics.py`: SMTP Prometheus parsing, daily persisted increments,
  private credential helper. Day boundaries use Europe/London.
- `unread_mail.py`: read-only JMAP inbox queries, stale-count merging and
  private mailbox configuration. Keep authentication on the approved HTTPS host.

## Constraints

Keep the single service and existing scheduler. Preserve the 1920×462 wire
resolution, serial selection, rotation, brightness and frame keepalive behavior.
Keep credentials out of logs and Git. Never stage `.env`, `.env.mailboxes.json`,
`.smtp-daily.json`, generated previews, logs or virtualenv files. Preserve SMTP
state on deploy; the first tracking day is partial, and polling cannot recover
sends lost before an unobserved mail-server counter reset.
Do not send mail or change mailbox contents to test read-only counters.
Preserve unrelated working changes; review the full staged scope before pushing.

## Checks and deployment

Run each `test_*.py` with `./venv/bin/python`, then `git diff --check`.
Tests mock network calls and generate previews under `/tmp`.
For authorized runtime changes, restart `lcd_therma.service` and check actual
frame-send and feed-update logs; an active service alone does not prove success.
