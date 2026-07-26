#!/usr/bin/env python3
"""Dependency-free RSS-to-BUSY Bar service."""

from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import html
import http.cookiejar
import json
import logging
from logging.handlers import RotatingFileHandler
import math
import os
import re
import shutil
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple, Optional

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ.get("BUSY_RSS_CONFIG", ROOT / "config.json"))
USER_AGENT = "BusyRSS/1.0"
# Some publishers (USOM, Sophos) serve an HTML interstitial to bare feed readers.
FEED_HEADERS = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
LOG_PATH = ROOT / "busy-rss.log"
FEED_ICON_DIR = ROOT / "static" / "feed-icons"
LOGGER = logging.getLogger("busy_rss")
LOGGER.setLevel(logging.INFO)
_log_handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)
_log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
LOGGER.addHandler(_log_handler)

# (source, url, enabled by default). The security set ships on; the newsroom feeds
# recovered from the old Tidbyt config ship off so the rotation stays short.
DEFAULT_FEEDS = [
    ("WIRED", "https://www.wired.com/feed/rss"),
    ("WIRED AI", "https://www.wired.com/feed/tag/ai/latest/rss"),
    ("DARKNET DIARIES", "https://podcast.darknetdiaries.com/"),
    ("GRAHAM CLULEY", "https://grahamcluley.com/feed/"),
    ("KREBS", "https://krebsonsecurity.com/feed/"),
    ("SANS ISC", "https://isc.sans.edu/rssfeed_full.xml"),
    ("SCHNEIER", "https://www.schneier.com/feed/atom/"),
    ("SECURELIST", "https://securelist.com/feed/"),
    ("SOPHOS OPS", "https://news.sophos.com/en-us/category/security-operations/feed/"),
    ("SOPHOS RESEARCH", "https://news.sophos.com/en-us/category/threat-research/feed/"),
    ("THE HACKER NEWS", "https://feeds.feedburner.com/TheHackersNews?format=xml"),
    ("TROY HUNT", "https://www.troyhunt.com/rss/"),
    ("USOM THREATS", "https://www.usom.gov.tr/rss/tehdit.rss"),
    ("USOM NEWS", "https://www.usom.gov.tr/rss/duyuru.rss"),
    ("WELIVESECURITY", "https://feeds.feedburner.com/eset/blog"),
    ("UNLEASHEDFLIP", "https://dev.unleashedflip.com/rss"),
]

# Recovered from the earlier Tidbyt setup. Every URL here was fetched and parsed
# successfully; WIRED Technology, WIRED Backchannel (both 404) and Verge Streaming
# Wars (parses but returns no items) were dropped rather than shipped broken.
RECOVERED_FEEDS = [
    ("HACKER NEWS", "https://news.ycombinator.com/rss"),
    ("WIRED BUSINESS", "https://www.wired.com/feed/category/business/latest/rss"),
    ("WIRED CULTURE", "https://www.wired.com/feed/category/culture/latest/rss"),
    ("WIRED SCIENCE", "https://www.wired.com/feed/category/science/latest/rss"),
    ("WIRED SECURITY", "https://www.wired.com/feed/category/security/latest/rss"),
    ("WIRED IDEAS", "https://www.wired.com/feed/category/ideas/latest/rss"),
    ("WIRED GEAR", "https://www.wired.com/feed/category/gear/latest/rss"),
    ("WIRED GUIDES", "https://www.wired.com/feed/tag/wired-guide/latest/rss"),
    ("NPR TOP", "https://feeds.npr.org/1002/rss.xml"),
    ("NPR NEWS", "https://feeds.npr.org/1001/rss.xml"),
    ("NPR NATIONAL", "https://feeds.npr.org/1003/rss.xml"),
    ("NPR WORLD", "https://feeds.npr.org/1004/rss.xml"),
    ("NPR BUSINESS", "https://feeds.npr.org/1006/rss.xml"),
    ("NPR SCIENCE", "https://feeds.npr.org/1007/rss.xml"),
    ("NPR CULTURE", "https://feeds.npr.org/1008/rss.xml"),
    ("NPR POLITICS", "https://feeds.npr.org/1014/rss.xml"),
    ("NPR ECONOMY", "https://feeds.npr.org/1017/rss.xml"),
    ("NPR TECH", "https://feeds.npr.org/1019/rss.xml"),
    ("NPR RESEARCH", "https://feeds.npr.org/1024/rss.xml"),
    ("NPR ENVIRONMENT", "https://feeds.npr.org/1025/rss.xml"),
    ("NPR SPACE", "https://feeds.npr.org/1026/rss.xml"),
    ("NPR BOOKS", "https://feeds.npr.org/1032/rss.xml"),
    ("NPR MUSIC", "https://feeds.npr.org/1039/rss.xml"),
    ("NPR MOVIES", "https://feeds.npr.org/1045/rss.xml"),
    ("VERGE ANDROID", "https://www.theverge.com/rss/android/index.xml"),
    ("VERGE APPLE", "https://www.theverge.com/rss/apple/index.xml"),
    ("VERGE APPS", "https://www.theverge.com/rss/apps/index.xml"),
    ("VERGE CLIMATE", "https://www.theverge.com/rss/climate-change/index.xml"),
    ("VERGE CRYPTO", "https://www.theverge.com/rss/cryptocurrency/index.xml"),
    ("VERGE CREATORS", "https://www.theverge.com/rss/creators/index.xml"),
    ("VERGE CYBER", "https://www.theverge.com/rss/cyber-security/index.xml"),
    ("VERGE DEALS", "https://www.theverge.com/rss/good-deals/index.xml"),
    ("VERGE DECODER", "https://www.theverge.com/rss/decoder-podcast-with-nilay-patel/index.xml"),
    ("VERGE MUSK", "https://www.theverge.com/rss/elon-musk/index.xml"),
    ("VERGE FACEBOOK", "https://www.theverge.com/rss/facebook/index.xml"),
    ("VERGE FILM", "https://www.theverge.com/rss/film/index.xml"),
    ("VERGE GADGETS", "https://www.theverge.com/rss/gadgets/index.xml"),
    ("VERGE GAMING", "https://www.theverge.com/rss/games/index.xml"),
    ("VERGE GOOGLE", "https://www.theverge.com/rss/google/index.xml"),
    ("VERGE HOTPOD", "https://www.theverge.com/rss/hot-pod-newsletter/index.xml"),
    ("VERGE HOWTO", "https://www.theverge.com/rss/how-to/index.xml"),
    ("VERGE META", "https://www.theverge.com/rss/meta/index.xml"),
    ("VERGE MICROSOFT", "https://www.theverge.com/rss/microsoft/index.xml"),
    ("VERGE POLICY", "https://www.theverge.com/rss/policy/index.xml"),
    ("VERGE REVIEWS", "https://www.theverge.com/rss/reviews/index.xml"),
    ("VERGE SAMSUNG", "https://www.theverge.com/rss/samsung/index.xml"),
    ("VERGE SCIENCE", "https://www.theverge.com/rss/science/index.xml"),
    ("VERGE SPACE", "https://www.theverge.com/rss/space/index.xml"),
    ("VERGE TESLA", "https://www.theverge.com/rss/tesla/index.xml"),
    ("VERGE VERGECAST", "https://www.theverge.com/rss/the-vergecast/index.xml"),
    ("VERGE TIKTOK", "https://www.theverge.com/rss/tiktok/index.xml"),
    ("VERGE TRANSPORT", "https://www.theverge.com/rss/transportation/index.xml"),
    ("VERGE TV", "https://www.theverge.com/rss/tv/index.xml"),
    ("VERGE TWITTER", "https://www.theverge.com/rss/twitter/index.xml"),
    ("VERGE YOUTUBE", "https://www.theverge.com/rss/youtube/index.xml"),
]

CATALOGUE = [(source, url, True) for source, url in DEFAULT_FEEDS] + \
            [(source, url, False) for source, url in RECOVERED_FEEDS]
CATALOGUE_SOURCES = {source for source, _, _ in CATALOGUE}

ALL_FEEDS: list[dict] = []   # every known feed, enabled or not
FEEDS: list[tuple] = []      # (source, url) for enabled feeds only — what the bar rotates


def sync_feeds(config: Config) -> None:
    """Rebuild the feed tables from config, falling back to the shipped catalogue."""
    chosen = {entry["source"]: bool(entry.get("enabled"))
              for entry in (config.feeds or []) if entry.get("source")}
    extra = [(entry["source"], entry["url"], bool(entry.get("enabled")))
             for entry in (config.feeds or [])
             if entry.get("source") and entry.get("url")
             and entry["source"] not in {s for s, _, _ in CATALOGUE}]
    ALL_FEEDS[:] = [{"source": source, "url": url,
                     "enabled": chosen.get(source, default),
                     "stock": True}
                    for source, url, default in CATALOGUE]
    ALL_FEEDS.extend({"source": source, "url": url, "enabled": enabled, "stock": False}
                     for source, url, enabled in extra)
    FEEDS[:] = [(entry["source"], entry["url"]) for entry in ALL_FEEDS if entry["enabled"]]


@dataclass
class Config:
    feed_url: str = "https://feeds.bbci.co.uk/news/rss.xml"
    alternate_feed_url: str = "https://www.wired.com/feed/tag/ai/latest/rss"
    device_url: str = "http://192.168.2.199"
    api_key: str = ""
    router_url: str = "https://192.168.2.1"
    router_username: str = "admin"
    router_password: str = ""
    router_sysauth: str = ""  # reusable authenticated session cookie
    interval_minutes: int = 15
    item_seconds: int = 12
    max_items: int = 5
    priority: int = 50
    font: str = "normal"
    color: str = "#FFFFFFFF"
    led_color: str = ""
    led_mode: str = "freshness"  # "freshness" colors the LED by item age, "fixed" uses led_color
    mode: str = "newest"  # "newest" = single latest across feeds, "rotate" = cycle all, "pinned" = one feed
    pinned_source: str = ""  # feed shown in "pinned" mode
    show_meta: bool = True  # append relative age and queue position to the marquee
    show_source: bool = True
    enabled: bool = False
    clock_format: str = "12"
    clock_blink: bool = True
    clock_blink_seconds: float = 1.0
    clock_background: str = "#05070AFF"
    clock_card_top: str = "#1F242AFF"
    clock_card_bottom: str = "#14181DFF"
    clock_digits: str = "#F8E8C5FF"
    clock_accent: str = "#FF9130FF"
    hourly_flash: bool = True
    hourly_flash_color: str = "#FF9130FF"
    custom_action: str = "clock"  # physical CUSTOM control: "clock" or "rss"
    badges: dict = field(default_factory=dict)  # source -> {label, background, foreground}
    feeds: list = field(default_factory=list)   # [{source, url, enabled}] — overrides CATALOGUE
    clock_presets: dict = field(default_factory=dict)  # name -> {clock_format, clock_blink, ...}


CLOCK_PRESET_FIELDS = ("clock_format", "clock_blink", "clock_blink_seconds", "clock_background",
                       "clock_card_top", "clock_card_bottom", "clock_digits", "clock_accent")


def clean_text(value: Optional[str]) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value).strip()
    # BUSY Bar bitmap fonts accept printable ASCII only.
    return value.encode("ascii", "replace").decode("ascii").replace("?", "-")


def load_config() -> Config:
    try:
        raw = json.loads(CONFIG_PATH.read_text())
        allowed = Config.__dataclass_fields__.keys()
        return Config(**{k: v for k, v in raw.items() if k in allowed})
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return Config()


def save_config(config: Config) -> None:
    CONFIG_PATH.write_text(json.dumps(asdict(config), indent=2) + "\n")


def request(url: str, *, data: Optional[bytes] = None, headers: Optional[dict] = None,
            method: Optional[str] = None, timeout: int = 15) -> bytes:
    merged = {"User-Agent": USER_AGENT, **(headers or {})}
    with urllib.request.urlopen(
        urllib.request.Request(url, data=data, headers=merged, method=method), timeout=timeout
    ) as response:
        return response.read()


def protobuf_fields(payload: bytes) -> list:
    """Decode the small subset of protobuf wire types used by device input events."""
    fields, offset = [], 0

    def varint(position: int) -> tuple:
        value, shift = 0, 0
        while position < len(payload):
            byte = payload[position]
            position += 1
            value |= (byte & 0x7F) << shift
            if byte < 0x80:
                return value, position
            shift += 7
        raise ValueError("Truncated protobuf varint")

    while offset < len(payload):
        key, offset = varint(offset)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, offset = varint(offset)
        elif wire == 2:
            size, offset = varint(offset)
            value, offset = payload[offset:offset + size], offset + size
        elif wire == 1:
            value, offset = payload[offset:offset + 8], offset + 8
        elif wire == 5:
            value, offset = payload[offset:offset + 4], offset + 4
        else:
            raise ValueError(f"Unsupported protobuf wire type {wire}")
        fields.append((number, wire, value))
    return fields


def websocket_send_text(sock: socket.socket, text: str) -> None:
    data, mask = text.encode(), os.urandom(4)
    size = len(data)
    header = bytes((0x81, 0x80 | size))
    sock.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)))


def websocket_send_control(sock: socket.socket, opcode: int, payload: bytes = b"") -> None:
    """Send a control frame (ping/pong/close); payloads here are always < 126 bytes."""
    mask = os.urandom(4)
    header = bytes((0x80 | opcode, 0x80 | len(payload)))
    sock.sendall(header + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload)))


def websocket_read_frame(sock: socket.socket) -> tuple:
    def exact(size: int) -> bytes:
        value = b""
        while len(value) < size:
            chunk = sock.recv(size - len(value))
            if not chunk:
                raise EOFError("WebSocket closed")
            value += chunk
        return value

    first, second = exact(2)
    size = second & 0x7F
    if size == 126:
        size = struct.unpack("!H", exact(2))[0]
    elif size == 127:
        size = struct.unpack("!Q", exact(8))[0]
    mask = exact(4) if second & 0x80 else None
    payload = exact(size)
    if mask:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return first & 0x0F, payload


