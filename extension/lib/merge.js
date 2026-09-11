/** Per-source last-good merge helpers. */

const LAST_GOOD_MAX_AGE_MS = 10 * 60 * 1000;

export function groupBySource(loads) {
  const by = {};
  for (const L of loads || []) {
    if (!L || !L.source) continue;
    (by[L.source] ||= []).push(L);
  }
  return by;
}

export function dedupeById(loads) {
  const seen = new Map();
  const out = [];
  for (const L of loads || []) {
    const id = String(L?.id || "");
    if (id) {
      if (seen.has(id)) {
        const prev = seen.get(id);
        // Prefer row with pickup_date
        if (!prev.pickup_date && L.pickup_date) {
          const i = out.indexOf(prev);
          if (i >= 0) out[i] = L;
          seen.set(id, L);
        }
        continue;
      }
      seen.set(id, L);
    }
    out.push(L);
  }
  return out;
}

/**
 * Merge sources into one loads array.
 * emptySources: keep previous loads for that source if status is needs_login/error/empty.
 */
export function mergeSources(sourceLoads, previousLoads, sourceMeta) {
  const prevBy = groupBySource(previousLoads);
  const out = [];
  const sources = new Set([
    ...Object.keys(sourceLoads || {}),
    ...Object.keys(prevBy),
    "Arrive",
    "RXO",
    "ArcBest",
    "MoLo",
    "Echo",
    "CHR",
  ]);
  for (const src of sources) {
    const fresh = sourceLoads[src] || [];
    const meta = (sourceMeta && sourceMeta[src]) || {};
    const status = meta.status || "unknown";
    if (fresh.length > 0) {
      out.push(...fresh);
      continue;
    }
    // Keep last-good for empty / needs_login / error (do not wipe)
    if (
      ["needs_login", "error", "empty", "kept_previous", "no_tab", "stale", "listening"].includes(status) ||
      meta.keepPrevious
    ) {
      const prev = prevBy[src] || [];
      if (prev.length) out.push(...prev);
    }
  }
  return dedupeById(out);
}

export function shouldReuseLastGood(newLoads, lastGood, savedAt) {
  if (!lastGood || !lastGood.length || !savedAt) return null;
  const age = Date.now() - savedAt;
  if (age >= LAST_GOOD_MAX_AGE_MS) return null;
  const n = (newLoads || []).length;
  const last = lastGood.length;
  if (n === 0) return lastGood;
  if (n < Math.max(5, Math.floor(last * 0.5))) {
    // merge prefer new
    const by = new Map();
    for (const L of lastGood) by.set(String(L.id || ""), L);
    for (const L of newLoads) by.set(String(L.id || ""), L);
    return [...by.values()];
  }
  return null;
}
