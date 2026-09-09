"""Probe Echo pickup-date chip / calendar and try to set a range."""
from __future__ import annotations
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
DEBUG = Path(__file__).resolve().parent / "debug"
OUT = DEBUG / "echo-date-probe.json"

def main():
    report = {"steps": [], "api_count": None, "html_date": "", "errors": []}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = None
        for pg in ctx.pages:
            if "echo" in (pg.url or "").lower() and "available" in (pg.url or "").lower():
                page = pg
                break
        if not page:
            report["errors"].append("no echo tab")
            OUT.write_text(json.dumps(report, indent=2))
            print(json.dumps(report, indent=2)[:3000])
            return

        # Snapshot text around PICKUP DATE
        try:
            body = page.inner_text("body") or ""
            m = re.search(r"PICKUP DATE.{0,80}", body, re.I | re.S)
            report["html_date"] = m.group(0).replace("\n", " | ") if m else body[body.lower().find("pickup"):body.lower().find("pickup")+120]
        except Exception as e:
            report["errors"].append(str(e))

        # Find clickable elements mentioning Sep / Pickup / date
        try:
            cands = page.evaluate("""() => {
              const out = [];
              const els = [...document.querySelectorAll('button, a, div, span, mat-chip, [role=button], [class*=date], [class*=chip], [class*=calendar]')];
              for (const el of els) {
                const t = (el.innerText||el.textContent||'').trim().replace(/\\s+/g,' ');
                if (!t || t.length > 60) continue;
                if (/sep\\s*\\d|pickup date|pick.?up|calendar|date range|clear/i.test(t) || /^\\d{1,2}\\/\\d{1,2}/.test(t)) {
                  const r = el.getBoundingClientRect();
                  if (r.width < 2 || r.height < 2) continue;
                  out.push({tag: el.tagName, text: t, cls: (el.className||'').toString().slice(0,80), id: el.id||'', x: Math.round(r.x), y: Math.round(r.y)});
                }
              }
              return out.slice(0, 40);
            }""")
            report["candidates"] = cands
        except Exception as e:
            report["errors"].append(f"cands: {e}")

        payloads = []
        def on_resp(response):
            try:
                if "getOpenBoardLoads" in (response.url or ""):
                    payloads.append(response.json())
            except Exception:
                pass
        page.on("response", on_resp)

        # Try click text "Sep 4" or "PICKUP DATE"
        clicked = False
        for label in ("Sep 4", "PICKUP DATE", "Pickup Date", "Sep"):
            try:
                loc = page.get_by_text(label, exact=False)
                if loc.count() > 0:
                    loc.first.click(timeout=3000)
                    report["steps"].append(f"clicked text {label}")
                    clicked = True
                    page.wait_for_timeout(800)
                    break
            except Exception as e:
                report["steps"].append(f"click {label} fail: {e}")

        # After open, dump calendar-ish inputs / days
        try:
            report["after_open"] = page.evaluate("""() => {
              const cal = document.querySelector('mat-calendar, .calendar, [class*=datepicker], [class*=DatePicker], mat-datepicker-content');
              const days = [...document.querySelectorAll('button, td, .mat-calendar-body-cell')].slice(0,30).map(el => (el.innerText||'').trim()).filter(Boolean);
              const inputs = [...document.querySelectorAll('input')].map(el => ({id:el.id, ph:el.placeholder, v:el.value, fc:el.getAttribute('formcontrolname')}));
              return {hasCal: !!cal, calCls: cal ? cal.className : '', days: days.slice(0,20), inputs: inputs.filter(i=>i.id||i.fc||i.ph).slice(0,20)};
            }""")
        except Exception as e:
            report["errors"].append(f"after: {e}")

        # Try selecting days 8 and 11 if calendar cells visible
        try:
            # click day 8 then 11 in calendar
            for day in ("8", "11"):
                cell = page.locator(f"button.mat-calendar-body-cell:has-text('{day}'), td >> text='{day}', [aria-label*='Sep {day}'], [aria-label*='September {day}']")
                if cell.count() > 0:
                    cell.first.click(timeout=2000)
                    report["steps"].append(f"clicked day {day}")
                    page.wait_for_timeout(300)
        except Exception as e:
            report["steps"].append(f"day click: {e}")

        # Click Search
        try:
            btn = page.locator("#save-search")
            if btn.count():
                page.evaluate("""() => { const b=document.querySelector('#save-search'); if(b){b.disabled=false;b.removeAttribute('disabled');}}""")
                btn.first.click(timeout=5000, force=True)
                report["steps"].append("clicked search")
                page.wait_for_timeout(5000)
        except Exception as e:
            report["steps"].append(f"search: {e}")

        for _ in range(20):
            if payloads:
                break
            page.wait_for_timeout(400)
        if payloads:
            data = payloads[-1].get("data") or {}
            report["api_count"] = data.get("count")
            items = data.get("items") or []
            report["api_items"] = len(items)
            if items:
                stops = items[0].get("loadStops") or []
                pick = next((s for s in stops if str(s.get("stopType","")).lower()=="pick"), None)
                report["sample_date"] = (pick or {}).get("appointmentTime")
        try:
            report["body_snip"] = re.sub(r"\s+", " ", (page.inner_text("body") or ""))[:400]
        except Exception:
            pass

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:5000])

if __name__ == "__main__":
    main()
