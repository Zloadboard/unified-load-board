/** Arrive — GraphQL getLoads / LoadBoardId mapping (from scanner/sources/arrive.py). */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "Arrive";
const BOARD = BROKER_URLS.Arrive;

const EQUIP = { V: "Van", VR: "Van/Reefer", R: "Reefer", F: "Flatbed", FD: "Flatbed" };

const DEFAULT_GQL_URLS = [
  "https://carrier.arrivelogistics.com/graphql",
  "https://carrier.arrivelogistics.com/api/graphql",
  "https://api.arrivelogistics.com/graphql",
];

const GET_LOADS_QUERY = `query GetLoads($input: GetLoadsInput) {
  getLoads(input: $input) {
    data {
      LoadBoardId
      PickupEarlyCity
      PickupEarlyStateCode
      DeliveryLateCity
      DeliveryLateStateCode
      PickupApptEarliest
      PickupApptLatest
      DeliveryApptEarliest
      DeliveryApptLatest
      PickupLocationIANACode
      DeliveryLocationIANACode
      Miles
      Weight
      TopSpend
      EquipmentType
      LoadStatus
    }
  }
}`;

function citySt(city, state) {
  const c = (city || "").toString().trim();
  const s = (state || "").toString().trim();
  if (c && s) return `${c}, ${s}`;
  return c || s;
}

function arriveLocalParts(iso, iana) {
  if (!iso) return ["", ""];
  try {
    const raw = String(iso).trim().replace(/(Z|[+-]\d{2}:\d{2})$/, "");
    const d = new Date(raw + "Z"); // parse as UTC wall then use components from naive
    // Prefer wall-clock from string (Arrive labels Z but shows local)
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) return ["", ""];
    const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
    const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][dt.getUTCDay()];
    const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.getUTCMonth()];
    const day = dt.getUTCDate();
    const tod = `${String(dt.getUTCHours()).padStart(2,"0")}:${String(dt.getUTCMinutes()).padStart(2,"0")}`;
    let tz = "";
    if (iana) {
      try {
        tz = new Intl.DateTimeFormat("en-US", { timeZone: String(iana), timeZoneName: "short" })
          .formatToParts(new Date())
          .find((p) => p.type === "timeZoneName")?.value || "";
      } catch { /* ignore */ }
    }
    return [`${dow} ${mon} ${day}`, `${tod}${tz ? " " + tz : ""}`.trim()];
  } catch {
    return ["", ""];
  }
}

function equip(cell) {
  const c = (cell || "").toString().trim().toUpperCase();
  return EQUIP[c] || (cell || "").toString().trim();
}

export function fromArriveApiItem(item) {
  if (!item || typeof item !== "object") return null;
  const lid = item.LoadBoardId ?? item.loadBoardId ?? item.loadId ?? item.id;
  if (lid == null || lid === "") return null;
  const lidS = String(lid).trim();
  const origin = citySt(item.PickupEarlyCity, item.PickupEarlyStateCode);
  const destination = citySt(item.DeliveryLateCity, item.DeliveryLateStateCode);
  if (!origin || !destination) return null;
  const [puDate, puTime] = arriveLocalParts(
    item.PickupApptEarliest || item.PickupApptLatest,
    item.PickupLocationIANACode
  );
  const [deDate, deTime] = arriveLocalParts(
    item.DeliveryApptEarliest || item.DeliveryApptLatest,
    item.DeliveryLocationIANACode
  );
  let miles = item.Miles;
  try { miles = miles != null ? Number(miles) : null; } catch { miles = null; }
  let weight = item.Weight;
  try { weight = weight != null ? Math.round(Number(weight)) : ""; } catch { /* keep */ }
  let rate = item.TopSpend;
  try { rate = rate != null ? Number(rate) : null; } catch { rate = null; }
  const raw = {
    id: lidS,
    origin,
    destination,
    pickupCity: origin,
    deliveryCity: destination,
    pickupDate: puDate,
    pickupTime: puTime,
    deliveryDate: deDate,
    deliveryTime: deTime,
    pickup: `${puDate} ${puTime}`.trim(),
    delivery: `${deDate} ${deTime}`.trim(),
    miles,
    weight: weight !== "" && weight != null ? weight : "",
    equipment: equip(item.EquipmentType || item.equipmentType),
    rate,
    url: /^\d+$/.test(lidS)
      ? `https://carrier.arrivelogistics.com/find-loads?loadBoardId=${lidS}`
      : BOARD,
    status: String(item.LoadStatus || ""),
  };
  try {
    return normalizeLoad(raw, SOURCE, BOARD);
  } catch {
    return null;
  }
}

