"""Arrive Logistics find-loads scraper.

Real load # ("Arrive Load #N") is NOT a table column — it appears in the
expanded detail panel as span[data-testid=arriveLoadNumber]. That N is the
same as:
  - GraphQL getLoads data[].LoadBoardId (preferred)
  - tr[data-testid=load-row-N] (DOM, no click needed)
Expand fires getUserOffers(loadNumber:N) but does not reveal a different id.
Synthetic ARR-* ids are last-resort only.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from extract import normalize_load, dump_html_snippet, is_login_wall, extract_loads_from_json

log = logging.getLogger("scanner.arrive")
SOURCE = "Arrive"

_CITY = re.compile(r"([A-Za-z][A-Za-z .'\-]+,\s*[A-Z]{2})")
_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH = ("Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec")
_LOAD_ROW_TID = re.compile(r"load-row-(\d+)", re.I)


def _parse_stop(blob: str) -> dict:
    out = {"city": "", "date": "", "time": ""}
    if not blob:
        return out
    text = blob.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for ln in lines:
        m = _CITY.search(ln)
        if m and not re.search(r"\(\s*\d+\s*mi", ln, re.I):
            out["city"] = m.group(1).strip()
            break
    dow = ""
    mon_day = ""
    for i, ln in enumerate(lines):
        if ln[:3] in _DOW and len(ln) <= 4:
            dow = ln[:3]
            if i + 1 < len(lines):
                mm = re.match(r"^(" + "|".join(_MONTH) + r")\s+(\d{1,2})", lines[i+1], re.I)
                if mm:
                    mon_day = f"{mm.group(1)[:3].title()} {int(mm.group(2))}"
        mm = re.match(r"^(" + "|".join(_MONTH) + r")\s+(\d{1,2})$", ln, re.I)
        if mm and not mon_day:
            mon_day = f"{mm.group(1)[:3].title()} {int(mm.group(2))}"
    if dow and mon_day:
        out["date"] = f"{dow} {mon_day}"
    elif mon_day:
        out["date"] = mon_day
    for ln in lines:
        if re.search(r"\d{1,2}:\d{2}", ln):
            out["time"] = re.sub(r"\s+", " ", ln).strip()
            break
    return out


def _parse_weight(cell: str):
    if not cell:
        return ""
    s = cell.strip().replace(",", "")
    m = re.match(r"^([\d.]+)\s*[Kk]$", s)
    if m:
        return int(round(float(m.group(1)) * 1000))
    m = re.search(r"([\d.]+)\s*[Kk]", s)
    if m:
        return int(round(float(m.group(1)) * 1000))
    m = re.search(r"([\d.]+)", s)
    if m:
        return float(m.group(1))
    return cell.strip()


def _parse_rate(cell: str):
    if not cell:
        return None
    if re.search(r"contact\s*rep|offer\s*only", cell, re.I):
        return None
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", cell)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _equip(cell: str) -> str:
    c = (cell or "").strip().upper()
    mapping = {"V": "Van", "VR": "Van/Reefer", "R": "Reefer", "F": "Flatbed", "FD": "Flatbed"}
    return mapping.get(c, cell.strip())


def _synthetic_id(pu: dict, de: dict) -> str:
    """Last-resort id when Arrive LoadBoardId is missing."""
    lid = f"ARR-{pu.get('city')}-{de.get('city')}-{pu.get('date')}-{pu.get('time')}".replace(" ", "-")
    return re.sub(r"[^A-Za-z0-9.\-]+", "", lid)[:80]


def _arrive_local_parts(iso: Any, iana: Any) -> tuple[str, str]:
    """Format Arrive appt ISO -> ('Fri Sep 11', '11:00 CDT').

    Arrive's GraphQL timestamps are wall-clock values labeled Z (DOM shows
    11:00 CDT for PickupApptEarliest=...T11:00:00Z). Do not convert zones;
    only use IANA for the abbreviation label.
    """
    if not iso:
        return "", ""
    try:
        raw = str(iso).strip()
        # Strip tz suffix so fromisoformat keeps the wall clock
        raw_naive = re.sub(r"(Z|[+-]\d{2}:\d{2})$", "", raw)
        dt = datetime.fromisoformat(raw_naive)
        dow = dt.strftime("%a")
        mon_day = f"{dt.strftime('%b')} {dt.day}"
        tod = dt.strftime("%H:%M")
        tz = ""
        if iana:
            try:
                from zoneinfo import ZoneInfo
                from datetime import timezone as _tz
                # Attach a real UTC instant only to ask ZoneInfo for abbr at that date
                aware = dt.replace(tzinfo=_tz.utc).astimezone(ZoneInfo(str(iana)))
                # Wrong clock — we only want tzname() at roughly that calendar day
                # Better: localize naive wall time into IANA
                aware = dt.replace(tzinfo=ZoneInfo(str(iana)))
                tz = (aware.tzname() or "").strip()
            except Exception:
                tz = ""
        return f"{dow} {mon_day}", f"{tod} {tz}".strip()
    except Exception:
        return "", ""


def _city_st(city: Any, state: Any) -> str:
    c = (str(city).strip() if city not in (None, "") else "")
    s = (str(state).strip() if state not in (None, "") else "")
    if c and s:
        return f"{c}, {s}"
    return c or s


def _from_arrive_api_item(item: dict, url: str) -> dict | None:
    """Map GraphQL Load / getLoads row (LoadBoardId) into normalize_load input."""
    if not isinstance(item, dict):
        return None
    lid = item.get("LoadBoardId")
    if lid is None:
        lid = item.get("loadBoardId") or item.get("loadId") or item.get("id")
    if lid is None:
        return None
    lid_s = str(lid).strip()
    if not lid_s or not re.fullmatch(r"\d+", lid_s):
        # Still accept non-numeric real ids, but skip obvious junk
        if not lid_s or lid_s.lower() in {"none", "null"}:
            return None

    origin = _city_st(item.get("PickupEarlyCity"), item.get("PickupEarlyStateCode"))
    destination = _city_st(item.get("DeliveryLateCity"), item.get("DeliveryLateStateCode"))
    pu_date, pu_time = _arrive_local_parts(
        item.get("PickupApptEarliest") or item.get("PickupApptLatest"),
        item.get("PickupLocationIANACode"),
    )
    de_date, de_time = _arrive_local_parts(
        item.get("DeliveryApptEarliest") or item.get("DeliveryApptLatest"),
        item.get("DeliveryLocationIANACode"),
    )

    miles = item.get("Miles")
    try:
        miles = float(miles) if miles is not None else None
    except (TypeError, ValueError):
        miles = None

    weight = item.get("Weight")
    if weight is not None:
        try:
            weight = int(round(float(weight)))
        except (TypeError, ValueError):
            pass

    rate = item.get("TopSpend")
    if rate is not None:
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            rate = None

    eq = _equip(str(item.get("EquipmentType") or item.get("equipmentType") or ""))

    if not origin or not destination:
        return None

    raw = {
        "id": lid_s,
        "origin": origin,
        "destination": destination,
        "pickupCity": origin,
        "deliveryCity": destination,
        "pickupDate": pu_date,
        "pickupTime": pu_time,
        "deliveryDate": de_date,
        "deliveryTime": de_time,
        "pickup": f"{pu_date} {pu_time}".strip(),
        "delivery": f"{de_date} {de_time}".strip(),
        "miles": miles,
        "weight": weight if weight is not None else "",
        "equipment": eq,
        "rate": rate,
        "url": (
            f"https://carrier.arrivelogistics.com/find-loads?loadBoardId={lid_s}"
            if lid_s.isdigit()
            else url
        ),
        "notes": "",
        "status": str(item.get("LoadStatus") or ""),
    }
    try:
        return normalize_load(raw, SOURCE, default_url=url)
    except Exception as exc:
        log.warning("normalize fail (api): %s", exc)
        return None


def _walk_loadboard_items(obj: Any, out: list[dict], depth: int = 0) -> None:
    if depth > 12 or obj is None:
        return
    if isinstance(obj, dict):
        if "LoadBoardId" in obj or "loadBoardId" in obj:
            out.append(obj)
            return
        # Prefer known getLoads shape
        gl = obj.get("getLoads")
        if isinstance(gl, dict) and isinstance(gl.get("data"), list):
            for it in gl["data"]:
                if isinstance(it, dict):
                    out.append(it)
            return
        data = obj.get("data")
        if isinstance(data, dict):
            _walk_loadboard_items(data, out, depth + 1)
            if out:
                return
        for v in obj.values():
            _walk_loadboard_items(v, out, depth + 1)
            if len(out) >= 500:
                return
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict) and (
            "LoadBoardId" in obj[0] or "loadBoardId" in obj[0]
        ):
            out.extend(x for x in obj if isinstance(x, dict))
            return
        for it in obj[:50]:
            _walk_loadboard_items(it, out, depth + 1)
            if len(out) >= 500:
                return


def loads_from_arrive_payloads(payloads: list, url: str) -> list[dict]:
    """Extract loads from captured GraphQL/JSON (prefer LoadBoardId)."""
    found: list[dict] = []
    seen: set[str] = set()
    for item in payloads or []:
        body = item.get("body") if isinstance(item, dict) else item
        rows: list[dict] = []
        _walk_loadboard_items(body, rows)
        for row in rows:
            n = _from_arrive_api_item(row, url)
            if not n:
                continue
            lid = str(n.get("id") or "")
            if not lid or lid in seen:
                continue
            seen.add(lid)
            found.append(n)
    return found


def wait_for_rows(page, timeout_s: float = 20.0) -> bool:
    """Wait until skeleton loaders clear and real weight cells appear."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        ready = page.evaluate(
            """() => {
          const tds = [...document.querySelectorAll('table td')];
          const withText = tds.filter(td => (td.innerText||'').trim().length > 2).length;
          const hasWeight = tds.some(td => {
            const t = (td.innerText||'').trim();
            return /\\d+(\\.\\d+)?\\s*K\\b/i.test(t) || /^\\d{3,}$/.test(t);
          });
          const loadingSvg = [...document.querySelectorAll('table svg title')]
            .some(t => (t.textContent||'').includes('Loading'));
          const loadRows = document.querySelectorAll('tr[data-testid^="load-row-"]').length;
          return {withText, hasWeight, loadingSvg, loadRows};
        }"""
        )
        if ready.get("loadRows", 0) >= 1 and not ready.get("loadingSvg"):
            return True
        if ready.get("hasWeight") and ready.get("withText", 0) >= 10 and not ready.get("loadingSvg"):
            return True
        if ready.get("withText", 0) >= 40:
            return True
        page.wait_for_timeout(500)
    return False


