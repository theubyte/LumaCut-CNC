#!/usr/bin/env bash
# LumaCut on Raspberry Pi OS Lite 64-bit. Invoke: sudo bash pi400/install.sh
set -Eeuo pipefail
if [[ "$(id -u)" != 0 ]]; then echo "Bitte mit sudo starten"; exit 1; fi
REPO="$(cd "$(dirname "$0")/.." && pwd)"
[[ -f "$REPO/pi400/lumacut/app.py" ]] || { echo "LumaCut repo fehlt"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 python3-flask python3-serial python3-pip \
  git curl avahi-daemon network-manager ca-certificates
id lumacut >/dev/null 2>&1 || useradd --system --home /var/lib/lumacut \
  --shell /usr/sbin/nologin --user-group lumacut
usermod -aG dialout,video,render lumacut
mkdir -p /var/lib/lumacut/jobs /etc/lumacut /opt
chown -R lumacut:lumacut /var/lib/lumacut
chmod 750 /var/lib/lumacut
TARGET=/opt/lumacut
if [[ "$REPO" != "$TARGET" ]]; then
  if [[ -e "$TARGET" ]]; then
    echo "FEHLER: $TARGET existiert bereits. Quellen vorher abgleichen."; exit 1
  fi
  mv "$REPO" "$TARGET"
fi
chown -R lumacut:lumacut "$TARGET"
ENV=/etc/lumacut/lumacut.env
if [[ ! -f "$ENV" ]]; then
  KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
  PORT="/dev/ttyACM0"
  if compgen -G "/dev/serial/by-id/*" >/dev/null; then
    for dev in /dev/serial/by-id/*; do
      [[ -e "$dev" ]] || continue
      PORT="$dev"; break
    done
  fi
  cat > "$ENV" <<EOF
LUMACUT_KEY=$KEY
LUMACUT_SKR=$PORT
LUMACUT_HTTP=8080
LUMACUT_TCP=23
LUMACUT_DATA=/var/lib/lumacut
LUMACUT_CAMERA_CMD=/usr/bin/rpicam-still
EOF
  chmod 600 "$ENV"
  echo "=== Zugangscode nur hier angezeigt. Sicher aufbewahren ==="
  echo "$KEY"
fi
if [[ -d /etc/polkit-1/rules.d ]]; then
  cat > /etc/polkit-1/rules.d/49-lumacut-network.rules <<'EOF'
polkit.addRule(function(action, subject) {
    if (subject.user == "lumacut" &&
        action.id.indexOf("org.freedesktop.NetworkManager.") == 0) {
        return polkit.Result.YES;
    }
});
EOF
fi
cp "$TARGET/pi400/systemd/lumacut.service" /etc/systemd/system/
cp "$TARGET/pi400/systemd/lumacut-update.service" /etc/systemd/system/
cp "$TARGET/pi400/systemd/lumacut-update.timer" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now avahi-daemon.service
systemctl enable --now lumacut.service
systemctl enable --now lumacut-update.timer
echo "Control Studio: http://lumacut.local:8080"
echo "LightBurn: GRBL Network -> lumacut.local Port 23"
echo "SKR USB: Geraet in $ENV pruefen; vorher USB-grblHAL flashen."
