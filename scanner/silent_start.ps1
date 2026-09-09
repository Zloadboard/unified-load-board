# Unified Load Board - silent auto-start (no console spam, no visible scanner Chrome, no pause).
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

function Invoke-ChromeWindow([string]$Action) {
  $pyw = Find-Pythonw
  $helper = Join-Path $Scanner "chrome_window.py"
  if (-not $pyw -or -not (Test-Path $helper)) {
    Write-Log "WARN: cannot $Action scanner chrome (pythonw/helper missing)"
    return
  }
  Start-Process -FilePath $pyw -ArgumentList "`"$helper`"","$Action" -WindowStyle Hidden -Wait | Out-Null
}

function Start-ScannerChrome {
  $port = 9222
  if (Test-PortListen $port) {
    Write-Log "CDP $port already listening - hide only (no new Chrome windows)"
    Invoke-ChromeWindow "hide"
    return
  }
  $profile = Join-Path $Scanner "chrome_cdp_profile"
  New-Item -ItemType Directory -Force -Path $profile | Out-Null
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
  # Hidden + off-screen. Prefer hidden over headless (broker logins break headless).
  # Start about:blank only — ensure-tabs opens broker boards inside this CDP Chrome.
  $chromeArgs = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-position=-32000,-32000",
    "--window-size=1280,900",
    "about:blank"
  )
  Write-Log "Starting scanner Chrome HIDDEN (CDP $port)"
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs -WindowStyle Hidden
  Start-Sleep -Seconds 4
  Invoke-ChromeWindow "hide"
  Invoke-ChromeWindow "ensure-tabs"
  Start-Sleep -Seconds 1
  Invoke-ChromeWindow "hide"
}

function Start-BoardServer {
  if (Test-PortListen 8765) {
    Write-Log "Port 8765 already listening - skip serve_board"
    return
  }
  $pyw = Find-Pythonw
  if (-not $pyw) {
    Write-Log "ERROR: pythonw/python not found"
    return
  }
  $scriptPath = Join-Path $Scanner "serve_board.py"
  Write-Log "Starting serve_board.py with $pyw"
  Start-Process -FilePath $pyw -ArgumentList "`"$scriptPath`"" -WorkingDirectory $Root -WindowStyle Hidden
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
Start-ScannerChrome
Start-Sleep -Seconds 4
Start-BoardServer
Start-Sleep -Seconds 2
Start-CdpAttach
# Final hide pass in case Chrome flashed
Invoke-ChromeWindow "hide"
Write-Log "=== silent_start done ==="