def enrich_ids_by_expand(page, max_rows: int = 40) -> dict[str, str]:
    """Click/expand rows missing a confirmed Arrive Load #; read arriveLoadNumber.

    Returns map of lane-ish key or row index -> load number. Prefer GraphQL /
    load-row testids first — expand is slower and only needed when those fail.
    """
    return page.evaluate(
        """(maxRows) => {
      const out = {};
      const rows = [...document.querySelectorAll('tr[data-testid^="load-row-"]')].slice(0, maxRows);
      const sleep = (ms) => new Promise(r => setTimeout(r, ms));
      // sync path: if details already populated, read without clicking
      for (const tr of rows) {
        const tid = tr.getAttribute('data-testid') || '';
        const m = tid.match(/load-row-(\\d+)/i);
        if (!m) continue;
        const id = m[1];
        const detail = document.querySelector('tr[data-testid="load-details-' + id + '"]');
        const span = detail && detail.querySelector('[data-testid="arriveLoadNumber"]');
        const txt = span ? (span.innerText || '') : '';
        const mm = txt.match(/#\\s*(\\d+)/);
        if (mm) out[id] = mm[1];
        else out[id] = id; // row testid already IS the Arrive Load #
      }
      return out;
    }""",
        max_rows,
    ) or {}


def expand_row_read_load_number(page, load_board_id: str, timeout_ms: int = 2500) -> str | None:
    """Expand one row and read span[data-testid=arriveLoadNumber]; collapse after."""
    try:
        got = page.evaluate(
            """(id) => {
          const tr = document.querySelector('tr[data-testid="load-row-' + id + '"]');
          if (!tr) return null;
          if (tr.getAttribute('aria-expanded') !== 'true') tr.click();
          return id;
        }""",
            str(load_board_id),
        )
        if not got:
            return None
        page.wait_for_timeout(min(800, timeout_ms))
        txt = page.evaluate(
            """(id) => {
          const span = document.querySelector(
            'tr[data-testid="load-details-' + id + '"] [data-testid="arriveLoadNumber"]'
          );
          return span ? (span.innerText || '').trim() : '';
        }""",
            str(load_board_id),
        )
        m = re.search(r"#\s*(\d+)", txt or "")
        # collapse
        try:
            page.evaluate(
                """(id) => {
              const tr = document.querySelector('tr[data-testid="load-row-' + id + '"]');
              if (tr && tr.getAttribute('aria-expanded') === 'true') tr.click();
            }""",
                str(load_board_id),
            )
        except Exception:
            pass
        return m.group(1) if m else str(load_board_id)
    except Exception as exc:
        log.debug("expand read fail %s: %s", load_board_id, exc)
        return None



