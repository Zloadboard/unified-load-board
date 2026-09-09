"""Open RXO and keep Edge open until the user explicitly finishes."""
from __future__ import annotations

import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

PROFILE = BASE / "browser_profile"
DONE_FLAG = BASE / "LOGIN_DONE.txt"
URL = "https://carrier.rxoconnect.rxo.com/loads/available-loads"


def main() -> int:
    from playwright.sync_api import sync_playwright

    if DONE_FLAG.exists():
        DONE_FLAG.unlink()

    print("=" * 60)
    print("RXO login — MANUAL CLOSE ONLY")
    print("=" * 60)
    print("1) Username + password")
    print("2) Phone code")
    print("3) Stay until you SEE the available loads list")
    print("4) Check 'remember/trust this device' if shown")
    print("5) ONLY THEN double-click MARK_LOGIN_DONE.bat")
    print("   (This window will NOT close by itself.)")
    print("=" * 60)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="msedge",
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=120_000)
        except Exception as exc:
            print("Nav warning:", exc)

        print("Waiting for MARK_LOGIN_DONE.bat (up to 20 minutes)…")
        print("Current URL will print every ~20s so you can see progress.")
        deadline = time.time() + 20 * 60
        last_print = 0.0
        finished = False
        while time.time() < deadline:
            if DONE_FLAG.exists():
                print("LOGIN_DONE detected.")
                finished = True
                break
            now = time.time()
            if now - last_print > 20:
                try:
                    print("… still open |", page.url)
                except Exception:
                    print("… still open")
                last_print = now
            try:
                import msvcrt
                if msvcrt.kbhit() and msvcrt.getwch() in ("\r", "\n"):
                    print("Enter pressed.")
                    finished = True
                    break
            except Exception:
                pass
            try:
                page.wait_for_timeout(500)
            except Exception:
                time.sleep(0.5)

        # Give cookies a moment to flush after MFA redirects
        print("Saving session (waiting 8s for cookies to settle)…")
        try:
            page.wait_for_timeout(8000)
        except Exception:
            time.sleep(8)
        try:
            print("Final URL:", page.url)
        except Exception:
            pass
        try:
            ctx.storage_state(path=str(BASE / "storage_state.json"))
            print("Wrote storage_state.json")
        except Exception as exc:
            print("storage_state warning:", exc)
        try:
            ctx.close()
        except Exception as exc:
            print("close warning:", exc)

    if DONE_FLAG.exists():
        try:
            DONE_FLAG.unlink()
        except Exception:
            pass
    print("Closed." if finished else "Timed out.")
    return 0 if finished else 1


if __name__ == "__main__":
    raise SystemExit(main())
