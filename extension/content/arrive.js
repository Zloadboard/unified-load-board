/** Arrive content script — capture GraphQL + optional DOM load-row ids. */
const BROKER = "Arrive";

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

function collect() {
  const url = location.href || "";
  if (/login|signin|auth/i.test(url) && !/find-loads/i.test(url)) {
    return { status: "needs_login", loads: [], error: "Arrive login wall", broker: BROKER };
  }
  // Prefer network payloads already sent; also scrape load-row testids as thin fallback
  const rows = [...document.querySelectorAll('tr[data-testid^="load-row-"]')];
  if (!rows.length) {
    const loginish = /sign\s*in|log\s*in|password/i.test(document.body?.innerText?.slice(0, 2000) || "");
    return {
      status: loginish ? "needs_login" : "empty",
      loads: [],
      error: loginish ? "Arrive login required" : "No load rows yet — click Refresh Results",
      broker: BROKER,
    };
  }
  // Signal only — background prefers GraphQL. Return empty so we don't invent synthetic ids.
  return { status: "ok_dom_hint", loads: [], countHint: rows.length, broker: BROKER, pageUrl: url };
}
