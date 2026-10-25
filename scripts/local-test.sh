#!/usr/bin/env bash
# Fast, local LumaCut checks; no GitHub Actions and no SKR flashing.
#
# syntax   -> Python, Bash, JavaScript, JSON (no Python packages needed)
# quick    -> syntax + native Marlin/Pi Python regression tests
# full     -> syntax + all Python tests (including previous grblHAL)
# firmware -> full + locally compile Marlin STM32F103RC via PlatformIO
# legacy   -> full + old grblHAL STM32F103RC build (only if requested)
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-quick}"
PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || PY=python3
PASSED=0

step(){
  echo
  printf '\n===== LumaCut LOCAL: %s =====\n' "$*"
}
check(){
  "$@"
  PASSED=$((PASSED + 1))
}
fail(){
  echo "LOKALER TEST FEHLGESCHLAGEN: $*" >&2
  exit 1
}

case "$MODE" in syntax|quick|full|firmware|legacy) ;; *)
  echo "Verwendung: bash scripts/local-test.sh [syntax|quick|full|firmware|legacy]" >&2
  exit 2
esac

# Standard: only current Marlin/Pi files and targeted regression tests.
# Full legacy regression and firmware compilation are explicit opt-ins.
if [[ "$MODE" == "quick" ]]; then
  step "Schnelltest: Marlin Python-Syntax"
  check "$PY" - <<'PY'
from pathlib import Path
paths = list(Path("pi400/marlin").glob("*.py"))
for file in paths:
    compile(file.read_text(encoding="utf-8"), str(file), "exec")
print("Marlin Python-Dateien:", len(paths))
PY
  step "Schnelltest: Marlin USB/TCP, Homing und Fehlerfaelle"
  check "$PY" -m unittest discover -s tests -p 'test_marlin_*.py' -q
  if command -v node >/dev/null; then
    step "Schnelltest: Marlin Web-UI JavaScript"
    tmpjs=$(mktemp --suffix=.js)
    trap 'rm -f "$tmpjs"' EXIT
    check "$PY" - "$tmpjs" <<'PY'
from pathlib import Path
import re, sys
source = Path("pi400/marlin/index.html").read_text(encoding="utf-8")
scripts = re.findall(r'<script[^>]*>([\s\S]*?)</script>', source)
if len(scripts) != 1:
    raise RuntimeError("Marlin UI JS Block missing/duplicated")
Path(sys.argv[1]).write_text(scripts[0], encoding="utf-8")
PY
    check node --check "$tmpjs"
  fi
  step "Schnelltest bestanden: $PASSED Pruefschritte"
  exit 0
fi

step "Python-Quelltext ohne neue Dateien kompilieren"
check "$PY" - <<'PY'
import pathlib
root=pathlib.Path.cwd()
folders=("pi400","firmware","tests","tools","builder")
paths=sorted(p for folder in folders for p in (root/folder).rglob("*.py")) 
for p in paths:
    try:
        compile(p.read_text(encoding="utf-8"),str(p),"exec")
    except Exception as exc:
        raise RuntimeError(f"{p.relative_to(root)}: {exc}") from exc
print("Python-Syntax geprueft:",len(paths),"Dateien")
PY

step "Bash-Skripte syntaktisch pruefen"
while IFS= read -r -d '' path; do
  check bash -n "$path"
done < <(find scripts pi400 -name '*.sh' -type f -print0 2>/dev/null)
echo "Bash-Syntax bestanden"

step "JSON-Manifeste pruefen"
check "$PY" - <<'PY'
import json,pathlib
root=pathlib.Path.cwd()
files=list(root.rglob("*.json"))
files=[p for p in files if not any(c in (".pio",".venv","node_modules",".cache") for c in p.parts)]
for p in files: json.loads(p.read_text(encoding="utf-8"))
print("JSON-Dateien geprueft:",len(files))
PY

step "Web-UI JavaScript mit Node pruefen"
if command -v node >/dev/null; then
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' EXIT
  check "$PY" - "$tmpdir" <<'PY'
import re,sys,pathlib
root=pathlib.Path.cwd()
out=pathlib.Path(sys.argv[1])
count=0
for path in (*root.glob("pi400/**/index.html"),
             *root.glob("pi400/**/service.html"),
             *root.glob("builder/*.html")):
    text=path.read_text(encoding="utf-8")
    for i,match in enumerate(re.finditer(r"<script(?:\s+[^>]*)?>([\s\S]*?)</script>",
                                      text,re.IGNORECASE)):
        target=out/f"check{count:03d}.js"
        target.write_text(match.group(1),encoding="utf-8")
        count+=1
print("JS-Bloecke extrahiert:",count)
PY
  for file in "$tmpdir"/*.js; do
    [[ -f "$file" ]] || continue
    check node --check "$file"
  done
  [[ ! -f builder/dashboard.js ]] || check node --check builder/dashboard.js
else
  fail "Node.js fehlt. JS-Pruefung fuer Webinterface ist erforderlich."
fi

if [[ "$MODE" == "syntax" ]]; then
  step "BESTANDEN: Syntaxpruefung abgeschlossen ($PASSED Pruefungen)"
  exit 0
fi

step "Python-Pakete pruefen"
"$PY" - <<'PY' || fail "Fehlende Python-Abhaengigkeiten. Mit Internetzugang einmal scripts/setup-local.sh ausfuehren."
import flask,serial,unittest
print("Flask:",flask.__version__ if hasattr(flask,"__version__") else "OK")
print("pyserial:",serial.VERSION)
PY

if [[ "$MODE" == "quick" ]]; then
  step "Marlin-Transport, USB-Erkennung und Web-Simulation (ohne Hardware)"
  check "$PY" -m unittest discover -s tests -p 'test_marlin_*.py' -v
  step "BESTANDEN: $PASSED lokale Pruefungen"
  exit 0
fi

step "Alle Projekt-Regressionstests"
check "$PY" -m unittest discover -s tests -v
if [[ "$MODE" == "full" ]]; then
  step "BESTANDEN: $PASSED lokale Pruefungen"
  exit 0
fi

step "PlatformIO pruefen"
"$PY" -m platformio --version || fail "PlatformIO nicht installiert; scripts/setup-local.sh mit Internet ausfuehren."

if [[ "$MODE" == "firmware" ]]; then
  step "Marlin STM32F103RC lokal kompilieren (kein SKR-Flash)"
  check "$PY" firmware/marlin/build.py
  "$PY" - <<'PY'
from pathlib import Path
import json,hashlib
p=Path("firmware/marlin/dist")
firmware=p/"firmware.bin"
manifest=json.loads((p/"manifest.json").read_text())
assert firmware.stat().st_size>4096
assert manifest["sha256"]==hashlib.sha256(firmware.read_bytes()).hexdigest()
assert manifest["hardware_verified"] is False
print("Marlin-Binary SHA256:",manifest["sha256"])
PY
elif [[ "$MODE" == "legacy" ]]; then
  step "Altes grblHAL lokal kompilieren (optional, kein SKR-Flash)"
  check "$PY" firmware/skr/build.py
fi
step "BESTANDEN: $PASSED lokale Pruefungen"
