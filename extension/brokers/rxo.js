/** RXO — search/loadboard API mapping (from scanner/sources/rxo.py). */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "RXO";
const BOARD = BROKER_URLS.RXO;

const DEFAULT_URLS = [
  "https://carrier.rxoconnect.rxo.com/api/loadboard/search/loadboard",
  "https://carrier.rxoconnect.rxo.com/loadboard/api/search/loadboard",
  "https://carrier.rxoconnect.rxo.com/api/search/loadboard",
];

function digDate(obj) {
  if (!obj || typeof obj !== "object") return "";
  for (const k of [
    "pickupDate","pickup_date","pickUpDate","availableDate","availabilityDate",
    "earliestPickupDate","pickupStartDate","pickupStart","puDate","startDate",
    "scheduledPickupDate","originDate","originPickupDateTimeInUTC",
    "scheduledArrivalEarly","scheduledArrivalEarlyDateTimeInUTC","scheduledArrivalLate",
  ]) {
    if (obj[k] != null && obj[k] !== "") return String(obj[k]).trim();
  }
  for (const nestKey of ["pickup","origin","appointment","appointmentTime","serviceWindow","schedule"]) {
    const nest = obj[nestKey];
    if (nest && typeof nest === "object") {
      const dug = digDate(nest);
      if (dug) return dug;
    } else if (typeof nest === "string" && nest.trim()) return nest.trim();
  }
  const stops = obj.stops || obj.loadStops || obj.Stops;
  if (Array.isArray(stops) && stops.length) {
    const ordered = [...stops].sort((a, b) => {
      const ta = String(a?.type || "").toLowerCase().startsWith("pick") ? 0 : 1;
      const tb = String(b?.type || "").toLowerCase().startsWith("pick") ? 0 : 1;
      return ta - tb;
    });
    for (const st of ordered) {
      if (st && typeof st === "object") {
        const d = digDate(st);
        if (d) return d;
      }
    }
  }
  return "";
}

function peelDt(dug) {
  dug = (dug || "").trim();
  if (!dug) return ["", ""];
  let m = dug.match(/^(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2})/);
  if (m) return [m[1], m[2]];
  m = dug.match(
    /^((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s*\d{4})?)(?:\s*,?\s*(\d{1,2}:\d{2}\s*(?:AM|PM)?))?/i
  );
  if (m) return [m[1].trim(), (m[2] || "").trim()];
  return [dug, ""];
}

function cityFromLoc(loc) {
  if (!loc) return "";
  if (typeof loc === "string") return loc.trim();
  if (typeof loc !== "object") return "";
  const city = (loc.city || loc.City || loc.name || "").toString().trim();
  const state = (loc.state || loc.State || loc.stateCode || loc.StateCode || "").toString().trim();
  const zip = (loc.zip || loc.postalCode || loc.Zip || "").toString().trim();
  if (city && state && zip) return `${city}, ${state} ${zip}`;
  if (city && state) return `${city}, ${state}`;
  if (state && zip) return `${state} ${zip}`;
  return city || state || zip;
}

function enrichRxo(rawItem, normalized) {
  const out = { ...normalized };
  const num = rawItem.number;
  if (num != null && num !== "") out.id = String(num).trim();
  else if (!out.id) {
    const rid = rawItem.alternateNumber || rawItem.suggestionId;
    if (rid != null && rid !== "") out.id = String(rid).trim();
  }
  if (!out.pickup_date) {
    const dug = digDate(rawItem);
    if (dug) {
      const [d, t] = peelDt(dug);
      out.pickup_date = d || dug;
      if (t && !out.pickup_time) out.pickup_time = t;
      out.pickup = [out.pickup_date, out.pickup_time].filter(Boolean).join(" ");
    }
  }
  if ((out.rate == null || out.rate === "") && rawItem) {
    for (const k of ["dmpRate", "genericDMPRate", "bidAmount", "bookNowPrice", "rate"]) {
      const v = rawItem[k];
      if (typeof v === "number" && v) { out.rate = v; break; }
      if (typeof v === "string" && v.trim()) {
        const n = Number(v.replace(/[$,]/g, ""));
        if (Number.isFinite(n)) { out.rate = n; break; }
      }
    }
  }
  if (out.id && /^\d+$/.test(String(out.id))) {
    out.url = `https://carrier.rxoconnect.rxo.com/loads/${out.id}`;
  }
  return out;
}

