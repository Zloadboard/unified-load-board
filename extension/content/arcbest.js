/** ArcBest content script — network hook + soft collect.
 *  Vue shipmentSummaries are read from the service worker via
 *  chrome.scripting.executeScript({ world: 'MAIN' }) — CSP blocks inline script.textContent.
 */
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
        requestHeaders: d.requestHeaders || null,
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

function collect() {
  const url = location.href || "";
  const low = url.toLowerCase();
  // Only hard needs_login on clear auth hosts/paths
  if (
    low.includes("auth0.com") ||
    /\/u\/login|\/signin|\/login(\?|$)/.test(low) ||
    (low.includes("login") && !low.includes("shipments"))
  ) {
    // Still allow Shipments board URLs that happen to mention login in query
    if (!/\/shipments/i.test(low)) {
      return { status: "needs_login", loads: [], error: "ArcBest login required", broker: BROKER, pageUrl: url };
    }
  }
  // Soft check: login form visible without shipment UI
  const body = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
  const hasShipments = /shipment|reference|suggested rate|miles/.test(body);
  const strongLogin =
    /enter your password|forgot (your )?password|one-time code|sign in to continue/.test(body);
  if (strongLogin && !hasShipments) {
    return { status: "needs_login", loads: [], error: "ArcBest login required", broker: BROKER, pageUrl: url };
  }
  // Background will MAIN-world scrape Vue; we just signal listening
  const onBoard = hasShipments || /\/shipments/i.test(low);
  return {
    status: onBoard ? "listening" : "empty",
    loads: [],
    summaries: [],
    onBoard,
    countHint: onBoard ? 1 : 0,
    error: onBoard
      ? ""
      : "Open ArcBest Shipments and wait for the list (visible search/list required)",
    broker: BROKER,
    pageUrl: url,
  };
}
