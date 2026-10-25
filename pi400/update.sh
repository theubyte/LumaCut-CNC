#!/usr/bin/env bash
# LumaCut Pi 400 fail-closed updater with actionable diagnostics.
# Never flashes the SKR. Refuses updates while LightBurn/jobs own the motion controller.
set -Eeuo pipefail

ROOT=/opt/lumacut
ENV_FILE=/etc/lumacut/lumacut.env
LOCK=/var/lib/lumacut/maintenance.lock
UPSTREAM_PUBLIC=https://github.com/theubyte/LumaCut-CNC.git
MODE=${1:-update}
ORIGINAL_REV=
STOPPED_SERVICE=0
CREATED_LOCK=0

log(){ printf '[LumaCut updater] %s\n' "$*" >&2; }
die(){ log "FEHLER: $*"; exit 1; }
cleanup(){
  if (( CREATED_LOCK )); then rm -f "$LOCK"; fi
}
recover(){
  local status=$?
  trap - ERR
  log "Fehler in Zeile $1 (Exitcode $status)."
  if (( STOPPED_SERVICE )); then
    if [[ -n "$ORIGINAL_REV" ]]; then
      log "Vorheriger Programmstand: $ORIGINAL_REV"
      log "Ein bereits aktualisierter Arbeitsbaum wird nicht blind überschrieben."
    fi
    systemctl start lumacut.service || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'recover "$LINENO"' ERR

[[ $EUID -eq 0 ]] || die "Bitte mit sudo starten."
[[ "$MODE" == "update" || "$MODE" == "diagnose" ]] || die "Verwendung: update.sh [update|diagnose]"
[[ -f "$ENV_FILE" ]] || die "Maschinen-Konfigurationsdatei fehlt: $ENV_FILE"
[[ -d "$ROOT/.git" ]] || die "Git-Arbeitsverzeichnis fehlt: $ROOT"
# The file is root-owned and not printed. Never put the access key into logs.
# shellcheck disable=SC1090
source "$ENV_FILE"
[[ -n "${LUMACUT_KEY:-}" ]] || die "LUMACUT_KEY nicht gesetzt"
HTTP_PORT=${LUMACUT_HTTP:-8080}

status_json(){
  curl -fsS --max-time 5 -H "X-LumaCut-Key: $LUMACUT_KEY" \
    "http://127.0.0.1:${HTTP_PORT}/api/status"
}
safe_state(){
  local payload="$1"
  STATUS_JSON="$payload" python3 - <<'PY'
import json,os,sys
try:
    s=json.loads(os.environ["STATUS_JSON"])
except (ValueError,TypeError,KeyError):
    print("Pi meldet keinen gültigen Maschinenstatus", file=sys.stderr)
    sys.exit(1)
owner=s.get("owner")
state=s.get("state")
print("Maschinenstatus:",state,"| Besitzer:",owner,
      "| USB:",s.get("connected"),"| SKR bereit:",s.get("ready"))
if owner!="Frei" or state not in ("Idle","Disconnected","Unknown","Alarm"):
    print("UPDATE GESPERRT: LightBurn/Job belegt die Maschine oder Bewegung aktiv.",
          file=sys.stderr)
    sys.exit(2)
PY
}
git_lumacut(){ runuser -u lumacut -- git -C "$ROOT" "$@"; }

log "Installierter Commit: $(git_lumacut rev-parse --short HEAD)"
log "Pi-Service: $(systemctl is-active lumacut.service || true)"
if [[ "$MODE" == "diagnose" ]]; then
  if response=$(status_json); then
    safe_state "$response" || true
  else
    log "HTTP-Status nicht erreichbar auf 127.0.0.1:${HTTP_PORT}"
  fi
  log "Arbeitsbaum mit Änderungen:"
  git_lumacut status --short || true
  log "Hinweis: diagnose ändert keine Dateien."
  exit 0
fi

exec 9>/run/lumacut-update.flock
flock -n 9 || die "Ein anderer LumaCut-Updater läuft bereits."
[[ ! -e "$LOCK" ]] || die "Bereits vorhandene Wartungssperre: $LOCK"
systemctl is-active --quiet lumacut.service || die "Pi-Service ist nicht aktiv. Bitte zuerst den Servicefehler beheben."
response=$(status_json) || die "Steuerungs-API unter 127.0.0.1:${HTTP_PORT} nicht erreichbar."
safe_state "$response" || die "LightBurn schließen, alle Jobs beenden und erneut aktualisieren."

# Refuse tracked local modifications rather than silently discarding them.
git_lumacut diff --quiet || die "Lokale Änderungen vorhanden. Zuerst sichern; kein automatischer Hard-Reset."
git_lumacut diff --cached --quiet || die "Vorgemerkte lokale Änderungen vorhanden. Zuerst sichern."
ORIGINAL_REV=$(git_lumacut rev-parse HEAD)

log "Aktuelle GitHub-Version abfragen ..."
if git_lumacut fetch --no-tags origin main; then
  target=$(git_lumacut rev-parse FETCH_HEAD)
else
  log "Origin-Fetch fehlgeschlagen; verwende das öffentliche HTTPS-Repository."
  git_lumacut fetch --no-tags "$UPSTREAM_PUBLIC" main ||
    die "GitHub nicht erreichbar. DNS/Netzwerk/Git prüfen."
  target=$(git_lumacut rev-parse FETCH_HEAD)
fi
log "GitHub-Commit: ${target:0:12}"
if [[ "$ORIGINAL_REV" == "$target" ]]; then
  log "Bereits aktuell. Keine Änderung notwendig."
  exit 0
fi
git_lumacut merge-base --is-ancestor "$ORIGINAL_REV" "$target" ||
  die "Git-Verlauf ist nicht fast-forward; bitte lokale Commits prüfen."

log "Aktualisierung wird ausgeführt (keine SKR-Flashes)."
touch "$LOCK"
chown lumacut:lumacut "$LOCK"
CREATED_LOCK=1
# Recheck after creating lock, so no new job can start unnoticed.
sleep 0.25
response=$(status_json) || die "API wurde vor dem Update nicht mehr erreicht."
safe_state "$response" || die "Maschine wurde vor Update belegt."
systemctl stop lumacut.service
STOPPED_SERVICE=1
git_lumacut merge --ff-only "$target" || die "Git Fast-forward fehlgeschlagen."
if ! python3 -m compileall -q "$ROOT/pi400"; then
  log "Python-Prüfung fehlgeschlagen. Rolle auf vorherigen Commit zurück."
  git_lumacut reset --hard "$ORIGINAL_REV"
  die "Python-Prüfung fehlgeschlagen."
fi
systemctl start lumacut.service
sleep 2
if ! systemctl is-active --quiet lumacut.service; then
  log "Pi-Dienststart fehlgeschlagen. Rolle auf vorherigen Commit zurück."
  systemctl stop lumacut.service || true
  git_lumacut reset --hard "$ORIGINAL_REV"
  systemctl start lumacut.service || true
  die "Pi-Service nach Update nicht aktiv. sudo journalctl -u lumacut -n 80 --no-pager"
fi
STOPPED_SERVICE=0
log "ERFOLG: $ORIGINAL_REV -> $target"
log "Hinweis: Die passende SKR-FAN1-LASER-Firmware wird separat benötigt."