export function loadsFromRxoPayload(body) {
  const out = [];
  let items = null;
  if (body && typeof body === "object") {
    const al = body.availableLoads;
    if (al && typeof al === "object" && Array.isArray(al.items)) items = al.items;
    else if (Array.isArray(body.items)) items = body.items;
    else if (Array.isArray(body)) items = body;
  }
  if (!items) return out;
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const origin =
      cityFromLoc(item.origin) ||
      cityFromLoc(item.originLocation) ||
      [item.originCity, item.originState, item.originZip].filter(Boolean).join(" ") ||
      cityFromLoc((item.stops || [])[0]);
    const dest =
      cityFromLoc(item.destination) ||
      cityFromLoc(item.destinationLocation) ||
      [item.destinationCity, item.destinationState, item.destinationZip].filter(Boolean).join(" ") ||
      cityFromLoc((item.stops || item.loadStops || []).slice(-1)[0]);
    const raw = {
      id: item.number || item.id || item.loadId || item.alternateNumber || "",
      origin,
      destination: dest,
      pickupCity: origin,
      deliveryCity: dest,
      miles: item.miles ?? item.distance ?? item.tripMiles,
      weight: item.weight ?? item.totalWeight,
      equipment: item.equipmentType || item.equipment || item.trailerType || "",
      rate: item.dmpRate ?? item.bookNowPrice ?? item.rate,
      url: BOARD,
    };
    try {
      let n = normalizeLoad(raw, SOURCE, BOARD);
      n = enrichRxo(item, n);
      if (n.origin || n.destination || n.rate || n.id) out.push(n);
    } catch { /* skip */ }
  }
  return out;
}

export function isRxoInterestingUrl(url) {
  const u = (url || "").toLowerCase();
  return u.includes("search/loadboard") || u.includes("availableloads") || u.includes("loadboard");
}

async function tryUrl(url, method, bodyText) {
  const opts = {
    method: method || "GET",
    credentials: "include",
    headers: { accept: "application/json" },
  };
  if (bodyText && (method || "GET").toUpperCase() === "POST") {
    opts.headers["content-type"] = "application/json";
    opts.body = bodyText;
  }
  const res = await fetch(url, opts);
  const ct = res.headers.get("content-type") || "";
  const text = await res.text();
  if (isLoginResponse(res.status, ct, text, res.url || url)) {
    return { status: "needs_login", loads: [], error: "RXO login required" };
  }
  if (!res.ok) return { status: "error", loads: [], error: `HTTP ${res.status}` };
  let json;
  try { json = JSON.parse(text); } catch {
    return { status: "error", loads: [], error: "non-json" };
  }
  const loads = loadsFromRxoPayload(json);
  return {
    status: loads.length ? "ok" : "empty",
    loads,
    error: loads.length ? "" : "0 loads",
    endpoint: url,
  };
}

export async function fetchRxo(opts = {}) {
  const discovered = opts.discoveredEndpoints?.RXO || [];
  const bodies = opts.lastRequestBodies?.RXO || [];
  // Prefer replaying captured loadboard POSTs
  for (const b of bodies) {
    if (!b.url || !isRxoInterestingUrl(b.url)) continue;
    try {
      const r = await tryUrl(b.url, b.method || "POST", b.bodyText);
      if (r.status === "needs_login") return r;
      if (r.loads.length) return r;
    } catch { /* next */ }
  }
  const urls = [...discovered, ...DEFAULT_URLS];
  const seen = new Set();
  for (const url of urls) {
    if (!url || seen.has(url)) continue;
    seen.add(url);
    try {
      // Default search body — Romeoville IL DH 150 (best-effort)
      const body = JSON.stringify({
        currentPage: 1,
        pageSize: 50,
        origin: { city: "Romeoville", state: "IL", deadhead: 150 },
      });
      let r = await tryUrl(url, "POST", body);
      if (r.status === "needs_login") return r;
      if (r.loads.length) return r;
      r = await tryUrl(url, "GET");
      if (r.status === "needs_login") return r;
      if (r.loads.length) return r;
    } catch { /* next */ }
  }
  try {
    const res = await fetch(BOARD, { credentials: "include", redirect: "follow" });
    const text = await res.text();
    const ct = res.headers.get("content-type") || "";
    if (isLoginResponse(res.status, ct, text, res.url || BOARD) ||
        /login\.id\.rxo\.com|sign\s*in/i.test(res.url + text.slice(0, 2000))) {
      return { status: "needs_login", loads: [], error: "RXO login required" };
    }
  } catch (e) {
    return { status: "error", loads: [], error: String(e.message || e) };
  }
  return {
    status: "no_tab",
    loads: [],
    error: "Open RXO Available Loads once so the extension can capture search/loadboard",
  };
}
