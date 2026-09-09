"""Win32 helpers to hide/show the scanner CDP Chrome window (chrome_cdp_profile).

Prefer SW_HIDE over headless so broker logins/sessions stay intact.
Safe no-ops on non-Windows.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any

PROFILE_MARKER = "chrome_cdp_profile"
CDP_PORT = int(os.environ.get("ULB_CDP_PORT", "9222"))
CDP = f"http://127.0.0.1:{CDP_PORT}"

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_RESTORE = 9
SW_SHOWMINIMIZED = 2

BROKER_URLS = [
    "https://carrier.arrivelogistics.com/find-loads",
    "https://carrier.rxoconnect.rxo.com/loads/available-loads",
    "https://carriers.arcb.com/Shipments",
    "https://echodrive.echo.com/carrier/10261/availableLoads",
    "https://www.navispherecarrier.com/",
]


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def cdp_up() -> bool:
    try:
        with urllib.request.urlopen(CDP + "/json/version", timeout=1.5) as r:
            return r.status == 200
    except Exception:
        return False


def list_cdp_pages() -> list[dict]:
    try:
        with urllib.request.urlopen(CDP + "/json", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
        return [t for t in data if isinstance(t, dict) and t.get("type") == "page"]
    except Exception:
        return []


def _scanner_chrome_pids() -> list[int]:
    """PIDs whose command line includes chrome_cdp_profile."""
    if not _is_windows():
        return []
    try:
        import subprocess

        # PowerShell is more reliable than wmic on modern Windows
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
            "Where-Object { $_.CommandLine -and $_.CommandLine -like '*chrome_cdp_profile*' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        pids = []
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except Exception:
        return []


def _enum_hwnds_for_pids(pids: set[int]) -> list[int]:
    if not pids or not _is_windows():
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):  # type: ignore[no-untyped-def]
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            # Still collect hidden windows so we can show them later
            pass
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) in pids:
            # Top-level windows only
            if user32.GetWindow(hwnd, 4) == 0:  # GW_OWNER = 4 → no owner
                length = user32.GetWindowTextLengthW(hwnd)
                # Chrome main window usually has a title; skip tiny tool windows
                if length >= 0:
                    hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return hwnds


def _all_scanner_hwnds() -> list[int]:
    """Include currently-hidden windows: EnumWindows still sees them."""
    pids = set(_scanner_chrome_pids())
    if not pids:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnds: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):  # type: ignore[no-untyped-def]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        # Skip owned popups
        if user32.GetWindow(hwnd, 4) != 0:
            return True
        # Require a real chrome frame: has size or is iconic/hidden root
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = abs(int(rect.right) - int(rect.left))
        h = abs(int(rect.bottom) - int(rect.top))
        if w < 50 and h < 50 and not user32.IsIconic(hwnd):
            return True
        hwnds.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return hwnds


def hide_scanner_chrome() -> dict[str, Any]:
    """Hide all top-level windows belonging to chrome_cdp_profile processes."""
    if not _is_windows():
        return {"ok": False, "error": "not_windows", "state": status().get("state")}
    import ctypes

    user32 = ctypes.windll.user32
    hwnds = _all_scanner_hwnds()
    hidden = 0
    for hwnd in hwnds:
        try:
            user32.ShowWindow(hwnd, SW_HIDE)
            hidden += 1
        except Exception:
            pass
    # Also shove off-screen in case ShowWindow is ignored
    for hwnd in hwnds:
        try:
            user32.SetWindowPos(hwnd, 0, -32000, -32000, 0, 0, 0x0001 | 0x0010)  # NOSIZE|NOZORDER
        except Exception:
            pass
    st = status()
    st["ok"] = True
    st["hiddenWindows"] = hidden
    return st


def show_scanner_chrome() -> dict[str, Any]:
    """Unhide / restore scanner Chrome so the user can sign into brokers."""
    if not _is_windows():
        return {"ok": False, "error": "not_windows", "state": status().get("state")}
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnds = _all_scanner_hwnds()
    shown = 0
    for hwnd in hwnds:
        try:
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_SHOW)
            user32.SetWindowPos(hwnd, 0, 80, 60, 1280, 900, 0x0040)  # SHOWWINDOW
            user32.SetForegroundWindow(hwnd)
            shown += 1
        except Exception:
            pass
    # Ensure broker tabs exist via CDP (never spawn a second Chrome)
    ensure_broker_tabs()
    st = status()
    st["ok"] = True
    st["shownWindows"] = shown
    return st


def _page_covers(url: str, pages: list[dict]) -> bool:
    host = url.split("/")[2].lower().replace("www.", "")
    needles = [host]
    if "arrivelogistics" in host:
        needles.append("arrivelogistics")
    if "rxo" in host:
        needles.append("rxo")
    if "arcb" in host:
        needles.append("arcb")
    if "echo" in host:
        needles.append("echodrive.echo.com")
    if "navisphere" in host:
        needles.append("navisphere")
    blob = " ".join((p.get("url") or "") for p in pages).lower()
    return any(n in blob for n in needles)


def ensure_broker_tabs() -> dict[str, Any]:
    """Open missing broker board URLs inside the existing CDP Chrome (no new process)."""
    if not cdp_up():
        return {"ok": False, "error": "cdp_down"}
    pages = list_cdp_pages()
    opened = []
    for url in BROKER_URLS:
        if _page_covers(url, pages):
            continue
        ok = False
        # Chrome accepts PUT or GET /json/new?<url>
        for method in ("PUT", "GET"):
            try:
                req = urllib.request.Request(CDP + "/json/new?" + url, method=method)
                with urllib.request.urlopen(req, timeout=8) as r:
                    r.read()
                ok = True
                break
            except Exception:
                continue
        if ok:
            opened.append(url)
            time.sleep(0.4)
            pages = list_cdp_pages()
    # Hide again after opening tabs so flashes don't linger
    try:
        hide_scanner_chrome()
    except Exception:
        pass
    return {"ok": True, "opened": opened, "pages": len(list_cdp_pages())}


def status() -> dict[str, Any]:
    up = cdp_up()
    if not up:
        return {
            "ok": True,
            "cdp": False,
            "state": "cdp_down",
            "visible": False,
            "pages": 0,
        }
    pages = list_cdp_pages()
    visible = False
    hwnd_count = 0
    if _is_windows():
        import ctypes

        user32 = ctypes.windll.user32
        hwnds = _all_scanner_hwnds()
        hwnd_count = len(hwnds)
        for hwnd in hwnds:
            try:
                if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    visible = True
                    break
            except Exception:
                pass
    state = "visible" if visible else "hidden"
    return {
        "ok": True,
        "cdp": True,
        "state": state,
        "visible": visible,
        "pages": len(pages),
        "hwnds": hwnd_count,
    }


# late import used by ensure_broker_tabs
import urllib.parse  # noqa: E402


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").strip().lower()
    if cmd == "hide":
        print(json.dumps(hide_scanner_chrome()))
    elif cmd == "show":
        print(json.dumps(show_scanner_chrome()))
    elif cmd == "ensure-tabs":
        print(json.dumps(ensure_broker_tabs()))
    else:
        print(json.dumps(status()))
