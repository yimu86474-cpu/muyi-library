$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

# Test fixtures use an upstream FFmpeg build installed on the runner only.
$buildRoot = Join-Path $env:RUNNER_TEMP 'muyi-test-media'
New-Item -ItemType Directory -Path $buildRoot | Out-Null
$ffmpegArchive = Join-Path $buildRoot 'ffmpeg.7z'
$ffmpegSource = 'https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.1-essentials_build.7z'
curl.exe --fail --silent --show-error --location --retry 2 --max-time 120 --output $ffmpegArchive $ffmpegSource
$expected = '835b9a733445ba7a56a37a26cf7bde84e2f3ce7da2a8ec984276bb2abb1b922c'
if ((Get-FileHash -Algorithm SHA256 $ffmpegArchive).Hash -ne $expected) {
    throw 'FFmpeg archive SHA-256 differs from the verified source.'
}
$ffmpegRoot = Join-Path $buildRoot 'ffmpeg'
& "$env:ProgramFiles\7-Zip\7z.exe" x -y "-o$ffmpegRoot" $ffmpegArchive | Out-Null
$ffmpegRelease = Join-Path $ffmpegRoot 'ffmpeg-9.1-essentials_build'
$ffmpegBin = Join-Path $ffmpegRelease 'bin'

Add-Content -Path $env:GITHUB_ENV -Value "MUYI_TEST_MEDIA_BIN=$ffmpegBin"
