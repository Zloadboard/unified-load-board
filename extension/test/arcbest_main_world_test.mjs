/** Mirrors background readArcbestMainWorld func against a fake window. */
function mainWorldRead(fakeWindow) {
  const app = fakeWindow.shipmentsListApp || null;
  const list =
    (app && (app.shipmentSummaries || (app.$data && app.$data.shipmentSummaries))) || null;
  const out = [];
  if (list && list.length) {
    for (let i = 0; i < list.length; i++) {
      const s = list[i];
      if (!s) continue;
      const ship = s.shipperLocation || {};
      const cons = s.consigneeLocation || {};
      out.push({
        shipmentId: s.shipmentId,
        referenceNumber: s.referenceNumber,
        shipmentType: s.shipmentType,
        suggestedRate: s.suggestedRate,
        weight: s.weight,
        miles: s.miles,
        equipmentTypes: s.equipmentTypes,
        pickupStartDateTime: s.pickupStartDateTime,
        pickupTimeZone: s.pickupTimeZone,
        deliveryStartDateTime: s.deliveryStartDateTime,
        deliveryTimeZone: s.deliveryTimeZone,
        shipperLocation: { city: ship.city || null, state: ship.state || null },
        consigneeLocation: { city: cons.city || null, state: cons.state || null },
      });
    }
  }
  return { summaries: out, hasApp: !!app };
}

const fake = {
  shipmentsListApp: {
    shipmentSummaries: [
      {
        shipmentId: "S1",
        referenceNumber: "R1",
        shipmentType: "TL",
        suggestedRate: 1200,
        weight: 40000,
        miles: 500,
        equipmentTypes: ["Van"],
        pickupStartDateTime: "2026-09-12T08:00",
        pickupTimeZone: "CT",
        deliveryStartDateTime: "2026-09-13T08:00",
        deliveryTimeZone: "ET",
        shipperLocation: { city: "Chicago", state: "IL" },
        consigneeLocation: { city: "Atlanta", state: "GA" },
      },
      {
        shipmentId: "S2",
        referenceNumber: "R2",
        shipmentType: "MoLoTL",
        shipperLocation: { city: "Dallas", state: "TX" },
        consigneeLocation: { city: "Houston", state: "TX" },
      },
    ],
  },
};

const r = mainWorldRead(fake);
if (r.summaries.length !== 2) throw new Error("expected 2 summaries");
if (r.summaries[0].shipperLocation.city !== "Chicago") throw new Error("city");
if (!r.hasApp) throw new Error("hasApp");
console.log("arcbest_main_world_test: all passed", r.summaries.length);
