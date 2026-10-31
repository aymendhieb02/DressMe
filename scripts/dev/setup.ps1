param(
    [switch]$Developer,
    [switch]$IncludeBo6
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonCommand = Get-Command python -ErrorAction Stop
$python = $pythonCommand.Source
$versionText = & $python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
if ($versionText -ne '3.11') {
    throw "Python 3.11 is required for the validated Windows setup; found $versionText."
}

function Install-Environment([string]$EnvironmentPath, [string]$RequirementsPath) {
    $environment = Join-Path $repoRoot $EnvironmentPath
    if (-not (Test-Path $environment)) {
        & $python -m venv $environment
        if ($LASTEXITCODE -ne 0) { throw "Could not create $EnvironmentPath." }
    }
    $cfgPath = Join-Path $environment 'pyvenv.cfg'
    if (-not (Test-Path $cfgPath) -or (Get-Content $cfgPath -Raw) -notmatch '(?im)^include-system-site-packages\s*=\s*false\s*$') {
        throw "$EnvironmentPath must be a regular isolated venv. It was left unchanged; create a new venv if its config is invalid."
    }
    $venvPython = Join-Path $environment 'Scripts\python.exe'
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $repoRoot $RequirementsPath)
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed for $RequirementsPath." }
    Write-Host "PASS $RequirementsPath installed in $EnvironmentPath (Python $versionText; no system packages)."
}

$environmentPath = if ($Developer) { 'requirements-dev.lock' } else { 'requirements.lock' }
Install-Environment '.venv-app' $environmentPath

if ($IncludeBo6) {
    $bo6Requirements = if ($Developer) { 'bo6_service\requirements-dev.lock' } else { 'bo6_service\requirements.lock' }
    Install-Environment '.venv-bo6' $bo6Requirements
}

$envPath = Join-Path $repoRoot '.env'
if (-not (Test-Path $envPath)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot '.env.example') -Destination $envPath
    Write-Host 'Created .env from .env.example; review local database, private storage, port and recovery settings.'
} else {
    Write-Host 'Kept existing .env unchanged.'
}

Write-Host 'No database was created, no migration was run and no model artifact was downloaded or replaced.'
