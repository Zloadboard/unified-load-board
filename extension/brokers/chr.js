/** CHR / Navisphere — best-effort API walk + content-script path. */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "CHR";
const BOARD = BROKER_URLS.CHR;

const ID_KEYS = [
  "loadId","LoadId","loadNumber","LoadNumber","LoadNumberId","carrierLoadId","CarrierLoadId",
  "shipmentId","ShipmentId","orderNumber","OrderNumber","orderId","OrderId",
  "movementId","MovementId","bolNumber","BolNumber","quoteId","QuoteId",
  "postingId","PostingId","availabilityId","AvailabilityId",
  "id","Id",
];

function firstStr(item, keys) {
  for (const k of keys) {
    if (item[k] != null && item[k] !== "") return String(item[k]).trim();
  }
  return "";
}

function cityFrom(obj) {
  if (obj == null) return "";
  if (typeof obj === "string") return obj.trim();
  if (typeof obj !== "object") return String(obj || "").trim();
  const city = String(
    obj.city || obj.City || obj.cityName || obj.CityName ||
    obj.name || obj.locationName || obj.LocationName || ""
  ).trim();
  const state = String(
    obj.state || obj.State || obj.stateCode || obj.StateCode ||
    obj.stateAbbreviation || obj.StateAbbreviation ||
    obj.stateOrProvince || obj.province || ""
  ).trim();
  const zipc = String(
    obj.zip || obj.postalCode || obj.Zip || obj.zipCode || obj.postal || ""
  ).trim();
  if (city && state && zipc) return `${city}, ${state} ${zipc}`;
  if (city && state) return `${city}, ${state}`;
  if (state && zipc) return `${state} ${zipc}`;
  return city || state || "";
}

function hasStateToken(s) {
  const str = String(s || "").trim();
  if (!str) return false;
  if (/,[\s]*[A-Za-z]{2}\b/.test(str)) return true;
  if (/\b[A-Za-z]{2}\s+\d{5}\b/.test(str)) return true;
  if (/^[A-Za-z]{2}$/.test(str)) return true;
  if (/\s[A-Za-z]{2}$/.test(str)) return true; // "ITASCA IL"
  return false;
}

function joinCityState(city, state, zip) {
  city = String(city || "").trim();
  state = String(state || "").trim();
  zip = String(zip || "").trim();
  if (!city && !state) return "";
  if (city && hasStateToken(city) && !state) return city;
  if (city && state && zip) return `${city}, ${state} ${zip}`;
  if (city && state) return `${city}, ${state}`;
  if (state && zip) return `${state} ${zip}`;
  return city || state || "";
}

