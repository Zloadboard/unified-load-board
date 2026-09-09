"""ArcBest / MoLo - parse Available Shipments from Vue app state.

MoLo postings live on the ArcBest portal as shipmentType == 'MoLoTL'.
Real Load # is shipmentSummary.referenceNumber (used in portal mailto
subjects as "Inquiry About Load #…"). shipmentId is ArcBest's internal id
(also in hidden search-tags as ID:…). Prefer Vue shipmentsListApp data —
no per-row expand required. Card DOM parse remains a fallback.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from extract import normalize_load, dump_html_snippet, is_login_wall

log = logging.getLogger("scanner.arcbest")
SOURCE = "ArcBest"
SOURCE_MOLO = "MoLo"
BOARD = "https://carriers.arcb.com/Shipments"

_CITY = re.compile(r"([A-Za-z][A-Za-z .'\-]+,\s*[A-Z]{2})")
_DT = re.compile(r"(\d{2}-\d{2}-\d{4}\s+\d{1,2}:\d{2}\s*\([A-Z]{2,4}\))")
_MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
_SEARCH_ID = re.compile(r"ID:(\d+)", re.I)
_SEARCH_ROUTE = re.compile(r"ROUTE:([A-Za-z0-9\-]+)", re.I)


def _is_molo(shipment_type: str | None) -> bool:
    return str(shipment_type or "").strip().lower() in {"molotl", "molo"}


def _source_for(shipment_type: str | None) -> str:
    return SOURCE_MOLO if _is_molo(shipment_type) else SOURCE


def _loc_city(loc) -> str:
    if not isinstance(loc, dict):
        return ""
    city = str(loc.get("city") or "").strip()
    state = str(loc.get("state") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return city or state


def _fmt_card_dt(iso: str | None, tz: str | None) -> tuple[str, str, str]:
    """Return (date MM-DD-YYYY or ISO date, time with optional tz, combined)."""
    if not iso:
        return "", "", ""
    s = str(iso).strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T\s]+(\d{1,2}:\d{2})", s)
    if m:
        y, mo, d, tm = m.group(1), m.group(2), m.group(3), m.group(4)
        date_mdy = f"{mo}-{d}-{y}"
        tz_s = str(tz or "").strip()
        time_part = f"{tm} ({tz_s})" if tz_s else tm
        return date_mdy, time_part, f"{date_mdy} {time_part}".strip()
    m2 = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)
    if m2:
        date_mdy = f"{m2.group(2)}-{m2.group(3)}-{m2.group(1)}"
        return date_mdy, "", date_mdy
    return s, "", s


def _load_id(summary: dict) -> str:
    """Portal Load # = referenceNumber; fall back to ArcBest shipmentId."""
    ref = summary.get("referenceNumber")
    if ref is not None and str(ref).strip():
        return str(ref).strip()
    sid = summary.get("shipmentId")
    if sid is not None and str(sid).strip():
        return str(sid).strip()
    return ""


