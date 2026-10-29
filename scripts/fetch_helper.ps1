$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $projectRoot 'external\helper.lock.json'
$manifest = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$destination = Join-Path $projectRoot 'external\helper'

function Invoke-GitChecked {
    param([string[]]$GitArguments)
    & git @GitArguments
    if ($LASTEXITCODE -ne 0) { throw "git failed with exit code $LASTEXITCODE" }
}

if (Test-Path -LiteralPath $destination) {
    if (-not (Test-Path -LiteralPath (Join-Path $destination '.git'))) {
        throw 'external/helper already exists without Git metadata; preserve it and resolve manually.'
    }
    $gitBase = @('-c', "safe.directory=$($destination.Replace('\','/'))", '-C', $destination)
    $changes = Invoke-GitChecked -GitArguments ($gitBase + @('status', '--porcelain', '--untracked-files=no'))
    if ($changes) { throw 'helper has tracked changes; refusing to overwrite them.' }
    $origin = Invoke-GitChecked -GitArguments ($gitBase + @('remote', 'get-url', 'origin'))
    if ($origin.Trim() -ne $manifest.repository) { throw 'helper origin differs from the locked repository.' }
    $head = Invoke-GitChecked -GitArguments ($gitBase + @('rev-parse', 'HEAD'))
    if ($head.Trim() -ne $manifest.commit) {
        throw 'Existing helper is at a different revision. Preserve it; inspect the upgrade separately.'
    }
} else {
    Invoke-GitChecked -GitArguments @('clone', '--no-checkout', $manifest.repository, $destination)
    $gitBase = @('-c', "safe.directory=$($destination.Replace('\','/'))", '-C', $destination)
    Invoke-GitChecked -GitArguments ($gitBase + @('checkout', '--detach', $manifest.commit))
}

foreach ($entry in $manifest.sha256.PSObject.Properties) {
    $file = Join-Path $destination $entry.Name
    $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $entry.Value) { throw "Bridge checksum mismatch: $($entry.Name)" }
}
foreach ($relative in @('LICENSE', 'THIRD_PARTY_NOTICES.md', 'native/bridge_watchdog.py', 'native/run_selftest.py')) {
    if (-not (Test-Path -LiteralPath (Join-Path $destination $relative) -PathType Leaf)) {
        throw "Required upstream file missing: $relative"
    }
}
Write-Output "helper verified at $($manifest.commit); sources and licenses retained. No bridge was loaded."
