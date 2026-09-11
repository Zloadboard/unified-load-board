/**
 * Unified Load Board — MV3 service worker.
 * Alarm ~60s: fetch brokers (cookies + content scripts), merge, POST localhost:8765/api/loads.
 */
import { BROKER_URLS, nowIsoZ } from "./lib/normalize.js";
import { mergeSources, shouldReuseLastGood, dedupeById, groupBySource } from "./lib/merge.js";
import { fetchArrive, loadsFromArrivePayload, isArriveInterestingUrl } from "./brokers/arrive.js";
import { fetchRxo, loadsFromRxoPayload, isRxoInterestingUrl } from "./brokers/rxo.js";
import { fetchArcbest, loadsFromSummaries, loadsFromArcbestPayload } from "./brokers/arcbest.js";
import { fetchEcho, loadsFromEchoPayload, isEchoInterestingUrl } from "./brokers/echo.js";
import { fetchChr, loadsFromChrPayload, isChrInterestingUrl } from "./brokers/chr.js";

const ALARM = "ulb-scan";
const BOARD_POST = "http://localhost:8765/api/loads";
const SOURCES = ["Arrive", "RXO", "ArcBest", "Echo", "CHR"];

const state = {
  scanning: false,
  lastScanAt: null,
  sources: Object.fromEntries(
    SOURCES.map((s) => [s, { status: "unknown", count: 0, error: "", keptPrevious: false }])
  ),
  total: 0,
  lastError: "",
  mode: "extension",
};

async function loadStore() {
  const data = await chrome.storage.local.get([
    "loads",
    "sourceLoads",
    "lastGood",
    "discoveredEndpoints",
    "lastRequestBodies",
    "sourceMeta",
  ]);
  return {
    loads: data.loads || [],
    sourceLoads: data.sourceLoads || {},
    lastGood: data.lastGood || {},
    discoveredEndpoints: data.discoveredEndpoints || {},
    lastRequestBodies: data.lastRequestBodies || {},
    sourceMeta: data.sourceMeta || {},
  };
}

async function saveStore( partial ) {
  await chrome.storage.local.set(partial);
}

function rememberEndpoint(broker, url, method, requestBody) {
  return loadStore().then(async (store) => {
    const eps = { ...(store.discoveredEndpoints || {}) };
    const list = [...(eps[broker] || [])];
    if (url && !list.includes(url)) {
      list.unshift(url);
      eps[broker] = list.slice(0, 8);
    }
    const bodies = { ...(store.lastRequestBodies || {}) };
    const blist = [...(bodies[broker] || [])];
    if (url && requestBody) {
      blist.unshift({
        url,
        method: method || "POST",
        bodyText: typeof requestBody === "string" ? requestBody : JSON.stringify(requestBody),
        savedAt: Date.now(),
      });
      bodies[broker] = blist.slice(0, 5);
    }
    await saveStore({ discoveredEndpoints: eps, lastRequestBodies: bodies });
  });
}

