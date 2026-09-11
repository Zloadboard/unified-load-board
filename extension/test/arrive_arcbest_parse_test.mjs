import {
  loadsFromArrivePayload,
  fromArriveApiItem,
  fromArriveDomRow,
  loadsFromArriveDomRows,
  parseArriveStopBlob,
  filterRealArriveLoads,
  isProbeOrFakeArriveId,
} from "../brokers/arrive.js";
import { loadsFromSummaries, summaryToLoad } from "../brokers/arcbest.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// Arrive GraphQL shape (realistic getLoads)
const gql = {
  data: {
    getLoads: {
      data: [
        {
          LoadBoardId: 9564487,
          PickupEarlyCity: "Romeoville",
          PickupEarlyStateCode: "IL",
          DeliveryLateCity: "Atlanta",
          DeliveryLateStateCode: "GA",
          PickupApptEarliest: "2026-09-12T08:00:00Z",
          DeliveryApptEarliest: "2026-09-13T14:00:00Z",
          PickupLocationIANACode: "America/Chicago",
          DeliveryLocationIANACode: "America/New_York",
          Miles: 720,
          Weight: 42000,
          TopSpend: 1800,
          EquipmentType: "V",
          LoadStatus: "Available",
        },
        {
          LoadBoardId: 9564501,
          PickupEarlyCity: "Dallas",
          PickupEarlyStateCode: "TX",
          DeliveryLateCity: "Phoenix",
          DeliveryLateStateCode: "AZ",
          PickupApptEarliest: "2026-09-12T11:00:00Z",
          DeliveryApptEarliest: "2026-09-13T16:00:00Z",
          Miles: 887,
          Weight: 38000,
          TopSpend: 2100,
          EquipmentType: "VR",
          LoadStatus: "Available",
        },
      ],
    },
  },
};
const arriveLoads = loadsFromArrivePayload(gql);
assert(arriveLoads.length === 2, "arrive parse count " + arriveLoads.length);
assert(arriveLoads[0].source === "Arrive", "arrive source");
assert(arriveLoads[0].id === "9564487", "arrive id");
assert(arriveLoads[0].origin.includes("Romeoville"), "arrive origin");
assert(arriveLoads[0].url.includes("loadBoardId=9564487"), "arrive url");

const bad = fromArriveApiItem({ LoadBoardId: 1, PickupEarlyCity: "", DeliveryLateCity: "" });
assert(bad === null, "arrive rejects incomplete");

// Probe / fake ids must not look like success
assert(isProbeOrFakeArriveId("A-0"), "A-0 is probe");
assert(isProbeOrFakeArriveId("A-1"), "A-1 is probe");
assert(isProbeOrFakeArriveId("probe-xyz"), "probe- is fake");
assert(!isProbeOrFakeArriveId("9564487"), "real LoadBoardId ok");
const mixed = filterRealArriveLoads([
  { id: "A-0", source: "Arrive" },
  { id: "A-1", source: "Arrive" },
  { id: "9564487", source: "Arrive" },
  { id: "probe-1", source: "Arrive" },
]);
assert(mixed.length === 1 && mixed[0].id === "9564487", "filter probes");

// DOM load-row-* → minimal + enriched loads
const stopBlob = "Romeoville, IL\nFri\nSep 12\n08:00 CDT";
const parsed = parseArriveStopBlob(stopBlob);
assert(parsed.city.includes("Romeoville"), "stop city " + parsed.city);
assert(/Sep/.test(parsed.date), "stop date " + parsed.date);

const domRow = fromArriveDomRow({
  testId: "load-row-9564487",
  cells: [
    "Romeoville, IL\nFri Sep 12\n08:00 CDT",
    "Atlanta, GA\nSat Sep 13\n14:00 EDT",
    "",
    "720",
    "42,000",
    "V",
    "$1,800",
  ],
});
assert(domRow && domRow.id === "9564487", "dom id");
assert(domRow.source === "Arrive", "dom source");
assert(domRow.url.includes("loadBoardId=9564487"), "dom url");
assert(domRow.origin.includes("Romeoville"), "dom origin");

// Minimal: id-only from testid (table visible, cells sparse)
const minimal = fromArriveDomRow({ testId: "load-row-999001", cells: [] });
assert(minimal && minimal.id === "999001", "minimal dom id");
assert(minimal.url.includes("loadBoardId=999001"), "minimal url");

const many = loadsFromArriveDomRows([
  { testId: "load-row-111", cells: [] },
  { testId: "load-row-222", cells: [] },
  { testId: "load-row-A-0", cells: [] }, // non-numeric after load-row- → no match in fromArriveDomRow via testId regex \d+
  { loadId: "A-0", testId: "x", cells: [] },
]);
assert(many.length === 2, "dom rows count " + many.length);
assert(many.every((L) => /^\d+$/.test(L.id)), "dom ids numeric");

// ArcBest / MoLoTL → MoLo
const summaries = [
  {
    shipmentId: "S1",
    referenceNumber: "R1",
    shipmentType: "TL",
    shipperLocation: { city: "Chicago", state: "IL" },
    consigneeLocation: { city: "Dallas", state: "TX" },
    miles: 900,
    suggestedRate: 2100,
    equipmentTypes: ["Van"],
  },
  {
    shipmentId: "S2",
    referenceNumber: "R2",
    shipmentType: "MoLoTL",
    shipperLocation: { city: "Austin", state: "TX" },
    consigneeLocation: { city: "Phoenix", state: "AZ" },
    miles: 1000,
    weight: 35000,
  },
  {
    shipmentId: "S3",
    referenceNumber: "R3",
    shipmentType: "molo",
    shipperLocation: { city: "Denver", state: "CO" },
    consigneeLocation: { city: "Salt Lake City", state: "UT" },
  },
];
const loads = loadsFromSummaries(summaries);
assert(loads.length === 3, "arcbest count");
assert(loads[0].source === "ArcBest", "TL → ArcBest");
assert(loads[1].source === "MoLo", "MoLoTL → MoLo, got " + loads[1].source);
assert(loads[2].source === "MoLo", "molo → MoLo");

const one = summaryToLoad(summaries[1]);
assert(one.source === "MoLo" && one.id === "R2", "summaryToLoad MoLo");

console.log(
  "arrive_arcbest_parse_test: all passed",
  "gql=" + arriveLoads.length,
  "dom=" + many.length,
  loads.map((L) => L.source).join(",")
);
