"""Attach to the stay-open Edge/Chrome (CDP port 9222) and scrape RXO/Arrive/ArcBest/Echo/CHR."""
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

from extract import (  # noqa: E402
    is_login_wall,
    load_config,
    merge_loads,
    now_iso_z,
    resolve_output_path,
    write_loads_json,
)
from sources import arrive, arcbest, chr as chr_src, echo, rxo  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scanner.cdp")

CDP = "http://127.0.0.1:9222"
LOCK_PATH = BASE / "cdp_attach.pid"
# Keep previous source rows when a fetch returns [] but prior data is still fresh
_STALE_KEEP_SEC = 10 * 60  # 10 minutes

# Flexible host needles for reusing tabs (never spawn a duplicate just because
# the config host is carrier.rxoconnect… while the live tab is login.id.rxo…).
_SOURCE_MATCH: dict[str, tuple[str, ...]] = {
    "Arrive": ("arrivelogistics",),
    "RXO": ("rxo",),
    "ArcBest": ("arcb.com", "arcb.", "capacity-carrierportal"),
    "Echo": ("echodrive.echo.com", "echo.com"),
    "CHR": ("navisphere",),
}

_LOGIN_URL_BITS = (
    "login",
    "signin",
    "sign-in",
    "sign_in",
    "authorize",
    "auth0.com",
    "okta.com",
    "oauth",
    "sso",
    "account/login",
    "multifactor",
)


def _acquire_single_instance() -> None:
    """Refuse a second cdp_attach.py so we never leave two scanners fighting."""
    if LOCK_PATH.exists():
        try:
            old_pid = int(LOCK_PATH.read_text(encoding="utf-8").strip() or "0")
        except Exception:
            old_pid = 0
        if old_pid and old_pid != os.getpid():
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
            if LOCK_PATH.exists() and LOCK_PATH.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    atexit.register(_cleanup)


def connect(p):
    browser = p.chromium.connect_over_cdp(CDP)
    if not browser.contexts:
        raise RuntimeError(
            "No browser contexts on CDP — is Chrome running with the CDP profile?"
        )
    return browser, browser.contexts[0]


def _url_looks_login(url: str) -> bool:
    u = (url or "").lower()
    if not u:
        return False
    return any(b in u for b in _LOGIN_URL_BITS)


def _page_score(name: str, url: str) -> int:
    """Higher = better tab to reuse for this source."""
    u = (url or "").lower()
    if not u or u.startswith("chrome-error://") or u.startswith("chrome://"):
        return -100
    needles = _SOURCE_MATCH.get(name) or ()
    if not any(n in u for n in needles):
        return -50
    score = 10
    if _url_looks_login(u):
        score -= 40
    # Prefer real board paths
    if name == "RXO" and "available-loads" in u:
        score += 30
    if name == "Arrive" and "find-loads" in u:
        score += 30
    if name == "ArcBest" and "shipment" in u:
        score += 30
    if name == "Echo" and "availableloads" in u:
        score += 30
    if name == "CHR" and "find-loads" in u:
        score += 20
    return score


def page_for(context, name: str, url: str):
    """Reuse the best existing tab for this broker; only open a new one if none match.

    CRITICAL: login tabs (login.id.rxo.com, Auth0, Okta) score low but MUST still be
    reused. Skipping them (old score>=0 gate) opened a second RXO/Arrive tab every cycle.
    """
    candidates = []
    for pg in list(context.pages):
        try:
            if pg.is_closed():
                continue
            cur = pg.url or ""
        except Exception:
            continue
        score = _page_score(name, cur)
        # -50 = wrong broker; anything else (including login at -30) is reusable
        if score > -50:
            candidates.append((score, pg))
    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best = candidates[0]
        log.info("[%s] Reusing tab score=%d url=%s", name, best_score, (best.url or "")[:120])
        return best
    log.info("[%s] No matching tab - opening %s", name, url)
    return context.new_page()


