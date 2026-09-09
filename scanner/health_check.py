"""Quick board health check for morning routine / manual run."""
from __future__ import annotations
import json, time, urllib.request
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
LOADS = ROOT / "loads.json"
STALE_SEC = 15 * 60  # 15 minutes

def main() -> int:
    issues = []
    ok = []

    # CDP
    try:
        urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=3)
        ok.append("CDP 9222 up")
    except Exception:
        issues.append("Scanner Chrome CDP :9222 is DOWN — run DAILY_START.bat and leave Chrome open")

    # Table
    try:
        urllib.request.urlopen("http://127.0.0.1:8765/", timeout=3)
        ok.append("Table :8765 up")
    except Exception:
        issues.append("Table server :8765 is DOWN — run DAILY_START.bat or START_TABLE.bat")

    # loads.json
    if not LOADS.exists():
        issues.append("loads.json missing")
    else:
        age = time.time() - LOADS.stat().st_mtime
        try:
            data = json.loads(LOADS.read_text(encoding="utf-8"))
            counts = Counter(x.get("source") for x in (data.get("loads") or []))
            updated = data.get("updatedAt")
        except Exception as e:
            issues.append(f"loads.json unreadable: {e}")
            counts, updated = {}, None
        else:
            if age > STALE_SEC:
                issues.append(
                    f"loads.json STALE ({int(age/60)} min old, updatedAt={updated}). "
                    f"Counts Arrive={counts.get('Arrive',0)} RXO={counts.get('RXO',0)} "
                    f"ArcBest={counts.get('ArcBest',0)} Echo={counts.get('Echo',0)}"
                )
            else:
                ok.append(
                    f"loads fresh ({int(age)}s) Arrive={counts.get('Arrive',0)} "
                    f"RXO={counts.get('RXO',0)} ArcBest={counts.get('ArcBest',0)} Echo={counts.get('Echo',0)}"
                )
            if counts.get("Echo", 0) == 0:
                issues.append("Echo count is 0 — sign into EchoDrive Available Loads in scanner Chrome")
            if counts.get("RXO", 0) < 5:
                issues.append(f"RXO only {counts.get('RXO', 0)} loads — check RXO login/search in scanner Chrome")

    print("OK:", "; ".join(ok) if ok else "(none)")
    print("ISSUES:", "; ".join(issues) if issues else "(none)")
    # exit 1 if any issues for scripts
    return 1 if issues else 0

if __name__ == "__main__":
    raise SystemExit(main())
