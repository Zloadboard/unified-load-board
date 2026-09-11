#!/usr/bin/env python3
"""CORS-enabled static file server for Unified Load Board (port 8765).

Serves the project root (index.html, loads.json, city_coords.json, …)
with Access-Control-Allow-Origin: * so GitHub Pages / phone browsers
can fetch live data from this work-PC endpoint (via tunnel).

Extension (preferred daily path):
  POST /api/loads              — body {loads, sources?, mode?, updatedAt?} → writes loads.json
  GET  /api/last_scan          — latest per-source status (extension or legacy CDP)

Legacy scanner Chrome controls (optional; CDP no longer required for daily use):
  GET  /api/scanner/status
  GET  /api/scanner/tabs
  POST /api/scanner/show|hide|focus-tab|ensure-tabs

Prefer launching with pythonw via silent_start.ps1 (serve_board only by default).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = int(os.environ.get("ULB_PORT", "8765"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNER = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(SCANNER, "chrome_window.py")
LOADS_PATH = os.path.join(ROOT, "loads.json")
LAST_SCAN_PATH = os.path.join(SCANNER, "debug", "last_scan.json")
LAST_SCAN_ROOT = os.path.join(ROOT, "last_scan.json")
LAST_SCAN_CANDIDATES = (LAST_SCAN_PATH, LAST_SCAN_ROOT)

# Extension payloads can be multi‑MB
_MAX_BODY = 12_000_000


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_last_scan() -> dict:
    for path in LAST_SCAN_CANDIDATES:
        try:
            if not os.path.isfile(path):
                continue
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("ok", True)
                data["path"] = path
                return data
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": path}
    return {"ok": False, "error": "last_scan_missing", "sources": {}}


def _json_bytes(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + chr(10)).encode("utf-8")


def _atomic_write_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(
        prefix=".loads_", suffix=".tmp", dir=os.path.dirname(path) or ROOT
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(raw)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_last_scan_from_extension(sources: dict | None, mode: str, total: int) -> None:
    payload = {
        "scannedAt": _now_iso_z(),
        "mode": mode or "extension",
        "total": total,
        "ok": True,
        "sources": sources or {},
    }
    text = json.dumps(payload, indent=2) + "\n"
    try:
        os.makedirs(os.path.dirname(LAST_SCAN_PATH), exist_ok=True)
        with open(LAST_SCAN_PATH, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass
    try:
        with open(LAST_SCAN_ROOT, "w", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def _find_python() -> str:
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


def _merge_keep_previous(new_loads: list, previous_loads: list, sources: dict | None) -> list:
    """If a source is needs_login/error/empty and sent 0 rows, keep previous rows for that source."""
    if not previous_loads:
        return new_loads
    sources = sources or {}
    new_by: dict[str, list] = {}
    for row in new_loads:
        if isinstance(row, dict) and row.get("source"):
            new_by.setdefault(str(row["source"]), []).append(row)
    prev_by: dict[str, list] = {}
    for row in previous_loads:
        if isinstance(row, dict) and row.get("source"):
            prev_by.setdefault(str(row["source"]), []).append(row)

    keep_statuses = {"needs_login", "error", "empty", "no_tab", "kept_previous"}
    out: list = []
    all_sources = set(new_by) | set(prev_by) | set(sources)
    for src in all_sources:
        fresh = new_by.get(src) or []
        meta = sources.get(src) if isinstance(sources.get(src), dict) else {}
        status = str((meta or {}).get("status") or "")
        if fresh:
            out.extend(fresh)
            continue
        if status in keep_statuses or (meta or {}).get("keptPrevious"):
            out.extend(prev_by.get(src) or [])
        elif src in new_by:
            # Explicitly present with empty list and no keep status → allow wipe
            pass
        else:
            # Source omitted from this POST — keep previous
            out.extend(prev_by.get(src) or [])
    return out


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
        if length > _MAX_BODY:
            return {"__error": "body_too_large", "__length": length}
        try:
            raw = self.rfile.read(min(length, _MAX_BODY))
            return json.loads(raw.decode("utf-8", "ignore") or "{}")
        except Exception as exc:
            return {"__error": str(exc)}

    def _handle_post_loads(self, body: dict) -> bool:
        parsed = urlparse(self.path)
        path = (parsed.path or "").rstrip("/") or "/"
        if path not in ("/api/loads", "/api/loads/"):
            return False
        if body.get("__error"):
            self._send_json(
                400,
                {"ok": False, "error": body.get("__error"), "detail": body.get("__length")},
            )
            return True
        loads = body.get("loads")
        if not isinstance(loads, list):
            self._send_json(400, {"ok": False, "error": "loads_must_be_array"})
            return True
        sources = body.get("sources") if isinstance(body.get("sources"), dict) else {}
        mode = str(body.get("mode") or "extension")
        updated = str(body.get("updatedAt") or _now_iso_z())

        previous: list = []
        try:
            if os.path.isfile(LOADS_PATH):
                with open(LOADS_PATH, "r", encoding="utf-8") as f:
                    prev = json.load(f)
                if isinstance(prev, dict) and isinstance(prev.get("loads"), list):
                    previous = prev["loads"]
                elif isinstance(prev, list):
                    previous = prev
        except Exception:
            previous = []

        merged = _merge_keep_previous(loads, previous, sources)
        out = {
            "updatedAt": updated,
            "mode": mode,
            "loads": merged,
        }
        try:
            _atomic_write_json(LOADS_PATH, out)
            _write_last_scan_from_extension(sources, mode, len(merged))
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": str(exc)})
            return True
        self._send_json(
            200,
            {
                "ok": True,
                "written": len(merged),
                "received": len(loads),
                "updatedAt": updated,
                "mode": mode,
                "path": LOADS_PATH,
            },
        )
        return True

    def _handle_api(self, body: dict | None = None) -> bool:
        parsed = urlparse(self.path)
        path = (parsed.path or "").rstrip("/") or "/"
        if path in ("/api/last_scan", "/api/last-scan", "/api/scan_status"):
            self._send_json(200, _read_last_scan())
            return True
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
        if self._handle_post_loads(body):
            return
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
