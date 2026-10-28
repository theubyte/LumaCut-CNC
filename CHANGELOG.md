# Changelog

Details und Begründungen stehen in den jeweiligen Commit-Messages.

## 2026-10-28

- **Pi-Weboberfläche neu:** gleiches Design wie die Android-App (hell/dunkel), Seiten Steuerung, Aufträge, Material, Kamera, Einstellungen und System. Arbeitsfläche zoom- und antippbar (hinfahren, abtasten, Ursprung setzen) mit Scanbild der App; Aufträge mit Vorschaubildern, Dauer und Platzierung; Materialtabelle mit Import/Export; Kamera live mit Bildeinstellungen; Befehlsliste (Strg+K) und Tastenkürzel. Das gewählte Material gilt jetzt auch aus dem Browser für alle Geräte.
- **Pi:** Gerätename (auch in der Lasersuche der App), Abluft automatisch mit Nachlauf, Marlin-Abfragen `op=report` (M503 u. a.), Sicherung aller Einstellungen (`GET /api/backup`); `/api/settings` speichert jetzt auch einzelne Gruppen.
- **Kalibrierlauf auf 3-mm-MDF:** Fokus-Test (Parabel über alle Linien), Bewegungs- und Schwing-Auswertung (robuster Linienabstand, Marken von einer Seite angefahren), Laserpunkt-Finder (weißer Kern im großen blauen Hof) nach echtem Lauf überarbeitet.
- **Scan gleichmäßig hell:** Das Licht auf dem Bett ändert sich mit der Kopfposition (Blendung mal links, mal rechts im Bild); der fertige Scan wird jetzt im Hintergrund ausgeglichen (`Scan.level`), Markierungen behalten ihren Kontrast.
- **Laser-Adresse als Name oder URL:** Statt nur der IP gehen auch `lumacut.local`, `192.168.2.89:9000`, `http://lumacut.fritz.box` oder `https://…/pfad`. Ohne `http://` gilt Port 8080; unverschlüsseltes http nur im Heimnetz, im Internet nur https.

## 2026-10-27

- **Abtastpunkte antippen:** Im Arbeitsplatz-Scan (Modus „Abtastpunkte“) antippen, wo Material liegt; Abtasten und der automatische Auftrag tasten nur dort (`probe_points` im Arbeitsstand).
- **Neue Kalibrierungen:** Schwing-Test (Nachschwingen nach Ecken, Frequenz für Input Shaping), Umkehrspiel, Graustufen-Kurve für Fotos (`toneCurve` je Ebene), 3D-Höhe ohne Berühren mit dem Laserpunkt (Leistungstest, Kalibrierung, Messen an den Abtastpunkten) und Unterstützung für einen roten Mess-Linienlaser an einem Pi-GPIO (`op=line_laser`, 3D-Scan).
- Pi: Aufträge können während einer Laserlinie Kamerabilder aufnehmen (`; LUMACUT-CAPTURE`, `/api/camera/captures`).
- **Pi als Zentrale:** Gewähltes Material, markierte Bereiche, Höhenmesh, App-Einstellungen, das offene Projekt (alle Platten) und das Scanbild liegen auf dem Pi (`/api/workspace…`, Revisionen in `status.sync`). Alle Geräte haben denselben Stand; ändern zwei Geräte gleichzeitig das Projekt, fragt die App.
- **Fahrhöhe aus der Materialstärke:** Materialstärke + 20 mm (mind. Rückzug, max. Z 80) für Fahren, Abtasten, Parken, nach dem Referenzieren und lange Leerfahrten im Auftrag. Material höchstens 60 mm. Aufträge starten nur mit gewähltem Material; weicht die abgetastete Oberfläche mehr als 2 mm von der Stärke ab, bricht der Auftrag vor dem Lasern ab. Vor dem Referenzieren hebt der Pi an (unbekanntes Z: ab der gemerkten letzten Höhe, sonst nach Bestätigung). Kamera-Schärfesuche ab 5 mm über dem Material.
- **Referenzprüfung:** Auf X0/Y0 müssen die X/Y-Endschalter gedrückt sein, sonst gilt die Maschine als nicht referenziert. Motoren halten im Leerlauf (`M84 S0`).
- Kalibrieren (Android): Kamera-Licht, Taster-Versatz, Fokus-Test, Gravur-Test, Bewegung (Tempo/Beschleunigung ohne Schrittverlust), geführter Schnitt-Test; Teilscan (Markierung/Motiv/alles); neues Laser-Panel mit Ebenen-Fenster.
- **Z nie über 80 mm** (darüber läuft der Kopf aus der Z-Linearschiene): Firmware `Z_MAX_POS 80` (SKR neu flashen), Pi-Z-Sperre für jede Z-Fahrt (Auftrag, Jog, LightBurn), Parken, Abtast-Rückzüge und `travels.z`; App: Kamera höchstens Z 80 (Schärfesuche, Scan), `scan_z` ≤ 80.
- Idee für Fahrhöhe nach Materialstärke, Kollisionsschutz und Kamera-3D-Vorprüfung: `docs/IDEE_HOEHE_KOLLISION_KAMERA_3D.md`.

## 2026-10-26

- Android: Laserleistung für das Kamera-Punktraster im Kalibrier-Dialog einstellbar, 20–60 % in 5-%-Schritten (Standard 20 %, wird gemerkt).
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
