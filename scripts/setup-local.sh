#!/usr/bin/env bash
# LumaCut CNC developer workstation bootstrap (Linux/macOS, x86_64 or aarch64).
# Run once on a computer with internet. Downloads are local; GitHub Actions
# are not used. Do not execute as root.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  echo "Bitte ohne sudo starten (venv und PlatformIO im Benutzerkonto)." >&2
  exit 1
fi
command -v python3 >/dev/null || { echo "Python 3 fehlt" >&2; exit 1; }
command -v git >/dev/null || { echo "Git fehlt" >&2; exit 1; }
python3 -m venv .venv
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install --disable-pip-version-check --upgrade pip
python -m pip install --disable-pip-version-check \
  "Flask==3.1.1" "pyserial==3.5" "pytest>=8,<10" "platformio==6.2.0"
echo "Lokale Werkzeuge:"
python --version
python -m platformio --version
if command -v node >/dev/null; then node --version; else
  echo "Optional: Node.js 20+ fuer JavaScript-Syntaxpruefung installieren." >&2
fi
echo "Bereit. Starte: bash scripts/local-test.sh quick"
echo "Firmware inkl. Marlin-Toolchain: bash scripts/local-test.sh firmware"
