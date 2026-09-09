"""Set Echo pickup calendar to Sep 8-11 2026, Search, print API count."""
from __future__ import annotations
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
DEBUG = Path(__file__).resolve().parent / "debug"

def main():
    report = {"steps": [], "api_count": None, "items": 0, "body": ""}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        page = None
        for pg in browser.contexts[0].pages:
            if "echo" in (pg.url or "").lower() and "available" in (pg.url or "").lower():
                page = pg
                break
        if not page:
            print("NO_ECHO_TAB")
            return

        payloads = []
        def on_resp(response):
            try:
                if "getOpenBoardLoads" in (response.url or ""):
                    payloads.append(response.json())
            except Exception:
                pass
        page.on("response", on_resp)

        # Ensure origin
        try:
            o = page.locator("#origin-field-input")
            if o.count():
                val = o.input_value()
                if "romeoville" not in (val or "").lower():
                    o.fill("")
                    o.type("Romeoville, IL", delay=40)
                    page.wait_for_timeout(700)
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
            dh = page.locator("#origin-dh-field-input")
            if dh.count():
                dh.fill("100")
            report["steps"].append("origin ok")
        except Exception as e:
            report["steps"].append(f"origin {e}")

        # Open calendar
        btn = page.locator("#pickup-dates-dropdown-button")
        btn.first.click(timeout=5000)
        page.wait_for_timeout(600)
        report["steps"].append("opened calendar")

        # Click RESET first for clean range
        try:
            page.get_by_text("RESET", exact=True).first.click(timeout=2000)
            report["steps"].append("reset")
            page.wait_for_timeout(300)
            # reopen
            btn.first.click(timeout=3000)
            page.wait_for_timeout(400)
        except Exception as e:
            report["steps"].append(f"reset skip {e}")

        # Click day cells 8 and 11 inside dates-dropdown
        menu = page.locator(".dates-dropdown, .pickup-dates-dropdown .dropdown-menu")
        for day in (8, 11):
            try:
                # prefer cells that are just the day number in the SEP grid
                cell = menu.locator(f"text='{day}'")
                # if multiple (AUG 31 etc), pick visible in menu
                n = cell.count()
                report["steps"].append(f"day {day} candidates={n}")
                if n:
                    # click the last matching in September area — try each until click works
                    cell.nth(min(n - 1, 1) if day == 8 else n - 1).click(timeout=2000)
                    # better: evaluate click on .dates-dropdown elements with exact text
                page.wait_for_timeout(250)
            except Exception as e:
                report["steps"].append(f"day {day} {e}")

        # More reliable: JS click days in .dates-dropdown
        clicked = page.evaluate("""() => {
          const menu = document.querySelector('.dates-dropdown') || document.querySelector('.dropdown-menu.dates-dropdown');
          if (!menu) return {ok:false, reason:'no menu'};
          const nodes = [...menu.querySelectorAll('td, button, div, span, a')];
          const clickDay = (d) => {
            const el = nodes.find(n => (n.innerText||'').trim() === String(d) && n.children.length === 0);
            if (el) { el.click(); return true; }
            const el2 = nodes.find(n => (n.innerText||'').trim() === String(d));
            if (el2) { el2.click(); return true; }
            return false;
          };
          return {ok: true, d8: clickDay(8), d11: clickDay(11), menuText: (menu.innerText||'').slice(0,120)};
        }""")
        report["steps"].append(f"js click {clicked}")
        page.wait_for_timeout(400)

        # click outside / search
        s = page.locator("#save-search")
        page.evaluate("""() => { const b=document.querySelector('#save-search'); if(b){b.disabled=false;b.removeAttribute('disabled');}}""")
        s.first.click(force=True, timeout=8000)
        report["steps"].append("search")
        page.wait_for_timeout(6000)

        for _ in range(20):
            if payloads:
                break
            page.wait_for_timeout(400)

        if payloads:
            data = payloads[-1].get("data") or {}
            items = data.get("items") or []
            report["api_count"] = data.get("count")
            report["items"] = len(items)
            (DEBUG / "echo-api.json").write_text(json.dumps({"count": len(items), "body": payloads[-1]}, indent=2)[:400000], encoding="utf-8")
            if items:
                stops = items[0].get("loadStops") or []
                pick = next((x for x in stops if str(x.get("stopType","")).lower()=="pick"), {})
                report["sample"] = {"city": pick.get("city"), "appt": pick.get("appointmentTime")}
        try:
            report["body"] = (page.inner_text("body") or "").replace("\n", " | ")[:300]
            # pickup date label
            import re
            m = re.search(r"PICKUP DATE\s*\|\s*([^|]+)", report["body"])
            report["pickup_label"] = m.group(1).strip() if m else ""
        except Exception:
            pass

    print(json.dumps(report, indent=2)[:4000])
    (DEBUG / "echo-set-dates.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
