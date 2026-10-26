# Changelog

Details und Begründungen stehen in den jeweiligen Commit-Messages.

## 2026-10-26

- Pi-Web-UI: Nullpunkt X0/Y0 oben rechts (Bett gespiegelt, Jog/Tastatur angepasst), Materialauswahl über `GET /api/materials` mit Abgleich gegen G-Code, Phasenanzeige für Ein-Klick-Aufträge, Fallback für ältere Pis. Siehe docs/PI_WEB_UI_REDESIGN.md §10.

**Pi-Weboberfläche neu gestaltet:** Sticky-Statusleiste (verbunden, referenziert, SKR, Steuerung, Laser, Job-Fortschritt) mit immer erreichbarem Not-Aus, Bewegung links, Bettansicht mittig, Aufträge rechts, Einrichtung in Tabs; Studio-Dark-Theme, große Touch-Ziele, responsiv. Neu in der UI: Rahmen fahren, Warteschlange, Auftrag löschen, Veraltet-Banner. API unverändert. Details: `docs/PI_WEB_UI_REDESIGN.md`.

## 2026-10-25

**Aufräumen:** grblHAL-Firmware, ESP32-HMI (Waveshare), Unraid-Build-Lab, alter GRBL-Pi-Dienst, GRBL-Exporte in Studio, GRBL-LightBurn-Profil und die veraltete Doku entfernt. Neue Doku: README, `docs/MASCHINE.md`, `PI_BETRIEB.md`, `FIRMWARE.md`, `ENTWICKLUNG.md`. `install.sh` installiert jetzt den Marlin-Dienst.

**SKR-Firmware über den Pi flashen:** Marlin-Binärübertragung auf die SD-Karte im SKR, Neustart mit `M997`, Prüfung des Build-Zeitstempels. Am echten SKR in etwa 12 s getestet. Dazu „Notstopp quittieren“ nach einem SKR-Reset.

**LightBurn:** `G1` ohne S nach einer Leerfahrt löste M112 aus. Der Pi setzt jetzt den letzten S-Wert ein (Marlin setzt die Leistung bei G0 auf 0).

**Abtasten (G30):** Marlins „Probing Failed“ bei Kontakt über 5 mm wird als echter Kontakt erkannt (M114 + M119 geprüft). `M851 X0 Y0 Z0` gleicht alte EEPROM-Werte aus. Nur die `Bed`-Zeile gilt als Messwert.

**Schnittqualität:** Kein `M400` mehr vor jedem Laser-Segment (der Kopf stoppte an jedem Knoten). Ein `M3 I` pro Auftrag in Studio. 800 ms Wartezeit, nachdem die Laserversorgung eingeschaltet wurde.

**Ablauf:** Ein-Klick (Homing → Abtasten → Fokus → Auftrag → Park), G30-Knopf, kontrollierter Abbruch statt M112, Safezone-Prüfung schon beim Upload.

**Studio:** Reiter Maschine mit echter Steuerung über die Pi-API.

**Reparatur:** `transport.py` war durch frühere Commits beschädigt (`safe_home()` fehlte, Homing ging nicht). Wiederhergestellt.

**Firmware:** Marlin 2.1.2.9 mit `BINARY_FILE_TRANSFER`. Kontaktgrenze für G30 auf 16 mm, Z-Geschwindigkeiten ×1,8.
