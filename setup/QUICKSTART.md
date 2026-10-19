# LumaCut: Installation auf Unraid

## Voraussetzungen
- Unraid mit x86-64 CPU, Docker und Internetverbindung, SSH/Termius.
- Ein privates GitHub-Repository theubyte/LumaCut-CNC (ist bereits erstellt).
- Für erstmalige Installation: Projekt als GitHub-ZIP herunterladen und per SFTP nach Unraid übertragen; GitHub-ZIP entpacken.
- Keine Installation auf dem Unraid-Bootstick, keine Container-Ports öffentlich ins Internet öffnen.

## In Termius
Im entpackten LumaCut-CNC-Ordner:
\`\`\`bash
bash setup/INSTALL-ALL.sh
\`\`\`
Das Skript erstellt /mnt/user/appdata/lumacut-builder, generiert ein sicheres Loginpasswort, erstellt ein Docker-Image und startet den Builder auf TCP 18744. Danach wird per GitHub Device Login ein read-only Deploy Key in dein bestehendes privates Repository eingetragen. Der Login erfordert deine Bestätigung im Browser. Weder das GitHub-Token noch private SSH-Schlüssel werden im Repository gespeichert.

## Browser
\`http://DEINE-UNRAID-IP:18744\`
Benutzer: lumacut
Passwort: /mnt/user/appdata/lumacut-builder/.env (Zeile BUILDER_PASSWORD)
Zuerst "Projekt-Tests" starten. Danach Ergebnis, Git-Commit, Log und Archiv ansehen.

## Was beim Bauen passiert
1. Unraid-Builder klont main aus GitHub mit rein lesendem SSH-Key.
2. Es laufen ausschließlich fest definierte Buildziele.
3. Jeder Job erstellt Manifest + Buildlog + ZIP; reale Firmware-Builds werden als UNVERIFIED markiert.
4. Kein Flashzugriff; kein Container-Docker-Socket und keine Serial-USB-Geräte.
5. Auf dem PC kann LightBurn unabhängig vom Unraid-Server über USB weiter verwendet werden.

## Häufige Probleme
Docker fehlt: Unraid Docker aktivieren.
SSH publickey denied: GitHub Deploy Key und Mounts /mnt/user/appdata/lumacut-builder/secrets prüfen.
Passwort verloren: Unraid .env auf dem eigenen NAS lesen, nicht in Chats posten.
Builder aktualisieren: neues GitHub-Quellpaket herunterladen, erneut setup/unraid-install.sh ausführen; Daten/Keys bleiben bestehen.
Containerstatus: \`docker logs --tail 80 lumacut-builder\`

Achtung: Noch keine flashfertige SKR-MZ-/ESP32-Firmware im Repo. Tests sind der einzige freigegebene erfolgreiche Build-Schritt.
