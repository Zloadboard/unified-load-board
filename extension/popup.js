const BROKERS = [
  { key: "Arrive", open: "Arrive" },
  { key: "RXO", open: "RXO" },
  { key: "ArcBest", open: "ArcBest" },
  { key: "Echo", open: "Echo" },
  { key: "CHR", open: "CHR" },
];

function pillClass(status, count) {
  const s = String(status || "unknown");
  if (s === "ok") return "ok";
  if (s === "needs_login" && count > 0) return "stale";
  if (s === "needs_login" || s === "no_tab") return s;
  if (s === "error") return "error";
  if (s === "kept_previous" || s === "empty" || s === "listening") return s;
  if (s === "stale") return "stale";
  return "";
}

function labelStatus(status, count) {
  const s = String(status || "unknown");
  if (s === "stale" || (s === "needs_login" && count > 0) || s === "kept_previous") {
    return "sign in / open tab to refresh";
  }
  const map = {
    ok: "ok",
    needs_login: "needs login",
    no_tab: "open tab",
    error: "error",
    empty: "empty",
    listening: "listening",
    stale: "stale",
    unknown: "…",
  };
  return map[s] || s || "…";
}

function render(state) {
  document.getElementById("lastScan").textContent = state.lastScanAt
    ? new Date(state.lastScanAt).toLocaleTimeString()
    : "—";
  document.getElementById("total").textContent =
    state.total != null ? String(state.total) : "—";
  const errRow = document.getElementById("errRow");
  if (state.lastError) {
    errRow.hidden = false;
    document.getElementById("lastErr").textContent = state.lastError;
  } else {
    errRow.hidden = true;
  }
  const ul = document.getElementById("brokerList");
  ul.innerHTML = "";
  for (const b of BROKERS) {
    const meta = (state.sources && state.sources[b.key]) || {};
    const count = meta.count != null ? Number(meta.count) : 0;
    const li = document.createElement("li");
    li.className = "broker";
    const countClass = count > 0 ? "count has-loads" : "count";
    li.innerHTML = `
      <div class="broker-name">${b.key}</div>
      <button type="button" class="tiny" data-open="${b.open}">Open</button>
      <div class="broker-meta">
        <span class="pill ${pillClass(meta.status, count)}">${labelStatus(meta.status, count)}</span>
        <span class="${countClass}" title="${meta.error || ""}">${count} loads</span>
      </div>
    `;
    ul.appendChild(li);
  }
  ul.querySelectorAll("[data-open]").forEach((btn) => {
    btn.addEventListener("click", () => {
      chrome.runtime.sendMessage({ type: "open_broker", broker: btn.getAttribute("data-open") });
    });
  });
}

async function refresh() {
  const state = await chrome.runtime.sendMessage({ type: "get_status" });
  const stored = await chrome.storage.local.get(["scanState"]);
  render({ ...(stored.scanState || {}), ...(state || {}) });
}

document.getElementById("btnScan").addEventListener("click", async () => {
  const btn = document.getElementById("btnScan");
  btn.disabled = true;
  btn.textContent = "Scanning…";
  try {
    const state = await chrome.runtime.sendMessage({ type: "scan_now" });
    render(state || {});
  } finally {
    btn.disabled = false;
    btn.textContent = "Scan now";
  }
});

document.getElementById("btnBoard").addEventListener("click", () => {
  chrome.runtime.sendMessage({ type: "open_board" });
});

refresh();
setInterval(refresh, 5000);
