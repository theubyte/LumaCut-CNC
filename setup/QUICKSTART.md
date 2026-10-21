# LumaCut Build Lab – Unraid Schnellstart

## Voraussetzungen

Unraid mit Docker, SSH/Termius, Internetzugriff und Zugang zum GitHub-Repository `theubyte/LumaCut-CNC`.
Niemals die Weboberfläche mit HTTP Basic Auth direkt ins öffentliche Internet stellen.

## Erstinstallation

Repository in einen Ordner auf Unraid herunterladen/entpacken und dort ausführen:

```bash
bash setup/INSTALL-ALL.sh
```

Das Setup erstellt `/mnt/user/appdata/lumacut-builder` und installiert den Docker-Container auf Port **18744**. Das Erstsetup richtet bei Bedarf GitHub-Lesezugriff über einen Deploy Key ein.

## Bestehendes Build Lab aktualisieren

Ein Commit auf GitHub ersetzt **nicht** automatisch die Dateien im bereits laufenden Docker-Container. Für die neue Flash-Funktion den Container mit aktuellem Quellcode neu bauen. Im Unraid-Termius-Terminal:

```bash
TMP_DIR="$(mktemp -d)"
curl -fL --retry 3 -o "$TMP_DIR/lumacut-main.tar.gz" \
  https://github.com/theubyte/LumaCut-CNC/archive/refs/heads/main.tar.gz &&
tar -xzf "$TMP_DIR/lumacut-main.tar.gz" -C "$TMP_DIR" &&
bash "$TMP_DIR/LumaCut-CNC-main/setup/unraid-install.sh"
```

Der Download per URL funktioniert nur, solange das Repository öffentlich erreichbar ist. Bestehendes Webpasswort, GitHub-Schlüssel und frühere Buildarchive bleiben beim erneuten Setup erhalten.

## Build Lab öffnen

Browser: `http://DEINE-UNRAID-IP:18744`

Benutzer: `lumacut`

Passwort: Inhalt von `BUILDER_PASSWORD` in `/mnt/user/appdata/lumacut-builder/.env`.

## Waveshare HMI flashen

1. Im Build Lab **Waveshare HMI (nur Touch) bauen** wählen.
2. Warten, bis der Build als `success` erscheint.
3. **Windows-Flashpaket** herunterladen und vollständig entpacken.
4. Waveshare `ESP32-S3-Touch-LCD-7 Rev1.2` per USB-Datenkabel am **USB TO UART** anschließen, Umschalter auf **UART1**.
5. Auf Windows mit Python 3 die Datei `Flash-Waveshare-Windows.cmd` starten. Chrome/Edge öffnet die lokale Web-Serial-Oberfläche.
6. **Installieren**, den richtigen COM-Port auswählen und nach Erfolg **RESET** drücken.

Bei vertrauenswürdigem **HTTPS** am Build Lab steht nach erfolgreichem Build alternativ **Jetzt per PC-USB flashen** direkt im Browser zur Verfügung. Die gewöhnliche HTTP-LAN-Adresse erlaubt Web Serial nicht; das lokale Windows-Flashpaket löst dies über `127.0.0.1`.

Ausführliche Erklärung: [Build Lab und Flashen](../builder/README.md).

**Sicherheit:** Dies ist eine noch nicht an echter Hardware verifizierte Entwicklungsfirmware. Laser und TTL bei der ersten Inbetriebnahme stromlos/getrennt lassen. SKR-flashen ist bewusst nicht über das Build Lab möglich.

## Wenn etwas nicht funktioniert

- Docker-Protokolle: `docker logs --tail 80 lumacut-builder`
- Passwort: `grep '^BUILDER_PASSWORD=' /mnt/user/appdata/lumacut-builder/.env` (nicht im Chat veröffentlichen)
- USB-Port: Originales Datenkabel, korrekte Buchse und UART1 prüfen, andere serielle Programme schließen.
- Kein Python 3: Python unter Windows installieren und CMD-Datei erneut starten.
- Kein GitHub-Zugriff: Deploy Key und `/mnt/user/appdata/lumacut-builder/secrets` prüfen.

Keine der oben genannten Befehle beendet deine SSH-Sitzung.
