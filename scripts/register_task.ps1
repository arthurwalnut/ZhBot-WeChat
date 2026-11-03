param(
    [string]$ConfigPath = '',
    [string]$TaskName = 'Astra-WeChat-Bot',
    [switch]$Remove
)
$ErrorActionPreference = 'Stop'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Removed scheduled task: $TaskName"
    exit 0
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_environment.ps1')
Assert-WindowsDesktop -Interactive
$ConfigPath = Resolve-ProjectConfig -ProjectRoot $ProjectRoot -ConfigPath $ConfigPath
$PythonWindowless = Join-Path $ProjectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $PythonWindowless -PathType Leaf)) {
    throw 'Project pythonw.exe is missing. Install the Windows project environment first.'
}
& (Join-Path $ProjectRoot '.venv\Scripts\python.exe') -I (Join-Path $ProjectRoot 'launcher\environment.py') $ProjectRoot
if ($LASTEXITCODE -ne 0) { throw 'Project environment moved or invalid. Run scripts/install.ps1 first.' }
$UserName = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$TaskArguments = '-u -m wechat_bot run --config "{0}"' -f $ConfigPath
$Action = New-ScheduledTaskAction -Execute $PythonWindowless -Argument $TaskArguments -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserName
$Principal = New-ScheduledTaskPrincipal -UserId $UserName -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description 'Astra WeChat bot in the signed-in robot user session. WeChat login and configured build are required.' -Force | Out-Null
Write-Output "Registered $TaskName for $UserName at logon. Windows and WeChat login still apply."
Write-Output 'Task Scheduler stores resolved paths. After moving this project or changing machines, run this command again under the target robot user.'
