#!/usr/bin/env python3
"""CORS-enabled static file server for Unified Load Board (port 8765).

Serves the project root (index.html, loads.json, city_coords.json, …)
with Access-Control-Allow-Origin: * so GitHub Pages / phone browsers
can fetch live data from this work-PC endpoint (via tunnel).

Scanner Chrome controls (work PC only) — ONE Chrome window with board + broker tabs:
  GET  /api/scanner/status
  GET  /api/scanner/tabs
  POST /api/scanner/show        — restore Chrome on primary monitor
  POST /api/scanner/hide        — minimize (not off-screen)
  POST /api/scanner/focus-tab   — body {"broker":"arrive"|…|"board"} activate tab
  POST /api/scanner/ensure-tabs — open missing board/broker tabs in same window

Prefer launching with python.exe (hidden) via silent_start.ps1.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("ULB_PORT", "8765"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(SCANNER, "chrome_window.py")


def _json_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + chr(10)).encode("utf-8")


def _find_python() -> str:
    # Prefer python.exe for the Win32 helper so stdout is captured.
    exe = sys.executable or "python"
    low = exe.lower()
    if low.endswith("pythonw.exe"):
        cand = exe[: -len("pythonw.exe")] + "python.exe"
        if os.path.isfile(cand):
            return cand
    return exe


def _scanner_action(action: str, extra: str | None = None) -> dict:
    """Run chrome_window.py in a subprocess so Win32 never crashes the HTTP thread."""
    if not os.path.isfile(HELPER):
        return {"ok": False, "error": "chrome_window.py missing", "state": "error"}
    cmd = [_find_python(), HELPER, action]
    if extra:
        cmd.append(extra)
    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": 60,
            "cwd": SCANNER,
        }
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(cmd, **kwargs)
        out = (proc.stdout or "").strip() or (proc.stderr or "").strip()
        if not out:
            return {
                "ok": False,
                "error": f"empty_helper_output code={proc.returncode}",
                "state": "error",
            }
        try:
            return json.loads(out.splitlines()[-1])
        except Exception:
            return {"ok": False, "error": out[:500], "state": "error"}
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

    def _send_json(self, code: int, obj: dict) -> None:
        body = _json_bytes(obj)
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        try:
            raw = self.rfile.read(min(length, 1_000_000))
            return json.loads(raw.decode("utf-8", "ignore") or "{}")
        except Exception:
            return {}

    def _handle_api(self, body: dict | None = None) -> bool:
        parsed = urlparse(self.path)
        path = (parsed.path or "").rstrip("/") or "/"
        if not path.startswith("/api/scanner"):
            return False
        qs = parse_qs(parsed.query or "")
        body = body if body is not None else {}
        try:
            action = "status"
            extra = None
            mutating = False

            if path.endswith("/show"):
                action, mutating = "show", True
            elif path.endswith("/hide"):
                action, mutating = "hide", True
            elif path.endswith("/ensure-tabs") or path.endswith("/ensure_tabs"):
                action, mutating = "ensure-tabs", True
            elif path.endswith("/focus-tab") or path.endswith("/focus_tab"):
                action, mutating = "focus-tab", True
                broker = (
                    (body.get("broker") if isinstance(body, dict) else None)
                    or (body.get("key") if isinstance(body, dict) else None)
                    or (qs.get("broker") or [None])[0]
                    or (qs.get("key") or [None])[0]
                    or "board"
                )
                extra = str(broker).strip().lower() or "board"
            elif path.endswith("/tabs") or path.endswith("/tab-status"):
                action = "tab-status"
            elif path.endswith("/status") or path == "/api/scanner":
                action = "status"
            else:
                self._send_json(404, {"ok": False, "error": "unknown_endpoint", "path": path})
                return True

            if mutating and self.command not in ("POST", "PUT"):
                self._send_json(
                    405,
                    {"ok": False, "error": "method_not_allowed", "hint": f"Use POST {path}"},
                )
                return True

            result = _scanner_action(action, extra)
            code = 200 if result.get("ok") else 500
            self._send_json(code, result)
        except Exception as exc:
            try:
                self._send_json(500, {"ok": False, "error": str(exc), "state": "error"})
            except Exception:
                pass
        return True

    def do_GET(self):
        if self._handle_api():
            return
        return super().do_GET()

    def do_POST(self):
        body = self._read_json_body()
        if self._handle_api(body):
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        try:
            path = getattr(self, "path", "") or ""
            if path.startswith("/api/"):
                sys.stderr.write(("%s - %s" % (self.address_string(), fmt % args)) + chr(10))
                return
            code = args[1] if len(args) > 1 else ""
            if str(code).startswith("2") or str(code).startswith("3"):
                return
        except Exception:
            pass
        sys.stderr.write(("%s - %s" % (self.address_string(), fmt % args)) + chr(10))


def main() -> int:
    os.chdir(ROOT)
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
