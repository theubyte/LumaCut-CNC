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
chmod 700 "$STATE/secrets" "$STATE/gh"
chown -R 10001:10001 "$STATE/data"
if [ ! -f "$STATE/.env" ]; then
  umask 077
  SECRET="$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n')"
  printf 'BUILDER_PASSWORD=%s\nGIT_REPOSITORY=git@github.com:theubyte/LumaCut-CNC.git\nGIT_BRANCH=main\n' "$SECRET" > "$STATE/.env"
fi
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
echo "Weboberfläche: http://DEINE-UNRAID-IP:18744"
echo "Login: lumacut"
echo "Passwort unter: $STATE/.env"
echo "GitHub-Leseschlüssel einrichten: bash $STATE/source/setup/github-setup.sh"
