param([string]$ConfigPath = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_environment.ps1')
Assert-WindowsDesktop -Interactive
$PythonPath = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$ConfigPath = Resolve-ProjectConfig -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Project Python environment missing. Run the README installation commands first.' }
& $PythonPath -I (Join-Path $ProjectRoot 'launcher\environment.py') $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Project environment moved or invalid. Run scripts/install.ps1 on this machine first.' }
$LogDirectory = Join-Path $ProjectRoot 'runtime\logs'
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss-ffff'
$OutputLog = Join-Path $LogDirectory "start-$Stamp.stdout.log"
$ErrorLog = Join-Path $LogDirectory "start-$Stamp.stderr.log"
$env:PYTHONIOENCODING = 'utf-8'
$Arguments = @('-u', '-m', 'wechat_bot', 'run', '--config', ('"{0}"' -f $ConfigPath))
$BotProcess = Start-Process -FilePath $PythonPath -ArgumentList $Arguments -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput $OutputLog -RedirectStandardError $ErrorLog -PassThru
Start-Sleep -Seconds 3
$BotProcess.Refresh()
if ($BotProcess.HasExited) {
    if (Test-Path -LiteralPath $ErrorLog) { Get-Content -LiteralPath $ErrorLog }
    if (Test-Path -LiteralPath $OutputLog) { Get-Content -LiteralPath $OutputLog }
    throw "Robot exited during startup (exit=$($BotProcess.ExitCode)). Logs: $LogDirectory"
}
Write-Output "Started process PID $($BotProcess.Id). Live status follows; a running process alone does not confirm WeChat reception."
& $PythonPath -m wechat_bot status --config $ConfigPath
Write-Output "Startup logs: $OutputLog ; $ErrorLog"
