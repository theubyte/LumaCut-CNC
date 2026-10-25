#!/usr/bin/env bash
# LumaCut Pi 400 installation: Marlin gateway, web UI, nightly updater.
# Raspberry Pi OS (64-bit). Run from a fresh clone:
#   git clone https://github.com/theubyte/LumaCut-CNC.git && sudo bash LumaCut-CNC/pi400/install.sh
# Never flashes the SKR; firmware updates go through the web UI.
set -Eeuo pipefail
[[ $EUID -eq 0 ]] || { echo "Bitte mit sudo starten" >&2; exit 1; }
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/pi400/marlin/web.py" ]] || { echo "LumaCut-Repository unvollständig: $REPO" >&2; exit 1; }
TARGET=/opt/lumacut
ENV=/etc/lumacut/lumacut.env
PORT_ENV=/etc/lumacut/lumacut-marlin-port.env

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-flask python3-serial git curl avahi-daemon ca-certificates

id lumacut >/dev/null 2>&1 || useradd --system --home /var/lib/lumacut \
  --shell /usr/sbin/nologin --user-group lumacut
usermod -aG dialout lumacut
install -d -o lumacut -g lumacut -m 750 /var/lib/lumacut
install -d -m 755 /etc/lumacut

if [[ "$REPO" != "$TARGET" ]]; then
  [[ ! -e "$TARGET" ]] || { echo "FEHLER: $TARGET existiert bereits (Update: pi400/update.sh)" >&2; exit 1; }
  mv "$REPO" "$TARGET"
fi
chown -R lumacut:lumacut "$TARGET"

if [[ ! -f "$ENV" ]]; then
  umask 077
  cat > "$ENV" <<EOF
LUMACUT_SKR=/dev/ttyACM0
LUMACUT_HTTP=8080
LUMACUT_TCP=23
LUMACUT_DATA=/var/lib/lumacut
EOF
fi
set -a
# shellcheck disable=SC1090
source "$ENV"
set +a

# Pin the SKR by its stable /dev/serial/by-id path once it answers M115 as
# LumaCut Marlin. Without a connected SKR the service retries on its own.
if DETECTED=$(runuser -u lumacut -- env PYTHONPATH="$TARGET/pi400" \
      python3 -m marlin.usb_detect "${LUMACUT_SKR:-/dev/ttyACM0}"); then
  BY_ID=$(find /dev/serial/by-id -maxdepth 1 -type l 2>/dev/null | while read -r link; do
    [[ "$(readlink -f "$link")" == "$(readlink -f "$DETECTED")" ]] && echo "$link"; done | head -n1)
  umask 077
  printf 'LUMACUT_SKR=%s\n' "${BY_ID:-$DETECTED}" > "$PORT_ENV"
  echo "SKR erkannt: ${BY_ID:-$DETECTED}"
else
  echo "WARNUNG: SKR nicht als LumaCut-Marlin erkannt. Dienst startet trotzdem und versucht es weiter." >&2
fi

# Remove the former grblHAL service if an old installation left it behind.
if [[ -f /etc/systemd/system/lumacut.service ]]; then
  systemctl disable --now lumacut.service 2>/dev/null || true
  rm -f /etc/systemd/system/lumacut.service
fi
cp "$TARGET/pi400/marlin/lumacut-marlin.service" /etc/systemd/system/
cp "$TARGET/pi400/systemd/lumacut-update.service" /etc/systemd/system/
cp "$TARGET/pi400/systemd/lumacut-update.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now avahi-daemon.service
systemctl enable --now lumacut-marlin.service
systemctl enable --now lumacut-update.timer

for _ in $(seq 1 15); do
  if curl -fsS --max-time 2 "http://127.0.0.1:${LUMACUT_HTTP:-8080}/api/status" >/dev/null 2>&1; then
    echo "LumaCut läuft: http://lumacut.local:${LUMACUT_HTTP:-8080}"
    exit 0
  fi
  sleep 1
done
journalctl -u lumacut-marlin.service -n 30 --no-pager >&2 || true
echo "FEHLER: Web-API antwortet nicht" >&2
exit 1