function walkLoadBoardItems(obj, out, depth = 0) {
  if (depth > 12 || obj == null) return;
  if (Array.isArray(obj)) {
    if (obj[0] && typeof obj[0] === "object" && ("LoadBoardId" in obj[0] || "loadBoardId" in obj[0])) {
      out.push(...obj.filter((x) => x && typeof x === "object"));
      return;
    }
    for (const it of obj.slice(0, 50)) {
      walkLoadBoardItems(it, out, depth + 1);
      if (out.length >= 500) return;
    }
    return;
  }
  if (typeof obj !== "object") return;
  if ("LoadBoardId" in obj || "loadBoardId" in obj) {
    out.push(obj);
    return;
  }
  const gl = obj.getLoads;
  if (gl && typeof gl === "object" && Array.isArray(gl.data)) {
    out.push(...gl.data.filter((x) => x && typeof x === "object"));
    return;
  }
  if (obj.data && typeof obj.data === "object") {
    walkLoadBoardItems(obj.data, out, depth + 1);
    if (out.length) return;
  }
  for (const v of Object.values(obj)) {
    walkLoadBoardItems(v, out, depth + 1);
    if (out.length >= 500) return;
  }
}

export function loadsFromArrivePayload(body) {
  const rows = [];
  walkLoadBoardItems(body, rows);
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    const n = fromArriveApiItem(row);
    if (!n) continue;
    const id = String(n.id || "");
    if (!id || seen.has(id)) continue;
    seen.add(id);
    out.push(n);
  }
  return out;
}

export function isArriveInterestingUrl(url) {
  const u = (url || "").toLowerCase();
  return u.includes("graphql") || u.includes("getloads") || u.includes("arrivelogistics");
}

async function tryGraphql(url, cachedBody) {
  const body =
    cachedBody ||
    JSON.stringify({
      operationName: "GetLoads",
      query: GET_LOADS_QUERY,
      variables: { input: {} },
    });
  const res = await fetch(url, {
    method: "POST",
    credentials: "include",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body,
  });
  const ct = res.headers.get("content-type") || "";
  const text = await res.text();
  if (isLoginResponse(res.status, ct, text, res.url || url)) {
    return { status: "needs_login", loads: [], error: "Arrive login required" };
  }
  if (!res.ok) {
    return { status: "error", loads: [], error: `HTTP ${res.status}` };
  }
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    return { status: "error", loads: [], error: "non-json" };
  }
  const loads = loadsFromArrivePayload(json);
  return {
    status: loads.length ? "ok" : "empty",
    loads,
    error: loads.length ? "" : "0 loads from GraphQL",
    endpoint: url,
  };
}

/**
 * @param {{ discoveredEndpoints?: object, lastRequestBodies?: object }} opts
 */
export async function fetchArrive(opts = {}) {
  const endpoints = [
    ...(opts.discoveredEndpoints?.Arrive || []),
    ...DEFAULT_GQL_URLS,
  ];
  const seen = new Set();
  const bodies = opts.lastRequestBodies?.Arrive || [];
  let sawLogin = false;
  let lastErr = "";
  for (const url of endpoints) {
    if (!url || seen.has(url)) continue;
    seen.add(url);
    try {
      // Prefer replaying a captured GraphQL body if we have one for this host
      const matchingBody = bodies.find((b) => (b.url || "").includes(new URL(url).host));
      const result = await tryGraphql(url, matchingBody?.bodyText);
      if (result.status === "needs_login") {
        sawLogin = true;
        lastErr = result.error || lastErr;
        continue; // try remaining endpoints + tab capture
      }
      if (result.loads.length) return result;
      if (result.status === "ok") return result;
      lastErr = result.error || lastErr;
    } catch (e) {
      lastErr = String(e.message || e);
    }
  }
  // Probe board page for login wall (only after all GraphQL attempts)
  try {
    const res = await fetch(BOARD, { credentials: "include", redirect: "follow" });
    const text = await res.text();
    const ct = res.headers.get("content-type") || "";
    if (isLoginResponse(res.status, ct, text, res.url || BOARD)) {
      sawLogin = true;
    }
  } catch (e) {
    return { status: "error", loads: [], error: String(e.message || e) };
  }
  if (sawLogin) {
    return { status: "needs_login", loads: [], error: "Arrive login required" };
  }
  return {
    status: "no_tab",
    loads: [],
    error: lastErr || "Open Arrive find-loads once so the extension can capture GraphQL",
  };
}
