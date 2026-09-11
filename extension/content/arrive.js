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
  // Hard login only on clear auth URLs (not find-loads SPA)
  if (/login|signin|auth/i.test(low) && !/find-loads/i.test(low)) {
    return { status: "needs_login", loads: [], error: "Arrive login wall", broker: BROKER, pageUrl: url };
  }
  const rows = [...document.querySelectorAll('tr[data-testid^="load-row-"]')];
  if (rows.length) {
    return {
      status: "ok_dom_hint",
      loads: [],
      countHint: rows.length,
      onBoard: true,
      broker: BROKER,
      pageUrl: url,
    };
  }
  const body = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
  const strongLogin =
    /enter your password|forgot (your )?password|one-time code|sign in to continue/.test(body);
  const onBoard = /find.?loads|refresh results|load board|equipment/.test(body) || /find-loads/i.test(low);
  if (strongLogin && !onBoard) {
    return { status: "needs_login", loads: [], error: "Arrive login required", broker: BROKER, pageUrl: url };
  }
  return {
    status: onBoard ? "listening" : "empty",
    loads: [],
    onBoard,
    error: onBoard ? "No load rows yet — click Refresh Results" : "Open Arrive find-loads",
    broker: BROKER,
    pageUrl: url,
  };
}
