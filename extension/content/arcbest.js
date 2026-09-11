/** ArcBest content script — read window.shipmentsListApp via page world. */
const BROKER = "ArcBest";

(function bridge() {
  function injectHook() {
    try {
      const s = document.createElement("script");
      s.src = chrome.runtime.getURL("content/injected_hook.js");
      s.onload = () => s.remove();
      (document.documentElement || document.head || document.body).appendChild(s);
    } catch (_) {}
  }
  injectHook();
  window.addEventListener("message", (ev) => {
    const d = ev.data;
    if (!d || d.source !== "ulb-extension-hook") return;
    try {
      chrome.runtime.sendMessage({
        type: "net_payload",
        broker: BROKER,
        url: d.url,
        method: d.method,
        body: d.body,
        requestBody: d.requestBody,
      });
    } catch (_) {}
  });
  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || msg.type !== "collect") return;
    Promise.resolve()
      .then(() => collect())
      .then((result) => sendResponse(result))
      .catch((e) => sendResponse({ status: "error", loads: [], error: String(e) }));
    return true;
  });
})();

function readVue() {
  return new Promise((resolve) => {
    const id = "ulb-arcbest-" + Math.random().toString(36).slice(2);
    function onMsg(ev) {
      if (!ev.data || ev.data.source !== "ulb-arcbest-vue" || ev.data.id !== id) return;
      window.removeEventListener("message", onMsg);
      resolve(ev.data.summaries || null);
    }
    window.addEventListener("message", onMsg);
    const script = document.createElement("script");
    script.textContent = `
      (function(){
        const id = ${JSON.stringify(id)};
        try {
          const app = window.shipmentsListApp || null;
          let list = app && (app.shipmentSummaries || (app.$data && app.$data.shipmentSummaries));
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
                source: s.source,
                status: s.status,
                partial: s.partial,
                preferred: s.preferred,
                suggestedRate: s.suggestedRate,
                currentOfferAmount: s.currentOfferAmount,
                weight: s.weight,
                miles: s.miles,
                equipmentTypes: s.equipmentTypes,
                pickupStartDateTime: s.pickupStartDateTime,
                pickupTimeZone: s.pickupTimeZone,
                deliveryStartDateTime: s.deliveryStartDateTime,
                deliveryTimeZone: s.deliveryTimeZone,
                shipperLocation: { city: ship.city || null, state: ship.state || null },
                consigneeLocation: { city: cons.city || null, state: cons.state || null }
              });
            }
          }
          window.postMessage({ source: "ulb-arcbest-vue", id, summaries: out }, "*");
        } catch (e) {
          window.postMessage({ source: "ulb-arcbest-vue", id, summaries: null, error: String(e) }, "*");
        }
      })();`;
    (document.documentElement || document.head).appendChild(script);
    script.remove();
    setTimeout(() => {
      window.removeEventListener("message", onMsg);
      resolve(null);
    }, 2000);
  });
}

async function collect() {
  const url = (location.href || "").toLowerCase();
  if (url.includes("auth0.com") || url.includes("login") || url.includes("signin")) {
    return { status: "needs_login", loads: [], error: "ArcBest login required", broker: BROKER };
  }
  const summaries = await readVue();
  if (summaries && summaries.length) {
    return { status: "ok", summaries, broker: BROKER, pageUrl: location.href };
  }
  const body = (document.body?.innerText || "").slice(0, 2000).toLowerCase();
  if (/sign\s*in|log\s*in|password/.test(body) && !/shipment/.test(body)) {
    return { status: "needs_login", loads: [], error: "ArcBest login required", broker: BROKER };
  }
  return {
    status: "empty",
    loads: [],
    error: "No Vue shipmentSummaries yet — open Shipments and wait",
    broker: BROKER,
  };
}
