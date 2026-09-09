"""Headed first-run login helper — save persistent Edge profile for all three boards."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from extract import load_config

BASE_DIR = Path(__file__).resolve().parent
PROFILE_DIR = BASE_DIR / "browser_profile"
STATE_PATH = BASE_DIR / "storage_state.json"
DONE_FLAG = BASE_DIR / "LOGIN_DONE.txt"
CONFIG_PATH = BASE_DIR / "config.json"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright is not installed. Run:")
        print("  pip install -r requirements.txt")
        print("  playwright install msedge")
        return 1

    config = load_config(CONFIG_PATH) if CONFIG_PATH.exists() else {}
    sources = config.get("sources") or {
        "Arrive": "https://carrier.arrivelogistics.com/find-loads",
        "RXO": "https://carrier.rxoconnect.rxo.com/loads/available-loads",
        "ArcBest": "https://carriers.arcb.com/Shipments",
    }

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    if DONE_FLAG.exists():
        DONE_FLAG.unlink()

    print("=" * 60)
    print("Unified Load Board — Login Helper")
    print("=" * 60)
    print(f"Persistent profile: {PROFILE_DIR}")
    print()
    print("IMPORTANT: Use the Edge window THIS script opens.")
    print("Do NOT use your normal everyday Edge/Chrome window.")
    print()
    print("1) Sign into Arrive, RXO, and ArcBest in that window.")
    print("2) When all three show load boards (not login pages), either:")
    print("     - Press Enter in THIS black window, OR")
    print("     - Create an empty file named LOGIN_DONE.txt in this folder")
    print("       (same folder as START_LOGIN.bat)")
    print("=" * 60)
    print()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="msedge",
            headless=False,
            viewport={"width": 1400, "height": 900},
            accept_downloads=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        pages = list(context.pages)
        if not pages:
            pages = [context.new_page()]

        urls = [
            ("Arrive", sources.get("Arrive")),
            ("RXO", sources.get("RXO")),
            ("ArcBest", sources.get("ArcBest")),
        ]

        first = True
        for name, url in urls:
            if not url:
                continue
            if first:
                page = pages[0]
                first = False
            else:
                page = context.new_page()
            print(f"Opening {name}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            except Exception as exc:
                print(f"  Warning: could not fully load {name}: {exc}")
                print("  You can still navigate/login manually in that tab.")

        print()
        print("Waiting for you to finish login…")
        print("(Press Enter here, or drop LOGIN_DONE.txt in the scanner folder)")

        # Poll for Enter (non-blocking-ish) OR done flag for up to 30 minutes
        deadline = time.time() + 30 * 60
        finished = False
        while time.time() < deadline:
            if DONE_FLAG.exists():
                print("Detected LOGIN_DONE.txt — saving session.")
                finished = True
                break
            # Try non-blocking stdin if available
            try:
                import msvcrt
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        print("Enter pressed — saving session.")
                        finished = True
                        break
            except Exception:
                pass
            time.sleep(0.4)

        if not finished:
            print("Timed out waiting for login confirmation.")
            try:
                context.close()
            except Exception:
                pass
            return 1

        try:
            context.storage_state(path=str(STATE_PATH))
            print(f"Wrote {STATE_PATH}")
        except Exception as exc:
            print(f"Warning: could not write storage_state.json: {exc}")

        try:
            context.close()
        except Exception as exc:
            print(f"Warning while closing browser: {exc}")

    # Verify profile has real browser data
    kids = [p for p in PROFILE_DIR.iterdir() if p.name != ".gitkeep"]
    print()
    if not kids and not STATE_PATH.exists():
        print("ERROR: Profile still looks empty. Login may not have saved.")
        print("Close other Edge windows and run START_LOGIN.bat again.")
        return 1

    print("Session saved. You can now run START_SCANNER.bat.")
    if DONE_FLAG.exists():
        try:
            DONE_FLAG.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
