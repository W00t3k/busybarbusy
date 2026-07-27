# BUSYBARBUSY

> A local-first command center for the BUSY Bar.

Turn the 72×16 display into a live information surface—with RSS, publisher
icons, a flip clock, network intelligence, direct messages, physical-button
workflows, and one unified Bar Hub.

## What it does

- Pushes the newest enabled RSS headline to the BUSY Bar on demand
- Uses publisher favicons for built-in feeds and a tiny white RSS fallback for custom feeds
- Rotates multiple sources or pins one favorite feed
- Colors the LED strip by freshness: green, amber, orange, slate, or gray
- Supports one-click per-source display, preview-only refreshes, and scheduled runs
- Includes a retro flip clock and local network views
- Includes **Bar Hub**, a dedicated command center for apps, automations,
  display composition, activity, and device transports
- Runs without third-party Python packages

## Quick start

Requires Python 3.9 or newer.

```sh
git clone https://github.com/W00t3k/busybarbusy.git
cd busybarbusy
./run.sh
```

The launcher creates `.venv` on first run. Open the interfaces:

- **Bar Hub:** <http://localhost:8090/hub>
- **Virtual Staging:** <http://localhost:8090/staging>
- **Classic feed control:** <http://localhost:8090>
- **Network Hub:** <http://localhost:8315>
- **BUSY Bar Emulator:** <http://localhost:8088>

Configure your BUSY Bar connection, enable the sources you want, and choose an action:

- **Push RSS** fetches enabled feeds and immediately sends the current headline
  to the bar.
- **Next** advances to the next loaded headline.
- **Refresh** fetches a preview without changing the display.
- **Show** pushes one specific source.
- **Display Studio** sends an operator-authored scrolling message using the
  same firmware-tested renderer as the feed ticker.

For reliable physical START/STOP control on macOS, install the included
LaunchAgent so exactly one controller stays alive:

```sh
cp com.busybarbusy.service.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.busybarbusy.service.plist
```

The service claims port `8090` before starting device workers, preventing
duplicate processes from competing for the bar.

The Bar Hub also detects the firmware-compatible
[BUSY Bar Emulator](https://github.com/maxswinkels/busybar-emulator) on port
`8088` and links directly to its app runner and capture tools. The included
`com.busybarbusy.emulator.plist` keeps that separate service available without
conflicting with applications already using port `8080`.

Virtual Staging is its own pop-out workspace rather than an embedded dashboard
panel. **Preview RSS** renders Newsroom virtually; **Push current RSS** atomically selects that
same app when needed, copies the currently visible headline to the configured device,
and stops the background clock, RSS rotation, and network sequence first so
they cannot immediately reclaim the display.

Settings are saved to `config.json`. That file is intentionally ignored because
it can contain device, router, and API credentials.

Router access prefers a saved CR1000A `sysauth` session token and keeps that
single session alive. The admin password is used only to bootstrap a replacement
token when no valid session exists.

## Pixel feed icons

Every source gets a compact icon suited to the BUSY Bar display. Built-in
publishers use locally bundled derivatives of their official favicons, while
all WIRED feeds retain the full tiled wordmark with category-specific
colorways. Any feed you add receives a tiny white RSS glyph. The same asset is
used in the web source list and uploaded to the physical display.

## Distributable apps

Standalone, community-gallery-ready apps live in
[`community-apps`](community-apps/). **Busy Newsroom** is the first packaged
release: it has no dependencies, accepts any RSS or Atom URL, targets a real
bar or the emulator with `--host`, and includes a real 720×160 emulator
preview.

## Display behavior

The default device address is `http://192.168.2.199`. Priority `50` lets normal
built-in apps replace the ticker but does not interrupt an active BUSY/CUSTOM
session at priority `90`. Use priority `90` or higher only when interruption is
intentional.

Headlines can include source, age, and queue position:

```text
KREBS | Patch Tuesday fixes 137 flaws | 2h | 3/16
```

Disable `show_meta` for a bare headline. In `freshness` LED mode, stories under
an hour are green, under six hours amber, under a day orange, older stories
slate, and undated stories gray. Use `fixed` mode for one constant LED color.

## Configuration

Environment variables:

- `PORT` — dashboard port (default `8090`)
- `BUSY_RSS_CONFIG` — alternate settings file path

## HTTP API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/config` | Configuration and last-run status; secrets are omitted |
| `POST` | `/api/config` | Save configuration |
| `GET` | `/api/feeds` | Feed catalogue, state, headlines, and icon URLs |
| `POST` | `/api/preview` | Fetch and parse enabled feeds without changing the display |
| `POST` | `/api/refresh` | Fetch enabled feeds and push the selected headline |
| `POST` | `/api/show` | Push one selected source |
| `POST` | `/api/message` | Push a direct 72×16 message from Bar Hub |
| `GET` | `/api/inputs` | Recent raw physical-control events for gesture mapping |
| `POST` | `/api/inputs/clear` | Clear the physical input trace |
| `GET` | `/api/logs` | Recent fetch, display, timing, and error logs |

Logs rotate automatically at 1 MB with three backups. Feed text is normalized
to printable ASCII for BUSY Bar bitmap-font compatibility. Keep the service
running for scheduled updates and physical-button actions.
