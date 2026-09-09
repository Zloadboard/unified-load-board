#!/usr/bin/env python3
"""CORS-enabled static file server for Unified Load Board (port 8765).

Serves the project root (index.html, loads.json, city_coords.json, …)
with Access-Control-Allow-Origin: * so GitHub Pages / phone browsers
can fetch live data from this work-PC endpoint (via tunnel).

Also exposes local scanner Chrome controls (work PC only):
  GET  /api/scanner/status
  POST /api/scanner/show   — unhide CDP Chrome for broker sign-in
  POST /api/scanner/hide   — hide CDP Chrome again (SW_HIDE)

These APIs require the work PC (localhost:8765). GitHub Pages cannot
control scanner Chrome — sign-in from http://localhost:8765/ on the PC.

Prefer launching with pythonw.exe (no console) via silent_start.ps1.
"""
from __future__ import annotations

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORT = int(os.environ.get("ULB_PORT", "8765"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.dirname(os.path.abspath(__file__))
if SCANNER not in sys.path:
    sys.path.insert(0, SCANNER)


def _json_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _scanner_action(action: str) -> dict:
    try:
        import chrome_window as cw
    except Exception as exc:
        return {"ok": False, "error": f"chrome_window import failed: {exc}", "state": "unknown"}
    try:
        if action == "show":
            return cw.show_scanner_chrome()
        if action == "hide":
            return cw.hide_scanner_chrome()
        return cw.status()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "state": "error"}


class CORSRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _handle_api(self) -> bool:
        parsed = urlparse(self.path)
        path = (parsed.path or "").rstrip("/") or "/"
        if not path.startswith("/api/scanner"):
            return False

        action = "status"
        if path.endswith("/show"):
            action = "show"
        elif path.endswith("/hide"):
            action = "hide"
        elif path.endswith("/status") or path == "/api/scanner":
            action = "status"
        else:
            body = _json_bytes({"ok": False, "error": "unknown_endpoint", "path": path})
            self.send_response(404)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        # Mutating actions require POST (GET status is fine)
        if action in ("show", "hide") and self.command not in ("POST", "PUT"):
            body = _json_bytes(
                {
                    "ok": False,
                    "error": "method_not_allowed",
                    "hint": f"Use POST {path}",
                }
            )
            self.send_response(405)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        result = _scanner_action(action)
        code = 200 if result.get("ok") else 500
        body = _json_bytes(result)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return True

    def do_GET(self):
        if self._handle_api():
            return
        return super().do_GET()

    def do_POST(self):
        # Consume body if any (we ignore payload)
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length > 0:
            try:
                self.rfile.read(length)
            except Exception:
                pass
        if self._handle_api():
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        # Keep quiet for successful GETs; still surface errors + API calls lightly.
        try:
            path = getattr(self, "path", "") or ""
            if path.startswith("/api/"):
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))
                return
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
