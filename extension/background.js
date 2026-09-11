/**
 * Unified Load Board — MV3 service worker.
 * Alarm ~60s: fetch brokers (cookies + MAIN-world + content scripts), merge, POST localhost:8765/api/loads.
 */
import { BROKER_URLS, nowIsoZ, looksLikeLoginUrl } from "./lib/normalize.js";
import { mergeSources, shouldReuseLastGood, dedupeById } from "./lib/merge.js";
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

async function saveStore(partial) {
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

/** Focus an existing broker tab if present; otherwise create one. */
async function openOrFocusBroker(url) {
  if (!url) return { ok: false };
  try {
    const origin = new URL(url).origin;
    const tabs = await chrome.tabs.query({ url: [`${origin}/*`] });
    // Prefer a tab whose path looks like the board URL
    const pathHint = new URL(url).pathname.split("/").filter(Boolean)[0] || "";
    let best = tabs.find((t) => t.url && pathHint && t.url.includes(pathHint));
    if (!best) best = tabs[0];
    if (best?.id != null) {
      await chrome.tabs.update(best.id, { active: true });
      if (best.windowId != null) {
        try {
          await chrome.windows.update(best.windowId, { focused: true });
        } catch {
          /* ignore */
        }
      }
      return { ok: true, reused: true, tabId: best.id };
    }
  } catch {
    /* fall through to create */
  }
  const tab = await chrome.tabs.create({ url });
  return { ok: true, reused: false, tabId: tab.id };
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
    const u = map[key] || BROKER_URLS[key] || BROKER_URLS[key?.charAt(0).toUpperCase() + key?.slice(1)];
    openOrFocusBroker(u).then((r) => sendResponse(r));
    return true;
  }
  if (msg.type === "open_board") {
    openOrFocusBroker("http://localhost:8765/").then((r) => sendResponse(r));
    return true;
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
  return tabs.filter((t) => t.id != null && !looksLikeLoginUrl(t.url || ""));
}

/** Inject page-world network hook (CSP-safe via chrome.scripting). */
async function ensureMainWorldHook(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      files: ["content/injected_hook.js"],
    });
  } catch {
    /* tab may be restricted */
  }
}

/**
 * Read ArcBest Vue shipmentSummaries from MAIN world.
 * CSP often blocks inline script.textContent; executeScript world:MAIN works.
 */
async function readArcbestMainWorld(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => {
        try {
          const app = window.shipmentsListApp || null;
          const list =
            (app && (app.shipmentSummaries || (app.$data && app.$data.shipmentSummaries))) ||
            null;
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
                consigneeLocation: { city: cons.city || null, state: cons.state || null },
              });
            }
          }
          return {
            summaries: out,
            href: String(location.href || ""),
            hasApp: !!app,
          };
        } catch (e) {
          return { summaries: [], error: String(e), href: String(location.href || "") };
        }
      },
    });
    return results?.[0]?.result || null;
  } catch (e) {
    return { summaries: [], error: String(e.message || e) };
  }
}

async function collectFromTabs(broker) {
  const tabs = await queryBrokerTabs(broker);
  if (!tabs.length) return null;
  let last = null;
  for (const tab of tabs) {
    await ensureMainWorldHook(tab.id);
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "collect" });
      if (result) {
        last = result;
        // Prefer any result that already has loads / summaries
        if (result.loads?.length || result.summaries?.length) return result;
        // Confirmed login URL on the tab itself
        if (result.status === "needs_login" && looksLikeLoginUrl(tab.url || result.pageUrl || "")) {
          return result;
        }
      }
    } catch {
      /* content script may not be ready */
    }
  }
  return last || { status: "no_tab", loads: [], error: "tab open but content script not ready" };
}

/**
 * fetchOne: never short-circuit solely on content-script needs_login.
 * Always try MAIN-world (ArcBest) + background GraphQL/API; content script is bonus.
 */
