/** Mirrors background readArcbestMainWorld discovery against fake windows. */
function listFromApp(app) {
  if (!app || typeof app !== "object") return null;
  return (
    app.shipmentSummaries ||
    (app.$data && app.$data.shipmentSummaries) ||
    (app._data && app._data.shipmentSummaries) ||
    null
  );
}

function discover(fakeWindow) {
  let appName = null;
  let app = fakeWindow.shipmentsListApp || null;
  let list = listFromApp(app);
  if (app) appName = "shipmentsListApp";
  if (!list || !list.length) {
    for (const k of Object.keys(fakeWindow)) {
      const v = fakeWindow[k];
      const cand = listFromApp(v);
      if (
        Array.isArray(cand) &&
        cand.length &&
        cand[0] &&
        typeof cand[0] === "object" &&
        ("shipmentId" in cand[0] || "referenceNumber" in cand[0])
      ) {
        app = v;
        list = cand;
        appName = k;
        break;
      }
    }
  }
  return { list: list || [], appName, hasApp: !!(app || (list && list.length)) };
}

const sample = [
  {
    shipmentId: "S1",
    referenceNumber: "R1",
    shipmentType: "TL",
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
];

let r = discover({ shipmentsListApp: { shipmentSummaries: sample } });
if (r.list.length !== 2 || r.appName !== "shipmentsListApp") throw new Error("named app fail");

r = discover({ arcBestShipmentsRoot: { $data: { shipmentSummaries: sample } } });
if (r.list.length !== 2 || r.appName !== "arcBestShipmentsRoot") throw new Error("discover fail");

console.log("arcbest_main_world_test: all passed", r.list.length, r.appName);
