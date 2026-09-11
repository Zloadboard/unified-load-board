# Unified Load Board (Zygis V)

One board URL from phone/anywhere. Scraping uses a **Chrome MV3 extension** on the work PC (normal Chrome cookies). No CDP scanner window required for daily use.

## Why extension (not iframes / CDP)

Broker sites set `X-Frame-Options` — login forms **cannot** be iframed into the board.  
The extension runs in **your normal Chrome**, uses existing broker cookies (`credentials: 'include'`), and POSTs merged loads to `http://localhost:8765/api/loads`.

## Easy daily use

1. **Once:** install the extension — see [EXTENSION.md](EXTENSION.md) or the **Download / Install extension** panel on the board.
2. **Once:** run `scanner\install_task.ps1` (Task Scheduler → logon + weekdays 7:45 AM). This starts **serve_board only** (no CDP Chrome).
3. Sign into Arrive / RXO / ArcBest / Echo / CHR in **normal Chrome** tabs (extension popup → Open).
4. Open the board: `http://localhost:8765/`
5. Leave Chrome open; extension scans ~every 60s.

### Download the extension

- Local: [http://localhost:8765/extension/ulb-extension.zip](http://localhost:8765/extension/ulb-extension.zip)
- Repo: `extension/ulb-extension.zip`
- Unzip → `chrome://extensions` → Developer mode → **Load unpacked** → select the unzipped folder.

Chrome Web Store is not required for v1.

## Load # links

Clicking **Load #** opens the broker load in a new tab of the same Chrome window.

- **Echo:** `…/v2/carrier/10261/availableLoads?loadId=`
- **Arrive:** `…/find-loads?loadBoardId=`
- **RXO:** `…/loads/{id}`
- **ArcBest/MoLo:** `…/Shipments?referenceNumber=` / `shipmentId=`
- **CHR:** `…/?loadId=`

## Remote / GitHub Pages

- See `PUBLIC_BOARD.md` and `web-publish/README.md`.
- Board supports `?api=https://…`, `config.js` (`window.ULB_API_BASE`), or Settings → localStorage `ulb_api_base`.
- Extension zip is also copied to `docs/ulb-extension.zip` for Pages.

## Key files

| Path | Purpose |
|------|---------|
| `extension/` | MV3 scanner (service worker + popup + content scripts) |
| `extension/ulb-extension.zip` | Downloadable package |
| `EXTENSION.md` | Install steps |
| `index.html` | Board UI + download panel + extension-mode banner |
| `scanner/serve_board.py` | CORS server :8765 + `POST /api/loads` |
| `SILENT_START.vbs` / `scanner/silent_start.ps1` | Auto-start **serve_board only** (CDP off unless `ULB_ENABLE_CDP=1`) |
| `scanner/cdp_attach.py` | **Legacy** CDP scraper (kept, not daily default) |

## Notes / ToS

- Personal use on your own carrier accounts only.
- Do not store broker passwords in this repo.
- Prefer leaving normal Chrome signed in; ArcBest/CHR work best with their board tab open.