async function fetchOne(broker, store) {
  const opts = {
    discoveredEndpoints: store.discoveredEndpoints,
    lastRequestBodies: store.lastRequestBodies,
  };

  let confirmedLogin = false;
  let tabHint = null;

  // --- 1) Content script collect (bonus; do NOT trust soft needs_login alone) ---
  const fromTab = await collectFromTabs(broker);
  if (fromTab) {
    tabHint = fromTab;
    if (fromTab.status === "needs_login" && looksLikeLoginUrl(fromTab.pageUrl || "")) {
      confirmedLogin = true;
    }
    if (broker === "ArcBest" && fromTab.summaries?.length) {
      const loads = loadsFromSummaries(fromTab.summaries);
      if (loads.length) return { status: "ok", loads, error: "" };
    }
    if (fromTab.loads?.length) {
      return { status: "ok", loads: fromTab.loads, error: "" };
    }
  }

  // --- 2) MAIN-world Vue scrape for ArcBest (CSP-safe) ---
  if (broker === "ArcBest") {
    const tabs = await queryBrokerTabs(broker);
    for (const tab of tabs) {
      const mw = await readArcbestMainWorld(tab.id);
      if (mw?.summaries?.length) {
        const loads = loadsFromSummaries(mw.summaries);
        if (loads.length) {
          return { status: "ok", loads, error: "" };
        }
      }
      if (mw?.href && looksLikeLoginUrl(mw.href)) confirmedLogin = true;
    }
  }

  // --- 3) Background cookie GraphQL / API (try ALL endpoints; don't bail on first login miss) ---
  let result;
  if (broker === "Arrive") result = await fetchArrive(opts);
  else if (broker === "RXO") result = await fetchRxo(opts);
  else if (broker === "ArcBest") result = await fetchArcbest(opts);
  else if (broker === "Echo") result = await fetchEcho(opts);
  else if (broker === "CHR") result = await fetchChr(opts);
  else result = { status: "error", loads: [], error: "unknown broker" };

  if (result.status === "needs_login") confirmedLogin = true;

  if (result.loads?.length) {
    const reused = shouldReuseLastGood(
      result.loads,
      store.lastGood?.[broker]?.loads,
      store.lastGood?.[broker]?.savedAt
    );
    if (reused && reused.length > result.loads.length) {
      return { status: "kept_previous", loads: reused, error: "", keptPrevious: true };
    }
    return { status: result.status === "needs_login" ? "ok" : result.status || "ok", loads: result.loads, error: "" };
  }

  // --- 4) lastGood / network-hook stash ---
  if (store.lastGood?.[broker]?.loads?.length) {
    const reused = shouldReuseLastGood(
      [],
      store.lastGood[broker].loads,
      store.lastGood[broker].savedAt
    );
    if (reused) {
      return {
        status: confirmedLogin ? "needs_login" : result.status === "no_tab" ? "kept_previous" : result.status || "kept_previous",
        loads: reused,
        error: confirmedLogin
          ? "sign in to refresh"
          : result.error || tabHint?.error || "",
        keptPrevious: true,
      };
    }
  }

  // Soft content needs_login without confirmed URL → treat as empty/listening, not hard login
  if (confirmedLogin) {
    return {
      status: "needs_login",
      loads: [],
      error: result.error || tabHint?.error || `${broker} login required`,
    };
  }

  // Prefer tab listening/empty over hard needs_login
  if (tabHint && tabHint.status && tabHint.status !== "needs_login") {
    return {
      status: result.status || tabHint.status || "empty",
      loads: [],
      error: result.error || tabHint.error || "",
    };
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

      // Empty + needs_login/error: keep previous from storage
      if (!loads.length) {
        const prev =
          store.sourceLoads?.[broker] || store.lastGood?.[broker]?.loads || [];
        if (
          prev.length &&
          ["needs_login", "error", "empty", "no_tab", "kept_previous", "listening"].includes(
            result.status
          )
        ) {
          loads = prev;
          result.keptPrevious = true;
          // Keep needs_login status but show prior count (popup: "sign in to refresh")
          if (result.status !== "needs_login") result.status = "kept_previous";
        }
      }

      if (broker === "ArcBest") {
        sourceLoads.ArcBest = loads.filter((L) => L.source === "ArcBest");
        sourceLoads.MoLo = loads.filter((L) => L.source === "MoLo");
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

chrome.alarms.get(ALARM, (a) => {
  if (!a) chrome.alarms.create(ALARM, { periodInMinutes: 1 });
});