def _summary_to_raw(s: dict, url: str) -> dict | None:
    if not isinstance(s, dict):
        return None
    origin = _loc_city(s.get("shipperLocation"))
    dest = _loc_city(s.get("consigneeLocation"))
    if not origin or not dest:
        return None

    lid = _load_id(s)
    if not lid:
        return None

    pu_d, pu_t, pu_comb = _fmt_card_dt(s.get("pickupStartDateTime"), s.get("pickupTimeZone"))
    de_d, de_t, de_comb = _fmt_card_dt(s.get("deliveryStartDateTime"), s.get("deliveryTimeZone"))

    equips = s.get("equipmentTypes") or []
    if isinstance(equips, list):
        equip = ", ".join(str(x) for x in equips if x)
    else:
        equip = str(equips or "")

    weight = s.get("weight")
    if weight is not None and weight != "":
        try:
            weight = f"{int(float(weight)):,}"
        except (TypeError, ValueError):
            weight = str(weight)

    miles = s.get("miles")
    try:
        miles = float(miles) if miles is not None and miles != "" else None
    except (TypeError, ValueError):
        miles = None

    rate = s.get("suggestedRate")
    if rate is None:
        rate = s.get("currentOfferAmount")
    try:
        rate = float(rate) if rate is not None and rate != "" else None
    except (TypeError, ValueError):
        rate = None

    partial = bool(s.get("partial"))
    service = "TL"
    st = str(s.get("shipmentType") or "")
    if st.lower() == "expedited":
        service = "EXP"
    fp = "Partial" if partial else "Full"
    status_bits = [service, fp, str(s.get("status") or "").strip()]
    if s.get("preferred"):
        status_bits.append("Preferred")
    status = " ".join(x for x in status_bits if x)

    notes_parts = []
    if s.get("shipmentId") is not None:
        notes_parts.append(f"shipmentId={s.get('shipmentId')}")
    if s.get("referenceNumber"):
        notes_parts.append(f"ref={s.get('referenceNumber')}")
    if st:
        notes_parts.append(f"type={st}")

    return {
        "id": lid,
        "origin": origin,
        "destination": dest,
        "pickupCity": origin,
        "deliveryCity": dest,
        "pickupDate": pu_d,
        "pickupTime": pu_t,
        "deliveryDate": de_d,
        "deliveryTime": de_t,
        "pickup": pu_comb,
        "delivery": de_comb,
        "equipment": equip,
        "weight": weight or "",
        "miles": miles,
        "rate": rate,
        "status": status,
        "url": url or BOARD,
        "notes": " | ".join(notes_parts),
        "shipmentType": st,
        "referenceNumber": s.get("referenceNumber"),
        "shipmentId": s.get("shipmentId"),
    }


def _read_vue_summaries_raw(page) -> list | None:
    """Pull plain shipmentSummaries from the Vue root (or $data)."""
    return page.evaluate(
        """() => {
          const app = window.shipmentsListApp || null;
          if (!app) return null;
          let list = app.shipmentSummaries;
          if (!list && app.$data) list = app.$data.shipmentSummaries;
          if (!list || typeof list.length !== 'number') return null;
          const out = [];
          for (let i = 0; i < list.length; i++) {
            const s = list[i];
            if (!s) continue;
            const ship = s.shipperLocation || {};
            const cons = s.consigneeLocation || {};
            out.push({
              shipmentId: s.shipmentId,
              referenceNumber: s.referenceNumber,
              shipmentType: s.shipmentType,
              source: s.source,
              status: s.status,
              partial: s.partial,
              preferred: s.preferred,
              suggestedRate: s.suggestedRate,
              currentOfferAmount: s.currentOfferAmount,
              weight: s.weight,
              miles: s.miles,
              equipmentTypes: s.equipmentTypes,
              pickupStartDateTime: s.pickupStartDateTime,
              pickupTimeZone: s.pickupTimeZone,
              deliveryStartDateTime: s.deliveryStartDateTime,
              deliveryTimeZone: s.deliveryTimeZone,
              shipperLocation: { city: ship.city || null, state: ship.state || null },
              consigneeLocation: { city: cons.city || null, state: cons.state || null }
            });
          }
          return out;
        }"""
    )


def wait_for_vue_summaries(page, timeout_ms: int = 15_000) -> bool:
    """Block until shipmentsListApp has at least one summary (CDP attach path)."""
    try:
        page.wait_for_function(
            """() => {
              const app = window.shipmentsListApp;
              if (!app) return false;
              const list = app.shipmentSummaries
                || (app.$data && app.$data.shipmentSummaries);
              return !!(list && list.length > 0);
            }""",
            timeout=timeout_ms,
        )
        return True
    except Exception as exc:
        log.debug("[%s] wait_for_vue_summaries: %s", SOURCE, exc)
        return False


