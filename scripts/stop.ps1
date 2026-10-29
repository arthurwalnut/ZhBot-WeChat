param([string]$ConfigPath = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not $ConfigPath) { $ConfigPath = Join-Path $ProjectRoot 'runtime\config.bot.toml' }
$ConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
& $PythonPath -m wechat_bot stop --config $ConfigPath
if ($LASTEXITCODE -ne 0) { throw "Stop request failed (exit=$LASTEXITCODE)." }