function fromItem(item) {
  if (!item || typeof item !== "object") return null;
  // Dig one level into nested load/shipment wrappers common on Navisphere
  const nested = item.load || item.Load || item.shipment || item.Shipment || item.posting || null;
  const src = nested && typeof nested === "object" ? { ...item, ...nested } : item;

  let lid = firstStr(src, ID_KEYS);
  // Avoid using useless generic ids that are empty-ish or look like UI keys
  if (lid && /^(null|undefined|true|false)$/i.test(lid)) lid = "";

  let origin =
    cityFrom(src.origin || src.Origin || src.pickup || src.Pickup || src.originLocation || {}) ||
    firstStr(src, ["originCity","OriginCity","pickupCity","PickupCity","originLocation","OriginLocation"]);
  let dest =
    cityFrom(src.destination || src.Destination || src.delivery || src.Delivery || src.destLocation || {}) ||
    firstStr(src, ["destinationCity","DestinationCity","deliveryCity","DeliveryCity","destLocation","DestLocation","destCity"]);

  // Sibling state fields when origin/dest are city-only strings ("ITASCA" + destinationState="IL")
  const oState = firstStr(src, [
    "originState","OriginState","originStateCode","OriginStateCode",
    "pickupState","PickupState","pickupStateCode","originProvince",
  ]);
  const dState = firstStr(src, [
    "destinationState","DestinationState","destinationStateCode","DestinationStateCode",
    "deliveryState","DeliveryState","deliveryStateCode","destState","DestState","destProvince",
  ]);
  const oZip = firstStr(src, ["originZip","OriginZip","originPostalCode","pickupZip","PickupZip"]);
  const dZip = firstStr(src, ["destinationZip","DestinationZip","deliveryZip","DeliveryZip","destZip"]);
  if (origin && oState && !hasStateToken(origin)) origin = joinCityState(origin, oState, oZip);
  else if (origin && oZip && !/\d{5}/.test(origin)) origin = joinCityState(origin, oState, oZip);
  if (dest && dState && !hasStateToken(dest)) dest = joinCityState(dest, dState, dZip);
  else if (dest && dZip && !/\d{5}/.test(dest)) dest = joinCityState(dest, dState, dZip);

  const stops = src.stops || src.Stops || src.StopList || src.locations || src.Locations;
  if ((!origin || !dest || !hasStateToken(origin) || !hasStateToken(dest)) && Array.isArray(stops) && stops.length) {
    const first = cityFrom(stops[0]);
    const last = cityFrom(stops[stops.length - 1]);
    if (!origin || (first && hasStateToken(first) && !hasStateToken(origin))) origin = origin && hasStateToken(origin) ? origin : (first || origin);
    if (!dest || (last && hasStateToken(last) && !hasStateToken(dest))) dest = dest && hasStateToken(dest) ? dest : (last || dest);
  }
  if (!origin && !dest) return null;

  let rate = src.rate ?? src.Rate ?? src.bookNowRate ?? src.price ?? src.RateAmount;
  try { rate = rate != null && rate !== "" ? Number(rate) : null; } catch { rate = null; }
  let miles = src.miles ?? src.Miles ?? src.distance ?? src.Distance ?? src.totalMiles;
  try { miles = miles != null && miles !== "" ? Number(miles) : null; } catch { miles = null; }

  const detail = firstStr(src, ["url","detailUrl","detail_url","href","loadUrl","LoadUrl","deepLink","DeepLink"]);
  let url = BOARD;
  if (detail && /^https?:\/\//i.test(detail)) {
    url = detail;
  } else if (lid && !/^CHR-/i.test(lid) && lid.indexOf(",") < 0) {
    // Best available Navisphere deep links (SPA still needs session)
    url = `https://www.navispherecarrier.com/find-loads?loadId=${encodeURIComponent(lid)}`;
  }

  const raw = {
    id: lid || `CHR-${origin}-${dest}`,
    origin,
    destination: dest,
    pickupCity: origin,
    deliveryCity: dest,
    pickupDate: firstStr(src, ["pickupDate","PickupDate","pickUpDate","originDate","pickupStart","PickupStart"]),
    deliveryDate: firstStr(src, ["deliveryDate","DeliveryDate","destDate","deliveryStart","DeliveryStart"]),
    equipment: firstStr(src, ["equipment","Equipment","equipmentType","EquipmentType","trailerType","TrailerType"]),
    miles,
    weight: src.weight ?? src.Weight ?? "",
    rate,
    url,
  };
  try {
    const n = normalizeLoad(raw, SOURCE, BOARD);
    // Keep a non-board url when we have a real lid
    if (lid && !/^CHR-/i.test(lid) && n.url === BOARD) {
      n.url = `https://www.navispherecarrier.com/find-loads?loadId=${encodeURIComponent(lid)}`;
    }
    return n;
  } catch {
    return null;
  }
}

function walkItems(body, out, depth = 0) {
  if (depth > 6 || body == null) return;
  if (Array.isArray(body)) {
    for (const row of body.slice(0, 500)) {
      if (row && typeof row === "object") {
        const keys = new Set(Object.keys(row).map((k) => k.toLowerCase()));
        if (
          ["loadid","loadnumber","origin","destination","pickupcity","miles","rate","stops","origincity","destinationcity","origincityname"].some((k) => keys.has(k)) ||
          ((keys.has("origin") || keys.has("pickup") || keys.has("origincity") || keys.has("pickupcity")) &&
            (keys.has("destination") || keys.has("delivery") || keys.has("destinationcity") || keys.has("deliverycity")))
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
      /okta\.|auth0\.|\/sso\//i.test(res.url || "")
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
