#!/usr/bin/env bash
set -Eeuo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
bash "$HERE/unraid-install.sh"
bash "/mnt/user/appdata/lumacut-builder/source/setup/github-setup.sh"
echo "LumaCut Build Lab auf Port 18744 installiert."
