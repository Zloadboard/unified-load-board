# Unified Load Board - silent auto-start (no console spam).
# ONE Chrome window: board tab + broker tabs (same CDP profile). Visible on primary
# monitor at start (for sign-in); use board "Hide Chrome" to minimize afterward.
# Never parks at -32000 (that caused taskbar-stuck hell).
# Called by SILENT_START.vbs / Task Scheduler. Safe to re-run (idempotent).
$ErrorActionPreference = "SilentlyContinue"
$Scanner = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $Scanner "..")).Path
$LogDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "silent_start.log"

function Write-Log([string]$msg) {
  $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
  Add-Content -Path $Log -Value $line -ErrorAction SilentlyContinue
}

function Test-PortListen([int]$Port) {
  $c = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return [bool]$c
}

function Find-Python {
  $w = Find-Pythonw
  if ($w -and ($w -match 'pythonw\.exe$')) {
    $exe = $w -replace 'pythonw\.exe$', 'python.exe'
    if (Test-Path $exe) { return $exe }
  }
  return $w
}

function Find-Pythonw {
  $candidates = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe",
    "$env:ProgramFiles\Python314\pythonw.exe",
    "$env:ProgramFiles\Python313\pythonw.exe"
  )
  foreach ($c in $candidates) {
    if (Test-Path $c) { return $c }
  }
  try {
    $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
    if ($exe -and (Test-Path $exe)) {
      $w = $exe -replace "python\.exe$", "pythonw.exe"
      if (Test-Path $w) { return $w }
      return $exe
    }
  } catch {}
  return $null
}

function Invoke-ChromeWindow([string]$Action, [string]$Extra = $null) {
  $py = Find-Python
  if (-not $py) { $py = Find-Pythonw }
  $helper = Join-Path $Scanner "chrome_window.py"
  if (-not $py -or -not (Test-Path $helper)) {
    Write-Log "WARN: cannot $Action scanner chrome (python/helper missing)"
    return
  }
  $args = @("`"$helper`"", $Action)
  if ($Extra) { $args += $Extra }
  Start-Process -FilePath $py -ArgumentList $args -WindowStyle Hidden -Wait | Out-Null
}

function Start-BoardServer {
  if (Test-PortListen 8765) {
    Write-Log "Port 8765 already listening - skip serve_board"
    return
  }
  $py = Find-Python
  if (-not $py) {
    Write-Log "ERROR: python not found"
    return
  }
  $scriptPath = Join-Path $Scanner "serve_board.py"
  Write-Log "Starting serve_board.py with $py (hidden)"
  Start-Process -FilePath $py -ArgumentList "`"$scriptPath`"" -WorkingDirectory $Root -WindowStyle Hidden
}

function Start-ScannerChrome {
  $port = 9222
  $profile = Join-Path $Scanner "chrome_cdp_profile"
  New-Item -ItemType Directory -Force -Path $profile | Out-Null

  if (Test-PortListen $port) {
    Write-Log "CDP $port already listening - ensure tabs only (no new Chrome)"
    Invoke-ChromeWindow "ensure-tabs"
    return
  }

  $candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  $chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $chrome) {
    Write-Log "ERROR: Chrome not found"
    return
  }

  # ONE visible window on primary monitor. First URL = board, then brokers.
  # Do NOT use -32000 / WindowStyle Hidden (taskbar-stuck). User hides via board UI.
  $board = "http://localhost:8765/"
  $chromeArgs = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=`"$profile`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-position=60,40",
    "--window-size=1400,900",
    $board,
    "https://carrier.arrivelogistics.com/find-loads",
    "https://carrier.rxoconnect.rxo.com/loads/available-loads",
    "https://carriers.arcb.com/Shipments",
    "https://echodrive.echo.com/carrier/10261/availableLoads",
    "https://www.navispherecarrier.com/"
  )
  Write-Log "Starting ONE scanner Chrome VISIBLE on primary (CDP $port, board + brokers)"
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs
  Start-Sleep -Seconds 5
  Invoke-ChromeWindow "ensure-tabs"
  Invoke-ChromeWindow "show"
}

function Start-CdpAttach {
  $existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and ($_.CommandLine -match "cdp_attach\.py") }
  if ($existing) {
    Write-Log ("cdp_attach.py already running (pid {0}) - skip" -f $existing[0].ProcessId)
    return
  }
  $pyw = Find-Pythonw
  if (-not $pyw) {
    Write-Log "ERROR: pythonw/python not found for cdp_attach"
    return
  }
  $scriptPath = Join-Path $Scanner "cdp_attach.py"
  Write-Log "Starting cdp_attach.py with $pyw"
  Start-Process -FilePath $pyw -ArgumentList "`"$scriptPath`"" -WorkingDirectory $Scanner -WindowStyle Hidden
}

Write-Log "=== silent_start begin ==="
# Board server first so Chrome's first tab can load the board
Start-BoardServer
Start-Sleep -Seconds 2
Start-ScannerChrome
Start-Sleep -Seconds 3
Start-CdpAttach
Write-Log "=== silent_start done (Chrome visible; Hide from board when signed in) ==="
