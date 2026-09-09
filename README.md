# Unified Load Board (Zygis V)

One board URL from phone/anywhere. Scraping stays quiet on the work PC — **only the board window** should be visible.

## Easy daily use

1. **Once:** run `scanner\install_task.ps1` (Task Scheduler → logon + weekdays 7:45 AM).
2. **Mornings:** do nothing — `SILENT_START.vbs` starts scanner Chrome **hidden** (Win32 `SW_HIDE` + off-screen), `serve_board.py`, and `cdp_attach.py` with no visible bats/consoles.
3. Open **`http://localhost:8765/`** (work PC) or the Cloudflare tunnel / GitHub Pages URL.
4. **Sign into brokers** from the board: click **Sign in brokers** (unhides the CDP Chrome with your persistent `chrome_cdp_profile`). Click **Hide scanner** when done (or it auto-hides after 10 minutes).
5. Status pill shows `hidden` / `visible` / `CDP down`. These controls call `POST /api/scanner/show|hide` on the work PC — **GitHub Pages cannot unhide Chrome**; sign-in there.

`DAILY_START.bat` remains as a **legacy** manual kick — you should not need it daily.

## Load # links

Clicking **Load #** opens the broker load in your current browser (Echo-email style). Scraping never spawns extra Chrome windows.

- **Echo (CDP-proven):** `https://echodrive.echo.com/v2/carrier/10261/availableLoads?loadId={loadId}`
- **Arrive:** `…/find-loads?loadBoardId={LoadBoardId}`
- **RXO:** `…/loads/{id}`
- **ArcBest/MoLo:** `…/Shipments?shipmentId=` or `?referenceNumber=`

## Remote / GitHub Pages

- See `PUBLIC_BOARD.md` and `web-publish/README.md`.
- Board supports `?api=https://…`, `config.js` (`window.ULB_API_BASE`), or Settings → localStorage `ulb_api_base`.
- Live data comes from the work PC. Broker sign-in is on the work PC board only.

## Key files

| Path | Purpose |
|------|---------|
| `index.html` | Board UI (remote-ready) |
| `scanner/serve_board.py` | CORS static server :8765 + `/api/scanner/*` |
| `scanner/chrome_window.py` | Hide/show CDP Chrome via Win32 |
| `scanner/cdp_attach.py` | Live scraper via Chrome CDP :9222 |
| `SILENT_START.vbs` / `scanner/silent_start.ps1` | Hidden auto-start |
| `scanner/start_tunnel.ps1` | Cloudflare quick tunnel → `tunnel_url.txt` |
| `web-publish/` | GitHub Pages package (no huge JSON) |

## Notes / ToS

- Personal use on your own carrier accounts only.
- Do not store broker passwords in this repo.
- Prefer **hidden** Chrome over headless (headless often breaks broker logins). Persistent profile must stay.