def parse_table(page, url: str) -> list[dict]:
    """Parse DOM rows; real Arrive Load # from load-row-{N} / load-details-{N}.

    N matches expanded panel "Arrive Load #N" (arriveLoadNumber). No per-row
    click required when testids are present.
    """
    raw_rows = page.evaluate(
        """() => {
      const table = document.querySelector('table') || document.querySelector('[data-testid="load-board-table"]');
      if (!table) return [];
      const trs = [...table.querySelectorAll('tbody tr, tr')];
      return trs.map(tr => {
        const tid = tr.getAttribute('data-testid') || '';
        const m = tid.match(/load-row-(\\d+)/i);
        const cells = [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim());
        return { loadId: m ? m[1] : null, testId: tid, cells };
      }).filter(r => r.cells.length >= 5 && r.cells.filter(c => c && c.length > 1).length >= 3);
    }"""
    )
    loads = []
    seen = set()
    for row in raw_rows or []:
        if isinstance(row, list):
            # backward compat if evaluate ever returns bare cell arrays
            cells = row
            load_id = None
        else:
            cells = row.get("cells") or []
            load_id = row.get("loadId")

        pickup_blob = cells[0] if len(cells) > 0 else ""
        deliver_blob = cells[1] if len(cells) > 1 else ""
        miles = None
        weight = ""
        eq = ""
        rate = None
        # Positional: [0]=pickup [1]=deliver [2]=icon [3]=miles [4]=weight [5]=eq [6]=price
        if len(cells) > 3 and re.fullmatch(r"[\d,]+", str(cells[3]).replace(",", "")):
            try:
                miles = float(str(cells[3]).replace(",", ""))
            except ValueError:
                pass
        if len(cells) > 4:
            weight = _parse_weight(cells[4])
        if len(cells) > 5:
            eq = _equip(cells[5])
        if len(cells) > 6:
            rate = _parse_rate(cells[6])

        pu = _parse_stop(pickup_blob)
        de = _parse_stop(deliver_blob)
        if not pu["city"] or not de["city"]:
            continue
        if miles is None and rate is None and not weight:
            continue

        if load_id and re.fullmatch(r"\d+", str(load_id)):
            lid = str(load_id)
        else:
            # last-resort synthetic (only when DOM has no load-row id)
            lid = _synthetic_id(pu, de)

        key = lid if re.fullmatch(r"\d+", lid) else (pu["city"], de["city"], pu["date"], pu["time"], miles, rate)
        if key in seen:
            continue
        seen.add(key)

        detail_url = (
            f"https://carrier.arrivelogistics.com/find-loads?loadBoardId={lid}"
            if re.fullmatch(r"\d+", str(lid))
            else url
        )
        raw = {
            "id": lid,
            "origin": pu["city"],
            "destination": de["city"],
            "pickupCity": pu["city"],
            "deliveryCity": de["city"],
            "pickupDate": pu["date"],
            "pickupTime": pu["time"],
            "deliveryDate": de["date"],
            "deliveryTime": de["time"],
            "pickup": f"{pu['date']} {pu['time']}".strip(),
            "delivery": f"{de['date']} {de['time']}".strip(),
            "miles": miles,
            "weight": weight,
            "equipment": eq,
            "rate": rate,
            "url": detail_url,
            "notes": "",
        }
        try:
            loads.append(normalize_load(raw, SOURCE, default_url=url))
        except Exception as exc:
            log.warning("normalize fail: %s", exc)
    return loads


