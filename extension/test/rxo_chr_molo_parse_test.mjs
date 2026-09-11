import { loadsFromRxoPayload } from "../brokers/rxo.js";
import { loadsFromChrPayload } from "../brokers/chr.js";
import { summaryToLoad } from "../brokers/arcbest.js";
import { readFileSync } from "fs";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// --- RXO real loadboard shape (cityName/stateCode/zipCode) ---
const sample = JSON.parse(readFileSync("/workspace/uploads/rxo-loadboard-page1.json", "utf8"));
const rxo = loadsFromRxoPayload({
  availableLoads: { items: [sample.item0] },
});
assert(rxo.length === 1, "rxo count");
assert(rxo[0].id === "24000967", "rxo id number " + rxo[0].id);
assert(/PARCHMENT,\s*MI/i.test(rxo[0].origin), "rxo origin cityName " + rxo[0].origin);
assert(/Fridley,\s*MN/i.test(rxo[0].destination), "rxo dest cityName " + rxo[0].destination);
assert(/\/loads\/24000967/.test(rxo[0].url), "rxo deep link " + rxo[0].url);

const junk = loadsFromRxoPayload({
  availableLoads: {
    items: [
      { id: 1, number: 1 },
      { id: 2, number: 2 },
      { number: 3, origin: {}, destination: {} },
    ],
  },
});
assert(junk.length === 0, "rxo drops index stubs");

// --- CHR city + sibling state ---
const chr = loadsFromChrPayload({
  loads: [
    {
      loadNumber: "99112233",
      originCity: "Ladson",
      originState: "SC",
      destinationCity: "ITASCA",
      destinationState: "IL",
      miles: 900,
      rate: 2100,
    },
    {
      // city-only (no state) — still accepted but no deep link without id
      origin: "CHICAGO",
      destination: "MENOMONIE",
    },
    {
      LoadId: "445566",
      origin: { cityName: "Hodgkins", stateCode: "IL", zipCode: "60525" },
      destination: { city: "CORNELL", state: "WI" },
    },
  ],
});
assert(chr.length >= 2, "chr count " + chr.length);
const c0 = chr.find((l) => l.id === "99112233");
assert(c0, "chr loadNumber id");
assert(/Ladson,\s*SC/i.test(c0.origin), "chr origin+state " + c0.origin);
assert(/ITASCA,\s*IL/i.test(c0.destination), "chr dest+state " + c0.destination);
assert(/loadId=99112233/.test(c0.url), "chr deep link " + c0.url);
assert(c0.url.includes("navispherecarrier.com") && c0.url.includes("loadId="), "chr url has loadId");
assert(!/^https:\/\/www\.navispherecarrier\.com\/?$/i.test(c0.url.replace(/\/$/, "")), "chr not bare homepage");

const c2 = chr.find((l) => l.id === "445566");
assert(c2, "chr LoadId");
assert(/Hodgkins,\s*IL/i.test(c2.origin), "chr nested cityName");
assert(/CORNELL,\s*WI/i.test(c2.destination), "chr nested city/state");

// --- MoLo: Load # = referenceNumber in URL ---
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
  status: "Available",
});
assert(molo.source === "MoLo", "molo source");
assert(molo.id === "2002760136", "molo id is referenceNumber");
assert(/referenceNumber=2002760136/.test(molo.url), "molo url prefers referenceNumber " + molo.url);
assert(/shipmentId=4011561/.test(molo.url), "molo url keeps shipmentId too");

console.log("rxo_chr_molo_parse_test OK");
