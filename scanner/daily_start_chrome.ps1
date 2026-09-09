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

function Hide-ScannerChrome {
  # Prefer Win32 SW_HIDE via chrome_window.py (pythonw). Fallback: off-screen move.
  $pyCandidates = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
  )
  $pyw = $pyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if (-not $pyw) {
    try {
      $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
      if ($exe) {
        $w = $exe -replace "python\.exe$", "pythonw.exe"
        if (Test-Path $w) { $pyw = $w } else { $pyw = $exe }
      }
    } catch {}
  }
  $helper = Join-Path $PSScriptRoot "chrome_window.py"
  if ($pyw -and (Test-Path $helper)) {
    Start-Process -FilePath $pyw -ArgumentList "`"$helper`"","hide" -WindowStyle Hidden -Wait
    return
  }
}

$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  Write-Host "Starting scanner Chrome HIDDEN (CDP port $port)..."
  # Persistent profile + off-screen position. Prefer hidden over headless (logins break in headless).
  # Do NOT open 5 visible windows — start one about:blank; tabs are ensured via CDP after hide.
  $chromeArgs = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-position=-32000,-32000",
    "--window-size=1280,900",
    "about:blank"
  )
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs -WindowStyle Hidden
  Start-Sleep -Seconds 3
  Hide-ScannerChrome
  # Ensure broker tabs inside THIS Chrome (never Start-Process extra windows)
  $helper = Join-Path $PSScriptRoot "chrome_window.py"
  $pyCandidates = @(
    "$env:LOCALAPPDATA\Python\pythoncore-3.14-64\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python314\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python313\pythonw.exe",
    "$env:LOCALAPPDATA\Programs\Python\Python312\pythonw.exe"
  )
  $pyw = $pyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($pyw -and (Test-Path $helper)) {
    Start-Process -FilePath $pyw -ArgumentList "`"$helper`"","ensure-tabs" -WindowStyle Hidden -Wait
  }
} else {
  Write-Host "CDP $port already up — hiding scanner Chrome (no new windows)."
  Hide-ScannerChrome
}

Write-Host "Scanner Chrome is hidden. Sign in from the board: http://localhost:8765/ → Sign in brokers"
