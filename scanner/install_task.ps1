# Create/update Windows Task Scheduler entries for silent start (extension mode).
# Starts serve_board only by default — does NOT launch CDP scanner Chrome.
# To unload / disable CDP-era tasks that spam scanner Chrome, re-run this script
# (it overwrites the same task names) or: schtasks /Delete /TN "Unified Load Board" /F
# Prefer current-user registration (no admin). Highest privileges need elevation.
$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Vbs = Join-Path $Root "SILENT_START.vbs"
if (-not (Test-Path $Vbs)) { throw "Missing $Vbs" }

$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$Vbs`""
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# At logon
try {
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  Register-ScheduledTask -TaskName "Unified Load Board" -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "OK: Unified Load Board (AtLogOn) — extension mode / serve_board only"
} catch {
  Write-Warning "AtLogOn task failed: $_"
  Write-Warning "Try elevated PowerShell if needed."
}

# Weekdays 7:45 AM
$tr = "wscript.exe `"$Vbs`""
& schtasks.exe /Create /TN "Unified Load Board Morning" /TR $tr /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 07:45 /F | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Host "OK: Unified Load Board Morning (weekdays 07:45)"
} else {
  Write-Warning "Morning task create returned $LASTEXITCODE"
}

Get-ScheduledTask -TaskName "Unified Load Board*" -ErrorAction SilentlyContinue | ForEach-Object {
  $info = $_ | Get-ScheduledTaskInfo
  "{0}  state={1}  next={2}" -f $_.TaskName, $_.State, $info.NextRunTime
}
Write-Host "Silent start target: $Vbs"
Write-Host "CDP Chrome is OFF unless env ULB_ENABLE_CDP=1. Install extension: see EXTENSION.md"
