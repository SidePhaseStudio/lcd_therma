# lcd_therma — Handover

## Current handover — 14 November 2026

The original build notes below are historical. Use README.md and AGENTS.md for
the current layout, configuration, checks, and operating rules.

- One `lcd_therma.service` drives two serial-selected 1920×462 USB panels.
  The original shows local/VPS metrics, crypto/presence/weather and social stats.
  The second shows Global Vectors, BeatMyLanding and mail statistics; it is
  rotated 180 degrees, with its background darkened separately from the text.
- VPS metrics use one persistent SSH stream with reconnect handling.
- Brevo shows daily free-plan usage out of 300, refreshed every ten minutes.
- SMTP polls Stalwart every minute and saves daily increments to
  `.smtp-daily.json`, using Europe/London dates. LCD restarts preserve the count.
  The first day is labelled `Today from HH:MM`; historical sends are unavailable.
  Polling can misattribute sends near midnight and miss sends before an
  unobserved Stalwart counter reset. Do not delete this runtime state to deploy.
- Unread Mail uses read-only JMAP queries for ten support inboxes every ten
  minutes. Fresh zeroes are hidden; failures remain visible as stale. Credentials
  live only in `.env.mailboxes.json`, configured through `unread_mail.py`.
- Global Vectors uses the existing private admin token and Luke Discord config.
  Stalwart credentials are entered privately through `stalwart_metrics.py`.
  Never publish credentials, runtime state, logs, or the virtualenv.
- Daily SMTP logic, rendering, mail auth/error paths, and the second-panel
  integration have runnable `test_*.py` checks. See README.md for the command.

## Historical original build notes

> **2026-09-20 correction**: this document (and the original build) assumed
> the panel's wire resolution was 1920x480, taken from the product's own
> marketed spec. It's actually **1920x462** — the vendor's real firmware
> (decompiled by the `thermalright-trcc-linux` project) expects 18 rows less
> than the box says. See the README's "Panel / Protocol" section for the
> full story; `lcd_therma_stats.py` now uses the corrected `HEIGHT = 462`.
> Left the rest of this file as originally written below, since it's meant
> to capture that session's context as it actually happened.

New project for a Thermalright Trofeo Vision 9.16" USB LCD panel, spun off from
the `LCD` project (`/home/craig/projects/LCD`) which drives Craig's original
3.5" panel. This is intended to become his **permanent** display. Read this
whole file before touching code — it captures context from a long prior
session that isn't otherwise written down anywhere.

## What's already done

- Project scaffolded: `lcd_therma_stats.py`, `requirements.txt`, `.env.example`,
  `lcd_therma.service`, `lcd_therma.rules`, `.gitignore`, logo assets (copied
  from `LCD`).
- Venv created at `venv/`, dependencies installed.
- **The USB transport layer is implemented and verified working against the
  real hardware** — a standalone smoke test opened the panel, rendered a test
  frame, and sent it successfully (handshake OK, frame sent, ACK received, no
  errors). See "Verifying it still works" below to repeat that test.
- A first-pass 4-column layout is implemented in `render_frame()` and renders
  correctly (checked visually) — see the "Layout" section below for what needs
  refining.
- All the data-fetching logic (BTC/ETH prices, BeatMyLanding stats, Discord,
  YouTube, TikTok, CPU/mem/disk/network/temp) is ported **unchanged** from the
  sibling project's `server_lcd_stats.py` — this part is mature and doesn't
  need rework.

## What's NOT done / needs deciding

1. **Layout is a rough first pass, not a final design.** Four ~480px columns
   (system stats / crypto / BeatMyLanding / social), see
   `lcd_therma_preview.png` description below for what it currently looks
   like. 1920×480 is a lot of real estate compared to the 3.5" panel's
   320×480 portrait — worth actually designing for the space (bigger text,
   maybe fewer/bigger stat tiles, use of the height more effectively — currently
   most content sits near the top with a lot of empty space below) rather than
   just cramming the same info in.
