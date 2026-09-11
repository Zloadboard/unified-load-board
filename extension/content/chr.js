/** CHR content script */
const BROKER = "CHR";

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
  const url = (location.href || "").toLowerCase();
  if (/okta\.|\/sso|login\.|signin/.test(url) && !/navispherecarrier\.com\/?$/.test(url) && !/find.?load|search/.test(url)) {
    // Only hard-fail on clear IdP URLs
    if (/okta\.|auth0\.|\/sso\//.test(url)) {
      return { status: "needs_login", loads: [], error: "CHR login required", broker: BROKER, pageUrl: location.href };
    }
  }
  const body = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
  const onBoard = /find loads|available|shipment|search loads|load board/.test(body);
  const strongLogin =
    /enter your password|forgot (your )?password|sign in to continue|one-time code/.test(body);
  if (strongLogin && !onBoard) {
    return { status: "needs_login", loads: [], error: "CHR login required", broker: BROKER, pageUrl: location.href };
  }
  return {
    status: "listening",
    loads: [],
    error: onBoard ? "" : "Run a search on Navisphere to capture CHR loads",
    broker: BROKER,
    pageUrl: location.href,
  };
}
