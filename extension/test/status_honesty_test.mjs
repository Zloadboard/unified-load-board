import { honestSourceMeta, sanitizeSourcesMap } from "../lib/status.js";

function assert(cond, msg) {
  if (!cond) throw new Error(msg);
}

// Fresh loads → ok
let m = honestSourceMeta({ status: "needs_login", count: 20, error: "RXO login required", keptPrevious: false });
assert(m.status === "ok" && m.count === 20 && m.error === "", "fresh loads must be ok, got " + JSON.stringify(m));

// Kept previous → stale (never needs_login)
m = honestSourceMeta({ status: "needs_login", count: 83, error: "CHR login", keptPrevious: true });
assert(m.status === "stale" && m.count === 83, "kept+count → stale, got " + JSON.stringify(m));

m = honestSourceMeta({ status: "error", count: 10, error: "x", keptPrevious: true });
assert(m.status === "stale", "error+kept → stale");

// Zero + confirmed login → needs_login
m = honestSourceMeta({ status: "needs_login", count: 0, error: "login", keptPrevious: false, confirmedLogin: true });
assert(m.status === "needs_login" && m.count === 0, "zero+login ok");

// Zero without confirmedLogin flag still allows needs_login if status says so
m = honestSourceMeta({ status: "needs_login", count: 0, error: "", keptPrevious: false });
assert(m.status === "needs_login", "zero needs_login preserved");

// Empty ok
m = honestSourceMeta({ status: "empty", count: 0, error: "", keptPrevious: false });
assert(m.status === "empty", "empty");

// Sanitize map — the exact last_scan lie we saw live
const sanitized = sanitizeSourcesMap({
  Arrive: { status: "needs_login", count: 0, error: "Arrive login required", keptPrevious: false },
  RXO: { status: "needs_login", count: 20, error: "RXO login required", keptPrevious: true },
  ArcBest: { status: "needs_login", count: 0, error: "ArcBest login required", keptPrevious: false },
  Echo: { status: "needs_login", count: 10, error: "Echo login required", keptPrevious: true },
  CHR: { status: "needs_login", count: 83, error: "CHR login", keptPrevious: true },
});
assert(sanitized.RXO.status === "stale" && sanitized.RXO.count === 20, "RXO sanitized");
assert(sanitized.Echo.status === "stale", "Echo sanitized");
assert(sanitized.CHR.status === "stale", "CHR sanitized");
assert(sanitized.Arrive.status === "needs_login" && sanitized.Arrive.count === 0, "Arrive zero login ok");
assert(sanitized.ArcBest.status === "needs_login", "ArcBest zero login ok");

console.log("status_honesty_test: all passed");