def stream_device_controls(config: Config, callback) -> None:
    """Continuously publish physical mode-switch and START events to callback."""
    parsed = urllib.parse.urlparse(config.device_url)
    sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=15)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        path = (parsed.path.rstrip("/") if parsed.path else "") + "/api/status/ws"
        handshake = (
            f"GET {path} HTTP/1.1\r\nHost: {parsed.hostname}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode())
        response = b""
        while b"\r\n\r\n" not in response:
            response += sock.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError("Device rejected status WebSocket")
        websocket_send_text(sock, '{"enable":true}')
        # A fresh subscription replays the device's most recent input history.
        # Treat only events arriving after the initial backlog as live controls.
        controls_ready_at = time.monotonic() + 3.0
        while True:
            opcode, frame = websocket_read_frame(sock)
            if opcode == 0x8:  # close
                raise EOFError("WebSocket closed by device")
            if opcode == 0x9:  # ping — device drops the connection if this goes unanswered
                websocket_send_control(sock, 0xA, frame)
                continue
            if opcode != 2:
                continue
            for number, wire, update in protobuf_fields(frame):
                if number != 2 or wire != 2:
                    continue
                for update_number, update_wire, input_value in protobuf_fields(update):
                    if update_number != 11 or update_wire != 2:
                        continue
                    for event_number, event_wire, event_value in protobuf_fields(input_value):
                        if event_wire != 2:
                            continue
                        details = {n: v for n, w, v in protobuf_fields(event_value) if w == 0}
                        if time.monotonic() < controls_ready_at:
                            continue
                        record_input_event(event_number, details)
                        if event_number == 2:  # physical mode switch
                            callback("custom" if details.get(1) == 1 else "other")
                        if event_number == 1 and details.get(1) == 2 and details.get(2, 0) == 0:
                            callback("start")
    finally:
        sock.close()


class Headline(NamedTuple):
    source: str
    title: str
    published: Optional[float]  # epoch seconds, None when the feed omits a date


def parse_date(value: Optional[str]) -> Optional[float]:
    """Accept RFC 822 (RSS) and ISO 8601 (Atom) timestamps, ignore anything else."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def parse_feed(xml: bytes) -> tuple[str, list[tuple[str, Optional[float]]]]:
    root = ET.fromstring(xml)
    channel = root.find("channel")
    items: list[tuple[str, Optional[float]]] = []
    if channel is not None:  # RSS 2.x
        source = clean_text(channel.findtext("title")) or "RSS"
        encoded_tag = "{http://purl.org/rss/1.0/modules/content/}encoded"
        for item in channel.findall("item"):
            title = clean_text(item.findtext("title"))
            content = item.findtext(encoded_tag) or item.findtext("description") or ""
            if not title and content:
                build = re.search(r"Build\s*-\s*(\d+[a-z]?)", content, re.IGNORECASE)
                title = f"New Unleashed Firmware Build {build.group(1)}" if build else clean_text(content)[:160]
            if title:
                items.append((title, parse_date(item.findtext("pubDate"))))
    else:  # Atom
        ns = "{http://www.w3.org/2005/Atom}"
        source = clean_text(root.findtext(f"{ns}title")) or "Feed"
        for entry in root.findall(f"{ns}entry"):
            title = clean_text(entry.findtext(f"{ns}title"))
            if title:
                published = parse_date(entry.findtext(f"{ns}published")) or \
                    parse_date(entry.findtext(f"{ns}updated"))
                items.append((title, published))
    if not items:
        # RSS 1.0/RDF and feeds using a default XML namespace do not match the
        # simple RSS 2.0 paths above. Match by local tag name as a final pass.
        def local_name(element: ET.Element) -> str:
            return element.tag.rsplit("}", 1)[-1].lower()

        source = next((clean_text(node.text) for node in root.iter()
                       if local_name(node) == "title" and clean_text(node.text)), "RSS")
        for item in root.iter():
            if local_name(item) not in {"item", "entry"}:
                continue
            fields = {local_name(child): clean_text(child.text) for child in item}
            title = fields.get("title", "")
            if title:
                published = parse_date(fields.get("pubdate")) or \
                    parse_date(fields.get("published")) or parse_date(fields.get("updated")) or \
                    parse_date(fields.get("date"))
                items.append((title, published))
    return source, items


def fetch_feed(config: Config) -> tuple[str, list[tuple[str, Optional[float]]]]:
    return parse_feed(request(config.feed_url))


async def fetch_all_feeds() -> tuple[list[Headline], list[str]]:
    async def fetch_one(name: str, url: str):
        LOGGER.info("feed.fetch.start source=%s url=%s", name, url)
        try:
            _, items = parse_feed(await asyncio.to_thread(request, url, timeout=45, headers=FEED_HEADERS))
            if not items:
                error = "feed returned no titled items (possibly redirected to HTML)"
                LOGGER.error("feed.fetch.empty source=%s error=%s", name, error)
                return None, f"{name}: {error}"
            LOGGER.info("feed.fetch.ok source=%s items=%d", name, len(items))
            title, published = items[0]
            return Headline(name, title, published), ""
        except Exception as exc:
            LOGGER.error("feed.fetch.failed source=%s error=%s", name, exc)
            return None, f"{name}: {exc}"
    results = await asyncio.gather(*(fetch_one(name, url) for name, url in FEEDS))
    return [item for item, _ in results if item], [error for _, error in results if error]


async def fetch_digest_fast(limit: Optional[int] = None) -> list[Headline]:
    """Fetch enabled sources concurrently for the physical-button digest."""
    async def fetch_one(name: str, url: str) -> Optional[Headline]:
        try:
            _, items = parse_feed(
                await asyncio.to_thread(request, url, timeout=10, headers=FEED_HEADERS)
            )
            if items:
                title, published = items[0]
                return Headline(name, title, published)
        except Exception as exc:
            LOGGER.info("digest.fetch.failed source=%s error=%s", name, exc)
        return None

    tasks = [asyncio.create_task(fetch_one(name, url)) for name, url in FEEDS]
    results = await asyncio.gather(*tasks)
    digest = [item for item in results if item]
    return digest[:limit] if limit is not None else digest


Pixel = tuple  # (r, g, b, a)
CLEAR: Pixel = (0, 0, 0, 0)


def encode_png(pixels: list[list[Pixel]]) -> bytes:
    """Encode an RGBA pixel grid as a PNG without external dependencies."""
    height, width = len(pixels), len(pixels[0])
    raw = b"".join(b"\x00" + b"".join(bytes(pixel) for pixel in row) for row in pixels)
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def mix(a: Pixel, b: Pixel, weight: float) -> Pixel:
    """Blend two opaque colors; weight 0 returns a, weight 1 returns b."""
    return tuple(round(a[i] + (b[i] - a[i]) * weight) for i in range(3)) + (255,)


def wired_logo_png(accent: Pixel = (226, 26, 34, 255),
                   secondary: Pixel = (255, 255, 255, 255)) -> bytes:
    """Return a legible 29x9 pixel interpretation of WIRED's tiled wordmark."""
    glyphs = {
        "W": ("101", "101", "101", "111", "101"),
        "I": ("111", "010", "010", "010", "111"),
        "R": ("110", "101", "110", "101", "101"),
        "E": ("111", "100", "110", "100", "111"),
        "D": ("110", "101", "101", "101", "110"),
    }
    width, height = 29, 9
    white, black = (255, 255, 255, 255), (0, 0, 0, 255)
    pixels = [[black for _ in range(width)] for _ in range(height)]
    for index, letter in enumerate("WIRED"):
        left = index * 6
        inverted = index % 2 == 0
        background, ink = (accent, white) if inverted else (secondary, black)
        for y in range(7):
            for x in range(5):
                pixels[y + 1][left + x] = background
        for gy, row in enumerate(glyphs[letter]):
            for gx, bit in enumerate(row):
                if bit == "1":
                    pixels[gy + 2][left + gx + 1] = ink
    return encode_png(pixels)


def pixel_icon_png(kind: str) -> bytes:
    """Create a security shield or Flipper-inspired dolphin pixel icon."""
    if kind == "flipper":
        # Trimmed to its content box; trailing blank columns used to shove it off-centre.
        art = ("....CCC......", "..CCCCCC.....", ".CC...CCCC...", "CC......CCMM.",
               ".CC....CC.MMM", "..CCCCCC...MM", "...CCC....MM.", "....C....MM..",
               ".........M...")
        colors = {"C": (45, 226, 255, 255), "M": (255, 55, 190, 255)}
    else:
        art = ("..GGGG..", ".G....G.", "G.GGGG.G", "G.G..G.G", ".G.GG.G.",
               "..G..G..", "...GG...", "....G...")
        colors = {"G": (72, 238, 151, 255)}
    return encode_png([[colors.get(char, CLEAR) for char in row] for row in art])


def clock_face_png(now: Optional[datetime] = None) -> bytes:
    """Generate a 15x15 analog face with live hour and minute hands."""
    now = now or datetime.now().astimezone()
    size, center = 15, 7
    cyan, white, orange = (52, 218, 255, 255), (244, 249, 255, 255), (255, 126, 48, 255)
    pixels = [[CLEAR for _ in range(size)] for _ in range(size)]
    for minute in range(60):
        angle = math.radians(minute * 6 - 90)
        x, y = round(center + 6 * math.cos(angle)), round(center + 6 * math.sin(angle))
        pixels[y][x] = white if minute % 5 == 0 else cyan

    def hand(degrees: float, length: int, color: Pixel) -> None:
        angle = math.radians(degrees - 90)
        end_x = round(center + length * math.cos(angle))
        end_y = round(center + length * math.sin(angle))
        steps = max(abs(end_x - center), abs(end_y - center), 1)
        for step in range(steps + 1):
            x = round(center + (end_x - center) * step / steps)
            y = round(center + (end_y - center) * step / steps)
            pixels[y][x] = color

    hand((now.hour % 12 + now.minute / 60) * 30, 3, orange)
    hand(now.minute * 6, 5, white)
    pixels[center][center] = orange
    return encode_png(pixels)


def flip_clock_png(now: Optional[datetime] = None, previous: Optional[datetime] = None,
                   phase: int = 3, dot_on: bool = True,
                   config: Optional[Config] = None) -> bytes:
    """Render a 12-hour split-flap frame; phases 1-3 form the flip transition."""
    now = now or datetime.now().astimezone()
    use_24 = bool(config and config.clock_format == "24")
    hour = now.strftime("%H") if use_24 else now.strftime("%I").lstrip("0").rjust(2)
    digits = hour + now.strftime("%M")
    if previous:
        old_hour = previous.strftime("%H") if use_24 else previous.strftime("%I").lstrip("0").rjust(2)
        old_digits = old_hour + previous.strftime("%M")
    else:
        old_digits = digits
    width, height = 72, 16
    def configured(name: str, fallback: Pixel) -> Pixel:
        value = getattr(config, name, "") if config else ""
        if re.fullmatch(r"#[0-9A-Fa-f]{8}", value or ""):
            raw = value[1:]
            return tuple(int(raw[index:index + 2], 16) for index in (0, 2, 4, 6))
        return fallback
    backdrop = configured("clock_background", (5, 7, 10, 255))
    card_top = configured("clock_card_top", (31, 36, 42, 255))
    card_bottom = configured("clock_card_bottom", (20, 24, 29, 255))
    edge = (61, 67, 74, 255)
    seam = (7, 9, 12, 255)
    ivory = configured("clock_digits", (248, 232, 197, 255))
    amber = configured("clock_accent", (255, 145, 48, 255))
    pixels = [[backdrop for _ in range(width)] for _ in range(height)]
    card_x = (1, 17, 40, 56)
    for left in card_x:
        for y in range(1, 15):
            for x in range(left, left + 15):
                rounded_corner = (y in (1, 14) and x in (left, left + 14))
                if not rounded_corner:
                    pixels[y][x] = card_top if y < 8 else card_bottom
        for x in range(left + 1, left + 14):
            pixels[1][x] = edge
            pixels[8][x] = seam
        pixels[7][left] = pixels[7][left + 14] = edge

    # 3x5 digits scaled 2x, centred on each 15px card.
    blank = ("000",) * 5
    for digit, old_digit, left in zip(digits, old_digits, card_x):
        changed = digit != old_digit
        new_glyph, old_glyph = FONT_3X5.get(digit, blank), FONT_3X5.get(old_digit, blank)
        for gy in range(5):
            for gx in range(3):
                for sy in range(2):
                    target_y = 3 + gy * 2 + sy
                    if not changed or phase >= 3:
                        bit = new_glyph[gy][gx]
                    elif phase == 1:
                        bit = old_glyph[gy][gx] if target_y < 8 else "0"
                    else:  # new upper flap has landed; old lower flap is still unfolding
                        bit = new_glyph[gy][gx] if target_y < 8 else old_glyph[gy][gx]
                    if bit == "1":
                        for sx in range(2):
                            pixels[target_y][left + 4 + gx * 2 + sx] = ivory
        # Reassert the physical flap seam over the numeral.
        for x in range(left + 1, left + 14):
            pixels[8][x] = amber if changed and phase in (1, 2) else mix(pixels[8][x], seam, 0.55)

    # One compact amber status lamp; the updater alternates it on/off each second.
    if dot_on:
        for y in (7, 8):
            pixels[y][35] = pixels[y][36] = amber
    return encode_png(pixels)


# 3x5 uppercase font. Rows read top to bottom; "1" is ink.
FONT_3X5 = {
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"), "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "110", "011"), "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("110", "001", "010", "100", "111"), "3": ("110", "001", "010", "001", "110"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "110", "001", "110"),
    "6": ("011", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "110"),
}


def badge_width(label: str) -> int:
    return len(label[:3]) * 4 + 3


def badge_logo_png(label: str, background: Pixel, foreground: Pixel) -> bytes:
    """Render a compact source badge: rounded 1px keyline, tinted plate, 3x5 label.

    Width is len(label) * 4 + 3: a 1px keyline plus a 1px gutter on both sides,
    which keeps the label optically centred inside the plate.
    """
    label = label[:3].upper()
    width, height = badge_width(label), 9
    keyline = mix(background, foreground, 0.45)
    plate = mix(background, (0, 0, 0, 255), 0.25)
    pixels = [[background for _ in range(width)] for _ in range(height)]
    for x in range(width):
        pixels[0][x] = pixels[height - 1][x] = keyline
    for y in range(height):
        pixels[y][0] = pixels[y][width - 1] = keyline
    for x, y in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1)):
        pixels[y][x] = CLEAR  # rounded corners
    for x in range(1, width - 1):
        pixels[1][x] = mix(background, (255, 255, 255, 255), 0.18)  # top highlight
        pixels[height - 2][x] = plate  # bottom shade
    for index, letter in enumerate(label):
        for y, row in enumerate(FONT_3X5.get(letter, FONT_3X5["S"])):
            for x, bit in enumerate(row):
                if bit == "1":
                    pixels[y + 2][index * 4 + x + 2] = foreground
    return encode_png(pixels)


def npr_logo_png() -> bytes:
    """Render a crisp, proportional NPR block mark for the BUSY Bar canvas."""
    colors = ((204, 30, 38, 255), (18, 18, 20, 255), (38, 116, 174, 255))
    pixels = [[CLEAR for _ in range(18)] for _ in range(9)]
    for index, (letter, color) in enumerate(zip("NPR", colors)):
        left = index * 6
        for y in range(1, 8):
            for x in range(left, left + 6):
                pixels[y][x] = color
        for y, row in enumerate(FONT_3X5[letter]):
            for x, bit in enumerate(row):
                if bit == "1":
                    pixels[y + 2][left + x + 2] = (255, 255, 255, 255)
    return encode_png(pixels)


