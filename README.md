# Trofeo Vision LCD Stats Display

Python service for a Thermalright Trofeo Vision 9.16" USB-C LCD panel (marketed as 1920x480; the actual wire-protocol frame size is 1920x462 — see Panel / Protocol below). It renders system stats and live service counters into a full-frame image, JPEG-encodes it, and pushes it to the panel over `pyusb` using the vendor's "LY" bulk transport protocol.

Spun off from the sibling [`LCD`](../LCD) project, which drives Craig's original 3.5" panel — the data-fetching logic (crypto prices, BeatMyLanding, Discord, YouTube, TikTok, system stats) is shared/ported from there, but the rendering is a fresh landscape layout designed for this panel's much larger, wider screen.

## Panel / Protocol

- **Panel**: Thermalright Trofeo Vision 9.16" ultrawide, marketed/branded as 1920x480, USB-C.
- **Actual wire resolution: 1920x462, not 1920x480.** The panel's own firmware handshake identifies it as PM byte 65 (`64 + resp[20]`), and the vendor's own Windows software (decompiled by the [`thermalright-trcc-linux`](https://github.com/Lexonight1/thermalright-trcc-linux) project) encodes and sends exactly 1920x462 for that PM value — confirmed in their `protocol.py` device table (`65: (1920, 462)`), reverse-engineered from the real `USBLCDNEW.dll`. This project rendered at 1920x480 (the marketed spec) for weeks before that mismatch was found; sending 18 rows taller than the panel's firmware expects is the leading suspect for a long-standing, still-not-fully-confirmed intermittent internal reboot (Thermalright boot logo replaying with zero trace anywhere at the USB/kernel/application level — see Troubleshooting below). `WIDTH`/`HEIGHT` in `lcd_therma_stats.py` are now `1920`/`462`.
- **USB ID**: `0416:5408` (Winbond Electronics Corp., product string "USBDISPLAY"). Vendor-specific USB class with two bulk endpoints — **not** a CDC/serial device, no `/dev/ttyACM*` node. Uses `pyusb` directly.
- **Endpoints**: `0x81` (bulk IN), `0x09` (bulk OUT).
- **Transport**: reverse-engineered from the open-source [`thermalright-lcd-control`](https://github.com/rejeb/thermalright-lcd-control) project. One-time handshake (fixed 2048-byte packet, expects a specific 512-byte ACK pattern), then every frame is JPEG-encoded, split into 512-byte chunks (16-byte header + 496 bytes data), and sent as 4096-byte USB bulk writes.
- **No partial/region updates** — unlike the `LCD` project's panels, this protocol has no "set window" command. Every update replaces the entire screen, so the code only re-encodes and sends when the rendered state actually changes (`state != last_sent_state` guard in the main loop).

## Layout

Four columns across the full 1920x462 canvas (the actual wire resolution — see Panel / Protocol above), each column's rows vertically centered to use the whole height rather than clustering at the top:

- **System**: CPU/Load, SWAP/MEM, TEMP/DISK, Ping (8.8.8.8)/Uptime, LAN/WAN throughput
- **VPS**: SidePhaseStudio VPS CPU/load, swap/memory, temperature/disk, TCP latency/uptime, RX/TX throughput
- **Crypto**: BTC/ETH (GBP, with green/red trend arrows on price moves) with the Crypto Fear & Greed Index number centered under its own label beside them, who's home (see "Household Presence" below), a separator, then weather for Playa del Ingles and Newton Aycliffe
- **Social**: Discord online/members, YouTube subscribers/total views, TikTok new/old account followers, AdSense earnings (today/yesterday)

Background is a subtle diagonal gradient with a soft corner vignette, built once and cached rather than recomputed per frame.

Brevo daily usage appears in screen two's third column as `used/300` and
refreshes once at startup and every 10 minutes from `GET /v3/account`, using the
`api-key` header with `BREVO_API_KEY` from the service environment or the existing
BeatMyLanding `api/.env`. The free `sendLimit` plan's remaining `credits` are
subtracted from the 300 daily cap; API rate-limit headers are not email usage.
This read-only request sends no email. Missing or failed responses keep the last
successful count, or `--/300` until the first successful fetch.

VPS stats stream every five seconds over one persistent SSH connection to
`uk.sidephasestudio.com` as `craig`. The local `vps_metrics.py` sampler is piped
to the remote Python interpreter; nothing is installed or written on the VPS.
SSH keepalives detect dropped connections, missing readings trigger a reconnect
after 15 seconds, and failed connections are retried after five seconds.
CPU and network rates use a one-second sample on the default-route interface.
Temperature is `--` when no sensor is exposed. `TCP 8.8.8.8` measures connection
latency to port 443, since this VPS has no ICMP ping utility. Failed SSH samples
are logged and the last successful readings remain displayed.

## Second Panel

The second panel (`2025E7B071A9`) uses the same background with three columns.
The first uses the Global Vectors logo beside the registered-driver label,
matching the compact BML logo treatment, and shows registered drivers, approved
drivers, and drivers awaiting access (`not_approved`). The middle column shows
BeatMyLanding total users/online/flying, new users/landings today, latest
traffic and Search Console clicks/impressions using the existing live feeds.
The third column shows Brevo daily usage, SMTP daily submissions and nonempty or stale unread inboxes. Below the driver counts, the first column shows server players,
CPU, memory (MB), incoming/outgoing traffic (kbps), and worst loss from
`POST https://globalvectors.app/api/admin/server-totals`; partial results are
marked below the figures. Counts refresh every 15 seconds from the server-totals
and `POST https://globalvectors.app/api/admin/driver-counts` endpoints; both use
`GLOBAL_VECTORS_ADMIN_TOKEN` from the local `.env` in the JSON `token` field.
Failed requests retain the last successful values, or show `--` before the
first successful fetch. Never commit the token.

Global Vectors Discord online/member counts appear below the server figures.
They refresh every 60 seconds for guild `1559305847874650194`, using Luke's
existing token read from `/home/craig/.openclaw/openclaw.json`. The LCD makes
read-only API requests; it does not change or run another Discord bot.
The original panel continues using HangerBot for its own Discord server.

The second panel stays at 0.5 image brightness and is rotated 180 degrees.
The current installation also sets `LCD_BRIGHTNESS_FACTOR=0.5` in its private
`.env` for the original panel; credentials and local settings remain untracked.
Its background alone is darkened a further 40%; text and divider colours stay unchanged.
Both panels use the existing service, quiet-hours rules, and serial-number
selection; the original (`2025E770099A`) retains its four-column stats layout.

## Brightness / Power Saving

Rendered frames are dimmed to `LCD_BRIGHTNESS_FACTOR` (default `0.7`) before encoding - this also fixed a panel-internal reboot issue (Thermalright boot logo replaying with zero trace at the USB/kernel level), which appears to be caused by peak backlight draw browning out the panel's own power regulation at full brightness.

On top of that, the display drops to `LCD_QUIET_BRIGHTNESS_FACTOR` (default `0.0`, fully black) whenever **either**:

- It's within the quiet-hours window - `LCD_QUIET_START` to `LCD_QUIET_END` (default `23:59`-`06:00`, wraps past midnight), or
- The phone at `LCD_PHONE_IP` (default `192.168.1.12`) hasn't answered a ping in `LCD_PHONE_AWAY_AFTER_MISSES` consecutive checks (default 5, checked every `LCD_PHONE_CHECK_SECONDS` = 20s, so ~100s) - debounced that direction only, so a WiFi power-save gap doesn't blank the screen; coming back home isn't debounced, a single successful ping restores normal brightness immediately.

The service keeps running and updating throughout either condition - it's rendering black content, not stopped - so it recovers instantly with no restart needed.

## Household Presence

The crypto column shows Home/Away for two people's phones, purely informational (doesn't affect brightness like the check above does). Both people's names and IPs are configured entirely via `.env` (`LCD_PERSON1_NAME`/`LCD_PERSON1_IP`/`LCD_PERSON1_IP_ALT` and `LCD_PERSON2_NAME`/`LCD_PERSON2_IP` — see `.env.example`), not hardcoded or committed to this repo. Leaving a person's IP blank disables their check (shows `--`).

`LCD_PERSON1_IP_ALT` can track a second phone. Both addresses are checked each time; either responding means Home. `LCD_PERSON1_DEVICE` and `LCD_PERSON1_DEVICE_ALT` name the phones in smaller text beneath the status, showing only the phones that responded to the latest check. The Home/Away status still uses the miss debounce below.

**Both default to Away, not Home, until an actual successful check proves otherwise** - and that flip happens fast (a single successful ping, no debounce), while going the other way to Away requires `LCD_HOUSEHOLD_AWAY_AFTER_MISSES` consecutive misses (default 3, checked every `LCD_HOUSEHOLD_CHECK_SECONDS` = 30s, so ~90s). Defaulting to Away means a restart briefly shows Away for someone who's actually home (self-corrects in a couple of seconds) rather than falsely showing Home for up to 90s for someone who isn't.

**Guest network isolation gotcha**: by design, devices on the main LAN (where this box lives) cannot ping devices on an isolated guest/SDN subnet - the router's own guest-isolation firewall chain (`SDN_IA` on this ASUS/Merlin router, a blanket `DROP` between any two bridge interfaces) blocks it, and no amount of picking a different target IP fixes that. Getting a guest-network presence check working required a narrow router-side exception: a persistent script at `/jffs/scripts/firewall-start` on the router (needs "Enable JFFS custom scripts and configs" turned on in the router's admin UI) that inserts an ICMP-only `ACCEPT` rule scoped to just this LCD box's IP and the guest-network phone's two possible IPs, ahead of the isolation `DROP` rule. That script lives on the router, not in this repo - if that presence check ever stops working after a router factory reset or migration to different hardware, that's the first thing to recreate.

## Project Files

- `lcd_therma_stats.py` - main display renderer, USB transport (`LyPanel`), and data fetchers
- `lcd_therma.service` - systemd unit for running the display at boot
- `lcd_therma.rules` - udev rule so the panel is writable by a normal user, not just root
- `scripts/lcd-network-counters-setup` - live nftables LAN/WAN counter setup used by the shared writer service
- `*_logo.png` - icons rendered on the display (`bml_logo.png` rasterized from BeatMyLanding's favicon SVG via `cairosvg`, one-time build step, not a runtime dependency)
- `.env.example` - optional environment variables
- `requirements.txt` - Python dependencies
- `vps_metrics.py` - remote sampler streamed over the existing SSH connection
- `stalwart_metrics.py` - persistent daily SMTP accounting and private credential setup
- `unread_mail.py` - read-only JMAP inbox counts and private mailbox setup
- `test_*.py` - runnable checks for presence, VPS, mail and rendering
- `AGENTS.md` - guidance for maintaining and deploying this project
- `HANDOVER.md` - current handover followed by historical build notes

Runtime files such as `.smtp-daily.json`, `.env.mailboxes.json`, `lcd_therma.log`, the virtualenv, and Python cache files are intentionally ignored by git.

## Setup

```bash
cd /home/craig/projects/lcd_therma
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
```

Optional local config:

```bash
cp .env.example .env
```

`.env` only needs `YOUTUBE_API_KEY`/`YOUTUBE_CHANNEL_ID` and TikTok usernames (which already have sane defaults) — Discord and BeatMyLanding credentials are read directly from the sibling projects' own `.env` files (see External Integrations below).

### udev rule (required for non-root access)

The panel is owned `root:root` by default. Install the udev rule once so a normal user can open it:

```bash
sudo cp lcd_therma.rules /etc/udev/rules.d/99-lcd-therma.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## Run Manually

```bash
cd /home/craig/projects/lcd_therma
./venv/bin/python lcd_therma_stats.py
```

(Needs `sudo` if the udev rule above hasn't been installed yet.)

## Install As A Service

```bash
sudo cp lcd_therma.service /etc/systemd/system/lcd_therma.service
sudo systemctl daemon-reload
sudo systemctl enable --now lcd_therma.service
```

Runs as `User=craig` — requires the udev rule to be installed first.

The existing display process waits for valid DNS and outbound HTTPS before it
opens the panel and schedules its first data fetches. `network-online.target`
can be reached while the router/WAN is still coming back after a reboot;
without this gate, long-refresh sources such as YouTube, TikTok, weather,
Bitcoin, AdSense, and Search Console can stay blank until their next scheduled
refresh. No helper service or persistent second process is used. The check URL
and retry delay can be overridden with `LCD_WAN_CHECK_URL` and
`LCD_WAN_RETRY_SECONDS`.

Logs are written to:

```text
/home/craig/projects/lcd_therma/lcd_therma.log
```

Useful checks:

```bash
systemctl status lcd_therma.service --no-pager
tail -80 /home/craig/projects/lcd_therma/lcd_therma.log
lsusb -d 0416:5408
```

## External Integrations

Unread Mail hides inboxes with a confirmed zero unread count and hides the list entirely when all ten are empty. Failed or not-yet-loaded inboxes remain visible so an unavailable count is not mistaken for an empty inbox.

- **Unread Mail**: screen 2's third column, beneath the Brevo and SMTP counters; there is no separate page or timed page rotation. Screen 1 is unchanged. At startup and every 10 minutes, background workers authenticate separately to the ten `support@` inboxes, discover their mail account IDs and API URL through the JMAP session, then request only `role` and `unreadEmails` with `Mailbox/get`. Only the `inbox` role counts: not Junk, Trash or aliases. Confirmed zero counts are hidden; failed inboxes retain their last value with `Stale`, or show `—` before their first success. These are unread message counts, not thread counts.
  Run `/home/craig/projects/lcd_therma/venv/bin/python /home/craig/projects/lcd_therma/unread_mail.py` in your own Lenovo terminal. The ten support addresses are prefilled from `unread_mail.DOMAINS`; enter their dedicated mailbox passwords at its hidden prompts. Each login is verified live before being atomically saved to `.env.mailboxes.json` (mode `0600`, gitignored); setup resumes with already verified entries. No Prometheus credentials are reused. HTTPS session redirects and the discovered API URL must stay on `uk.sidephasestudio.com`; redirects never forward credentials elsewhere. The app reloads this private file on each refresh, so adding or repairing mailbox credentials does not require another restart. Missing credentials show `—` and `Stale` for that inbox.

- **Stalwart SMTP**: screen 2, column 3, below Brevo. Fetches the authenticated HTTPS Prometheus endpoint every 60 seconds in the existing background scheduler. Sums `queue_authenticated_message_queued` across mailboxes and persists increments in `.smtp-daily.json` to show accepted SMTP submissions today in Europe/London time (including Brevo relays), not delivery confirmations. LCD restarts preserve the count; observed Stalwart counter resets are handled. The first day shows `Today from HH:MM` because earlier submissions cannot be reconstructed. Day boundaries have up to one poll interval of uncertainty; sends before an unobserved Stalwart restart cannot be recovered. Failed checks retain the last count with `Stale`; before a successful check the count is `—`.
  Run `/home/craig/projects/lcd_therma/venv/bin/python /home/craig/projects/lcd_therma/stalwart_metrics.py` in a terminal on Lenovo to enter the Basic authentication password invisibly. The helper verifies the live endpoint as `stalwart-metrics`, then atomically saves `STALWART_METRICS_PASSWORD` in the existing service `.env` with mode `0600`. Restart `lcd_therma.service` after changing it. Never pass the password as a command argument or paste it into chat.

- **BeatMyLanding API** at `http://localhost:4001` (admin secret from `/home/craig/projects/beatmylanding/api/.env`)
- **Discord bot token** from `/home/craig/projects/hanger-bot/.env`
- **YouTube Data API** key/channel from this project's own `.env`
- **TikTok** — public profile page scraping, no auth
- **CoinGecko** — BTC/ETH prices, no auth
- **Crypto Fear & Greed Index** ([alternative.me](https://alternative.me/crypto/fear-and-greed-index/)) — no auth
- **Open-Meteo** — weather, no auth, no API key
- **Google AdSense Management API** and **Search Console API** — OAuth via `~/.config/gsc/oauth-client.json`, refresh tokens in `~/.config/gsc/adsense-token.json` and `~/.config/gsc/token.json` (shared with the `seo-tools` project's `adsense-check.mjs`/`seo-check.mjs`). The OAuth app is published to production so these refresh tokens don't expire on Google's 7-day Testing-mode timer.

If any of these services or credentials are unavailable, the display keeps running and shows `--`/stale values for the affected rows rather than crashing.

## LAN/WAN Counters

The display reads split LAN/WAN traffic counters from `/run/lcd-network-counters.json`, written by `lcd-network-counters-writer.service`.

The live setup script is mirrored in `scripts/lcd-network-counters-setup`. It classifies both direct host traffic and Docker-forwarded traffic, so LAN clients using Docker-published services count against LAN rather than WAN.

## Troubleshooting

If the screen stays blank:

1. Check the device is visible and has the right permissions:

   ```bash
   lsusb -d 0416:5408
   ls -l /dev/bus/usb/*/*   # find the matching node, should be crw-rw-rw-
   ```

   If it's not `crw-rw-rw-`, the udev rule likely isn't installed — see Setup above.

2. Check the service log:

   ```bash
   tail -80 /home/craig/projects/lcd_therma/lcd_therma.log
   ```

3. USB errors mid-run (unplug/replug, power event) are caught and retried automatically — the service closes and reopens the panel handle every 2s until it reconnects, rather than crash-looping. If the panel is wedged rather than just momentarily gone (soft reopen keeps failing), after `LCD_RESET_AFTER_FAILURES` consecutive failures (default 5) it escalates to an actual USB port reset (`USBDEVFS_RESET`, the same recovery a physical unplug/replug gives you) before continuing to retry.

4. If the panel flashes its own Thermalright boot logo and then recovers on its own with **zero corresponding error anywhere** (log, `dmesg`, USB events) — this had an extended investigation (see [issue #281](https://github.com/Lexonight1/thermalright-trcc-linux/issues/281) filed against the more thoroughly reverse-engineered `trcc-linux` project). Several real causes were found along the way: a `set_configuration()` bug that caused a genuine reopen storm (fixed), an underpowered bus-powered USB hub in the cable path (this panel wants up to 500mA — fixed by removing the hub, and confirmed it wasn't purely a power issue since it recurred even on a genuinely powered hub), sending frames at 1920x480 when the panel's firmware actually expects 1920x462 (fixed, `HEIGHT = 462`, see Panel / Protocol above) — and confirmed still recurring after that fix, with log analysis showing no USB errors, reopens, or ACK anomalies anywhere near an occurrence, which pointed at the actual root cause: **`thermalright-trcc-linux`'s own CLI docs state that Bulk/LY firmware (the family this panel's `0416:5408` belongs to) "reverts to the built-in logo after ~2-3s without a frame"** — their own workaround is a dedicated `display keepalive` command that resends the last frame every 0.150s by default. This project's change-detection guard (skip the send when on-screen content hasn't changed, since a full send is a full JPEG-encode + full-frame push) could leave gaps of a tick or more with no frame going out at all, and even a single `SAMPLE_SECONDS` tick was sitting right at that 2-3s edge with no margin for encode/USB-write jitter on top. Fixed by: `LyPanel.resend_last()` cheaply rewrites the last already-encoded frame's wire bytes (no re-encode) whenever a tick's content hasn't changed, so a frame goes out every tick no matter what (`KEEPALIVE_SECONDS`, default 1.0s); `SAMPLE_SECONDS` also dropped from 2.0 to 1.0 for headroom. Not yet time-confirmed, the same way each earlier fix looked promising before the issue resurfaced — if it still happens after this, the diagnostics below remain the way to check: every `Frame sent OK`/`Keepalive resent OK` line includes the frame's mean brightness (`luma=X/255`), the handshake logs the panel's PM/SUB identity bytes, and the frame ACK's content (not just its length) is logged whenever it changes.

## Verification and publishing

Run the lightweight checks without opening the USB panels or sending mail:

```bash
for test in test_*.py; do ./venv/bin/python "$test" || break; done
git diff --check
```

After an approved runtime change, restart `lcd_therma.service` and verify the
log shows successful panel frames and the affected feed update. Preserve
`.smtp-daily.json` across deployments: losing it starts another partial day.
Review the entire staged diff before publishing; private configuration, logs,
mailbox passwords and generated previews must stay out of GitHub.
