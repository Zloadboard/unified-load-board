Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -and ($_.CommandLine -like '*http.server*8765*' -or $_.CommandLine -like '*cdp_attach*') } |
  ForEach-Object { Write-Output ("{0}|{1}" -f $_.ProcessId, $_.CommandLine) }
