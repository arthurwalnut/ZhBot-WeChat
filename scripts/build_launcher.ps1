param()
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$CompilerPath = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
if (-not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) {
    throw 'The Windows .NET Framework v4 x64 C# compiler is required to rebuild the launcher.'
}
$BuildDirectory = Join-Path $ProjectRoot 'build\launcher'
New-Item -ItemType Directory -Force -Path $BuildDirectory | Out-Null
$TemporaryExe = Join-Path $BuildDirectory 'ZhBot.exe'
$OutputExe = Join-Path $ProjectRoot 'ZhBot.exe'
$SourcePath = Join-Path $ProjectRoot 'launcher\Launcher.cs'
& $CompilerPath /nologo /target:winexe /platform:x64 /optimize+ /codepage:65001 /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Web.Extensions.dll "/out:$TemporaryExe" $SourcePath
if ($LASTEXITCODE -ne 0) { throw 'Launcher compilation failed.' }
Copy-Item -LiteralPath $TemporaryExe -Destination $OutputExe -Force
Write-Output "Built $OutputExe. Keep it in the project root; future bot code updates use the same entry point."
