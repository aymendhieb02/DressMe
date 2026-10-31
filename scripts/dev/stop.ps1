$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtimeRoot = if ($env:DRESSME_RUNTIME_DIR) { $env:DRESSME_RUNTIME_DIR } else { Join-Path $env:LOCALAPPDATA 'DressMe\Project_DressMe\runtime' }
$statePath = Join-Path $runtimeRoot 'services.json'
if (-not (Test-Path $statePath)) { Write-Host 'No services are recorded for this checkout.'; exit 0 }
$state = Get-Content $statePath -Raw | ConvertFrom-Json

foreach ($name in @('app', 'bo6')) {
    $record = $state.$name
    if (-not $record -or -not $record.pid) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
    if (-not $process) { $state.$name = $null; continue }
    $expectedExecutable = Join-Path $repoRoot (if ($name -eq 'app') { '.venv-app\Scripts\python.exe' } else { '.venv-bo6\Scripts\python.exe' })
    $expectedModule = if ($name -eq 'app') { 'api:app' } else { 'app.main:app' }
    if ([IO.Path]::GetFullPath($process.ExecutablePath) -ne [IO.Path]::GetFullPath($expectedExecutable) -or
        $process.CommandLine -ne $record.command -or $process.CommandLine -notlike "*$expectedModule*") {
        Write-Warning "$name PID $($record.pid) no longer matches this checkout; left it running and kept its record."
        continue
    }
    Stop-Process -Id ([int]$record.pid) -ErrorAction Stop
    try { Wait-Process -Id ([int]$record.pid) -Timeout 10 -ErrorAction Stop }
    catch { Write-Warning "$name did not exit promptly. It may still be shutting down; no forced termination was attempted."; continue }
    $state.$name = $null
    Write-Host "Stopped this checkout's $name service on port $($record.port). Persistent database and image files were kept."
}

$json = $state | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText($statePath, $json + "`n", [Text.UTF8Encoding]::new($false))
