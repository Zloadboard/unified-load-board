#!/usr/bin/env python3
"""CORS-enabled static file server for Unified Load Board (port 8765).

Serves the project root (index.html, loads.json, city_coords.json, …)
with Access-Control-Allow-Origin: * so GitHub Pages / phone browsers
can fetch live data from this work-PC endpoint (via tunnel).

Prefer launching with pythonw.exe (no console) via silent_start.ps1.
"""
from __future__ import annotations

import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("ULB_PORT", "8765"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CORSRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args):
        # Keep quiet for successful GETs; still surface errors.
        try:
            code = args[1] if len(args) > 1 else ""
            if str(code).startswith("2") or str(code).startswith("3"):
                return
        except Exception:
            pass
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    os.chdir(ROOT)
    # 127.0.0.1 is enough for cloudflared --url http://localhost:8765
    # and keeps the board off the LAN unless you change this.
    host = os.environ.get("ULB_BIND", "127.0.0.1")
    httpd = ThreadingHTTPServer((host, PORT), CORSRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
