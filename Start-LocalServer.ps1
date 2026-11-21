param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$settingsJson = & $pythonPath -m pyscenedetect_demo.settings
if ($LASTEXITCODE -ne 0) { throw 'Could not read WAIE settings.' }
$settings = $settingsJson | ConvertFrom-Json
New-Item -ItemType Directory -Force -Path $settings.output_root | Out-Null
$browserHost = if ($settings.host -eq '0.0.0.0') { '127.0.0.1' } elseif ($settings.host.Contains(':')) { '[' + $settings.host + ']' } else { $settings.host }
$url = 'http://{0}:{1}' -f $browserHost, $settings.port
$running = $false
$needsRestart = $false
try {
    $api = Invoke-RestMethod -Uri "$url/openapi.json" -TimeoutSec 2
    # Accept previous display names so an existing instance can update to WAIE.
    if ($api.info.title -notin @('WAIE', 'Easy Edit', 'Scene Scribe')) { throw ('Port {0} belongs to another application.' -f $settings.port) }
    try {
        $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 2
        if ($health.application -ne 'scene-scribe') { throw 'Unrecognized server health response.' }
        if ($health.output_root -ne $settings.output_root) { throw 'This port belongs to a WAIE instance using another output folder.' }
        $running = $health.revision -eq $settings.revision
        $needsRestart = -not $running
    } catch {
        if ($_.Exception.Message -match 'another output folder|Unrecognized') { throw }
        # An older build has no health endpoint and needs a verified restart.
        $needsRestart = $true
    }
} catch {
    if ($_.Exception.Message -match 'belongs to|Unrecognized') { throw }
    if ($null -ne $_.Exception.Response) { throw "The server at $url could not identify itself. No process was stopped." }
}
if ($needsRestart) {
    $jobs = @(Invoke-RestMethod -Uri "$url/api/jobs" -TimeoutSec 3 | ForEach-Object { $_ })
    $projects = if ($api.paths.'/api/editor/projects') { @(Invoke-RestMethod -Uri "$url/api/editor/projects" -TimeoutSec 3 | ForEach-Object { $_ }) } else { @() }
    $busy = @($jobs + $projects | Where-Object { $_.status -in @('pending', 'running', 'analyzing', 'rendering') })
    if ($busy.Count -gt 0) { throw 'The running server needs an update. Finish its active jobs before restarting it.' }
    if (-not (Test-Path -LiteralPath (Join-Path $settings.output_root 'server-process.json'))) {
        throw 'The outdated server was not started by this launcher. Stop it manually, then start WAIE again.'
    }
    Write-Host 'Restarting WAIE to load updated code...'
    & (Join-Path $PSScriptRoot 'Stop-LocalServer.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'The previous WAIE server could not be stopped.' }
}
if (-not $running) {
    $env:HF_HOME = Join-Path $settings.model_dir '.hf-cache'
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    $env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
    $env:CUDA_VISIBLE_DEVICES = '-1'
    $process = Start-Process -FilePath $pythonPath -ArgumentList '-m','pyscenedetect_demo.web.main' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $settings.output_root 'server.log') -RedirectStandardError (Join-Path $settings.output_root 'server-error.log') -PassThru
    @{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().ToString('o'); path = $process.Path } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $settings.output_root 'server-process.json')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try {
            $health = Invoke-RestMethod -Uri "$url/api/health" -TimeoutSec 1
            if ($health.application -eq 'scene-scribe' -and $health.revision -eq $settings.revision) { $running = $true; break }
        } catch { }
    }
    if (-not $running) { throw 'Server did not start. Check output\server-error.log.' }
}
if (-not $NoBrowser) {
    $pagePath = if ($api -and -not $api.paths.'/editor') { '/' } else { '/editor' }
    Start-Process ($url + $pagePath)
}
Write-Host "WAIE is running at $url. Use Stop WAIE.cmd when finished."
