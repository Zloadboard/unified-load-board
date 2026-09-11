/** Page-world network hook — posts interesting XHR/fetch JSON to content script. */
(function () {
  if (window.__ULB_HOOK__) return;
  window.__ULB_HOOK__ = true;
  const INTERESTING =
    /graphql|getloads|loadboard|getopenboardloads|booknowprice|availableload|shipment|navisphere|search\/loadboard|loads/i;

  function emit(url, method, body, reqBody) {
    try {
      window.postMessage(
        {
          source: "ulb-extension-hook",
          url: String(url || ""),
          method: String(method || "GET"),
          body,
          requestBody: reqBody != null ? String(reqBody).slice(0, 200000) : null,
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
        const url = typeof req === "string" ? req : req && req.url;
        const method =
          (args[1] && args[1].method) || (req && req.method) || "GET";
        const reqBody = (args[1] && args[1].body) || null;
        if (url && INTERESTING.test(url)) {
          const clone = res.clone();
          const ct = (clone.headers.get("content-type") || "").toLowerCase();
          if (ct.includes("json") || INTERESTING.test(url)) {
            clone
              .json()
              .then((body) => emit(url, method, body, reqBody))
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
            emit(_url, _method, parsed, _reqBody);
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
