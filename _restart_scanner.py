import subprocess, time, os
def list_cdp():
    ps = r"""
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*cdp_attach*') } |
  ForEach-Object { Write-Output ("{0}|{1}" -f $_.ProcessId, $_.CommandLine) }
"""
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    out = []
    for ln in (r.stdout or "").splitlines():
        ln = ln.strip()
        if "|" in ln and ln.split("|", 1)[0].strip().isdigit():
            out.append(ln)
    return out
for ln in list_cdp():
    pid = ln.split("|", 1)[0].strip()
    if "cdp_attach" in ln:
        subprocess.run(["taskkill", "/PID", pid, "/F"], check=False)
        print("killed", pid)
lock = r"C:\Users\Disp\Desktop\unified-load-board\scanner\cdp_attach.pid"
if os.path.exists(lock):
    try: os.remove(lock)
    except Exception: pass
time.sleep(1)
subprocess.run(["cmd", "/c", r"C:\Users\Disp\Desktop\unified-load-board\scanner\START_SCANNER_CDP.bat"], check=False)
time.sleep(4)
print("now:", list_cdp())
