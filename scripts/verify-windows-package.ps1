$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$download = Join-Path $env:RUNNER_TEMP 'muyi-download'
$zip = Join-Path $download 'MuyiMaterialLibrary-windows-x64.zip'
$expected = (Get-Content (Join-Path $download 'SHA256.txt') -Raw).Trim()
if ((Get-FileHash -Algorithm SHA256 $zip).Hash -ne $expected) {
    throw 'Downloaded Windows package SHA-256 does not match the build job.'
}
$install = Join-Path $env:RUNNER_TEMP 'muyi-test install'
Expand-Archive -LiteralPath $zip -DestinationPath $install
$exe = Join-Path $install 'MuyiMaterialLibrary/MuyiMaterialLibrary.exe'
$python = (Get-Command python.exe).Source

# Only the test harness uses the runner Python. The child app gets the OS PATH.
$env:Path = @(
    "$env:SystemRoot\System32"
    "$env:SystemRoot"
    "$env:SystemRoot\System32\Wbem"
    "$env:SystemRoot\System32\WindowsPowerShell\v1.0"
) -join ';'
foreach ($dependency in @('ffmpeg.exe', 'pg_ctl.exe', 'python.exe', 'node.exe')) {
    if (Get-Command $dependency -ErrorAction SilentlyContinue) {
        throw "Unexpected test runner dependency on PATH: $dependency"
    }
}
$work = Join-Path $env:RUNNER_TEMP 'muyi-verify'
& $python -I scripts/smoke_standalone.py --launcher $exe --work $work --media-bin $env:MUYI_TEST_MEDIA_BIN --check-no-tools
