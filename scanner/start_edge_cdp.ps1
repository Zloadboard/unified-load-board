# Launch a dedicated Edge that stays open for the load scanner
$ErrorActionPreference = "Stop"
$port = 9222
$profile = Join-Path $PSScriptRoot "edge_cdp_profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null

$edge = @(
  "$env:ProgramFiles(x86)\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $edge) { Write-Error "Edge not found"; exit 1 }

# If something already listens on 9222, just open the loads URL in a new tab via the existing browser
$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  Write-Host "Starting Edge with remote debugging on port $port ..."
  Start-Process -FilePath $edge -ArgumentList @(
    "--remote-debugging-port=$port",
    "--user-data-dir=$profile",
    "--no-first-run",
    "--no-default-browser-check",
    "https://carrier.rxoconnect.rxo.com/loads/available-loads"
  )
} else {
  Write-Host "Edge debug port $port already listening — opening RXO tab"
  Start-Process $edge "https://carrier.rxoconnect.rxo.com/loads/available-loads"
}

Write-Host ""
Write-Host "Log into RXO (and Arrive/ArcBest if you want) in THAT Edge window."
Write-Host "Leave this Edge window open while the scanner runs."
Write-Host "When logged in and you see loads, tell AI Load Offers."
