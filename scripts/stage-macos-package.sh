#!/bin/bash
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
python="${MUYI_BUILD_PYTHON:-python3}"
output="${1:?Pass an output directory for the disk image}"
mkdir -p "$output"
output="$(cd "$output" && pwd)"
build="$(mktemp -d "${RUNNER_TEMP:-/tmp}/muyi-mac-build.XXXXXX")"
trap 'rm -rf "$build"' EXIT

if [[ "$(uname -m)" != arm64 ]]; then
  echo "This Mac preview is built for Apple Silicon" >&2
  exit 1
fi
pgroot="${MUYI_MACOS_POSTGRES:-$build/postgres}"
if [[ -z "${MUYI_MACOS_POSTGRES:-}" ]]; then
  "$repo/scripts/build_postgres_macos.sh" "$pgroot"
fi

disk="$build/disk"
app="$disk/MuyiMaterialLibrary.app"
bundle="$app/Contents/Resources/MuyiMaterialLibrary"
mkdir -p "$app/Contents/MacOS"
"$python" "$repo/scripts/build_standalone.py" --output "$bundle" --postgres-root "$pgroot"
printf 'source_commit=%s\n' "$(git -C "$repo" rev-parse HEAD)" > "$bundle/build-info.txt"
cp "$repo/scripts/macos/Info.plist" "$app/Contents/Info.plist"
cp "$repo/scripts/macos/launcher" "$app/Contents/MacOS/launcher"
chmod +x "$app/Contents/MacOS/launcher"
codesign --force --sign - "$app"
codesign --verify --strict "$app"
ln -s /Applications "$disk/Applications"
ditto "$bundle/chrome-extension" "$disk/Chrome Collector"
dmg="$output/MuyiMaterialLibrary-macOS-arm64.dmg"
hdiutil create -quiet -fs HFS+ -format UDZO -volname "Muyi Material Library" -srcfolder "$disk" "$dmg"
(cd "$output" && shasum -a 256 "$(basename "$dmg")" > SHA256.txt)
