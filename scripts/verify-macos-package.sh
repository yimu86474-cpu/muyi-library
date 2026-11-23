#!/bin/bash
set -euo pipefail

dmg="${1:?Pass the disk image to verify}"
results="${2:?Pass a new directory for verification results}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
python="${MUYI_BUILD_PYTHON:-python3}"
verification="$(mktemp -d "${RUNNER_TEMP:-/tmp}/muyi-mac-verify.XXXXXX")"
mounted="$verification/mounted"
cleanup() {
  if [[ -d "$mounted/MuyiMaterialLibrary.app" ]]; then hdiutil detach "$mounted" -quiet; fi
  rm -rf "$verification"
}
trap cleanup EXIT
hdiutil verify "$dmg"
hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mounted" "$dmg"
installed="$verification/Installed Apps"
mkdir "$installed"
ditto "$mounted/MuyiMaterialLibrary.app" "$installed/MuyiMaterialLibrary.app"
app="$installed/MuyiMaterialLibrary.app"
codesign --verify --strict "$app"
bundle="$app/Contents/Resources/MuyiMaterialLibrary"
env PATH=/usr/bin:/bin:/usr/sbin:/sbin "$python" "$repo/scripts/smoke_standalone.py" \
  --launcher "$app/Contents/MacOS/launcher" --tools-root "$bundle" --work "$results" \
  --ffmpeg "${MUYI_TEST_MEDIA_BIN:?Set the directory for the test FFmpeg and FFprobe}/ffmpeg" --check-no-tools
