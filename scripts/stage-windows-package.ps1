$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$buildRoot = Join-Path $env:RUNNER_TEMP 'muyi-package'
$pgRoot = Join-Path $buildRoot 'postgres-bin'
$uploadRoot = Join-Path $buildRoot 'upload'
New-Item -ItemType Directory -Path $uploadRoot | Out-Null
& "$PSScriptRoot/build-postgres-windows.ps1" -OutputRoot $pgRoot
$version = & (Join-Path $pgRoot 'bin/pg_ctl.exe') --version

$package = Join-Path $buildRoot 'MuyiMaterialLibrary'

python scripts/build_standalone.py --postgres-root $pgRoot --output $package
@(
    "source_commit=$env:GITHUB_SHA"
    "runner_image=$env:ImageVersion"
    "postgresql=$version"
) | Set-Content -Encoding ascii (Join-Path $package 'build-info.txt')

$zip = Join-Path $uploadRoot 'MuyiMaterialLibrary-windows-x64.zip'
tar.exe -a -cf $zip -C $buildRoot 'MuyiMaterialLibrary'
(Get-FileHash -Algorithm SHA256 $zip).Hash | Set-Content -Encoding ascii (Join-Path $uploadRoot 'SHA256.txt')
