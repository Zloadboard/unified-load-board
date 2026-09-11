#!/usr/bin/env python3
"""Verify POST /api/loads under concurrent GET + honest last_scan."""
from __future__ import annotations
import json, threading, time, urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, sys

BASE = "http://127.0.0.1:8765"
PASS = 0
FAIL = 0
LOG = []

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def http_json(method, path, body=None, timeout=30):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "ignore")
        return resp.status, json.loads(raw) if raw.strip() else {}

def make_loads(src, n, prefix):
    out = []
    for i in range(n):
        out.append({
            "id": f"{prefix}-{i}",
            "source": src,
            "origin": "Romeoville, IL",
            "destination": "Atlanta, GA",
            "pickup_city": "Romeoville, IL",
            "delivery_city": "Atlanta, GA",
            "pickup_date": "09-12-2026",
            "pickup_time": "08:00",
            "delivery_date": "09-13-2026",
            "delivery_time": "14:00",
            "pickup": "09-12-2026 08:00",
            "delivery": "09-13-2026 14:00",
            "miles": 720,
            "rate": 1800,
            "equipment": "Van",
            "weight": "42000",
            "status": "Available",
            "url": "https://example.com",
            "notes": "",
        })
    return out

def assert_honest(sources, label):
    bad = []
    for name, meta in (sources or {}).items():
        st = meta.get("status")
        n = meta.get("count") or 0
        if n > 0 and st == "needs_login":
            bad.append(f"{name}: needs_login with count={n}")
        if n > 0 and st not in ("ok", "stale"):
            bad.append(f"{name}: status={st} with count={n}")
    if bad:
        raise AssertionError(label + " dishonest: " + "; ".join(bad))

def cycle(i, scenario):
    global PASS, FAIL
    name = scenario["name"]
    loads = scenario["loads"]
    sources = scenario["sources"]
    stopper = {"stop": False, "ok": 0, "err": 0}
    def hammer():
        while not stopper["stop"]:
            try:
                http_json("GET", "/loads.json")
                http_json("GET", "/api/last_scan")
                stopper["ok"] += 1
            except Exception:
                stopper["err"] += 1
            time.sleep(0.02)
    t = threading.Thread(target=hammer, daemon=True)
    t.start()
    time.sleep(0.05)
    try:
        code, resp = http_json("POST", "/api/loads", {
            "updatedAt": now(),
            "mode": "extension",
            "sources": sources,
            "loads": loads,
        })
        time.sleep(0.15)
        stopper["stop"] = True
        t.join(timeout=2)
        if code != 200 or not resp.get("ok"):
            raise AssertionError(f"POST failed code={code} resp={resp}")
        _, last = http_json("GET", "/api/last_scan")
        assert_honest(last.get("sources"), "last_scan")
        # Extra: the lie scenario must flip to stale
        if name == "lie_needs_login_with_counts":
            for k in ("RXO", "Echo", "CHR"):
                st = last["sources"][k]["status"]
                n = last["sources"][k]["count"]
                if st != "stale":
                    raise AssertionError(f"{k} expected stale got {st}")
                if n <= 0:
                    raise AssertionError(f"{k} expected count>0 got {n}")
            # Arrive: if merge kept prior rows → stale; only needs_login when board count is 0
            arr = last["sources"]["Arrive"]
            if arr["count"] > 0 and arr["status"] == "needs_login":
                raise AssertionError("Arrive needs_login with count>0")
            if arr["count"] > 0 and arr["status"] not in ("ok", "stale"):
                raise AssertionError(f"Arrive bad status {arr}")
            if arr["count"] == 0 and arr["status"] != "needs_login":
                raise AssertionError(f"Arrive zero should needs_login got {arr}")
        _, board = http_json("GET", "/loads.json")
        board_loads = board.get("loads") if isinstance(board, dict) else board
        if not isinstance(board_loads, list):
            raise AssertionError("loads.json missing loads array")
        counts = {}
        for row in board_loads:
            if isinstance(row, dict) and row.get("source"):
                counts[row["source"]] = counts.get(row["source"], 0) + 1
        row = {
            "cycle": i,
            "name": name,
            "ok": True,
            "written": resp.get("written"),
            "gets_ok": stopper["ok"],
            "gets_err": stopper["err"],
            "last_scan": {k: (v.get("status"), v.get("count")) for k,v in (last.get("sources") or {}).items()},
            "board_counts": counts,
        }
        PASS += 1
        LOG.append(row)
        print(f"CYCLE {i} PASS [{name}] written={resp.get('written')} gets={stopper['ok']}/{stopper['err']} sources={row['last_scan']}")
        return row
    except Exception as e:
        stopper["stop"] = True
        FAIL += 1
        row = {"cycle": i, "name": name, "ok": False, "error": str(e)}
        LOG.append(row)
        print(f"CYCLE {i} FAIL [{name}] {e}")
        return row

