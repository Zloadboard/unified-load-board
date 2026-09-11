/** RXO content script */
const BROKER = "RXO";

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
  const url = (location.href || "").toLowerCase();
  const body = (document.body?.innerText || "").slice(0, 3000).toLowerCase();
  if (
    url.includes("login.id.rxo") ||
    url.includes("multifactor") ||
    body.includes("one-time code") ||
    body.includes("enter your 6-digit")
  ) {
    return { status: "needs_login", loads: [], error: "RXO login / MFA required", broker: BROKER, pageUrl: location.href };
  }
  const strongLogin =
    /enter your password|forgot (your )?password|sign in to continue/.test(body) &&
    !/available loads|loadboard|search loads/.test(body);
  if (strongLogin) {
    return { status: "needs_login", loads: [], error: "RXO login required", broker: BROKER, pageUrl: location.href };
  }
  return { status: "listening", loads: [], broker: BROKER, pageUrl: location.href };
}
