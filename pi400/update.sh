#!/usr/bin/env bash
# LumaCut Pi 400 fail-closed updater with actionable diagnostics.
# Never flashes the SKR. Refuses updates while LightBurn/jobs own the motion controller.
# Run nightly by lumacut-update.timer; manual: sudo bash pi400/update.sh [update|diagnose]
set -Eeuo pipefail

ROOT=/opt/lumacut
ENV_FILE=/etc/lumacut/lumacut.env
LOCK=/var/lib/lumacut/maintenance.lock
UPSTREAM_PUBLIC=https://github.com/theubyte/LumaCut-CNC.git
MODE=${1:-update}
SERVICE=lumacut-marlin.service
ORIGINAL_REV=
STOPPED_SERVICE=0
CREATED_LOCK=0

log(){ printf '[LumaCut updater] %s\n' "$*" >&2; }
die(){ log "FEHLER: $*"; exit 1; }
cleanup(){
  if (( STOPPED_SERVICE )); then
    log "FEHLERBEHEBUNG: Starte den gestoppten LumaCut-Dienst erneut."
    systemctl start "$SERVICE" || true
  fi
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
    systemctl start "$SERVICE" || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'recover "$LINENO"' ERR

[[ $EUID -eq 0 ]] || die "Bitte mit sudo starten."
[[ "$MODE" == "update" || "$MODE" == "diagnose" ]] || die "Verwendung: update.sh [update|diagnose]"
[[ -f "$ENV_FILE" ]] || die "Maschinen-Konfigurationsdatei fehlt: $ENV_FILE"
[[ -d "$ROOT/.git" ]] || die "Git-Arbeitsverzeichnis fehlt: $ROOT"
# shellcheck disable=SC1090
source "$ENV_FILE"
HTTP_PORT=${LUMACUT_HTTP:-8080}

status_json(){
  local answer attempt
  # systemctl reports active before Flask has bound its TCP port. In
  # particular, a restart followed immediately by update used to fail.
  for attempt in {1..15}; do
    if answer=$(curl -fs --max-time 2 \
      "http://127.0.0.1:${HTTP_PORT}/api/status" 2>/dev/null); then
      printf '%s' "$answer"
      return 0
    fi
    sleep 1
  done
  return 1
}
show_api_diagnostics(){
  log "HTTP-Port: ${HTTP_PORT}; systemd-Dienst:"
  systemctl --no-pager --full status "$SERVICE" 2>&1 | head -n 25 >&2 || true
  log "Aktuelle TCP-Listener:"
  ss -ltnp 2>/dev/null | head -n 35 >&2 || true
  log "Letzte Dienstmeldungen (keine Maschinen-Zugangscodes ausgeben):"
  journalctl -u "$SERVICE" -n 18 --no-pager --output=short 2>&1 >&2 || true
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
log "Pi-Service: $(systemctl is-active "$SERVICE" || true)"
if [[ "$MODE" == "diagnose" ]]; then
  if response=$(status_json); then
    safe_state "$response" || true
  else
    log "HTTP-Status nicht erreichbar auf 127.0.0.1:${HTTP_PORT}"
    show_api_diagnostics
  fi
  log "Arbeitsbaum mit Änderungen:"
  git_lumacut status --short || true
  log "Hinweis: diagnose ändert keine Dateien."
  exit 0
fi

exec 9>/run/lumacut-update.flock
flock -n 9 || die "Ein anderer LumaCut-Updater läuft bereits."
[[ ! -e "$LOCK" ]] || die "Bereits vorhandene Wartungssperre: $LOCK"
systemctl is-active --quiet "$SERVICE" || die "Pi-Service ist nicht aktiv. Bitte zuerst den Servicefehler beheben."
response=$(status_json) || { show_api_diagnostics; die "Steuerungs-API unter 127.0.0.1:${HTTP_PORT} nicht erreichbar."; }
safe_state "$response" || die "LightBurn schließen, alle Jobs beenden und erneut aktualisieren."

# Refuse tracked local modifications rather than silently discarding them.
git_lumacut diff --quiet || die "Lokale Änderungen vorhanden. Zuerst sichern; kein automatischer Hard-Reset."
git_lumacut diff --cached --quiet || die "Vorgemerkte lokale Änderungen vorhanden. Zuerst sichern."
ORIGINAL_REV=$(git_lumacut rev-parse HEAD)

log "Aktuelle GitHub-Version über HTTPS abfragen (unabhängig vom SSH-Deploy-Key) ..."
GIT_TERMINAL_PROMPT=0 git_lumacut fetch --no-tags "$UPSTREAM_PUBLIC" main ||
  die "GitHub über HTTPS nicht erreichbar. DNS/Netzwerk/Zertifikate/Git prüfen."
target=$(git_lumacut rev-parse FETCH_HEAD)
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
systemctl stop "$SERVICE"
STOPPED_SERVICE=1
git_lumacut merge --ff-only "$target" || die "Git Fast-forward fehlgeschlagen."
if ! python3 -m compileall -q "$ROOT/pi400"; then
  log "Python-Syntaxprüfung fehlgeschlagen. Rolle auf vorherigen Commit zurück."
  git_lumacut reset --hard "$ORIGINAL_REV"
  die "Python-Syntaxprüfung fehlgeschlagen."
fi
# Compileall doesn't catch missing runtime exports (e.g. MarlinTransport).
# Import under the same user/environment as the actual service.
if ! runuser -u lumacut -- env PYTHONPATH="$ROOT/pi400" \
  python3 -c 'from marlin.transport import MarlinTransport, MarlinLaserGuard, normalize, serve_tcp; from marlin import web; assert isinstance(web.machine, MarlinTransport)' ; then
  log "LumaCut-Modulimport fehlgeschlagen. Rolle auf vorherigen Commit zurück."
  git_lumacut reset --hard "$ORIGINAL_REV"
  die "Importprüfung fehlgeschlagen (MarlinTransport/web.py)."
fi
systemctl start "$SERVICE"
# Real health-check: 'systemctl active' may appear briefly between crashes.
if ! response=$(status_json) || ! systemctl is-active --quiet "$SERVICE"; then
  log "API-Starttest fehlgeschlagen. Rolle auf vorherigen Commit zurück."
  show_api_diagnostics
  systemctl stop "$SERVICE" || true
  git_lumacut reset --hard "$ORIGINAL_REV"
  systemctl start "$SERVICE" || true
  die "Service startet nicht dauerhaft oder HTTP-API ist nicht erreichbar."
fi
STOPPED_SERVICE=0
log "ERFOLG: $ORIGINAL_REV -> $target"
log "Hinweis: SKR-Firmware wird nicht automatisch aktualisiert (Web-UI: Karte SKR-Firmware)."
