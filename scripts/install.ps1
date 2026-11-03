param([string]$PythonPath = '', [switch]$RecreateEnvironment)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot 'windows_environment.ps1')
Assert-WindowsDesktop
$EnvironmentRoot = Join-Path $ProjectRoot '.venv'
$EnvironmentPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$EnvironmentValid = $false
if (Test-Path -LiteralPath $EnvironmentPython -PathType Leaf) {
    $SavedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $ProbeJson = & $EnvironmentPython -I (Join-Path $ProjectRoot 'launcher\environment.py') $ProjectRoot 2>$null
        if ($LASTEXITCODE -eq 0) { $EnvironmentValid = ($ProbeJson | ConvertFrom-Json).ok }
    } finally { $ErrorActionPreference = $SavedPreference }
}

if (-not $EnvironmentValid -or $RecreateEnvironment) {
    if (-not $PythonPath) {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            $SavedPreference = $ErrorActionPreference
            try {
                $ErrorActionPreference = 'Continue'
                $DetectedPython = & py -3.12 -c 'import sys,json; print(json.dumps(sys.executable))' 2>$null
                if ($LASTEXITCODE -eq 0) { $PythonPath = $DetectedPython | ConvertFrom-Json }
            } finally { $ErrorActionPreference = $SavedPreference }
        }
        if (-not $PythonPath) {
            # A copied standalone Python is usable only if it actually executes.
            $BundledPython = Get-ChildItem -LiteralPath (Join-Path $ProjectRoot '.python') -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($BundledPython) { $PythonPath = $BundledPython.FullName }
        }
        if (-not $PythonPath) { throw 'Install Python 3.12 x64 on this machine, or supply -PythonPath. The existing environment was preserved.' }
    }
    # Validate a base interpreter before touching the previous environment.
    $BasePython = & $PythonPath -I -c "import sys,struct,pathlib,json; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Python 3.12 x64 required'; print(json.dumps(str(pathlib.Path(sys.base_prefix) / 'python.exe')))"
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 required.' }
    $PythonPath = $BasePython | ConvertFrom-Json
    if ($PythonPath.StartsWith($EnvironmentRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Select a base Python outside the environment being recreated.' }
    # The Windows venv redirector remains alive while its child Python runs.
    # Get-Process avoids requiring WMI/CIM permissions on locked-down servers.
    $ManagerExecutable = Join-Path $ProjectRoot 'ZhBot.exe'
    $BusyProcesses = Get-Process -Name python, pythonw, ZhBot -ErrorAction SilentlyContinue | Where-Object {
        $_.Path -and ($_.Path.StartsWith($EnvironmentRoot + '\', [StringComparison]::OrdinalIgnoreCase) -or $_.Path -eq $ManagerExecutable)
    }
    if ($BusyProcesses) { throw 'This project Python environment is in use. Stop the bot normally and close its manager before recreating it.' }
    if (Test-Path -LiteralPath $EnvironmentRoot) {
        $ResolvedEnvironment = (Resolve-Path -LiteralPath $EnvironmentRoot).Path
        if ($ResolvedEnvironment -ne [IO.Path]::GetFullPath($EnvironmentRoot) -or
            ((Get-Item -LiteralPath $EnvironmentRoot).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'The existing environment is redirected; preserve it and recreate explicitly in a regular project directory.'
        }
        $BackupDirectory = Join-Path $ProjectRoot ('.venv.backup-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0,8))
        if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($BackupDirectory)) -ne [IO.Path]::GetFullPath($ProjectRoot)) { throw 'Environment backup target must stay in the project root.' }
        Move-Item -LiteralPath $ResolvedEnvironment -Destination $BackupDirectory
        Write-Output "Previous environment retained at $BackupDirectory"
    }
    & $PythonPath -m venv $EnvironmentRoot
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}

Push-Location $ProjectRoot
try {
    & $EnvironmentPython -m pip install -c requirements-lock.txt -e '.[bot,reader]'
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; keep the environment and retry after checking network access.' }
    & $EnvironmentPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency consistency check failed.' }
    & $EnvironmentPython -I (Join-Path $ProjectRoot 'launcher\environment.py') $ProjectRoot
    if ($LASTEXITCODE -ne 0) { throw 'The installed environment does not resolve to this project.' }
    [IO.File]::WriteAllText((Join-Path $EnvironmentRoot 'zhbot-install-root.txt'), $ProjectRoot, [Text.UTF8Encoding]::new($false))
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
