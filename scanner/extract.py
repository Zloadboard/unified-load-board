"""Shared helpers: normalize load dicts, merge, write JSON, API/DOM extractors."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from cleanse import cleanse_loads

log = logging.getLogger("scanner.extract")

SCHEMA_KEYS = (
    "id",
    "source",
    "pickup_city",
    "delivery_city",
    "origin",
    "destination",
    "pickup_date",
    "pickup_time",
    "delivery_date",
    "delivery_time",
    "pickup",
    "delivery",
    "weight",
    "pallets",
    "equipment",
    "miles",
    "rate",
    "status",
    "url",
    "notes",
    "first_seen_at",
    "seen_age",
)

# Echo must stay listed — normalize_load drops unknown sources, which silently
# emptied Echo rows when VALID_SOURCES lacked it (see _parse_api_items except).
VALID_SOURCES = frozenset({"Arrive", "RXO", "ArcBest", "Echo", "MoLo", "CHR"})

# Keys that suggest a JSON object is a load / shipment row
_ORIGIN_KEYS = ("origin", "originCity", "origin_city", "pickupCity", "pickup_city",
                "fromCity", "from_city", "originLocation", "shipFrom", "puCity",
                "pickupLocation", "puLocation")
_DEST_KEYS = ("destination", "destCity", "dest_city", "destinationCity", "deliveryCity",
              "delivery_city", "toCity", "to_city", "destinationLocation", "shipTo", "delCity",
              "deliveryLocation", "dropLocation")
_RATE_KEYS = ("rate", "allInRate", "all_in_rate", "totalRate", "total_rate", "customerRate",
              "lineHaul", "linehaul", "amount", "price", "offerRate", "postedRate",
              "bookItRate", "buyRate", "sellRate", "carrierRate", "dmpRate",
              "genericDMPRate", "bookNowPrice", "buyItNowRate", "TopSpend", "topSpend")
_ID_KEYS = ("id", "loadId", "load_id", "LoadBoardId", "loadBoardId", "shipmentId", "shipment_id",
            "orderId", "order_id", "referenceNumber", "refNumber", "ref", "proNumber",
            "loadNumber", "load_number", "loadNum", "shipmentNumber", "orderNumber",
            "confirmationNumber", "bolNumber")
_EQUIP_KEYS = ("equipment", "equipmentType", "equipment_type", "trailerType", "trailer_type",
               "eqType", "mode", "equipmentTypeName", "trailer")
_PICKUP_DATE_KEYS = ("pickup_date", "pickupDate", "puDate", "pu_date", "pickUpDate",
                     "originDate", "availableDate", "availabilityDate", "shipDate",
                     "pickupDateTime", "puDateTime", "earliestPickupDate", "latestPickupDate",
                     "pickupStartDate", "pickupEndDate", "pickupStart", "pickupEnd",
                     "puStartDate", "puEndDate", "puStart", "startDate", "availableOn",
                     "scheduledPickupDate", "scheduledPickup", "earlyPickupDate",
                     "latePickupDate", "pickupWindowStart", "pickupWindowEnd",
                     "originPickupDateTimeInUTC", "scheduledArrivalEarly",
                     "scheduledArrivalEarlyDateTimeInUTC")
_PICKUP_TIME_KEYS = ("pickup_time", "pickupTime", "puTime", "pu_time", "pickUpTime",
                     "originTime", "availableTime", "pickupAppointmentTime",
                     "pickupStartTime", "puStartTime", "earlyPickupTime")
_DELIVERY_DATE_KEYS = ("delivery_date", "deliveryDate", "delDate", "del_date",
                       "destDate", "dueDate", "deliveryBy", "deliveryDateTime",
                       "earliestDeliveryDate", "latestDeliveryDate", "dropDate",
                       "deliveryStartDate", "deliveryEndDate", "deliveryStart",
                       "delStartDate", "dropStartDate")
_DELIVERY_TIME_KEYS = ("delivery_time", "deliveryTime", "delTime", "del_time",
                       "destTime", "dueTime", "deliveryAppointmentTime", "dropTime",
                       "deliveryStartTime")
# Combined date/time fallbacks (legacy)
_PICKUP_KEYS = ("pickup",) + _PICKUP_DATE_KEYS
_DELIVERY_KEYS = ("delivery",) + _DELIVERY_DATE_KEYS
_MILES_KEYS = ("miles", "distance", "totalMiles", "total_miles", "mileage", "loadedMiles",
               "tripMiles", "estimatedMiles")
_STATUS_KEYS = ("status", "loadStatus", "load_status", "shipmentStatus")
_URL_KEYS = ("url", "link", "detailUrl", "detail_url", "href")
_NOTES_KEYS = ("notes", "comments", "comment", "remarks", "description", "specialInstructions",
               "instructions")
_WEIGHT_KEYS = ("weight", "totalWeight", "total_weight", "grossWeight", "gross_weight",
                "commodityWeight", "weightLbs", "weight_lbs", "lbs", "loadWeight",
                "shipmentWeight", "estimatedWeight")
_PALLET_KEYS = ("pallets", "palletCount", "pallet_count", "palletQty", "numberOfPallets",
                "numPallets", "pieces", "pieceCount", "piece_count", "packages",
                "packageCount", "handlingUnits", "handlingUnitCount")

_LOGIN_HINTS = (
    "sign in",
    "log in",
    "login",
    "authenticate",
    "session expired",
    "unauthorized",
    "access denied",
    "please log",
    "sso",
)


def now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _first(d: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    # case-insensitive fallback
    lower = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        # location objects often have city/state; appointment windows have startTime
        if isinstance(v, dict):
            city = (
                v.get("city")
                or v.get("City")
                or v.get("cityName")
                or v.get("CityName")
                or v.get("name")
                or ""
            )
            state = (
                v.get("state")
                or v.get("State")
                or v.get("stateCode")
                or v.get("StateCode")
                or v.get("stateOrProvince")
                or v.get("province")
                or ""
            )
            zipc = v.get("zip") or v.get("postalCode") or v.get("zipCode") or ""
            parts = [str(x).strip() for x in (city, state) if x]
            s = ", ".join(parts)
            if zipc and s:
                # "Chicago, IL 60601" or "IL 60410" when city empty -> "IL, 60410"? 
                # Prefer "ST ZIP" when no city
                if city:
                    s = f"{s} {zipc}".strip()
                else:
                    s = f"{state} {zipc}".strip()
            elif zipc:
                s = str(zipc)
            if s:
                return s
            for k in (
                "startTime", "start", "dateTime", "datetime", "date",
                "value", "display", "label", "text",
            ):
                if v.get(k) not in (None, ""):
                    return str(v.get(k)).strip()
            return ""
        return ""
    return str(v).strip()


def _as_num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("$", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def normalize_load(raw: dict, source: str, default_url: str = "") -> dict:
    """Normalize a raw dict into the unified load schema."""
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {sorted(VALID_SOURCES)}, got {source!r}")

    flat = dict(raw)

    def _loc_city(obj: Any) -> str:
        if isinstance(obj, dict):
            return _as_str(
                obj.get("location")
                or obj.get("city")
                or obj.get("City")
                or obj.get("cityName")
                or obj.get("CityName")
                or obj
            )
        return _as_str(obj)

    def _loc_date(obj: Any) -> str:
        if not isinstance(obj, dict):
            return ""
        direct = (
            obj.get("date")
            or obj.get("Date")
            or obj.get("appointmentDate")
            or obj.get("dateTime")
            or obj.get("datetime")
            or obj.get("scheduledDate")
            or obj.get("pickupDate")
            or obj.get("startDate")
            or obj.get("earliestPickupDate")
            or obj.get("scheduledArrivalEarly")
            or obj.get("scheduledArrivalLate")
            or obj.get("scheduledArrivalEarlyDateTimeInUTC")
            or obj.get("stopDate")
        )
        if direct not in (None, ""):
            return _as_str(direct)
        appt = obj.get("appointmentTime") or obj.get("appointment") or obj.get("serviceWindow")
        if isinstance(appt, dict):
            return _as_str(
                appt.get("startTime")
                or appt.get("start")
                or appt.get("startDate")
                or appt.get("date")
            )
        if isinstance(appt, str):
            return appt.strip()
        return ""

    def _loc_time(obj: Any) -> str:
        if not isinstance(obj, dict):
            return ""
        direct = (
            obj.get("time")
            or obj.get("Time")
            or obj.get("scheduledTime")
            or obj.get("pickupTime")
            or obj.get("startTime")
        )
        if direct not in (None, "") and not isinstance(direct, dict):
            return _as_str(direct)
        appt = obj.get("appointmentTime") or obj.get("appointment") or obj.get("serviceWindow")
        if isinstance(appt, dict):
            st = appt.get("startTime") or appt.get("start") or ""
            en = appt.get("endTime") or appt.get("end") or ""
            # If startTime is a full datetime, caller will split date/time
            if st and en and str(st) != str(en):
                # Prefer time-of-day fragments when present
                def _tod(x: str) -> str:
                    m = re.search(r"(\d{1,2}:\d{2})", str(x))
                    return m.group(1) if m else str(x)
                ts, te = _tod(st), _tod(en)
                if ts and te and "T" not in str(st) and "/" not in str(st)[:5]:
                    return f"{ts} - {te}"
                return _as_str(st)
            return _as_str(st)
        if isinstance(appt, str):
            return appt.strip()
        return ""

    # Dig nested pickup/delivery / stops without polluting top-level with state/date
    pu_obj = raw.get("pickup") if isinstance(raw.get("pickup"), dict) else None
    de_obj = raw.get("delivery") if isinstance(raw.get("delivery"), dict) else None
    if isinstance(raw.get("stops"), list) and raw["stops"]:
        if isinstance(raw["stops"][0], dict) and pu_obj is None:
            pu_obj = raw["stops"][0]
        if len(raw["stops"]) > 1 and isinstance(raw["stops"][-1], dict) and de_obj is None:
            de_obj = raw["stops"][-1]

    # Lift nested weight/pallets/rate-like keys with clear names only
    for nest in (pu_obj, de_obj, raw.get("attributes"), raw.get("details"),
                 raw.get("load"), raw.get("shipment"), raw.get("data")):
        if not isinstance(nest, dict):
            continue
        for sk, sv in nest.items():
            kl = str(sk).lower()
            if sv in (None, ""):
                continue
            if "weight" in kl or kl in ("lbs", "kg", "mass"):
                flat.setdefault("weight", sv)
            if any(x in kl for x in ("pallet", "piece", "package", "handlingunit")):
                flat.setdefault("pallets", sv)
            if kl in ("rate", "allinrate", "totalrate", "amount", "price"):
                flat.setdefault("rate", sv)

    origin = _as_str(_first(flat, _ORIGIN_KEYS))
    destination = _as_str(_first(flat, _DEST_KEYS))

    if not origin and pu_obj is not None:
        origin = _loc_city(pu_obj)
    if not origin:
        for nest in ("origin", "from", "shipFrom"):
            sub = raw.get(nest)
            if isinstance(sub, dict):
                origin = _loc_city(sub)
                if origin:
                    break
    if not destination and de_obj is not None:
        destination = _loc_city(de_obj)
    if not destination:
        for nest in ("destination", "to", "shipTo"):
            sub = raw.get(nest)
            if isinstance(sub, dict):
                destination = _loc_city(sub)
                if destination:
                    break

    pickup_city = _as_str(_first(flat, ("pickup_city", "pickupCity", "puCity"))) or origin
    delivery_city = _as_str(_first(flat, ("delivery_city", "deliveryCity", "delCity"))) or destination

    pickup_date = _as_str(_first(flat, _PICKUP_DATE_KEYS))
    pickup_time = _as_str(_first(flat, _PICKUP_TIME_KEYS))
    delivery_date = _as_str(_first(flat, _DELIVERY_DATE_KEYS))
    delivery_time = _as_str(_first(flat, _DELIVERY_TIME_KEYS))

    if not pickup_date and pu_obj is not None:
        pickup_date = _loc_date(pu_obj)
    if not pickup_time and pu_obj is not None:
        pickup_time = _loc_time(pu_obj)
    if not delivery_date and de_obj is not None:
        delivery_date = _loc_date(de_obj)
    if not delivery_time and de_obj is not None:
        delivery_time = _loc_time(de_obj)

    # Nested origin/destination objects (RXO loadboard) when stops lacked dates
    if not pickup_date:
        origin_obj = raw.get("origin") if isinstance(raw.get("origin"), dict) else None
        if origin_obj is not None:
            pickup_date = _loc_date(origin_obj) or _as_str(
                origin_obj.get("scheduledArrivalEarly")
                or origin_obj.get("scheduledArrivalEarlyDateTimeInUTC")
                or ""
            )
            if not pickup_time:
                pickup_time = _loc_time(origin_obj)
    if not delivery_date:
        dest_obj = raw.get("destination") if isinstance(raw.get("destination"), dict) else None
        if dest_obj is not None:
            delivery_date = _loc_date(dest_obj) or _as_str(
                dest_obj.get("scheduledArrivalEarly")
                or dest_obj.get("scheduledArrivalEarlyDateTimeInUTC")
                or ""
            )
            if not delivery_time:
                delivery_time = _loc_time(dest_obj)

    # RXO / odd APIs: fuzzy key scan for pickup dates when standard keys missed
    if not pickup_date:
        for k, v in flat.items():
            kl = str(k).lower()
            if v in (None, "") or isinstance(v, (dict, list, bool)):
                continue
            if any(x in kl for x in ("pickupdate", "pu_date", "pudate", "availabledate",
                                      "availability", "pickupstart", "earliestpick",
                                      "scheduledpick", "origin_date", "origindate")):
                pickup_date = _as_str(v)
                break
            if kl.endswith("date") and "pick" in kl:
                pickup_date = _as_str(v)
                break

    def _split_dt(val: str) -> tuple[str, str]:
        if not val:
            return "", ""
        val = str(val).strip()
        m = re.match(
            r"^(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)",
            val,
        )
        if m:
            return m.group(1), m.group(2)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            return val, ""
        m = re.match(
            r"^(\d{1,2}/\d{1,2}/\d{2,4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?",
            val,
        )
        if m:
            return m.group(1), (m.group(2) or "")
        return val, ""

    # Always peel ISO/MM-DD datetimes into date + time parts
    if pickup_date:
        d, t = _split_dt(pickup_date)
        if d and d != pickup_date:
            pickup_date = d
        if t and not pickup_time:
            pickup_time = t
    if pickup_time and "T" in str(pickup_time):
        d, t = _split_dt(str(pickup_time))
        if t:
            pickup_time = t
        elif d and not pickup_date:
            pickup_date = d
            pickup_time = ""
    if delivery_date:
        d, t = _split_dt(delivery_date)
        if d and d != delivery_date:
            delivery_date = d
        if t and not delivery_time:
            delivery_time = t
    if delivery_time and "T" in str(delivery_time):
        d, t = _split_dt(str(delivery_time))
        if t:
            delivery_time = t
        elif d and not delivery_date:
            delivery_date = d
            delivery_time = ""

    # Combined string fields only when they are strings (not nested dicts)
    pickup_combined = ""
    delivery_combined = ""
    if isinstance(raw.get("pickup"), str):
        pickup_combined = raw.get("pickup") or ""
    if isinstance(raw.get("delivery"), str):
        delivery_combined = raw.get("delivery") or ""

    if not pickup_date and pickup_combined:
        d, t = _split_dt(pickup_combined)
        pickup_date = d or pickup_combined
        if t and not pickup_time:
            pickup_time = t
    if not delivery_date and delivery_combined:
        d, t = _split_dt(delivery_combined)
        delivery_date = d or delivery_combined
        if t and not delivery_time:
            delivery_time = t

    pickup = " ".join(x for x in (pickup_date, pickup_time) if x).strip() or pickup_combined
    delivery = " ".join(x for x in (delivery_date, delivery_time) if x).strip() or delivery_combined

    lid = _as_str(_first(flat, _ID_KEYS)) or ""
    if not lid:
        lid = f"{source[:3].upper()}-{abs(hash((origin, destination, pickup_date or pickup))) % 10_000_000}"

    rate = _as_num(_first(flat, _RATE_KEYS))
    miles = _as_num(_first(flat, _MILES_KEYS))
    if miles is not None:
        miles = int(round(miles)) if miles == int(miles) else miles

    # Prefer nested weight on pickup stop when present
    weight_raw = _first(flat, _WEIGHT_KEYS)
    if weight_raw in (None, "") and isinstance(pu_obj, dict):
        weight_raw = pu_obj.get("weight") or pu_obj.get("totalWeight")
    weight: Any = None
    if weight_raw is not None and weight_raw != "":
        if isinstance(weight_raw, (int, float)) and not isinstance(weight_raw, bool):
            weight = weight_raw
        else:
            s = str(weight_raw).strip()
            if re.search(r"(?i)\b(lbs?|kg|pounds?)\b", s):
                weight = s
            else:
                n = _as_num(s)
                weight = n if n is not None else s

    pallets_raw = _first(flat, _PALLET_KEYS)
    pallets: Any = None
    if pallets_raw is not None and pallets_raw != "":
        if isinstance(pallets_raw, (int, float)) and not isinstance(pallets_raw, bool):
            pallets = int(pallets_raw) if float(pallets_raw) == int(pallets_raw) else pallets_raw
        else:
            n = _as_num(pallets_raw)
            pallets = int(n) if n is not None and n == int(n) else (n if n is not None else str(pallets_raw).strip())

    # Preserve unknown weight/pallet-like keys from odd RXO shapes
    if weight is None or pallets is None:
        for k, v in list(flat.items()) + (
            list(pu_obj.items()) if isinstance(pu_obj, dict) else []
        ) + (
            list(de_obj.items()) if isinstance(de_obj, dict) else []
        ):
            kl = str(k).lower()
            if weight is None and ("weight" in kl or kl in ("lbs", "kg", "mass")) and v not in (None, ""):
                if not isinstance(v, (dict, list)):
                    weight = v
            if pallets is None and any(x in kl for x in ("pallet", "piece", "package", "handlingunit")) and v not in (None, ""):
                if not isinstance(v, (dict, list)):
                    pallets = v

    url = _as_str(_first(flat, _URL_KEYS)) or default_url or ""

    # Status: avoid bare "state" when it came from a location object
    status = _as_str(_first(flat, [k for k in _STATUS_KEYS if k != "state"]))
    if not status:
        st = flat.get("status") or flat.get("loadStatus") or flat.get("shipmentStatus")
        status = _as_str(st)

    return {
        "id": lid,
        "source": source,
        "pickup_city": pickup_city or origin,
        "delivery_city": delivery_city or destination,
        "origin": origin or pickup_city,
        "destination": destination or delivery_city,
        "pickup_date": pickup_date,
        "pickup_time": pickup_time,
        "delivery_date": delivery_date,
        "delivery_time": delivery_time,
        "pickup": pickup,
        "delivery": delivery,
        "weight": weight if weight is not None else "",
        "pallets": pallets if pallets is not None else "",
        "equipment": _as_str(_first(flat, _EQUIP_KEYS)),
        "miles": miles,
        "rate": rate,
        "status": status,
        "url": url,
        "notes": _as_str(_first(flat, _NOTES_KEYS)),
        "first_seen_at": "",
        "seen_age": "",
    }



def looks_like_load_object(obj: Any) -> bool:
    if not isinstance(obj, dict) or len(obj) < 2:
        return False
    keys_l = {str(k).lower() for k in obj.keys()}
    # simpler: any origin-like and dest-like or rate-like
    origin_hit = any(any(ok.lower() == kl or ok.lower() in kl for ok in _ORIGIN_KEYS) for kl in keys_l)
    dest_hit = any(any(dk.lower() == kl or dk.lower() in kl for dk in _DEST_KEYS) for kl in keys_l)
    rate_hit = any(any(rk.lower() == kl for rk in _RATE_KEYS) for kl in keys_l)
    id_hit = any(any(ik.lower() == kl for ik in _ID_KEYS) for kl in keys_l)
    return (origin_hit and dest_hit) or (id_hit and (origin_hit or dest_hit or rate_hit))


def find_load_arrays(data: Any, depth: int = 0, max_depth: int = 6) -> list[list]:
    """Recursively find arrays of objects that look like loads."""
    found: list[list] = []
    if depth > max_depth:
        return found
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data[: min(5, len(data))]):
            sample = data[: min(8, len(data))]
            hits = sum(1 for x in sample if looks_like_load_object(x))
            if hits >= max(1, len(sample) // 2):
                found.append(data)
        for item in data[:50]:
            found.extend(find_load_arrays(item, depth + 1, max_depth))
    elif isinstance(data, dict):
        for v in data.values():
            found.extend(find_load_arrays(v, depth + 1, max_depth))
    return found


def extract_loads_from_json(data: Any, source: str, default_url: str = "") -> list[dict]:
    loads: list[dict] = []
    arrays = find_load_arrays(data)
    # prefer largest array
    arrays.sort(key=len, reverse=True)
    seen_ids: set[str] = set()
    for arr in arrays[:3]:
        for item in arr:
            if not isinstance(item, dict):
                continue
            try:
                n = normalize_load(item, source, default_url=default_url)
            except Exception:
                continue
            if not n["origin"] and not n["destination"] and not n["rate"]:
                continue
            key = n["id"]
            if key in seen_ids:
                continue
            seen_ids.add(key)
            loads.append(n)
        if loads:
            break
    return loads


def is_login_wall(page_or_html: Any) -> bool:
    """Best-effort detection of login / auth walls.

    Prefer URL/title/password-field signals. Avoid counting generic
    "login"/"auth" strings inside SPA JS bundles (false positives).
    """
    try:
        url = ""
        title = ""
        if hasattr(page_or_html, "url"):
            url = (page_or_html.url or "").lower()
            try:
                title = (page_or_html.title() or "").lower()
            except Exception:
                title = ""
            try:
                html = page_or_html.content()
            except Exception:
                html = ""
        else:
            html = str(page_or_html)

        # MFA / OTP is not a login wall — caller should wait_out_mfa instead
        try:
            _u = ""
            _body = ""
            if hasattr(page_or_html, "url"):
                _u = (page_or_html.url or "").lower()
                try:
                    _body = (page_or_html.inner_text("body") or "").lower()
                except Exception:
                    _body = ""
            else:
                _body = str(page_or_html).lower()
            if (
                "multifactor" in _u
                or "one-time code" in _body
                or "enter your 6-digit" in _body
                or "verification code" in _body
            ):
                return False
        except Exception:
            pass

        # Strong URL host/path signals (not bare "auth" substring in query/scripts)
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            path = (parsed.path or "").lower()
        except Exception:
            host, path = "", ""

        login_hosts = (
            "login.",
            "signin.",
            "sso.",
            "auth0.com",
            "okta.com",
        )
        if any(h in host for h in login_hosts) or host.startswith("login"):
            return True
        path_bits = [x for x in path.split("/") if x]
        if path_bits and path_bits[-1] in {"login", "signin", "sign-in", "sso"}:
            return True
        if any(b in {"login", "signin", "sign-in"} for b in path_bits[:2]):
            return True

        # Phrase match only — bare "login" false-positives on MultiFactorAuthLogin titles
        if any(h in title for h in ("sign in", "log in |", "sign-in", "log in -", "sign in -")):
            return True
        if title.strip() in {"login", "log in", "sign in", "sign-in"}:
            return True

        # Visible password field is strong
        sample = (html or "")[:120_000].lower()
        if 'type="password"' in sample or "type='password'" in sample:
            return True

        # Visible body text only (strip scripts/styles) — require clear CTA language
        import re as _re
        body = _re.sub(r"<script[\s\S]*?</script>", " ", sample)
        body = _re.sub(r"<style[\s\S]*?</style>", " ", body)
        body = _re.sub(r"<[^>]+>", " ", body)
        body = _re.sub(r"\s+", " ", body)
        visible_hits = sum(1 for h in ("sign in", "log in", "forgot password", "keep me signed") if h in body)
        return visible_hits >= 2
    except Exception:
        return False



def wait_out_mfa(page, timeout_ms: int = 180_000) -> bool:
    """If page looks like MFA / OTP, wait for user to complete it.

    Returns True if we appear past MFA (or never were on it).
    """
    import time
    import logging
    log = logging.getLogger("scanner")
    deadline = time.time() + (timeout_ms / 1000.0)

    def _is_mfa() -> bool:
        try:
            u = (page.url or "").lower()
            if "multifactor" in u or "mfa" in u or "otp" in u or "onetime" in u.replace("-", ""):
                return True
            body = (page.inner_text("body") or "").lower()
            return any(
                s in body
                for s in (
                    "one-time code",
                    "one time code",
                    "enter your 6-digit",
                    "verification code",
                    "authenticator",
                )
            )
        except Exception:
            return False

    if not _is_mfa():
        return True

    log.warning("MFA / one-time code detected — enter the code in the Edge window. Waiting up to %ss…", int(timeout_ms/1000))
    while time.time() < deadline:
        try:
            page.wait_for_timeout(2000)
        except Exception:
            time.sleep(2)
        if not _is_mfa():
            log.info("MFA appears complete — continuing.")
            try:
                page.wait_for_timeout(3000)
            except Exception:
                pass
            return True
    log.warning("Timed out waiting for MFA.")
    return False


def dump_html_snippet(html: str, path: Path, max_chars: int = 200_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    snippet = html[:max_chars]
    if len(html) > max_chars:
        snippet += f"\n\n<!-- truncated: original {len(html)} chars -->\n"
    path.write_text(snippet, encoding="utf-8", errors="replace")


def append_api_urls(urls: Iterable[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.exists():
        existing = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
    seen = set(existing)
    for u in urls:
        u = (u or "").strip()
        if u and u not in seen:
            existing.append(u)
            seen.add(u)
    path.write_text("\n".join(existing[-200:]) + ("\n" if existing else ""), encoding="utf-8")


def scrape_dom_loads(page, source: str, default_url: str = "") -> list[dict]:
    """Best-effort CSS heuristics for tables, rows, and cards."""
    loads: list[dict] = []
    try:
        rows = page.evaluate(
            """() => {
              const out = [];
              const push = (obj) => { if (obj && (obj.origin || obj.destination || obj.rate || obj.id)) out.push(obj); };

              // Tables
              document.querySelectorAll('table').forEach((table) => {
                const headers = [...table.querySelectorAll('thead th, tr:first-child th, tr:first-child td')]
                  .map(th => (th.innerText || '').trim().toLowerCase());
                const bodyRows = table.querySelectorAll('tbody tr');
                const trs = bodyRows.length ? bodyRows : table.querySelectorAll('tr');
                trs.forEach((tr, idx) => {
                  if (idx === 0 && !bodyRows.length && tr.querySelector('th')) return;
                  const cells = [...tr.querySelectorAll('td')].map(td => (td.innerText || '').trim());
                  if (cells.length < 2) return;
                  const obj = { id: '', origin: '', destination: '', equipment: '', pickup: '', delivery: '', miles: '', rate: '', status: '', notes: '', url: '', weight: '', pallets: '', pickup_date: '', pickup_time: '', delivery_date: '', delivery_time: '' };
                  const a = tr.querySelector('a[href]');
                  if (a) obj.url = a.href || '';
                  cells.forEach((val, i) => {
                    const h = headers[i] || '';
                    if (/origin|from|pickup.?city|pu.?city/.test(h)) obj.origin = val;
                    else if (/dest|to\\b|deliv.?city/.test(h)) obj.destination = val;
                    else if (/equip|trailer|van|reefer|flat/.test(h)) obj.equipment = val;
                    else if (/pick.?up|pu.?date|avail/.test(h)) obj.pickup = val;
                    else if (/deliv|due|drop/.test(h)) obj.delivery = val;
                    else if (/mile|dist/.test(h)) obj.miles = val;
                    else if (/rate|pay|price|\\$/.test(h)) obj.rate = val;
                    else if (/status/.test(h)) obj.status = val;
                    else if (/id|ref|load|#|shipment|order/.test(h)) obj.id = val;
                    else if (/note|comment/.test(h)) obj.notes = val;
                    else if (/weight|lbs|kg/.test(h)) obj.weight = val;
                    else if (/pallet|piece|pkg|package/.test(h)) obj.pallets = val;
                  });
                  // positional fallback when headers unknown
                  if (!obj.origin && !obj.destination && cells.length >= 3) {
                    obj.origin = cells[1] || cells[0];
                    obj.destination = cells[2] || cells[1];
                    if (!obj.id) obj.id = cells[0];
                  }
                  push(obj);
                });
              });

              // Cards / list items with data attributes or common class names
              const cardSel = '[class*="load"], [class*="shipment"], [class*="Load"], [class*="Shipment"], [data-testid*="load"], article, .MuiCard-root, .card';
              document.querySelectorAll(cardSel).forEach((el) => {
                const text = (el.innerText || '').trim();
                if (!text || text.length < 10 || text.length > 2000) return;
                const lines = text.split(/\\n+/).map(s => s.trim()).filter(Boolean);
                if (lines.length < 2) return;
                const a = el.querySelector('a[href]');
                const obj = {
                  id: el.getAttribute('data-id') || el.getAttribute('data-load-id') || lines[0].slice(0, 40),
                  origin: '',
                  destination: '',
                  equipment: '',
                  pickup: '',
                  delivery: '',
                  miles: '',
                  rate: '',
                  status: '',
                  notes: lines.slice(0, 4).join(' | ').slice(0, 200),
                  url: a ? (a.href || '') : ''
                };
                const lane = text.match(/([A-Za-z .'-]+,?\\s*[A-Z]{2})\\s*(?:→|->|to)\\s*([A-Za-z .'-]+,?\\s*[A-Z]{2})/i);
                if (lane) { obj.origin = lane[1].trim(); obj.destination = lane[2].trim(); }
                // Prefer City, ST pairs (ArcBest cards often lack arrow lanes)
                if (!obj.origin || !obj.destination) {
                  const cityRe = /\\b([A-Za-z][A-Za-z .'-]*?,\\s*[A-Z]{2})\\b/g;
                  const cities = [];
                  let cm;
                  while ((cm = cityRe.exec(text)) !== null) {
                    const c = cm[1].trim();
                    if (!cities.includes(c)) cities.push(c);
                  }
                  if (cities.length >= 2) {
                    if (!obj.origin) obj.origin = cities[0];
                    if (!obj.destination) obj.destination = cities[1];
                  } else if (cities.length === 1 && !obj.origin) {
                    obj.origin = cities[0];
                  }
                }
                const rateM = text.match(/\\$\\s*[\\d,]+(?:\\.\\d{2})?/);
                if (rateM) obj.rate = rateM[0];
                const milesM = text.match(/([\\d,]+)\\s*(?:mi|miles)\\b/i);
                if (milesM) obj.miles = milesM[1];
                const weightM = text.match(/([\\d,]+)\\s*(?:lbs?|pounds?|kg)\\b/i);
                if (weightM) obj.weight = weightM[0];
                const palletM = text.match(/(\\d+)\\s*(?:pallets?|plts?|pcs?|pieces?)\\b/i);
                if (palletM) obj.pallets = palletM[1];
                // ArcBest: keep pipe-joined notes for post-cleanse
                if (!obj.origin && !obj.destination && lines.length >= 2) {
                  obj.notes = lines.join(' | ').slice(0, 300);
                }
                push(obj);
              });

              return out.slice(0, 500);
            }"""
        )
    except Exception as exc:
        log.warning("[%s] DOM scrape failed: %s", source, exc)
        return []

    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        try:
            n = normalize_load(raw, source, default_url=default_url)
        except Exception:
            continue
        if n["origin"] or n["destination"] or n["rate"]:
            loads.append(n)
    return loads


def merge_loads(*groups: list[dict]) -> list[dict]:
    """Merge load lists; drop EXAMPLE-* when any real load exists; cleanse; dedupe."""
    merged: list[dict] = []
    for g in groups:
        merged.extend(g or [])

    has_real = any(
        not str(l.get("id", "")).upper().startswith("EXAMPLE-")
        for l in merged
    )
    if has_real:
        merged = [l for l in merged if not str(l.get("id", "")).upper().startswith("EXAMPLE-")]

    # Arrive / ArcBest field repair + cross-source dedupe
    merged = cleanse_loads(merged)

    seen: set[tuple] = set()
    out: list[dict] = []
    for l in merged:
        key = (l.get("source"), str(l.get("id", "")))
        if key in seen:
            continue
        seen.add(key)
        row = ensure_schema(l)
        out.append(row)
    return out


def ensure_schema(load: dict) -> dict:
    """Fill all SCHEMA_KEYS; keep origin/destination aliases synced with cities."""
    row: dict[str, Any] = {}
    for k in SCHEMA_KEYS:
        if k in ("miles", "rate"):
            row[k] = load.get(k, None)
        elif k in ("weight", "pallets"):
            v = load.get(k, "")
            row[k] = "" if v is None else v
        else:
            row[k] = load.get(k, "") if load.get(k) is not None else ""

    # Sync city aliases
    pu_city = row.get("pickup_city") or row.get("origin") or ""
    de_city = row.get("delivery_city") or row.get("destination") or ""
    row["pickup_city"] = pu_city
    row["delivery_city"] = de_city
    row["origin"] = pu_city or row.get("origin") or ""
    row["destination"] = de_city or row.get("destination") or ""

    # Sync combined pickup/delivery from split fields when useful
    if not row.get("pickup"):
        row["pickup"] = " ".join(
            x for x in (row.get("pickup_date") or "", row.get("pickup_time") or "") if x
        ).strip()
    if not row.get("delivery"):
        row["delivery"] = " ".join(
            x for x in (row.get("delivery_date") or "", row.get("delivery_time") or "") if x
        ).strip()

    row["source"] = load.get("source") or row.get("source")
    return row


def _is_real_load_id(lid: str) -> bool:
    """True when id looks like a broker load number (not a stop blob / money / empty)."""
    if not lid or not str(lid).strip():
        return False
    s = str(lid).strip()
    if "\n" in s:
        return False
    if re.match(r"^\$?\s*[\d,]+(?:\.\d{2})?\s*$", s):
        return False
    if s.upper() in {"TL", "FULL", "LTL", "PARTIAL", "VAN", "REEFER", "FLATBED"}:
        return False
    # Arrive stop-like (weekday + city)
    if re.search(r"\b(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", s) and re.search(
        r"[A-Za-z].*,\s*[A-Z]{2}", s
    ):
        return False
    return True


def seen_key_for_load(load: dict) -> str:
    """Stable index key: (source, id) when real load #, else lane+date+rate."""
    source = str(load.get("source") or "")
    lid = str(load.get("id") or "").strip()
    if _is_real_load_id(lid):
        return f"{source}|id|{lid}"
    origin = str(load.get("pickup_city") or load.get("origin") or "")
    dest = str(load.get("delivery_city") or load.get("destination") or "")
    pu_date = str(load.get("pickup_date") or load.get("pickup") or "")
    rate = load.get("rate")
    rate_s = "" if rate is None else str(rate)
    return f"{source}|lane|{origin}|{dest}|{pu_date}|{rate_s}"


def format_seen_age(first_seen_at: str, now: Optional[datetime] = None) -> str:
    """Human-readable age since first_seen_at, e.g. '12m', '2h 5m', '3d 1h'."""
    now = now or datetime.now(timezone.utc)
    try:
        ts = first_seen_at.replace("Z", "+00:00") if first_seen_at.endswith("Z") else first_seen_at
        then = datetime.fromisoformat(ts)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
    except Exception:
        return ""
    secs = int((now - then).total_seconds())
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs}s"
    minutes = secs // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    rem_m = minutes % 60
    if hours < 48:
        return f"{hours}h {rem_m}m" if rem_m else f"{hours}h"
    days = hours // 24
    rem_h = hours % 24
    return f"{days}d {rem_h}h" if rem_h else f"{days}d"


def resolve_seen_index_path(output_path: Optional[Path] = None, base_dir: Optional[Path] = None) -> Path:
    """Prefer sibling of loads.json; else scanner/seen_index.json."""
    if output_path is not None:
        return Path(output_path).resolve().parent / "seen_index.json"
    if base_dir is not None:
        # ../seen_index.json from scanner when output is ../loads.json
        return (Path(base_dir) / ".." / "seen_index.json").resolve()
    return Path(__file__).resolve().parent / "seen_index.json"


def apply_first_seen(
    loads: list[dict],
    index_path: Path,
    now: Optional[datetime] = None,
) -> list[dict]:
    """Stamp first_seen_at / seen_age using persisted seen_index; prune >7 days."""
    now = now or datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    index_path = Path(index_path)
    index: dict[str, str] = {}
    if index_path.exists():
        try:
            raw = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                # support {"key": "iso"} or {"key": {"first_seen_at": "iso"}}
                for k, v in raw.items():
                    if isinstance(v, str):
                        index[str(k)] = v
                    elif isinstance(v, dict) and v.get("first_seen_at"):
                        index[str(k)] = str(v["first_seen_at"])
        except Exception as exc:
            log.warning("Could not read seen_index %s: %s", index_path, exc)

    out: list[dict] = []
    touched: set[str] = set()
    for load in loads or []:
        row = dict(load)
        key = seen_key_for_load(row)
        touched.add(key)
        first = index.get(key) or row.get("first_seen_at") or now_iso
        if not index.get(key):
            index[key] = first
        row["first_seen_at"] = first
        row["seen_age"] = format_seen_age(first, now)
        out.append(row)

    # Prune entries older than 7 days
    cutoff = now.timestamp() - 7 * 24 * 3600
    pruned: dict[str, str] = {}
    for k, iso in index.items():
        try:
            ts = iso.replace("Z", "+00:00") if iso.endswith("Z") else iso
            then = datetime.fromisoformat(ts)
            if then.tzinfo is None:
                then = then.replace(tzinfo=timezone.utc)
            if then.timestamp() >= cutoff or k in touched:
                pruned[k] = iso
        except Exception:
            if k in touched:
                pruned[k] = iso

    try:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path.with_suffix(index_path.suffix + ".tmp")
        tmp.write_text(json.dumps(pruned, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(index_path)
    except Exception as exc:
        log.warning("Could not write seen_index %s: %s", index_path, exc)

    return out


def write_loads_json(
    path: Path,
    loads: list[dict],
    updated_at: Optional[str] = None,
    seen_index_path: Optional[Path] = None,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Primary: scanner/seen_index.json; also mirror next to loads.json
    scanner_idx = Path(__file__).resolve().parent / "seen_index.json"
    idx = Path(seen_index_path) if seen_index_path else scanner_idx
    stamped = apply_first_seen(loads, idx)
    sibling = path.parent / "seen_index.json"
    if sibling.resolve() != Path(idx).resolve() and Path(idx).exists():
        try:
            sibling.write_text(Path(idx).read_text(encoding="utf-8"), encoding="utf-8")
        except Exception as exc:
            log.warning("Could not mirror seen_index to %s: %s", sibling, exc)
    stamped = [ensure_schema(l) for l in stamped]
    payload = {
        "updatedAt": updated_at or now_iso_z(),
        "loads": stamped,
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def resolve_output_path(config: dict, base_dir: Path) -> Path:
    out = config.get("output") or "../loads.json"
    p = Path(out)
    if not p.is_absolute():
        p = (base_dir / p).resolve()
    return p
