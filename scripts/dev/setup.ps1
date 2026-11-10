param(
    [switch]$Developer,
    [switch]$IncludeBo6,
    [switch]$G2L
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$pythonCommand = Get-Command python -ErrorAction Stop
$python = $pythonCommand.Source
$versionText = & $python -c 'import sys; print(str(sys.version_info.major)+chr(46)+str(sys.version_info.minor))'
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

$environmentPath = 'requirements-integrated.lock.txt' # validated merged application, including test tools
Install-Environment '.venv-app' $environmentPath

if ($IncludeBo6) {
    $bo6Requirements = if ($Developer) { 'bo6_service\requirements-dev.lock' } else { 'bo6_service\requirements.lock' }
    Install-Environment '.venv-bo6' $bo6Requirements
}

if ($G2L) {
    # CPU torch and transformers for the Garments2Look bundle; the bundle itself is copied by hand.
    Install-Environment '.venv-bo6-g2l' 'bo6_service\requirements-g2l.in'
    if (-not (Test-Path (Join-Path $repoRoot 'bo6_service\bundle_g2l\clip_vision\model.safetensors'))) {
        Write-Warning 'Put the unzipped G2L bundle in bo6_service\bundle_g2l before running start.ps1 -G2L.'
    }
}

$envPath = Join-Path $repoRoot '.env'
if (-not (Test-Path $envPath)) {
    Copy-Item -LiteralPath (Join-Path $repoRoot '.env.example') -Destination $envPath
    $bytes = New-Object byte[] 48
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $secret = [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
    $config = Get-Content -LiteralPath $envPath -Raw
    $config = $config.Replace('JWT_SECRET=', "JWT_SECRET=$secret")
    [IO.File]::WriteAllText($envPath, $config, [Text.UTF8Encoding]::new($false))
    Write-Host 'Created .env from .env.example; review local database, private storage, port and recovery settings.'
} else {
    Write-Host 'Kept existing .env unchanged.'
}

Push-Location (Join-Path $repoRoot 'landing')
try {
    npm ci --no-audit --no-fund
    if ($LASTEXITCODE -ne 0) { throw 'Landing dependency installation failed.' }
    # Vite empties static/landing before it writes, so a hand-written page there would be lost.
    # Its output is recognised by comparison: it repeats landing/index.html or links /landing/assets/.
    $livePage = Join-Path $repoRoot 'static\landing\index.html'
    $handWritten = $false
    if (Test-Path -LiteralPath $livePage) {
        $live = (Get-Content -LiteralPath $livePage -Raw -Encoding UTF8) -replace "`r`n", "`n"
        $source = (Get-Content -LiteralPath 'index.html' -Raw -Encoding UTF8) -replace "`r`n", "`n"
        $handWritten = ($live -ne $source) -and -not $live.Contains('/landing/assets/')
    }
    if ($handWritten) {
        Write-Warning 'Skipped the landing build: static/landing/index.html is hand-written and the build would replace it. To rebuild from landing/, delete that file and run setup again.'
    } else {
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'Landing build failed.' }
    }
} finally { Pop-Location }

Write-Host 'No database was created, no migration was run and no model artifact was downloaded or replaced.'
