# Unraid Architektur

Docker-Image python:3.12-slim-bookworm mit Flask, Git-SSH und PlatformIO. Quellen im GitHub-Repository, Runtime in /mnt/user/appdata/lumacut-builder:
- source/ – lokale Installationsdateien, niemals für Build als Quelle verwendet
- .env – Webpasswort, Repository-Konfiguration (nicht in GitHub)
- gh/ – GitHub CLI Device-Login, nur Root
- secrets/ – read-only Deploy Key und bekannte GitHub SSH Hostkeys
- data/artifacts/<jobid>/ – Manifest, Buildlog, ZIP und ggf. UNVERIFIED-Binaries
- data/jobs/ – nur während Builds

Aufruf:
\`bash setup/INSTALL-ALL.sh\`
Browser: TCP 18744, Benutzer lumacut, Passwort in .env.
Containerstart mit --restart unless-stopped; 3 GB RAM / 3 CPUs, non-root Container-User 10001, keine Privileged-Rechte, keine Hostgeräte oder Docker-Socket.

Der GitHub-Setup-Assistent nutzt GitHub CLI auf Unraid in einem kurzlebigen Container und verknüpft nur einen Lese-Deploy-Key mit dem privaten Repository. Die Builder-Weboberfläche ist nicht zum beliebigen Git-Push geeignet.
Alles per Commit versioniert. Änderung auf main → nächster Browser-Build lädt die neueste Revision.

Bei defekter GitHub-Verbindung zuerst Schlüssel/known_hosts und GitHub-Zugriff prüfen, keine Hostkey-Prüfung deaktivieren.
Für öffentliche Internetzugriffe ist Basic Auth ohne TLS NICHT geeignet.