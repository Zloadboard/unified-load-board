# Chrome extension — Unified Load Board Scanner

**Preferred daily path.** Sign into brokers in **normal Chrome**. No CDP / scanner profile window.

**Current version: 1.0.1**

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

## How capture works (v1.0.1)

1. Content scripts inject a MAIN-world network hook (fetch/XHR) and never alone short-circuit the scan on soft `needs_login`.
2. Background always tries cookie GraphQL/API across **all** known + discovered endpoints (does not bail on the first soft login miss).
3. ArcBest Vue state is read with `chrome.scripting.executeScript({ world: 'MAIN' })` (CSP-safe; inline `script.textContent` is blocked on many boards).
4. When a broker tab is open, the extension also ensures the network hook is present and collects captured payloads.

**Honest limits:** ArcBest needs the Shipments list loaded in a visible tab. CHR needs you to run a search so the API fires (the extension listens; it does not invent a search for you).

## Rebuild the zip (dev)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File extension\pack.ps1
# or:
python extension/pack.py
```

Writes `extension/ulb-extension.zip` and copies into `docs/` + `web-publish/` when those folders exist.

## Legacy CDP

Old `cdp_attach.py` / scanner Chrome code remains in the repo but is **not** started by `silent_start.ps1` unless `ULB_ENABLE_CDP=1`.
