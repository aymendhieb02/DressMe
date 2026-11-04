param(
    [ValidateRange(1024, 65535)][int]$AppPort = 8000,
    [ValidateRange(1024, 65535)][int]$Bo6Port = 18022
)

$ErrorActionPreference = 'Stop'
$appUrl = "http://127.0.0.1:$AppPort"
$bo6Url = "http://127.0.0.1:$Bo6Port"
$results = [ordered]@{}

try {
    $ml = Invoke-RestMethod -Uri "$bo6Url/health" -TimeoutSec 5
    $results.BO6 = if ($ml.status -eq 'ok') { 'PASS' } else { 'FAIL' }
    if ($results.BO6 -eq 'PASS') { Write-Host "PASS BO6 real inference service: $($ml.model_version), $($ml.taxonomy_version)" }
} catch { $results.BO6 = 'BLOCKED'; Write-Host 'BLOCKED BO6 health unavailable; inspect the BO6 service log.' }

try {
    $app = Invoke-RestMethod -Uri "$appUrl/studio-api/health/ready" -TimeoutSec 5
    $results.Application = if ($app.status -eq 'ok') { 'PASS' } else { 'FAIL' }
    $results.Database = if ($app.dependencies.database) { 'PASS' } else { 'FAIL' }
    $results.ApplicationML = if ($app.dependencies.bo6_service -and $app.inference_mode -eq 'bo6_real') { 'PASS' } else { 'FAIL' }
    Write-Host "$($results.Application) application readiness"
    Write-Host "$($results.Database) database connectivity"
    Write-Host "$($results.ApplicationML) backend uses real BO6 service"
} catch {
    $results.Application = 'BLOCKED'
    $results.Database = 'BLOCKED'
    $results.ApplicationML = 'BLOCKED'
    Write-Host 'BLOCKED application readiness; inspect local configuration and private service logs.'
}

try {
    $queue = Invoke-RestMethod -Uri "$appUrl/studio-api/health/try-on" -TimeoutSec 5
    $results.RedisRQ = if ($queue.available) { 'PASS' } else { 'BLOCKED' }
    if ($queue.available) { Write-Host 'PASS Redis/RQ worker ready (this checkout only produces MOCK jobs).' }
    else { Write-Host "BLOCKED Redis/RQ unavailable: $($queue.reason)" }
} catch { $results.RedisRQ = 'BLOCKED'; Write-Host 'BLOCKED Redis/RQ readiness endpoint unavailable.' }

if ($results.Application -eq 'FAIL' -or $results.Database -eq 'FAIL' -or $results.ApplicationML -eq 'FAIL') { exit 1 }
if ($results.Application -eq 'BLOCKED' -or $results.BO6 -eq 'BLOCKED') { exit 2 }
