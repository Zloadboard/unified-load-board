# Unified Load Board (Zygis V)

One board URL from phone/anywhere. Scraping stays quiet on the work PC.

## Honest UX (no iframe logins)

Broker sites set `X-Frame-Options` — login forms **cannot** be iframed into the board.
Closest match to “no extra windows”:

**ONE Chrome window** (CDP profile `chrome_cdp_profile`, port `9222`) hosts:

| Tab | Content |
|-----|---------|
| 1 | Board `http://localhost:8765/` |
| 2+ | Arrive / RXO / ArcBest / Echo / CHR |

- **Sign in Arrive / RXO / …** on the board → `POST /api/scanner/focus-tab` activates that tab in the **same** window and restores it on the primary monitor.
- **Back to board** focuses the localhost:8765 tab.
- **Hide Chrome** minimizes (never parks at `-32000` — that caused taskbar-stuck hell).
- Scraping (`cdp_attach.py`) attaches to **this same** Chrome via CDP — never a second profile window.
- **Load #** uses `target="_blank"` → new **tab** in the same window (Chrome default), not a new window.

## Easy daily use

1. **Once:** run `scanner\install_task.ps1` (Task Scheduler → logon + weekdays 7:45 AM).
2. **Mornings:** `SILENT_START.vbs` starts `serve_board.py`, **one** visible scanner Chrome (board + broker tabs), and `cdp_attach.py`.
3. Open the board (already tab 1, or `http://localhost:8765/` elsewhere).
4. Sign into brokers with the per-broker buttons, then **Hide Chrome**.
5. Status pills show visibility + best-effort tab login guesses. Controls only work on the work PC board — GitHub Pages cannot drive Chrome.

## Load # links

Clicking **Load #** opens the broker load in a **new tab** of the same Chrome window.

- **Echo:** `…/v2/carrier/10261/availableLoads?loadId=`
- **Arrive:** `…/find-loads?loadBoardId=`
- **RXO:** `…/loads/{id}`
- **ArcBest/MoLo:** `…/Shipments?referenceNumber=`
- **CHR:** `…/?loadId=`

## Remote / GitHub Pages

- See `PUBLIC_BOARD.md` and `web-publish/README.md`.
- Board supports `?api=https://…`, `config.js` (`window.ULB_API_BASE`), or Settings → localStorage `ulb_api_base`.

## Key files

| Path | Purpose |
|------|---------|
| `index.html` | Board UI + per-broker Sign in / Hide Chrome |
| `scanner/serve_board.py` | CORS server :8765 + `/api/scanner/*` |
| `scanner/chrome_window.py` | Show/minimize/focus-tab via Win32 + CDP |
| `scanner/cdp_attach.py` | Live scraper via Chrome CDP :9222 |
| `SILENT_START.vbs` / `scanner/silent_start.ps1` | Auto-start (one Chrome, on-screen) |
| `scanner/start_tunnel.ps1` | Cloudflare quick tunnel → `tunnel_url.txt` |

## Notes / ToS

- Personal use on your own carrier accounts only.
- Do not store broker passwords in this repo.
- Prefer **minimized** Chrome over headless (headless often breaks broker logins). Persistent profile must stay.
