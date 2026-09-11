# Build ulb-extension.zip
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if ($py) {
  & python "$here\pack.py"
  if ($LASTEXITCODE -ne 0) { & py -3 "$here\pack.py" }
} else {
  throw "python not found"
}
