# Read-only Windows prerequisites and project-relative config resolution.
function Assert-WindowsDesktop {
    param([switch]$Interactive)
    if ($PSVersionTable.PSVersion -lt [version]'5.1') { throw 'PowerShell 5.1 or later is required.' }
    if (-not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 is required.' }
    $MachineKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
    try {
        $WindowsKey = $MachineKey.OpenSubKey('SOFTWARE\Microsoft\Windows NT\CurrentVersion')
        $FrameworkKey = $MachineKey.OpenSubKey('SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full')
        try {
            if (-not $WindowsKey -or [int]$WindowsKey.GetValue('CurrentMajorVersionNumber', 0) -lt 10) { throw 'Windows 10/11 or Windows Server 2016+ desktop installation is required.' }
            if ($WindowsKey.GetValue('InstallationType') -notin @('Client', 'Server')) { throw 'Windows Server requires Desktop Experience; Server Core/Nano is unsupported.' }
            if (-not $FrameworkKey -or [int]$FrameworkKey.GetValue('Release', 0) -lt 528040) { throw 'Enable .NET Framework 4.8 or a later 4.x release before using ZhBot.' }
        } finally {
            if ($WindowsKey) { $WindowsKey.Dispose() }
            if ($FrameworkKey) { $FrameworkKey.Dispose() }
        }
    } finally { $MachineKey.Dispose() }
    if ($Interactive -and [System.Diagnostics.Process]::GetCurrentProcess().SessionId -eq 0) {
        throw 'Run in the signed-in robot user desktop, not a Session 0 service.'
    }
}

function Resolve-ProjectConfig {
    param([string]$ProjectRoot, [string]$ConfigPath)
    if (-not $ConfigPath) { $ConfigPath = 'runtime\config.bot.toml' }
    if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) { $ConfigPath = Join-Path $ProjectRoot $ConfigPath }
    return (Resolve-Path -LiteralPath $ConfigPath).Path
}
