# Unified Load Board (Zygis V)

One board URL from phone/anywhere. Scraping stays quiet on the work PC.

## Easy daily use

1. **Once:** run `scanner\install_task.ps1` (Task Scheduler → logon + weekdays 7:45 AM).
2. **Mornings:** do nothing — `SILENT_START.vbs` starts scanner Chrome (minimized), `serve_board.py`, and `cdp_attach.py` with no visible bats.
3. Open `http://localhost:8765/` or the Cloudflare tunnel URL (`tunnel_url.txt` / phone).
4. Sign into brokers **once** in the scanner Chrome on the work PC.

`DAILY_START.bat` remains as a **legacy** manual kick — you should not need it daily.

## Remote / GitHub Pages

- See `PUBLIC_BOARD.md` and `web-publish/README.md`.
- Board supports `?api=https://…`, `config.js` (`window.ULB_API_BASE`), or Settings → localStorage `ulb_api_base`.
- Live data comes from the work PC. Sign into brokers there once (scanner Chrome).

## Key files

| Path | Purpose |
|------|---------|
| `index.html` | Board UI (remote-ready) |
| `scanner/serve_board.py` | CORS static server :8765 |
| `scanner/cdp_attach.py` | Live scraper via Chrome CDP :9222 |
| `SILENT_START.vbs` / `scanner/silent_start.ps1` | Hidden auto-start |
| `scanner/start_tunnel.ps1` | Cloudflare quick tunnel → `tunnel_url.txt` |
| `web-publish/` | GitHub Pages package (no huge JSON) |

## Notes / ToS

- Personal use on your own carrier accounts only.
- Do not store broker passwords in this repo.
- Arrive/MoLo numeric load # parsing must stay intact in the scanner.
