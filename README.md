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
- **Crypto**: BTC/ETH (GBP, with green/red trend arrows on price moves) with the Crypto Fear & Greed Index number centered under its own label beside them, who's home (Matt/Jordan — see "Household Presence" below), a separator, then weather for Playa del Ingles and Newton Aycliffe
- **BeatMyLanding**: total users/online/currently flying, new users/landings today, latest traffic event, Search Console clicks/impressions (7d)
- **Social**: Discord online/members, YouTube subscribers/total views, TikTok new/old account followers, AdSense earnings (today/yesterday)

Background is a subtle diagonal gradient with a soft corner vignette, built once and cached rather than recomputed per frame.

## Brightness / Power Saving

Rendered frames are dimmed to `LCD_BRIGHTNESS_FACTOR` (default `0.7`) before encoding - this also fixed a panel-internal reboot issue (Thermalright boot logo replaying with zero trace at the USB/kernel level), which appears to be caused by peak backlight draw browning out the panel's own power regulation at full brightness.

On top of that, the display drops to `LCD_QUIET_BRIGHTNESS_FACTOR` (default `0.0`, fully black) whenever **either**:

- It's within the quiet-hours window - `LCD_QUIET_START` to `LCD_QUIET_END` (default `23:59`-`06:00`, wraps past midnight), or
- The phone at `LCD_PHONE_IP` (default `192.168.1.12`) hasn't answered a ping in `LCD_PHONE_AWAY_AFTER_MISSES` consecutive checks (default 5, checked every `LCD_PHONE_CHECK_SECONDS` = 20s, so ~100s) - debounced that direction only, so a WiFi power-save gap doesn't blank the screen; coming back home isn't debounced, a single successful ping restores normal brightness immediately.

The service keeps running and updating throughout either condition - it's rendering black content, not stopped - so it recovers instantly with no restart needed.

## Household Presence (Matt/Jordan)

The crypto column shows Home/Away for two more phones, purely informational (doesn't affect brightness like the check above does):

- **Jordan** (`LCD_JORDAN_PHONE_IP`, default `192.168.1.14`) - plain main-LAN device, checked with a normal ping.
- **Matt** (`LCD_MATT_PHONE_IP`/`LCD_MATT_PHONE_IP_ALT`, default `192.168.52.100`/`192.168.52.29`) - lives on the router's isolated "Lodger" guest network (a separate subnet, its own DHCP scope), not the main LAN. Two IPs are checked because the DHCP reservation for his phone was pointing it at `.100` but it hadn't yet done a full DHCP renegotiation to pick that up, so it can currently answer on either.

**Both default to Away, not Home, until an actual successful check proves otherwise** - and that flip happens fast (a single successful ping, no debounce), while going the other way to Away requires `LCD_HOUSEHOLD_AWAY_AFTER_MISSES` consecutive misses (default 3, checked every `LCD_HOUSEHOLD_CHECK_SECONDS` = 30s, so ~90s). Defaulting to Away means a restart briefly shows Away for someone who's actually home (self-corrects in a couple of seconds) rather than falsely showing Home for up to 90s for someone who isn't - the opposite default previously made an already-away Jordan look like a bug every time the service restarted for an unrelated reason.

**Guest network isolation gotcha**: by design, devices on the main LAN (where this box lives) cannot ping devices on an isolated guest/SDN subnet - the router's own guest-isolation firewall chain (`SDN_IA` on this ASUS/Merlin router, a blanket `DROP` between any two bridge interfaces) blocks it, and no amount of picking a different target IP fixes that. Getting Matt's presence check working required a narrow router-side exception: a persistent script at `/jffs/scripts/firewall-start` on the router (needs "Enable JFFS custom scripts and configs" turned on in the router's admin UI) that inserts an ICMP-only `ACCEPT` rule scoped to just this LCD box's IP and Matt's two possible guest IPs, ahead of the isolation `DROP` rule. That script lives on the router, not in this repo - if Matt's presence check ever stops working after a router factory reset or migration to different hardware, that's the first thing to recreate.

## Project Files

- `lcd_therma_stats.py` - main display renderer, USB transport (`LyPanel`), and data fetchers
- `lcd_therma.service` - systemd unit for running the display at boot
- `lcd_therma.rules` - udev rule so the panel is writable by a normal user, not just root
- `scripts/lcd-network-counters-setup` - live nftables LAN/WAN counter setup used by the shared writer service
- `*_logo.png` - icons rendered on the display (`bml_logo.png` rasterized from BeatMyLanding's favicon SVG via `cairosvg`, one-time build step, not a runtime dependency)
- `.env.example` - optional environment variables
- `requirements.txt` - Python dependencies
- `HANDOVER.md` - detailed original build notes/context

Runtime files such as `lcd_therma.log`, the virtualenv, and Python cache files are intentionally ignored by git.

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

4. If the panel flashes its own Thermalright boot logo and then recovers on its own with **zero corresponding error anywhere** (log, `dmesg`, USB events) — this had an extended investigation (see [issue #281](https://github.com/Lexonight1/thermalright-trcc-linux/issues/281) filed against the more thoroughly reverse-engineered `trcc-linux` project). Three real causes were found along the way: a `set_configuration()` bug that caused a genuine reopen storm (fixed), an underpowered bus-powered USB hub in the cable path (this panel wants up to 500mA — fixed by removing the hub, and confirmed it wasn't purely a power issue since it recurred even on a genuinely powered hub), and — the current leading suspect — **sending frames at 1920x480 when the panel's firmware actually expects 1920x462** (see Panel / Protocol above). That's now fixed (`HEIGHT = 462`) but not yet confirmed to be the actual root cause versus another coincidental improvement, the same way the earlier fixes each seemed to help before the issue resurfaced. If it happens again post-fix, the log carries diagnostics to check: every `Frame sent OK` line includes the frame's mean brightness (`luma=X/255`), the handshake logs the panel's PM/SUB identity bytes, and the frame ACK's content (not just its length) is logged whenever it changes.
