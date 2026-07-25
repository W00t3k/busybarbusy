# Busy RSS

A small, dependency-free RSS/Atom reader for the LaMetric BUSY Bar HTTP API. It shows a clean feed label and one scrolling headline at a time through `/api/display/draw`. It does not use or change the BUSY timer.

## Run

Requires Python 3.9 or newer.

```sh
./run.sh
```

The launcher creates `.venv` on first run and executes the service with that environment's Python.

Open <http://localhost:8090>, enter a feed URL, preview it, and click **Show now**. Enable **Run automatically** when the display looks right. Settings are saved to `config.json` (ignored by Git because it may contain the API key).

The default device address is `http://192.168.2.199`. Priority 50 allows normal built-in apps to be replaced but does not interrupt an active BUSY/CUSTOM session, whose priority is 90. Use priority 90 or higher only if interruption is intended.

Each headline scrolls as `SOURCE | title | age | position/total`, for example `KREBS | Patch Tuesday fixes 137 flaws | 2h | 3/16`. Set `show_meta` to `false` to display the bare headline.

The LED strip is colour-coded by item age when `led_mode` is `freshness` (the default): green under an hour, amber under six hours, orange within a day, slate for older items, and grey when the feed publishes no date. Set `led_mode` to `fixed` to use the single `led_color` value instead.

Environment variables:

- `PORT`: web UI port (default `8090`)
- `BUSY_RSS_CONFIG`: alternate settings file path

## API

- `GET /api/config` — configuration and last-run status (never returns the API key)
- `POST /api/config` — save configuration
- `POST /api/preview` — fetch and parse the feed without touching the display
- `POST /api/refresh` — fetch and show the current headlines
- `GET /api/logs` — recent fetch, display, duration, and error logs for every feed

Logs are written to `busy-rss.log` with automatic rotation at 1 MB (three backups).

RSS content is normalized to printable ASCII because BUSY Bar bitmap fonts do not accept Unicode. The service must stay running for scheduled updates.
