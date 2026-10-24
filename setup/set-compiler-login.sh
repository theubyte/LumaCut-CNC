#!/usr/bin/env bash
# Change the persistent LumaCut Build Lab password ON THE UNRAID HOST.
# Never place the password in source control or shell command arguments.
set -Eeuo pipefail
STATE=/mnt/user/appdata/lumacut-builder
ENV_FILE="$STATE/.env"
if [ "$(id -u)" -ne 0 ]; then
  echo "Bitte als root auf Unraid/NextTerm ausfuehren." >&2
  exit 1
fi
if [ ! -f "$ENV_FILE" ]; then
  echo "Build-Lab .env fehlt: $ENV_FILE" >&2
  exit 1
fi
if [ ! -f "$STATE/source/setup/unraid-install.sh" ]; then
  echo "Unraid-Installer fehlt: $STATE/source/setup/unraid-install.sh" >&2
  exit 1
fi
echo 'Benutzername bleibt: lumacut'
echo 'Aktive Builds vorher beenden; Docker wird mit demselben Appdata neu erstellt.'
read -r -s -p 'Neues dauerhaftes Passwort: ' NEW_PASSWORD
printf '\n'
if [ "${#NEW_PASSWORD}" -lt 8 ] || [ "${#NEW_PASSWORD}" -gt 128 ]; then
  echo "Passwort muss zwischen 8 und 128 Zeichen enthalten." >&2
  exit 1
fi
if [[ "$NEW_PASSWORD" == *$'\n'* || "$NEW_PASSWORD" == *$'\r'* ]]; then
  echo "Zeilenumbrueche nicht erlaubt." >&2
  exit 1
fi
export LUMACUT_NEW_PASSWORD="$NEW_PASSWORD"
unset NEW_PASSWORD
python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os
import sys
p=Path(sys.argv[1])
password=os.environ["LUMACUT_NEW_PASSWORD"]
lines=p.read_text(encoding="utf-8").splitlines()
out=[]
written=False
for line in lines:
    if line.startswith("BUILDER_PASSWORD="):
        if not written:
            out.append("BUILDER_PASSWORD="+password)
            written=True
    else:
        out.append(line)
if not written:
    out.append("BUILDER_PASSWORD="+password)
temp=p.with_suffix(".env.new")
fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
with os.fdopen(fd,"w",encoding="utf-8") as target:
    target.write("\n".join(out)+"\n")
os.chmod(temp,0o600)
os.replace(temp,p)
PY
unset LUMACUT_NEW_PASSWORD
chmod 600 "$ENV_FILE"
bash "$STATE/source/setup/unraid-install.sh"
echo "Login aktualisiert: lumacut. Passwort bleibt in $ENV_FILE."
