# Build the Windows x64 desktop preview and its frozen Python sidecar.
# Run on Windows with Python 3.11+, Rust MSVC and Visual Studio C++ build tools.
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# Native failures are checked below, including the offline fetch fallback.
$PSNativeCommandUseErrorActionPreference = $false

function Invoke-Checked {
    param([string]$Command, [string[]]$Arguments)
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command"
    }
}

function Initialize-MsvcEnvironment {
    # A regular PowerShell session does not inherit the VS developer environment.
    $VsWhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (Test-Path -LiteralPath $VsWhere -PathType Leaf) {
        $Installation = & $VsWhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not locate Visual Studio C++ tools using vswhere.exe.'
        }
        if ($Installation) {
            $DevCommand = Join-Path $Installation 'Common7/Tools/VsDevCmd.bat'
            if (-not (Test-Path -LiteralPath $DevCommand -PathType Leaf)) {
                throw "Visual Studio developer environment is missing: $DevCommand. Repair the C++ build tools installation."
            }
            # cmd.exe runs only the VS environment setup; import its environment
            # into this process so cargo and its build scripts inherit PATH/LIB/INCLUDE.
            $CommandLine = 'call "' + $DevCommand + '" -no_logo -arch=x64 -host_arch=x64 && set'
            $EnvironmentLines = & $env:ComSpec /d /c $CommandLine
            if ($LASTEXITCODE -ne 0) {
                throw 'Could not initialize the Visual Studio x64 developer environment.'
            }
            foreach ($Line in $EnvironmentLines) {
                if ($Line -match '^([^=]+)=(.*)$') {
                    [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process')
                }
            }
        }
    }

    $Compiler = Get-Command cl.exe -CommandType Application -ErrorAction SilentlyContinue
    $Linker = Get-Command link.exe -CommandType Application -ErrorAction SilentlyContinue
    $ResourceCompiler = Get-Command rc.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $Compiler -or -not $Linker -or -not $ResourceCompiler -or -not $env:LIB -or
        $env:VSCMD_ARG_TGT_ARCH -ne 'x64' -or
        (Split-Path -Parent $Compiler.Source) -ne (Split-Path -Parent $Linker.Source)) {
        throw @'
Windows x64 MSVC build tools are unavailable or incomplete (cl.exe, link.exe, Windows SDK, or x64 environment).
Install Visual Studio 2022 Build Tools with "Desktop development with C++", including MSVC x64/x86 tools and a Windows 10/11 SDK.
If already installed, repair/add these components in Visual Studio Installer, or run this script from Developer PowerShell for VS with an x64 target.
Installing Rust or VS Code alone does not provide the MSVC linker. See apps/desktop/docs/build-windows.md.
'@
    }
    Write-Host "Using MSVC linker: $($Linker.Source)"
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This entry point requires Windows x64.'
}

$Repository = Split-Path -Parent $PSScriptRoot
Push-Location $Repository
try {
    Initialize-MsvcEnvironment
    $Python = $env:STAGE0_PYTHON
    if (-not $Python) {
        $Python = Join-Path $Repository '.venv/Scripts/python.exe'
    }
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
        throw 'Prepare .venv using apps/desktop/docs/build-windows.md or set STAGE0_PYTHON.'
    }
    Invoke-Checked $Python @('-c', 'import platform, struct, sys; assert sys.version_info >= (3, 11); assert platform.machine() == ''AMD64'' and struct.calcsize(''P'') == 8; import yaml, pydantic, psutil, watchdog')
    Get-Command cargo -ErrorAction Stop | Out-Null
    if (-not $env:CARGO_HOME) {
        $env:CARGO_HOME = Join-Path $Repository 'apps/desktop/build/stage0/cargo-home'
    }

    $Tools = 'apps/desktop/build/stage0/tools-windows-x86_64'
    if (-not (Test-Path "$Tools/PyInstaller" -PathType Container)) {
        Invoke-Checked $Python @('-m', 'pip', 'install', '--target', $Tools, '-r', 'apps/desktop/stage0/requirements.txt')
    }
    $Manifest = 'apps/desktop/stage0/tauri/Cargo.toml'
    & cargo fetch --offline --locked --manifest-path $Manifest
    if ($LASTEXITCODE -ne 0) {
        Invoke-Checked 'cargo' @('fetch', '--locked', '--manifest-path', $Manifest)
    }

    Invoke-Checked $Python @('-X', 'utf8', 'apps/desktop/stage0/build_probe.py', '--tools-dir', $Tools)
    $Sidecar = 'apps/desktop/dist/stage0/hybrid-stage0-probe-x86_64-pc-windows-msvc.exe'
    Invoke-Checked $Python @('-X', 'utf8', 'apps/desktop/stage0/verify.py', '--executable', $Sidecar,
        '--output', 'apps/desktop/build/stage0/frozen-results-windows-x86_64.json')

    $Target = 'x86_64-pc-windows-msvc'
    $TargetDirectory = 'apps/desktop/stage0/tauri/target'
    Invoke-Checked 'cargo' @('build', '--offline', '--locked', '--release', '--target', $Target,
        '--target-dir', $TargetDirectory, '--manifest-path', $Manifest, '--features', 'custom-protocol')

    # Verify a complete pair before replacing the previous preview directory.
    $Output = 'apps/desktop/dist/stage0/windows-x86_64'
    $Staging = "$Output-$([Guid]::NewGuid().ToString('N')).tmp"
    $Backup = "$Staging.previous"
    New-Item -ItemType Directory -Path $Staging | Out-Null
    try {
        Copy-Item -LiteralPath "$TargetDirectory/$Target/release/hybrid-stage0-shell.exe" -Destination "$Staging/Codex Hybrid.exe"
        Copy-Item -LiteralPath $Sidecar -Destination "$Staging/hybrid-stage0-probe.exe"
        Invoke-Checked $Python @('-X', 'utf8', 'apps/desktop/stage0/verify.py', '--executable', "$Staging/hybrid-stage0-probe.exe",
            '--output', 'apps/desktop/build/stage0/packaged-results-windows-x86_64.json')
        if (Test-Path -LiteralPath $Output) {
            Move-Item -LiteralPath $Output -Destination $Backup
        }
        try {
            Move-Item -LiteralPath $Staging -Destination $Output
        }
        catch {
            if (Test-Path -LiteralPath $Backup) {
                Move-Item -LiteralPath $Backup -Destination $Output
            }
            throw
        }
    }
    finally {
        if (Test-Path -LiteralPath $Staging) {
            Remove-Item -LiteralPath $Staging -Recurse -Force
        }
    }
    if (Test-Path -LiteralPath $Backup) {
        Remove-Item -LiteralPath $Backup -Recurse -Force
    }
    Write-Host "Desktop preview built at $Repository/$Output"
    Write-Host 'Keep both EXE files together. Close the running preview before rebuilding.'
}
finally {
    Pop-Location
}