2. **Refresh interval (`LCD_SAMPLE_SECONDS`, default 2.0s) is a guess, not
   tuned.** This panel has no partial-update capability (see Protocol below)
   — every send is a full JPEG-encode + full-frame USB push, so it's more
   expensive than the RGB565 partial updates the other project uses on its
   0.5s tick. Worth profiling actual CPU/USB time per send on this hardware
   and tuning from there. There's already a change-detection guard (`state !=
   last_sent_state`) so it won't send when nothing's changed, but every tick
   still does the `sample_metrics()` work regardless.
3. **Not installed as a service yet.** `lcd_therma.service` is written but not
   copied to `/etc/systemd/system/` or enabled.
4. **udev rule not installed.** The panel is owned `root:root`, group-readable
   only (`crw-rw-r--`) — normal-user access needs the udev rule in
   `lcd_therma.rules` installed first (see file for the one-liner). The smoke
   test so far was run under `sudo`; the systemd service is configured to run
   as `User=craig`, which **will not have permission to open the device until
   that udev rule is installed.**
5. **No `.env` file created yet** — copy `.env.example` to `.env` and fill in
   real values (YouTube API key etc.) before running for real.
6. **No auto-reconnect testing done** — the code has a basic
   `usb.core.USBError` catch-and-reopen loop, modeled on the other project's
   serial-disconnect handling, but it hasn't actually been exercised against
   a real unplug/replug cycle. Worth testing.
7. **Display count decision still open.** Craig hadn't decided, as of this
   handover, whether this 9" panel runs alone, alongside the current 3.5"
   Turing panel, alongside the very original panel (pre-Turing-swap), or all
   three at once. That affects whether `LCD` and `lcd_therma` end up running
   as independent systemd services side by side (current assumption) or need
   any coordination.

## Hardware / protocol reference

- **Panel**: Thermalright Trofeo Vision 9.16" ultrawide, 1920×480, USB-C.
- **USB ID**: `0416:5408` (Winbond Electronics Corp., product string
  "USBDISPLAY"). Vendor-specific USB class, two bulk endpoints — **not** a
  CDC/serial device, no `/dev/ttyACM*` node. Uses `pyusb` directly, not
  `pyserial`.
- **Endpoints**: `0x81` (bulk IN), `0x09` (bulk OUT).
- **Protocol** ("LY" bulk transport) — ported from the open-source
  [`thermalright-lcd-control`](https://github.com/rejeb/thermalright-lcd-control)
  project, which reverse-engineered it from the vendor's TRCC USBLCDNEW
  Windows software. Their code has explicit config for this exact device at
  `src/thermalright_lcd_control/device_controller/display/probe_registry/0416x5408.yaml`
  and the transport implementation at
  `src/thermalright_lcd_control/device_controller/display/transport.py`
  (class `LyTransport`) if you need to cross-reference the original.
  - One-time handshake: write a fixed 2048-byte packet (`02 FF ... 01 ...`
    + zero padding), read a 512-byte response, expect `resp[0]==3,
    resp[1]==0xFF, resp[8]==1` (best-effort — a mismatch just logs a warning
    and continues, since some firmware variants apparently differ slightly).
  - Frame: JPEG-encode the full image, split into 512-byte chunks (16-byte
    header + 496 bytes data), pad chunk count to a multiple of 4, batch into
    4096-byte USB bulk writes, then read one 512-byte ACK.
  - **No partial/region update exists in this protocol** — confirmed by
    reading the reference implementation's full call chain, not assumed.
    Every update replaces the entire screen. This is a materially different
    model from the `LCD` project's two panels, which both support a
    "set window" command for redrawing just a small changed region.
  - Per-chunk 16-byte header layout (all implemented in `LyPanel._build_chunks`
    in `lcd_therma_stats.py`):
    ```
    [0]      0x01
    [1]      0xFF
    [2:6]    total payload size (LE32)
    [6:8]    this chunk's data length (LE16)
    [8]      cmd (1 for this "LY" panel; a related "LY1" variant at PID 0x5409 uses 2)
    [9:11]   total number of chunks (LE16)
    [11:13]  chunk index (LE16)
    [13:16]  zero padding
    ```

## Verifying it still works

```bash
cd /home/craig/projects/lcd_therma
sudo ./venv/bin/python -c "
from lcd_therma_stats import LyPanel, render_frame
panel = LyPanel()
panel.open()
frame = render_frame({'cpu': '1%', 'mem': '2%'})
panel.send_image(frame)
panel.close()
print('OK')
"
```
(`sudo` needed until the udev rule from `lcd_therma.rules` is installed.)

## External dependencies (shared with the `LCD` project, same paths)

- Discord bot token from `/home/craig/projects/hanger-bot/.env`
- BeatMyLanding admin secret from `/home/craig/projects/beatmylanding/api/.env`
- BeatMyLanding API at `http://localhost:4001`
- YouTube API key / TikTok usernames from this project's own `.env`

If those services/credentials are unavailable, the script keeps running and
just shows `--`/stale values for those rows (same fallback behavior as the
original project).

## Background context worth knowing

- This came out of a long session where Craig first swapped his original
  no-name panel for a Turing/TURZX 3.5" panel (documented in the `LCD`
  project — see its `README.md` and memory notes), then went down a
  significant side-quest trying to dump/rebrand that panel's firmware
  (paused, see `LCD/FIRMWARE_DUMP_PLAN.md` — resuming after his holiday,
  unrelated to this project but same person/hardware family).
- The 9" Thermalright panel was identified fresh in that same session:
  confirmed via `lsusb`/`dmesg` as Winbond `0416:5408`, then matched to the
  `thermalright-lcd-control` open-source project which had explicit,
  documented support for this exact device — that's what made this a
  same-day build rather than another reverse-engineering slog like the first
  panel.
