$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$url = 'https://aka.ms/vc14/vc_redist.x64.exe'
$installer = Join-Path $env:RUNNER_TEMP 'vc_redist.x64.exe'
curl.exe --fail --silent --show-error --location --retry 2 --max-time 120 --output $installer $url
$signature = Get-AuthenticodeSignature -LiteralPath $installer
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(?:^|, )O=Microsoft Corporation(?:,|$)') {
    throw 'The Microsoft Visual C++ installer does not have a valid Microsoft signature.'
}
$process = Start-Process -FilePath $installer -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru
if ($process.ExitCode -notin @(0, 1638, 3010)) {
    throw "Microsoft runtime installation exited with $($process.ExitCode)."
}
$systemRuntime = Join-Path $env:SystemRoot 'System32/vcruntime140.dll'
if (!(Test-Path -LiteralPath $systemRuntime)) {
    throw 'The Microsoft runtime is missing from System32.'
}
[ordered]@{
    official_source = $url
    installer_sha256 = (Get-FileHash -Algorithm SHA256 $installer).Hash
    installer_signature = $signature.Status.ToString()
    installer_exit = $process.ExitCode
    system_runtime_version = (Get-Item -LiteralPath $systemRuntime).VersionInfo.FileVersion
} | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $env:RUNNER_TEMP 'muyi-windows-runtime.json')
