/**
 * Unified Load Board — MV3 service worker.
 * Alarm ~60s: fetch brokers (cookies + MAIN-world + content scripts), merge, POST localhost:8765/api/loads.
 */
import { BROKER_URLS, nowIsoZ, looksLikeLoginUrl, isLoginResponse } from "./lib/normalize.js";
import { mergeSources, shouldReuseLastGood, dedupeById } from "./lib/merge.js";
import { honestSourceMeta } from "./lib/status.js";
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

function rememberEndpoint(broker, url, method, requestBody, requestHeaders) {
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
        headers: requestHeaders || null,
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
      await rememberEndpoint(broker, msg.url, msg.method, msg.requestBody, msg.requestHeaders);
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
 * Discovers app if window.shipmentsListApp is renamed.
 * CSP-safe via executeScript world:MAIN.
 */
async function readArcbestMainWorld(tabId) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => {
        try {
          function summarize(list) {
            const out = [];
            if (!list || !list.length) return out;
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
            return out;
          }

          function listFromApp(app) {
            if (!app || typeof app !== "object") return null;
            return (
              app.shipmentSummaries ||
              (app.$data && app.$data.shipmentSummaries) ||
              (app._data && app._data.shipmentSummaries) ||
              null
            );
          }

          let appName = null;
          let app = window.shipmentsListApp || null;
          let list = listFromApp(app);
          if (app) appName = "shipmentsListApp";

          if (!list || !list.length) {
            const keys = Object.keys(window);
            for (let i = 0; i < keys.length; i++) {
              const k = keys[i];
              if (!k || k.length > 80) continue;
              let v;
              try {
                v = window[k];
              } catch (_) {
                continue;
              }
              if (!v || typeof v !== "object") continue;
              const cand = listFromApp(v);
              if (
                Array.isArray(cand) &&
                cand.length &&
                cand[0] &&
                typeof cand[0] === "object" &&
                ("shipmentId" in cand[0] || "referenceNumber" in cand[0])
              ) {
                app = v;
                list = cand;
                appName = k;
                break;
              }
            }
          }

          // Vue 2 roots on DOM
          if (!list || !list.length) {
            const els = document.querySelectorAll("*");
            const lim = Math.min(els.length, 2500);
            for (let i = 0; i < lim; i++) {
              const el = els[i];
              const vue = el.__vue__ || null;
              if (!vue) continue;
              const root = vue.$root || vue;
              const cand =
                listFromApp(root) ||
                listFromApp(root.$data) ||
                (root.$store &&
                  root.$store.state &&
                  (root.$store.state.shipmentSummaries ||
                    (root.$store.state.shipments && root.$store.state.shipments.summaries)));
              if (
                Array.isArray(cand) &&
                cand.length &&
                cand[0] &&
                ("shipmentId" in cand[0] || "referenceNumber" in cand[0])
              ) {
                list = cand;
                appName = "dom.__vue__";
                break;
              }
            }
          }

          const out = summarize(list);
          return {
            summaries: out,
            href: String(location.href || ""),
            hasApp: !!(app || (list && list.length)),
            appName,
            listLen: list && list.length ? list.length : 0,
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

const ARRIVE_GET_LOADS_BODY = JSON.stringify({
  operationName: "GetLoads",
  query: `query GetLoads($input: GetLoadsInput) {
  getLoads(input: $input) {
    data {
      LoadBoardId
      PickupEarlyCity
      PickupEarlyStateCode
      DeliveryLateCity
      DeliveryLateStateCode
      PickupApptEarliest
      PickupApptLatest
      DeliveryApptEarliest
      DeliveryApptLatest
      PickupLocationIANACode
      DeliveryLocationIANACode
      Miles
      Weight
      TopSpend
      EquipmentType
      LoadStatus
    }
  }
}`,
  variables: { input: {} },
});

/**
 * GraphQL fetch inside Arrive tab (page cookies). Prefer over SW fetch.
 */
async function fetchArriveInPage(tabId, url, bodyText, headers) {
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: async (fetchUrl, body, extraHeaders) => {
        try {
          const hdrs = Object.assign(
            {
              "content-type": "application/json",
              accept: "application/json",
            },
            extraHeaders && typeof extraHeaders === "object" ? extraHeaders : {}
          );
          // Drop forbidden / hop-by-hop headers if any leaked from capture
          delete hdrs["host"];
          delete hdrs["content-length"];
          delete hdrs["origin"];
          delete hdrs["referer"];
          delete hdrs["cookie"];
          const res = await fetch(fetchUrl, {
            method: "POST",
            credentials: "include",
            headers: hdrs,
            body: body,
          });
          const ct = res.headers.get("content-type") || "";
          const text = await res.text();
          return {
            ok: res.ok,
            status: res.status,
            ct,
            text: text.slice(0, 4000000),
            finalUrl: String(res.url || fetchUrl),
          };
        } catch (e) {
          return { ok: false, status: 0, ct: "", text: "", error: String(e && e.message ? e.message : e) };
        }
      },
      args: [url, bodyText || ARRIVE_GET_LOADS_BODY, headers || null],
    });
    return results?.[0]?.result || null;
  } catch (e) {
    return { ok: false, error: String(e.message || e) };
  }
}

async function nudgeArriveRefresh(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: () => {
        const nodes = [...document.querySelectorAll("button, a, [role='button']")];
        const btn = nodes.find((el) => /refresh results/i.test((el.textContent || "").trim()));
        if (btn) {
          btn.click();
          return true;
        }
        return false;
      },
    });
  } catch {
    /* ignore */
  }
}