function parseNetPayload(broker, url, body) {
  if (!body) return [];
  if (broker === "Arrive" || isArriveInterestingUrl(url)) return loadsFromArrivePayload(body);
  if (broker === "RXO" || isRxoInterestingUrl(url)) return loadsFromRxoPayload(body);
  if (broker === "Echo" || isEchoInterestingUrl(url)) return loadsFromEchoPayload(body);
  if (broker === "CHR" || isChrInterestingUrl(url)) return loadsFromChrPayload(body);
  if (broker === "ArcBest") return loadsFromArcbestPayload(body);
  return [];
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === "net_payload") {
    (async () => {
      const broker = msg.broker || "Unknown";
      const loads = parseNetPayload(broker, msg.url, msg.body);
      await rememberEndpoint(broker, msg.url, msg.method, msg.requestBody);
      if (loads.length) {
        const store = await loadStore();
        const lg = { ...(store.lastGood || {}) };
        lg[broker] = { loads, savedAt: Date.now() };
        // ArcBest may include MoLo
        if (broker === "ArcBest") {
          const molo = loads.filter((L) => L.source === "MoLo");
          const arc = loads.filter((L) => L.source === "ArcBest");
          if (arc.length) lg.ArcBest = { loads: arc, savedAt: Date.now() };
          if (molo.length) lg.MoLo = { loads: molo, savedAt: Date.now() };
        }
        const sourceLoads = { ...(store.sourceLoads || {}), [broker]: loads };
        if (broker === "ArcBest") {
          sourceLoads.ArcBest = loads.filter((L) => L.source === "ArcBest");
          sourceLoads.MoLo = loads.filter((L) => L.source === "MoLo");
        }
        await saveStore({ lastGood: lg, sourceLoads });
        state.sources[broker] = {
          status: "ok",
          count: loads.length,
          error: "",
          keptPrevious: false,
        };
      }
      sendResponse({ ok: true, n: loads.length });
    })();
    return true;
  }
  if (msg.type === "get_status") {
    sendResponse({ ...state });
    return false;
  }
  if (msg.type === "scan_now") {
    runScan("manual").then((r) => sendResponse(r));
    return true;
  }
  if (msg.type === "open_broker") {
    const key = msg.broker;
    const url = BROKER_URLS[key] || BROKER_URLS[key?.charAt(0).toUpperCase() + key?.slice(1)];
    const map = {
      arrive: BROKER_URLS.Arrive,
      rxo: BROKER_URLS.RXO,
      arcbest: BROKER_URLS.ArcBest,
      echo: BROKER_URLS.Echo,
      chr: BROKER_URLS.CHR,
      Arrive: BROKER_URLS.Arrive,
      RXO: BROKER_URLS.RXO,
      ArcBest: BROKER_URLS.ArcBest,
      Echo: BROKER_URLS.Echo,
      CHR: BROKER_URLS.CHR,
    };
    const u = map[key] || url;
    if (u) chrome.tabs.create({ url: u });
    sendResponse({ ok: true });
    return false;
  }
  if (msg.type === "open_board") {
    chrome.tabs.create({ url: "http://localhost:8765/" });
    sendResponse({ ok: true });
    return false;
  }
});

async function queryBrokerTabs(broker) {
  const patterns = {
    Arrive: ["*://carrier.arrivelogistics.com/*", "*://*.arrivelogistics.com/*"],
    RXO: ["*://carrier.rxoconnect.rxo.com/*", "*://*.rxoconnect.rxo.com/*"],
    ArcBest: ["*://carriers.arcb.com/*", "*://*.arcb.com/*"],
    Echo: ["*://echodrive.echo.com/*", "*://*.echo.com/*"],
    CHR: ["*://www.navispherecarrier.com/*", "*://*.navispherecarrier.com/*"],
  };
  const tabs = await chrome.tabs.query({ url: patterns[broker] || [] });
  return tabs.filter((t) => t.id != null);
}

async function collectFromTabs(broker) {
  const tabs = await queryBrokerTabs(broker);
  if (!tabs.length) return null;
  for (const tab of tabs) {
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "collect" });
      if (result) return result;
    } catch {
      /* content script may not be ready */
    }
  }
  return { status: "no_tab", loads: [], error: "tab open but content script not ready" };
}

async function fetchOne(broker, store) {
  const opts = {
    discoveredEndpoints: store.discoveredEndpoints,
    lastRequestBodies: store.lastRequestBodies,
  };
  // Content script first when tab is open
  const fromTab = await collectFromTabs(broker);
  if (fromTab) {
    if (fromTab.status === "needs_login") {
      return { status: "needs_login", loads: [], error: fromTab.error || "needs login" };
    }
    if (broker === "ArcBest" && fromTab.summaries?.length) {
      const loads = loadsFromSummaries(fromTab.summaries);
      return { status: loads.length ? "ok" : "empty", loads, error: "" };
    }
    if (fromTab.loads?.length) {
      return { status: "ok", loads: fromTab.loads, error: "" };
    }
  }

  let result;
  if (broker === "Arrive") result = await fetchArrive(opts);
  else if (broker === "RXO") result = await fetchRxo(opts);
  else if (broker === "ArcBest") result = await fetchArcbest(opts);
  else if (broker === "Echo") result = await fetchEcho(opts);
  else if (broker === "CHR") result = await fetchChr(opts);
  else result = { status: "error", loads: [], error: "unknown broker" };

  // If background said no_tab but we have recent last-good from network hook, surface as kept
  if ((!result.loads || !result.loads.length) && store.lastGood?.[broker]?.loads?.length) {
    const reused = shouldReuseLastGood(
      result.loads || [],
      store.lastGood[broker].loads,
      store.lastGood[broker].savedAt
    );
    if (reused) {
      return {
        status: result.status === "needs_login" ? "needs_login" : "kept_previous",
        loads: reused,
        error: result.error || "",
        keptPrevious: true,
      };
    }
  }
  if (result.loads?.length && result.status !== "needs_login") {
    const reused = shouldReuseLastGood(
      result.loads,
      store.lastGood?.[broker]?.loads,
      store.lastGood?.[broker]?.savedAt
    );
    if (reused) {
      return { status: "kept_previous", loads: reused, error: "", keptPrevious: true };
    }
  }
  return result;
}

