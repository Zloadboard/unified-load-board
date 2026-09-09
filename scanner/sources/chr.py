"""C.H. Robinson / Navisphere Carrier best-effort scraper.

No passwords. Relies on an already-logged-in Chrome tab
(https://www.navispherecarrier.com/). Prefers captured JSON API
payloads; falls back to DOM scrape via extract.scrape_dom_loads.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from extract import (
    dump_html_snippet,
    extract_loads_from_json,
    is_login_wall,
    normalize_load,
    scrape_dom_loads,
)

log = logging.getLogger("scanner.chr")

SOURCE = "CHR"
BOARD = "https://www.navispherecarrier.com/"

_ID_KEYS = (
    "loadId",
    "LoadId",
    "loadNumber",
    "LoadNumber",
    "shipmentId",
    "ShipmentId",
    "orderNumber",
    "OrderNumber",
    "id",
    "Id",
)


def _attach_response_listener(page) -> None:
    if getattr(page, "_scanner_chr_hooked", False):
        return

    def _on_response(response) -> None:
        try:
            url = (response.url or "").lower()
            ct = (response.headers or {}).get("content-type", "")
            if "json" not in ct.lower() and "json" not in url:
                # still try a few known path fragments
                if not any(
                    k in url
                    for k in (
                        "load",
                        "shipment",
                        "freight",
                        "search",
                        "available",
                        "navisphere",
                        "carrier",
                    )
                ):
                    return
            if response.status >= 400:
                return
            body = response.json()
        except Exception:
            return
        try:
            if not hasattr(page, "_scanner_api_payloads"):
                page._scanner_api_payloads = []
            page._scanner_api_payloads.append({"url": response.url, "body": body})
        except Exception:
            pass

    page.on("response", _on_response)
    try:
        page._scanner_chr_hooked = True
    except Exception:
        pass


def _first_str(item: dict, keys: tuple[str, ...]) -> str:
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return str(item[k]).strip()
    return ""


def _city_from(obj: Any) -> str:
    if not isinstance(obj, dict):
        return str(obj or "").strip()
    city = str(obj.get("city") or obj.get("City") or obj.get("name") or "").strip()
    state = str(
        obj.get("state")
        or obj.get("State")
        or obj.get("stateCode")
        or obj.get("StateCode")
        or ""
    ).strip()
    zipc = str(obj.get("postal") or obj.get("postalCode") or obj.get("Zip") or "").strip()
    if city and state and zipc:
        return f"{city}, {state} {zipc}"
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


def _from_item(item: dict, default_url: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    lid = _first_str(item, _ID_KEYS)
    # Origin / destination from common CHR/Navisphere shapes
    origin = (
        _city_from(item.get("origin") or item.get("Origin") or item.get("pickup") or {})
        or _first_str(
            item,
            ("originCity", "OriginCity", "pickupCity", "PickupCity", "originLocation"),
        )
    )
    dest = (
        _city_from(
            item.get("destination")
            or item.get("Destination")
            or item.get("delivery")
            or {}
        )
        or _first_str(
            item,
            (
                "destinationCity",
                "DestinationCity",
                "deliveryCity",
                "DeliveryCity",
                "destLocation",
            ),
        )
    )
    # Stops array fallback
    if (not origin or not dest) and isinstance(item.get("stops") or item.get("Stops"), list):
        stops = item.get("stops") or item.get("Stops") or []
        if stops:
            origin = origin or _city_from(stops[0] if isinstance(stops[0], dict) else {})
            dest = dest or _city_from(stops[-1] if isinstance(stops[-1], dict) else {})

    if not origin and not dest:
        return None

    rate = item.get("rate") or item.get("Rate") or item.get("bookNowRate") or item.get("price")
    try:
        rate = float(rate) if rate not in (None, "") else None
    except (TypeError, ValueError):
        rate = None

    miles = item.get("miles") or item.get("Miles") or item.get("distance") or item.get("Distance")
    try:
        miles = float(miles) if miles not in (None, "") else None
    except (TypeError, ValueError):
        miles = None

    weight = item.get("weight") or item.get("Weight")
    equip = _first_str(
        item,
        ("equipment", "Equipment", "equipmentType", "EquipmentType", "trailerType"),
    )
    pu_date = _first_str(
        item, ("pickupDate", "PickupDate", "pickUpDate", "originDate", "pickupStart")
    )
    de_date = _first_str(
        item, ("deliveryDate", "DeliveryDate", "destDate", "deliveryStart")
    )

    detail = _first_str(
        item, ("url", "detailUrl", "detail_url", "href", "loadUrl", "LoadUrl")
    )
    if detail and detail.lower().startswith("http"):
        url = detail
    elif lid:
        url = f"{BOARD.rstrip('/')}/?loadId={lid}"
    else:
        url = default_url or BOARD

    raw = {
        "id": lid or f"CHR-{origin}-{dest}-{pu_date or rate or ''}",
        "origin": origin,
        "destination": dest,
        "pickupCity": origin,
        "deliveryCity": dest,
        "pickupDate": pu_date,
        "deliveryDate": de_date,
        "equipment": equip,
        "miles": miles,
        "weight": weight if weight is not None else "",
        "rate": rate,
        "url": url,
        "notes": "",
    }
    try:
        return normalize_load(raw, SOURCE, default_url=url)
    except Exception:
        return None


def _walk_items(body: Any, out: list[dict], default_url: str, depth: int = 0) -> None:
    if depth > 6 or body is None:
        return
    if isinstance(body, list):
        for row in body[:500]:
            if isinstance(row, dict):
                # Heuristic: dict that looks like a load
                keys = {str(k).lower() for k in row.keys()}
                if keys & {
                    "loadid",
                    "loadnumber",
                    "origin",
                    "destination",
                    "pickupcity",
                    "miles",
                    "rate",
                    "stops",
                } or (
                    ("origin" in keys or "pickup" in keys or "origincity" in keys)
                    and ("destination" in keys or "delivery" in keys or "destinationcity" in keys)
                ):
                    n = _from_item(row, default_url)
                    if n:
                        out.append(n)
                else:
                    _walk_items(row, out, default_url, depth + 1)
            else:
                _walk_items(row, out, default_url, depth + 1)
        return
    if isinstance(body, dict):
        for key in (
            "loads",
            "Loads",
            "items",
            "Items",
            "results",
            "Results",
            "data",
            "Data",
            "availableLoads",
            "searchResults",
            "value",
        ):
            if key in body:
                _walk_items(body[key], out, default_url, depth + 1)
        # shallow self
        n = _from_item(body, default_url)
        if n and (body.get("origin") or body.get("Origin") or body.get("stops")):
            out.append(n)


def loads_from_payloads(payloads: list, default_url: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in payloads or []:
        body = item.get("body") if isinstance(item, dict) else item
        bucket: list[dict] = []
        _walk_items(body, bucket, default_url)
        # also try generic extractor
        try:
            bucket.extend(extract_loads_from_json(body, SOURCE, default_url=default_url))
        except Exception:
            pass
        for L in bucket:
            lid = str(L.get("id") or "")
            key = lid or json.dumps(L, sort_keys=True, default=str)[:120]
            if key in seen:
                continue
            seen.add(key)
            out.append(L)
    return out


def collect(page, url: str, debug_dir: Path) -> list[dict]:
    try:
        cur = (page.url or "").lower()
    except Exception:
        cur = ""
    if is_login_wall(page) or "login" in cur or "signin" in cur or "okta" in cur:
        log.warning("[%s] Login wall — sign into Navisphere Carrier in scanner Chrome", SOURCE)
        try:
            dump_html_snippet(page.content(), Path(debug_dir) / "chr-last.html")
        except Exception:
            pass
        return []

    # Give SPA a moment to fire XHR after attach/navigation
    try:
        page.wait_for_timeout(2500)
    except Exception:
        time.sleep(2)

    payloads = list(getattr(page, "_scanner_api_payloads", []) or [])
    api_loads = loads_from_payloads(payloads, url or BOARD)
    if api_loads:
        log.info("[%s] API/JSON %d loads from %d payloads", SOURCE, len(api_loads), len(payloads))
        try:
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            (Path(debug_dir) / "chr-api.json").write_text(
                json.dumps({"count": len(api_loads), "payloads": len(payloads)}, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        return api_loads

    # Soft nudge: try clicking Find Loads / Search if visible
    for sel in (
        "text=Find Loads",
        "text=Search Loads",
        "text=Available Loads",
        "button:has-text('Search')",
        "[data-testid*='search']",
    ):
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                loc.first.click(timeout=2000)
                page.wait_for_timeout(2500)
                break
        except Exception:
            continue

    payloads = list(getattr(page, "_scanner_api_payloads", []) or [])
    api_loads = loads_from_payloads(payloads, url or BOARD)
    if api_loads:
        log.info("[%s] API after nudge %d loads", SOURCE, len(api_loads))
        return api_loads

    try:
        dom = scrape_dom_loads(page, SOURCE, default_url=url or BOARD)
    except Exception as exc:
        log.warning("[%s] DOM scrape failed: %s", SOURCE, exc)
        dom = []
    if dom:
        log.info("[%s] DOM %d loads", SOURCE, len(dom))
        return dom

    try:
        dump_html_snippet(page.content(), Path(debug_dir) / "chr-last.html")
    except Exception:
        pass
    log.info("[%s] 0 loads (best-effort; login + Find Loads may be required)", SOURCE)
    return []


def fetch(context, url: str, debug_dir: Path, page=None) -> list[dict]:
    owns_page = page is None
    try:
        if page is None:
            page = context.new_page()
        try:
            page._scanner_api_payloads = []
        except Exception:
            pass
        _attach_response_listener(page)
        already = False
        try:
            cur = (page.url or "").lower()
            already = "navispherecarrier" in cur
        except Exception:
            already = False
        if not already:
            page.goto(url or BOARD, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(3000)
        return collect(page, url or BOARD, debug_dir)
    except Exception as exc:
        log.warning("[%s] Fetch failed: %s", SOURCE, exc)
        return []
    finally:
        if owns_page and page is not None:
            try:
                page.close()
            except Exception:
                pass
