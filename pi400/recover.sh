#!/usr/bin/env bash
# LumaCut Pi 400 Recovery: repariert beschädigten Git-Checkout und startet den Marlin-Dienst neu.
#
# Warum: Am 25.10.2026 war der lokale /opt/lumacut/.git korrupt
# (loose object inflate error). Ein normaler git restore/merge scheiterte,
# der Dienst crashte mit ImportError weil die installierten Dateien
# nicht mehr zum aktuellen Quellstand passten.
#
# Dieses Skript:
# 1. Sichert die aktuelle /opt/lumacut und die Nutzerdaten.
# 2. Klont ein frisches Repository in ein temporäres Verzeichnis.
# 3. Ersetzt den Arbeitsbaum, behält /etc/lumacut und /var/lib/lumacut.
# 4. Prüft den Import von MarlinTransport.
# 5. Startet lumacut-marlin.service und prüft HTTP + TCP.
#
# Aufruf: sudo bash pi400/recover.sh
# Nach erfolgreichem Lauf sollte http://lumacut.local:8080 wieder erreichbar sein.

set -Eeuo pipefail

ROOT=/opt/lumacut
BACKUP_BASE=/var/lib/lumacut/recovery-backups
UPSTREAM=https://github.com/theubyte/LumaCut-CNC.git
SERVICE=lumacut-marlin.service

log() { printf '[LumaCut recover] %s\n' "$*" >&2; }
die() { log "FEHLER: $*"; exit 1; }

[[ $EUID -eq 0 ]] || die "Bitte mit sudo starten."

STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUP_BASE/$STAMP"
mkdir -p "$BACKUP"

log "Sichere aktuellen /opt/lumacut nach $BACKUP/opt-lumacut.tar.gz ..."
tar -czf "$BACKUP/opt-lumacut.tar.gz" -C /opt lumacut 2>/dev/null || log "Warnung: tar von /opt/lumacut teilweise fehlgeschlagen (Git korrupt?)."

log "Sichere /etc/lumacut und /var/lib/lumacut ..."
tar -czf "$BACKUP/etc-lumacut.tar.gz" -C /etc lumacut || true
tar -czf "$BACKUP/var-lib-lumacut.tar.gz" -C /var/lib lumacut || true

log "Klone frisches Repository ..."
TMP=$(mktemp -d)
git clone --depth 1 --branch main "$UPSTREAM" "$TMP/fresh" || die "Git-Clone fehlgeschlagen."

log "Ersetze Arbeitsbaum (Konfiguration und Nutzerdaten bleiben erhalten) ..."
systemctl stop "$SERVICE" || true
rm -rf "$ROOT"
mv "$TMP/fresh" "$ROOT"
chown -R lumacut:lumacut "$ROOT"
rm -rf "$TMP"

log "Prüfe Python-Import ..."
if ! runuser -u lumacut -- env PYTHONPATH="$ROOT/pi400" \
  python3 -c 'from marlin.transport import MarlinTransport; from marlin import web; print("Import OK:", type(web.machine).__name__)'; then
  die "Import von MarlinTransport fehlgeschlagen. Backup unter $BACKUP."
fi

log "Starte Dienst ..."
systemctl daemon-reload || true
systemctl enable "$SERVICE" || true
systemctl start "$SERVICE" || die "Service-Start fehlgeschlagen. Siehe journalctl -u $SERVICE"

sleep 3
if systemctl is-active --quiet "$SERVICE"; then
  log "Dienst aktiv."
else
  die "Dienst nicht aktiv. journalctl -u $SERVICE -n 40"
fi

log "Prüfe Ports ..."
if ss -ltnp | grep -q ':8080'; then
  log "HTTP 8080 lauscht."
else
  log "Warnung: HTTP 8080 noch nicht gebunden."
fi
if ss -ltnp | grep -q ':23'; then
  log "TCP 23 (LightBurn) lauscht."
else
  log "Warnung: TCP 23 noch nicht gebunden."
fi

log "RECOVERY ABGESCHLOSSEN. Backup liegt unter $BACKUP"
log "Webinterface: http://lumacut.local:8080"
log "Falls weiterhin Probleme: sudo journalctl -u $SERVICE -n 80 --no-pager"
exit 0
