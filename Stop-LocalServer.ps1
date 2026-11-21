$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$settingsJson = & (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') -m pyscenedetect_demo.settings
if ($LASTEXITCODE -ne 0) { throw 'Could not read WAIE settings.' }
$settings = $settingsJson | ConvertFrom-Json
$statePath = Join-Path $settings.output_root 'server-process.json'
if (-not (Test-Path -LiteralPath $statePath)) { Write-Host 'No recorded WAIE server.'; exit 0 }
$serverState = Get-Content -LiteralPath $statePath | ConvertFrom-Json
$process = Get-Process -Id $serverState.pid -ErrorAction SilentlyContinue
if (-not $process) { Write-Host 'WAIE is already stopped.'; exit 0 }
$expectedPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if ($process.Path -ne $expectedPath -or $process.StartTime.ToUniversalTime().ToString('o') -ne $serverState.started) {
    throw 'The saved process does not match this WAIE launch. No process was stopped.'
}
& taskkill.exe /PID $process.Id /T /F
if ($LASTEXITCODE -ne 0) { throw 'Could not stop WAIE.' }
Write-Host 'WAIE stopped.'
