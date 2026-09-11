/** Page-world network hook — posts interesting XHR/fetch JSON to content script. */
(function () {
  if (window.__ULB_HOOK__) return;
  window.__ULB_HOOK__ = true;
  const INTERESTING =
    /graphql|getloads|loadboard|getopenboardloads|booknowprice|availableload|shipment|navisphere|search\/loadboard|loads/i;

  function headersToObject(h) {
    try {
      if (!h) return null;
      if (h instanceof Headers) {
        const o = {};
        h.forEach((v, k) => {
          o[k] = v;
        });
        return o;
      }
      if (Array.isArray(h)) {
        const o = {};
        for (const pair of h) {
          if (pair && pair.length >= 2) o[String(pair[0]).toLowerCase()] = String(pair[1]);
        }
        return o;
      }
      if (typeof h === "object") {
        const o = {};
        for (const [k, v] of Object.entries(h)) o[String(k).toLowerCase()] = String(v);
        return o;
      }
    } catch (_) {}
    return null;
  }

  function emit(url, method, body, reqBody, reqHeaders) {
    try {
      window.postMessage(
        {
          source: "ulb-extension-hook",
          url: String(url || ""),
          method: String(method || "GET"),
          body,
          requestBody: reqBody != null ? String(reqBody).slice(0, 200000) : null,
          requestHeaders: reqHeaders || null,
        },
        "*"
      );
    } catch (_) {}
  }

  const origFetch = window.fetch;
  if (typeof origFetch === "function") {
    window.fetch = async function (...args) {
      const res = await origFetch.apply(this, args);
      try {
        const req = args[0];
        const init = args[1] || {};
        const url = typeof req === "string" ? req : req && req.url;
        const method = init.method || (req && req.method) || "GET";
        const reqBody = init.body != null ? init.body : null;
        let reqHeaders = headersToObject(init.headers);
        if (!reqHeaders && req && typeof req.headers !== "undefined") {
          reqHeaders = headersToObject(req.headers);
        }
        if (url && INTERESTING.test(url)) {
          const clone = res.clone();
          const ct = (clone.headers.get("content-type") || "").toLowerCase();
          if (ct.includes("json") || INTERESTING.test(url)) {
            clone
              .json()
              .then((body) => emit(url, method, body, reqBody, reqHeaders))
              .catch(() => {});
          }
        }
      } catch (_) {}
      return res;
    };
  }

  const OrigXHR = window.XMLHttpRequest;
  if (OrigXHR) {
    function Wrapped() {
      const xhr = new OrigXHR();
      let _url = "";
      let _method = "GET";
      let _reqBody = null;
      const open = xhr.open;
      xhr.open = function (method, url, ...rest) {
        _method = method;
        _url = url;
        return open.call(xhr, method, url, ...rest);
      };
      const send = xhr.send;
      xhr.send = function (body) {
        _reqBody = body;
        xhr.addEventListener("load", function () {
          try {
            if (!_url || !INTERESTING.test(_url)) return;
            const ct = (xhr.getResponseHeader("content-type") || "").toLowerCase();
            if (!ct.includes("json") && !INTERESTING.test(_url)) return;
            let parsed = null;
            try {
              parsed = JSON.parse(xhr.responseText);
            } catch (_) {
              return;
            }
            emit(_url, _method, parsed, _reqBody, null);
          } catch (_) {}
        });
        return send.call(xhr, body);
      };
      return xhr;
    }
    Wrapped.prototype = OrigXHR.prototype;
    window.XMLHttpRequest = Wrapped;
  }
})();
