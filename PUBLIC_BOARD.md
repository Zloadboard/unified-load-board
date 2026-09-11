# Public / phone board (Cloudflare Tunnel)

## What you get

- One board URL from phone or any browser.
- Work PC keeps scraping quietly (**one** scanner Chrome + `serve_board.py` + `cdp_attach.py`).
- GitHub Pages can host the HTML; live data is fetched from the tunnel with CORS.

## Honest constraint (also shown in the UI)

> Broker sites block iframes. Sign into brokers on **http://localhost:8765/** using **Sign in Arrive / RXO / …** — that focuses the broker **tab in the same Chrome window** as the board (CDP profile).  
> GitHub Pages cannot control Chrome. Load # links open a new **tab** (same window); they do **not** feed the scraper.

## Morning flow (should be ~zero clicks)

After Task Scheduler is installed:

1. Log into Windows (or leave PC on / wake).
2. Task **Unified Load Board** runs `SILENT_START.vbs` at logon and weekdays 7:45 AM.
3. Open the board:
   - Local: already tab 1 of scanner Chrome, or `http://localhost:8765/`
   - Phone: tunnel URL from `tunnel_url.txt` (or GitHub Pages with `?api=…`)
4. First time / after profile wipe: on **http://localhost:8765/** click **Sign in Arrive** (etc.), sign in, **Back to board**, then **Hide Chrome**.

Optional tunnel each day (quick tunnels change URL):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scanner\start_tunnel.ps1
# reads public URL → tunnel_url.txt
```

## Install Task Scheduler (once)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scanner\install_task.ps1
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
