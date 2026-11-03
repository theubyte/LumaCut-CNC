#!/usr/bin/env bash
# Build the panel firmware and hand it to the Pi: pi400/marlin/panel_fw/ gets the
# app image plus manifest.json; after commit + deploy the Pi flashes the panel itself.
# Run from firmware/panel. PYTHON may point at the Python with PlatformIO.
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python}
"$PY" -m platformio run
version=$(sed -n 's/^#define PANEL_VERSION "\(.*\)"/\1/p' src/version.h)
out=../../pi400/marlin/panel_fw
mkdir -p "$out"
cp .pio/build/panel/firmware.bin "$out/lumacut-panel.bin"
sum=$(sha256sum "$out/lumacut-panel.bin" | cut -d' ' -f1)
cat > "$out/manifest.json" <<EOF
{
  "version": "$version",
  "file": "lumacut-panel.bin",
  "address": "0x10000",
  "sha256": "$sum"
}
EOF
echo "Panel-Firmware $version -> $out ($(stat -c %s "$out/lumacut-panel.bin") Bytes)"
