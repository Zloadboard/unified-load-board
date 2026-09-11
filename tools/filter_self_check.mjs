/** Self-check: dest multi-state filter + loadDetailUrl against sample loads. */
import { readFileSync } from "fs";
import { summaryToLoad } from "../extension/brokers/arcbest.js";
import { loadsFromRxoPayload } from "../extension/brokers/rxo.js";
import { loadsFromChrPayload } from "../extension/brokers/chr.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

const US_STATE_CODES = {
  AL:1,AK:1,AZ:1,AR:1,CA:1,CO:1,CT:1,DE:1,FL:1,GA:1,HI:1,ID:1,IL:1,IN:1,IA:1,KS:1,
  KY:1,LA:1,ME:1,MD:1,MA:1,MI:1,MN:1,MS:1,MO:1,MT:1,NE:1,NV:1,NH:1,NJ:1,NM:1,NY:1,
  NC:1,ND:1,OH:1,OK:1,OR:1,PA:1,RI:1,SC:1,SD:1,TN:1,TX:1,UT:1,VT:1,VA:1,WA:1,WV:1,
  WI:1,WY:1,DC:1
};

function parseDestStateList(destQ) {
  const raw = String(destQ || "").trim();
  if (!raw) return null;
  if (/,/.test(raw) && /[A-Za-z]{3,}/.test(raw)) return null;
  const parts = raw.split(/[,\/|\s]+/).map((p) => p.trim()).filter(Boolean);
  if (!parts.length) return null;
  const codes = [];
  for (const p of parts) {
    if (!/^[A-Za-z]{2}$/.test(p)) return null;
    const up = p.toUpperCase();
    if (!US_STATE_CODES[up]) return null;
    if (codes.indexOf(up) < 0) codes.push(up);
  }
  return codes.length ? codes : null;
}

