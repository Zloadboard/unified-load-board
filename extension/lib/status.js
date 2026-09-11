/**
 * Honest per-source status for board + popup.
 * Rules:
 *  - loads/count > 0 this scan (not keptPrevious) → ok
 *  - loads/count > 0 only via kept previous → stale
 *  - needs_login ONLY when count === 0 AND confirmed login wall
 *  - Never advertise needs_login when count > 0
 */
export function honestSourceMeta({ status, count, error, keptPrevious, confirmedLogin }) {
  const n = typeof count === "number" && Number.isFinite(count) ? Math.max(0, count) : 0;
  const kept = !!keptPrevious;
  let st = String(status || "unknown");
  let err = error != null ? String(error) : "";

  if (n > 0) {
    if (kept) {
      st = "stale";
      if (!err) err = "sign in / open tab to refresh";
    } else {
      st = "ok";
      err = "";
    }
  } else {
    // Zero loads: needs_login only with confirmed wall
    if (st === "needs_login" && confirmedLogin === false) {
      st = "empty";
    }
    if (st === "needs_login" && !err) err = "login required";
    if (st === "kept_previous") st = "stale";
  }

  // Absolute guard
  if (n > 0 && st === "needs_login") {
    st = kept ? "stale" : "ok";
  }

  return {
    status: st,
    count: n,
    error: err,
    keptPrevious: kept,
  };
}

/** Sanitize a sources map in place / return copy (for POST bodies + last_scan). */
export function sanitizeSourcesMap(sources) {
  const out = {};
  if (!sources || typeof sources !== "object") return out;
  for (const [name, raw] of Object.entries(sources)) {
    if (!raw || typeof raw !== "object") continue;
    const count =
      typeof raw.count === "number"
        ? raw.count
        : Array.isArray(raw.loads)
          ? raw.loads.length
          : 0;
    out[name] = honestSourceMeta({
      status: raw.status,
      count,
      error: raw.error || "",
      keptPrevious: !!(raw.keptPrevious || raw.kept_previous),
      confirmedLogin: raw.confirmedLogin,
    });
  }
  return out;
}
