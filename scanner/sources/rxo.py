"""RXO Connect carrier load board extractor.

Prefers All-loads search/loadboard API (rich cities + dates) over Recommended DOM.
Nudges origin to Romeoville, IL with a useful deadhead when the UI allows.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Optional

from extract import (
    append_api_urls,
    dump_html_snippet,
    extract_loads_from_json,
    find_load_arrays,
    is_login_wall,
    normalize_load,
    scrape_dom_loads,
    wait_out_mfa,
)

log = logging.getLogger("scanner.rxo")
SOURCE = "RXO"

_LAST_GOOD_MAX_AGE_SEC = 10 * 60
_WEAK_FLOOR = 8
_MAX_PAGES = 8  # pageSize~20 → up to ~160 loads per cycle

_DATE_BLOB_RE = re.compile(
    r"(?:\b\d{4}-\d{2}-\d{2}\b)|"
    r"(?:\b\d{1,2}/\d{1,2}/\d{2,4}\b)|"
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}"
    r"(?:,?\s*\d{4})?(?:\s*,?\s*\d{1,2}:\d{2}\s*(?:AM|PM)?)?)",
    re.I,
)


def _last_good_path(debug_dir: Path) -> Path:
    return Path(debug_dir) / "rxo-last-good.json"


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
    if last_count <= 0:
        return False
    return new_count < max(_WEAK_FLOOR, int(last_count * 0.5))


def _merge_prefer_new(old: list[dict], new: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for L in old or []:
        lid = str(L.get("id") or "")
        if lid:
            by_id[lid] = L
        else:
            by_id[f"_anon_{len(by_id)}"] = L
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
    last_loads, last_ts = _load_last_good(debug_dir)
    if not last_loads or not last_ts:
        return None
    age = time.time() - last_ts
    if age >= _LAST_GOOD_MAX_AGE_SEC:
        log.info("[%s] last-good too old (%.0fs) — not reusing (%s)", SOURCE, age, reason)
        return None
    new_n = len(api_loads or [])
    last_n = len(last_loads)
    if new_n == 0 or _is_weak_vs_last(new_n, last_n):
        if new_n >= 1:
            merged = _merge_prefer_new(last_loads, api_loads)
            log.warning(
                "[%s] API weak (%d vs last-good %d, age %.0fs) — merging -> %d (%s)",
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


def _dig_date(obj: dict) -> str:
    if not isinstance(obj, dict):
        return ""
    for k in (
        "pickupDate",
        "pickup_date",
        "pickUpDate",
        "availableDate",
        "availabilityDate",
        "earliestPickupDate",
        "pickupStartDate",
        "pickupStart",
        "puDate",
        "startDate",
        "scheduledPickupDate",
        "originDate",
        "originPickupDateTimeInUTC",
        "scheduledArrivalEarly",
        "scheduledArrivalEarlyDateTimeInUTC",
        "scheduledArrivalLate",
    ):
        v = obj.get(k)
        if v not in (None, ""):
            return str(v).strip()
    for nest_key in (
        "pickup",
        "origin",
        "appointment",
        "appointmentTime",
        "serviceWindow",
        "schedule",
    ):
        nest = obj.get(nest_key)
        if isinstance(nest, dict):
            dug = _dig_date(nest)
            if dug:
                return dug
            for k in ("date", "startDate", "startTime", "start", "dateTime", "datetime",
                      "scheduledArrivalEarly", "scheduledArrivalEarlyDateTimeInUTC"):
                v = nest.get(k)
                if v not in (None, ""):
                    return str(v).strip()
        elif isinstance(nest, str) and nest.strip():
            return nest.strip()
    stops = obj.get("stops") or obj.get("loadStops") or obj.get("Stops")
    if isinstance(stops, list) and stops:
        # Prefer Pickup-typed stop
        ordered = list(stops)
        ordered.sort(
            key=lambda s: 0
            if isinstance(s, dict) and str(s.get("type") or "").lower().startswith("pick")
            else 1
        )
        for st0 in ordered:
            if isinstance(st0, dict):
                d = _dig_date(st0)
                if d:
                    return d
    for k, v in obj.items():
        kl = str(k).lower()
        if v in (None, "") or isinstance(v, (dict, list, bool)):
            continue
        if "pick" in kl and "date" in kl:
            return str(v).strip()
        if kl in ("availability", "availableon"):
            return str(v).strip()
        if "scheduledarrivalearly" in kl.replace("_", ""):
            return str(v).strip()
    return ""


def _peel_dt(dug: str) -> tuple[str, str]:
    dug = (dug or "").strip()
    if not dug:
        return "", ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2})", dug)
    if m:
        return m.group(1), m.group(2)
    m = re.match(
        r"^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s*\d{4})?)"
        r"(?:\s*,?\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?))?",
        dug,
        re.I,
    )
    if m:
        return m.group(1).strip(), (m.group(2) or "").strip()
    return dug, ""


def _enrich_rxo_from_raw(raw_item: dict, normalized: dict) -> dict:
    """Fill missing id / pickup_date / rate from raw API keys normalize may have missed."""
    out = dict(normalized)
    # Prefer stable RXO loadboard "number" (e.g. 24000967) over suggestion/hash ids
    num = raw_item.get("number")
    if num not in (None, ""):
        out["id"] = str(num).strip()
    elif not out.get("id"):
        rid = raw_item.get("alternateNumber") or raw_item.get("suggestionId")
        if rid not in (None, ""):
            out["id"] = str(rid).strip()

    if not out.get("pickup_date"):
        dug = _dig_date(raw_item)
        if dug:
            d, t = _peel_dt(dug)
            out["pickup_date"] = d or dug
            if t and not out.get("pickup_time"):
                out["pickup_time"] = t
            out["pickup"] = " ".join(
                x for x in (out.get("pickup_date") or "", out.get("pickup_time") or "") if x
            ).strip()

    if out.get("rate") in (None, "") and isinstance(raw_item, dict):
        for k in ("dmpRate", "genericDMPRate", "bidAmount", "bookNowPrice"):
            v = raw_item.get(k)
            if isinstance(v, (int, float)) and v:
                out["rate"] = float(v)
                break
            if isinstance(v, str) and v.strip():
                try:
                    out["rate"] = float(v.replace(",", "").replace("$", "").strip())
                    break
                except Exception:
                    pass
    return out


def _extract_from_payload(body: Any, url: str, default_url: str) -> list[dict]:
    """Prefer loadboard availableLoads.items; fall back to generic extract."""
    loads: list[dict] = []
    if isinstance(body, dict):
        al = body.get("availableLoads")
        items = None
        if isinstance(al, dict) and isinstance(al.get("items"), list):
            items = al["items"]
            log.info(
                "[%s] loadboard page=%s size=%s total=%s items=%d",
                SOURCE,
                al.get("currentPage"),
                al.get("pageSize"),
                al.get("totalItemCount"),
                len(items),
            )
        elif isinstance(body.get("items"), list):
            items = body["items"]
        if items:
            for item in items:
                if not isinstance(item, dict):
                    continue
                try:
                    n = normalize_load(item, SOURCE, default_url=default_url)
                    n = _enrich_rxo_from_raw(item, n)
                    if n.get("origin") or n.get("destination") or n.get("rate") or n.get("id"):
                        loads.append(n)
                except Exception as exc:
                    log.debug("[%s] normalize item skip: %s", SOURCE, exc)
            if loads:
                return loads

    found = extract_loads_from_json(body, SOURCE, default_url=default_url)
    if not found:
        return []
    try:
        arrays = find_load_arrays(body)
        arrays.sort(key=len, reverse=True)
        raw_by_id: dict[str, dict] = {}
        for arr in arrays[:3]:
            for item in arr:
                if not isinstance(item, dict):
                    continue
                rid = str(
                    item.get("number")
                    or item.get("id")
                    or item.get("loadId")
                    or item.get("load_id")
                    or item.get("loadNumber")
                    or item.get("shipmentId")
                    or item.get("alternateNumber")
                    or item.get("suggestionId")
                    or ""
                )
                if rid:
                    raw_by_id[rid] = item
        enriched = []
        for L in found:
            raw = raw_by_id.get(str(L.get("id") or ""))
            enriched.append(_enrich_rxo_from_raw(raw, L) if raw else L)
        return enriched
    except Exception as exc:
        log.warning("[%s] date enrich skipped: %s", SOURCE, exc)
        return found


def _payload_score(item: dict) -> tuple[int, int]:
    """Prefer search/loadboard over recommendations; prefer larger item sets."""
    url = (item.get("url") or "").lower()
    body = item.get("body")
    n = 0
    if isinstance(body, dict):
        al = body.get("availableLoads")
        if isinstance(al, dict) and isinstance(al.get("items"), list):
            n = len(al["items"])
        else:
            try:
                n = len(extract_loads_from_json(body, SOURCE, default_url=""))
            except Exception:
                n = 0
    elif isinstance(body, list):
        n = len(body)
    prio = 0
    if "search/loadboard" in url:
        prio = 3
    elif "availableloads" in url and "recommendation" not in url:
        prio = 2
    elif "recommendation" in url:
        prio = 1
    return prio, n


def _probe_filter_controls(page) -> dict:
    """Log visible search/filter controls for debugging."""
    try:
        info = page.evaluate(
            """() => {
              const out = {tabs: [], selects: [], inputs: [], buttons: []};
              document.querySelectorAll('[role=tab], .mat-tab-label').forEach(el => {
                out.tabs.push(((el.innerText||'')+'').trim().slice(0,40));
              });
              document.querySelectorAll('mat-select').forEach(el => {
                out.selects.push({
                  id: el.id||'',
                  text: ((el.innerText||'')+'').trim().slice(0,60),
                  w: Math.round(el.getBoundingClientRect().width)
                });
              });
              document.querySelectorAll('input').forEach(el => {
                const r = el.getBoundingClientRect();
                if (r.width < 2 || r.height < 2) return;
                out.inputs.push({
                  id: el.id||'', ph: el.placeholder||'',
                  cls: (el.className||'').toString().slice(0,80)
                });
              });
              document.querySelectorAll('button').forEach(el => {
                const t = ((el.innerText||'')+'').trim();
                if (!t) return;
                if (/search|apply|more|clear|all loads|recommended/i.test(t))
                  out.buttons.push(t.slice(0,40));
              });
              out.bodyHead = ((document.body&&document.body.innerText)||'').replace(/\\s+/g,' ').slice(0,240);
              return out;
            }"""
        )
        log.info("[%s] UI probe: %s", SOURCE, json.dumps(info, ensure_ascii=False)[:800])
        return info if isinstance(info, dict) else {}
    except Exception as exc:
        log.warning("[%s] UI probe failed: %s", SOURCE, exc)
        return {}


def _click_all_loads_tab(page) -> bool:
    try:
        for sel in (
            "#load-board-home-tab-name-1",
            "[id^='load-board-home-tab-name-1']",
            "#mat-tab-label-0-1",
        ):
            loc = page.locator(sel)
            if loc.count():
                loc.first.click(timeout=2500)
                page.wait_for_timeout(1200)
                log.info("[%s] Clicked All loads tab (%s)", SOURCE, sel)
                return True
        loc = page.get_by_role("tab", name=re.compile(r"all\s*loads", re.I))
        if loc.count():
            loc.first.click(timeout=2500)
            page.wait_for_timeout(1200)
            log.info("[%s] Clicked All loads tab (role)", SOURCE)
            return True
        page.get_by_text("All loads", exact=False).first.click(timeout=2500)
        page.wait_for_timeout(1200)
        log.info("[%s] Clicked All loads tab (text)", SOURCE)
        return True
    except Exception as exc:
        log.warning("[%s] All loads tab click failed: %s", SOURCE, exc)
        return False


def _set_origin_romeoville(page, radius_label: str = "150 MI") -> bool:
    """Open origin multi-select, pick Romeoville IL, set deadhead, Search."""
    try:
        # Close advance-search popup if open
        try:
            page.locator("#advance-search-close").click(timeout=800)
            page.wait_for_timeout(300)
        except Exception:
            pass

        opened = page.evaluate(
            """() => {
              const sel = document.querySelector('.origin-container mat-select')
                || document.querySelector('xpoc-mat-multi-select.origin-container mat-select')
                || document.querySelector('#mat-select-4');
              if (!sel) return false;
              try { sel.click(); } catch (e) { return false; }
              return true;
            }"""
        )
        if not opened:
            log.info("[%s] Origin mat-select not found", SOURCE)
            return False
        page.wait_for_timeout(700)

        inp = page.locator(
            "input.mat-select-search-input-single, "
            ".cdk-overlay-pane input[placeholder*='City'], "
            ".cdk-overlay-pane input[placeholder*='Zip']"
        )
        if inp.count() == 0:
            log.info("[%s] Origin search input not in overlay", SOURCE)
            page.keyboard.press("Escape")
            return False
        inp.first.click(timeout=2500)
        inp.first.fill("")
        inp.first.type("Romeoville", delay=45)
        page.wait_for_timeout(1100)

        chosen = False
        opts = page.locator("mat-option")
        for i in range(min(opts.count(), 12)):
            try:
                t = (opts.nth(i).inner_text() or "").strip()
            except Exception:
                continue
            if "Romeoville, IL" in t or re.search(r"Romeoville,\s*IL\b", t):
                opts.nth(i).click(timeout=2000)
                chosen = True
                log.info("[%s] Selected origin option: %s", SOURCE, t[:80])
                break
        if not chosen:
            for i in range(min(opts.count(), 12)):
                try:
                    t = (opts.nth(i).inner_text() or "").strip()
                except Exception:
                    continue
                if "60446" in t and "IL" in t:
                    opts.nth(i).click(timeout=2000)
                    chosen = True
                    log.info("[%s] Selected origin zip option: %s", SOURCE, t[:80])
                    break
        if not chosen:
            log.warning("[%s] No Romeoville, IL option in overlay", SOURCE)
            page.keyboard.press("Escape")
            return False

        page.wait_for_timeout(400)
        apply = page.locator(
            ".cdk-overlay-pane button:has-text('Apply'), "
            ".cdk-overlay-pane .mat-button:has-text('Apply')"
        )
        if apply.count():
            apply.first.click(timeout=2500)
            page.wait_for_timeout(600)
        else:
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)

        # Deadhead / radius
        try:
            page.evaluate(
                """() => { const dh = document.querySelector('#origin-dead-head'); if (dh) dh.click(); }"""
            )
            page.wait_for_timeout(400)
            for label in (radius_label, "150 MI", "100 MI", "250 MI"):
                o = page.locator("mat-option").filter(has_text=label)
                if o.count():
                    o.first.click(timeout=2000)
                    log.info("[%s] Set origin deadhead %s", SOURCE, label)
                    break
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception as exc:
            log.info("[%s] Deadhead set skipped: %s", SOURCE, exc)

        # Search
        try:
            btn = page.locator("button:has-text('Search')")
            if btn.count():
                btn.first.click(force=True, timeout=3000)
                page.wait_for_timeout(3500)
                log.info("[%s] Clicked Search", SOURCE)
            else:
                page.keyboard.press("Enter")
                page.wait_for_timeout(2500)
        except Exception as exc:
            log.warning("[%s] Search click failed: %s", SOURCE, exc)
        return True
    except Exception as exc:
        log.warning("[%s] Origin nudge failed: %s", SOURCE, exc)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False


def _paginate_next(page, times: int = 4) -> int:
    """Click Next page a few times so more loadboard API pages are captured."""
    clicked = 0
    for _ in range(max(0, times)):
        try:
            btn = page.get_by_label("Next page")
            if btn.count() == 0:
                break
            if btn.first.is_disabled():
                break
            before = len(getattr(page, "_scanner_api_payloads", []) or [])
            btn.first.click(timeout=2500)
            page.wait_for_timeout(2200)
            after = len(getattr(page, "_scanner_api_payloads", []) or [])
            clicked += 1
            if after <= before:
                # still ok — DOM may update without new listener race
                pass
        except Exception:
            break
    if clicked:
        log.info("[%s] Paginated Next x%d", SOURCE, clicked)
    return clicked


def _ensure_search(page) -> None:
    """Best-effort: All loads tab + Romeoville IL origin + DH, then wait for API."""
    try:
        _probe_filter_controls(page)
        _click_all_loads_tab(page)
        page.wait_for_timeout(800)
        ok = _set_origin_romeoville(page, radius_label="150 MI")
        if not ok:
            # Still on All loads — Search may refresh loadboard without origin
            try:
                btn = page.locator("button:has-text('Search')")
                if btn.count():
                    btn.first.click(force=True, timeout=2500)
                    page.wait_for_timeout(3000)
            except Exception:
                pass
        _paginate_next(page, times=_MAX_PAGES - 1)
    except Exception as exc:
        log.warning("[%s] search nudge failed: %s", SOURCE, exc)


def _dedupe_loads(loads: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    out: list[dict] = []
    for L in loads or []:
        lid = str(L.get("id") or "")
        if lid:
            if lid in by_id:
                # Prefer row with pickup_date
                prev = by_id[lid]
                if not prev.get("pickup_date") and L.get("pickup_date"):
                    by_id[lid] = L
                    # replace in out
                    for i, x in enumerate(out):
                        if str(x.get("id") or "") == lid:
                            out[i] = L
                            break
                continue
            by_id[lid] = L
        out.append(L)
    return out


def collect(page, url: str, debug_dir: Path) -> list[dict]:
    loads: list[dict] = []
    interesting_urls: list[str] = []

    try:
        payloads = list(getattr(page, "_scanner_api_payloads", None) or [])
        loadboard = [
            p for p in payloads
            if "search/loadboard" in ((p.get("url") or "").lower())
        ]
        # If any loadboard responses were captured, use ONLY those (skip thin recommendations)
        use = loadboard if loadboard else payloads
        ranked = sorted(
            enumerate(use),
            key=lambda pair: (_payload_score(pair[1]), pair[0]),
            reverse=True,
        )
        for _, item in ranked:
            body = item.get("body")
            resp_url = item.get("url") or ""
            if body is None:
                continue
            # When falling back (no loadboard), skip pure tag/recommendation noise if we
            # already have a decent set — but always take the first few.
            found = _extract_from_payload(body, resp_url, default_url=url)
            if not found:
                continue
            loads.extend(found)
            interesting_urls.append(resp_url)
            dated = sum(1 for L in found if L.get("pickup_date"))
            log.info(
                "[%s] API extracted %d loads (%d with pickup_date) from %s",
                SOURCE,
                len(found),
                dated,
                resp_url[:120],
            )
        loads = _dedupe_loads(loads)
        if loadboard:
            log.info("[%s] Used %d loadboard payload(s); unique loads=%d", SOURCE, len(loadboard), len(loads))
    except Exception as exc:
        log.warning("[%s] API parse error: %s", SOURCE, exc)

    if interesting_urls:
        append_api_urls(interesting_urls, debug_dir / "last_api_urls.txt")

    if loads:
        dated = sum(1 for L in loads if L.get("pickup_date"))
        log.info("[%s] API total unique=%d (%d dated)", SOURCE, len(loads), dated)
        reused = _reuse_last_good_if_ok(debug_dir, loads, reason="weak-api")
        if reused is not None:
            return reused
        _save_last_good(debug_dir, loads)
        return loads

    # Empty API — try last-good before DOM
    reused = _reuse_last_good_if_ok(debug_dir, [], reason="empty-api")
    if reused is not None:
        return reused

    try:
        try:
            body_l = (page.inner_text("body") or "").lower()
            url_l = (page.url or "").lower()
        except Exception:
            body_l, url_l = "", ""
        if (
            "multifactor" in url_l
            or "one-time code" in body_l
            or "enter your 6-digit" in body_l
        ):
            log.warning("[%s] MFA screen — waiting for you to enter the code…", SOURCE)
            wait_out_mfa(page, timeout_ms=180_000)
            try:
                if "available-loads" not in (page.url or "").lower():
                    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                    page.wait_for_timeout(8000)
            except Exception:
                pass
        if is_login_wall(page):
            log.warning("[%s] Login wall detected — skip this cycle (re-run START_LOGIN.bat)", SOURCE)
            reused = _reuse_last_good_if_ok(debug_dir, [], reason="login-wall")
            return reused or []
        loads = scrape_dom_loads(page, SOURCE, default_url=url)
        if loads:
            for L in loads:
                if L.get("pickup_date"):
                    continue
                blob = " ".join(
                    str(L.get(k) or "")
                    for k in ("pickup", "notes", "status", "delivery", "origin", "destination")
                )
                m = _DATE_BLOB_RE.search(blob)
                if m:
                    d, t = _peel_dt(m.group(0))
                    L["pickup_date"] = d or m.group(0)
                    if t and not L.get("pickup_time"):
                        L["pickup_time"] = t
                    L["pickup"] = " ".join(
                        x for x in (L.get("pickup_date") or "", L.get("pickup_time") or "") if x
                    )
            # Also parse dates from visible load cards if still blank
            try:
                card_dates = page.evaluate(
                    """() => {
                      const out = [];
                      document.querySelectorAll('[id*=\"available-loads-grid-load\"]').forEach(el => {
                        const id = (el.id||'');
                        const text = (el.innerText||'').replace(/\\s+/g,' ').trim();
                        out.push({id, text: text.slice(0,240)});
                      });
                      // fallback cards
                      if (!out.length) {
                        document.querySelectorAll('[id*=\"available-loads-grid-loads\"]').forEach(el => {
                          out.push({id: el.id||'', text: ((el.innerText||'')+'').replace(/\\s+/g,' ').slice(0,300)});
                        });
                      }
                      return out.slice(0, 40);
                    }"""
                )
                if isinstance(card_dates, list) and card_dates:
                    # Best-effort: if DOM loads lack dates, try matching by load number in card text
                    by_num = {str(L.get("id") or ""): L for L in loads}
                    for card in card_dates:
                        text = card.get("text") or ""
                        mnum = re.search(r"\b(\d{7,10})\b", text)
                        if not mnum:
                            continue
                        L = by_num.get(mnum.group(1))
                        if not L or L.get("pickup_date"):
                            continue
                        m = _DATE_BLOB_RE.search(text)
                        if m:
                            d, t = _peel_dt(m.group(0))
                            L["pickup_date"] = d or m.group(0)
                            if t and not L.get("pickup_time"):
                                L["pickup_time"] = t
            except Exception:
                pass
            dated = sum(1 for L in loads if L.get("pickup_date"))
            log.info("[%s] DOM extracted %d loads (%d with pickup_date)", SOURCE, len(loads), dated)
            reused = _reuse_last_good_if_ok(debug_dir, loads, reason="weak-dom")
            if reused is not None:
                return reused
            if loads:
                _save_last_good(debug_dir, loads)
    except Exception as exc:
        log.warning("[%s] DOM scrape error: %s", SOURCE, exc)

    if not loads:
        try:
            html = page.content()
            dump_html_snippet(html, debug_dir / "rxo-last.html")
            log.info("[%s] No loads found; dumped HTML snippet to debug/rxo-last.html", SOURCE)
        except Exception as exc:
            log.warning("[%s] Could not dump HTML: %s", SOURCE, exc)
        reused = _reuse_last_good_if_ok(debug_dir, [], reason="empty-all")
        if reused is not None:
            return reused

    return loads


def fetch(context, url: str, debug_dir: Path, page=None) -> list[dict]:
    owns_page = page is None
    try:
        if page is None:
            page = context.new_page()
        _attach_response_listener(page)
        # Clear prior payloads so this cycle's search responses win
        try:
            page._scanner_api_payloads = []
        except Exception:
            pass

        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        try:
            page.wait_for_load_state("networkidle", timeout=45_000)
        except Exception:
            pass
        try:
            page.wait_for_timeout(4000)
        except Exception:
            pass

        for _ in range(15):
            u = (page.url or "").lower()
            try:
                body = (page.inner_text("body") or "").lower()
            except Exception:
                body = ""
            if (
                "multifactor" in u
                or "one-time code" in body
                or "enter your 6-digit" in body
                or "verification code" in body
            ):
                break
            if "available" in body and ("load" in body or "equipment" in body or "origin" in body):
                break
            try:
                page.wait_for_timeout(1000)
            except Exception:
                break

        wait_out_mfa(page, timeout_ms=180_000)

        try:
            u = (page.url or "").lower()
            if "available-loads" not in u or "multifactor" in u:
                page.goto(url, wait_until="domcontentloaded", timeout=90_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=45_000)
                except Exception:
                    pass
                page.wait_for_timeout(6000)
        except Exception:
            pass

        # Nudge All-loads + Romeoville search before collect
        _ensure_search(page)
        return collect(page, url, debug_dir)
    except Exception as exc:
        msg = str(exc).lower()
        if any(x in msg for x in ("proxy", "err_tunnel", "net::", "timeout", "blocked", "403")):
            log.warning("[%s] Network/proxy error — skip this cycle: %s", SOURCE, exc)
        else:
            log.warning("[%s] Fetch failed — skip this cycle: %s", SOURCE, exc)
        try:
            if page is not None:
                dump_html_snippet(page.content(), debug_dir / "rxo-last.html")
        except Exception:
            pass
        reused = _reuse_last_good_if_ok(debug_dir, [], reason="fetch-error")
        return reused or []
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
            if "json" not in ct and "javascript" not in ct:
                req = response.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
            body = response.json()
            page._scanner_api_payloads.append({"url": response.url, "body": body})
        except Exception:
            return

    page.on("response", on_response)
