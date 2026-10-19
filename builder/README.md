# LumaCut Browser-Builder

Docker / Python Flask / PlatformIO, nur privates LAN. Port 18744 außen, 8080 im Container. Alle Build-Jobs klonen git@github.com:theubyte/LumaCut-CNC.git (main). Read-only Deploy Key liegt im Unraid Appdata secrets-Ordner, nicht im Repository.

Targets:
- tests: Python-Unit-Tests + py_compile; nutzbar.
- stm32_project_unverified: prüft firmware/skr/platformio.ini und baut Profil lumacut_skr_mz_usb; aktuell absichtlich fehlende Firmwarequellen.
- esp32_hmi_unverified: prüft firmware/hmi/platformio.ini und baut Profil lumacut_waveshare_s3; aktuell absichtlich fehlende Firmwarequellen.

Bei jedem Job: Git-SHA, UTC, Log, Manifest, Status, SHA256 aller BIN/ELF, ZIP. Keine Konsole zum Ausführen beliebiger Befehle, keine Gerätefreigabe, keine Docker-Socket-Freigabe. Das Flashen ist ein manueller, gesondert freizugebender Vorgang.

Passwort per HTTP Basic Auth. Nur im LAN/VPN betreiben; für externen Zugriff TLS-Reverse-Proxy ergänzen.