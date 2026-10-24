#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE="/mnt/user/appdata/lumacut-builder"
PORT="18744"
NAME="lumacut-builder"
if ! command -v docker >/dev/null || ! docker info >/dev/null 2>&1; then
  echo "Docker auf Unraid aktivieren." >&2
  return 1 2>/dev/null || false
fi
mkdir -p "$STATE/source" "$STATE/data/artifacts" "$STATE/data/jobs" "$STATE/secrets" "$STATE/gh"
if [ "$ROOT" != "$STATE/source" ]; then cp -a "$ROOT"/. "$STATE/source"/; fi
chmod 700 "$STATE/gh"
# Container runs as UID 10001; a root-owned 0700 directory was not traversable.
# Make secrets readable/traversable only for that UID, with container mount read-only.
printf '%s\n' 'github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl' > "$STATE/secrets/known_hosts"
chown -R 10001:10001 "$STATE/secrets"
chmod 500 "$STATE/secrets"
chmod 644 "$STATE/secrets/known_hosts"
if [ -f "$STATE/secrets/deploy_key" ]; then chmod 400 "$STATE/secrets/deploy_key"; fi
chown -R 10001:10001 "$STATE/data"
if [ ! -f "$STATE/.env" ]; then
  umask 077
  SECRET="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  printf 'BUILDER_PASSWORD=%s\nGIT_REPOSITORY=git@github.com:theubyte/LumaCut-CNC.git\nGIT_BRANCH=main\n' "$SECRET" > "$STATE/.env"
fi
# Device update token is independent of the builder administrator password.
# Store it only in Unraid appdata, never in GitHub or public release JSON.
if ! grep -q '^UPDATE_DEVICE_KEY=' "$STATE/.env"; then
  umask 077
  UPDATE_SECRET="$(od -An -N32 -tx1 /dev/urandom | tr -dc '0-9a-f')"
  printf 'UPDATE_DEVICE_KEY=%s\n' "$UPDATE_SECRET" >> "$STATE/.env"
fi
if ! grep -q '^UPDATE_PUBLIC_ORIGIN=' "$STATE/.env"; then
  printf 'UPDATE_PUBLIC_ORIGIN=https://luma.millione.de\n' >> "$STATE/.env"
fi
chmod 600 "$STATE/.env"
echo "Baue Docker-Image ..."
docker build -t lumacut-builder:0.3 "$STATE/source/builder"
if docker container inspect "$NAME" >/dev/null 2>&1; then
  echo "Vorhandener LumaCut-Builder wird ersetzt; Buildarchive bleiben erhalten."
  docker rm -f "$NAME" >/dev/null
fi
docker run -d --name "$NAME" --restart unless-stopped \
  --publish "$PORT:8080" \
  --memory 3g --cpus 3 --pids-limit 256 \
  --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  --env-file "$STATE/.env" \
  --env 'PLATFORMIO_CORE_DIR=/data/pio' \
  --env 'GIT_SSH_COMMAND=ssh -i /run/secrets/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/run/secrets/known_hosts' \
  --volume "$STATE/data:/data:rw" \
  --volume "$STATE/secrets:/run/secrets:ro" \
  lumacut-builder:0.3 >/dev/null

# Check the same public JSON endpoint the Waveshare polls.
# The Flask app intentionally exempts it from Basic auth.
# A 401 on localhost means the container is stale or misconfigured.
# A 200 on localhost but 401 through HTTPS means the reverse proxy
# (Nginx Proxy Manager access list, Cloudflare Access, etc.) is blocking it.
if command -v curl >/dev/null 2>&1; then
  UPDATE_PATH="/api/updates/latest"
  LOCAL_CODE="000"
  for attempt in 1 2 3 4 5 6 7 8 9 10; do
    LOCAL_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:${PORT}${UPDATE_PATH}" || true)"
    if [ "$LOCAL_CODE" != "000" ]; then break; fi
    sleep 1
  done
  REMOTE_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://luma.millione.de${UPDATE_PATH}" || true)"
  echo "LumaCut Update-API: lokal HTTP $LOCAL_CODE / HTTPS-Domain HTTP $REMOTE_CODE"
  if [ "$LOCAL_CODE" != "200" ]; then
    echo "ACHTUNG: Die Update-API antwortet lokal nicht mit 200. Container/Route pruefen."
  elif [ "$REMOTE_CODE" = "401" ] || [ "$REMOTE_CODE" = "403" ]; then
    echo "FEHLER: Externe Update-API wird durch vorgeschaltete Auth gesperrt."
    echo "Reverse Proxy: /api/updates/latest ohne zusaetzliche Login-Schranke freigeben."
    echo "Der restliche Compiler bleibt durch Flask Basic-Auth geschuetzt."
  elif [ "$REMOTE_CODE" = "200" ]; then
    echo "OK: HMI kann die oeffentlichen Stable-Update-Metadaten abrufen (HTTP 200)."
  elif [ "$REMOTE_CODE" = "000" ]; then
    echo "HINWEIS: HTTPS-Domain vom Unraid-Host nicht erreichbar (DNS/TLS/Netzwerk)."
  else
    echo "HINWEIS: Externer Updatepfad HTTP $REMOTE_CODE. Proxy-Weiterleitung pruefen."
  fi
else
  echo "HINWEIS: curl fehlt, oeffentliche Update-API nicht geprueft."
fi
echo "Weboberfläche: http://DEINE-UNRAID-IP:18744"
echo "Login: lumacut"
echo "Passwort unter: $STATE/.env"
echo "GitHub-Leseschlüssel einrichten: bash $STATE/source/setup/github-setup.sh"
