import subprocess, re, sys
ps = r'''
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*http.server*8765*') } |
  ForEach-Object { Write-Output ("{0}|{1}" -f $_.ProcessId, $_.CommandLine) }
'''
r = subprocess.run(['powershell','-NoProfile','-Command', ps], capture_output=True, text=True)
lines = [ln.strip() for ln in r.stdout.splitlines() if ln.strip() and '|' in ln]
print('FOUND', len(lines))
for ln in lines:
    print(ln)
pids = []
for ln in lines:
    pid = ln.split('|',1)[0].strip()
    if pid.isdigit():
        pids.append(int(pid))
# keep newest (highest PID heuristic) or first; kill extras
if len(pids) <= 1:
    print('OK one or zero http.server')
    sys.exit(0)
keep = max(pids)
for pid in pids:
    if pid == keep:
        print('KEEP', pid)
        continue
    print('KILL', pid)
    subprocess.run(['taskkill','/PID',str(pid),'/F'], check=False)
