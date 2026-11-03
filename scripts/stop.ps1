param([string]$ConfigPath = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_environment.ps1')
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ConfigPath = Resolve-ProjectConfig -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath
$PreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Join-Path $ProjectRoot 'src')
    & $PythonPath -m wechat_bot stop --config $ConfigPath
    if ($LASTEXITCODE -ne 0) { throw "Stop request failed (exit=$LASTEXITCODE)." }
} finally { $env:PYTHONPATH = $PreviousPythonPath }
