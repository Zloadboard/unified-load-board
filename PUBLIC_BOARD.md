# Public / phone board (Cloudflare Tunnel)

## What you get

- One board URL from phone or any browser.
- Work PC: **Chrome extension** + `serve_board.py` (+ optional tunnel). No CDP scanner Chrome required.
- GitHub Pages can host the HTML; live data is fetched from the tunnel with CORS.
- Extension zip: `docs/ulb-extension.zip` / `extension/ulb-extension.zip` for install on another PC.

## Honest constraint

> Broker sites block iframes. Sign into brokers in **normal Chrome** (where the extension is installed).  
> GitHub Pages cannot install the extension or control Chrome. Load # links open the broker site; they do **not** feed the scanner by themselves.

## Morning flow (~zero clicks after setup)

1. Log into Windows (or leave PC on / wake).
2. Task **Unified Load Board** runs `SILENT_START.vbs` → **serve_board** on :8765.
3. Leave normal Chrome open (extension installed, brokers signed in).
4. Open the board: `http://localhost:8765/` or phone via tunnel / Pages `?api=…`

## Install extension (another computer)

1. Download `ulb-extension.zip` from the board Download panel, repo, or Pages.
2. Unzip to a stable folder.
3. `chrome://extensions` → Developer mode → Load unpacked → select that folder.
4. Sign into the five brokers in that Chrome; keep `serve_board` reachable if posting locally (or point a future gist sync — v1 = localhost).

## Install Task Scheduler (once)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scanner\install_task.ps1
```

CDP Chrome is **not** started. To force legacy CDP: set env `ULB_ENABLE_CDP=1` before silent start.

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
