# Start a Cloudflare quick tunnel to the local board (port 8765).
# Writes the public https://....trycloudflare.com URL to ..\tunnel_url.txt
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutFile = Join-Path $Root "tunnel_url.txt"
$LogDir = Join-Path $Root "data"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$CfOut = Join-Path $LogDir "cloudflared.out.log"
$CfErr = Join-Path $LogDir "cloudflared.err.log"

function Find-Cloudflared {
  $p = Join-Path $Root "tools\cloudflared.exe"
  if (Test-Path $p) { return (Resolve-Path $p).Path }
  $cmd = Get-Command cloudflared -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

$cf = Find-Cloudflared
if (-not $cf) {
  Write-Error "cloudflared not found. Place cloudflared.exe in tools\ or install it."
  exit 1
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and ($_.CommandLine -match "cloudflared.*tunnel --url") } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Test-Path $OutFile) { Remove-Item $OutFile -Force -ErrorAction SilentlyContinue }
Remove-Item $CfOut,$CfErr -Force -ErrorAction SilentlyContinue

$cfArgs = @("tunnel", "--url", "http://127.0.0.1:8765", "--no-autoupdate")
$p = Start-Process -FilePath $cf -ArgumentList $cfArgs -RedirectStandardOutput $CfOut -RedirectStandardError $CfErr -PassThru -WindowStyle Hidden

$url = $null
for ($i = 0; $i -lt 60; $i++) {
  Start-Sleep -Seconds 1
  $text = ""
  if (Test-Path $CfErr) { $text += [string](Get-Content $CfErr -Raw -ErrorAction SilentlyContinue) }
  if (Test-Path $CfOut) { $text += [string](Get-Content $CfOut -Raw -ErrorAction SilentlyContinue) }
  if ($text -match "https://[a-z0-9-]+\.trycloudflare\.com") {
    $url = $Matches[0]
    break
  }
  if ($p.HasExited) { break }
}

if ($url) {
  Set-Content -Path $OutFile -Value $url -Encoding ascii
  Write-Host "Public board URL: $url"
  Write-Host "Saved to $OutFile"
  Write-Host "Phone / GitHub Pages: open board with ?api=$url"
} else {
  Write-Warning "Tunnel started but URL not parsed yet. Check $CfErr / $CfOut"
  if ($p.HasExited) {
    Write-Error "cloudflared exited early. See logs in data\"
    exit 1
  } else {
    Write-Host "cloudflared still running (pid $($p.Id)). Tail data\cloudflared.err.log for the URL."
  }
}
