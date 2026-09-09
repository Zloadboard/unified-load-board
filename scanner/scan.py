"""Main scanner loop — poll Arrive / RXO / ArcBest and write loads.json."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure scanner/ is on path for `extract` and `sources.*`
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from extract import (  # noqa: E402
    load_config,
    merge_loads,
    now_iso_z,
    resolve_output_path,
    write_loads_json,
)
from sources import arrive, arcbest, rxo  # noqa: E402

PROFILE_DIR = BASE_DIR / "browser_profile"
DEBUG_DIR = BASE_DIR / "debug"
CONFIG_PATH = BASE_DIR / "config.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("scanner")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Unified load board scanner")
    p.add_argument("--headless", action="store_true", help="Run Edge headless (default: headed)")
    p.add_argument("--headed", action="store_true", help="Force headed mode")
    p.add_argument("--once", action="store_true", help="Run a single scan cycle then exit")
    p.add_argument("--interval", type=int, default=None, help="Override interval_seconds")
    p.add_argument("--config", type=str, default=str(CONFIG_PATH), help="Path to config.json")
    return p.parse_args()


def run_cycle(context, sources: dict, pages: dict, output_path: Path) -> None:
    """Visit each source and write merged loads.json."""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    results = {
        "Arrive": [],
        "RXO": [],
        "ArcBest": [],
    }

    fetchers = {
        "Arrive": arrive,
        "RXO": rxo,
        "ArcBest": arcbest,
    }

    for name, mod in fetchers.items():
        url = sources.get(name)
        if not url:
            log.warning("[%s] No URL in config — skip", name)
            continue
        page = pages.get(name)
        # Clear prior API payloads before navigation
        if page is not None:
            try:
                page._scanner_api_payloads = []
            except Exception:
                pass
        log.info("[%s] Scanning %s", name, url)
        try:
            loads = mod.fetch(context, url, DEBUG_DIR, page=page)
        except Exception as exc:
            log.warning("[%s] Unexpected error — skip: %s", name, exc)
            loads = []
        results[name] = loads or []
        log.info("[%s] %d loads", name, len(results[name]))

    merged = merge_loads(results["Arrive"], results["RXO"], results["ArcBest"])
    write_loads_json(output_path, merged, updated_at=now_iso_z())
    log.info(
        "Wrote %s — total %d (Arrive=%d RXO=%d ArcBest=%d)",
        output_path,
        len(merged),
        len(results["Arrive"]),
        len(results["RXO"]),
        len(results["ArcBest"]),
    )


def main() -> int:
    args = parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:")
        print("  pip install -r requirements.txt")
        print("  playwright install msedge")
        return 1

    config = load_config(Path(args.config))
    interval = args.interval if args.interval is not None else int(config.get("interval_seconds", 60))
    headed_cfg = bool(config.get("headed", True))
    if args.headless:
        headed = False
    elif args.headed:
        headed = True
    else:
        headed = headed_cfg

    sources = config.get("sources") or {}
    output_path = resolve_output_path(config, BASE_DIR)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    log.info("Profile: %s", PROFILE_DIR)
    log.info("Output:  %s", output_path)
    log.info("Interval: %ss | headed=%s", interval, headed)
    log.info("Press Ctrl+C to stop.")

    with sync_playwright() as p:
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=not headed,
            viewport={"width": 1400, "height": 900},
            accept_downloads=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        state_path = BASE_DIR / "storage_state.json"
        # Prefer persistent profile; storage_state is a backup from login.py
        context = p.chromium.launch_persistent_context(**launch_kwargs)
        if state_path.exists():
            try:
                # Re-apply cookies/localStorage from explicit export if profile was thin
                import json
                state = json.loads(state_path.read_text(encoding="utf-8"))
                for origin in state.get("origins", []):
                    pass  # persistent context already has disk profile
                log.info("storage_state.json present (%s)", state_path)
            except Exception as exc:
                log.warning("Could not read storage_state.json: %s", exc)

        # Reuse one page per source across cycles
        pages: dict = {}
        existing = list(context.pages)
        names = [n for n in ("Arrive", "RXO", "ArcBest") if sources.get(n)]
        for i, name in enumerate(names):
            if i < len(existing):
                pages[name] = existing[i]
            else:
                pages[name] = context.new_page()

        try:
            while True:
                t0 = time.time()
                try:
                    run_cycle(context, sources, pages, output_path)
                except Exception as exc:
                    log.error("Cycle failed (will retry): %s", exc)
                if args.once:
                    break
                elapsed = time.time() - t0
                sleep_for = max(5, interval - elapsed)
                log.info("Sleeping %.0fs until next cycle…", sleep_for)
                time.sleep(sleep_for)
        except KeyboardInterrupt:
            log.info("Stopped by user.")
        finally:
            try:
                context.close()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
