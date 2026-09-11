/** Echo — getOpenBoardLoadsV3 mapping (from scanner/sources/echo.py). */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "Echo";
const BOARD = BROKER_URLS.Echo;
const CARRIER_ID = "10261";

function fmtCity(stop) {
  if (!stop || typeof stop !== "object") return "";
  const city = String(stop.city || "").trim().replace(/\b\w/g, (c) => c.toUpperCase());
  const state = String(stop.state || "").trim().toUpperCase();
  const zipc = String(stop.postalCode || "").trim();
  if (city && state && zipc) return `${city}, ${state} ${zipc}`;
  if (city && state) return `${city}, ${state}`;
  return city || state || "";
}

function splitAppt(stop) {
  const appt = (stop && stop.appointmentTime) || {};
  const start = String(appt.startTime || "").trim();
  const end = String(appt.endTime || "").trim();
  function parts(s) {
    let m = (s || "").match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})\s+(\d{1,2}:\d{2})/);
    if (m) return [`${m[3]}-${m[1].padStart(2,"0")}-${m[2].padStart(2,"0")}`, m[4]];
    m = (s || "").match(/^(\d{4}-\d{2}-\d{2})[T\s]+(\d{1,2}:\d{2})/);
    if (m) return [m[1], m[2]];
    return [s, ""];
  }
  const [d1, t1] = parts(start);
  const [, t2] = parts(end);
  if (t1 && t2 && t1 !== t2) return [d1, `${t1} - ${t2}`];
  return [d1, t1];
}

function equipLabel(equipment) {
  if (!equipment) return "";
  const list = Array.isArray(equipment) ? equipment : [equipment];
  const names = [];
  for (const e of list) {
    if (!e || typeof e !== "object") continue;
    const name = String(e.displayName || e.truckType || "").trim();
    if (name && !names.includes(name)) names.push(name);
  }
  return names.join(", ");
}

export function loadsFromEchoPayload(body, priceById = {}) {
  let root = body;
  if (body && typeof body === "object" && "data" in body) root = body.data;
  let items = null;
  if (root && typeof root === "object" && !Array.isArray(root)) {
    items = root.items || root.loads || root.results;
  } else if (Array.isArray(root)) items = root;
  if (!Array.isArray(items)) return [];
  const out = [];
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const stops = item.loadStops || item.stops || [];
    const picks = stops.filter((s) => ["pick", "pickup"].includes(String(s.stopType || "").toLowerCase()));
    const drops = stops.filter((s) => ["drop", "delivery", "del"].includes(String(s.stopType || "").toLowerCase()));
    const pick = picks[0] || stops[0] || {};
    const drop = drops.slice(-1)[0] || (stops.length > 1 ? stops[stops.length - 1] : {}) || {};
    const puCity = fmtCity(pick);
    const deCity = fmtCity(drop);
    if (!puCity || !deCity) continue;
    const [puD, puT] = splitAppt(pick);
    const [deD, deT] = splitAppt(drop);
    const loadId = String(item.loadId || item.id || "");
    let rate = item.bookNowPrice || item.rate || priceById[loadId];
    try { rate = rate != null && rate !== "" && Number(rate) !== 0 ? Number(rate) : null; } catch { rate = null; }
    let miles = item.loadedMiles ?? item.miles;
    try { miles = miles != null ? Number(miles) : null; } catch { miles = null; }
    const raw = {
      id: loadId || `ECHO-${puCity}-${deCity}-${puD}`,
      origin: puCity,
      destination: deCity,
      pickupCity: puCity,
      deliveryCity: deCity,
      pickupDate: puD,
      pickupTime: puT,
      deliveryDate: deD,
      deliveryTime: deT,
      weight: item.weight,
      equipment: equipLabel(item.equipment),
      miles,
      rate,
      url:
        loadId && /^\d+$/.test(loadId)
          ? `https://echodrive.echo.com/v2/carrier/${CARRIER_ID}/availableLoads?loadId=${loadId}`
          : BOARD,
    };
    try { out.push(normalizeLoad(raw, SOURCE, BOARD)); } catch { /* skip */ }
  }
  return out;
}

export function isEchoInterestingUrl(url) {
  const u = (url || "").toLowerCase();
  return u.includes("getopenboardloads") || u.includes("booknowprice") || u.includes("availableload");
}

const DEFAULT_URLS = [
  `https://echodrive.echo.com/api/carrier/${CARRIER_ID}/getOpenBoardLoadsV3`,
  `https://echodrive.echo.com/v2/api/getOpenBoardLoadsV3`,
  `https://echodrive.echo.com/api/getOpenBoardLoadsV3`,
];

async function tryUrl(url, method, bodyText) {
  const opts = {
    method: method || "POST",
    credentials: "include",
    headers: { accept: "application/json", "content-type": "application/json" },
  };
  if (bodyText) opts.body = bodyText;
  else if ((opts.method || "").toUpperCase() === "POST") {
    const today = new Date();
    const end = new Date(today);
    end.setDate(end.getDate() + 10);
    opts.body = JSON.stringify({
      origin: { city: "Romeoville", state: "IL", deadHead: 100 },
      pickupStart: today.toISOString().slice(0, 10),
      pickupEnd: end.toISOString().slice(0, 10),
    });
  }
  const res = await fetch(url, opts);
  const ct = res.headers.get("content-type") || "";
  const text = await res.text();
  if (isLoginResponse(res.status, ct, text, res.url || url) || /auth0\.com|\/u\/login/i.test(res.url || "")) {
    return { status: "needs_login", loads: [], error: "Echo login required" };
  }
  if (!res.ok) return { status: "error", loads: [], error: `HTTP ${res.status}` };
  let json;
  try { json = JSON.parse(text); } catch {
    return { status: "error", loads: [], error: "non-json" };
  }
  const loads = loadsFromEchoPayload(json);
  return { status: loads.length ? "ok" : "empty", loads, error: loads.length ? "" : "0 loads", endpoint: url };
}

export async function fetchEcho(opts = {}) {
  const bodies = opts.lastRequestBodies?.Echo || [];
  let sawLogin = false;
  let lastErr = "";
  for (const b of bodies) {
    if (!b.url || !isEchoInterestingUrl(b.url)) continue;
    try {
      const r = await tryUrl(b.url, b.method || "POST", b.bodyText);
      if (r.status === "needs_login") { sawLogin = true; lastErr = r.error; continue; }
      if (r.loads.length) return r;
    } catch { /* next */ }
  }
  const urls = [...(opts.discoveredEndpoints?.Echo || []), ...DEFAULT_URLS];
  const seen = new Set();
  for (const url of urls) {
    if (!url || seen.has(url)) continue;
    seen.add(url);
    try {
      const r = await tryUrl(url, "POST");
      if (r.status === "needs_login") { sawLogin = true; lastErr = r.error; continue; }
      if (r.loads.length) return r;
      lastErr = r.error || lastErr;
    } catch { /* next */ }
  }
  try {
    const res = await fetch(BOARD, { credentials: "include", redirect: "follow" });
    const text = await res.text();
    const ct = res.headers.get("content-type") || "";
    if (isLoginResponse(res.status, ct, text, res.url || BOARD) || /auth0\.com|\/u\/login/i.test(res.url || "")) {
      sawLogin = true;
    }
  } catch (e) {
    return { status: "error", loads: [], error: String(e.message || e) };
  }
  if (sawLogin) {
    return { status: "needs_login", loads: [], error: "Echo login required" };
  }
  return {
    status: "no_tab",
    loads: [],
    error: lastErr || "Open Echo Available Loads once so the extension can capture getOpenBoardLoadsV3",
  };
}
