/** ArcBest / MoLo — prefer Vue shipmentSummaries; map like scanner/sources/arcbest.py. */
import { normalizeLoad, isLoginResponse, BROKER_URLS } from "../lib/normalize.js";

const SOURCE = "ArcBest";
const SOURCE_MOLO = "MoLo";
const BOARD = BROKER_URLS.ArcBest;

function isMolo(st) {
  return ["molotl", "molo"].includes(String(st || "").trim().toLowerCase());
}

function locCity(loc) {
  if (!loc || typeof loc !== "object") return "";
  const city = String(loc.city || "").trim();
  const state = String(loc.state || "").trim();
  if (city && state) return `${city}, ${state}`;
  return city || state;
}

function fmtCardDt(iso, tz) {
  if (!iso) return ["", "", ""];
  const s = String(iso).trim();
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})[T\s]+(\d{1,2}:\d{2})/);
  if (m) {
    const dateMdy = `${m[2]}-${m[3]}-${m[1]}`;
    const tzS = String(tz || "").trim();
    const timePart = tzS ? `${m[4]} (${tzS})` : m[4];
    return [dateMdy, timePart, `${dateMdy} ${timePart}`.trim()];
  }
  m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) {
    const dateMdy = `${m[2]}-${m[3]}-${m[1]}`;
    return [dateMdy, "", dateMdy];
  }
  return [s, "", s];
}

function loadId(summary) {
  const ref = summary.referenceNumber;
  if (ref != null && String(ref).trim()) return String(ref).trim();
  const sid = summary.shipmentId;
  if (sid != null && String(sid).trim()) return String(sid).trim();
  return "";
}

export function summaryToLoad(s) {
  if (!s || typeof s !== "object") return null;
  const origin = locCity(s.shipperLocation);
  const dest = locCity(s.consigneeLocation);
  if (!origin || !dest) return null;
  const lid = loadId(s);
  if (!lid) return null;
  const [puD, puT, puComb] = fmtCardDt(s.pickupStartDateTime, s.pickupTimeZone);
  const [deD, deT, deComb] = fmtCardDt(s.deliveryStartDateTime, s.deliveryTimeZone);
  let equip = "";
  if (Array.isArray(s.equipmentTypes)) equip = s.equipmentTypes.filter(Boolean).join(", ");
  else equip = String(s.equipmentTypes || "");
  let weight = s.weight;
  if (weight != null && weight !== "") {
    try { weight = Number(weight).toLocaleString("en-US"); } catch { weight = String(weight); }
  }
  let miles = s.miles;
  try { miles = miles != null && miles !== "" ? Number(miles) : null; } catch { miles = null; }
  let rate = s.suggestedRate ?? s.currentOfferAmount;
  try { rate = rate != null && rate !== "" ? Number(rate) : null; } catch { rate = null; }
  const st = String(s.shipmentType || "");
  const src = isMolo(st) ? SOURCE_MOLO : SOURCE;
  const sid = s.shipmentId != null ? String(s.shipmentId).trim() : "";
  let detailUrl = BOARD;
  if (sid && /^[\w-]+$/.test(sid)) detailUrl = `https://carriers.arcb.com/Shipments?shipmentId=${sid}`;
  else if (/^[\w-]+$/.test(lid)) detailUrl = `https://carriers.arcb.com/Shipments?referenceNumber=${lid}`;
  const raw = {
    id: lid,
    origin,
    destination: dest,
    pickupCity: origin,
    deliveryCity: dest,
    pickupDate: puD,
    pickupTime: puT,
    deliveryDate: deD,
    deliveryTime: deT,
    pickup: puComb,
    delivery: deComb,
    equipment: equip,
    weight: weight || "",
    miles,
    rate,
    status: [st.toLowerCase() === "expedited" ? "EXP" : "TL", s.partial ? "Partial" : "Full", s.status || ""]
      .filter(Boolean)
      .join(" "),
    url: detailUrl,
    notes: [
      s.shipmentId != null ? `shipmentId=${s.shipmentId}` : "",
      s.referenceNumber ? `ref=${s.referenceNumber}` : "",
      st ? `type=${st}` : "",
    ]
      .filter(Boolean)
      .join(" | "),
  };
  try {
    const L = normalizeLoad(raw, src, BOARD);
    L.id = lid;
    return L;
  } catch {
    return null;
  }
}

export function loadsFromSummaries(summaries) {
  const seen = new Set();
  const out = [];
  for (const s of summaries || []) {
    const L = summaryToLoad(s);
    if (!L) continue;
    const k = String(L.id || "");
    if (!k || seen.has(k)) continue;
    seen.add(k);
    out.push(L);
  }
  return out;
}

export function loadsFromArcbestPayload(body) {
  // Some portals expose shipment summaries via XHR
  const rows = [];
  function walk(o, d = 0) {
    if (d > 8 || o == null) return;
    if (Array.isArray(o)) {
      if (o[0] && typeof o[0] === "object" && ("referenceNumber" in o[0] || "shipmentId" in o[0])) {
        rows.push(...o);
        return;
      }
      for (const x of o.slice(0, 200)) walk(x, d + 1);
      return;
    }
    if (typeof o === "object") {
      if ("referenceNumber" in o || "shipmentId" in o) {
        if (o.shipperLocation || o.consigneeLocation) rows.push(o);
      }
      for (const v of Object.values(o)) walk(v, d + 1);
    }
  }
  walk(body);
  return loadsFromSummaries(rows);
}

export async function fetchArcbest(/* opts */) {
  // Cookie session cannot read Vue state from background — need content script / open tab.
  try {
    const res = await fetch(BOARD, { credentials: "include", redirect: "follow" });
    const text = await res.text();
    const ct = res.headers.get("content-type") || "";
    if (isLoginResponse(res.status, ct, text, res.url || BOARD) || /auth0\.com|sign\s*in/i.test(res.url + text.slice(0, 1500))) {
      return { status: "needs_login", loads: [], error: "ArcBest login required" };
    }
  } catch (e) {
    return { status: "error", loads: [], error: String(e.message || e) };
  }
  return {
    status: "no_tab",
    loads: [],
    error: "Open ArcBest Shipments tab — extension reads Vue shipmentSummaries",
  };
}
