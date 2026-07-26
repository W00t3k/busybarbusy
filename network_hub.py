#!/usr/bin/env python3
"""Live system + Wi-Fi + router visualization on port 8315."""

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import time
import urllib.request

import psutil

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "static" / "network-hub.html"
ALIASES_PATH = ROOT / "network-hub-aliases.json"
BUSY = "http://127.0.0.1:8090"
HISTORY = {key: deque(maxlen=120) for key in ("cpu", "memory", "disk", "down", "up")}
LAST = {"at": 0.0, "recv": 0, "sent": 0}
FAVICON = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
<rect width="32" height="32" rx="7" fill="#070b10"/>
<path d="M5 12a16 16 0 0 1 22 0M9 17a10 10 0 0 1 14 0M13 22a4 4 0 0 1 6 0"
 fill="none" stroke="#3ce7cf" stroke-width="3" stroke-linecap="round"/>
<circle cx="16" cy="26" r="2" fill="#ff6a35"/>
</svg>"""


def human(value):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024


def busy(path, method="GET"):
    request = urllib.request.Request(BUSY + path, data=b"{}" if method == "POST" else None,
                                     headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def client_settings():
    try:
        value = json.loads(ALIASES_PATH.read_text())
        if not isinstance(value, dict):
            return {"aliases": {}, "unknown": []}
        if "aliases" not in value:
            return {"aliases": value, "unknown": []}
        return {
            "aliases": value.get("aliases", {}) if isinstance(value.get("aliases"), dict) else {},
            "unknown": value.get("unknown", []) if isinstance(value.get("unknown"), list) else [],
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"aliases": {}, "unknown": []}


def write_client_settings(value):
    ALIASES_PATH.write_text(json.dumps(value, indent=2) + "\n")


def router_snapshot():
    value = busy("/api/router/overview", "POST")
    settings = client_settings()
    saved = settings["aliases"]
    forced_unknown = set(settings["unknown"])
    for client in value.get("clients", []):
        mac = str(client.get("mac", "")).lower()
        alias = saved.get(mac)
        if mac in forced_unknown:
            client["name"] = mac or "Unknown device"
            client["has_name"] = False
            client["forced_unknown"] = True
        elif alias:
            client["name"] = alias
            client["has_name"] = True
            client["local_alias"] = True
    return value


def save_alias(mac, name):
    mac = mac.strip().lower()
    name = " ".join(name.split())[:40]
    if not mac:
        raise ValueError("Device MAC is required")
    settings = client_settings()
    saved = settings["aliases"]
    if name:
        saved[mac] = name
        settings["unknown"] = [item for item in settings["unknown"] if item != mac]
    else:
        saved.pop(mac, None)
    write_client_settings(settings)
    return {"mac": mac, "name": name}


def set_known(mac, known):
    mac = mac.strip().lower()
    if not mac:
        raise ValueError("Device MAC is required")
    settings = client_settings()
    unknown = set(settings["unknown"])
    if known:
        unknown.discard(mac)
    else:
        unknown.add(mac)
        settings["aliases"].pop(mac, None)
    settings["unknown"] = sorted(unknown)
    write_client_settings(settings)
    return {"mac": mac, "known": known}


def snapshot():
    now = time.time()
    cpu = psutil.cpu_percent(interval=0.1)
    memory = psutil.virtual_memory()
    root = psutil.disk_usage("/")
    io = psutil.net_io_counters()
    elapsed = now - LAST["at"] if LAST["at"] else 0
    down = max(0, (io.bytes_recv - LAST["recv"]) / elapsed) if elapsed else 0
    up = max(0, (io.bytes_sent - LAST["sent"]) / elapsed) if elapsed else 0
    LAST.update(at=now, recv=io.bytes_recv, sent=io.bytes_sent)
    values = {"cpu": cpu, "memory": memory.percent, "disk": root.percent,
              "down": down, "up": up}
    for key, value in values.items():
        HISTORY[key].append(round(value, 2))
    processes = []
    for process in psutil.process_iter(("pid", "name", "cpu_percent", "memory_percent")):
        try:
            info = process.info
            processes.append({"pid": info["pid"], "name": info["name"] or "process",
                              "cpu": round(info["cpu_percent"] or 0, 1),
                              "memory": round(info["memory_percent"] or 0, 1)})
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    processes.sort(key=lambda item: (item["cpu"], item["memory"]), reverse=True)
    volumes = []
    for item in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(item.mountpoint)
            volumes.append({"name": item.mountpoint, "percent": usage.percent,
                            "used": human(usage.used), "total": human(usage.total)})
        except (OSError, PermissionError):
            pass
    interfaces = []
    stats = psutil.net_if_stats()
    counters = psutil.net_io_counters(pernic=True)
    for name, addresses in psutil.net_if_addrs().items():
        stat = stats.get(name)
        if (not stat or not stat.isup or name == "lo0" or
                name.startswith(("utun", "awdl", "llw", "anpi", "gif", "stf"))):
            continue
        ipv4 = next((item.address for item in addresses if item.family == socket.AF_INET), "")
        ipv6 = next((item.address.split("%", 1)[0] for item in addresses
                     if item.family == socket.AF_INET6 and not item.address.startswith("fe80")), "")
        mac = next((item.address for item in addresses
                    if getattr(psutil, "AF_LINK", object()) == item.family), "")
        traffic = counters.get(name)
        if not ipv4 and name != "en0":
            continue
        interfaces.append({
            "name": name, "ipv4": ipv4, "ipv6": ipv6, "mac": mac,
            "speed": stat.speed, "mtu": stat.mtu,
            "received": human(traffic.bytes_recv) if traffic else "0 B",
            "sent": human(traffic.bytes_sent) if traffic else "0 B",
        })
    interfaces.sort(key=lambda item: (item["name"] != "en0", not bool(item["ipv4"]), item["name"]))
    connections = {"established": 0, "listen": 0, "total": 0}
    try:
        for connection in psutil.net_connections(kind="inet"):
            connections["total"] += 1
            if connection.status == psutil.CONN_ESTABLISHED:
                connections["established"] += 1
            elif connection.status == psutil.CONN_LISTEN:
                connections["listen"] += 1
    except (psutil.AccessDenied, PermissionError):
        pass
    return {
        "at": now, "host": socket.gethostname(), "uptime": int(now - psutil.boot_time()),
        "cpu": {"percent": cpu, "cores": psutil.cpu_count(), "load": list(psutil.getloadavg())},
        "memory": {"percent": memory.percent, "used": human(memory.used),
                   "available": human(memory.available), "total": human(memory.total)},
        "disk": {"percent": root.percent, "volumes": volumes[:8]},
        "network": {"down": down, "up": up, "down_label": human(down) + "/s",
                    "up_label": human(up) + "/s", "received": human(io.bytes_recv),
                    "sent": human(io.bytes_sent), "interfaces": interfaces[:12],
                    "connections": connections},
        "processes": processes[:12], "history": {key: list(value) for key, value in HISTORY.items()},
    }


class Handler(BaseHTTPRequestHandler):
    def send_json(self, value, status=200):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/api/system":
                self.send_json(snapshot())
            elif self.path == "/api/wifi":
                self.send_json(busy("/api/networks"))
            elif self.path in ("/", "/index.html"):
                body = PAGE.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/favicon.ico":
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(FAVICON)))
                self.end_headers()
                self.wfile.write(FAVICON)
            elif self.path == "/static/network-particles.js":
                body = (ROOT / "static" / "network-particles.js").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/javascript; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/vendor-icons/"):
                path = ROOT / "static" / "vendor-icons" / Path(self.path).name
                if not path.is_file():
                    self.send_json({"error": "icon not found"}, 404)
                    return
                body = path.read_bytes()
                self.send_response(200)
                media_type = {"svg": "image/svg+xml", "ico": "image/x-icon"}.get(path.suffix.lstrip("."), "image/png")
                self.send_header("Content-Type", media_type)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as error:
            self.send_json({"error": str(error)}, 503)

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size) or b"{}")
            if self.path == "/api/router":
                self.send_json(router_snapshot())
            elif self.path == "/api/wifi/scan":
                self.send_json(busy("/api/networks/scan", "POST"))
            elif self.path == "/api/alias":
                self.send_json(save_alias(str(body.get("mac", "")), str(body.get("name", ""))))
            elif self.path == "/api/known":
                self.send_json(set_known(str(body.get("mac", "")), bool(body.get("known", False))))
            else:
                self.send_json({"error": "not found"}, 404)
        except Exception as error:
            self.send_json({"error": str(error)}, 503)

    def log_message(self, fmt, *args):
        return


if __name__ == "__main__":
    print("Network Hub is running at http://localhost:8315")
    ThreadingHTTPServer(("0.0.0.0", 8315), Handler).serve_forever()
