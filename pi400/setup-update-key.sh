#!/usr/bin/env bash
# Provision a SEPARATE read-only GitHub deploy key for automatic Pi updates.
# Never copy or print an existing private key.
set -Eeuo pipefail
[[ "$(id -u)" -eq 0 ]] || { echo "sudo bash pi400/setup-update-key.sh"; exit 1; }
install -d -o lumacut -g lumacut -m 700 /var/lib/lumacut/.ssh
KEY=/var/lib/lumacut/.ssh/id_ed25519
if [[ ! -f "$KEY" ]]; then
  runuser -u lumacut -- ssh-keygen -q -t ed25519 -N "" -f "$KEY" \
    -C "lumacut-pi400-readonly"
fi
chmod 600 "$KEY"
chown lumacut:lumacut "$KEY" "$KEY.pub"
echo
echo "DIESEN öffentlichen Key in GitHub hinzufügen:"
echo "Repository theubyte/LumaCut-CNC → Settings → Deploy keys → Add deploy key"
echo "'Allow write access' darf NICHT angehakt werden."
echo
cat "$KEY.pub"
echo
echo "GitHub Host-Key-Fingerprint vor dem ersten SSH-Kontakt unabhängig prüfen."
echo "Dann als Pi-Service testen:"
echo "sudo -u lumacut ssh -T git@github.com"
echo "Automatische Softwareupdates: sudo systemctl start lumacut-update"
