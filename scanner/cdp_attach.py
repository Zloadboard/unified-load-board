"""Attach to the stay-open Edge/Chrome (CDP port 9222) and scrape RXO/Arrive/ArcBest/Echo."""
from __future__ import annotations

import argparse
import atexit
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from extract import load_config, merge_loads, now_iso_z, resolve_output_path, write_loads_json  # noqa: E402
from sources import arrive, arcbest, echo, rxo  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("scanner.cdp")

CDP = "http://127.0.0.1:9222"
LOCK_PATH = BASE / "cdp_attach.pid"
# Keep previous source rows when a fetch returns [] but prior data is still fresh
_STALE_KEEP_SEC = 10 * 60  # 10 minutes


def _acquire_single_instance() -> None:
    """Refuse a second cdp_attach.py so we never leave two scanners fighting."""
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old_pid = 0
        if old_pid and old_pid != os.getpid():
            # Check if still alive (POSIX); on Windows os.kill(pid, 0) also works for own processes
            alive = False
            try:
                os.kill(old_pid, 0)
                alive = True
            except OSError:
                alive = False
            except Exception:
                alive = False
            if alive:
                raise SystemExit(
                    f"Another cdp_attach.py is already running (pid {old_pid}). "
                    "Stop it before starting a new scanner."
                )
    LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")

    def _cleanup() -> None:
        try:
            if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(os.getpid()):
                LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)


def connect(p):
    browser = p.chromium.connect_over_cdp(CDP)
    if not browser.contexts:
        raise RuntimeError("No browser contexts on CDP — is Edge running with START_EDGE_FOR_SCANNER.bat?")
    return browser, browser.contexts[0]


def page_for(context, url: str):
    # Reuse an existing tab with matching host if possible
    for pg in context.pages:
        try:
            if url.split("/")[2] in (pg.url or ""):
                return pg
        except Exception:
            continue
    return context.new_page()


def _parse_iso_age_sec(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        s = iso.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        return None


def _load_previous_by_source(output_path: Path) -> tuple[dict[str, list], str | None]:
    """Read prior loads.json grouped by source (for empty-fetch keep)."""
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
    except Exception:
        return {}, None
    updated = data.get("updatedAt") if isinstance(data, dict) else None
    by: dict[str, list] = {}
    for row in (data.get("loads") if isinstance(data, dict) else None) or []:
        if not isinstance(row, dict):
            continue
        src = row.get("source") or ""
        if not src:
            continue
        by.setdefault(src, []).append(row)
    return by, updated


def _write_last_scan(debug_dir: Path, per_source: dict, kept: dict[str, bool]) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "scannedAt": now_iso_z(),
        "sources": {
            name: {
                "count": len(loads or []),
                "keptPrevious": bool(kept.get(name)),
            }
            for name, loads in per_source.items()
        },
    }
    path = debug_dir / "last_scan.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_once(context, sources, output_path, debug_dir: Path):
    debug_dir.mkdir(parents=True, exist_ok=True)
    results = {"Arrive": [], "RXO": [], "ArcBest": [], "Echo": []}
    hard_fail = {"Arrive": False, "RXO": False, "ArcBest": False, "Echo": False}
    fetchers = {"Arrive": arrive, "RXO": rxo, "ArcBest": arcbest, "Echo": echo}

    prev_by_source, prev_updated = _load_previous_by_source(Path(output_path))
    prev_age = _parse_iso_age_sec(prev_updated)

    for name, mod in fetchers.items():
        url = sources.get(name)
        if not url:
            log.warning("[%s] No URL in config — skipping", name)
            continue
        page = page_for(context, url)
        try:
            page._scanner_api_payloads = []
        except Exception:
            pass
        log.info("[%s] Scanning %s", name, url)
        # Per-source try/except: one board failing must not wipe others
        try:
            loads = mod.fetch(context, url, debug_dir, page=page)
            hard_fail[name] = False
        except Exception as exc:
            log.warning("[%s] error: %s", name, exc)
            loads = []
            hard_fail[name] = True
        results[name] = loads or []
        log.info("[%s] %d loads", name, len(results[name]))

    # Merge strategy: never replace a source with [] if prior loads.json had that
    # source with items within the last ~10 min, and either this fetch hard-failed
    # or other sources succeeded this cycle (so we don't blank one board on a blip).
    any_ok = any(len(results.get(n) or []) > 0 for n in results)
    kept_prev: dict[str, bool] = {n: False for n in results}
    age_ok = prev_age is not None and prev_age <= _STALE_KEEP_SEC
    if age_ok:
        for name in list(results.keys()):
            if results[name]:
                continue
            prev_rows = prev_by_source.get(name) or []
            if not prev_rows:
                continue
            if hard_fail.get(name) or any_ok:
                results[name] = prev_rows
                kept_prev[name] = True
                log.warning(
                    "[%s] empty/failed fetch — keeping %d previous loads (loads.json age %.0fs)",
                    name,
                    len(prev_rows),
                    prev_age or 0,
                )

    _write_last_scan(debug_dir, results, kept_prev)

    merged = merge_loads(results["Arrive"], results["RXO"], results["ArcBest"], results.get("Echo", []))
    try:
        from cleanse import cleanse_loads

        merged = cleanse_loads(merged)
    except Exception as exc:
        log.warning("cleanse skipped: %s", exc)
    write_loads_json(output_path, merged, updated_at=now_iso_z())
    log.info("Wrote %s total=%d", output_path, len(merged))
    return results


def main() -> int:
    from playwright.sync_api import sync_playwright

    _acquire_single_instance()

    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=None)
    args = ap.parse_args()

    config = load_config(BASE / "config.json")
    interval = args.interval or int(config.get("interval_seconds", 60))
    sources = config.get("sources") or {}
    output_path = resolve_output_path(config, BASE)
    debug_dir = BASE / "debug"

    log.info("Connecting to Edge CDP at %s", CDP)
    log.info("Leave the Edge window open. Ctrl+C to stop the scanner only.")
    log.info("Scan interval ~%ss", interval)

    with sync_playwright() as p:
        try:
            browser, context = connect(p)
        except Exception as exc:
            log.error("Could not attach to Edge: %s", exc)
            log.error("Run START_EDGE_FOR_SCANNER.bat first and log in.")
            return 1

        try:
            while True:
                try:
                    run_once(context, sources, output_path, debug_dir)
                except Exception as exc:
                    log.error("Cycle failed: %s", exc)
                    # try reconnect
                    try:
                        browser, context = connect(p)
                    except Exception as exc2:
                        log.error("Reconnect failed: %s", exc2)
                if args.once:
                    break
                time.sleep(max(5, interval))
        except KeyboardInterrupt:
            log.info("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
