param(
    [Parameter(Mandatory = $true)][string]$SourceBundlePath,
    [string]$PythonPath
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$source = (Resolve-Path $SourceBundlePath).Path
$target = Join-Path $repoRoot 'bo6_service\bundle'
$bo6Python = if ($PythonPath) { (Resolve-Path $PythonPath).Path } else { Join-Path $repoRoot '.venv-bo6\Scripts\python.exe' }
if (-not (Test-Path $bo6Python)) { throw 'The isolated BO6 environment is missing. Run scripts/dev/setup.ps1 -IncludeBo6 before restoring model weights.' }
$manifestPath = Join-Path $target 'checksums.json'
$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$names = @('model_weights.pt', 'attribute_heads.pt')

function Assert-ManifestFile([string]$Directory, [string]$Name) {
    $expectedProperty = $manifest.PSObject.Properties[$Name]
    if (-not $expectedProperty) { throw "The repository manifest does not include $Name." }
    $expected = $expectedProperty.Value
    $path = Join-Path $Directory $Name
    if (-not (Test-Path $path -PathType Leaf)) { throw "Missing checksum-verified artifact $Name in $Directory." }
    $file = Get-Item -LiteralPath $path
    $digest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($file.Length -ne [int64]$expected.bytes -or $digest -ne $expected.sha256) {
        throw "Checksum or size mismatch for $Name. No destination file was overwritten."
    }
}

foreach ($name in $names) { Assert-ManifestFile $source $name }
$present = @($names | Where-Object { Test-Path (Join-Path $target $_) -PathType Leaf })
if ($present.Count -eq $names.Count) {
    foreach ($name in $names) { Assert-ManifestFile $target $name }
    Write-Host 'PASS existing model weights match the exported bundle; they were left unchanged.'
} elseif ($present.Count -gt 0) {
    throw 'The destination bundle contains only part of the model weights. It was left unchanged; inspect it before restoring.'
} else {
    $staging = Join-Path $target ('.restore-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $staging | Out-Null
    $moved = [System.Collections.Generic.List[string]]::new()
    try {
        foreach ($name in $names) {
            Copy-Item -LiteralPath (Join-Path $source $name) -Destination (Join-Path $staging $name)
            Assert-ManifestFile $staging $name
        }
        foreach ($name in $names) {
            $destination = Join-Path $target $name
            [IO.File]::Move((Join-Path $staging $name), $destination)
            $moved.Add($destination)
        }
    } catch {
        foreach ($path in $moved) { Remove-Item -LiteralPath $path -ErrorAction SilentlyContinue }
        throw
    } finally {
        foreach ($name in $names) { Remove-Item -LiteralPath (Join-Path $staging $name) -ErrorAction SilentlyContinue }
        Remove-Item -LiteralPath $staging -ErrorAction SilentlyContinue
    }
    foreach ($name in $names) { Assert-ManifestFile $target $name }
    Write-Host 'PASS copied only the two checksum-matched weights; no existing bundle files were replaced.'
}

$previousBundlePath = [Environment]::GetEnvironmentVariable('MODEL_BUNDLE_DIR', 'Process')
[Environment]::SetEnvironmentVariable('MODEL_BUNDLE_DIR', $target, 'Process')
Push-Location (Join-Path $repoRoot 'bo6_service')
try {
    $manifestOutput = & $bo6Python -c "from pathlib import Path; from app.checksum import verify_bundle; verify_bundle(Path('bundle')); print('PASS full bundle manifest')"
    if ($LASTEXITCODE -ne 0) { throw 'Full bundle manifest verification failed.' }
    Write-Host ($manifestOutput -join "`n")
    $output = & $bo6Python bundle\selftest.py
    if ($LASTEXITCODE -ne 0) { throw 'Bundle self-test process failed.' }
    $report = $output | ConvertFrom-Json
    if (-not $report.passed) { throw "Bundle self-test failed ($($report.n_checks) checks)." }
    Write-Host "PASS exported BO6 bundle self-test: $($report.n_checks) checks."
    Write-Output ($output -join "`n")
} finally {
    Pop-Location
    [Environment]::SetEnvironmentVariable('MODEL_BUNDLE_DIR', $previousBundlePath, 'Process')
}
