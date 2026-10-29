param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$EnvironmentPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf)) {
    if (-not $PythonPath) {
        $PythonPath = & py -3.12 -c 'import sys; print(sys.executable)'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 x64, or supply -PythonPath.' }
        $PythonPath = $PythonPath.Trim()
    }
    & $PythonPath -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 x64 required'"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 required.' }
    & $PythonPath -m venv (Join-Path $ProjectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

Push-Location $ProjectRoot
try {
    & $EnvironmentPython -m pip install -c requirements-lock.txt -e '.[bot,reader]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; keep the environment and retry after checking network access.' }
    & $EnvironmentPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
    & (Join-Path $PSScriptRoot 'fetch_helper.ps1')
    $ConfigPath = Join-Path $ProjectRoot 'runtime\config.bot.toml'
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $ConfigPath) | Out-Null
        Copy-Item -LiteralPath (Join-Path $ProjectRoot 'config.bot.example.toml') -Destination $ConfigPath
    }
    Write-Output 'Installed. Follow README to bind the robot account and group before opening ZhBot.exe. No bridge was loaded.'
} finally {
    Pop-Location
}