def parse_vue_summaries(page, url: str) -> list[dict]:
    """Read window.shipmentsListApp.shipmentSummaries (preferred)."""
    try:
        summaries = _read_vue_summaries_raw(page)
    except Exception as exc:
        log.debug("[%s] Vue summaries unavailable: %s", SOURCE, exc)
        return []

    if not summaries:
        return []

    loads: list[dict] = []
    seen: set[str] = set()
    molo_n = 0
    for s in summaries:
        raw = _summary_to_raw(s, url)
        if not raw:
            continue
        src = _source_for(s.get("shipmentType"))
        if src == SOURCE_MOLO:
            molo_n += 1
        try:
            L = normalize_load(raw, src, default_url=url or BOARD)
        except Exception:
            continue
        # Keep real id (normalize_load may invent hash ids if blank — we guard above)
        if raw.get("id"):
            L["id"] = str(raw["id"])
        k = str(L.get("id") or "")
        if not k or k in seen:
            continue
        seen.add(k)
        loads.append(L)

    if loads:
        log.info(
            "[%s] Vue summaries parsed %d loads (MoLo=%d)",
            SOURCE,
            len(loads),
            molo_n,
        )
    return loads


def _parse_card(text: str, url: str, search_tags: str = "") -> dict | None:
    text = (text or "").replace("\u2013", "-").replace("\u2014", "-")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 6:
        return None
    cities = []
    for ln in lines:
        if _CITY.fullmatch(ln.strip()):
            cities.append(ln.strip())
    if len(cities) < 2:
        found = _CITY.findall(text)
        cities = found[:2]
    if len(cities) < 2:
        return None
    dts = _DT.findall(text)
    pu_dt = dts[0] if dts else ""
    de_dt = dts[1] if len(dts) > 1 else ""

    def split_dt(s):
        m = re.match(r"(\d{2}-\d{2}-\d{4})\s+(.+)", s or "")
        if m:
            return m.group(1), m.group(2)
        return s, ""

    pu_d, pu_t = split_dt(pu_dt)
    de_d, de_t = split_dt(de_dt)

    equip = ""
    for ln in lines:
        if re.search(r"van|reefer|flatbed|power only|expedite", ln, re.I):
            if not re.search(r"book it|view details|place offer", ln, re.I):
                equip = ln
                break

    weight = ""
    miles = None
    nums = []
    for ln in lines:
        if re.fullmatch(r"[\d,]+", ln):
            nums.append(ln)
    if len(nums) >= 2:
        a, b = float(nums[0].replace(",", "")), float(nums[1].replace(",", ""))
        if a > 1000 and b < 5000:
            weight, miles = nums[0], b
        elif b > 1000 and a < 5000:
            weight, miles = nums[1], a
        else:
            weight, miles = nums[0], b
    elif len(nums) == 1:
        n = float(nums[0].replace(",", ""))
        if n > 5000:
            weight = nums[0]
        else:
            miles = n

    rate = None
    m = _MONEY.search(text)
    if m:
        rate = float(m.group(1).replace(",", ""))

    service = lines[0] if lines else ""
    fp = lines[1] if len(lines) > 1 else ""
    status = f"{service} {fp}".strip()

    # Prefer real ids from hidden search-tags (ROUTE=referenceNumber / ID=shipmentId)
    tags = search_tags or ""
    route = (_SEARCH_ROUTE.search(tags) or _SEARCH_ROUTE.search(text) or (None))
    sid = (_SEARCH_ID.search(tags) or _SEARCH_ID.search(text) or (None))
    lid = ""
    if route:
        lid = route.group(1).strip()
    elif sid:
        lid = sid.group(1).strip()
    if not lid:
        # Last resort synthetic — only when Vue path unavailable
        lid = f"ARC-{cities[0]}-{cities[1]}-{pu_d}-{rate or ''}".replace(" ", "-")
        lid = re.sub(r"[^A-Za-z0-9.\-]+", "", lid)[:80]

    # Heuristic MoLo: portal tags MoLoTL as TL + MasterMind; card text alone
    # cannot see shipmentType — leave source ArcBest in DOM fallback unless
    # search-tags / surrounding text mention MoLo.
    shipment_type = ""
    if re.search(r"molo", text + " " + tags, re.I):
        shipment_type = "MoLoTL"

    raw = {
        "id": lid,
        "origin": cities[0],
        "destination": cities[1],
        "pickupCity": cities[0],
        "deliveryCity": cities[1],
        "pickupDate": pu_d,
        "pickupTime": pu_t,
        "deliveryDate": de_d,
        "deliveryTime": de_t,
        "pickup": pu_dt,
        "delivery": de_dt,
        "equipment": equip,
        "weight": weight,
        "miles": miles,
        "rate": rate,
        "status": status,
        "url": url or BOARD,
        "notes": (f"tags={tags}" if tags else ""),
        "shipmentType": shipment_type,
    }
    src = _source_for(shipment_type)
    try:
        L = normalize_load(raw, src, default_url=url or BOARD)
    except Exception:
        return None
    if lid:
        L["id"] = str(lid)
    return L


