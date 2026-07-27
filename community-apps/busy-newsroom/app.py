#!/usr/bin/env python3
"""Busy Newsroom: scroll live RSS headlines across a BUSY Bar.

    python app.py
    python app.py --host 127.0.0.1:8088
    python app.py --feed https://feeds.npr.org/1001/rss.xml --source NPR
"""
import argparse
import html
import json
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

APP = "busy-newsroom"
DEFAULT_FEED = "https://feeds.bbci.co.uk/news/rss.xml"


def clean(value):
    return " ".join(html.unescape(value or "").split())


def headlines(url, limit):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "busy-newsroom/1.0",
            "Accept": "application/rss+xml, application/atom+xml, application/xml",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        root = ET.fromstring(response.read())
    items = root.findall(".//item")
    if items:
        return [clean(item.findtext("title")) for item in items[:limit] if clean(item.findtext("title"))]
    atom = "{http://www.w3.org/2005/Atom}"
    return [clean(entry.findtext(atom + "title")) for entry in root.findall(".//" + atom + "entry")[:limit]
            if clean(entry.findtext(atom + "title"))]


def draw(base, source, headline):
    payload = {
        "application_name": APP,
        "priority": 50,
        "elements": [
            {
                "id": "source",
                "type": "text",
                "text": source.upper()[:16],
                "x": 1,
                "y": 0,
                "font": "tiny",
                "color": "0xFF7A00FF",
            },
            {
                "id": "headline",
                "type": "text",
                "text": headline[:300],
                "x": 0,
                "y": 7,
                "width": 72,
                "font": "small",
                "color": "0xFFFFFFFF",
                "scroll_rate": 420,
                "scroll_start_delay": 650,
                "scroll_repeat_delay": 1200,
            },
        ],
    }
    req = urllib.request.Request(
        base + "/api/display/draw",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5):
        pass
    sound = urllib.request.Request(
        base + "/api/audio/play",
        data=json.dumps({
            "application_name": APP,
            "stock_path": "shared/calendar_event_starts.snd",
        }).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(sound, timeout=5):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="10.0.4.20", help="BUSY Bar or emulator host")
    parser.add_argument("--feed", default=DEFAULT_FEED, help="RSS or Atom feed URL")
    parser.add_argument("--source", default="NEWS", help="short label shown above the headline")
    parser.add_argument("--interval", type=int, default=14, help="seconds per headline")
    parser.add_argument("--limit", type=int, default=12, help="headlines fetched per refresh")
    args = parser.parse_args()
    base = "http://" + args.host.replace("http://", "").rstrip("/")
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                base + "/api/audio/volume?volume=70&silent=1",
                method="POST",
            ),
            timeout=5,
        ).read()
    except urllib.error.URLError:
        pass

    print(f"{APP} → {base} · {args.feed}  (Ctrl-C to stop)")
    while True:
        stories = headlines(args.feed, max(1, args.limit))
        if not stories:
            raise RuntimeError("feed returned no headlines")
        for story in stories:
            try:
                draw(base, args.source, story)
            except urllib.error.HTTPError as exc:
                if exc.code != 409:
                    raise
                print("display busy (409), retrying...")
            time.sleep(max(3, args.interval))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped.")
    except urllib.error.URLError as exc:
        sys.exit(f"network error: {exc.reason}")
    except (ET.ParseError, RuntimeError) as exc:
        sys.exit(f"feed error: {exc}")
