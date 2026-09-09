"""One-shot: attach CDP, dump Echo form fields, run Romeoville search, save API body."""
from __future__ import annotations
import json, re, time
from datetime import date, timedelta
from pathlib import Path

from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
DEBUG = Path(__file__).resolve().parent / "debug"
DEBUG.mkdir(exist_ok=True)
OUT = DEBUG / "echo-probe.json"

def main():
    report = {"inputs": [], "api": None, "url": "", "errors": []}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            u = (pg.url or "").lower()
            if "echo" in u and ("available" in u or "load" in u):
                page = pg
                break
        if page is None:
            # open available loads
            page = ctx.new_page()
            page.goto("https://echodrive.echo.com/carrier/10261/availableLoads", wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(3000)
        report["url"] = page.url

        # dump inputs
        try:
            report["inputs"] = page.evaluate("""() => [...document.querySelectorAll('input,select')].map(el => ({
              tag: el.tagName, type: el.type||'', id: el.id||'', name: el.name||'',
              placeholder: el.placeholder||'', aria: el.getAttribute('aria-label')||'',
              formcontrol: el.getAttribute('formcontrolname')||'',
              value: (el.value||'').slice(0,80),
              visible: !!(el.offsetWidth||el.offsetHeight)
            })).filter(x => x.visible || x.id || x.formcontrol || /date|origin|pickup|dh|equip|mile/i.test(JSON.stringify(x)))
            """)
        except Exception as e:
            report["errors"].append(f"inputs: {e}")

        payloads = []
        def on_response(response):
            try:
                u = response.url or ""
                if "getOpenBoardLoads" not in u:
                    return
                body = response.json()
                payloads.append({"url": u, "body": body})
            except Exception:
                pass
        page.on("response", on_response)

        # Fill origin Romeoville + 100
        try:
            origin = page.locator("#origin-field-input")
            if origin.count():
                origin.click(timeout=3000)
                origin.fill("")
                origin.type("Romeoville, IL", delay=40)
                page.wait_for_timeout(800)
                for sel in (".pac-item", "[role='option']", "mat-option"):
                    opts = page.locator(sel)
                    if opts.count() > 0:
                        opts.first.click(timeout=2000)
                        break
                else:
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                page.wait_for_timeout(400)
            dh = page.locator("#origin-dh-field-input")
            if dh.count():
                dh.fill("100")
            # Clear date fields if any — empty search for next 7 days via UI if present
            start = date.today()
            end = start + timedelta(days=7)
            start_s = f"{start.month:02d}/{start.day:02d}/{start.year}"
            end_s = f"{end.month:02d}/{end.day:02d}/{end.year}"
            # try common date ids from dumped inputs later; also write values into first two date-looking inputs
            page.evaluate("""(args) => {
              const [a,b] = args;
              const inputs = [...document.querySelectorAll('input')].filter(el => {
                const t = ((el.placeholder||'')+' '+(el.getAttribute('aria-label')||'')+' '+(el.id||'')+' '+(el.getAttribute('formcontrolname')||'')).toLowerCase();
                return (el.type||'')==='date' || /date|pickup|available|start|end/.test(t);
              });
              const set = (el,v) => { if(!el) return; el.focus(); el.value=v;
                el.dispatchEvent(new Event('input',{bubbles:true}));
                el.dispatchEvent(new Event('change',{bubbles:true})); };
              // Prefer NOT zeroing results: set a wide window today..+7
              if (inputs[0]) set(inputs[0], a);
              if (inputs[1]) set(inputs[1], b);
              return inputs.map(el => el.id||el.getAttribute('formcontrolname')||el.placeholder||el.type);
            }""", [start_s, end_s])

            btn = page.locator("#save-search")
            if btn.count():
                for _ in range(20):
                    if not btn.first.is_disabled():
                        break
                    page.wait_for_timeout(400)
                if btn.first.is_disabled():
                    page.evaluate("""() => { const b=document.querySelector('#save-search'); if(b){b.disabled=false;b.removeAttribute('disabled');}}""")
                btn.first.click(timeout=8000, force=True)
                page.wait_for_timeout(5000)
        except Exception as e:
            report["errors"].append(f"search: {e}")

        # wait for API
        for _ in range(25):
            if payloads:
                break
            page.wait_for_timeout(400)

        if payloads:
            body = payloads[-1]["body"]
            data = body.get("data") if isinstance(body, dict) else None
            items = (data or {}).get("items") if isinstance(data, dict) else []
            report["api"] = {
                "url": payloads[-1]["url"][:200],
                "count": (data or {}).get("count") if isinstance(data, dict) else None,
                "items": len(items) if isinstance(items, list) else None,
                "first_pu": None,
            }
            if isinstance(items, list) and items:
                stops = items[0].get("loadStops") or []
                pick = next((s for s in stops if str(s.get("stopType","")).lower()=="pick"), stops[0] if stops else {})
                appt = (pick.get("appointmentTime") or {})
                report["api"]["first_pu"] = {
                    "city": pick.get("city"), "state": pick.get("state"),
                    "start": appt.get("startTime"),
                }
            (DEBUG / "echo-api.json").write_text(json.dumps({"count": report["api"].get("items"), "body": body}, indent=2)[:500000], encoding="utf-8")
        else:
            report["errors"].append("no getOpenBoardLoads response")

        # header text
        try:
            report["body_snip"] = (page.inner_text("body") or "")[:500]
        except Exception:
            pass

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:4000])

if __name__ == "__main__":
    main()
