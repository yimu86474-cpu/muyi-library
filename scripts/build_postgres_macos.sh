#!/bin/bash
# Build the standalone application's PostgreSQL runtime from upstream sources.
set -euo pipefail

output="${1:?Pass a destination for the PostgreSQL runtime}"
inputs="${MUYI_MACOS_INPUTS:-${RUNNER_TEMP:-/tmp}/muyi-macos-inputs}"
version=18.6
archive="$inputs/postgresql-$version.tar.bz2"
checksum=555610c24d53e4316da5b7d3fc25c279d96856d5e0e23ee308c328c5fa881d9f
mkdir -p "$inputs" "$output"
output="$(cd "$output" && pwd)"
if [[ -e "$output/bin" ]]; then
  echo "PostgreSQL output already populated" >&2
  exit 1
fi
if [[ ! -f "$archive" ]]; then
  curl --fail --silent --show-error --location --retry 2 --continue-at - --max-time 900 \
    --output "$archive.part" "https://ftp.postgresql.org/pub/source/v$version/postgresql-$version.tar.bz2"
  mv "$archive.part" "$archive"
fi
printf '%s  %s\n' "$checksum" "$archive" | shasum -a 256 -c -
work="$(mktemp -d "${RUNNER_TEMP:-/tmp}/muyi-postgres-build.XXXXXX")"
trap 'rm -rf "$work"' EXIT
tar -xjf "$archive" -C "$work"
cd "$work/postgresql-$version"
./configure --prefix="$work/install" --without-icu --without-readline --without-zlib --disable-rpath
make -j"${MUYI_BUILD_JOBS:-4}" -s
make -s install
mkdir "$output/bin"
for tool in initdb pg_ctl postgres; do
  cp "$work/install/bin/$tool" "$output/bin/$tool"
done
cp -R "$work/install/lib" "$work/install/share" "$output/"
# The upstream Make build records its install prefix in library references.
libpq="$work/install/lib/libpq.5.dylib"
install_name_tool -id "@loader_path/libpq.5.dylib" "$output/lib/libpq.5.dylib"
install_name_tool -change "$libpq" "@loader_path/../lib/libpq.5.dylib" "$output/bin/initdb"
install_name_tool -change "$libpq" "@loader_path/libpq.5.dylib" "$output/lib/libpqwalreceiver.dylib"
rm -rf "$output/lib/pgxs"
find "$output/lib" -maxdepth 1 \( -name 'libecpg*' -o -name 'libpgtypes*' -o -name '*.a' \) -delete
for changed in "$output/bin/initdb" "$output/lib/libpq.5.dylib" "$output/lib/libpqwalreceiver.dylib"; do
  codesign --force --sign - "$changed"
done
cp COPYRIGHT "$output/LICENSE"
printf '%s\n' "PostgreSQL $version" \
  "https://ftp.postgresql.org/pub/source/v$version/postgresql-$version.tar.bz2" \
  "SHA-256 $checksum" > "$output/SOURCE.txt"