def parse_cards(page, url: str) -> list[dict]:
    rows = page.evaluate(
        """() => {
      const tagText = (root) => {
        if (!root) return '';
        const els = [
          ...root.querySelectorAll('.search-tags, .hidden.search-tags, [class*="search-tags"]')
        ];
        return els.map(e => (e.innerText || e.textContent || '').trim()).filter(Boolean).join(' ');
      };
      let nodes = [...document.querySelectorAll('.shipment-summary-card')];
      if (!nodes.length) {
        nodes = [...document.querySelectorAll('.shipment-summary')];
      }
      const out = [];
      const seen = new Set();
      for (const el of nodes) {
        const t = (el.innerText || '').trim();
        if (t.length < 40 || t.length > 1200) continue;
        const key = t.replace(/\\s+/g, ' ').slice(0, 180);
        if (seen.has(key)) continue;
        seen.add(key);
        let tags = tagText(el);
        if (!tags) {
          let p = el.parentElement;
          for (let i = 0; i < 4 && p && !tags; i++, p = p.parentElement) {
            tags = tagText(p);
          }
        }
        if (!tags && el.previousElementSibling && /search-tags/i.test(el.previousElementSibling.className || '')) {
          tags = (el.previousElementSibling.innerText || el.previousElementSibling.textContent || '').trim();
        }
        if (!tags && el.nextElementSibling && /search-tags/i.test(el.nextElementSibling.className || '')) {
          tags = (el.nextElementSibling.innerText || el.nextElementSibling.textContent || '').trim();
        }
        out.push({ text: t, tags: tags || '' });
      }
      return out;
    }"""
    )
    loads = []
    seen_ids = set()
    for row in rows or []:
        if isinstance(row, dict):
            t, tags = row.get("text") or "", row.get("tags") or ""
        else:
            t, tags = str(row), ""
        L = _parse_card(t, url, tags)
        if not L:
            continue
        kid = str(L.get("id") or "")
        if kid and kid in seen_ids:
            continue
        k = (
            L.get("pickup_city"),
            L.get("delivery_city"),
            L.get("pickup_date"),
            L.get("pickup_time"),
            L.get("delivery_date"),
            L.get("delivery_time"),
            L.get("rate"),
            L.get("weight"),
            L.get("miles"),
        )
        if not kid and k in seen_ids:
            continue
        seen_ids.add(kid or k)
        loads.append(L)
    return loads


def collect(page, url: str, debug_dir: Path) -> list[dict]:
    if is_login_wall(page):
        log.warning("[%s] Login wall", SOURCE)
        return []
    # CDP attach often hits the tab mid-render — wait briefly for Vue data.
    wait_for_vue_summaries(page, timeout_ms=12_000)
    loads = parse_vue_summaries(page, url)
    if not loads:
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass
        wait_for_vue_summaries(page, timeout_ms=8_000)
        loads = parse_vue_summaries(page, url)
    if loads:
        return loads
    loads = parse_cards(page, url)
    if loads:
        real = sum(
            1
            for L in loads
            if str(L.get("id") or "").isdigit()
            or not str(L.get("id") or "").upper().startswith("ARC-")
        )
        log.info(
            "[%s] Cards parsed %d loads (Vue unavailable; realish_ids=%d)",
            SOURCE,
            len(loads),
            real,
        )
        return loads
    dump_html_snippet(page.content(), debug_dir / "arcbest-last.html")
    return []


def fetch(context, url: str, debug_dir: Path, page=None) -> list[dict]:
    owns = page is None
    try:
        if page is None:
            page = context.new_page()
        already = False
        try:
            cur = (page.url or "").lower()
            already = "arcb.com" in cur and "shipment" in cur
        except Exception:
            already = False
        if not already:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(5000)
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
