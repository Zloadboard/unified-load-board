"""Win32 + CDP helpers for the single scanner Chrome window (chrome_cdp_profile).

ONE Chrome hosts:
  Tab 1: board http://localhost:8765/
  Other tabs: Arrive / RXO / ArcBest / Echo / CHR

Hide = minimize (never park at -32000 — that caused taskbar-stuck hell).
Show / focus-tab = restore on primary monitor + CDP activate tab.
Safe no-ops on non-Windows.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROFILE_MARKER = "chrome_cdp_profile"
CDP_PORT = int(os.environ.get("ULB_CDP_PORT", "9222"))
CDP = f"http://127.0.0.1:{CDP_PORT}"
BOARD_URL = os.environ.get("ULB_BOARD_URL", "http://localhost:8765/")

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_SHOW = 5
SW_MINIMIZE = 6
SW_RESTORE = 9
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0

# Primary-monitor restore geometry (avoid -32000 forever)
RESTORE_X = 60
RESTORE_Y = 40
RESTORE_W = 1400
RESTORE_H = 900

BROKER_TABS: dict[str, dict[str, str]] = {
    "board": {
        "label": "Board",
        "url": BOARD_URL,
        "match": "localhost:8765",
    },
    "arrive": {
        "label": "Arrive",
        "url": "https://carrier.arrivelogistics.com/find-loads",
        "match": "arrivelogistics",
    },
    "rxo": {
        "label": "RXO",
        "url": "https://carrier.rxoconnect.rxo.com/loads/available-loads",
        "match": "rxo",
    },
    "arcbest": {
        "label": "ArcBest",
        "url": "https://carriers.arcb.com/Shipments",
        "match": "arcb",
    },
    "echo": {
        "label": "Echo",
        "url": "https://echodrive.echo.com/carrier/10261/availableLoads",
        "match": "echodrive.echo.com",
    },
    "chr": {
        "label": "CHR",
        "url": "https://www.navispherecarrier.com/",
        "match": "navisphere",
    },
}

# Startup / ensure order: board first, then brokers
BROKER_URLS = [BROKER_TABS[k]["url"] for k in ("arrive", "rxo", "arcbest", "echo", "chr")]
STARTUP_URLS = [BOARD_URL] + BROKER_URLS


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


def kill_scanner_chrome() -> dict[str, Any]:
    """Force-kill all chrome_cdp_profile Chrome processes (stuck taskbar recovery)."""
    if not _is_windows():
        return {"ok": False, "error": "not_windows", "killed": []}
    import subprocess

    pids = _scanner_chrome_pids()
    killed: list[int] = []
    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            killed.append(pid)
        except Exception:
            pass
    time.sleep(0.8)
    return {"ok": True, "killed": killed, "remaining": _scanner_chrome_pids()}


def _all_scanner_hwnds() -> list[int]:
    """Main Chrome frame hwnds for chrome_cdp_profile (includes minimized / hidden).

    Prefer titled top-level windows (the real browser frame). Fall back to large
    untitled roots only if no titled frame is found (recovery from -32000 park).
    """
    pids = set(_scanner_chrome_pids())
    if not pids:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titled: list[int] = []
    untitled: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):  # type: ignore[no-untyped-def]
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if int(pid.value) not in pids:
            return True
        if user32.GetWindow(hwnd, 4) != 0:  # GW_OWNER
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = abs(int(rect.right) - int(rect.left))
        h = abs(int(rect.bottom) - int(rect.top))
        title_len = int(user32.GetWindowTextLengthW(hwnd))
        iconic = bool(user32.IsIconic(hwnd))
        visible = bool(user32.IsWindowVisible(hwnd))
        # Real browser frames are large OR iconic/hidden (may be tiny after -32000)
        large = w >= 200 and h >= 200
        recoverable = iconic or (not visible and title_len >= 0)
        if not large and not recoverable and w < 50 and h < 50:
            return True
        if title_len > 0:
            titled.append(int(hwnd))
        elif large or recoverable:
            untitled.append(int(hwnd))
        return True

    user32.EnumWindows(_cb, 0)
    return titled if titled else untitled


def _force_foreground(hwnd: int) -> None:
    """Best-effort SetForegroundWindow (AttachThreadInput when needed)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.BringWindowToTop(hwnd)
        if user32.SetForegroundWindow(hwnd):
            return
        # Attach to foreground thread and retry
        fg = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg, None)
        our_tid = kernel32.GetCurrentThreadId()
        if fg_tid and fg_tid != our_tid:
            user32.AttachThreadInput(our_tid, fg_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(our_tid, fg_tid, False)
        else:
            user32.SetForegroundWindow(hwnd)
    except Exception:
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def _restore_on_primary(hwnd: int) -> None:
    """Move window onto primary monitor and show it (fixes -32000 / taskbar-stuck)."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    # Clear any leftover off-screen park, then restore + show
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:
        pass
    try:
        user32.ShowWindow(hwnd, SW_SHOW)
    except Exception:
        pass
    flags = SWP_SHOWWINDOW
    try:
        user32.SetWindowPos(
            hwnd,
            HWND_TOP,
            RESTORE_X,
            RESTORE_Y,
            RESTORE_W,
            RESTORE_H,
            flags,
        )
    except Exception:
        pass
    _force_foreground(hwnd)


def hide_scanner_chrome() -> dict[str, Any]:
    """Minimize scanner Chrome (do NOT SW_HIDE + -32000 — that stuck the taskbar)."""
    if not _is_windows():
        return {"ok": False, "error": "not_windows", "state": status().get("state")}
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    hwnds = _all_scanner_hwnds()
    minimized = 0
    for hwnd in hwnds:
        try:
            # If previously parked off-screen, snap back first so minimize is sane
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            if int(rect.left) < -1000 or int(rect.top) < -1000:
                user32.SetWindowPos(
                    hwnd,
                    HWND_TOP,
                    RESTORE_X,
                    RESTORE_Y,
                    RESTORE_W,
                    RESTORE_H,
                    SWP_NOZORDER,
                )
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            minimized += 1
        except Exception:
            pass
    st = status()
    st["ok"] = True
    st["minimizedWindows"] = minimized
    return st


def show_scanner_chrome() -> dict[str, Any]:
    """Restore scanner Chrome on the primary monitor and ensure broker + board tabs."""
    if not _is_windows():
        return {"ok": False, "error": "not_windows", "state": status().get("state")}
    hwnds = _all_scanner_hwnds()
    shown = 0
    for hwnd in hwnds:
        try:
            _restore_on_primary(hwnd)
            shown += 1
        except Exception:
            pass
    # Ensure tabs exist (board + brokers) inside THIS Chrome — never spawn a second window
    tabs = ensure_tabs(hide_after=False)
    # Focus board tab by default when showing for sign-in overview
    try:
        focus_tab("board", restore_window=True)
    except Exception:
        pass
    st = status()
    st["ok"] = True
    st["shownWindows"] = shown
    st["tabs"] = tabs
    return st


def _page_matches(match: str, page: dict) -> bool:
    url = (page.get("url") or "").lower()
    title = (page.get("title") or "").lower()
    m = match.lower()
    if m in url or m in title:
        return True
    # board: also match 127.0.0.1:8765
    if "localhost:8765" in m and ("127.0.0.1:8765" in url or "localhost:8765" in url):
        return True
    return False


def _find_page_for_key(key: str, pages: list[dict] | None = None) -> dict | None:
    meta = BROKER_TABS.get(key)
    if not meta:
        return None
    pages = pages if pages is not None else list_cdp_pages()
    match = meta["match"]
    login_bits = (
        "login", "signin", "sign-in", "authorize", "auth0.com", "okta.com",
        "oauth", "sso", "account/login", "multifactor",
    )
    scored: list[tuple[int, dict]] = []
    for p in pages:
        if not _page_matches(match, p):
            continue
        url = (p.get("url") or "").lower()
        title = (p.get("title") or "").lower()
        score = 10
        if any(b in url or b in title for b in login_bits):
            score -= 40
        if key == "rxo" and "available-loads" in url:
            score += 30
        if key == "arrive" and "find-loads" in url:
            score += 30
        if key == "arcbest" and "shipment" in url:
            score += 30
        if key == "echo" and "availableloads" in url:
            score += 30
        if key == "chr" and "find-loads" in url:
            score += 20
        if key == "board" and "8765" in url:
            score += 30
        scored.append((score, p))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _cdp_activate(target_id: str) -> bool:
    if not target_id:
        return False
    tid = urllib.parse.quote(target_id, safe="")
    for method in ("GET", "PUT"):
        try:
            req = urllib.request.Request(CDP + "/json/activate/" + tid, method=method)
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
            return True
        except Exception:
            continue
    return False


def _cdp_new(url: str) -> bool:
    enc = urllib.parse.quote(url, safe=":/?&=#%")
    for method in ("PUT", "GET"):
        try:
            req = urllib.request.Request(CDP + "/json/new?" + enc, method=method)
            with urllib.request.urlopen(req, timeout=8) as r:
                r.read()
            return True
        except Exception:
            continue
    return False


def _login_guess(key: str, page: dict | None) -> str:
    """Best-effort: logged_in | needs_login | unknown | missing."""
    if not page:
        return "missing"
    url = (page.get("url") or "").lower()
    title = (page.get("title") or "").lower()
    blob = url + " " + title
    if key == "board":
        return "ok" if ("8765" in url) else "unknown"
    login_needles = (
        "login",
        "signin",
        "sign-in",
        "sign_in",
        "log-in",
        "log_in",
        "auth0",
        "oauth",
        "sso",
        "accounts.google",
        "microsoftonline",
        "okta",
        "b2clogin",
    )
    if any(n in blob for n in login_needles):
        return "needs_login"
    # On expected host and not an auth page → likely logged in
    meta = BROKER_TABS.get(key) or {}
    match = (meta.get("match") or "").lower()
    if match and match in url:
        return "logged_in"
    if match and match in blob:
        return "logged_in"
    return "unknown"


def _cdp_close(target_id: str) -> bool:
    if not target_id:
        return False
    tid = urllib.parse.quote(target_id, safe="")
    for method in ("GET", "POST"):
        try:
            req = urllib.request.Request(CDP + "/json/close/" + tid, method=method)
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
            return True
        except Exception:
            continue
    return False


def _score_page_for_key(key: str, page: dict) -> int | None:
    """None = not this broker. Higher = better tab to keep."""
    meta = BROKER_TABS.get(key)
    if not meta or not _page_matches(meta["match"], page):
        return None
    url = (page.get("url") or "").lower()
    title = (page.get("title") or "").lower()
    score = 10
    login_bits = (
        "login", "signin", "sign-in", "authorize", "auth0.com", "okta.com",
        "oauth", "sso", "account/login", "multifactor",
    )
    if any(b in url or b in title for b in login_bits):
        score -= 40
    if url.startswith("chrome-error://") or url.startswith("chrome://"):
        score -= 100
    if key == "rxo" and "available-loads" in url:
        score += 30
    if key == "arrive" and "find-loads" in url:
        score += 30
    if key == "arcbest" and "shipment" in url:
        score += 30
    if key == "echo" and "availableloads" in url:
        score += 30
    if key == "chr" and "find-loads" in url:
        score += 20
    if key == "board" and "8765" in url:
        score += 30
    return score


def dedupe_tabs() -> dict[str, Any]:
    """Close extra tabs per broker — keep the highest-scoring one only.

    Never leaves 2x Arrive / 2x RXO Sign In. Safe to call anytime CDP is up.
    """
    if not cdp_up():
        return {"ok": False, "error": "cdp_down", "closed": []}
    pages = list_cdp_pages()
    by_key: dict[str, list[tuple[int, dict]]] = {k: [] for k in BROKER_TABS}
    for p in pages:
        for key in BROKER_TABS:
            sc = _score_page_for_key(key, p)
            if sc is not None:
                by_key[key].append((sc, p))
                break
    closed: list[dict[str, str]] = []
    for key, items in by_key.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: x[0], reverse=True)
        for _sc, p in items[1:]:
            tid = str(p.get("id") or "")
            if _cdp_close(tid):
                closed.append({
                    "key": key,
                    "id": tid[:12],
                    "url": (p.get("url") or "")[:160],
                })
            time.sleep(0.15)
    return {
        "ok": True,
        "closed": closed,
        "pages": len(list_cdp_pages()),
        "closedCount": len(closed),
    }


def ensure_tabs(hide_after: bool = False) -> dict[str, Any]:
    """Open missing board + broker tabs inside the existing CDP Chrome (no new process).

    Never opens a second tab for a broker that already has ANY matching tab
    (including login / Auth0 / Okta). Always dedupes afterward.
    """
    if not cdp_up():
        return {"ok": False, "error": "cdp_down"}
    # Retry briefly: Chrome may still be on about:blank right after launch
    pages = list_cdp_pages()
    for _ in range(6):
        if pages:
            break
        time.sleep(0.5)
        pages = list_cdp_pages()
    opened: list[str] = []
    for key in ("board", "arrive", "rxo", "arcbest", "echo", "chr"):
        meta = BROKER_TABS[key]
        pages = list_cdp_pages()
        if _find_page_for_key(key, pages):
            continue
        # Extra safety: any page matching the needle counts — do not open another
        if any(_page_matches(meta["match"], p) for p in pages):
            continue
        if _cdp_new(meta["url"]):
            opened.append(key)
            time.sleep(0.5)
    dedupe = dedupe_tabs()
    if hide_after:
        try:
            hide_scanner_chrome()
        except Exception:
            pass
    return {
        "ok": True,
        "opened": opened,
        "deduped": dedupe.get("closed") or [],
        "pages": len(list_cdp_pages()),
    }


def ensure_broker_tabs() -> dict[str, Any]:
    """Back-compat alias used by older scripts."""
    return ensure_tabs(hide_after=False)


def focus_tab(key: str, restore_window: bool = True) -> dict[str, Any]:
    """Bring a broker/board tab to front in the SAME Chrome window and focus the window."""
    key = (key or "board").strip().lower()
    aliases = {
        "back": "board",
        "home": "board",
        "ulb": "board",
        "molo": "arcbest",
        "arc": "arcbest",
        "navisphere": "chr",
    }
    key = aliases.get(key, key)
    if key not in BROKER_TABS:
        return {"ok": False, "error": "unknown_broker", "key": key, "known": list(BROKER_TABS)}

    if not cdp_up():
        return {"ok": False, "error": "cdp_down", "key": key}

    # Always collapse duplicates before focusing
    try:
        dedupe_tabs()
    except Exception:
        pass
    pages = list_cdp_pages()
    page = _find_page_for_key(key, pages)
    created = False
    if not page:
        meta = BROKER_TABS[key]
        # Any matching tab (even login) → activate it, never open a second
        for p in pages:
            if _page_matches(meta["match"], p):
                page = p
                break
        if not page:
            if _cdp_new(meta["url"]):
                created = True
                time.sleep(0.5)
                pages = list_cdp_pages()
                page = _find_page_for_key(key, pages)

    activated = False
    if page and page.get("id"):
        activated = _cdp_activate(str(page["id"]))

    shown = 0
    if restore_window and _is_windows():
        for hwnd in _all_scanner_hwnds():
            try:
                _restore_on_primary(hwnd)
                shown += 1
            except Exception:
                pass

    st = status()
    st["ok"] = bool(activated or created or shown)
    st["key"] = key
    st["label"] = BROKER_TABS[key]["label"]
    st["activated"] = activated
    st["created"] = created
    st["shownWindows"] = shown
    st["pageUrl"] = (page or {}).get("url")
    st["login"] = _login_guess(key, page)
    return st


def tab_status() -> dict[str, Any]:
    """Per-tab presence + best-effort login guess."""
    up = cdp_up()
    out: dict[str, Any] = {"ok": True, "cdp": up, "tabs": {}}
    if not up:
        for k, meta in BROKER_TABS.items():
            out["tabs"][k] = {"label": meta["label"], "present": False, "login": "cdp_down"}
        return out
    pages = list_cdp_pages()
    for k, meta in BROKER_TABS.items():
        page = _find_page_for_key(k, pages)
        out["tabs"][k] = {
            "label": meta["label"],
            "present": bool(page),
            "login": _login_guess(k, page),
            "url": (page or {}).get("url"),
            "title": (page or {}).get("title"),
        }
    out["pages"] = len(pages)
    return out


def status() -> dict[str, Any]:
    up = cdp_up()
    if not up:
        return {
            "ok": True,
            "cdp": False,
            "state": "cdp_down",
            "visible": False,
            "pages": 0,
            "tabs": {},
        }
    pages = list_cdp_pages()
    visible = False
    minimized = False
    hwnd_count = 0
    if _is_windows():
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnds = _all_scanner_hwnds()
        hwnd_count = len(hwnds)
        for hwnd in hwnds:
            try:
                if user32.IsIconic(hwnd):
                    minimized = True
                if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                    # Treat far off-screen as not really visible
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    if int(rect.left) > -500 and int(rect.top) > -500:
                        visible = True
                        break
            except Exception:
                pass
    if visible:
        state = "visible"
    elif minimized or hwnd_count:
        state = "hidden"  # minimized counts as hidden for UI
    else:
        state = "hidden"
    tabs_info = {}
    for k in BROKER_TABS:
        page = _find_page_for_key(k, pages)
        tabs_info[k] = {
            "label": BROKER_TABS[k]["label"],
            "present": bool(page),
            "login": _login_guess(k, page),
        }
    return {
        "ok": True,
        "cdp": True,
        "state": state,
        "visible": visible,
        "pages": len(pages),
        "hwnds": hwnd_count,
        "tabs": tabs_info,
    }


if __name__ == "__main__":
    cmd = (sys.argv[1] if len(sys.argv) > 1 else "status").strip().lower()
    if cmd == "hide":
        print(json.dumps(hide_scanner_chrome()))
    elif cmd == "show":
        print(json.dumps(show_scanner_chrome()))
    elif cmd in ("ensure-tabs", "ensure_tabs"):
        print(json.dumps(ensure_tabs(hide_after=False)))
    elif cmd in ("dedupe", "dedupe-tabs", "dedupe_tabs"):
        print(json.dumps(dedupe_tabs()))
    elif cmd in ("focus-tab", "focus_tab", "focus"):
        key = sys.argv[2] if len(sys.argv) > 2 else "board"
        print(json.dumps(focus_tab(key)))
    elif cmd in ("tab-status", "tabs"):
        print(json.dumps(tab_status()))
    elif cmd in ("kill", "kill-chrome"):
        print(json.dumps(kill_scanner_chrome()))
    else:
        print(json.dumps(status()))