async function postToBoard(loads, sourceMeta) {
  const payload = {
    updatedAt: nowIsoZ(),
    mode: "extension",
    sources: sourceMeta,
    loads,
  };
  const res = await fetch(BOARD_POST, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new Error(`POST /api/loads HTTP ${res.status} ${t.slice(0, 200)}`);
  }
  return res.json().catch(() => ({ ok: true }));
}

async function runScan(reason = "alarm") {
  if (state.scanning) return { ...state, skipped: true };
  state.scanning = true;
  state.lastError = "";
  try {
    const store = await loadStore();
    const sourceLoads = {};
    const meta = {};

    for (const broker of SOURCES) {
      let result;
      try {
        result = await fetchOne(broker, store);
      } catch (e) {
        result = { status: "error", loads: [], error: String(e.message || e) };
      }
      let loads = result.loads || [];

      // Empty + needs_login/error: keep previous from storage / loads
      if (!loads.length) {
        const prev =
          store.sourceLoads?.[broker] ||
          store.lastGood?.[broker]?.loads ||
          [];
        if (prev.length && ["needs_login", "error", "empty", "no_tab", "kept_previous"].includes(result.status)) {
          loads = prev;
          result.keptPrevious = true;
          if (result.status !== "needs_login") result.status = "kept_previous";
        }
      }

      if (broker === "ArcBest") {
        sourceLoads.ArcBest = loads.filter((L) => L.source === "ArcBest");
        sourceLoads.MoLo = loads.filter((L) => L.source === "MoLo");
        // If all tagged ArcBest only, still fine
        if (!sourceLoads.ArcBest.length && !sourceLoads.MoLo.length) {
          sourceLoads.ArcBest = loads;
        }
      } else {
        sourceLoads[broker] = loads.map((L) => ({ ...L, source: L.source || broker }));
      }

      const count =
        broker === "ArcBest"
          ? (sourceLoads.ArcBest?.length || 0) + (sourceLoads.MoLo?.length || 0)
          : loads.length;

      meta[broker] = {
        status: result.status || "unknown",
        count,
        error: result.error || "",
        keptPrevious: !!result.keptPrevious,
      };
      state.sources[broker] = meta[broker];

      if (loads.length && !result.keptPrevious && result.status === "ok") {
        const lg = { ...(store.lastGood || {}) };
        lg[broker] = { loads, savedAt: Date.now() };
        store.lastGood = lg;
      }
    }

    // Also apply MoLo meta
    if (sourceLoads.MoLo?.length) {
      meta.MoLo = {
        status: meta.ArcBest?.status || "ok",
        count: sourceLoads.MoLo.length,
        error: "",
        keptPrevious: !!meta.ArcBest?.keptPrevious,
      };
    }

    const previous = store.loads || [];
    const merged = mergeSources(sourceLoads, previous, meta);
    const finalLoads = dedupeById(merged);

    await saveStore({
      loads: finalLoads,
      sourceLoads,
      lastGood: store.lastGood,
      sourceMeta: meta,
    });

    try {
      await postToBoard(finalLoads, meta);
      state.lastError = "";
    } catch (e) {
      state.lastError = String(e.message || e);
      // Still keep chrome.storage; board server may be down
    }

    state.lastScanAt = nowIsoZ();
    state.total = finalLoads.length;
    state.mode = "extension";
    await chrome.storage.local.set({ scanState: { ...state } });
    return { ...state, reason };
  } finally {
    state.scanning = false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  runScan("install");
});

chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create(ALARM, { periodInMinutes: 1 });
  runScan("startup");
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === ALARM) runScan("alarm");
});

// Ensure alarm exists when SW wakes
chrome.alarms.get(ALARM, (a) => {
  if (!a) chrome.alarms.create(ALARM, { periodInMinutes: 1 });
});
