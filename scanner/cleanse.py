"""Post-extract field cleansing for Arrive / ArcBest DOM scrapes."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Optional

_ZIP_ST_RE = re.compile(r"^([A-Za-z]{2})\s+(\d{5})(?:-\d{4})?$")
_ZIP_COORDS = None


def _load_zip_coords() -> dict:
    global _ZIP_COORDS
    if _ZIP_COORDS is not None:
        return _ZIP_COORDS
    _ZIP_COORDS = {}
    # Prefer board root zip_coords.json (next to loads.json)
    try:
        candidates = [
            Path(__file__).resolve().parents[1] / "zip_coords.json",
            Path(__file__).resolve().parent / "zip_coords.json",
        ]
    except Exception:
        candidates = []
    for zp in candidates:
        try:
            if zp.exists():
                import json
                _ZIP_COORDS = json.loads(zp.read_text(encoding="utf-8"))
                break
        except Exception:
            continue
    return _ZIP_COORDS


def expand_zip_city(raw: str) -> str:
    """Turn 'IL 60410' into 'Channahon, IL 60410' when zip_coords.json is present."""
    s = (raw or "").strip()
    if not s:
        return s
    m = _ZIP_ST_RE.match(s)
    if not m:
        # bare ZIP
        m2 = re.match(r"^(\d{5})(?:-\d{4})?$", s)
        if not m2:
            return s
        z = m2.group(1)
        rec = _load_zip_coords().get(z) or {}
        label = (rec.get("label") or "").strip()
        if label:
            return f"{label} {z}"
        city = (rec.get("city") or "").strip()
        st = (rec.get("state") or "").strip().upper()
        if city and st:
            return f"{city}, {st} {z}"
        return s
    st, z = m.group(1).upper(), m.group(2)
    rec = _load_zip_coords().get(z) or {}
    label = (rec.get("label") or "").strip()
    if label:
        # Keep ZIP so UI radius can resolve via zip_coords even if city index misses
        if not re.search(r"\b" + z + r"\b", label):
            return f"{label} {z}"
        return label
    city = (rec.get("city") or "").strip()
    if city:
        return f"{city}, {st} {z}"
    return s


_CITY_ST_RE = re.compile(
    r"\b([A-Za-z][A-Za-z .'-]*?,\s*[A-Z]{2})\b"
)
_TIME_RE = re.compile(
    r"\b(\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:[A-Z]{2,4})?)\b",
    re.IGNORECASE,
)
_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTH = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_MONEY_RE = re.compile(r"^\$?\s*[\d,]+(?:\.\d{2})?\s*$")
_BOOK_IT_RE = re.compile(r"book\s*it\s*rate", re.IGNORECASE)
_WEIGHT_RE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(lbs?|pounds?|kg|kgs|kilograms?)\b",
    re.IGNORECASE,
)
_PALLETS_RE = re.compile(
    r"(\d+)\s*(pallets?|plts?|pcs?|pieces?|pkgs?|packages?|hu|handling\s*units?)\b",
    re.IGNORECASE,
)


def _sanitize_id_part(s: str, max_len: int = 40) -> str:
    s = re.sub(r"[,\s]+", "-", (s or "").strip())
    s = re.sub(r"[^A-Za-z0-9.\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s[:max_len] or "X"


ARCBEST_BOARD_URL = "https://carriers.arcb.com/Shipments"
ARRIVE_BOARD_URL = "https://carrier.arrivelogistics.com/find-loads"


def parse_arrive_stop(blob: str) -> dict:
    """Parse an Arrive multi-line stop blob into city / date / time."""
    out = {"city": "", "date": "", "time": ""}
    if not blob or not isinstance(blob, str):
        return out

    text = blob.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # Also allow single-line with spaces / pipes
    if len(lines) == 1 and ("|" in lines[0] or "  " in lines[0]):
        lines = [p.strip() for p in re.split(r"\s*\|\s*|\s{2,}", lines[0]) if p.strip()]

    # City: first City, ST match (skip distance-like "(0mi)")
    for ln in lines:
        if re.search(r"\(\s*\d+\s*mi", ln, re.IGNORECASE):
            continue
        m = _CITY_ST_RE.search(ln)
        if m:
            out["city"] = m.group(1).strip()
            break
    if not out["city"]:
        m = _CITY_ST_RE.search(text.replace("\n", " "))
        if m:
            out["city"] = m.group(1).strip()

    # Date: "Fri" + "Sep 11" on consecutive lines, or "Fri Sep 11" / "Sep 11"
    dow = ""
    mon_day = ""
    for i, ln in enumerate(lines):
        if ln[:3] in _DOW and (len(ln) == 3 or ln[3:4] in ("", " ", ",")):
            dow = ln[:3]
            # peek next line for "Sep 11"
            if i + 1 < len(lines):
                nxt = lines[i + 1]
                mm = re.match(
                    r"^(" + "|".join(_MONTH) + r")\s+(\d{1,2})(?:st|nd|rd|th)?$",
                    nxt,
                    re.IGNORECASE,
                )
                if mm:
                    mon_day = f"{mm.group(1)[:1].upper() + mm.group(1)[1:3].lower()} {int(mm.group(2))}"
            # same line: "Fri Sep 11"
            same = re.match(
                r"^(?:" + "|".join(_DOW) + r")\s+(" + "|".join(_MONTH) + r")\s+(\d{1,2})",
                ln,
                re.IGNORECASE,
            )
            if same and not mon_day:
                mon_day = f"{same.group(1)[:1].upper() + same.group(1)[1:3].lower()} {int(same.group(2))}"
                dow = ln[:3]
        if not mon_day:
            mm = re.match(
                r"^(" + "|".join(_MONTH) + r")\s+(\d{1,2})(?:st|nd|rd|th)?$",
                ln,
                re.IGNORECASE,
            )
            if mm:
                mon_day = f"{mm.group(1)[:1].upper() + mm.group(1)[1:3].lower()} {int(mm.group(2))}"

    if dow and mon_day:
        out["date"] = f"{dow} {mon_day}"
    elif mon_day:
        out["date"] = mon_day
    else:
        # collapsed single string fallback
        m = re.search(
            r"\b((?:" + "|".join(_DOW) + r")\s+(?:" + "|".join(_MONTH) + r")\s+\d{1,2})\b",
            text.replace("\n", " "),
            re.IGNORECASE,
        )
        if m:
            parts = m.group(1).split()
            out["date"] = f"{parts[0][:3]} {parts[1][:1].upper() + parts[1][1:3].lower()} {int(parts[2])}"

    # Time: "11:00 CDT" etc. Prefer line that looks like time (not city)
    for ln in lines:
        if _CITY_ST_RE.search(ln):
            continue
        if re.search(r"\(\s*\d+\s*mi", ln, re.IGNORECASE):
            continue
        tm = _TIME_RE.search(ln)
        if tm:
            out["time"] = re.sub(r"\s+", " ", tm.group(1)).strip()
            break
    if not out["time"]:
        tm = _TIME_RE.search(text.replace("\n", " "))
        if tm:
            out["time"] = re.sub(r"\s+", " ", tm.group(1)).strip()

    return out


def extract_weight_pallets(*texts: Any) -> tuple[Any, Any]:
    """Pull weight / pallet-like counts from free text via regex."""
    blob = " ".join(str(t) for t in texts if t not in (None, ""))
    if not blob:
        return "", ""
    weight: Any = ""
    pallets: Any = ""
    wm = _WEIGHT_RE.search(blob)
    if wm:
        num = wm.group(1).replace(",", "")
        unit = wm.group(2).lower()
        if unit.startswith("kg"):
            weight = f"{num} kg"
        else:
            weight = f"{num} lbs"
    pm = _PALLETS_RE.search(blob)
    if pm:
        try:
            pallets = int(pm.group(1))
        except ValueError:
            pallets = pm.group(1)
    return weight, pallets



def _sanitize_dashes(s: Any) -> Any:
    """Replace en/em dashes with ASCII hyphen so UI never shows mojibake."""
    if not isinstance(s, str) or not s:
        return s
    return (
        s.replace("–", "-")
        .replace("—", "-")
        .replace("‒", "-")
        .replace("―", "-")
        .replace("…", "...")
    )


def _arrive_pickup_blob(load: dict) -> str:
    for key in ("pickup", "id"):
        v = load.get(key)
        if isinstance(v, str) and _looks_like_arrive_stop(v):
            return v
    # origin sometimes holds the pickup stop
    v = load.get("origin")
    if isinstance(v, str) and _looks_like_arrive_stop(v):
        # only use if destination also looks like a stop (both are stop blobs)
        d = load.get("destination")
        if isinstance(d, str) and _looks_like_arrive_stop(d):
            return v
    return str(load.get("pickup") or load.get("id") or "")


def _arrive_delivery_blob(load: dict) -> str:
    for key in ("delivery", "destination"):
        v = load.get(key)
        if isinstance(v, str) and (_looks_like_arrive_stop(v) or _CITY_ST_RE.search(v or "")):
            return v
    # if origin looks like stop and pickup blob already consumed origin city from id/pickup
    v = load.get("origin")
    if isinstance(v, str) and _looks_like_arrive_stop(v):
        pu = _arrive_pickup_blob(load)
        if pu and pu != v:
            return v
    return str(load.get("delivery") or load.get("destination") or "")


def _looks_like_arrive_stop(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if "\n" in s and _CITY_ST_RE.search(s):
        return True
    # multi-token with weekday + city
    has_dow = any(re.search(rf"\b{d}\b", s) for d in _DOW)
    has_city = bool(_CITY_ST_RE.search(s))
    has_time = bool(_TIME_RE.search(s))
    return has_city and (has_dow or has_time or any(m in s for m in _MONTH))


def _set_city_aliases(out: dict, pickup_city: str, delivery_city: str) -> None:
    out["pickup_city"] = pickup_city or ""
    out["delivery_city"] = delivery_city or ""
    out["origin"] = pickup_city or ""
    out["destination"] = delivery_city or ""


def cleanse_arrive(load: dict) -> Optional[dict]:
    """Normalize Arrive DOM/API rows; return None to drop."""
    if not isinstance(load, dict):
        return None
    out = dict(load)
    out["source"] = "Arrive"

    pu_blob = _arrive_pickup_blob(out)
    del_blob = _arrive_delivery_blob(out)

    pu = parse_arrive_stop(pu_blob) if pu_blob else {"city": "", "date": "", "time": ""}
    de = parse_arrive_stop(del_blob) if del_blob else {"city": "", "date": "", "time": ""}

    # If pickup blob empty but origin is a plain city, keep it
    origin = pu.get("city") or ""
    destination = de.get("city") or ""

    # Fallback: if origin field is already a clean City, ST and pickup blob failed
    if not origin:
        o = str(out.get("origin") or out.get("pickup_city") or "").strip()
        if o and "\n" not in o and _CITY_ST_RE.search(o):
            origin = _CITY_ST_RE.search(o).group(1).strip()
    if not destination:
        d = str(out.get("destination") or out.get("delivery_city") or "").strip()
        if d and "\n" not in d and _CITY_ST_RE.search(d):
            destination = _CITY_ST_RE.search(d).group(1).strip()

    # Avoid origin==destination when both blobs were the same delivery text
    if origin and destination and origin == destination and pu_blob and del_blob and pu_blob == del_blob:
        # try id as pickup
        alt = parse_arrive_stop(str(out.get("id") or ""))
        if alt.get("city") and alt["city"] != destination:
            origin = alt["city"]
            pu = alt

    pickup_date = pu.get("date") or str(out.get("pickup_date") or "")
    pickup_time = pu.get("time") or str(out.get("pickup_time") or "")
    delivery_date = de.get("date") or str(out.get("delivery_date") or "")
    delivery_time = de.get("time") or str(out.get("delivery_time") or "")

    _set_city_aliases(out, origin, destination)
    out["pickup_date"] = pickup_date
    out["pickup_time"] = pickup_time
    out["delivery_date"] = delivery_date
    out["delivery_time"] = delivery_time

    pu_dt = f"{pickup_date} {pickup_time}".strip()
    de_dt = f"{delivery_date} {delivery_time}".strip()
    if pu_dt:
        out["pickup"] = pu_dt
    elif out.get("pickup") and _looks_like_arrive_stop(str(out.get("pickup"))):
        out["pickup"] = ""
    if de_dt:
        out["delivery"] = de_dt
    elif out.get("delivery") and _looks_like_arrive_stop(str(out.get("delivery"))):
        out["delivery"] = ""

    # Weight / pallets from notes and any leftover text fields
    w, p = extract_weight_pallets(
        out.get("notes"),
        out.get("equipment"),
        out.get("status"),
        pu_blob,
        del_blob,
        out.get("id"),
    )
    if w and not out.get("weight"):
        out["weight"] = w
    if p != "" and not out.get("pallets"):
        out["pallets"] = p
    if out.get("weight") is None:
        out["weight"] = ""
    if out.get("pallets") is None:
        out["pallets"] = ""

    rate = out.get("rate")
    if not origin and not destination and not rate:
        return None

    # Stable id: keep real LoadBoardId (numeric); else ARR-origin-dest-pickup / hash
    old_id = str(out.get("id") or "").strip()
    if old_id.isdigit():
        out["id"] = old_id  # Arrive LoadBoardId from GraphQL / data-testid=load-row-N
    elif _looks_like_arrive_stop(old_id) or not old_id or old_id.startswith("ARR-"):
        base = (
            f"ARR-{_sanitize_id_part(origin)}-"
            f"{_sanitize_id_part(destination)}-"
            f"{_sanitize_id_part(pu_dt or str(rate or ''), 24)}"
        )
        if base.endswith("-X") or base.count("X") >= 2:
            h = hashlib.sha1(
                f"{origin}|{destination}|{pu_dt}|{de_dt}|{rate}".encode()
            ).hexdigest()[:10]
            out["id"] = f"ARR-{h}"
        else:
            out["id"] = base
    # else keep existing non-blob id (e.g. real API id)

    return out


def _is_money_string(s: str) -> bool:
    s = (s or "").strip()
    if not s:
        return False
    return bool(_MONEY_RE.match(s))


def _parse_arcbest_notes(notes: str) -> dict:
    """Parse 'A | B | City, ST | City, ST' style notes."""
    result = {
        "equipment": "",
        "status": "",
        "origin": "",
        "destination": "",
        "rate_hint": None,
        "has_cities": False,
        "is_rate_only": False,
        "weight": "",
        "pallets": "",
    }
    notes = (notes or "").strip()
    if not notes:
        return result

    parts = [p.strip() for p in notes.split("|")]
    parts = [p for p in parts if p]

    cities = []
    for p in parts:
        m = _CITY_ST_RE.fullmatch(p) or _CITY_ST_RE.search(p)
        if m and _CITY_ST_RE.fullmatch(p.strip()):
            cities.append(m.group(1).strip())
        elif _CITY_ST_RE.fullmatch(p.replace("  ", " ").strip()):
            cities.append(p.strip())

    # Also find City, ST anywhere in notes
    if len(cities) < 2:
        found = _CITY_ST_RE.findall(notes)
        for c in found:
            if c not in cities:
                cities.append(c)

    if len(cities) >= 2:
        result["origin"] = cities[0]
        result["destination"] = cities[1]
        result["has_cities"] = True
    elif len(cities) == 1:
        result["origin"] = cities[0]
        result["has_cities"] = True

    # equipment / status from leading non-city, non-money parts
    non_city = []
    for p in parts:
        if _CITY_ST_RE.fullmatch(p.strip()):
            continue
        if _is_money_string(p) or _BOOK_IT_RE.search(p):
            if _is_money_string(p):
                try:
                    result["rate_hint"] = float(p.replace("$", "").replace(",", "").strip())
                except ValueError:
                    pass
            continue
        # skip pure weight/pallet fragments from equipment slot
        if _WEIGHT_RE.fullmatch(p.strip()) or _PALLETS_RE.fullmatch(p.strip()):
            continue
        non_city.append(p)

    if non_city:
        result["equipment"] = non_city[0]
        if len(non_city) > 1:
            result["status"] = non_city[1]

    w, pcount = extract_weight_pallets(notes)
    result["weight"] = w
    result["pallets"] = pcount

    # rate-only / Book It Rate without cities
    if not result["has_cities"]:
        joined = " ".join(parts).lower()
        only_money_or_book = all(
            _is_money_string(p) or bool(_BOOK_IT_RE.search(p)) for p in parts
        ) if parts else False
        if only_money_or_book or (
            _BOOK_IT_RE.search(notes) and not _CITY_ST_RE.search(notes)
        ):
            result["is_rate_only"] = True

    return result


def cleanse_arcbest(load: dict) -> Optional[dict]:
    """Normalize ArcBest DOM/API rows; return None to drop junk."""
    if not isinstance(load, dict):
        return None
    out = dict(load)
    src0 = str(out.get("source") or "ArcBest").strip()
    out["source"] = "MoLo" if src0 == "MoLo" else "ArcBest"

    notes = str(out.get("notes") or "")
    parsed = _parse_arcbest_notes(notes)

    if parsed["is_rate_only"] and not (
        str(out.get("origin") or out.get("pickup_city") or "").strip()
        and str(out.get("destination") or out.get("delivery_city") or "").strip()
    ):
        return None

    if parsed["has_cities"]:
        if parsed["origin"]:
            out["origin"] = parsed["origin"]
            out["pickup_city"] = parsed["origin"]
        if parsed["destination"]:
            out["destination"] = parsed["destination"]
            out["delivery_city"] = parsed["destination"]
        if parsed["equipment"] and not out.get("equipment"):
            out["equipment"] = parsed["equipment"]
        if parsed["status"] and not out.get("status"):
            out["status"] = parsed["status"]

    origin = str(out.get("pickup_city") or out.get("origin") or "").strip()
    destination = str(out.get("delivery_city") or out.get("destination") or "").strip()
    _set_city_aliases(out, origin, destination)

    # Preserve/split any existing pickup/delivery into date/time when possible
    for side, date_k, time_k, comb_k in (
        ("pickup", "pickup_date", "pickup_time", "pickup"),
        ("delivery", "delivery_date", "delivery_time", "delivery"),
    ):
        if not out.get(date_k) and out.get(comb_k):
            comb = str(out.get(comb_k) or "").strip()
            # ISO split
            m = re.match(
                r"^(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2})",
                comb,
            )
            if m:
                out[date_k] = m.group(1)
                out[time_k] = out.get(time_k) or m.group(2)
            elif re.match(r"^\d{4}-\d{2}-\d{2}$", comb):
                out[date_k] = comb
            else:
                out[date_k] = out.get(date_k) or comb

    out.setdefault("pickup_date", out.get("pickup_date") or "")
    out.setdefault("pickup_time", out.get("pickup_time") or "")
    out.setdefault("delivery_date", out.get("delivery_date") or "")
    out.setdefault("delivery_time", out.get("delivery_time") or "")

    if parsed.get("weight") and not out.get("weight"):
        out["weight"] = parsed["weight"]
    if parsed.get("pallets") != "" and not out.get("pallets"):
        out["pallets"] = parsed["pallets"]
    if out.get("weight") is None:
        out["weight"] = ""
    if out.get("pallets") is None:
        out["pallets"] = ""

    rate = out.get("rate")
    if rate is None and parsed.get("rate_hint") is not None:
        rate = parsed["rate_hint"]
        out["rate"] = rate

    # Drop if still no useful lane and no rate with cities
    if not origin and not destination:
        # money-only id with no cities
        if parsed["is_rate_only"] or not notes:
            return None
        # notes had no cities — drop
        if not parsed["has_cities"]:
            return None

    lid = str(out.get("id") or "").strip()
    # Keep real Load # (referenceNumber / shipmentId). Only invent ARC-* for junk.
    real_id = bool(lid) and (
        lid.isdigit()
        or (lid.upper().startswith("ARC-") is False and not _is_money_string(lid)
            and lid.upper() not in {"TL", "FULL", "LTL", "PARTIAL"})
    )
    if not real_id:
        if _is_money_string(lid) or lid.upper() in {"TL", "FULL", "LTL", "PARTIAL"} or not lid:
            rate_part = ""
            if rate is not None:
                rate_part = str(int(rate)) if float(rate) == int(float(rate)) else str(rate)
            elif _is_money_string(lid):
                rate_part = lid.replace("$", "").replace(",", "").strip()
            out["id"] = (
                f"ARC-{_sanitize_id_part(origin)}-"
                f"{_sanitize_id_part(destination)}-"
                f"{_sanitize_id_part(rate_part or 'NA', 16)}"
            )

    # tel: links -> board URL
    url = str(out.get("url") or "")
    if url.lower().startswith("tel:"):
        out["url"] = ARCBEST_BOARD_URL

    return out


def cleanse_rxo(load: dict) -> Optional[dict]:
    """Light RXO pass: expand ST+ZIP cities, sync aliases; keep weight/pallets."""
    if not isinstance(load, dict):
        return None
    out = dict(load)
    out["source"] = "RXO"
    pu = expand_zip_city(str(out.get("pickup_city") or out.get("origin") or "").strip())
    de = expand_zip_city(str(out.get("delivery_city") or out.get("destination") or "").strip())
    _set_city_aliases(out, pu, de)

    # Try notes for weight/pallets if missing
    if not out.get("weight") or not out.get("pallets"):
        w, p = extract_weight_pallets(out.get("notes"), out.get("equipment"))
        if w and not out.get("weight"):
            out["weight"] = w
        if p != "" and not out.get("pallets"):
            out["pallets"] = p
    if out.get("weight") is None:
        out["weight"] = ""
    if out.get("pallets") is None:
        out["pallets"] = ""

    out.setdefault("pickup_date", out.get("pickup_date") or "")
    out.setdefault("pickup_time", out.get("pickup_time") or "")
    out.setdefault("delivery_date", out.get("delivery_date") or "")
    out.setdefault("delivery_time", out.get("delivery_time") or "")

    def _split_combo(comb: str) -> tuple[str, str]:
        comb = (comb or "").strip()
        if not comb:
            return "", ""
        m = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T\s]+(\d{1,2}:\d{2}(?::\d{2})?))?", comb)
        if m:
            return m.group(1), (m.group(2) or "")
        m = re.match(r"^(\d{1,2}/\d{1,2}/\d{2,4})(?:\s+(\d{1,2}:\d{2}(?::\d{2})?))?", comb)
        if m:
            return m.group(1), (m.group(2) or "")
        m = re.match(
            r"^((?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)?\s*(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s*\d{4})?)"
            r"(?:\s+(\d{1,2}:\d{2}.*))?$",
            comb,
            re.I,
        )
        if m:
            return m.group(1).strip(), (m.group(2) or "").strip()
        return comb, ""

    # Split combined pickup/delivery into date fields when needed
    if not out.get("pickup_date") and out.get("pickup"):
        d, t = _split_combo(str(out["pickup"]))
        out["pickup_date"] = d
        if t and not out.get("pickup_time"):
            out["pickup_time"] = t
    if not out.get("delivery_date") and out.get("delivery"):
        d, t = _split_combo(str(out["delivery"]))
        out["delivery_date"] = d
        if t and not out.get("delivery_time"):
            out["delivery_time"] = t

    # Sync combined pickup/delivery strings for UI
    pu_d = str(out.get("pickup_date") or "").strip()
    pu_t = str(out.get("pickup_time") or "").strip()
    if pu_d or pu_t:
        out["pickup"] = " ".join(x for x in (pu_d, pu_t) if x)
    de_d = str(out.get("delivery_date") or "").strip()
    de_t = str(out.get("delivery_time") or "").strip()
    if de_d or de_t:
        out["delivery"] = " ".join(x for x in (de_d, de_t) if x)

    return out


def cleanse_loads(loads: list[dict]) -> list[dict]:
    """Apply per-source cleansers, then dedupe."""
    cleansed: list[dict] = []
    for load in loads or []:
        if not isinstance(load, dict):
            continue
        src = str(load.get("source") or "")
        try:
            if src == "Arrive":
                row = cleanse_arrive(load)
            elif src in ("ArcBest", "MoLo"):
                row = cleanse_arcbest(load)
            elif src == "RXO":
                row = cleanse_rxo(load)
            else:
                row = dict(load)
        except Exception:
            # Never let one bad row abort the whole merge/write
            row = dict(load)
        if row is None:
            continue
        if "notes" in row and row.get("notes"):
            row["notes"] = _sanitize_dashes(row.get("notes"))
        if "status" in row and row.get("status"):
            row["status"] = _sanitize_dashes(row.get("status"))
        cleansed.append(row)

    seen: set[tuple] = set()
    out: list[dict] = []
    for row in cleansed:
        key1 = (row.get("source"), str(row.get("id") or ""))
        key2 = (
            row.get("source"),
            str(row.get("pickup_city") or row.get("origin") or ""),
            str(row.get("delivery_city") or row.get("destination") or ""),
            str(row.get("pickup_date") or row.get("pickup") or ""),
            str(row.get("rate") if row.get("rate") is not None else ""),
        )
        if key1 in seen or key2 in seen:
            continue
        seen.add(key1)
        seen.add(key2)
        out.append(row)
    return out


if __name__ == "__main__":
    # --- Arrive sample ---
    arrive_before = {
        "id": "Fri\nSep 11\nRomeoville, IL\n(0mi)\n11:00 CDT",
        "source": "Arrive",
        "origin": "Sat\nSep 12\nKutztown, PA\n15:00 EDT",
        "destination": "Sat\nSep 12\nKutztown, PA\n15:00 EDT",
        "equipment": "",
        "pickup": "Fri\nSep 11\nRomeoville, IL\n(0mi)\n11:00 CDT",
        "delivery": "",
        "miles": 750,
        "rate": 2100,
        "status": "",
        "url": "https://arrive.example/board",
        "notes": "42,000 lbs / 26 pallets",
    }
    stop = parse_arrive_stop(arrive_before["pickup"])
    assert stop["city"] == "Romeoville, IL", stop
    assert stop["date"] == "Fri Sep 11", stop
    assert stop["time"] == "11:00 CDT", stop

    arrive_after = cleanse_arrive(arrive_before)
    assert arrive_after is not None
    assert arrive_after["origin"] == "Romeoville, IL", arrive_after
    assert arrive_after["destination"] == "Kutztown, PA", arrive_after
    assert arrive_after["pickup_city"] == "Romeoville, IL", arrive_after
    assert arrive_after["delivery_city"] == "Kutztown, PA", arrive_after
    assert arrive_after["pickup_date"] == "Fri Sep 11", arrive_after
    assert arrive_after["pickup_time"] == "11:00 CDT", arrive_after
    assert arrive_after["delivery_date"] == "Sat Sep 12", arrive_after
    assert arrive_after["delivery_time"] == "15:00 EDT", arrive_after
    assert arrive_after["pickup"] == "Fri Sep 11 11:00 CDT", arrive_after
    assert arrive_after["delivery"] == "Sat Sep 12 15:00 EDT", arrive_after
    assert str(arrive_after["id"]).startswith("ARR-"), arrive_after
    # Real LoadBoardId must not be rewritten to ARR-*
    arrive_real = cleanse_arrive({**arrive_before, "id": "9564487"})
    assert arrive_real is not None and arrive_real["id"] == "9564487", arrive_real
    assert "42000" in str(arrive_after["weight"]).replace(",", ""), arrive_after
    assert arrive_after["pallets"] == 26, arrive_after

    # --- ArcBest good notes ---
    arc_before = {
        "id": "TL",
        "source": "ArcBest",
        "origin": "",
        "destination": "",
        "equipment": "",
        "pickup": "",
        "delivery": "",
        "miles": None,
        "rate": 2259.0,
        "status": "",
        "url": "tel:+18005551212",
        "notes": "TL | Full | Chicago, IL | Pell City, AL | 38000 lbs | 18 pallets",
    }
    arc_after = cleanse_arcbest(arc_before)
    assert arc_after is not None
    assert arc_after["origin"] == "Chicago, IL", arc_after
    assert arc_after["destination"] == "Pell City, AL", arc_after
    assert arc_after["pickup_city"] == "Chicago, IL", arc_after
    assert arc_after["delivery_city"] == "Pell City, AL", arc_after
    assert arc_after["equipment"] == "TL", arc_after
    assert arc_after["status"] == "Full", arc_after
    assert str(arc_after["id"]).startswith("ARC-"), arc_after
    assert arc_after.get("url") == ARCBEST_BOARD_URL, arc_after
    assert "38000" in str(arc_after["weight"]).replace(",", ""), arc_after
    assert arc_after["pallets"] == 18, arc_after

    # --- ArcBest junk (drop) ---
    arc_junk = {
        "id": "$2,259.00",
        "source": "ArcBest",
        "origin": "",
        "destination": "",
        "notes": "$2,259.00 | Book It Rate",
        "rate": 2259.0,
        "url": "tel:+18005551212",
    }
    assert cleanse_arcbest(arc_junk) is None

    # --- ArcBest/MoLo real Load # must stay numeric (never ARC-*) ---
    molo_real = {
        "id": "2002766043",
        "source": "MoLo",
        "origin": "Ripon, WI",
        "destination": "Mebane, NC",
        "pickup_city": "Ripon, WI",
        "delivery_city": "Mebane, NC",
        "pickup_date": "09-08-2026",
        "rate": 1800,
        "notes": "shipmentId=4003678 | ref=2002766043 | type=MoLoTL",
        "url": "https://carriers.arcb.com/Shipments",
    }
    molo_after = cleanse_arcbest(molo_real)
    assert molo_after is not None
    assert molo_after["source"] == "MoLo", molo_after
    assert molo_after["id"] == "2002766043", molo_after
    arc_real = cleanse_arcbest({**molo_real, "id": "4005001", "source": "ArcBest",
                                "notes": "shipmentId=4005001 | type=Expedited"})
    assert arc_real is not None and arc_real["id"] == "4005001", arc_real
    assert arc_real["source"] == "ArcBest"

    # --- RXO passthrough ---
    rxo = {
        "id": "2-21411111",
        "source": "RXO",
        "origin": "GA 31069",
        "destination": "TX 75001",
        "pickup": "2026-09-05",
        "rate": 1800,
        "weight": 41000,
        "pallets": 24,
    }
    merged = cleanse_loads([arrive_before, arc_before, arc_junk, rxo])
    assert len(merged) == 3, merged
    rxo_out = [x for x in merged if x["source"] == "RXO"][0]
    assert rxo_out["id"] == "2-21411111"
    # ST+ZIP expanded via zip_coords when present
    assert "31069" in str(rxo_out["origin"]) or "Perry" in str(rxo_out["origin"]), rxo_out
    assert "31069" in str(rxo_out["pickup_city"]) or "Perry" in str(rxo_out["pickup_city"]), rxo_out
    assert "75001" in str(rxo_out["delivery_city"]) or "Dallas" in str(rxo_out.get("delivery_city") or "") or "TX" in str(rxo_out["delivery_city"]), rxo_out
    assert rxo_out["pickup_date"] == "2026-09-05"
    assert rxo_out["weight"] == 41000
    assert rxo_out["pallets"] == 24
    # Direct expand helper
    assert "Channahon" in expand_zip_city("IL 60410")

    print("OK")
    print("--- Arrive after ---")
    keys = (
        "id", "pickup_city", "pickup_date", "pickup_time",
        "delivery_city", "delivery_date", "delivery_time",
        "weight", "pallets", "rate", "origin", "destination",
    )
    print({k: arrive_after.get(k) for k in keys})
    print("--- ArcBest after ---")
    print({k: arc_after.get(k) for k in keys + ("equipment", "status", "url")})
    print("--- RXO after ---")
    print({k: rxo_out.get(k) for k in keys})
