/** CHR / Navisphere — best-effort API walk + content-script path. */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "CHR";
const BOARD = BROKER_URLS.CHR;

const ID_KEYS = ["loadId","LoadId","loadNumber","LoadNumber","shipmentId","ShipmentId","orderNumber","OrderNumber","id","Id"];

function firstStr(item, keys) {
  for (const k of keys) {
    if (item[k] != null && item[k] !== "") return String(item[k]).trim();
  }
  return "";
}

function cityFrom(obj) {
  if (!obj || typeof obj !== "object") return String(obj || "").trim();
  const city = String(obj.city || obj.City || obj.name || "").trim();
  const state = String(obj.state || obj.State || obj.stateCode || obj.StateCode || "").trim();
  const zipc = String(obj.zip || obj.postalCode || obj.Zip || "").trim();
  if (city && state && zipc) return `${city}, ${state} ${zipc}`;
  if (city && state) return `${city}, ${state}`;
  return city || state || "";
}

function fromItem(item) {
  if (!item || typeof item !== "object") return null;
  const lid = firstStr(item, ID_KEYS);
  let origin =
    cityFrom(item.origin || item.Origin || item.pickup || {}) ||
    firstStr(item, ["originCity","OriginCity","pickupCity","PickupCity","originLocation"]);
  let dest =
    cityFrom(item.destination || item.Destination || item.delivery || {}) ||
    firstStr(item, ["destinationCity","DestinationCity","deliveryCity","DeliveryCity","destLocation"]);
  const stops = item.stops || item.Stops;
  if ((!origin || !dest) && Array.isArray(stops) && stops.length) {
    origin = origin || cityFrom(stops[0]);
    dest = dest || cityFrom(stops[stops.length - 1]);
  }
  if (!origin && !dest) return null;
  let rate = item.rate ?? item.Rate ?? item.bookNowRate ?? item.price;
  try { rate = rate != null && rate !== "" ? Number(rate) : null; } catch { rate = null; }
  let miles = item.miles ?? item.Miles ?? item.distance ?? item.Distance;
  try { miles = miles != null && miles !== "" ? Number(miles) : null; } catch { miles = null; }
  const raw = {
    id: lid || `CHR-${origin}-${dest}`,
    origin,
    destination: dest,
    pickupCity: origin,
    deliveryCity: dest,
    pickupDate: firstStr(item, ["pickupDate","PickupDate","pickUpDate","originDate","pickupStart"]),
    deliveryDate: firstStr(item, ["deliveryDate","DeliveryDate","destDate","deliveryStart"]),
    equipment: firstStr(item, ["equipment","Equipment","equipmentType","EquipmentType","trailerType"]),
    miles,
    weight: item.weight ?? item.Weight ?? "",
    rate,
    url: lid ? `${BOARD}?loadId=${lid}` : BOARD,
  };
  try { return normalizeLoad(raw, SOURCE, BOARD); } catch { return null; }
}

function walkItems(body, out, depth = 0) {
  if (depth > 6 || body == null) return;
  if (Array.isArray(body)) {
    for (const row of body.slice(0, 500)) {
      if (row && typeof row === "object") {
        const keys = new Set(Object.keys(row).map((k) => k.toLowerCase()));
        if (
          ["loadid","loadnumber","origin","destination","pickupcity","miles","rate","stops"].some((k) => keys.has(k)) ||
          ((keys.has("origin") || keys.has("pickup") || keys.has("origincity")) &&
            (keys.has("destination") || keys.has("delivery") || keys.has("destinationcity")))
        ) {
          const n = fromItem(row);
          if (n) out.push(n);
        } else walkItems(row, out, depth + 1);
      }
    }
    return;
  }
  if (typeof body === "object") {
    for (const key of ["loads","Loads","items","Items","results","Results","data","Data","availableLoads","searchResults","value"]) {
      if (key in body) walkItems(body[key], out, depth + 1);
    }
  }
}

export function loadsFromChrPayload(body) {
  const bucket = [];
  walkItems(body, bucket);
  const seen = new Set();
  const out = [];
  for (const L of bucket) {
    const key = String(L.id || JSON.stringify(L).slice(0, 120));
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(L);
  }
  return out;
}

export function isChrInterestingUrl(url) {
  const u = (url || "").toLowerCase();
  return /load|shipment|freight|search|available|navisphere|carrier/.test(u);
}

export async function fetchChr(/* opts */) {
  try {
    const res = await fetch(BOARD, { credentials: "include", redirect: "follow" });
    const text = await res.text();
    const ct = res.headers.get("content-type") || "";
    if (
      isLoginResponse(res.status, ct, text, res.url || BOARD) ||
      /login|signin|okta|sso/i.test(res.url || "")
    ) {
      return { status: "needs_login", loads: [], error: "CHR / Navisphere login required" };
    }
  } catch (e) {
    return { status: "error", loads: [], error: String(e.message || e) };
  }
  return {
    status: "no_tab",
    loads: [],
    error: "Open Navisphere Carrier and search loads — extension captures API/DOM",
  };
}