async function collectArriveViaOpenTabs(store) {
  const tabs = await queryBrokerTabs("Arrive");
  if (!tabs.length) return null;
  const endpoints = [];
  for (const u of store.discoveredEndpoints?.Arrive || []) if (u) endpoints.push(u);
  for (const u of [
    "https://carrier.arrivelogistics.com/graphql",
    "https://carrier.arrivelogistics.com/api/graphql",
    "https://api.arrivelogistics.com/graphql",
  ]) {
    if (!endpoints.includes(u)) endpoints.push(u);
  }
  const bodies = store.lastRequestBodies?.Arrive || [];
  let lastErr = "";
  for (const tab of tabs) {
    await ensureMainWorldHook(tab.id);
    // Prefer replaying captured bodies (exact search filters)
    const attempts = [];
    for (const b of bodies) {
      if (b?.bodyText && b?.url) attempts.push({ url: b.url, bodyText: b.bodyText, headers: b.headers || null });
    }
    for (const url of endpoints) {
      attempts.push({ url, bodyText: ARRIVE_GET_LOADS_BODY, headers: null });
    }
    const seen = new Set();
    for (const a of attempts) {
      const key = `${a.url}::${(a.bodyText || "").slice(0, 80)}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const raw = await fetchArriveInPage(tab.id, a.url, a.bodyText, a.headers);
      if (!raw || raw.error) {
        lastErr = raw?.error || lastErr;
        continue;
      }
      const ct = raw.ct || "";
      if (isLoginResponse(raw.status, ct, raw.text || "", raw.finalUrl || a.url)) {
        lastErr = "Arrive login in page fetch";
        continue;
      }
      let json;
      try {
        json = JSON.parse(raw.text || "");
      } catch {
        lastErr = "Arrive page fetch non-json";
        continue;
      }
      const loads = loadsFromArrivePayload(json);
      if (loads.length) {
        return { status: "ok", loads, error: "", endpoint: a.url, via: "page" };
      }
      lastErr = "0 loads from page GraphQL";
    }
    // Nudge Refresh Results so the SPA fires real getLoads; hook captures it
    await nudgeArriveRefresh(tab.id);
    await new Promise((r) => setTimeout(r, 2200));
    const store2 = await loadStore();
    if (store2.lastGood?.Arrive?.loads?.length) {
      const age = Date.now() - (store2.lastGood.Arrive.savedAt || 0);
      if (age < 15000) {
        return {
          status: "ok",
          loads: store2.lastGood.Arrive.loads,
          error: "",
          via: "hook_after_refresh",
        };
      }
    }
  }
  return { status: "empty", loads: [], error: lastErr || "Arrive page GraphQL returned 0" };
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
 * Arrive: prefer in-tab GraphQL (cookies). ArcBest: MAIN-world Vue (+ discover).
 * Status: loads from this scan → ok; kept previous only → stale.
 */
async function fetchOne(broker, store) {
  const opts = {
    discoveredEndpoints: store.discoveredEndpoints,
    lastRequestBodies: store.lastRequestBodies,
  };

  let confirmedLogin = false;
  let tabHint = null;
  let onBoard = false;

  // --- 0) Very recent network-hook capture counts as this scan ---
  const recent = store.lastGood?.[broker];
  if (recent?.loads?.length && recent.savedAt && Date.now() - recent.savedAt < 120000) {
    // Still try live paths below for ArcBest/Arrive; for others recent hook is enough
    if (broker === "Echo" || broker === "CHR" || broker === "RXO") {
      return { status: "ok", loads: recent.loads, error: "" };
    }
  }

  // --- 1) Content script collect (bonus; do NOT trust soft needs_login alone) ---
  const fromTab = await collectFromTabs(broker);
  if (fromTab) {
    tabHint = fromTab;
    if (fromTab.status === "needs_login" && looksLikeLoginUrl(fromTab.pageUrl || "")) {
      confirmedLogin = true;
    }
    if (fromTab.onBoard || fromTab.status === "ok_dom_hint" || fromTab.countHint > 0) {
      onBoard = true;
    }
    if (broker === "ArcBest" && fromTab.summaries?.length) {
      const loads = loadsFromSummaries(fromTab.summaries);
      if (loads.length) return { status: "ok", loads, error: "" };
    }
    if (fromTab.loads?.length) {
      return { status: "ok", loads: fromTab.loads, error: "" };
    }
  }

  // --- 2) Arrive: page-context GraphQL when find-loads tab is open ---
  if (broker === "Arrive") {
    const pageResult = await collectArriveViaOpenTabs(store);
    if (pageResult?.loads?.length) {
      return { status: "ok", loads: pageResult.loads, error: "" };
    }
    if (pageResult && pageResult.status && pageResult.status !== "needs_login") {
      // keep as fallback hint; still try SW below
      tabHint = tabHint || pageResult;
    }
  }

  // --- 3) MAIN-world Vue scrape for ArcBest (CSP-safe + discover) ---
  if (broker === "ArcBest") {
    const tabs = await queryBrokerTabs(broker);
    let sawShipmentsApp = false;
    for (const tab of tabs) {
      const mw = await readArcbestMainWorld(tab.id);
      if (mw?.summaries?.length) {
        const loads = loadsFromSummaries(mw.summaries);
        if (loads.length) {
          return { status: "ok", loads, error: "", appName: mw.appName || "" };
        }
      }
      if (mw?.hasApp || (mw?.listLen || 0) > 0) {
        sawShipmentsApp = true;
        onBoard = true;
      }
      if (mw?.href && looksLikeLoginUrl(mw.href)) confirmedLogin = true;
      if (mw?.href && /\/shipments/i.test(mw.href)) onBoard = true;
    }
    if (sawShipmentsApp) onBoard = true;
  }

  // --- 4) Background cookie GraphQL / API ---
  let result;
  if (broker === "Arrive") result = await fetchArrive(opts);
  else if (broker === "RXO") result = await fetchRxo(opts);
  else if (broker === "ArcBest") result = await fetchArcbest(opts);
  else if (broker === "Echo") result = await fetchEcho(opts);
  else if (broker === "CHR") result = await fetchChr(opts);
  else result = { status: "error", loads: [], error: "unknown broker" };

  // If we clearly have an open board tab, do not let soft SW login HTML win
  if (result.status === "needs_login" && onBoard) {
    result = {
      status: "empty",
      loads: [],
      error: result.error || `${broker} open but 0 fresh loads`,
    };
  } else if (result.status === "needs_login") {
    confirmedLogin = true;
  }

  if (result.loads?.length) {
    const reused = shouldReuseLastGood(
      result.loads,
      store.lastGood?.[broker]?.loads,
      store.lastGood?.[broker]?.savedAt
    );
    if (reused && reused.length > result.loads.length) {
      return { status: "ok", loads: reused, error: "", keptPrevious: false };
    }
    return { status: "ok", loads: result.loads, error: "" };
  }

  // --- 5) lastGood / network-hook stash → STALE (not needs_login) ---
  if (store.lastGood?.[broker]?.loads?.length) {
    const reused = shouldReuseLastGood(
      [],
      store.lastGood[broker].loads,
      store.lastGood[broker].savedAt
    );
    if (reused) {
      return {
        status: "stale",
        loads: reused,
        error: confirmedLogin
          ? "sign in / open tab to refresh"
          : result.error || tabHint?.error || "open tab to refresh",
        keptPrevious: true,
      };
    }
  }

  if (confirmedLogin && !onBoard) {
    return {
      status: "needs_login",
      loads: [],
      error: result.error || tabHint?.error || `${broker} login required`,
    };
  }

  if (tabHint && tabHint.status && tabHint.status !== "needs_login") {
    return {
      status: result.status === "needs_login" ? "empty" : result.status || tabHint.status || "empty",
      loads: [],
      error: result.error || tabHint.error || "",
    };
  }

  if (result.status === "needs_login" && onBoard) {
    return { status: "empty", loads: [], error: result.error || "0 loads" };
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

      // Empty + soft fail: keep previous from storage — status becomes stale
      if (!loads.length) {
        const prev =
          store.sourceLoads?.[broker] || store.lastGood?.[broker]?.loads || [];
        if (
          prev.length &&
          ["needs_login", "error", "empty", "no_tab", "kept_previous", "listening", "stale"].includes(
            result.status
          )
        ) {
          loads = prev;
          result.keptPrevious = true;
          result.status = "stale";
          result.error = result.error || "sign in / open tab to refresh";
        }
      }

      // Honesty: fresh loads this scan → always ok; kept-only → stale
      if (loads.length && !result.keptPrevious) {
        result.status = "ok";
        result.error = "";
      } else if (loads.length && result.keptPrevious) {
        result.status = "stale";
        if (!result.error) result.error = "sign in / open tab to refresh";
      } else if (!loads.length && result.status !== "needs_login") {
        // leave empty/error/no_tab as-is; needs_login only when zero + confirmed wall
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

      meta[broker] = honestSourceMeta({
        status: result.status || "unknown",
        count,
        error: result.error || "",
        keptPrevious: !!result.keptPrevious,
        confirmedLogin: result.status === "needs_login" && count === 0,
      });
      state.sources[broker] = meta[broker];

      if (loads.length && !result.keptPrevious) {
        const lg = { ...(store.lastGood || {}) };
        lg[broker] = { loads, savedAt: Date.now() };
        store.lastGood = lg;
      }
    }

    if (sourceLoads.MoLo?.length) {
      const moloStale = !!meta.ArcBest?.keptPrevious;
      meta.MoLo = honestSourceMeta({
        status: moloStale ? "stale" : "ok",
        count: sourceLoads.MoLo.length,
        error: moloStale ? "sign in / open tab to refresh" : "",
        keptPrevious: moloStale,
      });
    } else if (meta.ArcBest && sourceLoads.MoLo) {
      // Explicit empty MoLo split — do not invent needs_login
      meta.MoLo = honestSourceMeta({
        status: meta.ArcBest.status === "needs_login" ? "empty" : (meta.ArcBest.status || "empty"),
        count: 0,
        error: "",
        keptPrevious: false,
      });
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

    // Absolute honesty pass before POST (covers any missed branch)
    for (const k of Object.keys(meta)) {
      meta[k] = honestSourceMeta(meta[k]);
    }

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
