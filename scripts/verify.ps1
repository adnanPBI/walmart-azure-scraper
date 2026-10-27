# Offline fixture qualification for Windows PowerShell. No Walmart/Azure contact.
$ErrorActionPreference = 'Stop'
Push-Location (Resolve-Path (Join-Path $PSScriptRoot '..'))
try {
    python -m compileall -q walmart_azure
    if ($LASTEXITCODE -ne 0) { throw 'Python compile check failed' }
    python -m walmart_azure validate --catalog examples/SYNTHETIC_RECORD_NOT_FOR_CONTEST.json
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic record contract check failed' }
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Offline tests failed' }
    Write-Host 'Offline qualification complete. Live Walmart and Azure qualification still required.'
}
finally { Pop-Location }
