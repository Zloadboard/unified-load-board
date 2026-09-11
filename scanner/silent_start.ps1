# Unified Load Board - silent auto-start (no console spam).
# DEFAULT (extension mode): start serve_board.py only (+ optional tunnel).
# CDP scanner Chrome is OFF unless ULB_ENABLE_CDP=1 is set in the environment.
# Daily path: install the Chrome extension, sign into brokers in normal Chrome, open board.
# Called by SILENT_START.vbs / Task Scheduler. Safe to re-run (idempotent).
$ErrorActionPreference = "SilentlyContinue"
$Scanner = $PSScriptRoot
$Root = (Resolve-Path (Join-Path $Scanner "..")).Path
$LogDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "silent_start.log"
$EnableCdp = $env:ULB_ENABLE_CDP -eq "1"

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
  Write-Log "Starting serve_board.py with $py (hidden) — extension POSTs to /api/loads"
  Start-Process -FilePath $py -ArgumentList "`"$scriptPath`"" -WorkingDirectory $Root -WindowStyle Hidden
}

function Start-ScannerChrome {
  $port = 9222
  $profile = Join-Path $Scanner "chrome_cdp_profile"
  New-Item -ItemType Directory -Force -Path $profile | Out-Null

  if (Test-PortListen $port) {
    Write-Log "CDP $port already listening - ensure+dedupe tabs only (no new Chrome)"
    Invoke-ChromeWindow "ensure-tabs"
    Invoke-ChromeWindow "dedupe"
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
  Write-Log "LEGACY: Starting scanner Chrome VISIBLE (CDP $port) — set only when ULB_ENABLE_CDP=1"
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs
  Start-Sleep -Seconds 5
  Invoke-ChromeWindow "ensure-tabs"
  Invoke-ChromeWindow "dedupe"
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
  Write-Log "LEGACY: Starting cdp_attach.py with $pyw"
  Start-Process -FilePath $pyw -ArgumentList "`"$scriptPath`"" -WorkingDirectory $Scanner -WindowStyle Hidden
}

Write-Log "=== silent_start begin (extension mode; CDP=$EnableCdp) ==="
Start-BoardServer
Start-Sleep -Seconds 2
if ($EnableCdp) {
  Write-Log "ULB_ENABLE_CDP=1 — launching legacy CDP Chrome + cdp_attach"
  Start-ScannerChrome
  Start-Sleep -Seconds 3
  Start-CdpAttach
} else {
  Write-Log "CDP Chrome NOT started (default). Use Chrome extension + normal broker tabs."
  Write-Log "Board: http://localhost:8765/  Extension zip: http://localhost:8765/extension/ulb-extension.zip"
}
Write-Log "=== silent_start done ==="
