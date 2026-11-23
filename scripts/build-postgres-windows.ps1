param([Parameter(Mandatory)][string] $OutputRoot)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

$version = '17.12'
$checksum = '9cf136a703d8ee2f83465c43be4e9e8e7930c82b0bfba13be7e2537be769ac55'
$work = Join-Path $env:RUNNER_TEMP 'muyi-postgres'
New-Item -ItemType Directory -Path $work | Out-Null
$archive = Join-Path $work "postgresql-$version.tar.bz2"
$url = "https://ftp.postgresql.org/pub/source/v$version/postgresql-$version.tar.bz2"

curl.exe --fail --silent --show-error --location --retry 2 --max-time 180 --output $archive $url
if ((Get-FileHash -Algorithm SHA256 $archive).Hash -ne $checksum) {
    throw 'PostgreSQL source SHA-256 mismatch.'
}
tar.exe -xf $archive -C $work
$src = Join-Path $work "postgresql-$version"
$build = Join-Path $work 'build'
$install = Join-Path $work 'install'
$env:CC = 'cl'
python -m mesonbuild.mesonmain setup $build $src --prefix $install --libdir lib --buildtype release --auto-features disabled -Dssl=none -Db_vscrt=md
python -m mesonbuild.mesonmain compile -C $build
python -m mesonbuild.mesonmain install -C $build --no-rebuild

New-Item -ItemType Directory -Path (Join-Path $OutputRoot 'bin') | Out-Null
foreach ($tool in @('initdb.exe', 'pg_ctl.exe', 'postgres.exe')) {
    Copy-Item -LiteralPath (Join-Path $install "bin/$tool") -Destination (Join-Path $OutputRoot 'bin')
}
Copy-Item -LiteralPath (Join-Path $install 'bin/libpq.dll') -Destination (Join-Path $OutputRoot 'bin')
foreach ($folder in @('lib', 'share')) {
    Copy-Item -LiteralPath (Join-Path $install $folder) -Destination $OutputRoot -Recurse
}
Copy-Item -LiteralPath (Join-Path $src 'COPYRIGHT') -Destination (Join-Path $OutputRoot 'LICENSE')
@("PostgreSQL $version", $url, "SHA-256 $checksum") | Set-Content -Encoding ascii (Join-Path $OutputRoot 'SOURCE.txt')
