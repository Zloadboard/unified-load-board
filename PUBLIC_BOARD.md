# Public / phone board (Cloudflare Tunnel)

## What you get

- One board URL from phone or any browser.
- Work PC keeps scraping quietly (scanner Chrome + `serve_board.py` + `cdp_attach.py`).
- GitHub Pages can host the HTML; live data is fetched from the tunnel with CORS.

## Honest constraint (also shown in the UI)

> Live data comes from the work PC. Sign into brokers there once (scanner Chrome).  
> Broker links from your phone open the broker site for you, but do **not** feed the scraper.

## Morning flow (should be ~zero clicks)

After Task Scheduler is installed:

1. Log into Windows (or leave PC on / wake).
2. Task **Unified Load Board** runs `SILENT_START.vbs` at logon and weekdays 7:45 AM.
3. Open the board:
   - Local: `http://localhost:8765/`
   - Phone: tunnel URL from `tunnel_url.txt` (or GitHub Pages with `?api=…`)
4. First time / after Chrome profile wipe: briefly open the minimized scanner Chrome and sign into Arrive / RXO / ArcBest / Echo. Leave it alone the rest of the day.

Optional tunnel each day (quick tunnels change URL):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scanner\start_tunnel.ps1
# reads public URL → tunnel_url.txt
```

Then on phone: open that URL, or GitHub Pages `?api=<that-url>`.

## Install Task Scheduler (once)

From an elevated PowerShell in the project folder, or use the helper:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scanner\install_task.ps1
```

Manual equivalent:

```bat
schtasks /Create /TN "Unified Load Board" /TR "wscript.exe \"C:\Users\Disp\Desktop\unified-load-board\SILENT_START.vbs\"" /SC ONLOGON /RL HIGHEST /F
schtasks /Create /TN "Unified Load Board Morning" /TR "wscript.exe \"C:\Users\Disp\Desktop\unified-load-board\SILENT_START.vbs\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:45 /RL HIGHEST /F
```

## Named tunnel later (stable URL)

Quick tunnels (`trycloudflare.com`) get a **new random URL each run**. For a stable hostname:

1. `cloudflared tunnel login`
2. `cloudflared tunnel create ulb`
3. Route DNS / config.yml → `http://localhost:8765`
4. Put that hostname in GitHub Pages `config.js` once.

## GitHub Pages `?api=` example

```
https://YOURUSER.github.io/unified-load-board/?api=https://random-words.trycloudflare.com
```

Coords JSON (`city_coords.json`, etc.) are fetched from the same API base — keep them on the work PC / tunnel so the GitHub repo stays small.