function parseDeliveryState(load) {
  const hay = String(
    (load && (load.delivery_city || load.destination || load.delivery || "")) || ""
  ).replace(/\s+/g, " ").trim();
  if (!hay) return "";
  let m = hay.match(/,\s*([A-Za-z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$/i);
  if (m && US_STATE_CODES[m[1].toUpperCase()]) return m[1].toUpperCase();
  m = hay.match(/^(.+?)\s+([A-Za-z]{2})$/);
  if (m && US_STATE_CODES[m[2].toUpperCase()] && m[1].length >= 2) return m[2].toUpperCase();
  m = hay.match(/^([A-Za-z]{2})(?:\s+\d{5}(?:-\d{4})?)?\s*$/);
  if (m && US_STATE_CODES[m[1].toUpperCase()]) return m[1].toUpperCase();
  m = hay.match(/\b([A-Za-z]{2})\s+\d{5}(?:-\d{4})?\b/);
  if (m && US_STATE_CODES[m[1].toUpperCase()]) return m[1].toUpperCase();
  m = hay.match(/\b([A-Za-z]{2})\s*$/);
  if (m && US_STATE_CODES[m[1].toUpperCase()]) return m[1].toUpperCase();
  return "";
}

function filterByDestStates(loads, destQ) {
  const destStates = parseDestStateList(destQ);
  if (!destStates) throw new Error("not a state list: " + destQ);
  const want = Object.fromEntries(destStates.map((s) => [s, true]));
  return loads.filter((l) => {
    const st = parseDeliveryState(l);
    if (st) return !!want[st];
    const hay = String(l.delivery_city || l.destination || "").trim();
    if (!hay) return false;
    return destStates.some((s) => new RegExp("\\b" + s + "\\b", "i").test(hay));
  });
}

const BROKER_BOARD_URLS = {
  Arrive: "https://carrier.arrivelogistics.com/find-loads",
  RXO: "https://carrier.rxoconnect.rxo.com/loads/available-loads",
  ArcBest: "https://carriers.arcb.com/Shipments",
  MoLo: "https://carriers.arcb.com/Shipments",
  Echo: "https://echodrive.echo.com/carrier/10261/availableLoads",
  CHR: "https://www.navispherecarrier.com/",
};

function isUsefulLoadUrl(u, id) {
  if (!u || !/^https?:\/\//i.test(u)) return false;
  const bare = u.replace(/\/$/, "");
  const boards = Object.values(BROKER_BOARD_URLS).map((x) => String(x).replace(/\/$/, ""));
  if (boards.includes(bare)) return false;
  if (/rxoconnect\.rxo\.com\/loads\/\d{1,2}\/?$/i.test(bare)) return false;
  const idStr = String(id || "");
  if (idStr && /^\d{1,2}$/.test(idStr) && /rxoconnect\.rxo\.com\/loads\//i.test(u)) return false;
  if (idStr && u.indexOf(idStr) >= 0) return true;
  if (/[?&#](loadId|loadNumber|loadBoardId|shipmentId|referenceNumber)=/i.test(u)) return true;
  if (/\/(loads|availableLoads|Shipments|find-loads)\/[^/?#]+/i.test(u)) return true;
  return true;
}

function isSyntheticLoadId(id) {
  const s = String(id || "").trim();
  if (!s) return true;
  if (/^\d+$/.test(s)) return false;
  if (/^\d+-\d+$/.test(s)) return false;
  if (/^[A-Za-z0-9_-]+$/.test(s) && !/^(ARR|ARC|ECHO|CHR|EXAMPLE)-/i.test(s) && s.indexOf(",") < 0) return false;
  return /^(ARR-|ARC-|ECHO-|CHR-|EXAMPLE-)/i.test(s) || s.indexOf(",") >= 0;
}

function loadDetailUrl(load) {
  const id = String((load && load.id) || "").trim();
  const src = String((load && load.source) || "").trim();
  const raw = String((load && load.url) || "").trim();
  const board = BROKER_BOARD_URLS[src] || "";
  const enc = encodeURIComponent(id);
  if (src === "RXO" && (/^\d{1,2}$/.test(id) || /rxoconnect\.rxo\.com\/loads\/\d{1,2}\/?$/i.test(raw))) {
    return board || "";
  }
  if ((src === "ArcBest" || src === "MoLo") && id && !isSyntheticLoadId(id)) {
    let u = "https://carriers.arcb.com/Shipments?referenceNumber=" + enc;
    const sm = raw.match(/[?&#]shipmentId=([^&#]+)/i);
    if (sm && sm[1] && decodeURIComponent(sm[1]) !== id) {
      u += "&shipmentId=" + encodeURIComponent(sm[1]);
    }
    return u;
  }
  if (isUsefulLoadUrl(raw, id)) return raw;
  if (isSyntheticLoadId(id)) return board || raw || "";
  if (src === "Arrive") return "https://carrier.arrivelogistics.com/find-loads?loadBoardId=" + enc;
  if (src === "RXO") {
    if (/^\d{1,2}$/.test(id)) return board || raw || "";
    return "https://carrier.rxoconnect.rxo.com/loads/" + enc;
  }
  if (src === "Echo") return "https://echodrive.echo.com/v2/carrier/10261/availableLoads?loadId=" + enc;
  if (src === "CHR") return "https://www.navispherecarrier.com/find-loads?loadId=" + enc;
  return board || raw || "";
}

// Sample loads across sources
const sample = JSON.parse(readFileSync("/workspace/uploads/rxo-loadboard-page1.json", "utf8"));
const rxoLoads = loadsFromRxoPayload({ availableLoads: { items: [sample.item0] } });
const chrLoads = loadsFromChrPayload({
  loads: [
    { loadNumber: "99112233", originCity: "Ladson", originState: "SC", destinationCity: "ITASCA", destinationState: "IL" },
    { loadNumber: "8877", originCity: "Chicago", originState: "IL", destinationCity: "Charlotte", destinationState: "NC" },
    { loadNumber: "7766", originCity: "Atlanta", originState: "GA", destinationCity: "Columbia", destinationState: "SC" },
  ],
});
const molo = summaryToLoad({
  referenceNumber: "2002760136",
  shipmentId: 4011561,
  shipmentType: "MoLoTL",
  shipperLocation: { city: "Chicago", state: "IL" },
  consigneeLocation: { city: "Appleton", state: "WI" },
  pickupStartDateTime: "2026-09-12T08:00:00",
  deliveryStartDateTime: "2026-09-13T14:00:00",
  miles: 180,
  suggestedRate: 650,
  equipmentTypes: ["Van"],
});
const loads = [
  ...rxoLoads,
  ...chrLoads,
  molo,
  { id: "69052599", source: "Echo", destination: "LANCASTER, NY 14086", delivery_city: "LANCASTER, NY 14086", url: "https://echodrive.echo.com/v2/carrier/10261/availableLoads?loadId=69052599" },
  { id: "69043869", source: "Echo", destination: "NASHVILLE, TN 37207", delivery_city: "NASHVILLE, TN 37207", url: "https://echodrive.echo.com/v2/carrier/10261/availableLoads?loadId=69043869" },
  { id: "9590664", source: "Arrive", destination: "Atlanta, GA", delivery_city: "Atlanta, GA", url: "https://carrier.arrivelogistics.com/find-loads?loadBoardId=9590664" },
  { id: "4011740", source: "ArcBest", destination: "Maxton, NC", delivery_city: "Maxton, NC", url: "https://carriers.arcb.com/Shipments?shipmentId=4011740" },
  // city-only CHR leftover — must NOT match SC,NC,GA via false positive
  { id: "CHR-CHICAGO-MENOMONIE", source: "CHR", destination: "MENOMONIE", delivery_city: "MENOMONIE", url: "https://www.navispherecarrier.com/" },
];

assert(parseDeliveryState({ destination: "LANCASTER, NY 14086" }) === "NY", "echo NY");
assert(parseDeliveryState({ destination: "Fridley, MN 55432" }) === "MN", "rxo MN");
assert(parseDeliveryState({ destination: "ITASCA, IL" }) === "IL", "chr IL");
assert(parseDeliveryState({ destination: "ITASCA IL" }) === "IL", "no-comma IL");
assert(parseDeliveryState({ destination: "MENOMONIE" }) === "", "city-only no state");

const multi = filterByDestStates(loads, "SC,NC,GA");
const bySrc = {};
for (const l of multi) bySrc[l.source] = (bySrc[l.source] || 0) + 1;
console.log("SC,NC,GA matches:", multi.map((l) => [l.source, l.id, l.destination || l.delivery_city]));
assert(multi.some((l) => l.source === "Arrive" && /GA/i.test(l.destination)), "Arrive GA kept");
assert(multi.some((l) => l.source === "CHR" && /SC|NC/i.test(l.destination)), "CHR SC/NC kept");
assert(multi.some((l) => l.source === "ArcBest" && /NC/i.test(l.destination)), "ArcBest NC kept");
assert(!multi.some((l) => l.id === "CHR-CHICAGO-MENOMONIE"), "city-only CHR not false-matched");
assert(!multi.some((l) => l.source === "RXO"), "RXO MN not in SC,NC,GA");
assert(!multi.some((l) => l.source === "Echo" && /NY/i.test(l.destination)), "Echo NY not matched");
// No whole-source wipe of Arrive just because MoLo is big — Arrive present when GA matches
assert(bySrc.Arrive > 0, "Arrive not wiped");

// Deep links
for (const l of loads) {
  const href = loadDetailUrl(l);
  const board = (BROKER_BOARD_URLS[l.source] || "").replace(/\/$/, "");
  if (/^\d{5,}$/.test(String(l.id)) || /^\d+-\d+$/.test(String(l.id)) || /^200\d+/.test(String(l.id))) {
    assert(href && href.replace(/\/$/, "") !== board, `deep link not bare for ${l.source} ${l.id}: ${href}`);
    assert(!/\/loads\/[1-9]$/.test(href), "not index url " + href);
  }
  if (l.source === "MoLo") {
    assert(/referenceNumber=2002760136/.test(href), "molo detail " + href);
  }
  if (l.source === "RXO") {
    assert(/\/loads\/24000967/.test(href), "rxo detail " + href);
  }
  if (l.source === "Echo") {
    assert(/loadId=/.test(href), "echo detail " + href);
  }
}
// Index RXO ids must not invent /loads/1
const badRxo = loadDetailUrl({ id: "1", source: "RXO", url: "https://carrier.rxoconnect.rxo.com/loads/1", destination: "" });
assert(!/\/loads\/1\/?$/.test(badRxo), "index id blocked: " + badRxo);
assert(/available-loads/i.test(badRxo) || badRxo === "" || /rxoconnect/.test(badRxo), "falls back board: " + badRxo);

console.log("FILTER_SELF_CHECK_OK");
console.log(JSON.stringify({ multiCount: multi.length, bySrc }, null, 2));
