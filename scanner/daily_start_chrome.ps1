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

$urls = @(
  "https://carrier.arrivelogistics.com/find-loads",
  "https://carrier.rxoconnect.rxo.com/loads/available-loads",
  "https://carriers.arcb.com/Shipments",
  "https://echodrive.echo.com/carrier/10261/availableLoads"
)

$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  Write-Host "Starting scanner Chrome (CDP port $port)..."
  $chromeArgs = @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check"
  ) + $urls
  Start-Process -FilePath $chrome -ArgumentList $chromeArgs
} else {
  Write-Host "CDP $port already up - opening board tabs..."
  foreach ($u in $urls) { Start-Process $chrome $u }
}

Write-Host "Sign into ALL four tabs in THAT Chrome window. Leave it open all day."
