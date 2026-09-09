from __future__ import annotations
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

CDP = "http://127.0.0.1:9222"
OUT = Path(__file__).resolve().parent / "debug" / "echo-dropdown-probe.json"

def main():
    report = {"steps": [], "dropdown": None, "api": None}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP)
        page = None
        for pg in browser.contexts[0].pages:
            if "echo" in (pg.url or "").lower() and "available" in (pg.url or "").lower():
                page = pg
                break
        if not page:
            report["steps"].append("no page")
            OUT.write_text(json.dumps(report, indent=2))
            print(report)
            return

        payloads = []
        page.on("response", lambda r: payloads.append(r) if "getOpenBoardLoads" in (r.url or "") else None)

        btn = page.locator("#pickup-dates-dropdown-button")
        report["steps"].append(f"btn count={btn.count()}")
        if btn.count():
            btn.first.click(timeout=5000)
            page.wait_for_timeout(1000)
            report["steps"].append("clicked dropdown")

        report["dropdown"] = page.evaluate("""() => {
          const menus = [...document.querySelectorAll('[class*=dropdown], [class*=menu], [class*=popover], [role=menu], [role=listbox], .cdk-overlay-pane, mat-option')];
          const items = [];
          for (const m of menus) {
            const t = (m.innerText||'').trim();
            if (!t || t.length > 500) continue;
            const r = m.getBoundingClientRect();
            if (r.width < 5) continue;
            items.push({cls: (m.className||'').toString().slice(0,100), text: t.slice(0,300), y: Math.round(r.y)});
          }
          // all visible buttons/options after open
          const opts = [...document.querySelectorAll('button, [role=option], mat-option, li, a')].map(el => {
            const t=(el.innerText||'').trim().replace(/\\s+/g,' ');
            if (!t || t.length>80) return null;
            const r=el.getBoundingClientRect();
            if (r.width<5||r.height<5) return null;
            return t;
          }).filter(Boolean);
          return {menus: items.slice(0,20), opts: [...new Set(opts)].slice(0,60)};
        }""")

        # Try click common range labels
        for label in ("Next 7 Days", "Next 7 days", "7 Days", "This Week", "Custom", "Date Range", "All Dates", "Any Date", "Clear"):
            try:
                loc = page.get_by_text(label, exact=False)
                if loc.count() > 0:
                    loc.first.click(timeout=2000)
                    report["steps"].append(f"clicked option {label}")
                    page.wait_for_timeout(500)
                    break
            except Exception as e:
                report["steps"].append(f"{label}: {e}")

        # Search again
        try:
            s = page.locator("#save-search")
            if s.count():
                page.evaluate("""() => { const b=document.querySelector('#save-search'); if(b){b.disabled=false;b.removeAttribute('disabled');}}""")
                s.first.click(force=True)
                report["steps"].append("search")
                page.wait_for_timeout(5000)
        except Exception as e:
            report["steps"].append(f"search {e}")

        # collect API from listener - need wrap
        # re-listen simply by reading last network via evaluate hard; instead wait and check body
        try:
            report["body"] = (page.inner_text("body") or "").replace("\n", " | ")[:350]
        except Exception:
            pass

        # Take screenshot path
        shot = Path(__file__).resolve().parent / "debug" / "echo-date-ui.png"
        try:
            page.screenshot(path=str(shot), full_page=False)
            report["screenshot"] = str(shot)
        except Exception as e:
            report["steps"].append(f"shot {e}")

    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)[:6000])

if __name__ == "__main__":
    main()
