/** Normalize broker rows into the board load shape (matches scanner/extract.py). */

export const VALID_SOURCES = new Set(["Arrive", "RXO", "ArcBest", "MoLo", "Echo", "CHR"]);

export const BROKER_URLS = {
  Arrive: "https://carrier.arrivelogistics.com/find-loads",
  RXO: "https://carrier.rxoconnect.rxo.com/loads/available-loads",
  ArcBest: "https://carriers.arcb.com/Shipments",
  Echo: "https://echodrive.echo.com/carrier/10261/availableLoads",
  CHR: "https://www.navispherecarrier.com/",
};

export function nowIsoZ() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function asStr(v) {
  if (v == null) return "";
  if (typeof v === "string") return v.trim();
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function asNum(v) {
  if (v == null || v === "") return null;
  if (typeof v === "number" && !Number.isNaN(v)) return v;
  const s = String(v).replace(/[$,]/g, "").trim();
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function normalizeLoad(raw, source, defaultUrl = "") {
  if (!VALID_SOURCES.has(source)) throw new Error("bad source " + source);
  const origin = asStr(
    raw.origin || raw.pickupCity || raw.pickup_city || raw.PickupCity || ""
  );
  const destination = asStr(
    raw.destination || raw.deliveryCity || raw.delivery_city || raw.DeliveryCity || ""
  );
  const pickup_date = asStr(raw.pickupDate || raw.pickup_date || "");
  const pickup_time = asStr(raw.pickupTime || raw.pickup_time || "");
  const delivery_date = asStr(raw.deliveryDate || raw.delivery_date || "");
  const delivery_time = asStr(raw.deliveryTime || raw.delivery_time || "");
  let lid = asStr(raw.id || raw.loadId || raw.LoadBoardId || raw.loadBoardId || "");
  if (!lid) {
    lid = `${source.slice(0, 3).toUpperCase()}-${Math.abs(
      hashCode(origin + "|" + destination + "|" + pickup_date)
    ) % 10_000_000}`;
  }
  const pickup =
    asStr(typeof raw.pickup === "string" ? raw.pickup : "") ||
    [pickup_date, pickup_time].filter(Boolean).join(" ");
  const delivery =
    asStr(typeof raw.delivery === "string" ? raw.delivery : "") ||
    [delivery_date, delivery_time].filter(Boolean).join(" ");
  let miles = asNum(raw.miles ?? raw.Miles ?? raw.loadedMiles);
  if (miles != null && miles === Math.floor(miles)) miles = Math.floor(miles);
  return {
    id: lid,
    source,
    pickup_city: asStr(raw.pickupCity || raw.pickup_city) || origin,
    delivery_city: asStr(raw.deliveryCity || raw.delivery_city) || destination,
    origin: origin || asStr(raw.pickupCity || raw.pickup_city),
    destination: destination || asStr(raw.deliveryCity || raw.delivery_city),
    pickup_date,
    pickup_time,
    delivery_date,
    delivery_time,
    pickup,
    delivery,
    weight: raw.weight != null && raw.weight !== "" ? raw.weight : "",
    pallets: raw.pallets != null && raw.pallets !== "" ? raw.pallets : "",
    equipment: asStr(raw.equipment || raw.EquipmentType || raw.equipmentType),
    miles,
    rate: asNum(raw.rate ?? raw.TopSpend ?? raw.bookNowPrice ?? raw.suggestedRate),
    status: asStr(raw.status || raw.LoadStatus),
    url: asStr(raw.url) || defaultUrl || "",
    notes: asStr(raw.notes),
    first_seen_at: asStr(raw.first_seen_at) || "",
    seen_age: asStr(raw.seen_age) || "",
  };
}

function hashCode(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

/** True when the URL itself is clearly an auth wall (not a board SPA). */
export function looksLikeLoginUrl(url = "") {
  const u = (url || "").toLowerCase();
  if (!u) return false;
  // Board paths that sometimes contain "login" in query/hash — exclude them
  if (
    /find-loads|available-?loads|shipment|loadboard|getloads|navispherecarrier|carriers\.arcb|echodrive\.echo\.com\/carrier/i.test(
      u
    )
  ) {
    return false;
  }
  return /login\.id\.rxo|auth0\.com|\/u\/login|okta\.com|\/signin|\/sign-in|\/login(\?|$|\/)|multifactor|sso\./i.test(
    u
  );
}

export function looksLikeLoginHtml(text, url = "") {
  if (looksLikeLoginUrl(url)) return true;
  const t = (text || "").toLowerCase().slice(0, 12000);
  if (!(t.includes("<html") || t.includes("<!doctype"))) return false;
  // SPA shells often mention "password" in bundled JS — require stronger signals
  const strongLogin =
    /sign\s*in\s*to\s+(your|continue)|log\s*in\s*to\s+(your|continue)|enter your password|forgot (your )?password|one-time code|verification code|enter your 6-digit|welcome back.*password/i.test(
      t
    ) ||
    (/<form[^>]{0,200}(login|signin|sign-in|auth)/i.test(text || "") &&
      /type=["']password["']/i.test(text || ""));
  const boardMarkers =
    /find-loads|available.?loads|shipmentsummar|loadboard|getloads|navisphere|shipments list|open board/i.test(
      t
    );
  return strongLogin && !boardMarkers;
}

/**
 * Soft login detector — avoid false positives on SPA HTML shells and GraphQL
 * error JSON that happens to mention auth words.
 */
export function isLoginResponse(status, contentType, text, url) {
  if (status === 401 || status === 403) return true;
  if (looksLikeLoginUrl(url)) return true;
  const ct = (contentType || "").toLowerCase();
  // JSON GraphQL / API errors are NOT login walls unless status already caught above
  if (ct.includes("application/json") || ct.includes("+json")) {
    try {
      const j = JSON.parse(text || "");
      // Some APIs return 200 + { errors: [{ message: "Unauthorized" }] }
      const errs = j && (j.errors || j.error);
      if (errs) {
        const msg = JSON.stringify(errs).toLowerCase();
        if (
          /unauthori[sz]ed|not authenticated|session expired|please log ?in|invalid.?token|jwt expired/.test(
            msg
          ) &&
          !/forbidden.*field|validation|bad request/.test(msg)
        ) {
          return true;
        }
      }
    } catch {
      /* ignore */
    }
    return false;
  }
  if (ct.includes("text/html") && looksLikeLoginHtml(text, url)) return true;
  return false;
}
