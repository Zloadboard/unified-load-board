import { loadsFromArrivePayload, fromArriveApiItem } from "../brokers/arrive.js";
import { loadsFromSummaries, summaryToLoad } from "../brokers/arcbest.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// Arrive GraphQL shape
const gql = {
  data: {
    getLoads: {
      data: [
        {
          LoadBoardId: 12345,
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
      ],
    },
  },
};
const arriveLoads = loadsFromArrivePayload(gql);
assert(arriveLoads.length === 1, "arrive parse count");
assert(arriveLoads[0].source === "Arrive", "arrive source");
assert(arriveLoads[0].id === "12345", "arrive id");
assert(arriveLoads[0].origin.includes("Romeoville"), "arrive origin");

const bad = fromArriveApiItem({ LoadBoardId: 1, PickupEarlyCity: "", DeliveryLateCity: "" });
assert(bad === null, "arrive rejects incomplete");

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

console.log("arrive_arcbest_parse_test: all passed", arriveLoads.length, loads.map((L) => L.source).join(","));
