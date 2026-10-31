param(
    [ValidateRange(1024, 65535)][int]$AppPort = 8000,
    [ValidateRange(1024, 65535)][int]$Bo6Port = 18022
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$appPython = Join-Path $repoRoot '.venv-app\Scripts\python.exe'
$bo6Python = Join-Path $repoRoot '.venv-bo6\Scripts\python.exe'
$bundlePath = Join-Path $repoRoot 'bo6_service\bundle'
if (-not (Test-Path $appPython)) { throw 'Run scripts/dev/setup.ps1 first.' }
if (-not (Test-Path $bo6Python)) { throw 'Run scripts/dev/setup.ps1 -IncludeBo6 first.' }
if (-not (Test-Path (Join-Path $bundlePath 'model_weights.pt')) -or -not (Test-Path (Join-Path $bundlePath 'attribute_heads.pt'))) {
    throw 'BO6 weights are absent. Restore only checksum-verified weights with scripts/dev/restore-model-bundle.ps1.'
}
Push-Location (Join-Path $repoRoot 'bo6_service')
try {
    & $bo6Python -c "from pathlib import Path; from app.checksum import verify_bundle; verify_bundle(Path('bundle')); print('PASS BO6 bundle checksums')"
    if ($LASTEXITCODE -ne 0) { throw 'BO6 bundle checksum validation failed; service startup was skipped.' }
} finally { Pop-Location }

$runtimeRoot = if ($env:DRESSME_RUNTIME_DIR) { $env:DRESSME_RUNTIME_DIR } else { Join-Path $env:LOCALAPPDATA 'DressMe\Project_DressMe\runtime' }
$logRoot = Join-Path $runtimeRoot 'logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$statePath = Join-Path $runtimeRoot 'services.json'
$state = if (Test-Path $statePath) { Get-Content $statePath -Raw | ConvertFrom-Json } else { [pscustomobject]@{ app = $null; bo6 = $null } }

function Test-Health([string]$Url) {
    try {
        $response = Invoke-RestMethod -Uri $Url -TimeoutSec 3
        if ($Url -like '*/health/ready') { return $response.status -eq 'ok' -and $response.dependencies.database -and $response.dependencies.bo6_service }
        return $response.status -eq 'ok'
    } catch { return $false }
}

function Test-PortFree([int]$Port) {
    $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $listener.Start(); return $true }
    catch { return $false }
    finally { $listener.Stop() }
}

function Save-State {
    $json = $state | ConvertTo-Json -Depth 5
    [IO.File]::WriteAllText($statePath, $json + "`n", [Text.UTF8Encoding]::new($false))
}

function Start-Service([string]$Name, [int]$Port, [string]$HealthUrl, [string]$PythonPath, [string]$WorkingDirectory, [string[]]$Arguments, [hashtable]$ChildEnvironment, [int]$TimeoutSeconds) {
    $owned = $state.$Name
    if ($owned -and $owned.pid) {
        $existingProcess = Get-Process -Id ([int]$owned.pid) -ErrorAction SilentlyContinue
        if ($existingProcess -and (Test-Health $HealthUrl)) {
            Write-Host "PASS $Name already running and healthy on 127.0.0.1:$Port (managed by this checkout)."
            return
        }
        if ($existingProcess) { throw "$Name is already managed but is not healthy. Inspect its private log under $logRoot." }
        $state.$Name = $null
    }
    if (Test-Health $HealthUrl) {
        Write-Host "PASS $Name already healthy on 127.0.0.1:$Port; it is not managed by this script."
        return
    }
    if (-not (Test-PortFree $Port)) { throw "Port $Port is occupied by an unrelated/unhealthy listener; no process was stopped." }

    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $stdoutPath = Join-Path $logRoot "$Name-$stamp.out.log"
    $stderrPath = Join-Path $logRoot "$Name-$stamp.err.log"
    $previous = @{}
    foreach ($key in $ChildEnvironment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$ChildEnvironment[$key], 'Process')
    }
    try {
        $process = Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory `
            -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -WindowStyle Hidden -PassThru
    } finally {
        foreach ($key in $ChildEnvironment.Keys) { [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process') }
    }
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($process.Id)"
    $state.$Name = [pscustomobject]@{
        pid = $process.Id
        executable = $PythonPath
        command = $processInfo.CommandLine
        startedUtc = $process.StartTime.ToUniversalTime().ToString('o')
        port = $Port
        stdout = $stdoutPath
        stderr = $stderrPath
    }
    Save-State

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ($process.HasExited) { throw "$Name exited before becoming healthy; private diagnostics are in $stderrPath." }
        if (Test-Health $HealthUrl) {
            Write-Host "PASS $Name healthy on 127.0.0.1:$Port."
            return
        }
        Start-Sleep -Seconds 2
    }
    throw "$Name did not become healthy within $TimeoutSeconds seconds. It remains recorded for safe shutdown; diagnostics are in $stderrPath."
}

if ($AppPort -eq $Bo6Port) { throw 'Application and BO6 ports must be different.' }
$frontendOrigin = "http://127.0.0.1:$AppPort"
$bo6Url = "http://127.0.0.1:$Bo6Port"
Start-Service 'bo6' $Bo6Port "$bo6Url/health" $bo6Python (Join-Path $repoRoot 'bo6_service') `
    @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', [string]$Bo6Port, '--workers', '1') `
    @{ MODEL_BUNDLE_DIR = $bundlePath } 180
Start-Service 'app' $AppPort "$frontendOrigin/studio-api/health/ready" $appPython $repoRoot `
    @('-m', 'uvicorn', 'api:app', '--host', '127.0.0.1', '--port', [string]$AppPort, '--workers', '1') `
    @{ BO6_SERVICE_URL = $bo6Url; FRONTEND_ORIGINS = $frontendOrigin } 90

Write-Host "Application: $frontendOrigin/#bo6-wardrobe"
Write-Host "BO6 health:  $bo6Url/health"
Write-Host 'Database migrations are explicit; this script does not run them.'
