/** Echo content script */
const BROKER = "Echo";

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
  if (url.includes("auth0.com") || url.includes("/u/login")) {
    return { status: "needs_login", loads: [], error: "Echo login required", broker: BROKER, pageUrl: location.href };
  }
  const body = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
  const onBoard = url.includes("/carrier/") || url.includes("available") || /available loads|open board/.test(body);
  const strongLogin =
    /enter your password|forgot (your )?password|sign in to continue|one-time code/.test(body);
  if (strongLogin && !onBoard) {
    return { status: "needs_login", loads: [], error: "Echo login required", broker: BROKER, pageUrl: location.href };
  }
  return { status: "listening", loads: [], broker: BROKER, pageUrl: location.href };
}
