/** Arrive content script — capture GraphQL + DOM load-row-{LoadBoardId} rows. */
const BROKER = "Arrive";
const BOARD = "https://carrier.arrivelogistics.com/find-loads";

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

function parseStop(blob) {
  const out = { city: "", date: "", time: "" };
  if (!blob || typeof blob !== "string") return out;
  const text = blob.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  let lines = text
    .split("\n")
    .map((ln) => ln.trim())
    .filter(Boolean);
  if (lines.length === 1 && (/\|/.test(lines[0]) || /\s{2,}/.test(lines[0]))) {
    lines = lines[0]
      .split(/\s*\|\s*|\s{2,}/)
      .map((p) => p.trim())
      .filter(Boolean);
  }
  const cityRe = /\b([A-Za-z][A-Za-z .'-]+,\s*[A-Z]{2})\b/;
  for (const ln of lines) {
    if (/\(\s*\d+\s*mi/i.test(ln)) continue;
    const m = ln.match(cityRe);
    if (m) {
      out.city = m[1].trim();
      break;
    }
  }
  if (!out.city) {
    const m = text.replace(/\n/g, " ").match(cityRe);
    if (m) out.city = m[1].trim();
  }
  const dows = "Sun|Mon|Tue|Wed|Thu|Fri|Sat";
  const months = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec";
  const fullDate = new RegExp(`\\b((?:${dows})\\s+(?:${months})\\s+\\d{1,2})\\b`, "i");
  const fd = text.replace(/\n/g, " ").match(fullDate);
  if (fd) {
    const parts = fd[1].split(/\s+/);
    out.date = `${parts[0].slice(0, 3)} ${parts[1].slice(0, 1).toUpperCase()}${parts[1]
      .slice(1, 3)
      .toLowerCase()} ${parseInt(parts[2], 10)}`;
  }
  const timeRe = /\b(\d{1,2}:\d{2})\s*([A-Z]{2,4})?\b/;
  for (const ln of lines) {
    if (cityRe.test(ln) || /\(\s*\d+\s*mi/i.test(ln)) continue;
    const tm = ln.match(timeRe);
    if (tm) {
      out.time = `${tm[1]}${tm[2] ? " " + tm[2] : ""}`;
      break;
    }
  }
  return out;
}

function equip(cell) {
  const c = (cell || "").toString().trim().toUpperCase();
  const map = { V: "Van", VR: "Van/Reefer", R: "Reefer", F: "Flatbed", FD: "Flatbed" };
  return map[c] || (cell || "").toString().trim();
}

/** Real LoadBoardId from tr[data-testid=load-row-N] — same as Arrive Load #. */
function collectDomLoads() {
  const trs = [...document.querySelectorAll('tr[data-testid^="load-row-"]')];
  const seen = new Set();
  const loads = [];
  for (const tr of trs) {
    const tid = tr.getAttribute("data-testid") || "";
    const m = tid.match(/load-row-(\d+)/i);
    if (!m) continue;
    const lid = m[1];
    if (seen.has(lid)) continue;
    seen.add(lid);
    const cells = [...tr.querySelectorAll("td")].map((td) => (td.innerText || "").trim());
    const pu = parseStop(cells[0] || "");
    const de = parseStop(cells[1] || "");
    let miles = null;
    let weight = "";
    let eq = "";
    let rate = null;
    if (cells.length > 3 && /^[\d,]+$/.test(String(cells[3]).replace(/,/g, ""))) {
      miles = Number(String(cells[3]).replace(/,/g, ""));
    }
    if (cells.length > 4) {
      const wm = String(cells[4]).replace(/,/g, "").match(/([\d.]+)/);
      if (wm) weight = Math.round(Number(wm[1]));
    }
    if (cells.length > 5) eq = equip(cells[5]);
    if (cells.length > 6) {
      const rm = String(cells[6]).replace(/[$,]/g, "").match(/([\d.]+)/);
      if (rm) rate = Number(rm[1]);
    }
    loads.push({
      id: lid,
      source: BROKER,
      origin: pu.city || "",
      destination: de.city || "",
      pickup_city: pu.city || "",
      delivery_city: de.city || "",
      pickup_date: pu.date || "",
      pickup_time: pu.time || "",
      delivery_date: de.date || "",
      delivery_time: de.time || "",
      pickup: `${pu.date || ""} ${pu.time || ""}`.trim(),
      delivery: `${de.date || ""} ${de.time || ""}`.trim(),
      miles,
      weight,
      equipment: eq,
      rate,
      status: "",
      url: `${BOARD}?loadBoardId=${lid}`,
      notes: "",
      first_seen_at: "",
      seen_age: "",
    });
  }
  return loads;
}

function collect() {
  const url = location.href || "";
  const low = url.toLowerCase();
  if (/login|signin|auth/i.test(low) && !/find-loads/i.test(low)) {
    return { status: "needs_login", loads: [], error: "Arrive login wall", broker: BROKER, pageUrl: url };
  }

  const loads = collectDomLoads();
  if (loads.length) {
    return {
      status: "ok",
      loads,
      countHint: loads.length,
      onBoard: true,
      broker: BROKER,
      pageUrl: url,
      via: "dom_load_row",
    };
  }

  const body = (document.body?.innerText || "").slice(0, 2500).toLowerCase();
  const strongLogin =
    /enter your password|forgot (your )?password|one-time code|sign in to continue/.test(body);
  const onBoard =
    /find.?loads|refresh results|load board|equipment/.test(body) || /find-loads/i.test(low);
  if (strongLogin && !onBoard) {
    return {
      status: "needs_login",
      loads: [],
      error: "Arrive login required",
      broker: BROKER,
      pageUrl: url,
    };
  }
  return {
    status: onBoard ? "listening" : "empty",
    loads: [],
    onBoard,
    countHint: 0,
    error: onBoard
      ? "Open Arrive find-loads, run Search, Scan now"
      : "Open Arrive find-loads, run Search, Scan now",
    broker: BROKER,
    pageUrl: url,
  };
}