def verge_logo_png() -> bytes:
    """Render a compact neon Verge-style split V."""
    cyan, magenta, orange = ((42, 220, 220, 255), (232, 39, 113, 255),
                             (255, 112, 35, 255))
    pixels = [[CLEAR for _ in range(13)] for _ in range(11)]
    for step in range(5):
        pixels[step + 1][step + 1] = cyan
        pixels[step + 1][step + 2] = cyan
        pixels[step + 1][11 - step] = magenta
        pixels[step + 1][10 - step] = magenta
    for step in range(4):
        pixels[6 + step][5 + step // 2] = orange
        pixels[6 + step][7 - step // 2] = orange
    pixels[10][6] = orange
    return encode_png(pixels)


def hacker_news_logo_png() -> bytes:
    """Render Hacker News' familiar orange tile with a white Y."""
    orange, white = (255, 102, 0, 255), (255, 255, 255, 255)
    pixels = [[orange for _ in range(9)] for _ in range(9)]
    for y, x_values in enumerate(((2, 6), (2, 6), (3, 5), (3, 5), (4,), (4,), (4,))):
        for x in x_values:
            pixels[y + 1][x] = white
    return encode_png(pixels)


def rss_icon_png() -> bytes:
    """Render a tiny monochrome RSS glyph for user-added feeds."""
    white = (255, 255, 255, 255)
    art = (
        ".......",
        ".W.....",
        "...W...",
        ".W..W..",
        ".....W.",
        ".W...W.",
        ".......",
    )
    return encode_png([[white if pixel == "W" else CLEAR for pixel in row] for row in art])


def site_favicon_png() -> bytes:
    """Render the dashboard's orange-and-white 16px BUSY mark."""
    orange, white, dark = (255, 93, 58, 255), (255, 255, 255, 255), (16, 7, 4, 255)
    pixels = [[dark for _ in range(16)] for _ in range(16)]
    for y in range(2, 14):
        for x in range(2, 14):
            pixels[y][x] = orange
    glyph = ("110", "101", "110", "101", "110")
    for gy, row in enumerate(glyph):
        for gx, bit in enumerate(row):
            if bit == "1":
                for sy in range(2):
                    for sx in range(2):
                        pixels[3 + gy * 2 + sy][5 + gx * 2 + sx] = white
    return encode_png(pixels)


BADGES = {
    "DARKNET DIARIES": ("DD", (13, 13, 18, 255), (255, 48, 73, 255)),
    "GRAHAM CLULEY": ("GC", (20, 72, 110, 255), (255, 255, 255, 255)),
    "KREBS": ("K", (167, 25, 48, 255), (255, 255, 255, 255)),
    "SANS ISC": ("ISC", (30, 61, 115, 255), (255, 190, 38, 255)),
    "SCHNEIER": ("BS", (32, 32, 36, 255), (111, 194, 255, 255)),
    "SECURELIST": ("SL", (196, 0, 50, 255), (255, 255, 255, 255)),
    "SOPHOS OPS": ("SO", (0, 91, 170, 255), (255, 255, 255, 255)),
    "SOPHOS RESEARCH": ("SR", (0, 126, 190, 255), (223, 252, 255, 255)),
    "THE HACKER NEWS": ("THN", (12, 104, 150, 255), (255, 255, 255, 255)),
    "TROY HUNT": ("TH", (92, 49, 128, 255), (255, 255, 255, 255)),
    "USOM THREATS": ("UT", (174, 24, 36, 255), (255, 255, 255, 255)),
    "USOM NEWS": ("UN", (210, 45, 45, 255), (255, 230, 155, 255)),
    "WELIVESECURITY": ("E", (0, 153, 136, 255), (255, 255, 255, 255)),
}


# Per-source badge overrides edited from the web UI, mirrored from Config.badges.
BADGE_OVERRIDES: dict[str, dict] = {}


def hex_to_pixel(value: str) -> Pixel:
    value = value.lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        raise ValueError(f"Colour must be #RRGGBB, got {value!r}")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def pixel_to_hex(pixel: Pixel) -> str:
    return "#%02X%02X%02X" % pixel[:3]


AUTO_PLATES = [(24, 62, 110), (120, 32, 48), (36, 84, 62), (86, 46, 110),
               (128, 74, 20), (26, 84, 96), (96, 40, 84), (52, 56, 128)]


def auto_badge(source: str) -> tuple[str, Pixel, Pixel]:
    """Derive a stable label and plate colour for feeds with no hand-picked badge."""
    words = [word for word in re.split(r"[^A-Za-z0-9]+", source) if word]
    if len(words) >= 2:
        label = (words[0][0] + words[1][:2]).upper()
    else:
        label = (words[0][:3] if words else "RSS").upper()
    plate = AUTO_PLATES[zlib.crc32(source.encode()) % len(AUTO_PLATES)]
    return label, plate + (255,), (255, 255, 255, 255)


def badge_spec(source: str) -> tuple[str, Pixel, Pixel]:
    """Resolve a badge to (label, background, foreground), honouring UI overrides."""
    label, background, foreground = BADGES.get(source) or auto_badge(source)
    override = BADGE_OVERRIDES.get(source)
    if override:
        label = (override.get("label") or label)[:3].upper()
        background = hex_to_pixel(override.get("background") or pixel_to_hex(background))
        foreground = hex_to_pixel(override.get("foreground") or pixel_to_hex(foreground))
    return label, background, foreground


def is_badge_source(source: str) -> bool:
    """True when the source uses the editable badge renderer rather than custom art."""
    return not (source == "CLOCK"
                or publisher_favicon(source) is not None
                or source not in CATALOGUE_SOURCES
                or source.startswith(("WIRED", "NPR ", "VERGE ")))


def source_slug(source: str) -> str:
    """Return one safe, stable asset stem for a feed source."""
    return re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-") or "rss"


PUBLISHER_FAVICONS = {
    "DARKNET DIARIES": "darknet-diaries.png",
    "GRAHAM CLULEY": "graham-cluley.png",
    "KREBS": "krebs.png",
    "SANS ISC": "sans-isc.png",
    "SCHNEIER": "schneier.png",
    "SECURELIST": "securelist.png",
    "THE HACKER NEWS": "the-hacker-news.png",
    "TROY HUNT": "troy-hunt.png",
    "WELIVESECURITY": "eset.png",
    "HACKER NEWS": "hacker-news.png",
    "USOM THREATS": "usom.png",
    "USOM NEWS": "usom.png",
    "UNLEASHEDFLIP": "unleashedflip.png",
}


def publisher_favicon(source: str) -> Optional[Path]:
    """Resolve a built-in feed to its publisher-provided favicon asset."""
    filename = PUBLISHER_FAVICONS.get(source)
    if source.startswith("NPR "):
        filename = "npr.png"
    elif source.startswith("VERGE "):
        filename = "the-verge.png"
    elif source.startswith("SOPHOS "):
        filename = "sophos.png"
    path = FEED_ICON_DIR / filename if filename else None
    return path if path and path.is_file() else None


WIRED_PALETTES = {
    "WIRED": ((226, 26, 34, 255), (255, 255, 255, 255), "#FFFFFFFF"),
    "WIRED AI": ((132, 66, 255, 255), (46, 224, 255, 255), "#B8F7FFFF"),
    "WIRED BUSINESS": ((16, 156, 98, 255), (255, 203, 61, 255), "#D8FFE9FF"),
    "WIRED CULTURE": ((225, 45, 132, 255), (255, 218, 75, 255), "#FFE2F1FF"),
    "WIRED SCIENCE": ((32, 108, 232, 255), (96, 238, 180, 255), "#DCEBFFFF"),
    "WIRED SECURITY": ((220, 38, 38, 255), (255, 125, 48, 255), "#FFE1D8FF"),
    "WIRED IDEAS": ((126, 71, 210, 255), (255, 177, 139, 255), "#EEE3FFFF"),
    "WIRED GEAR": ((0, 164, 190, 255), (255, 118, 48, 255), "#D8FAFFFF"),
    "WIRED GUIDES": ((225, 142, 24, 255), (255, 239, 190, 255), "#FFF4D6FF"),
}


def icon_details(source: str) -> tuple[str, bytes, int, str]:
    if source == "CLOCK":
        return "clock.png", flip_clock_png(), 72, "#F8E8C5FF"
    if source.startswith("NPR "):
        return "npr-pixel-v3.png", npr_logo_png(), 21, "#FFFFFFFF"
    favicon = publisher_favicon(source)
    if favicon:
        content = favicon.read_bytes()
        width = struct.unpack(">I", content[16:20])[0]
        return favicon.stem + "-favicon-v1.png", content, width + 3, "#FFFFFFFF"
    if source.startswith("WIRED"):
        accent, secondary, color = WIRED_PALETTES.get(source, WIRED_PALETTES["WIRED"])
        filename = source_slug(source) + "-pixel-v2.png"
        return filename, wired_logo_png(accent, secondary), 32, color
    if source == "UNLEASHEDFLIP":
        return "flipper.png", pixel_icon_png("flipper"), 16, "#9EEDFFFF"
    if source.startswith("VERGE "):
        return "verge-pixel-v2.png", verge_logo_png(), 16, "#FFFFFFFF"
    if source == "HACKER NEWS":
        return "hacker-news-pixel-v2.png", hacker_news_logo_png(), 12, "#FFFFFFFF"
    if source not in CATALOGUE_SOURCES:
        return source_slug(source) + "-rss-white-v1.png", rss_icon_png(), 10, "#FFFFFFFF"
    label, background, foreground = badge_spec(source)
    filename = source_slug(source) + ".png"
    return (filename, badge_logo_png(label, background, foreground),
            badge_width(label) + 3, "#E8FFF1FF")


def icons_by_filename() -> dict[str, str]:
    """Map generated PNG filenames back to their feed source, for the web gallery."""
    return {icon_details(entry["source"])[0]: entry["source"] for entry in ALL_FEEDS}


def upload_icon(config: Config, source: str,
                application_name: str = "busy_rss") -> tuple[str, int, str]:
    filename, content, text_x, color = icon_details(source)
    if source == "CLOCK":
        content = flip_clock_png(config=config)
    query = urllib.parse.urlencode({"application_name": application_name, "file": filename})
    headers = {"Content-Type": "application/octet-stream", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    request(config.device_url.rstrip("/") + "/api/assets/upload?" + query,
            data=content, headers=headers)
    return filename, text_x, color


FRESHNESS = (  # (max age in seconds, LED color)
    (3600, "#33FF88FF"),      # under an hour: breaking
    (6 * 3600, "#FFD23AFF"),  # this morning / afternoon
    (24 * 3600, "#FF8A2BFF"), # today
)
STALE_COLOR = "#4A6A8AFF"
UNDATED_COLOR = "#8888AAFF"


def format_age(published: Optional[float], now: Optional[float] = None) -> str:
    """Compact relative age: 45m, 5h, 3d. Empty when the feed gave no date."""
    if not published:
        return ""
    seconds = max(0.0, (now or time.time()) - published)
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 48 * 3600:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def freshness_color(published: Optional[float], now: Optional[float] = None) -> str:
    if not published:
        return UNDATED_COLOR
    seconds = max(0.0, (now or time.time()) - published)
    for limit, color in FRESHNESS:
        if seconds < limit:
            return color
    return STALE_COLOR


def headline_text(config: Config, item: Headline, position: int = 0, total: int = 0) -> str:
    """Build the exact marquee string, so display and duration never disagree."""
    if item.source == "CLOCK":
        now = datetime.now().astimezone()
        return (now.strftime("%H:%M") if config.clock_format == "24"
                else now.strftime("%I:%M %p").lstrip("0"))
    text = item.title if item.source.startswith("WIRED") else f"{item.source} | {item.title}"
    if not config.show_meta:
        return text
    meta = [part for part in (format_age(item.published),
                              f"{position}/{total}" if total else "") if part]
    return f"{text}  |  {' | '.join(meta)}" if meta else text


def display_payload(config: Config, item: Headline, position: int = 0, total: int = 0) -> dict:
    source = item.source
    filename, _, text_x, color = icon_details(source)
    if source == "CLOCK":
        return {"application_name": "busy_clock", "priority": 100, "elements": [{
            "id": "flip-clock", "type": "image", "path": filename,
            "align": "top_left", "x": 0, "y": 0, "display": "front",
            "opacity": 100, "timeout": 0,
        }]}
    text = headline_text(config, item, position, total)
    width = 72 - text_x
    elements = [{
        "id": "feed-logo", "type": "image", "path": filename,
        "align": "mid_left", "x": 0, "y": 10, "display": "front",
        "opacity": 100, "timeout": 0,
    }, {
        "id": "headline", "type": "text", "text": text[:500],
        "font": "large" if source == "CLOCK" else config.font, "color": color, "width": width,
        "align": "mid_left", "x": text_x, "y": 8 if source == "CLOCK" else 10,
        "display": "front", "scroll_rate": 900, "scroll_start_delay": 250,
        "scroll_repeat_delay": 800, "timeout": 0,
    }]
    payload = {"application_name": "busy_rss", "priority": config.priority, "elements": elements}
    led = freshness_color(item.published) if config.led_mode == "freshness" else config.led_color
    if led:
        payload["led_notification_color"] = led
    return payload


def headline_duration(config: Config, item: Headline, position: int = 0, total: int = 0) -> float:
    """Estimate one complete marquee pass from font width and scroll rate."""
    if item.source == "CLOCK":
        return 30.0
    pixels_per_character = {
        "tiny": 4, "small": 5, "normal": 6, "condensed": 5,
        "bold": 7, "large": 8, "extra_large": 10, "global": 6,
    }[config.font]
    _, _, text_x, _ = icon_details(item.source)
    viewport_width = 72 - text_x
    text = headline_text(config, item, position, total)
    pixels_per_second = 900 / 60
    scrolling_pixels = max(0, len(text) * pixels_per_character - viewport_width)
    # Includes the configured 250ms start delay and a short pause at the end.
    return min(90.0, max(5.0, 0.25 + scrolling_pixels / pixels_per_second + 1.25))


def send_to_device(config: Config, item: Headline, position: int = 0, total: int = 0) -> dict:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    upload_icon(config, item.source)
    url = config.device_url.rstrip("/") + "/api/display/draw"
    clear_url = url + "?" + urllib.parse.urlencode({"application_name": "busy_rss"})
    request(clear_url, headers=headers, method="DELETE")
    payload = display_payload(config, item, position, total)
    try:
        result = request(url, data=json.dumps(payload).encode(), headers=headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        # An explicit feed push is allowed to replace our own priority-100 clock.
        # Clear that layer only after the new feed icon is safely uploaded, then
        # retry once so the display transition remains as close to atomic as the
        # firmware permits.
        clear_app(config, "busy_clock")
        result = request(url, data=json.dumps(payload).encode(), headers=headers)
    parsed = json.loads(result or b"{}")
    LOGGER.info("display.ok source=%s age=%s position=%d/%d title=%r result=%s",
                item.source, format_age(item.published) or "-", position, total, item.title, parsed)
    return parsed


def send_clock_frame(config: Config, image: bytes, filename: str) -> None:
    """Upload and atomically replace the clock face without exposing BUSY."""
    headers = {"Content-Type": "application/octet-stream", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    base = config.device_url.rstrip("/")
    query = urllib.parse.urlencode({"application_name": "busy_clock", "file": filename})
    request(base + "/api/assets/upload?" + query, data=image, headers=headers)
    draw_headers = dict(headers)
    draw_headers["Content-Type"] = "application/json"
    draw_url = base + "/api/display/draw"
    # Keep the application alive while replacing its stable element ID. Clearing
    # first briefly exposes the firmware's underlying BUSY screen every minute.
    payload = {"application_name": "busy_clock", "priority": 100, "elements": [{
        "id": "flip-clock", "type": "image", "path": filename,
        "align": "top_left", "x": 0, "y": 0, "display": "front", "opacity": 100, "timeout": 0,
    }]}
    try:
        request(draw_url, data=json.dumps(payload).encode(), headers=draw_headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        release_active_timer(config)
        request(draw_url, data=json.dumps(payload).encode(), headers=draw_headers)


def upload_clock_asset(config: Config, image: bytes, filename: str) -> None:
    headers = {"Content-Type": "application/octet-stream", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    query = urllib.parse.urlencode({"application_name": "busy_clock", "file": filename})
    request(config.device_url.rstrip("/") + "/api/assets/upload?" + query, data=image, headers=headers)


def draw_clock_asset(config: Config, filename: str) -> None:
    """Overlay one preloaded blink frame; its opaque background replaces the prior frame."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    payload = {"application_name": "busy_clock", "priority": 100, "elements": [{
        "id": "clock-blink-on" if filename.endswith("on.png") else "clock-blink-off",
        "type": "image", "path": filename, "align": "top_left", "x": 0, "y": 0,
        "display": "front", "opacity": 100, "timeout": 2,
    }]}
    request(config.device_url.rstrip("/") + "/api/display/draw",
            data=json.dumps(payload).encode(), headers=headers)


def draw_clock_dot(config: Config) -> None:
    """Draw only the amber lamp; timeout creates the off half of the blink."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    payload = {"application_name": "busy_clock", "priority": 100, "elements": [{
        "id": "clock-lamp", "type": "rectangle", "x": 35, "y": 7,
        "width": 2, "height": 2, "fill": "solid",
        "fill_colors": [config.clock_accent], "border_width": 0,
        "display": "front", "timeout": 1,
    }]}
    request(config.device_url.rstrip("/") + "/api/display/draw",
            data=json.dumps(payload).encode(), headers=headers)


def set_hourly_light(config: Config, color: str) -> None:
    """Set the notification lights without changing any visible screen pixels."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    with STATE.lock:
        application_name = "busy_clock" if STATE.clock_active else "busy_rss"
    payload = {
        "application_name": application_name,
        "priority": 100,
        "led_notification_color": color,
        "elements": [{
            "id": "hour-chime-light", "type": "rectangle", "x": -1, "y": -1,
            "width": 1, "height": 1, "fill": "solid",
            "fill_colors": ["#00000000"], "border_width": 0,
            "display": "front", "timeout": 1,
        }],
    }
    request(config.device_url.rstrip("/") + "/api/display/draw",
            data=json.dumps(payload).encode(), headers=headers)


async def hourly_light_scheduler() -> None:
    """Flash once at the top of each hour, with a guard against duplicate runs."""
    last_hour = ""
    while True:
        now = datetime.now().astimezone()
        hour_key = now.strftime("%Y-%m-%d-%H")
        with STATE.lock:
            config = STATE.config
        if config.hourly_flash and now.minute == 0 and now.second < 12 and hour_key != last_hour:
            last_hour = hour_key
            LOGGER.info("hourly.flash.start hour=%s color=%s", now.strftime("%I:%M %p"),
                        config.hourly_flash_color)
            try:
                for _ in range(3):
                    await asyncio.to_thread(set_hourly_light, config, config.hourly_flash_color)
                    await asyncio.sleep(0.45)
                    await asyncio.to_thread(set_hourly_light, config, "#00000000")
                    await asyncio.sleep(0.35)
                LOGGER.info("hourly.flash.done hour=%s", now.strftime("%I:%M %p"))
            except Exception as exc:
                LOGGER.warning("hourly.flash.failed error=%s", exc)
        await asyncio.sleep(1)


def animate_clock(config: Config, previous: datetime, current: datetime) -> None:
    """Play a compact mechanical flip and settle on the current minute."""
    for phase, pause in ((1, 0.09), (2, 0.11), (3, 0.0)):
        filename = "clock.png" if phase == 3 else f"clock-flip-{phase}.png"
        send_clock_frame(config, flip_clock_png(current, previous, phase), filename)
        if pause:
            time.sleep(pause)
    LOGGER.info("clock.flip from=%s to=%s", previous.strftime("%I:%M %p"), current.strftime("%I:%M %p"))


def sync_badges(config: Config) -> None:
    """Mirror saved badge overrides into the renderer's lookup table."""
    BADGE_OVERRIDES.clear()
    BADGE_OVERRIDES.update(config.badges or {})


def validate_badge(source: str, badge: dict) -> dict:
    if not any(source == entry["source"] for entry in ALL_FEEDS):
        raise ValueError(f"Unknown feed {source!r}")
    if not is_badge_source(source):
        raise ValueError(f"{source} uses custom artwork and has no editable badge")
    label = re.sub(r"[^A-Za-z0-9]", "", str(badge.get("label", ""))).upper()[:3]
    if not label:
        raise ValueError("Label must contain 1-3 letters or digits")
    return {"label": label,
            "background": pixel_to_hex(hex_to_pixel(badge.get("background", "#000000"))),
            "foreground": pixel_to_hex(hex_to_pixel(badge.get("foreground", "#FFFFFF")))}


def validate_clock_preset(preset: dict) -> dict:
    if preset.get("clock_format") not in {"12", "24"}:
        raise ValueError("Clock format must be '12' or '24'")
    try:
        blink_seconds = float(preset.get("clock_blink_seconds", 1))
    except (TypeError, ValueError):
        raise ValueError("Clock blink interval must be a number")
    if not 1 <= blink_seconds <= 5:
        raise ValueError("Clock blink interval must be between 1 and 5 seconds")
    colors = {}
    for name in ("clock_background", "clock_card_top", "clock_card_bottom", "clock_digits", "clock_accent"):
        value = preset.get(name, "")
        if not re.fullmatch(r"#[0-9A-Fa-f]{8}", value or ""):
            raise ValueError(f"{name} must use #RRGGBBAA format")
        colors[name] = value
    return {"clock_format": preset["clock_format"], "clock_blink": bool(preset.get("clock_blink")),
            "clock_blink_seconds": blink_seconds, **colors}


def describe(item: Headline) -> str:
    """One-line summary for the web UI status list."""
    age = format_age(item.published)
    return f"{item.source}: {item.title}" + (f"  ({age} ago)" if age else "")


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.config = load_config()
        sync_badges(self.config)
        sync_feeds(self.config)
        self.last_run: Optional[float] = None
        self.last_error = ""
        self.last_source = ""
        self.last_titles: list[str] = []
        self.last_items: list[Headline] = []
        self.cursor = 0  # rotation position, shared so "next" works while paused
        self.clock_active = False
        self.custom_active = False
        self.custom_last_start = 0.0
        self.network_scan_active = False
        self.network_sequence_cancelled = False
        self.rss_mode_active = False
        self.rss_cursor = -1
        self.button_stage = "clock"  # "clock" | "auto" — START starts/cancels the auto-play run
        self.auto_play_active = False
        self.rss_digest: list[Headline] = []
        self.rss_digest_at = 0.0
        self.control_last_press = 0.0
        self.selector_last_custom = 0.0
        self.selector_last_other = 0.0
        self.suppress_websocket_start_until = 0.0
        self.suppress_snapshot_start_until = 0.0
        self.networks: list[dict] = []
        self.network_scanned_at: Optional[float] = None
        self.network_scan_error = ""
        self.device_wifi: dict = {}
        self.input_events: list[dict] = []
        self.last_input_at: Optional[float] = None

    def refresh(self, send: bool = True) -> dict:
        with self.lock:
            config = self.config
            if send:
                self.clock_active = False
        try:
            items, errors = asyncio.run(fetch_all_feeds())
            if not items:
                raise ValueError("The feed contains no titled items")
            shown = display_list(config, items)
            result = send_to_device(config, shown[0], 1, len(shown)) if send else {"result": "preview"}
            with self.lock:
                self.last_run, self.last_error = time.time(), ""
                self.last_source = "WIRED + WIRED AI"
                self.last_items = items
                self.last_titles = [describe(item) for item in items]
                self.last_error = "; ".join(errors)
            return {"source": self.last_source, "titles": self.last_titles, "device": result}
        except Exception as exc:
            with self.lock:
                self.last_run, self.last_error = time.time(), str(exc)
            LOGGER.exception("feed.refresh.failed")
            raise


STATE = State()


def record_input_event(event_number: int, details: dict[int, int]) -> None:
    """Keep a bounded, browser-safe trace of live physical control events."""
    now = time.time()
    if event_number == 2:
        label = "CUSTOM selected" if details.get(1) == 1 else "Selector changed"
    elif event_number == 1 and details.get(1) == 2:
        label = "START pressed" if details.get(2, 0) == 0 else "START changed"
    else:
        label = f"Input event {event_number}"
    with STATE.lock:
        previous = STATE.last_input_at
        STATE.last_input_at = now
        STATE.input_events.append({
            "timestamp": now,
            "delta_ms": round((now - previous) * 1000) if previous else None,
            "event": event_number,
            "label": label,
            "details": {str(key): value for key, value in sorted(details.items())},
        })
        del STATE.input_events[:-100]
    LOGGER.info("input.raw event=%s label=%r details=%s", event_number, label, details)


def show_clock() -> dict:
    """Switch the display into a continuously refreshed hybrid clock mode."""
    with STATE.lock:
        STATE.clock_active = True
        STATE.rss_mode_active = False
        STATE.rss_cursor = -1
        STATE.button_stage = "clock"
        config = STATE.config
    item = Headline("CLOCK", "", time.time())
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    # The newest priority-100 app becomes frontmost atomically. Keep the prior
    # layer underneath; deleting it during a transition can expose CUSTOM or 409.
    send_clock_frame(config, flip_clock_png(config=config), "clock.png")
    hide_rss_overlays(config)
    result = {"result": "OK"}
    LOGGER.info("clock.start result=%s", result)
    return {"result": result, "time": headline_text(config, item)}


def hide_rss_overlays(config: Config) -> None:
    """Replace temporary RSS layers off-screen so the clock appears immediately."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    payload = {
        "application_name": "busy_clock", "priority": 100,
        "elements": [{
            "id": "rss-clean-bg", "type": "rectangle", "x": -1, "y": -1,
            "width": 1, "height": 1, "fill": "solid",
            "fill_colors": ["#00000000"], "border_width": 0,
            "display": "front", "timeout": 1,
        }, {
            "id": "rss-source-name", "type": "text", "text": ".",
            "font": "tiny", "color": "#00000000", "width": 1,
            "align": "top_left", "x": -1, "y": -1, "display": "front",
            "scroll_rate": 0, "scroll_start_delay": 0,
            "scroll_repeat_delay": 0, "timeout": 1,
        }, {
            "id": "rss-divider", "type": "rectangle", "x": -1, "y": -1,
            "width": 1, "height": 1, "fill": "solid",
            "fill_colors": ["#00000000"], "border_width": 0,
            "display": "front", "timeout": 1,
        }, {
            "id": "rss-clean-text", "type": "text", "text": ".",
            "font": "tiny", "color": "#00000000", "width": 1,
            "align": "top_left", "x": -1, "y": -1, "display": "front",
            "scroll_rate": 0, "scroll_start_delay": 0,
            "scroll_repeat_delay": 0, "timeout": 1,
        }],
    }
    request(config.device_url.rstrip("/") + "/api/display/draw",
            data=json.dumps(payload).encode(), headers=headers)


def stop_clock() -> dict:
    with STATE.lock:
        STATE.clock_active = False
        config = STATE.config
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    url = config.device_url.rstrip("/") + "/api/display/draw?" + \
        urllib.parse.urlencode({"application_name": "busy_clock"})
    request(url, headers=headers, method="DELETE")
    LOGGER.info("clock.stop")
    return {"result": "stopped"}


def show_network_now(config: Config) -> dict:
    """GUI-triggered: scan and push the strongest nearby AP to the display immediately."""
    with STATE.lock:
        STATE.clock_active = False
    send_network_result(config, {"ssid": "SCANNING", "signal": "", "unit": ""}, 0)
    snapshot = refresh_network_data(config)
    networks = snapshot["networks"]
    if not networks:
        send_network_result(config, {"ssid": "SCAN UNAVAILABLE", "signal": 0, "unit": ""}, 0)
        LOGGER.info("networks.show scan_empty")
        return {"result": "shown", "network": None}
    network = strongest_unique_networks(networks, limit=1)[0]
    send_network_result(config, network, 1)
    LOGGER.info("networks.show ssid=%r signal=%s%s", network["ssid"], network["signal"], network["unit"])
    return {"result": "shown", "network": network}


async def feed_refresher() -> None:
    """Refresh feeds independently so network latency never stops the marquee."""
    while True:
        with STATE.lock:
            config = STATE.config
        if config.enabled:
            try:
                items, errors = await fetch_all_feeds()
                if not items:
                    raise ValueError("All configured feeds failed")
                with STATE.lock:
                    STATE.last_run = time.time()
                    STATE.last_items = items
                    STATE.last_source = "ALL SECURITY FEEDS"
                    STATE.last_titles = [describe(item) for item in items]
                    STATE.last_error = "; ".join(errors)
                LOGGER.info("feed.refresh.complete available=%d failed=%d", len(items), len(errors))
            except Exception as exc:
                LOGGER.exception("feed.refresh.failed error=%s", exc)
            await asyncio.sleep(max(1, config.interval_minutes) * 60)
        else:
            await asyncio.sleep(2)


async def refresh_button_digest() -> bool:
    """Fetch and cache the physical-button digest now; True on success.

    Shared by the periodic background warm and anything that just cleared the
    digest (e.g. a config save) and needs it back without waiting out a full
    interval_minutes gap.
    """
    try:
        digest = await fetch_digest_fast()
    except Exception as exc:
        LOGGER.warning("rss.digest.warm_failed error=%s", exc)
        return False
    if not digest:
        return False
    with STATE.lock:
        STATE.rss_digest = digest
        STATE.rss_digest_at = time.time()
        STATE.rss_cursor %= len(digest)
    LOGGER.info("rss.digest.warmed available=%d enabled=%d", len(digest), len(FEEDS))
    return True


async def warm_button_digest() -> None:
    """Refresh headlines in the background; physical presses never wait on feeds."""
    while True:
        await refresh_button_digest()
        with STATE.lock:
            interval = max(1, STATE.config.interval_minutes) * 60
        await asyncio.sleep(interval)


NEXT_EVENT: Optional[asyncio.Event] = None
NEXT_LOOP: Optional[asyncio.AbstractEventLoop] = None
SEQUENCE_CANCEL_EVENT: Optional[asyncio.Event] = None
AUTO_PLAY_SKIP_EVENT: Optional[asyncio.Event] = None


def request_next() -> dict:
    """Advance one headline. Interrupts the rotator when running, pushes directly when paused."""
    with STATE.lock:
        config, items = STATE.config, list(STATE.last_items)
        STATE.clock_active = False
        STATE.cursor += 1
        index = STATE.cursor
    if not items:
        raise ValueError("Nothing to show yet — refetch the feeds first")
    if config.enabled and NEXT_EVENT is not None and NEXT_LOOP is not None:
        NEXT_LOOP.call_soon_threadsafe(NEXT_EVENT.set)  # rotator draws it
    else:
        position = index % len(items)
        item = items[position]
        send_to_device(config, item, position + 1, len(items))
    position = index % len(items)
    return {"source": items[position].source, "title": items[position].title,
            "position": position + 1, "total": len(items)}


def display_list(config: Config, items: list[Headline]) -> list[Headline]:
    """The headlines the bar should actually show, per the configured mode.

    Evaluated fresh on every rotation tick so a newer story swaps in as soon as a
    refetch lands, without waiting for a full lap.
    """
    if not items:
        return []
    if config.mode == "newest":
        return [max(items, key=lambda it: it.published or 0.0)]
    if config.mode == "pinned":
        pinned = next((it for it in items if it.source == config.pinned_source), None)
        return [pinned] if pinned else items
    return items  # "rotate"


def show_source(source: str) -> dict:
    """Push one specific feed's current headline to the device immediately.

    Also parks the rotation cursor on it, so if auto-rotation is running it resumes
    from the feed you picked instead of jumping somewhere unrelated.
    """
    with STATE.lock:
        config, items = STATE.config, list(STATE.last_items)
        STATE.clock_active = False
    if not items:
        raise ValueError("Nothing to show yet — refetch the feeds first")
    match = next(((i, it) for i, it in enumerate(items) if it.source == source), None)
    if match is None:
        raise ValueError(f"{source} has no current headline — it may be disabled or still fetching")
    index, item = match
    with STATE.lock:
        STATE.cursor = index  # rotator will advance from here on its next tick
    send_to_device(config, item, index + 1, len(items))
    LOGGER.info("display.show source=%s title=%r", item.source, item.title)
    return {"source": item.source, "title": item.title,
            "position": index + 1, "total": len(items)}


async def headline_rotator() -> None:
    """Show each item for one complete, length-aware scrolling pass."""
    global NEXT_EVENT, NEXT_LOOP
    NEXT_EVENT = asyncio.Event()
    NEXT_LOOP = asyncio.get_running_loop()
    while True:
        with STATE.lock:
            config = STATE.config
            items = display_list(config, list(STATE.last_items))
            index = STATE.cursor
            clock_active = STATE.clock_active
            custom_active = STATE.custom_active
        rss_active = config.enabled or (custom_active and config.custom_action == "rss")
        if rss_active and items and not clock_active:
            position = index % len(items)
            item = items[position]
            try:
                draw_config = replace(config, priority=100) if custom_active else config
                await asyncio.to_thread(send_to_device, draw_config, item, position + 1, len(items))
                with STATE.lock:
                    STATE.cursor = index + 1
            except Exception as exc:
                with STATE.lock:
                    STATE.last_error = str(exc)
                LOGGER.exception("display.failed source=%s error=%s", item.source, exc)
            duration = headline_duration(config, item, position + 1, len(items))
            LOGGER.info("display.wait source=%s seconds=%.2f", item.source, duration)
            try:  # a "next" request cuts the wait short instead of skipping a beat
                await asyncio.wait_for(NEXT_EVENT.wait(), timeout=duration)
                LOGGER.info("display.skip source=%s", item.source)
            except asyncio.TimeoutError:
                pass
            finally:
                NEXT_EVENT.clear()
        else:
            await asyncio.sleep(2)


async def clock_updater() -> None:
    """Atomically swap preloaded minute faces while blinking the centre lamp."""
    shown_minute: Optional[datetime] = None
    prepared_minute: Optional[datetime] = None
    while True:
        with STATE.lock:
            active, config = STATE.clock_active, STATE.config
        if active:
            try:
                now = datetime.now().astimezone()
                minute = now.replace(second=0, microsecond=0)
                if prepared_minute != minute:
                    # Timestamped paths prevent the firmware from briefly resolving a
                    # freshly uploaded minute to an older cached bitmap (e.g. 4:52 at 4:54).
                    slot = minute.strftime("%Y%m%d%H%M")
                    filename = f"clock-{slot}.png"
                    # The base is the only full-screen clock layer. It remains until the
                    # next minute and is never used for blinking.
                    await asyncio.to_thread(send_clock_frame, config,
                                            flip_clock_png(minute, dot_on=not config.clock_blink,
                                                           config=config), filename)
                    prepared_minute = minute
                    shown_minute = minute
                    LOGGER.info("clock.minute time=%s slot=%s", minute.strftime("%I:%M %p"), slot)
                blink_on = (not config.clock_blink or
                            int(time.time() / max(0.25, config.clock_blink_seconds)) % 2 == 0)
                if config.clock_blink and blink_on:
                    await asyncio.to_thread(draw_clock_dot, config)
            except Exception as exc:
                LOGGER.exception("clock.display.failed error=%s", exc)
            now = datetime.now().astimezone()
            tick = max(0.25, config.clock_blink_seconds) if config.clock_blink else 1.0
            await asyncio.sleep(max(0.1, tick - (time.time() % tick)))
        else:
            shown_minute = None
            prepared_minute = None
            await asyncio.sleep(2)


def clear_app(config: Config, application_name: str) -> None:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    url = config.device_url.rstrip("/") + "/api/display/draw?" + \
        urllib.parse.urlencode({"application_name": application_name})
    request(url, headers=headers, method="DELETE")


def show_message(text: str, color: str = "#FFFFFFFF", sound: bool = False) -> dict:
    """Put an operator-authored message on the bar using the existing local transport."""
    text = clean_text(text)[:240]
    if not text:
        raise ValueError("Message cannot be empty")
    if not re.fullmatch(r"#[0-9A-Fa-f]{8}", color):
        raise ValueError("Message color must use #RRGGBBAA format")
    with STATE.lock:
        config = STATE.config
    payload = {
        "application_name": "busy_hub",
        "priority": 100,
        "elements": [{
            "id": "hub-message",
            "type": "text",
            "text": text,
            "font": "small",
            "color": color.upper(),
            "width": 68,
            "align": "mid_left",
            "x": 2,
            "y": 10,
            "display": "front",
            "scroll_rate": 900,
            "scroll_start_delay": 250,
            "scroll_repeat_delay": 800,
            "timeout": 0,
        }],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    base = config.device_url.rstrip("/") + "/api/display/draw"
    try:
        request(base + "?" + urllib.parse.urlencode({"application_name": "busy_hub"}),
                headers=headers, method="DELETE")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    request(base,
            data=json.dumps(payload).encode(), headers=headers, method="POST")
    # Only stop the updater after the new priority-100 layer is safely live.
    # If the device rejects the draw, the current clock remains untouched.
    with STATE.lock:
        STATE.clock_active = False
    if sound:
        try:
            request(config.device_url.rstrip("/") + "/api/audio/play",
                    data=json.dumps({"sound": "notification"}).encode(),
                    headers=headers, method="POST", timeout=5)
        except Exception as exc:
            LOGGER.info("hub.message.sound_unavailable error=%s", exc)
    LOGGER.info("hub.message text=%r color=%s sound=%s", text, color, sound)
    return {"result": "shown", "text": text, "color": color.upper(), "sound": sound}


def release_active_timer(config: Config) -> bool:
    """Release firmware timer ownership so priority-100 Canvas apps can draw."""
    base = config.device_url.rstrip("/")
    raw = request(base + "/api/busy/snapshot", timeout=5)
    snapshot = json.loads(raw).get("snapshot", {})
    if snapshot.get("type") == "NOT_STARTED":
        return False
    payload = {
        "snapshot": {
            "type": "NOT_STARTED",
            "busy_bar_settings": snapshot.get("busy_bar_settings", {}),
        },
        "snapshot_timestamp_ms": int(time.time() * 1000),
    }
    request(base + "/api/busy/snapshot", data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="PUT", timeout=5)
    LOGGER.info("timer.guard.released type=%s", snapshot.get("type"))
    time.sleep(0.08)
    return True


def scan_nearby_networks(config: Config) -> list:
    """Return nearby APs strongest-first using an available local scanner."""
    networks = []
    if shutil.which("nmcli"):
        output = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "device", "wifi", "list",
             "--rescan", "yes"],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout
        for line in output.splitlines():
            parts = line.rsplit(":", 2)
            if len(parts) == 3 and parts[0]:
                networks.append({"ssid": parts[0].replace(r"\:", ":"), "security": parts[1] or "OPEN",
                                 "signal": int(parts[2]), "unit": "%", "scanner": "nmcli"})
    airport = Path("/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport")
    if not networks and airport.exists():
        output = subprocess.run([str(airport), "-s"], capture_output=True, text=True,
                                timeout=20, check=True).stdout
        for line in output.splitlines()[1:]:
            match = re.match(r"^\s*(.*?)\s+([0-9a-f:]{17})\s+(-?\d+)\s+", line, re.I)
            if match and match.group(1):
                networks.append({"ssid": match.group(1).strip(), "security": "",
                                 "signal": int(match.group(3)), "unit": " dBm",
                                 "bssid": match.group(2), "scanner": "airport"})
    swift_scanner = ROOT / "scan_wifi.swift"
    if not networks and sys.platform == "darwin" and shutil.which("swift") and swift_scanner.exists():
        output = subprocess.run(
            ["swift", str(swift_scanner)], capture_output=True, text=True,
            timeout=25, check=True,
        ).stdout
        for line in output.splitlines():
            parts = line.split("\t", 5)
            if len(parts) == 6 and parts[5] != "<hidden>":
                signal, noise, channel, band, bssid, ssid = parts
                networks.append({
                    "ssid": ssid, "bssid": bssid, "security": "",
                    "signal": int(signal), "unit": " dBm", "noise": int(noise),
                    "channel": int(channel), "band": band, "scanner": "CoreWLAN",
                })
    if not networks:
        try:
            raw = request(config.device_url.rstrip("/") + "/api/wifi/networks", timeout=20)
            for entry in json.loads(raw).get("networks", []):
                networks.append({"ssid": entry.get("ssid", "Hidden"),
                                 "security": entry.get("security", ""),
                                 "signal": int(entry.get("rssi", -999)), "unit": " dBm",
                                 "scanner": "BUSY Bar"})
        except Exception as exc:
            LOGGER.info("wifi.scan.device_unavailable error=%s", exc)
    return sorted(networks, key=lambda item: item["signal"], reverse=True)


def refresh_network_data(config: Config) -> dict:
    """Scan and cache a dashboard-friendly network snapshot."""
    scanned_at = time.time()
    error = ""
    try:
        networks = []
        for attempt in range(3):
            networks = scan_nearby_networks(config)
            if len(networks) >= 5:
                break
            LOGGER.info("wifi.scan.retry attempt=%d count=%d", attempt + 1, len(networks))
            time.sleep(0.5)
        if not networks:
            error = "No nearby access points were returned"
    except Exception as exc:
        networks, error = [], str(exc)
    try:
        raw = request(config.device_url.rstrip("/") + "/api/wifi/status", timeout=8)
        device_wifi = json.loads(raw)
    except Exception as exc:
        device_wifi = {"error": str(exc)}
    with STATE.lock:
        STATE.networks = networks
        STATE.network_scanned_at = scanned_at
        STATE.network_scan_error = error
        STATE.device_wifi = device_wifi
    return {
        "scanned_at": scanned_at,
        "count": len(networks),
        "strongest": networks[0] if networks else None,
        "networks": networks,
        "device_wifi": device_wifi,
        "error": error,
    }


# --- Home router (Verizon Fios "CR1000A"-family) client -----------------------
# Login handshake and endpoint layout reverse-engineered by the community
# (github.com/Brishen/verizon_router_client); reimplemented here with stdlib
# only (urllib + http.cookiejar) to match this project's no-dependency design.

_ROUTER_ADD_ROD_RE = re.compile(r'addROD\("(?P<key>[^"]+)",\s*(?P<val>.*?)\);\s*', re.DOTALL)
# The router hands out one login token at a time and appears to support a single
# active admin session; two concurrent login attempts from this server race for
# that slot and the loser's token/session gets invalidated mid-flight (403).
# Serialize every router fetch through this lock so we never race ourselves.
_ROUTER_LOCK = threading.Lock()
_ROUTER_TLS_HOSTNAME = "mynetworksettings.com"


def _router_arc_md5(s: str) -> str:
    """JS ArcMD5(): md5(8-bit-truncated chars) as hex, then sha512 of that hex string."""
    md5_hex = hashlib.md5(bytes(ord(ch) & 0xFF for ch in s)).hexdigest()
    return hashlib.sha512(md5_hex.encode("ascii")).hexdigest()


def _router_parse_js_literal(s: str) -> Any:
    v = s.strip()
    v = re.sub(r"\bnull\b", "None", v)
    v = re.sub(r"\btrue\b", "True", v)
    v = re.sub(r"\bfalse\b", "False", v)
    v = v.replace(r"\/", "/")
    try:
        return ast.literal_eval(v)
    except Exception:
        return v.strip('"\' ')


def _router_extract_js_object(src: str, call_prefix: str) -> str:
    """Extract the {...} argument from `addROD("key", {...});` via brace matching
    (safe against nested braces/strings), e.g. for known_device_list."""
    i = src.find(call_prefix)
    if i < 0:
        raise ValueError(f"{call_prefix!r} not found in router response")
    j = src.find("{", i)
    if j < 0:
        raise ValueError("No '{' found after call prefix")
    depth, in_str, esc = 0, False, False
    for k in range(j, len(src)):
        ch = src[k]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[j:k + 1]
    raise ValueError("Unbalanced braces in router response")


def _router_parse_addrod(text: str) -> dict[str, Any]:
    return {m.group("key"): _router_parse_js_literal(m.group("val"))
            for m in _ROUTER_ADD_ROD_RE.finditer(text)}


def _router_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # local router, self-signed cert issued for a hostname we don't use
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=ctx),
    )


def _router_headers(config: Config, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Match the CR1000A web client's hostname-aware request headers."""
    base = config.router_url.rstrip("/")
    headers = {"Referer": base + "/"}
    hostname = urllib.parse.urlparse(base).hostname or ""
    try:
        socket.inet_pton(socket.AF_INET6 if ":" in hostname else socket.AF_INET, hostname)
        headers["Host"] = _ROUTER_TLS_HOSTNAME
    except OSError:
        pass
    if config.router_sysauth:
        headers["Cookie"] = f"sysauth={config.router_sysauth}"
    if extra:
        headers.update(extra)
    return headers


def _router_open(opener: urllib.request.OpenerDirector, req: urllib.request.Request, stage: str):
    try:
        return opener.open(req, timeout=10)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        LOGGER.warning("router.%s.http_error code=%s body=%r", stage, exc.code, body)
        raise


def _router_login(config: Config) -> urllib.request.OpenerDirector:
    """Log into the router admin UI; returns an opener carrying the session cookie."""
    if not config.router_password:
        raise ValueError("Router admin password isn't saved — add it in Settings first")
    base = config.router_url.rstrip("/")
    opener = _router_opener()
    headers = _router_headers(config)
    status_req = urllib.request.Request(base + "/loginStatus.cgi", headers=headers)
    with _router_open(opener, status_req, "login_status") as resp:
        status = json.loads(resp.read())
    LOGGER.info("router.login_status.ok islogin=%s", status.get("islogin"))
    token = status.get("loginToken")
    if not isinstance(token, str) or len(token) != 32:
        raise RuntimeError("Router didn't return a login token — wrong address, or firmware differs")
    token = token.lower()
    luci_username = _router_arc_md5(config.router_username)
    luci_password = hashlib.sha512((token + _router_arc_md5(config.router_password)).encode("ascii")).hexdigest()
    payload = urllib.parse.urlencode({
        "luci_username": luci_username, "luci_password": luci_password,
        # Match verizon-router-client's safe default. Persistent sessions survive
        # app restarts and eventually exhaust the router's small session table.
        "luci_view": "Mobile", "luci_token": token, "luci_keep_login": "0",
    }).encode()
    login_req = urllib.request.Request(
        base + "/login.cgi", data=payload,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    )
    with _router_open(opener, login_req, "login_post") as resp:
        body = resp.read().decode("utf-8", "replace")
    jar_names = [c.name for handler in opener.handlers
                 if isinstance(handler, urllib.request.HTTPCookieProcessor)
                 for c in handler.cookiejar]
    LOGGER.info("router.login_post.ok body=%r cookies=%s", body[:200], jar_names)
    sysauth = next((cookie.value for handler in opener.handlers
                    if isinstance(handler, urllib.request.HTTPCookieProcessor)
                    for cookie in handler.cookiejar if cookie.name == "sysauth"), "")
    if sysauth:
        with STATE.lock:
            STATE.config.router_sysauth = sysauth
            save_config(STATE.config)
        LOGGER.info("router.session_token.saved")
    return opener


_router_session: dict = {"opener": None, "retry_after": 0.0, "auth_error": ""}


def _router_get_session(config: Config) -> urllib.request.OpenerDirector:
    """Reuse a still-valid login session across calls instead of logging in
    fresh every time. The router caps concurrent sessions (maxsession: 10) and
    doesn't appear to expire them promptly — repeated fresh logins under
    frequent polling exhausted that cap and login.cgi started intermittently
    rejecting valid credentials (flag: 2 / 403), even with luci_keep_login=0.
    """
    if time.monotonic() < _router_session["retry_after"]:
        raise RuntimeError(_router_session["auth_error"])
    opener = _router_session.get("opener")
    if opener is None and config.router_sysauth:
        opener = _router_opener()
    if opener is not None:
        try:
            base = config.router_url.rstrip("/")
            status_req = urllib.request.Request(base + "/loginStatus.cgi",
                                                headers=_router_headers(config))
            with _router_open(opener, status_req, "session_check") as resp:
                status = json.loads(resp.read())
            if status.get("islogin") in (1, "1", True):
                _router_session["opener"] = opener
                return opener
        except Exception:
            pass
    try:
        opener = _router_login(config)
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise
        message = ("Router rejected the admin login (403). Login persistence is now disabled; "
                   "wait for old sessions to expire or sign out of the router UI, then retry.")
        _router_session.update(opener=None, retry_after=time.monotonic() + 60,
                               auth_error=message)
        raise RuntimeError(message) from exc
    _router_session["opener"] = opener
    _router_session["retry_after"] = 0.0
    _router_session["auth_error"] = ""
    return opener


def _router_keepalive_once(config: Config) -> None:
    """Touch loginStatus through the cached sysauth session without relogging."""
    if not config.router_sysauth:
        return
    with _ROUTER_LOCK:
        opener = _router_get_session(config)
        base = config.router_url.rstrip("/")
        req = urllib.request.Request(base + "/loginStatus.cgi",
                                     headers=_router_headers(config))
        with _router_open(opener, req, "keepalive") as resp:
            status = json.loads(resp.read())
        if status.get("islogin") not in (1, "1", True):
            raise RuntimeError("Router session token is no longer authenticated")
        LOGGER.info("router.keepalive.ok")


async def router_keepalive() -> None:
    """Keep one token-backed router session alive instead of creating new sessions."""
    while True:
        with STATE.lock:
            config = STATE.config
            enabled = bool(config.router_sysauth)
        if enabled:
            try:
                await asyncio.to_thread(_router_keepalive_once, config)
            except Exception as exc:
                LOGGER.warning("router.keepalive.failed error=%s", exc)
        await asyncio.sleep(45)


def router_logout(config: Config, clear_saved_token: bool = True) -> None:
    """Invalidate our sysauth session on the router and forget the local token."""
    token = config.router_sysauth
    if token:
        try:
            base = config.router_url.rstrip("/")
            opener = _router_session.get("opener") or _router_opener()
            req = urllib.request.Request(base + "/logout.cgi",
                                         headers=_router_headers(config))
            with _router_open(opener, req, "logout") as resp:
                resp.read()
            LOGGER.info("router.logout.ok")
        except Exception as exc:
            LOGGER.warning("router.logout.failed error=%s", exc)
    _router_session.update(opener=None, retry_after=0.0, auth_error="")
    if clear_saved_token and token:
        with STATE.lock:
            if STATE.config.router_sysauth == token:
                STATE.config.router_sysauth = ""
                save_config(STATE.config)
        LOGGER.info("router.session_token.cleared")


def _router_get(opener: urllib.request.OpenerDirector, config: Config, path: str) -> str:
    base = config.router_url.rstrip("/")
    req = urllib.request.Request(base + path, headers={
        **_router_headers(config), "Accept": "application/json, text/plain, */*"})
    with _router_open(opener, req, "get_" + path.strip("/").replace("/", "_")) as resp:
        return resp.read().decode("utf-8", "replace")


def _router_fetch_devices(opener: urllib.request.OpenerDirector, config: Config) -> list[dict]:
    text = _router_get(opener, config, "/cgi/cgi_owl.js")
    obj_text = _router_extract_js_object(text, 'addROD("known_device_list",')
    payload = json.loads(obj_text)
    devices = payload.get("known_devices", [])
    if not isinstance(devices, list):
        raise RuntimeError(f"Unexpected known_devices payload: {type(devices)}")
    return devices


def _router_fetch_bandwidth(opener: urllib.request.OpenerDirector, config: Config) -> dict:
    text = _router_get(opener, config, "/cgi/cgi_bandwith.js")  # sic — misspelled in firmware
    rod = _router_parse_addrod(text)
    if not rod:
        raise RuntimeError("No data found in router bandwidth response")
    return rod


def _router_call(config: Config, func):
    """Run `func(opener, config)` against the cached session; if the session
    turned out to be stale mid-use, drop it and retry once with a fresh login
    rather than surfacing a spurious error."""
    opener = _router_get_session(config)
    try:
        return func(opener, config)
    except Exception:
        _router_session["opener"] = None
        opener = _router_get_session(config)
        return func(opener, config)


def fetch_router_devices(config: Config) -> list[dict]:
    """Return the router's known-device list (named clients, wired + wifi)."""
    with _ROUTER_LOCK:
        return _router_call(config, _router_fetch_devices)


def fetch_router_bandwidth(config: Config) -> dict:
    """Return per-host traffic stats + bandwidth history from the router."""
    with _ROUTER_LOCK:
        return _router_call(config, _router_fetch_bandwidth)


_ROUTER_DEVICE_MAC_KEYS = ("mac", "macAddress", "mac_address", "hw_addr", "hwaddr")
_ROUTER_JUNK_VALUES = {"", "null", "(null)", "n/a", "unknown"}

_LOCAL_MACS: Optional[set] = None


def _local_mac_addresses() -> set:
    """This machine's own interface MACs (Ethernet, Wi-Fi, …), lowercased.
    The box running this server is definitionally active even when the router
    reports its idle Wi-Fi interface as inactive, so we force those to active
    rather than let this host land in History under whichever NIC is idle.
    Cached — interface MACs don't change during a run."""
    global _LOCAL_MACS
    if _LOCAL_MACS is None:
        try:
            out = subprocess.run(["ifconfig"], capture_output=True, text=True,
                                 timeout=5, check=True).stdout
            _LOCAL_MACS = {m.lower() for m in re.findall(r"ether ([0-9a-fA-F:]{17})", out)}
        except Exception:
            _LOCAL_MACS = set()
    return _LOCAL_MACS


def _router_clean(value: Any) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    return "" if text.lower() in _ROUTER_JUNK_VALUES else text


def _router_has_identity(device: dict) -> bool:
    """True when the router actually identifies this device — an assigned name,
    the router's own model guess, a real DHCP hostname, or a manufacturer/product
    (e.g. name="" but suggested_name="MacBook Neo" + Apple/MacBook is "known").
    Only a device with nothing but a MAC (and maybe a bare vendor) is Unknown."""
    if _router_clean(device.get("name")) or _router_clean(device.get("suggested_name")):
        return True
    hostname = _router_clean(device.get("hostname"))
    if hostname and not hostname.lower().startswith("unknown_"):
        return True
    return bool(_router_clean(device.get("device_manufacturer")) or _router_clean(device.get("device_product")))


def _router_device_name(device: dict) -> str:
    """Best human-readable label: user-assigned name, then the router's own
    guess, then a real DHCP hostname, then manufacturer/product, then vendor —
    never the router's "unknown_<mac>" placeholder hostname."""
    name = _router_clean(device.get("name"))
    if name:
        return name
    suggested = _router_clean(device.get("suggested_name"))
    if suggested:
        return suggested
    hostname = _router_clean(device.get("hostname"))
    if hostname and not hostname.lower().startswith("unknown_"):
        return hostname
    manufacturer = _router_clean(device.get("device_manufacturer"))
    product = _router_clean(device.get("device_product"))
    if manufacturer or product:
        return " ".join(part for part in (manufacturer, product) if part)
    vendor = _router_clean(device.get("mac_vendor"))
    if vendor:
        return vendor
    mac = _router_device_mac(device)
    return mac or "Unnamed device"


def _router_device_mac(device: dict) -> str:
    """Lowercase, matching the router's own convention — the join key against
    hosts_trafstat depends on this matching exactly."""
    for key in _ROUTER_DEVICE_MAC_KEYS:
        value = device.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()
    return ""


def fetch_router_overview(config: Config) -> dict:
    """One login, both endpoints: named devices, plus per-host traffic (last hour)
    and bandwidth history, with device names joined onto their MAC where known."""
    with _ROUTER_LOCK:
        devices, bandwidth = _router_call(
            config, lambda opener, config: (
                _router_fetch_devices(opener, config), _router_fetch_bandwidth(opener, config),
            ))

    traffic_by_mac = {}
    trafstat = bandwidth.get("hosts_trafstat")
    if isinstance(trafstat, dict):
        hour = trafstat.get(3600) or trafstat.get("3600") or {}
        if isinstance(hour, dict):
            # Normalize case defensively — router's own device.mac field is
            # lowercase; this join breaks silently (all-zero traffic) if these
            # keys ever don't match that exactly.
            traffic_by_mac = {str(mac).lower(): stats for mac, stats in hour.items()}

    local_macs = _local_mac_addresses()
    clients = []
    for device in devices:
        mac = _router_device_mac(device)
        stats = traffic_by_mac.get(mac, {}) if mac else {}
        # This host is always active — it's running this server — even if the
        # router marks its idle Wi-Fi interface inactive.
        is_active = bool(device.get("activity")) or (mac in local_macs)
        clients.append({
            "name": _router_device_name(device),
            "mac": mac,
            "active": is_active,
            "is_self": mac in local_macs,
            "has_name": _router_has_identity(device),
            "raw": device,
            "bytes_rx": int(stats.get("bytes_rx", 0)) if isinstance(stats, dict) else 0,
            "bytes_tx": int(stats.get("bytes_tx", 0)) if isinstance(stats, dict) else 0,
        })
    clients.sort(key=lambda c: c["bytes_rx"] + c["bytes_tx"], reverse=True)

    history = bandwidth.get("get_history_rates")
    if not isinstance(history, list):
        history = []

    return {"clients": clients, "history_rates": history, "device_count": len(clients)}


def strongest_unique_networks(networks: list, limit: int = 5) -> list:
    """Select strongest distinct SSIDs while preserving full BSSID data elsewhere."""
    result, seen = [], set()
    for network in networks:
        ssid = clean_text(network.get("ssid", "")).strip(" |")
        key = ssid.casefold()
        if not ssid or key in seen:
            continue
        seen.add(key)
        result.append({**network, "ssid": ssid})
        if len(result) == limit:
            break
    return result


def network_result_png(config: Config, network: dict, rank: int) -> bytes:
    """Render a compact two-line AP card while keeping the element type as image."""
    background = hex_to_pixel(config.clock_background[:7])
    foreground = hex_to_pixel(config.clock_accent[:7]) if rank % 2 or rank == 0 else (255, 255, 255, 255)
    pixels = [[background for _ in range(72)] for _ in range(16)]
    extra = {
        "-": ("000", "000", "111", "000", "000"),
        "|": ("010", "010", "010", "010", "010"),
        " ": ("000", "000", "000", "000", "000"),
        ".": ("000", "000", "000", "000", "010"),
    }

    def draw_line(text: str, y: int) -> None:
        text = clean_text(text).upper()[:18]
        width = max(0, len(text) * 4 - 1)
        left = max(0, (72 - width) // 2)
        for index, char in enumerate(text):
            glyph = FONT_3X5.get(char, extra.get(char, extra[" "]))
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1" and left + index * 4 + gx < 72:
                        pixels[y + gy][left + index * 4 + gx] = foreground

    if rank == 0:
        draw_line("SCANNING", 2)
        draw_line("PLEASE WAIT", 9)
    else:
        ssid = clean_text(network["ssid"]).strip(" |")[:18]
        unit = network["unit"].strip().upper()
        signal = f"{network['signal']} {unit}" if unit else str(network["signal"])
        draw_line(ssid, 2)
        draw_line(f"{rank} | {signal}", 9)
    return encode_png(pixels)


def send_network_result(config: Config, network: dict, rank: int) -> None:
    """Atomically replace the clock image with an alternating-color AP card."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    base = config.device_url.rstrip("/")
    filename = f"network-{rank}.png"
    upload_clock_asset(config, network_result_png(config, network, rank), filename)
    payload = {
        "application_name": "busy_clock", "priority": 100,
        "elements": [{
            "id": "flip-clock", "type": "image", "path": filename,
            "align": "top_left", "x": 0, "y": 0, "display": "front",
            "opacity": 100, "timeout": 0,
        }],
    }
    release_active_timer(config)
    try:
        request(base + "/api/display/draw", data=json.dumps(payload).encode(), headers=headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        release_active_timer(config)
        request(base + "/api/display/draw", data=json.dumps(payload).encode(), headers=headers)


def human_bytes(n) -> str:
    """Compact byte size for the 72px bar: 1.9MB, 512KB, 40GB (no decimal >=100)."""
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.0f}{unit}" if n >= 100 else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.0f}TB"


def bar_two_line_png(line1: str, line2: str) -> bytes:
    """Render client data in a fixed Flipper-inspired orange/white palette."""
    background = (5, 5, 6, 255)
    orange = (255, 130, 0, 255)
    white = (255, 255, 255, 255)
    pixels = [[background for _ in range(72)] for _ in range(16)]
    extra = {"-": ("000", "000", "111", "000", "000"), "|": ("010", "010", "010", "010", "010"),
             " ": ("000", "000", "000", "000", "000"), ".": ("000", "000", "000", "000", "010"),
             "/": ("001", "001", "010", "100", "100"), ":": ("000", "010", "000", "010", "000")}

    def draw_line(text: str, y: int, color: Pixel) -> None:
        text = clean_text(text).upper()[:18]
        width = max(0, len(text) * 4 - 1)
        left = max(0, (72 - width) // 2)
        for index, char in enumerate(text):
            glyph = FONT_3X5.get(char, extra.get(char, extra[" "]))
            for gy, row in enumerate(glyph):
                for gx, bit in enumerate(row):
                    if bit == "1" and left + index * 4 + gx < 72:
                        pixels[y + gy][left + index * 4 + gx] = color

    draw_line(line1, 2, orange)
    draw_line(line2, 9, white)
    return encode_png(pixels)


def send_bar_screen(config: Config, line1: str, line2: str, slot: int) -> None:
    """Push one two-line client screen to the bar (same atomic swap as AP cards)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    base = config.device_url.rstrip("/")
    filename = f"client-{slot}.png"
    upload_clock_asset(config, bar_two_line_png(line1, line2), filename)
    payload = {"application_name": "busy_clock", "priority": 100, "elements": [{
        "id": "flip-clock", "type": "image", "path": filename,
        "align": "top_left", "x": 0, "y": 0, "display": "front", "opacity": 100, "timeout": 0,
    }]}
    release_active_timer(config)
    try:
        request(base + "/api/display/draw", data=json.dumps(payload).encode(), headers=headers)
    except urllib.error.HTTPError as exc:
        if exc.code != 409:
            raise
        release_active_timer(config)
        request(base + "/api/display/draw", data=json.dumps(payload).encode(), headers=headers)


def client_bar_screens(overview: dict) -> list:
    """Build the client screens the bar shows in place of SSIDs: busiest active
    device, overall down/up totals, and the current throughput rate."""
    clients = [c for c in overview.get("clients", []) if c.get("active")]
    screens = []
    if clients:
        top = max(clients, key=lambda c: c["bytes_rx"] + c["bytes_tx"])
        screens.append((f"TOP: {top['name']}", human_bytes(top["bytes_rx"] + top["bytes_tx"])))
    total_rx = sum(c["bytes_rx"] for c in overview.get("clients", []))
    total_tx = sum(c["bytes_tx"] for c in overview.get("clients", []))
    screens.append((f"D {human_bytes(total_rx)}", f"U {human_bytes(total_tx)}"))
    hist = overview.get("history_rates") or []
    dl = hist[0][-1] if len(hist) > 0 and hist[0] else 0
    ul = hist[1][-1] if len(hist) > 1 and hist[1] else 0
    screens.append(("NET NOW", f"D {human_bytes(dl)} U {human_bytes(ul)}"))
    return screens


def show_clients_now(config: Config) -> dict:
    """GUI-triggered: pull router client data and cycle the client screens on the bar."""
    with STATE.lock:
        STATE.clock_active = False
    send_bar_screen(config, "LOADING", "CLIENTS", 0)
    overview = fetch_router_overview(config)
    screens = client_bar_screens(overview)
    for slot, (l1, l2) in enumerate(screens, 1):
        send_bar_screen(config, l1, l2, slot)
        time.sleep(3)
    active = sum(1 for c in overview.get("clients", []) if c.get("active"))
    LOGGER.info("clients.show active=%d screens=%d", active, len(screens))
    return {"result": "shown", "active": active, "screens": len(screens)}


def send_plain_headline(config: Config, item: Headline, rank: int, timeout: int = 7) -> None:
    """Show one digest item with the same pixel logo used by normal RSS pushes."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.api_key:
        headers["X-API-Key"] = config.api_key
    filename, text_x, color = upload_icon(config, item.source, "busy_clock")
    age = format_age(item.published)
    title = clean_text(item.title) + (f"  |  {age}" if age else "")
    payload = {
        "application_name": "busy_clock", "priority": 100,
        "elements": [{
            "id": "rss-clean-bg", "type": "rectangle", "x": 0, "y": 0,
            "width": 72, "height": 16, "fill": "solid",
            "fill_colors": [config.clock_background], "border_width": 0,
            "display": "front", "timeout": timeout,
        }, {
            "id": "rss-feed-logo", "type": "image", "path": filename,
            "align": "mid_left", "x": 0, "y": 8,
            "display": "front", "timeout": timeout,
        }, {
            "id": "rss-clean-text", "type": "text", "text": title[:500],
            "font": "tiny", "color": color, "width": 72 - text_x,
            "align": "mid_left", "x": text_x, "y": 8, "display": "front",
            "scroll_rate": 850, "scroll_start_delay": 300,
            "scroll_repeat_delay": 500, "timeout": timeout,
        }],
    }
    release_active_timer(config)
    request(config.device_url.rstrip("/") + "/api/display/draw",
            data=json.dumps(payload).encode(), headers=headers)


async def show_strongest_network() -> None:
    """Pause the clock, show the strongest AP, then return to the live clock."""
    with STATE.lock:
        config = STATE.config
        STATE.clock_active = False
        STATE.network_scan_active = True
        STATE.network_sequence_cancelled = False
    if SEQUENCE_CANCEL_EVENT:
        SEQUENCE_CANCEL_EVENT.clear()

    async def wait_or_cancel(seconds: float) -> bool:
        if not SEQUENCE_CANCEL_EVENT:
            await asyncio.sleep(seconds)
            return False
        try:
            await asyncio.wait_for(SEQUENCE_CANCEL_EVENT.wait(), timeout=seconds)
            return True
        except asyncio.TimeoutError:
            return False
    try:
        await asyncio.to_thread(send_network_result, config, {
            "ssid": "SCANNING", "signal": "", "unit": "",
        }, 0)
        LOGGER.info("wifi.display scanning")
        with STATE.lock:
            cached_headlines = list(STATE.last_items)
        digest_task = None if cached_headlines else asyncio.create_task(fetch_digest_fast())
        snapshot = await asyncio.to_thread(refresh_network_data, config)
        networks = snapshot["networks"]
        if networks:
            closest = networks[0]
            security = f" | {closest['security']}" if closest["security"] else ""
            text = f"{closest['ssid']} | {closest['signal']}{closest['unit']}{security}"
            LOGGER.info("wifi.scan.closest ssid=%r signal=%s%s count=%d",
                        closest["ssid"], closest["signal"], closest["unit"], len(networks))
        else:
            LOGGER.warning("wifi.scan.empty")
        if networks:
            displayed = strongest_unique_networks(networks)
            for rank, network in enumerate(displayed, 1):
                await asyncio.to_thread(send_network_result, config, network, rank)
                LOGGER.info("wifi.display rank=%d ssid=%r signal=%s%s",
                            rank, network["ssid"], network["signal"], network["unit"])
                if await wait_or_cancel(3):
                    return
            with STATE.lock:
                headlines = list(STATE.last_items)
            if not headlines:
                headlines = await digest_task if digest_task else []
                with STATE.lock:
                    STATE.last_items = headlines
            # The physical START sequence is deliberately a five-source digest,
            # independent of the normal GUI playback mode ("newest", etc.).
            digest, seen_sources = [], set()
            for item in headlines:
                if item.source in seen_sources:
                    continue
                seen_sources.add(item.source)
                digest.append(item)
                if len(digest) == 5:
                    break
            for rank, item in enumerate(digest, 1):
                duration = min(24, max(7, 1.5 + len(clean_text(item.title)) * 0.32))
                await asyncio.to_thread(send_plain_headline, config, item, rank,
                                        math.ceil(duration + 1))
                LOGGER.info("rss.clean.display rank=%d source=%s title=%r",
                            rank, item.source, item.title)
                if await wait_or_cancel(duration):
                    return
        else:
            await asyncio.to_thread(send_network_result, config, {
                "ssid": "SCAN UNAVAILABLE", "signal": 0, "unit": "",
            }, 0)
            await asyncio.sleep(5)
    except Exception as exc:
        LOGGER.warning("wifi.scan.failed error=%s", exc)
    finally:
        with STATE.lock:
            still_custom = STATE.custom_active
            STATE.network_scan_active = False
            STATE.network_sequence_cancelled = False
        if still_custom:
            await asyncio.to_thread(show_clock)


async def auto_play_digest() -> None:
    """One press runs the whole thing: every enabled feed back-to-back (each a
    full scroll pass, source + timestamp), then up to 5 nearby APs, then back
    to the live clock. A further press advances immediately to the next item
    (AUTO_PLAY_SKIP_EVENT) instead of waiting out the current one's timer;
    SEQUENCE_CANCEL_EVENT (from elsewhere — the physical dial leaving CUSTOM)
    stops the whole run instead of just skipping one item."""
    with STATE.lock:
        config = STATE.config
        digest = list(STATE.rss_digest)
        STATE.button_stage = "auto"
        STATE.rss_mode_active = True
        STATE.clock_active = False
        STATE.auto_play_active = True
        # Mirrors what a physical press already sets — makes the finally
        # block's "am I still supposed to be on custom" check below correct
        # regardless of whether this run started from hardware or the GUI.
        STATE.custom_active = True
    if SEQUENCE_CANCEL_EVENT:
        SEQUENCE_CANCEL_EVENT.clear()
    if AUTO_PLAY_SKIP_EVENT:
        AUTO_PLAY_SKIP_EVENT.clear()

    async def wait_step(seconds: float) -> str:
        """"timeout" (ran the full duration), "skip" (advance now), or "cancel" (stop the run)."""
        events = [event for event in (SEQUENCE_CANCEL_EVENT, AUTO_PLAY_SKIP_EVENT) if event]
        if not events:
            await asyncio.sleep(seconds)
            return "timeout"
        waiters = {asyncio.ensure_future(event.wait()): event for event in events}
        done, pending = await asyncio.wait(waiters, timeout=seconds, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if not done:
            return "timeout"
        fired = waiters[next(iter(done))]
        if fired is SEQUENCE_CANCEL_EVENT:
            return "cancel"
        AUTO_PLAY_SKIP_EVENT.clear()
        return "skip"

    try:
        for index, item in enumerate(digest):
            with STATE.lock:
                STATE.rss_cursor = index
            try:
                duration = min(24, max(7, 1.5 + len(clean_text(item.title)) * 0.32))
                await asyncio.to_thread(send_plain_headline, config, item, index + 1,
                                        math.ceil(duration + 1))
                LOGGER.info("rss.autoplay.display position=%d/%d source=%s title=%r",
                            index + 1, len(digest), item.source, item.title)
            except Exception as exc:
                # One feed failing to draw (transient device/HTTP error) shouldn't
                # abort the whole run — skip it and move on to the next one.
                LOGGER.warning("rss.autoplay.display_failed source=%s error=%s", item.source, exc)
                continue
            outcome = await wait_step(duration)
            if outcome == "cancel":
                LOGGER.info("rss.autoplay.cancelled")
                return
            if outcome == "skip":
                LOGGER.info("rss.autoplay.skipped position=%d/%d", index + 1, len(digest))
        # Client info stage — busiest active device, overall down/up, live rate.
        # Login round-trip takes a moment; paint a placeholder so there's no gap.
        try:
            await asyncio.to_thread(send_bar_screen, config, "LOADING", "CLIENTS", 0)
        except Exception as exc:
            LOGGER.warning("rss.autoplay.client_placeholder_failed error=%s", exc)
        try:
            overview = await asyncio.to_thread(fetch_router_overview, config)
            screens = client_bar_screens(overview)
        except Exception as exc:
            LOGGER.warning("rss.autoplay.client_fetch_failed error=%s", exc)
            screens = [("NO ROUTER", "DATA", True)]
        for slot, (l1, l2) in enumerate(screens, 1):
            try:
                await asyncio.to_thread(send_bar_screen, config, l1, l2, slot)
                LOGGER.info("rss.autoplay.client slot=%d %r / %r", slot, l1, l2)
            except Exception as exc:
                LOGGER.warning("rss.autoplay.client_failed error=%s", exc)
                continue
            outcome = await wait_step(4)
            if outcome == "cancel":
                LOGGER.info("rss.autoplay.cancelled")
                return
            if outcome == "skip":
                LOGGER.info("rss.autoplay.skipped client_slot=%d", slot)
    finally:
        with STATE.lock:
            STATE.auto_play_active = False
            STATE.rss_mode_active = False
            STATE.rss_cursor = -1
            still_custom = STATE.custom_active
        LOGGER.info("rss.autoplay.done")
        if still_custom:
            await asyncio.to_thread(show_clock)


async def register_start_press() -> None:
    """START while idle begins the auto-play run. A press while it's already
    running advances immediately to the next feed/network instead of waiting
    out the current item's timer — it never returns to clock from a START
    press alone (only from leaving CUSTOM entirely, or reaching the end)."""
    with STATE.lock:
        digest = list(STATE.rss_digest)
        auto_playing = STATE.auto_play_active
    if auto_playing:
        LOGGER.info("rss.autoplay.skip_requested")
        if AUTO_PLAY_SKIP_EVENT:
            AUTO_PLAY_SKIP_EVENT.set()
        return
    if not digest:
        LOGGER.warning("rss.button.empty digest_not_ready")
        return
    asyncio.create_task(auto_play_digest())


async def push_enabled_feeds() -> dict:
    """Refresh every enabled feed and start the complete digest from the web UI."""
    with STATE.lock:
        already_playing = STATE.auto_play_active
    if already_playing:
        await register_start_press()
        return {"result": "skipped", "feeds": len(STATE.rss_digest)}
    if not await refresh_button_digest():
        raise ValueError("None of the enabled RSS feeds returned a headline")
    with STATE.lock:
        count = len(STATE.rss_digest)
    await register_start_press()
    return {"result": "started", "feeds": count}


async def accept_start_press(origin: str) -> None:
    """Accept one authoritative firmware snapshot edge per physical press.

    The firmware's websocket occasionally fires two "start" events for a
    single physical press, roughly 0.4-0.9s apart (confirmed in busy-rss.log).
    That was harmless under the old one-step-per-press design (worst case: an
    extra step) but is now start/cancel — a stray duplicate instantly cancels
    what the first event just started. 1.5s comfortably clears the observed
    dupe gap while still letting a deliberate quick double-press cancel.
    """
    now = time.monotonic()
    with STATE.lock:
        elapsed = now - STATE.control_last_press
        if elapsed < 1.5:
            LOGGER.info("custom.start.repeat_ignored origin=%s elapsed=%.2f", origin, elapsed)
            return
        STATE.control_last_press = now
    LOGGER.info("custom.start.accepted origin=%s", origin)
    await register_start_press()


async def trigger_network_scan() -> None:
    """Start one scan with shared debounce, regardless of which device signal arrived first."""
    now = time.monotonic()
    with STATE.lock:
        active = STATE.custom_active
        elapsed = now - STATE.custom_last_start
        if active and STATE.network_scan_active and elapsed >= 3:
            STATE.network_sequence_cancelled = True
            STATE.custom_last_start = now
            LOGGER.info("custom.start.cancel_to_clock")
            if SEQUENCE_CANCEL_EVENT:
                SEQUENCE_CANCEL_EVENT.set()
            return
        allowed = active and not STATE.network_scan_active and elapsed >= 3
        if allowed:
            STATE.custom_last_start = now
    if allowed:
        LOGGER.info("custom.start.scan")
        asyncio.create_task(show_strongest_network())
    elif active:
        LOGGER.info("custom.start.debounced")


async def handle_immediate_start() -> None:
    """Beat the firmware CUSTOM start screen, then process one physical press."""
    with STATE.lock:
        config = STATE.config
        # START itself proves the CUSTOM control path is active even when the
        # preceding selector WebSocket event was dropped during reconnect.
        STATE.custom_active = True
    # The input edge can arrive just before the firmware snapshot changes. Give
    # it a few very short chances so Canvas owns the screen before it is visible.
    for _ in range(4):
        try:
            if await asyncio.to_thread(release_active_timer, config):
                break
        except Exception as exc:
            LOGGER.info("custom.start.release_retry error=%s", exc)
        await asyncio.sleep(0.06)
    await accept_start_press("websocket")


async def handle_device_control(event: str) -> None:
    with STATE.lock:
        config = STATE.config
        network_scan_active = STATE.network_scan_active
    if network_scan_active and event in {"custom", "other"}:
        LOGGER.info("custom.switch.ignored_during_scan event=%s", event)
        return
    if event == "custom":
        now = time.monotonic()
        with STATE.lock:
            if now - STATE.selector_last_custom < 3.5:
                LOGGER.info("custom.switch.replay_ignored")
                return
            STATE.selector_last_custom = now
            STATE.custom_active = True
        LOGGER.info("custom.switch.clock")
        await asyncio.to_thread(show_clock)
    elif event == "start":
        # The snapshot monitor only ever sees the firmware's own CUSTOM timer
        # rise once (on first entry); it stays released after that and never
        # edges again on later presses. This websocket edge is what actually
        # fires per physical press once the post-subscribe replay window
        # (controls_ready_at, in stream_device_controls) has passed, so it is
        # the live per-press trigger; accept_start_press()'s own debounce
        # absorbs any duplicate from the snapshot path firing for the same press.
        with STATE.lock:
            custom_active = STATE.custom_active
        if custom_active:
            await handle_immediate_start()
        else:
            LOGGER.info("custom.start.websocket_ignored")
    else:
        # The input stream repeats several non-CUSTOM selector values during a
        # single physical transition — react to the first one (same 3.5s
        # debounce already used for CUSTOM entry) and swallow the repeats,
        # rather than ignoring the exit forever. Priority-100 means our clock
        # otherwise stays frontmost over every other physical mode/app.
        now = time.monotonic()
        with STATE.lock:
            already_seen = now - STATE.selector_last_other < 3.5
            was_custom = STATE.custom_active
            STATE.selector_last_other = now
            if not already_seen and was_custom:
                STATE.custom_active = False
        if not already_seen and was_custom:
            LOGGER.info("custom.switch.exit")
            if SEQUENCE_CANCEL_EVENT:
                SEQUENCE_CANCEL_EVENT.set()  # stop an in-flight auto-play run too
            await asyncio.to_thread(stop_clock)
        else:
            LOGGER.info("custom.switch.noncustom_ignored")


async def custom_selector_monitor() -> None:
    """Maintain a gap-free input stream so a quick CUSTOM then START is never missed."""
    loop = asyncio.get_running_loop()
    while True:
        with STATE.lock:
            config = STATE.config
        try:
            def publish(event: str) -> None:
                loop.call_soon_threadsafe(asyncio.create_task, handle_device_control(event))
            await asyncio.to_thread(stream_device_controls, config, publish)
        except Exception as exc:
            LOGGER.warning("custom.websocket.failed error=%s", exc)
            await asyncio.sleep(0.35)


async def custom_control_monitor() -> None:
    """Release a firmware CUSTOM timer lock if START also starts the built-in timer."""
    profile_id = ""
    profile_was_running = False
    last_trigger = 0.0
    while True:
        with STATE.lock:
            config = STATE.config
        try:
            if not profile_id:
                raw = await asyncio.to_thread(
                    request, config.device_url.rstrip("/") + "/api/busy/profiles/custom")
                profile_id = json.loads(raw).get("id", "")
                LOGGER.info("custom.profile id=%s", profile_id)
            raw = await asyncio.to_thread(
                request, config.device_url.rstrip("/") + "/api/busy/snapshot")
            snapshot = json.loads(raw).get("snapshot", {})
            active = bool(profile_id and snapshot.get("card_id") == profile_id
                          and snapshot.get("type") != "NOT_STARTED")
            if active and not profile_was_running:
                # Active timers reject Canvas draws with 409. Stop the timer first,
                # then treat this rising edge as a toggle for our own screen.
                stop_payload = {
                    "snapshot": {"type": "NOT_STARTED",
                                 "busy_bar_settings": snapshot.get("busy_bar_settings", {})},
                    "snapshot_timestamp_ms": int(time.time() * 1000),
                }
                await asyncio.to_thread(
                    request, config.device_url.rstrip("/") + "/api/busy/snapshot",
                    data=json.dumps(stop_payload).encode(),
                    headers={"Content-Type": "application/json"}, method="PUT")
                await asyncio.sleep(0.25)
                last_trigger = time.monotonic()
                LOGGER.info("custom.timer.released")
                with STATE.lock:
                    was_custom = STATE.custom_active
                    STATE.custom_active = True
                if not was_custom:
                    LOGGER.info("custom.snapshot.clock_fallback")
                    await asyncio.to_thread(show_clock)
                await accept_start_press("snapshot")
            profile_was_running = active
        except Exception as exc:
            LOGGER.warning("custom.monitor.failed error=%s", exc)
            profile_id = ""
        with STATE.lock:
            custom_selected = STATE.custom_active
        await asyncio.sleep(0.05 if custom_selected else 0.2)


async def scheduler() -> None:
    global SEQUENCE_CANCEL_EVENT, AUTO_PLAY_SKIP_EVENT
    SEQUENCE_CANCEL_EVENT = asyncio.Event()
    AUTO_PLAY_SKIP_EVENT = asyncio.Event()
    await asyncio.gather(warm_button_digest(), feed_refresher(), headline_rotator(), clock_updater(),
                         custom_control_monitor(), custom_selector_monitor(),
                         hourly_light_scheduler(), router_keepalive())


class Handler(BaseHTTPRequestHandler):
    def json_response(self, status: int, value: dict) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/":
            body = (ROOT / "static" / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")  # always serve the latest UI
            self.end_headers()
            self.wfile.write(body)
        elif path in ("/hub", "/hub/"):
            body = (ROOT / "static" / "bar-hub.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/favicon.ico":
            body = site_favicon_png()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/static/vertex.js":
            body = (ROOT / "static" / "vertex.js").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/config":
            with STATE.lock:
                config = asdict(STATE.config)
                config["api_key"] = ""  # never echo secrets into the browser
                config["router_password"] = ""
                config["router_sysauth"] = ""
                status = {"last_run": STATE.last_run, "last_error": STATE.last_error,
                          "last_source": STATE.last_source, "last_titles": STATE.last_titles,
                          "clock_active": STATE.clock_active}
            self.json_response(200, {"config": config, "status": status})
        elif path == "/api/clock/image":
            with STATE.lock:
                config = STATE.config
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            overrides = {}
            for name in CLOCK_PRESET_FIELDS:
                if name not in query:
                    continue
                if name == "clock_blink":
                    overrides[name] = query[name] in ("1", "true", "True")
                elif name == "clock_blink_seconds":
                    try:
                        overrides[name] = float(query[name])
                    except ValueError:
                        pass
                else:
                    overrides[name] = query[name]
            if overrides:
                config = replace(config, **overrides)
            blink_interval = max(0.25, float(config.clock_blink_seconds))
            dot_on = (not config.clock_blink or
                      int(time.time() / blink_interval) % 2 == 0)
            body = flip_clock_png(config=config, dot_on=dot_on)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
        elif path.startswith("/icons/"):
            source = icons_by_filename().get(path[len("/icons/"):])
            if not source:
                self.json_response(404, {"error": "Unknown icon"})
                return
            body = icon_details(source)[1]
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/feeds":
            with STATE.lock:
                config, items = STATE.config, list(STATE.last_items)
            latest = {item.source: item for item in items}
            now = time.time()
            feeds = []
            enabled_total = len(FEEDS)
            position = 0
            for entry in ALL_FEEDS:
                source, url = entry["source"], entry["url"]
                if entry["enabled"]:
                    position += 1
                item = latest.get(source)
                filename, _, text_x, color = icon_details(source)
                editable = is_badge_source(source)
                label, background, foreground = badge_spec(source) if editable else ("", CLEAR, CLEAR)
                feeds.append({
                    "source": source, "url": url, "icon": f"/icons/{filename}",
                    "icon_width": text_x - 3, "text_color": color,
                    "editable": editable, "label": label,
                    "background": pixel_to_hex(background) if editable else "",
                    "foreground": pixel_to_hex(foreground) if editable else "",
                    "customised": source in BADGE_OVERRIDES,
                    "enabled": entry["enabled"], "stock": entry["stock"],
                    "position": position if entry["enabled"] else 0, "total": enabled_total,
                    "title": item.title if item else "",
                    "age": format_age(item.published, now) if item else "",
                    "led": freshness_color(item.published, now) if item and config.led_mode == "freshness"
                           else (config.led_color or UNDATED_COLOR),
                    "marquee": headline_text(config, item, position, enabled_total) if item else "",
                })
            self.json_response(200, {"feeds": feeds})
        elif path == "/api/logs":
            try:
                lines = LOG_PATH.read_text(errors="replace").splitlines()[-250:]
            except FileNotFoundError:
                lines = []
            self.json_response(200, {"log": lines})
        elif path == "/api/inputs":
            with STATE.lock:
                events = list(STATE.input_events)
                custom_active = STATE.custom_active
                auto_play_active = STATE.auto_play_active
            self.json_response(200, {
                "events": events,
                "custom_active": custom_active,
                "auto_play_active": auto_play_active,
                "connected": bool(events),
            })
        elif path == "/api/networks":
            with STATE.lock:
                networks = list(STATE.networks)
                scanned_at = STATE.network_scanned_at
                error = STATE.network_scan_error
                device_wifi = dict(STATE.device_wifi)
            self.json_response(200, {
                "scanned_at": scanned_at, "count": len(networks),
                "strongest": networks[0] if networks else None,
                "networks": networks, "device_wifi": device_wifi, "error": error,
            })
        else:
            self.json_response(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size) or b"{}")
            if path == "/api/config":
                with STATE.lock:
                    current = asdict(STATE.config)
                    if not body.get("api_key"):
                        body.pop("api_key", None)
                    if not body.get("router_password"):
                        body.pop("router_password", None)
                    if not body.get("router_sysauth"):
                        body.pop("router_sysauth", None)
                    current.update(body)
                    config = Config(**current)
                    validate_config(config)
                    STATE.config = config
                    sync_badges(config)
                    sync_feeds(config)
                    STATE.rss_digest = []
                    STATE.rss_digest_at = 0.0
                    STATE.rss_cursor = -1
                    STATE.button_stage = "clock"
                    save_config(config)
                # A saved config can change which feeds/URLs the digest pulls from,
                # so it's cleared above — but don't leave the physical button dead
                # until the next scheduled warm (up to interval_minutes away).
                if NEXT_LOOP is not None:
                    asyncio.run_coroutine_threadsafe(refresh_button_digest(), NEXT_LOOP)
                self.json_response(200, {"result": "saved"})
            elif path == "/api/feed":
                source = body.get("source", "")
                if not any(source == entry["source"] for entry in ALL_FEEDS):
                    raise ValueError(f"Unknown feed {source!r}")
                with STATE.lock:
                    config = STATE.config
                    selection = {entry["source"]: entry["enabled"] for entry in ALL_FEEDS}
                    selection[source] = bool(body.get("enabled"))
                    urls = {entry["source"]: entry["url"] for entry in ALL_FEEDS}
                    config.feeds = [{"source": name, "url": urls[name], "enabled": on}
                                    for name, on in selection.items()]
                    sync_feeds(config)
                    save_config(config)
                LOGGER.info("feed.toggle source=%s enabled=%s active=%d",
                            source, body.get("enabled"), len(FEEDS))
                self.json_response(200, {"source": source, "enabled": bool(body.get("enabled")),
                                         "active": len(FEEDS)})
            elif path == "/api/feeds/add":
                source = re.sub(r"\s+", " ", str(body.get("source", "")).strip()).upper()[:24]
                url = str(body.get("url", "")).strip()
                if not source:
                    raise ValueError("Name the feed")
                if urllib.parse.urlparse(url).scheme not in ("http", "https"):
                    raise ValueError("Feed URL must start with http:// or https://")
                with STATE.lock:
                    config = STATE.config
                    if any(entry["source"] == source for entry in ALL_FEEDS):
                        raise ValueError(f"{source!r} already exists")
                    entries = {entry["source"]: {"source": entry["source"], "url": entry["url"],
                                                 "enabled": entry["enabled"]} for entry in ALL_FEEDS}
                    entries[source] = {"source": source, "url": url, "enabled": True}
                    config.feeds = list(entries.values())
                    sync_feeds(config)
                    save_config(config)
                LOGGER.info("feed.add source=%s url=%s", source, url)
                self.json_response(200, {"source": source, "url": url, "active": len(FEEDS)})
            elif path == "/api/button/start":
                if NEXT_LOOP is None:
                    raise ValueError("Scheduler isn't ready yet")
                with STATE.lock:
                    digest_ready = bool(STATE.rss_digest)
                    was_playing = STATE.auto_play_active
                if not was_playing and not digest_ready:
                    raise ValueError("Feed digest isn't warmed up yet — try again in a few seconds")
                future = asyncio.run_coroutine_threadsafe(register_start_press(), NEXT_LOOP)
                future.result(timeout=5)
                self.json_response(200, {"result": "skipped" if was_playing else "started"})
            elif path == "/api/rss/push":
                if NEXT_LOOP is None:
                    raise ValueError("Scheduler isn't ready yet")
                future = asyncio.run_coroutine_threadsafe(push_enabled_feeds(), NEXT_LOOP)
                self.json_response(200, future.result(timeout=20))
            elif path == "/api/message":
                self.json_response(200, show_message(
                    str(body.get("text", "")),
                    str(body.get("color", "#FFFFFFFF")),
                    bool(body.get("sound")),
                ))
            elif path == "/api/inputs/clear":
                with STATE.lock:
                    STATE.input_events.clear()
                    STATE.last_input_at = None
                self.json_response(200, {"result": "cleared"})
            elif path == "/api/next":
                self.json_response(200, request_next())
            elif path == "/api/networks/scan":
                with STATE.lock:
                    config = STATE.config
                self.json_response(200, refresh_network_data(config))
            elif path == "/api/networks/show":
                with STATE.lock:
                    config = STATE.config
                self.json_response(200, show_clients_now(config))
            elif path == "/api/router/logout":
                with STATE.lock:
                    config = STATE.config
                router_logout(config)
                self.json_response(200, {"result": "logged out"})
            elif path == "/api/router/devices":
                with STATE.lock:
                    config = STATE.config
                devices = fetch_router_devices(config)
                self.json_response(200, {"devices": devices, "count": len(devices)})
            elif path == "/api/router/bandwidth":
                with STATE.lock:
                    config = STATE.config
                self.json_response(200, fetch_router_bandwidth(config))
            elif path == "/api/router/overview":
                with STATE.lock:
                    config = STATE.config
                self.json_response(200, fetch_router_overview(config))
            elif path == "/api/clock":
                self.json_response(200, show_clock())
            elif path == "/api/clock/stop":
                self.json_response(200, stop_clock())
            elif path == "/api/clock/presets":
                name = str(body.get("name", "")).strip()
                if not name:
                    raise ValueError("Preset needs a name")
                preset = validate_clock_preset(body)
                with STATE.lock:
                    config = STATE.config
                    presets = dict(config.clock_presets or {})
                    presets[name] = preset
                    config.clock_presets = presets
                    save_config(config)
                self.json_response(200, {"result": "saved", "name": name, "presets": presets})
            elif path == "/api/clock/presets/delete":
                name = str(body.get("name", ""))
                with STATE.lock:
                    config = STATE.config
                    presets = dict(config.clock_presets or {})
                    presets.pop(name, None)
                    config.clock_presets = presets
                    save_config(config)
                self.json_response(200, {"result": "deleted", "presets": presets})
            elif path == "/api/clock/presets/apply":
                name = str(body.get("name", ""))
                with STATE.lock:
                    config = STATE.config
                    preset = (config.clock_presets or {}).get(name)
                    if not preset:
                        raise ValueError(f"Unknown preset {name!r}")
                    current = asdict(config)
                    current.update(preset)
                    config = Config(**current)
                    validate_config(config)
                    STATE.config = config
                    save_config(config)
                self.json_response(200, {"result": "applied", "name": name, "clock": show_clock()})
            elif path == "/api/show":
                self.json_response(200, show_source(body.get("source", "")))
            elif path == "/api/badge":
                source = body.get("source", "")
                with STATE.lock:
                    config = STATE.config
                    badges = dict(config.badges or {})
                    if body.get("reset"):
                        badges.pop(source, None)
                    else:
                        badges[source] = validate_badge(source, body)
                    config.badges = badges
                    sync_badges(config)
                    save_config(config)
                label, background, foreground = badge_spec(source)
                self.json_response(200, {"source": source, "label": label,
                                         "background": pixel_to_hex(background),
                                         "foreground": pixel_to_hex(foreground)})
            elif path in ("/api/preview", "/api/refresh"):
                self.json_response(200, STATE.refresh(send=path == "/api/refresh"))
            else:
                self.json_response(404, {"error": "Not found"})
        except (ValueError, ET.ParseError, urllib.error.URLError) as exc:
            self.json_response(400, {"error": str(exc)})
        except Exception as exc:
            self.json_response(502, {"error": str(exc)})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}")


def validate_config(config: Config) -> None:
    for label, url in (("Feed URL", config.feed_url), ("AI feed URL", config.alternate_feed_url),
                       ("Device URL", config.device_url)):
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            raise ValueError(f"{label} must start with http:// or https://")
    if not 1 <= config.priority <= 100:
        raise ValueError("Priority must be between 1 and 100")
    if not 1 <= config.interval_minutes <= 1440 or not 1 <= config.item_seconds <= 3600:
        raise ValueError("Interval or display duration is out of range")
    if not 1 <= config.max_items <= 50:
        raise ValueError("Max items must be between 1 and 50")
    if config.font not in {"tiny", "small", "normal", "condensed", "bold", "large", "extra_large", "global"}:
        raise ValueError("Unsupported font")
    if config.led_mode not in {"freshness", "fixed"}:
        raise ValueError("LED mode must be 'freshness' or 'fixed'")
    if config.mode not in {"newest", "rotate", "pinned"}:
        raise ValueError("Mode must be 'newest', 'rotate', or 'pinned'")
    if config.clock_format not in {"12", "24"}:
        raise ValueError("Clock format must be '12' or '24'")
    if config.custom_action not in {"clock", "rss"}:
        raise ValueError("CUSTOM action must be 'clock' or 'rss'")
    if not 1 <= config.clock_blink_seconds <= 5:
        raise ValueError("Clock blink interval must be between 1 and 5 seconds")
    for source, badge in (config.badges or {}).items():
        validate_badge(source, badge)
    for entry in (config.feeds or []):
        if not entry.get("source") or urllib.parse.urlparse(entry.get("url", "")).scheme not in ("http", "https"):
            raise ValueError(f"Feed entry needs a source and an http(s) url: {entry!r}")
    for color in (config.color, config.led_color, config.clock_background,
                  config.clock_card_top, config.clock_card_bottom,
                  config.clock_digits, config.clock_accent, config.hourly_flash_color):
        if color and not re.fullmatch(r"#[0-9A-Fa-f]{8}", color):
            raise ValueError("Colors must use #RRGGBBAA format")


if __name__ == "__main__":
    LOGGER.info("service.start port=%s feeds=%d", os.environ.get("PORT", "8090"), len(FEEDS))
    threading.Thread(target=lambda: asyncio.run(scheduler()), daemon=True).start()
    port = int(os.environ.get("PORT", "8090"))
    print(f"Busy RSS is running at http://localhost:{port}")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)

    def stop_service(signum, frame) -> None:
        LOGGER.info("service.stop signal=%s", signum)
        # shutdown() must run outside the serve_forever thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)
    try:
        server.serve_forever()
    finally:
        with STATE.lock:
            config = STATE.config
        router_logout(config)
        server.server_close()
        LOGGER.info("service.stopped")
