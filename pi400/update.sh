#!/usr/bin/env bash
# Headless Pi update. Never flash SKR here; requires a separate proven bootloader.
set -Eeuo pipefail
ROOT=/opt/lumacut
ENV=/etc/lumacut/lumacut.env
LOCK=/var/lib/lumacut/maintenance.lock
[[ -f "$ENV" && -d "$ROOT/.git" ]] || exit 1
source "$ENV"
exec 9>/run/lumacut-update.flock
flock -n 9 || exit 0
idle(){
  local status
  status="$(curl --silent --max-time 4 -H "X-LumaCut-Key: $LUMACUT_KEY" \
    http://127.0.0.1:8080/api/status)" || return 1
  STATUS_JSON="$status" python3 - <<'PY'
import json,os,sys
try: d=json.loads(os.environ["STATUS_JSON"])
except (ValueError,KeyError): sys.exit(1)
sys.exit(0 if d.get("owner")=="Frei" and d.get("state") in
         ("Idle","Disconnected","Unknown","Alarm") else 1)
PY
}
idle || exit 0
touch "$LOCK"
chown lumacut:lumacut "$LOCK"
trap 'rm -f "$LOCK"' EXIT
sleep 0.5
idle || exit 0
old="$(runuser -u lumacut -- git -C "$ROOT" rev-parse HEAD)"
if ! runuser -u lumacut -- git -C "$ROOT" fetch --quiet origin main; then
  echo "LumaCut: GitHub fetch not configured; add a read-only deploy key." >&2
  exit 0
fi
new="$(runuser -u lumacut -- git -C "$ROOT" rev-parse origin/main)"
[[ "$old" != "$new" ]] || exit 0
runuser -u lumacut -- git -C "$ROOT" merge-base --is-ancestor "$old" "$new" || {
  echo "LumaCut: non-fast-forward rejected" >&2; exit 1;
}
systemctl stop lumacut.service
if ! runuser -u lumacut -- git -C "$ROOT" merge --ff-only "$new"; then
  systemctl start lumacut.service; exit 1
fi
if ! python3 -m compileall -q "$ROOT/pi400"; then
  runuser -u lumacut -- git -C "$ROOT" reset --hard "$old"
  systemctl start lumacut.service
  exit 1
fi
systemctl start lumacut.service
sleep 3
if ! systemctl is-active --quiet lumacut.service; then
  systemctl stop lumacut.service || true
  runuser -u lumacut -- git -C "$ROOT" reset --hard "$old"
  systemctl start lumacut.service
  echo "Pi update reverted to $old" >&2
  exit 1
fi
echo "LumaCut Pi updated: $old -> $new"
