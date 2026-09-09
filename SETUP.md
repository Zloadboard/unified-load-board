# Unified Load Board - setup

## First time (work PC)
1. Ensure Python 3 is installed (`py -3`).
2. `pip install -r scanner\requirements.txt` (once).
3. Run once: `powershell -NoProfile -ExecutionPolicy Bypass -File scanner\install_task.ps1`
4. Double-click `SILENT_START.vbs` (or wait for Task Scheduler).
5. Open **http://localhost:8765/** → **Sign in brokers** (unhides scanner Chrome). Sign into Arrive / RXO / ArcBest / Echo / CHR once. Click **Hide scanner**.
6. Board stays; scanner Chrome stays hidden the rest of the day.

## Every morning after (should be ~zero)
- Log into Windows (or leave PC on). Task **Unified Load Board** / **Unified Load Board Morning** runs `SILENT_START.vbs` hidden.
- Open the board URL (local or tunnel / GitHub Pages).
- Re-login only if a broker kicked the session: **Sign in brokers** on `http://localhost:8765/`.

## Phone / anywhere
1. Optional: `powershell -File scanner\start_tunnel.ps1` -> writes `tunnel_url.txt`
2. Open that URL, or GitHub Pages with `?api=<tunnel-url>`
3. See `PUBLIC_BOARD.md` and `web-publish\README.md`
4. Sign-in controls need the work PC board (or a tunnel that reaches `:8765` APIs).

## Legacy
`DAILY_START.bat` still works but is marked legacy — prefer silent auto-start.
