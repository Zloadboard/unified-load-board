# Unified Load Board — GitHub Pages package

Static UI only. **Live `loads.json` and geo JSON stay on the work PC** (served via Cloudflare Tunnel). This folder is safe to publish — no secrets, no huge data files.

## Enable GitHub Pages

1. Push this repo to GitHub.
2. Settings → Pages → Source: Deploy from a branch.
3. Folder: `/web-publish` (or copy these files into `/docs` and pick `/docs`).
4. Save. Your board URL will look like `https://YOURUSER.github.io/REPO/`.

## Point the UI at live data

Pick one:

**A. Query param (fastest)**  
Open: `https://YOURUSER.github.io/REPO/?api=https://xxxx.trycloudflare.com`

**B. config.js**  
```bash
cp config.example.js config.js
# edit config.js → set window.ULB_API_BASE
git add config.js && git commit && git push
```

**C. Settings in the UI**  
Open the board → Settings → paste the tunnel URL → Save (stored in this browser’s localStorage).

## Honest constraint

- Viewing works from phone/anywhere.
- **Scrape sessions** must stay signed in on the **work PC scanner Chrome**.
- Broker login links on the board open the broker site for *you*; they do **not** feed the scraper.

See `../PUBLIC_BOARD.md` for tunnel + Task Scheduler morning flow.
