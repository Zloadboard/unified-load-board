import subprocess, os, time
ps = r"""
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*cdp_attach*') } |
  ForEach-Object { Write-Output ("{0}|{1}" -f $_.ProcessId, $_.CommandLine) }
"""
r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
for ln in (r.stdout or "").splitlines():
    ln = ln.strip()
    if "|" not in ln: continue
    pid, cmd = ln.split("|", 1)
    if pid.isdigit() and "cdp_attach" in cmd:
        subprocess.run(["taskkill", "/PID", pid, "/F"], check=False)
        print("killed", pid)
lock = r"C:\Users\Disp\Desktop\unified-load-board\scanner\cdp_attach.pid"
if os.path.exists(lock):
    try: os.remove(lock)
    except Exception: pass
time.sleep(1)
print("ok")