def main(rounds, tag):
    global PASS, FAIL
    PASS = FAIL = 0
    LOG.clear()
    scenarios = []
    L1 = (make_loads("Arrive", 5, "A") + make_loads("RXO", 8, "R") +
          make_loads("ArcBest", 4, "AB") + make_loads("MoLo", 3, "M") +
          make_loads("Echo", 6, "E") + make_loads("CHR", 12, "C"))
    scenarios.append({
        "name": "all_ok",
        "loads": L1,
        "sources": {
            "Arrive": {"status": "ok", "count": 5, "error": "", "keptPrevious": False},
            "RXO": {"status": "ok", "count": 8, "error": "", "keptPrevious": False},
            "ArcBest": {"status": "ok", "count": 4, "error": "", "keptPrevious": False},
            "MoLo": {"status": "ok", "count": 3, "error": "", "keptPrevious": False},
            "Echo": {"status": "ok", "count": 6, "error": "", "keptPrevious": False},
            "CHR": {"status": "ok", "count": 12, "error": "", "keptPrevious": False},
        },
    })
    L2 = make_loads("RXO", 20, "RX") + make_loads("Echo", 10, "EC") + make_loads("CHR", 83, "CH")
    scenarios.append({
        "name": "lie_needs_login_with_counts",
        "loads": L2,
        "sources": {
            "Arrive": {"status": "needs_login", "count": 0, "error": "Arrive login required", "keptPrevious": False},
            "RXO": {"status": "needs_login", "count": 20, "error": "RXO login required", "keptPrevious": True},
            "ArcBest": {"status": "needs_login", "count": 0, "error": "ArcBest login required", "keptPrevious": False},
            "Echo": {"status": "needs_login", "count": 10, "error": "Echo login required", "keptPrevious": True},
            "CHR": {"status": "needs_login", "count": 83, "error": "CHR login", "keptPrevious": True},
        },
    })
    L3 = make_loads("Arrive", 7, "AR") + make_loads("ArcBest", 5, "ARC") + make_loads("MoLo", 2, "MO")
    scenarios.append({
        "name": "arrive_arcbest_fresh",
        "loads": L3 + make_loads("RXO", 20, "RX") + make_loads("Echo", 10, "EC") + make_loads("CHR", 83, "CH"),
        "sources": {
            "Arrive": {"status": "ok", "count": 7, "error": "", "keptPrevious": False},
            "RXO": {"status": "stale", "count": 20, "error": "open tab", "keptPrevious": True},
            "ArcBest": {"status": "ok", "count": 5, "error": "", "keptPrevious": False},
            "MoLo": {"status": "ok", "count": 2, "error": "", "keptPrevious": False},
            "Echo": {"status": "stale", "count": 10, "error": "open tab", "keptPrevious": True},
            "CHR": {"status": "stale", "count": 83, "error": "open tab", "keptPrevious": True},
        },
    })
    scenarios.append({
        "name": "zero_login_ok",
        "loads": make_loads("RXO", 5, "R2") + make_loads("CHR", 5, "C2"),
        "sources": {
            "Arrive": {"status": "needs_login", "count": 0, "error": "Arrive login required", "keptPrevious": False},
            "RXO": {"status": "ok", "count": 5, "error": "", "keptPrevious": False},
            "ArcBest": {"status": "needs_login", "count": 0, "error": "ArcBest login", "keptPrevious": False},
            "Echo": {"status": "empty", "count": 0, "error": "", "keptPrevious": False},
            "CHR": {"status": "ok", "count": 5, "error": "", "keptPrevious": False},
        },
    })
    L5 = (make_loads("Arrive", 15, "A5") + make_loads("RXO", 25, "R5") +
          make_loads("ArcBest", 10, "AB5") + make_loads("MoLo", 8, "M5") +
          make_loads("Echo", 18, "E5") + make_loads("CHR", 40, "C5"))
    scenarios.append({
        "name": "large_ok",
        "loads": L5,
        "sources": {
            "Arrive": {"status": "ok", "count": 15, "error": "", "keptPrevious": False},
            "RXO": {"status": "ok", "count": 25, "error": "", "keptPrevious": False},
            "ArcBest": {"status": "ok", "count": 10, "error": "", "keptPrevious": False},
            "MoLo": {"status": "ok", "count": 8, "error": "", "keptPrevious": False},
            "Echo": {"status": "ok", "count": 18, "error": "", "keptPrevious": False},
            "CHR": {"status": "ok", "count": 40, "error": "", "keptPrevious": False},
        },
    })

    print(f"===== {tag}: {rounds} cycles =====")
    for i in range(1, rounds + 1):
        sc = scenarios[(i - 1) % len(scenarios)]
        cycle(i, sc)
        time.sleep(0.1)
    print(f"===== {tag} SUMMARY pass={PASS} fail={FAIL} =====")
    out_path = r"C:\Users\Disp\Desktop\unified-load-board\scanner\debug\verify_cycles.json"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"tag": tag, "pass": PASS, "fail": FAIL, "log": LOG}, f, indent=2)
    print("wrote", out_path)
    return FAIL == 0

if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "round1"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    ok = main(rounds, tag)
    raise SystemExit(0 if ok else 1)

