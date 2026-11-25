# Forward the desktop build to its platform-owned implementation.
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
# Both entry points are parameterless; splatting $args here passes $null.
& (Join-Path $PSScriptRoot '../desktop/tools/build_windows.ps1')
exit $LASTEXITCODE
