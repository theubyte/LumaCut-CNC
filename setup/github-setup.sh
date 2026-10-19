#!/usr/bin/env bash
set -Eeuo pipefail
STATE="/mnt/user/appdata/lumacut-builder"
REPO="theubyte/LumaCut-CNC"
IMAGE="ghcr.io/cli/cli:latest"
[ -f "$STATE/source/README.md" ] || { echo "Zuerst unraid-install.sh ausführen"; exit 1; }
mkdir -p "$STATE/secrets" "$STATE/gh"
chmod 700 "$STATE/secrets" "$STATE/gh"
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
  gh api /meta --jq ".ssh_keys[]" | sed "s/^/github.com /" > /keys/known_hosts
  grep -q "^github.com ssh-ed25519 " /keys/known_hosts
  '
chown 10001:10001 "$STATE/secrets/deploy_key" "$STATE/secrets/known_hosts"
chmod 400 "$STATE/secrets/deploy_key"
chmod 644 "$STATE/secrets/known_hosts"
echo "Fertig. Builder ist mit privatem GitHub-Lesezugriff ausgestattet."
echo "Wähle danach in http://DEINE-UNRAID-IP:18744 den Tests-Button."
