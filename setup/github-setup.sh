#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/mnt/user/appdata/lumacut-builder"
REPO="theubyte/LumaCut-CNC"
IMAGE="ghcr.io/cli/cli:latest"
[ -f "$STATE/source/README.md" ] || { echo "Zuerst unraid-install.sh ausführen"; exit 1; }
mkdir -p "$STATE/secrets" "$STATE/gh"
chmod 700 "$STATE/gh"
# Writable only while setting up. Reapply read/execute for container afterwards.
chown 10001:10001 "$STATE/secrets"
chmod 700 "$STATE/secrets"
if [ ! -f "$STATE/secrets/deploy_key" ]; then
  ssh-keygen -q -t ed25519 -N '' -C 'lumacut-unraid-readonly' -f "$STATE/secrets/deploy_key"
fi
docker pull "$IMAGE"
if ! docker run --rm -e GH_CONFIG_DIR=/gh -v "$STATE/gh:/gh" \
     --entrypoint gh "$IMAGE" auth status >/dev/null 2>&1; then
  echo "GitHub Gerätecode-Anmeldung (GitHub-Konto theubyte)"
  docker run --rm -it -e GH_CONFIG_DIR=/gh -v "$STATE/gh:/gh" \
    --entrypoint gh "$IMAGE" auth login --hostname github.com --git-protocol https --web --scopes repo
fi
docker run --rm -e GH_CONFIG_DIR=/gh -v "$STATE/gh:/gh" \
  -v "$STATE/secrets:/keys" \
  --entrypoint /bin/sh "$IMAGE" -ec '
  test "$(gh api user --jq .login)" = "theubyte" || { echo "Falsches GitHub-Konto"; exit 1; }
  test "$(gh api repos/theubyte/LumaCut-CNC --jq .private)" = true || { echo "Repo ist nicht privat"; exit 1; }
  pub="$(cat /keys/deploy_key.pub)"
  keys="$(gh api repos/theubyte/LumaCut-CNC/keys --jq ".[].key" 2>/dev/null || true)"
  if ! printf "%s\n" "$keys" | grep -Fqx "$pub"; then
    gh api -X POST repos/theubyte/LumaCut-CNC/keys -f title="LumaCut Unraid read-only" -f key="$pub" -F read_only=true >/dev/null
  fi
  # Official GitHub ED25519 host key, verified by published SHA256 fingerprint.
  # Do NOT bypass StrictHostKeyChecking and do not trust ssh-keyscan blindly.
  printf "%s\n" "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" > /keys/known_hosts
  '
chown 10001:10001 "$STATE/secrets/deploy_key" "$STATE/secrets/known_hosts"
chmod 400 "$STATE/secrets/deploy_key"
chmod 644 "$STATE/secrets/known_hosts"
chmod 500 "$STATE/secrets"
echo "Fertig. Builder ist mit privatem GitHub-Lesezugriff ausgestattet."
echo "Berechtigungen geprüft: UID 10001 darf /run/secrets durchqueren."
if docker container inspect lumacut-builder >/dev/null 2>&1; then
  echo "SSH-Repositoryprüfung im laufenden Builder:"
  docker exec lumacut-builder git ls-remote git@github.com:theubyte/LumaCut-CNC.git HEAD || {
    echo "SSH-Test fehlgeschlagen. Repo-Deploy-Key und Container-Mounts prüfen."; 
  }
fi
echo "Wähle danach in http://DEINE-UNRAID-IP:18744 den Tests-Button."
