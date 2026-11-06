# Forward the desktop build to its platform-owned implementation.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '../desktop/tools/build_windows.ps1') @args
exit $LASTEXITCODE
