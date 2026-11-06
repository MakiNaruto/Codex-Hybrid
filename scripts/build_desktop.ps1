# Forward the desktop build to its platform-owned implementation.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '../apps/desktop/tools/build_windows.ps1') @args
exit $LASTEXITCODE
