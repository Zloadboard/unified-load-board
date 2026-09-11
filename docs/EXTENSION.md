# Chrome extension — Unified Load Board Scanner

**Preferred daily path.** Sign into brokers in **normal Chrome**. No CDP / scanner profile window.

**Current version: 1.0.2**

## Download

| Where | URL |
|-------|-----|
| Work PC board | [http://localhost:8765/extension/ulb-extension.zip](http://localhost:8765/extension/ulb-extension.zip) |
| Same folder in repo | `extension/ulb-extension.zip` |
| GitHub Pages (after publish) | `…/docs/ulb-extension.zip` or `…/extension/ulb-extension.zip` |

Chrome Web Store is **not** required for v1 (unpacked / Load unpacked). Store packaging can come later if you want one-click install for others.

## Install (once per Chrome profile)

1. Download **ulb-extension.zip**.
2. Unzip it to a stable folder, e.g.  
   `C:\Users\Disp\Desktop\unified-load-board\extension\`  
   You should see `manifest.json` inside that folder (not nested an extra level).
3. Open Chrome → go to `chrome://extensions`
4. Turn on **Developer mode** (top right).
5. Click **Load unpacked**.
6. Select the unzipped **`extension`** folder (the one that contains `manifest.json`).
7. Pin the extension if you like (puzzle icon → pin).

**After updates:** overwrite the folder (or pull), then click **Reload** on `chrome://extensions`. Then open each broker board tab once and hit **Scan now**.

## Daily use

1. Leave **normal Chrome** open (the profile where the extension is installed).
2. Ensure `serve_board.py` is running (`SILENT_START.vbs` / Task Scheduler — board only, no CDP).
3. Open the board: [http://localhost:8765/](http://localhost:8765/)
4. **One-time (or after cookie expiry):** use the extension popup → **Open** for Arrive / RXO / ArcBest / Echo / CHR → sign in.  
   - **Open reuses an existing tab** (focus) instead of piling new tabs.
   - ArcBest: leave the **Shipments** tab open with the list visible (extension reads Vue `shipmentSummaries` via MAIN-world `executeScript`).  
   - CHR: open Navisphere and **run a search** when you want CHR rows (network capture).
5. Extension scans ~every 60s and POSTs to `http://localhost:8765/api/loads`.
6. Popup shows per-broker status: **ok** / **needs login** / **sign in to refresh** (has prior loads) / **open tab** / **kept last** / **error**. Counts stay visible even when status is needs_login if last-good loads exist.

Empty or logged-out sources **keep last-good loads** for that source (do not wipe the board).

## How capture works (v1.0.2)

1. Content scripts inject a MAIN-world network hook (fetch/XHR + request body/headers) and never alone short-circuit the scan on soft `needs_login`.
2. **Arrive:** GraphQL `getLoads` is fetched **inside the open find-loads tab** (page cookies) via `executeScript({ world: 'MAIN' })`, replaying the last captured body. SW fetch is fallback only.
3. **ArcBest:** Vue `shipmentSummaries` read from MAIN world; if `shipmentsListApp` is missing, the extension discovers another window/DOM Vue root that holds summaries. MoLoTL → MoLo.
4. Background also tries cookie GraphQL/API across known + discovered endpoints.
5. **Status honesty:** fresh loads this scan → `ok` (never `needs_login`). Kept previous only → `stale` + “sign in / open tab to refresh”. `needs_login` only when zero loads and a confirmed login wall.

**Honest limits:** ArcBest needs the Shipments list loaded in a visible tab. Arrive needs find-loads open + a search/refresh so GraphQL fires (or a captured body to replay). CHR needs you to run a search so the API fires.

## Rebuild the zip (dev)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File extension\pack.ps1
# or:
python extension/pack.py
```

Writes `extension/ulb-extension.zip` and copies into `docs/` + `web-publish/` when those folders exist.

## Legacy CDP

Old `cdp_attach.py` / scanner Chrome code remains in the repo but is **not** started by `silent_start.ps1` unless `ULB_ENABLE_CDP=1`.
