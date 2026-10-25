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
echo "Erwarte Marlin 2.1.x mit eindeutigem LumaCut CNC Namen."
runuser -u lumacut -- env PYTHONPATH="$ROOT/pi400" \
  LUMACUT_SKR="$LUMACUT_SKR" python3 - <<'PY'
import os
from marlin.transport import MarlinTransport
m=MarlinTransport(os.environ["LUMACUT_SKR"])
try:
    m.ensure_ready()
    print("Bestätigte Marlin-Firmware:", m.status()["identity"])
finally:
    with m.lock:
        m._close_locked()
PY
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
