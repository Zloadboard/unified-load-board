"""EchoDrive available loads extractor — prefers getOpenBoardLoadsV3 API."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from extract import dump_html_snippet, is_login_wall, normalize_load

log = logging.getLogger("scanner.echo")

SOURCE = "Echo"

# Last-good Echo API snapshot (avoid wiping a strong board with a weak cycle)
_LAST_GOOD_MAX_AGE_SEC = 10 * 60  # 10 minutes
_WEAK_FLOOR = 5


def _last_good_path(debug_dir: Path) -> Path:
    return Path(debug_dir) / "echo-last-good.json"


def _write_echo_api_debug(debug_dir: Path, body: Any, count: int) -> None:
    """Always persist last successful API body for debugging."""
    try:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        payload = {"count": count, "savedAt": time.time(), "body": body}
        (Path(debug_dir) / "echo-api.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        log.info("[%s] Wrote debug/echo-api.json (%d loads)", SOURCE, count)
    except Exception as exc:
        log.warning("[%s] Could not write echo-api.json: %s", SOURCE, exc)


def _load_last_good(debug_dir: Path) -> tuple[list[dict], float]:
    path = _last_good_path(debug_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        loads = raw.get("loads") if isinstance(raw, dict) else None
        ts = float(raw.get("savedAt") or 0) if isinstance(raw, dict) else 0.0
        if isinstance(loads, list) and loads:
            return loads, ts
    except Exception:
        pass
    return [], 0.0


def _save_last_good(debug_dir: Path, loads: list[dict]) -> None:
    if not loads:
        return
    try:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        payload = {"savedAt": time.time(), "count": len(loads), "loads": loads}
        _last_good_path(debug_dir).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("[%s] Could not save last-good: %s", SOURCE, exc)


def _is_weak_vs_last(new_count: int, last_count: int) -> bool:
    """True when new parse is suspiciously thin vs a recent strong board."""
    if last_count <= 0:
        return False
    return new_count < max(_WEAK_FLOOR, int(last_count * 0.5))


def _merge_prefer_new(old: list[dict], new: list[dict]) -> list[dict]:
    """Merge by id; prefer fresher (new) rows, keep old ids missing from new."""
    by_id: dict[str, dict] = {}
    for L in old or []:
        lid = str(L.get("id") or "")
        if lid:
            by_id[lid] = L
    for L in new or []:
        lid = str(L.get("id") or "")
        if lid:
            by_id[lid] = L
        else:
            by_id[f"_anon_{len(by_id)}"] = L
    return list(by_id.values())


def _reuse_last_good_if_ok(
    debug_dir: Path,
    api_loads: list[dict],
    *,
    reason: str,
) -> Optional[list[dict]]:
    """
    Reuse last-good Echo loads when this cycle is empty/weak.
    Only if last-good age < 10 minutes (never forever-stale).
    """
    last_loads, last_ts = _load_last_good(debug_dir)
    if not last_loads or not last_ts:
        return None
    age = time.time() - last_ts
    if age >= _LAST_GOOD_MAX_AGE_SEC:
        log.info(
            "[%s] last-good too old (%.0fs) — not reusing (%s)",
            SOURCE,
            age,
            reason,
        )
        return None
    new_n = len(api_loads or [])
    last_n = len(last_loads)
    if new_n == 0 or _is_weak_vs_last(new_n, last_n):
        if new_n >= 1:
            merged = _merge_prefer_new(last_loads, api_loads)
            log.warning(
                "[%s] API weak (%d vs last-good %d, age %.0fs) — merging with last-good -> %d (%s)",
                SOURCE,
                new_n,
                last_n,
                age,
                len(merged),
                reason,
            )
            return merged
        log.warning(
            "[%s] API empty — reusing last-good %d loads (age %.0fs) (%s)",
            SOURCE,
            last_n,
            age,
            reason,
        )
        return last_loads
    return None


_CITY_ZIP = re.compile(
    r"([A-Za-z][A-Za-z .'-]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)"
)
_DATE = re.compile(
    r"((?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+\d{1,2}\s+\d{1,2}:\d{2}(?:\s*-\s*\d{1,2}:\d{2})?)",
    re.I,
)
_MILES = re.compile(r"([\d,]+)\s*MI\b", re.I)
_WEIGHT = re.compile(r"([\d,]+)\s*LBS?\b", re.I)
_RATE = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")


def _fmt_city(stop: dict) -> str:
    city = (stop.get("city") or "").strip().title()
    state = (stop.get("state") or "").strip().upper()
    zipc = (stop.get("postalCode") or "").strip()
    if city and state and zipc:
        return f"{city}, {state} {zipc}"
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


def _split_appt(stop: dict) -> tuple[str, str]:
    appt = stop.get("appointmentTime") or {}
    start = (appt.get("startTime") or "").strip()
    end = (appt.get("endTime") or "").strip()
    # "09/08/2026 08:00:00"
    def parts(s: str) -> tuple[str, str]:
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d{2})", s or "")
        if m:
            mm, dd, yy, tm = m.group(1), m.group(2), m.group(3), m.group(4)
            iso = f"{yy}-{int(mm):02d}-{int(dd):02d}"
            return iso, tm
        m = re.match(r"(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2})", s or "")
        if m:
            return m.group(1), m.group(2)
        return s, ""

    d1, t1 = parts(start)
    d2, t2 = parts(end)
    if t1 and t2 and t1 != t2:
        return d1, f"{t1} - {t2}"
    return d1, t1


def _equip_label(equipment: Any) -> str:
    if not equipment:
        return ""
    names = []
    for e in equipment if isinstance(equipment, list) else [equipment]:
        if not isinstance(e, dict):
            continue
        name = (e.get("displayName") or e.get("truckType") or "").strip()
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _parse_api_items(body: Any, url: str, price_by_id: dict | None = None) -> list[dict]:
    price_by_id = price_by_id or {}
    root = body
    if isinstance(body, dict) and "data" in body:
        root = body.get("data")
    items = None
    if isinstance(root, dict):
        items = root.get("items") or root.get("loads") or root.get("results")
    elif isinstance(root, list):
        items = root
    if not isinstance(items, list):
        return []

    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        stops = item.get("loadStops") or item.get("stops") or []
        picks = [s for s in stops if str(s.get("stopType") or "").lower() in ("pick", "pickup")]
        drops = [s for s in stops if str(s.get("stopType") or "").lower() in ("drop", "delivery", "del")]
        pick = picks[0] if picks else (stops[0] if stops else {})
        drop = drops[-1] if drops else (stops[-1] if len(stops) > 1 else {})

        pu_city = _fmt_city(pick) if pick else ""
        de_city = _fmt_city(drop) if drop else ""
        if not pu_city or not de_city:
            continue
        pu_d, pu_t = _split_appt(pick) if pick else ("", "")
        de_d, de_t = _split_appt(drop) if drop else ("", "")

        load_id = str(item.get("loadId") or item.get("id") or "")
        rate = item.get("bookNowPrice") or item.get("rate") or price_by_id.get(load_id)
        try:
            rate = float(rate) if rate not in (None, "", 0, 0.0) else None
        except (TypeError, ValueError):
            rate = None

        miles = item.get("loadedMiles") or item.get("miles")
        try:
            miles = float(miles) if miles is not None else None
        except (TypeError, ValueError):
            miles = None

        weight = item.get("weight")
        equip = _equip_label(item.get("equipment"))

        raw = {
            "id": load_id or f"ECHO-{pu_city}-{de_city}-{pu_d}",
            "origin": pu_city,
            "destination": de_city,
            "pickupCity": pu_city,
            "deliveryCity": de_city,
            "pickupDate": pu_d,
            "pickupTime": pu_t,
            "deliveryDate": de_d,
            "deliveryTime": de_t,
            "weight": weight,
            "equipment": equip,
            "miles": miles,
            "rate": rate,
            "url": url,
            "notes": "",
        }
        try:
            out.append(normalize_load(raw, SOURCE, default_url=url))
        except Exception as exc:
            log.warning(
                "[%s] normalize failed id=%s origin=%r dest=%r: %s",
                SOURCE,
                load_id,
                pu_city,
                de_city,
                exc,
            )
            continue
    return out


def _parse_price_map(body: Any) -> dict[str, float]:
    """Map loadId -> book-now price from Echo bookNowPrice responses."""
    out: dict[str, float] = {}
    if body is None:
        return out
    data = body.get("data") if isinstance(body, dict) else body
    if isinstance(data, dict):
        # common shapes: {loadId: price} or {prices:[{loadId,price}]}
        if "prices" in data and isinstance(data["prices"], list):
            for row in data["prices"]:
                if not isinstance(row, dict):
                    continue
                lid = str(row.get("loadId") or row.get("id") or "")
                try:
                    out[lid] = float(row.get("bookNowPrice") or row.get("price") or 0) or out.get(lid, 0)
                except (TypeError, ValueError):
                    pass
        else:
            for k, v in data.items():
                if isinstance(v, (int, float)) and re.match(r"^\d+$", str(k)):
                    out[str(k)] = float(v)
                elif isinstance(v, dict):
                    lid = str(v.get("loadId") or k)
                    try:
                        val = v.get("bookNowPrice") or v.get("price")
                        if val not in (None, "", 0, 0.0):
                            out[lid] = float(val)
                    except (TypeError, ValueError):
                        pass
    elif isinstance(data, list):
        for row in data:
            if not isinstance(row, dict):
                continue
            lid = str(row.get("loadId") or row.get("id") or "")
            try:
                val = row.get("bookNowPrice") or row.get("price")
                if lid and val not in (None, "", 0, 0.0):
                    out[lid] = float(val)
            except (TypeError, ValueError):
                pass
    return {k: v for k, v in out.items() if v}


def _parse_cards_from_text(text: str, url: str) -> list[dict]:
    """Fallback: parse Echo card text (less accurate miles)."""
    if not text:
        return []
    chunks = re.split(r"\bBOOK NOW\b|\bPLACE BID\b|\bBid\b", text, flags=re.I)
    loads = []
    for chunk in chunks:
        cities = _CITY_ZIP.findall(chunk)
        if len(cities) < 2:
            continue
        dates = _DATE.findall(chunk)
        # Prefer "1,146 MI" style trip miles over small DH numbers by taking the largest MI in chunk
        miles_vals = []
        for m in _MILES.finditer(chunk):
            try:
                miles_vals.append(float(m.group(1).replace(",", "")))
            except ValueError:
                pass
        miles = max(miles_vals) if miles_vals else None
        weight_m = _WEIGHT.search(chunk)
        rates = _RATE.findall(chunk)
        rate = None
        if rates:
            try:
                rate = float(rates[0].replace(",", ""))
            except ValueError:
                rate = None
        weight = weight_m.group(0) if weight_m else ""
        equip = ""
        em = re.search(r"(Van[^|\n]{0,40}|Reefer[^|\n]{0,40}|Flatbed[^|\n]{0,40})", chunk, re.I)
        if em:
            equip = re.sub(r"\s+", " ", em.group(1)).strip(" |")
        pu_city, del_city = cities[0], cities[1]
        pu_date = dates[0] if dates else ""
        del_date = dates[1] if len(dates) > 1 else ""

        def split_dt(s: str):
            s = (s or "").strip()
            m = re.match(r"([A-Z]{3}\s+\d{1,2})\s+(.+)", s, re.I)
            if m:
                # Keep MON DD; UI parsePickupDate assumes current year
                return m.group(1).upper(), m.group(2)
            m = re.match(r"([A-Z]{3}\s+\d{1,2})$", s, re.I)
            if m:
                return m.group(1).upper(), ""
            return s, ""

        pu_d, pu_t = split_dt(pu_date)
        de_d, de_t = split_dt(del_date)
        raw = {
            "id": f"ECHO-{pu_city}-{del_city}-{pu_d}-{rate or ''}",
            "origin": pu_city,
            "destination": del_city,
            "pickupCity": pu_city,
            "deliveryCity": del_city,
            "pickupDate": pu_d,
            "pickupTime": pu_t,
            "deliveryDate": de_d,
            "deliveryTime": de_t,
            "weight": weight,
            "equipment": equip,
            "miles": miles,
            "rate": rate,
            "url": url,
            "notes": "",
        }
        try:
            loads.append(normalize_load(raw, SOURCE, default_url=url))
        except Exception as exc:
            log.warning("[%s] text normalize failed: %s", SOURCE, exc)
            continue
    seen = set()
    out = []
    for L in loads:
        k = (L.get("pickup_city"), L.get("delivery_city"), L.get("pickup_date"), L.get("miles"), L.get("rate"))
        if k in seen:
            continue
        seen.add(k)
        out.append(L)
    return out


def _fmt_echo_ui_date(d: date) -> str:
    """Echo date inputs commonly want MM/DD/YYYY."""
    return f"{d.month:02d}/{d.day:02d}/{d.year}"



def _fill_echo_date_inputs(page, start: date, end: date) -> bool:
    """
    EchoDrive pickup dates use #pickup-dates-dropdown-button + .dates-dropdown
    calendar (not text inputs). Click start day then end day for a range.
    """
    try:
        btn = page.locator("#pickup-dates-dropdown-button")
        if btn.count() == 0:
            # legacy text-input fallback
            log.warning("[%s] No #pickup-dates-dropdown-button — date chip missing", SOURCE)
            return False

        btn.first.click(timeout=4000)
        page.wait_for_timeout(400)

        # RESET for a clean range when available
        try:
            reset = page.locator(".dates-dropdown >> text=RESET")
            if reset.count() == 0:
                reset = page.get_by_text("RESET", exact=True)
            if reset.count() > 0:
                reset.first.click(timeout=1500)
                page.wait_for_timeout(250)
                btn.first.click(timeout=3000)
                page.wait_for_timeout(350)
        except Exception:
            pass

        start_day = int(start.day)
        end_day = int(end.day)
        # Same-month range click via JS inside .dates-dropdown
        result = page.evaluate(
            """(args) => {
              const [d0, d1] = args;
              const menu = document.querySelector('.dropdown-menu.dates-dropdown')
                || document.querySelector('.dates-dropdown');
              if (!menu) return { ok: false, reason: 'no-menu' };
              const nodes = [...menu.querySelectorAll('td, button, div, span, a, li')];
              const clickDay = (d) => {
                const exact = nodes.filter(n => (n.innerText || '').trim() === String(d));
                // prefer leaf nodes
                const leaf = exact.find(n => n.children.length === 0) || exact[0];
                if (!leaf) return false;
                leaf.click();
                return true;
              };
              const a = clickDay(d0);
              const b = clickDay(d1);
              return { ok: a && b, a, b, text: (menu.innerText || '').slice(0, 160) };
            }""",
            [start_day, end_day],
        )
        log.info("[%s] Calendar date range %s..%s -> %s", SOURCE, start, end, result)
        page.wait_for_timeout(300)
        # click outside to close
        try:
            page.locator("#origin-field-input").click(timeout=1000)
        except Exception:
            page.keyboard.press("Escape")
        return bool(result and result.get("ok"))
    except Exception as exc:
        log.warning("[%s] calendar date fill failed: %s", SOURCE, exc)
        return False



def _ensure_search(
    page,
    origin: str = "Romeoville, IL",
    radius: str = "100",
    pickup_start: date | None = None,
    pickup_end: date | None = None,
) -> None:
    """Fill origin via autocomplete + DH + pickup dates, then click Search when enabled."""
    try:
        origin_el = page.locator("#origin-field-input")
        if origin_el.count() == 0:
            return
        # Always re-select origin so Search enables (Echo disables submit otherwise)
        origin_el.click(timeout=3000)
        origin_el.fill("")
        page.wait_for_timeout(150)
        origin_el.type(origin, delay=40)
        page.wait_for_timeout(700)
        # Prefer clicking first autocomplete suggestion if present
        picked = False
        for sel in (
            ".pac-item",
            "[class*='suggestion']",
            "[class*='autocomplete'] li",
            ".dropdown-menu li",
            "mat-option",
            "[role='option']",
        ):
            try:
                opts = page.locator(sel)
                if opts.count() > 0:
                    opts.first.click(timeout=2000)
                    picked = True
                    break
            except Exception:
                continue
        if not picked:
            try:
                page.keyboard.press("ArrowDown")
                page.wait_for_timeout(150)
                page.keyboard.press("Enter")
                picked = True
            except Exception:
                pass
        page.wait_for_timeout(400)

        dh = page.locator("#origin-dh-field-input")
        if dh.count() > 0:
            try:
                dh.fill("")
                dh.type(str(radius), delay=30)
            except Exception:
                try:
                    dh.fill(str(radius))
                except Exception:
                    pass
            page.wait_for_timeout(200)

        # Default: today .. today+10 so Sep 8-11 style windows are covered
        today = date.today()
        start = pickup_start or today
        end = pickup_end or (today + timedelta(days=10))
        if end < start:
            end = start
        _fill_echo_date_inputs(page, start, end)
        page.wait_for_timeout(250)

        btn = page.locator("#save-search")
        if btn.count() == 0:
            return
        # Wait up to ~8s for Search to enable
        for _ in range(16):
            try:
                disabled = btn.first.is_disabled()
            except Exception:
                disabled = True
            if not disabled:
                break
            page.wait_for_timeout(500)
        try:
            if btn.first.is_disabled():
                # last resort: force-enable via DOM then click
                page.evaluate("""() => {
                  const b = document.querySelector('#save-search');
                  if (b) { b.disabled = false; b.removeAttribute('disabled'); }
                }""")
                page.wait_for_timeout(200)
            btn.first.click(timeout=8000, force=True)
            page.wait_for_timeout(3000)
        except Exception as exc:
            log.warning("[%s] search click failed: %s", SOURCE, exc)
    except Exception as exc:
        log.warning("[%s] search nudge failed: %s", SOURCE, exc)


def collect(page, url: str, debug_dir: Path) -> list[dict]:
    try:
        cur = (page.url or "").lower()
    except Exception:
        cur = ""
    logged_out = (
        "auth0.com" in cur
        or "/u/login" in cur
        or ("echodrive.echo.com" in cur and "/carrier/" not in cur and "available" not in cur)
    )
    if logged_out or is_login_wall(page):
        log.warning(
            "[%s] Not logged in / login wall — sign into EchoDrive in scanner Chrome, open Available Loads",
            SOURCE,
        )
        reused = _reuse_last_good_if_ok(debug_dir, [], reason="login-wall")
        return reused or []

    _attach_response_listener(page)
    # Clear old payloads for this cycle so we wait for a fresh search response
    try:
        page._scanner_api_payloads = []
    except Exception:
        pass

    _ensure_search(page)

    # Wait for getOpenBoardLoadsV3 (search can be slow after date/origin fill)
    for _ in range(40):
        payloads = getattr(page, "_scanner_api_payloads", None) or []
        if any("getOpenBoardLoadsV3" in (p.get("url") or "") for p in payloads):
            break
        page.wait_for_timeout(400)

    payloads = getattr(page, "_scanner_api_payloads", None) or []
    price_map: dict[str, float] = {}
    api_loads: list[dict] = []
    last_api_body: Any = None
    api_raw_count = 0
    for item in payloads:
        u = item.get("url") or ""
        body = item.get("body")
        if "bookNowPrice" in u:
            price_map.update(_parse_price_map(body))
        if "getOpenBoardLoadsV3" in u or "getOpenBoardLoads" in u:
            # Track server-reported count when present
            try:
                if isinstance(body, dict):
                    data = body.get("data") if isinstance(body.get("data"), dict) else body
                    if isinstance(data, dict) and data.get("count") is not None:
                        api_raw_count = int(data.get("count") or 0)
                    items = None
                    if isinstance(data, dict):
                        items = data.get("items") or data.get("loads") or data.get("results")
                    elif isinstance(data, list):
                        items = data
                    if isinstance(items, list):
                        api_raw_count = max(api_raw_count, len(items))
            except Exception:
                pass
            found = _parse_api_items(body, page.url or url, price_map)
            if found:
                api_loads = found  # latest search wins
                last_api_body = body
                log.info(
                    "[%s] API parsed %d loads (raw/count~%s) from %s",
                    SOURCE,
                    len(found),
                    api_raw_count or "?",
                    u[:100],
                )
            elif body is not None:
                last_api_body = body
                log.warning(
                    "[%s] getOpenBoardLoadsV3 body present but parsed 0 (raw/count~%s)",
                    SOURCE,
                    api_raw_count or "?",
                )

    if api_loads and price_map:
        for L in api_loads:
            lid = str(L.get("id") or "")
            if lid in price_map and not L.get("rate"):
                L["rate"] = price_map[lid]

    # Prefer API over text whenever API yielded >= 1 load
    if api_loads:
        _write_echo_api_debug(debug_dir, last_api_body, len(api_loads))
        log.info(
            "[%s] Using API loads=%d (server count~%s); saving last-good",
            SOURCE,
            len(api_loads),
            api_raw_count or len(api_loads),
        )
        reused = _reuse_last_good_if_ok(debug_dir, api_loads, reason="weak-api")
        if reused is not None:
            # Keep last-good snapshot (do not overwrite with weak set)
            return reused
        _save_last_good(debug_dir, api_loads)
        return api_loads

    # Persist empty/failed API body for debugging when present
    if last_api_body is not None:
        _write_echo_api_debug(debug_dir, last_api_body, 0)

    # API empty this cycle — try recent last-good before weak text fallback
    reused = _reuse_last_good_if_ok(debug_dir, [], reason="empty-api")
    if reused is not None:
        return reused

    # Fallback text ONLY if we still have nothing from API / last-good
    try:
        page_text = page.inner_text("body") or ""
        text_loads = _parse_cards_from_text(page_text, page.url or url)
        # Header count like "21 Loads" — if text under-counts badly, keep trying once more
        m = re.search(r"(\d+)\s+Loads?", page_text, re.I)
        header_n = int(m.group(1)) if m else 0
        if text_loads and (header_n == 0 or len(text_loads) >= max(5, header_n // 3)):
            log.info("[%s] Text fallback %d loads (header=%s)", SOURCE, len(text_loads), header_n or "?")
            # Still prefer last-good if text is weak vs recent API snapshot
            reused = _reuse_last_good_if_ok(debug_dir, text_loads, reason="weak-text")
            if reused is not None:
                return reused
            return text_loads
        if text_loads:
            log.warning(
                "[%s] Text fallback weak (%d vs header %s) — prefer last-good if available",
                SOURCE,
                len(text_loads),
                header_n,
            )
            reused = _reuse_last_good_if_ok(debug_dir, text_loads, reason="weak-text")
            if reused is not None:
                return reused
            return text_loads
    except Exception as exc:
        log.warning("[%s] text parse fail: %s", SOURCE, exc)

    try:
        dump_html_snippet(page.content(), debug_dir / "echo-last.html")
    except Exception:
        pass
    return []


def fetch(context, url: str, debug_dir: Path, page=None) -> list[dict]:
    owns_page = page is None
    try:
        if page is None:
            page = context.new_page()
        _attach_response_listener(page)
        already = False
        try:
            cur = (page.url or "").lower()
            already = "echo" in cur and "availableloads" in cur
        except Exception:
            already = False
        if not already:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(3000)
        return collect(page, url, debug_dir)
    except Exception as exc:
        log.warning("[%s] Fetch failed: %s", SOURCE, exc)
        return []
    finally:
        if owns_page and page is not None:
            try:
                page.close()
            except Exception:
                pass


def _attach_response_listener(page) -> None:
    if getattr(page, "_scanner_listener_attached", False):
        return
    page._scanner_api_payloads = []
    page._scanner_listener_attached = True

    def on_response(response):
        try:
            ct = (response.headers.get("content-type") or "").lower()
            if "json" not in ct:
                if response.request.resource_type not in ("xhr", "fetch"):
                    return
            u = response.url or ""
            if not re.search(r"echo|load|bookNow|available", u, re.I):
                return
            body = response.json()
            page._scanner_api_payloads.append({"url": u, "body": body})
        except Exception:
            return

    page.on("response", on_response)
