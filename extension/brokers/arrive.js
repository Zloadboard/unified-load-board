/** Arrive — GraphQL getLoads / LoadBoardId + DOM load-row-* mapping. */
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

/** Fake / probe ids that must never count as Arrive success. */
export function isProbeOrFakeArriveId(id) {
  const s = String(id || "").trim();
  if (!s) return true;
  if (/^A-\d+$/i.test(s)) return true;
  if (/^probe[-_]/i.test(s)) return true;
  if (/^ARR-0$/i.test(s)) return true;
  // Pure hash synthetics with empty cities (ARR-<digits> from empty origin|dest)
  // Keep numeric LoadBoardIds and ARR-City-... last resorts from real DOM.
  return false;
}

export function filterRealArriveLoads(loads) {
  return (loads || []).filter((L) => L && !isProbeOrFakeArriveId(L.id));
}

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
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!m) return ["", ""];
    const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]));
    const dow = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][dt.getUTCDay()];
    const mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][dt.getUTCMonth()];
    const day = dt.getUTCDate();
    const tod = `${String(dt.getUTCHours()).padStart(2, "0")}:${String(dt.getUTCMinutes()).padStart(2, "0")}`;
    let tz = "";
    if (iana) {
      try {
        tz =
          new Intl.DateTimeFormat("en-US", { timeZone: String(iana), timeZoneName: "short" })
            .formatToParts(new Date())
            .find((p) => p.type === "timeZoneName")?.value || "";
      } catch {
        /* ignore */
      }
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

/** Parse Arrive multi-line stop cell → { city, date, time }. */
export function parseArriveStopBlob(blob) {
  const out = { city: "", date: "", time: "" };
  if (!blob || typeof blob !== "string") return out;
  const text = blob.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  let lines = text
    .split("\n")
    .map((ln) => ln.trim())
    .filter(Boolean);
  if (lines.length === 1 && (/\|/.test(lines[0]) || /\s{2,}/.test(lines[0]))) {
    lines = lines[0]
      .split(/\s*\|\s*|\s{2,}/)
      .map((p) => p.trim())
      .filter(Boolean);
  }
  const cityRe = /\b([A-Za-z][A-Za-z .'-]+,\s*[A-Z]{2})\b/;
  for (const ln of lines) {
    if (/\(\s*\d+\s*mi/i.test(ln)) continue;
    const m = ln.match(cityRe);
    if (m) {
      out.city = m[1].trim();
      break;
    }
  }
  if (!out.city) {
    const m = text.replace(/\n/g, " ").match(cityRe);
    if (m) out.city = m[1].trim();
  }
  const dows = "Sun|Mon|Tue|Wed|Thu|Fri|Sat";
  const months = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";
  const fullDate = new RegExp(`\\b((?:${dows})\\s+(?:${months})\\s+\\d{1,2})\\b`, "i");
  const collapsed = text.replace(/\n/g, " ");
  const fd = collapsed.match(fullDate);
  if (fd) {
    const parts = fd[1].split(/\s+/);
    out.date = `${parts[0].slice(0, 3)} ${parts[1].slice(0, 1).toUpperCase()}${parts[1].slice(1, 3).toLowerCase()} ${parseInt(parts[2], 10)}`;
  } else {
    for (let i = 0; i < lines.length; i++) {
      const ln = lines[i];
      if (/^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)\b/i.test(ln) && i + 1 < lines.length) {
        const nxt = lines[i + 1];
        const mm = nxt.match(new RegExp(`^(${months})\\s+(\\d{1,2})`, "i"));
        if (mm) {
          out.date = `${ln.slice(0, 3)} ${mm[1].slice(0, 1).toUpperCase()}${mm[1].slice(1, 3).toLowerCase()} ${parseInt(mm[2], 10)}`;
          break;
        }
      }
    }
  }
  const timeRe = /\b(\d{1,2}:\d{2})\s*([A-Z]{2,4})?\b/;
  for (const ln of lines) {
    if (cityRe.test(ln) || /\(\s*\d+\s*mi/i.test(ln)) continue;
    const tm = ln.match(timeRe);
    if (tm) {
      out.time = `${tm[1]}${tm[2] ? " " + tm[2] : ""}`;
      break;
    }
  }
  return out;
}

export function fromArriveApiItem(item, { allowMinimal = false } = {}) {
  if (!item || typeof item !== "object") return null;
  const lid = item.LoadBoardId ?? item.loadBoardId ?? item.loadId ?? item.id;
  if (lid == null || lid === "") return null;
  const lidS = String(lid).trim();
  if (isProbeOrFakeArriveId(lidS)) return null;
  const origin = citySt(item.PickupEarlyCity, item.PickupEarlyStateCode);
  const destination = citySt(item.DeliveryLateCity, item.DeliveryLateStateCode);
  if (!allowMinimal && (!origin || !destination)) return null;
  if (allowMinimal && !origin && !destination && !/^\d+$/.test(lidS)) return null;
  const [puDate, puTime] = arriveLocalParts(
    item.PickupApptEarliest || item.PickupApptLatest,
    item.PickupLocationIANACode
  );
  const [deDate, deTime] = arriveLocalParts(
    item.DeliveryApptEarliest || item.DeliveryApptLatest,
    item.DeliveryLocationIANACode
  );
  let miles = item.Miles;
  try {
    miles = miles != null ? Number(miles) : null;
  } catch {
    miles = null;
  }
  let weight = item.Weight;
  try {
    weight = weight != null ? Math.round(Number(weight)) : "";
  } catch {
    /* keep */
  }
  let rate = item.TopSpend;
  try {
    rate = rate != null ? Number(rate) : null;
  } catch {
    rate = null;
  }
  const raw = {
    id: lidS,
    origin: origin || "",
    destination: destination || "",
    pickupCity: origin || "",
    deliveryCity: destination || "",
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

/**
 * Build a load from a DOM row: data-testid=load-row-{LoadBoardId} + td cells.
 * Minimal: numeric id alone is enough (enrich via GraphQL when available).
 */
export function fromArriveDomRow(row) {
  if (!row || typeof row !== "object") return null;
  let lid = row.loadId || row.loadBoardId || row.LoadBoardId || null;
  const tid = String(row.testId || row.testid || "");
  if (!lid && tid) {
    const m = tid.match(/load-row-(\d+)/i);
    if (m) lid = m[1];
  }
  if (lid == null) return null;
  const lidS = String(lid).trim();
  if (!/^\d+$/.test(lidS) || isProbeOrFakeArriveId(lidS)) return null;

  const cells = Array.isArray(row.cells) ? row.cells : [];
  const pu = parseArriveStopBlob(cells[0] || "");
  const de = parseArriveStopBlob(cells[1] || "");
  let miles = null;
  let weight = "";
  let eq = "";
  let rate = null;
  if (cells.length > 3 && /^[\d,]+$/.test(String(cells[3]).replace(/,/g, ""))) {
    miles = Number(String(cells[3]).replace(/,/g, ""));
  }
  if (cells.length > 4) {
    const wm = String(cells[4]).replace(/,/g, "").match(/([\d.]+)/);
    if (wm) weight = Math.round(Number(wm[1]));
  }
  if (cells.length > 5) eq = equip(cells[5]);
  if (cells.length > 6) {
    const rm = String(cells[6]).replace(/[$,]/g, "").match(/([\d.]+)/);
    if (rm) rate = Number(rm[1]);
  }

  const raw = {
    id: lidS,
    origin: pu.city || "",
    destination: de.city || "",
    pickupCity: pu.city || "",
    deliveryCity: de.city || "",
    pickupDate: pu.date || "",
    pickupTime: pu.time || "",
    deliveryDate: de.date || "",
    deliveryTime: de.time || "",
    pickup: `${pu.date || ""} ${pu.time || ""}`.trim(),
    delivery: `${de.date || ""} ${de.time || ""}`.trim(),
    miles,
    weight,
    equipment: eq,
    rate,
    url: `https://carrier.arrivelogistics.com/find-loads?loadBoardId=${lidS}`,
    status: "",
  };
  try {
    return normalizeLoad(raw, SOURCE, BOARD);
  } catch {
    return null;
  }
}

export function loadsFromArriveDomRows(rows) {
  const seen = new Set();
  const out = [];
  for (const row of rows || []) {
    const n = fromArriveDomRow(row);
    if (!n) continue;
    if (seen.has(n.id)) continue;
    seen.add(n.id);
    out.push(n);
  }
  return out;
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
    const n = fromArriveApiItem(row, { allowMinimal: false });
    if (!n) continue;
    if (isProbeOrFakeArriveId(n.id)) continue;
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
  const endpoints = [...(opts.discoveredEndpoints?.Arrive || []), ...DEFAULT_GQL_URLS];
  const seen = new Set();
  const bodies = opts.lastRequestBodies?.Arrive || [];
  let sawLogin = false;
  let lastErr = "";
  for (const url of endpoints) {
    if (!url || seen.has(url)) continue;
    seen.add(url);
    try {
      const matchingBody = bodies.find((b) => (b.url || "").includes(new URL(url).host));
      const result = await tryGraphql(url, matchingBody?.bodyText);
      if (result.status === "needs_login") {
        sawLogin = true;
        lastErr = result.error || lastErr;
        continue;
      }
      if (result.loads.length) return result;
      if (result.status === "ok") return result;
      lastErr = result.error || lastErr;
    } catch (e) {
      lastErr = String(e.message || e);
    }
  }
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
    error: lastErr || "Open Arrive find-loads, run Search, then Scan now",
  };
}

export { GET_LOADS_QUERY, DEFAULT_GQL_URLS, BOARD as ARRIVE_BOARD };