def _ensure_broker_tabs() -> None:
    """Open any missing board/broker tabs inside the existing CDP Chrome."""
    try:
        from chrome_window import ensure_tabs

        result = ensure_tabs(hide_after=False)
        opened = (result or {}).get("opened") or []
        if opened:
            log.info("ensure_tabs opened: %s", opened)
    except Exception as exc:
        log.warning("ensure_tabs failed: %s", exc)


def _prune_duplicate_tabs(context) -> None:
    """Close extra tabs for the same broker, keeping the highest-scoring one."""
    by_name: dict[str, list] = {n: [] for n in _SOURCE_MATCH}
    for pg in list(context.pages):
        try:
            if pg.is_closed():
                continue
            cur = (pg.url or "").lower()
        except Exception:
            continue
        for name, needles in _SOURCE_MATCH.items():
            if any(n in cur for n in needles):
                by_name[name].append(pg)
                break
    for name, pages in by_name.items():
        if len(pages) <= 1:
            continue
        ranked = sorted(
            pages,
            key=lambda pg: _page_score(name, getattr(pg, "url", "") or ""),
            reverse=True,
        )
        keep = ranked[0]
        for pg in ranked[1:]:
            try:
                log.info(
                    "[%s] Closing duplicate tab %s",
                    name,
                    (pg.url or "")[:100],
                )
                pg.close()
            except Exception:
                pass
        _ = keep


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


def _guess_status(name: str, page, loads: list, hard_fail: bool, kept: bool) -> str:
    if loads and not kept:
        return "ok"
    if kept and loads:
        return "kept_previous"
    try:
        if page is not None and not page.is_closed() and is_login_wall(page):
            return "needs_login"
        cur = ((page.url if page is not None else "") or "").lower()
        if _url_looks_login(cur):
            return "needs_login"
    except Exception:
        pass
    if hard_fail:
        return "error"
    return "empty"


def _write_last_scan(
    debug_dir: Path,
    output_path: Path,
    per_source: dict,
    kept: dict[str, bool],
    status: dict[str, str],
    errors: dict[str, str],
) -> None:
    debug_dir.mkdir(parents=True, exist_ok=True)
    # Also count MoLo rows sitting inside ArcBest fetch results / merged file
    payload = {
        "scannedAt": now_iso_z(),
        "sources": {
            name: {
                "count": len(loads or []),
                "keptPrevious": bool(kept.get(name)),
                "status": status.get(name) or "unknown",
                "error": errors.get(name) or "",
            }
            for name, loads in per_source.items()
        },
    }
    # Surface MoLo count from post-cleanse file if present
    try:
        data = json.loads(Path(output_path).read_text(encoding="utf-8"))
        molo_n = sum(
            1
            for row in (data.get("loads") or [])
            if isinstance(row, dict) and row.get("source") == "MoLo"
        )
        arc_n = sum(
            1
            for row in (data.get("loads") or [])
            if isinstance(row, dict) and row.get("source") == "ArcBest"
        )
        payload["sources"]["MoLo"] = {
            "count": molo_n,
            "keptPrevious": bool(kept.get("ArcBest")),
            "status": status.get("ArcBest") or "unknown",
            "error": "",
        }
        if "ArcBest" in payload["sources"]:
            # Replace ArcBest pre-cleanse count with post-cleanse ArcBest-only
            payload["sources"]["ArcBest"]["count"] = arc_n
    except Exception:
        pass

    text = json.dumps(payload, indent=2) + "\n"
    (debug_dir / "last_scan.json").write_text(text, encoding="utf-8")
    # Mirror to project root so "last_scan.json missing" false alarms stop
    try:
        (BASE.parent / "last_scan.json").write_text(text, encoding="utf-8")
    except Exception:
        pass


