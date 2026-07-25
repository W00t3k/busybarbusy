# BUSYBARBUSY

> A tiny RSS command center for the LaMetric BUSY Bar.

Turn RSS and Atom feeds into a live, pixel-perfect headline ticker—with source
icons, freshness-colored LEDs, a flip clock, and direct control from a polished
local dashboard.

## What it does

- Pushes the newest enabled RSS headline to the BUSY Bar on demand
- Uses publisher favicons for built-in feeds and a tiny white RSS fallback for custom feeds
- Rotates multiple sources or pins one favorite feed
- Colors the LED strip by freshness: green, amber, orange, slate, or gray
- Supports one-click per-source display, preview-only refreshes, and scheduled runs
- Includes a retro flip clock and local network views
- Runs without third-party Python packages

## Quick start

Requires Python 3.9 or newer.

```sh
git clone https://github.com/W00t3k/busybarbusy.git
cd busybarbusy
./run.sh
```

The launcher creates `.venv` on first run. Open <http://localhost:8090>, configure
your BUSY Bar connection, enable the sources you want, and choose an action:

- **Push RSS** fetches enabled feeds and immediately sends the current headline
  to the bar.
- **Next** advances to the next loaded headline.
- **Refresh** fetches a preview without changing the display.
- **Show** pushes one specific source.

Settings are saved to `config.json`. That file is intentionally ignored because
it can contain device, router, and API credentials.

## Pixel feed icons

Every source gets a compact icon suited to the BUSY Bar display. Built-in
publishers use locally bundled derivatives of their official favicons; any feed
you add receives a tiny white RSS glyph. The same asset is used in the web
source list and uploaded to the physical display.

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
| `GET` | `/api/logs` | Recent fetch, display, timing, and error logs |

Logs rotate automatically at 1 MB with three backups. Feed text is normalized
to printable ASCII for BUSY Bar bitmap-font compatibility. Keep the service
running for scheduled updates and physical-button actions.
