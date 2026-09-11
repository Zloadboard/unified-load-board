# Start ONE scanner Chrome (board + broker tabs) with CDP :9222.
# Visible on primary monitor - never -32000. Hide from the board UI when done signing in.
$ErrorActionPreference = "Stop"
$port = 9222
$profile = Join-Path $PSScriptRoot "chrome_cdp_profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null

$candidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome not found"; exit 1 }

function Find-Python {
  $pyCandidates = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
  )
  $py = $pyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($py) { return $py }
  try {
    $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
    if ($exe -and (Test-Path $exe)) { return $exe }
  } catch {}
  return $null
}

function Invoke-ChromeWindow([string]$Action) {
  $py = Find-Python
  $helper = Join-Path $PSScriptRoot "chrome_window.py"
  if ($py -and (Test-Path $helper)) {
    Start-Process -FilePath $py -ArgumentList "`"$helper`"","$Action" -WindowStyle Hidden -Wait
  }
}

$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  Write-Host "Starting ONE scanner Chrome on primary monitor (CDP port $port)..."
  # ONLY the board URL at process start. Brokers opened once via ensure-tabs after CDP is ready.
  # Passing all broker URLs here + ensure-tabs previously caused duplicate Arrive/RXO tabs.
  $board = "http://localhost:8765/"
  $chromeArgs = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=`"$profile`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-position=60,40",
    "--window-size=1400,900",
    $board
  )
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs
  Start-Sleep -Seconds 5
  Invoke-ChromeWindow "ensure-tabs"
  Invoke-ChromeWindow "dedupe"
  Invoke-ChromeWindow "show"
} else {
  Write-Host "CDP $port already up - ensuring board+broker tabs (no new Chrome window)."
  Invoke-ChromeWindow "ensure-tabs"
  Invoke-ChromeWindow "dedupe"
  Invoke-ChromeWindow "show"
}

Write-Host "Scanner Chrome: ONE window (board + brokers). Sign in from http://localhost:8765/ per-broker buttons, then Hide Chrome."