def run_once(context, sources, output_path, debug_dir: Path):
    debug_dir.mkdir(parents=True, exist_ok=True)
    _ensure_broker_tabs()
    try:
        _prune_duplicate_tabs(context)
    except Exception as exc:
        log.warning("prune duplicates: %s", exc)

    results: dict[str, list] = {
        "Arrive": [],
        "RXO": [],
        "ArcBest": [],
        "Echo": [],
        "CHR": [],
    }
    hard_fail = {n: False for n in results}
    errors: dict[str, str] = {n: "" for n in results}
    statuses: dict[str, str] = {n: "unknown" for n in results}
    pages_used: dict = {n: None for n in results}
    fetchers = {
        "Arrive": arrive,
        "RXO": rxo,
        "ArcBest": arcbest,
        "Echo": echo,
        "CHR": chr_src,
    }

    prev_by_source, prev_updated = _load_previous_by_source(Path(output_path))
    prev_age = _parse_iso_age_sec(prev_updated)

    for name, mod in fetchers.items():
        url = sources.get(name)
        if not url:
            log.warning("[%s] No URL in config — skipping", name)
            statuses[name] = "misconfigured"
            continue
        page = page_for(context, name, url)
        pages_used[name] = page
        try:
            page._scanner_api_payloads = []
        except Exception:
            pass
        log.info("[%s] Scanning %s (tab=%s)", name, url, (page.url or "")[:100])
        try:
            loads = mod.fetch(context, url, debug_dir, page=page)
            hard_fail[name] = False
        except Exception as exc:
            log.warning("[%s] error: %s", name, exc)
            loads = []
            hard_fail[name] = True
            errors[name] = str(exc)[:300]
        results[name] = loads or []
        log.info("[%s] %d loads", name, len(results[name]))

    # Empty-fetch keep: never wipe a healthy source to 0 on a login wall / blip.
    # ArcBest fetch also carries MoLo rows — restore both from prior loads.json.
    any_ok = any(len(results.get(n) or []) > 0 for n in results)
    kept_prev: dict[str, bool] = {n: False for n in results}
    age_ok = prev_age is not None and prev_age <= _STALE_KEEP_SEC
    if age_ok:
        for name in list(results.keys()):
            if results[name]:
                continue
            if name == "ArcBest":
                prev_rows = (prev_by_source.get("ArcBest") or []) + (
                    prev_by_source.get("MoLo") or []
                )
            else:
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

    for name in results:
        statuses[name] = _guess_status(
            name,
            pages_used.get(name),
            results.get(name) or [],
            hard_fail.get(name, False),
            kept_prev.get(name, False),
        )
        if statuses[name] == "needs_login" and not errors.get(name):
            errors[name] = "Login wall — use board Sign in " + name

    merged = merge_loads(
        results["Arrive"],
        results["RXO"],
        results["ArcBest"],
        results.get("Echo", []),
        results.get("CHR", []),
    )
    try:
        from cleanse import cleanse_loads

        merged = cleanse_loads(merged)
    except Exception as exc:
        log.warning("cleanse skipped: %s", exc)
    write_loads_json(output_path, merged, updated_at=now_iso_z())
    _write_last_scan(debug_dir, Path(output_path), results, kept_prev, statuses, errors)
    log.info(
        "Wrote %s total=%d statuses=%s",
        output_path,
        len(merged),
        {k: statuses[k] for k in statuses},
    )
    return results


def _setup_file_logging(debug_dir: Path) -> None:
    """Mirror scanner logs to debug/cdp_attach.log (pythonw has no console)."""
    try:
        debug_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(debug_dir / "cdp_attach.log", encoding="utf-8")
        fh.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )
        logging.getLogger().addHandler(fh)
    except Exception:
        pass


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
    _setup_file_logging(debug_dir)

    log.info("Connecting to Chrome CDP at %s", CDP)
    log.info("Leave the Chrome window open. Ctrl+C to stop the scanner only.")
    log.info("Scan interval ~%ss", interval)

    with sync_playwright() as p:
        try:
            browser, context = connect(p)
        except Exception as exc:
            log.error("Could not attach to Chrome: %s", exc)
            log.error("Run DAILY_START / silent_start so CDP Chrome is on :9222.")
            return 1

        try:
            while True:
                try:
                    # Refresh context in case Chrome restarted tabs
                    if not browser.contexts:
                        browser, context = connect(p)
                    else:
                        context = browser.contexts[0]
                    run_once(context, sources, output_path, debug_dir)
                except Exception as exc:
                    log.error("Cycle failed: %s", exc)
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
