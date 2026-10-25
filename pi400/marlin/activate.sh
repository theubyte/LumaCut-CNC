#!/usr/bin/env bash
# Controlled Pi400 switch to native Marlin web bridge, AFTER SKR firmware flash.
# Does not flash SKR or move axes.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo starten" >&2; exit 1; }
[[ "${1:-}" == "--laser-disconnected" ]] || {
  echo "Abbruch: Nur bei physisch getrennter Laser-Versorgung und PWM." >&2
  echo "Nach einem SKR-Marlin-Flash: sudo bash pi400/marlin/activate.sh --laser-disconnected" >&2
  exit 1
}
ROOT=/opt/lumacut
ENV=/etc/lumacut/lumacut.env
[[ -f "$ENV" && -f "$ROOT/pi400/marlin/web.py" ]] || {
  echo "Pi Marlin-Version oder Konfiguration fehlt." >&2; exit 1;
}
set -a
# shellcheck disable=SC1090
source "$ENV"
set +a
: "${LUMACUT_KEY:?}"
: "${LUMACUT_SKR:?}"
echo "LumaCut: Beende bisherigen GRBL-Dienst – kein SKR-Firmwareflash."
systemctl stop lumacut.service || true
systemctl stop lumacut-marlin.service 2>/dev/null || true
rollback(){
  echo "Marlin USB-Identität/Service fehlgeschlagen. Alten Pi-Dienst wiederherstellen." >&2
  systemctl stop lumacut-marlin.service 2>/dev/null || true
  systemctl disable lumacut-marlin.service 2>/dev/null || true
  systemctl enable lumacut.service
  systemctl start lumacut.service
}
trap rollback ERR
echo "Suche USB-Geraete und pruefe echte Marlin-LumaCut-Identitaet via M115."
# The old grblHAL USB identity may disappear after flashing Marlin.
# Probe serial devices but accept only an explicitly LumaCut-named Marlin.
DETECTED_PORT=$(runuser -u lumacut -- env PYTHONPATH="$ROOT/pi400" \
  python3 -m marlin.usb_detect "$LUMACUT_SKR") || {
  echo "SKR nicht als LumaCut Marlin erkannt; Firmware/USB-Verbindung pruefen." >&2
  exit 2
}
[[ "$DETECTED_PORT" == /dev/* ]] || { echo "Ungueltiger USB-Pfad" >&2; exit 2; }
echo "Verifizierter SKR-USB-Pfad: $DETECTED_PORT"
# Keep the old grblHAL machine USB config completely unchanged.
# A separate Marlin override survives reboot and is read only by
# lumacut-marlin.service after the regular EnvironmentFile.
umask 077
TEMP_PORT_FILE=$(mktemp /etc/lumacut/.marlin-port.XXXXXXXX)
printf 'LUMACUT_SKR=%s\n' "$DETECTED_PORT" > "$TEMP_PORT_FILE"
chmod 600 "$TEMP_PORT_FILE"
mv -f "$TEMP_PORT_FILE" /etc/lumacut/lumacut-marlin-port.env
cp "$ROOT/pi400/marlin/lumacut-marlin.service" /etc/systemd/system/
systemctl daemon-reload
systemctl disable lumacut.service
systemctl enable --now lumacut-marlin.service
ready=0
for i in $(seq 1 15); do
  if curl -fsS --max-time 2 -H "X-LumaCut-Key: $LUMACUT_KEY" \
    "http://127.0.0.1:${LUMACUT_HTTP:-8080}/api/status" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" == "1" ]] || {
  journalctl -u lumacut-marlin.service -n 25 --no-pager >&2 || true
  exit 1
}
trap - ERR
echo "LumaCut MARLIN aktiv – Control OS: http://lumacut.local:${LUMACUT_HTTP:-8080}"
echo "LightBurn Custom GCode/Marlin über Pi-IP TCP ${LUMACUT_TCP:-23}"
echo "Bewegungen bleiben gesperrt, bis Mechanik/Z-Homing einzeln geprüft wurden."
