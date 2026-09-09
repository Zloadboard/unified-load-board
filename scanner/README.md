# Load board scanner (Arrive · RXO · ArcBest)

Polls the three carrier portals on **your PC’s network** (not a cloud proxy), keeps a persistent Edge login profile, and writes merged results to `../loads.json` for the unified table.

## Setup (once)

From this `scanner` folder:

```bat
pip install -r requirements.txt
playwright install msedge
```

Use the same Python you’ll run with (`py -3` or `python`).

## 1) Log in once

Double-click **`START_LOGIN.bat`** (or `py -3 login.py`).

- Edge opens with Arrive, RXO Connect, and ArcBest tabs.
- Sign into all three (complete MFA if needed).
- Return to the terminal and **press Enter** to save the session into `browser_profile/`.

No credentials are stored in this repo — only the browser profile cookies/storage on disk.

## 2) Start the scanner

Double-click **`START_SCANNER.bat`** (or `py -3 scan.py`).

- Reuses the saved Edge profile (headed by default so you can see/fix MFA).
- Every ~60 seconds visits each board, extracts loads (API JSON listener, then DOM heuristics), and writes `../loads.json`.
- Optional: `py -3 scan.py --headless` or `py -3 scan.py --once`.

## 3) View the table

From the parent folder (`unified-load-board`), double-click **`START_TABLE.bat`**.

Opens http://localhost:8765/ and serves `index.html` + `loads.json`. Reload the browser tab after scans (or leave it open and refresh).

## Notes / ToS

- **Personal use on your own carrier accounts only.** Respect each portal’s Terms of Service.
- Arrive often blocks cloud/proxy IPs — that is why this runs **locally on your Windows PC**, not from a datacenter.
- Do not share `browser_profile/` (it holds your login session).
- If a source shows a login wall or network error, that source is skipped for the cycle; re-run `START_LOGIN.bat` if sessions expire.
- Debug dumps: `debug/<source>-last.html` and `debug/last_api_urls.txt` (for tuning parsers).

## Config

Edit `config.json` for interval, headed mode, output path, and URLs:

```json
{
  "interval_seconds": 60,
  "headed": true,
  "output": "../loads.json",
  "sources": { ... }
}
```