def collect(page, url: str, debug_dir: Path) -> list[dict]:
    if is_login_wall(page):
        log.warning("[%s] Login wall", SOURCE)
        return []

    try:
        need = page.evaluate(
            """() => {
          const tds = [...document.querySelectorAll('table td')];
          const withText = tds.filter(td => (td.innerText||'').trim().length > 2).length;
          const loadRows = document.querySelectorAll('tr[data-testid^="load-row-"]').length;
          return withText < 10 && loadRows < 1;
        }"""
        )
        if need:
            btn = page.get_by_text("Refresh Results", exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(800)
    except Exception:
        pass

    wait_for_rows(page, timeout_s=25)

    payloads = getattr(page, "_scanner_api_payloads", None) or []
    api_loads = loads_from_arrive_payloads(payloads, url)
    if not api_loads:
        # Nudge a refresh so GraphQL getLoads is captured when tab was already open
        try:
            before = len(payloads)
            btn = page.get_by_text("Refresh Results", exact=False)
            if btn.count() > 0:
                btn.first.click(timeout=3000)
                page.wait_for_timeout(2500)
                wait_for_rows(page, timeout_s=15)
                payloads = getattr(page, "_scanner_api_payloads", None) or []
                if len(payloads) > before:
                    api_loads = loads_from_arrive_payloads(payloads, url)
        except Exception:
            pass

    if api_loads:
        log.info("[%s] GraphQL/API LoadBoardId %d loads", SOURCE, len(api_loads))
        return api_loads

    loads = parse_table(page, url)
    if loads:
        real_n = sum(1 for l in loads if re.fullmatch(r"\d+", str(l.get("id") or "")))
        log.info("[%s] Table parsed %d loads (%d with LoadBoardId)", SOURCE, len(loads), real_n)
        return loads

    # Generic JSON walk last
    for item in payloads:
        found = extract_loads_from_json(item.get("body"), SOURCE, default_url=url)
        if found:
            loads.extend(found)
    if loads:
        log.info("[%s] API fallback %d loads", SOURCE, len(loads))
        return loads

    dump_html_snippet(page.content(), debug_dir / "arrive-last.html")
    return []


def fetch(context, url: str, debug_dir: Path, page=None) -> list[dict]:
    owns = page is None
    try:
        if page is None:
            page = context.new_page()
        _attach(page)
        already = False
        try:
            cur = (page.url or "").lower()
            already = "arrivelogistics" in cur and "find-loads" in cur
        except Exception:
            already = False
        if not already:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(2000)
        return collect(page, page.url or url, debug_dir)
    except Exception as exc:
        log.warning("[%s] fetch fail: %s", SOURCE, exc)
        return []
    finally:
        if owns and page is not None:
            try:
                page.close()
            except Exception:
                pass


def _attach(page):
    if getattr(page, "_scanner_listener_attached", False):
        return
    page._scanner_api_payloads = []
    page._scanner_listener_attached = True

    def on_response(response):
        try:
            ct = (response.headers.get("content-type") or "").lower()
            if "json" not in ct and response.request.resource_type not in ("xhr", "fetch"):
                return
            page._scanner_api_payloads.append({"url": response.url, "body": response.json()})
        except Exception:
            return

    page.on("response", on_response)
