# Changelog

Details und Begründungen stehen in den jeweiligen Commit-Messages.

## 2026-10-31

- **Android-App auf die neue Arbeitsfläche:** Die App liest Fahrwege und Park-Ecke vom Pi (`config.travels`, `park_corner_mm`) und zeigt die ganze Fläche (370 × 360) mit der schraffierten Park-Ecke oben rechts. Umrechnung jetzt `Maschine X = Fahrweg − x`, `Maschine Y = y` (vorher `390 − x` / `30 + y`); der Auftragsbau lehnt Elemente in der Park-Ecke ab. Alte Projekte und Scans liegen dadurch versetzt – neu ausrichten bzw. neu scannen. Der Pi rechnet angetippte Abtastpunkte gleich um.

- **Arbeitsfläche Kopf v6:** Fahrwege 370 × 360 mm (gemessen, Pi-Einstellung `travel_x_mm`/`travel_y_mm`). Die 30-mm-L-Zone ist weg; nur die Park-Ecke X0–78 / Y0–35 (Kopf + 1 cm) bleibt frei, überall sonst wird gelasert. Pi-Prüfungen (Schnitt, Platzierung, Ursprung, Materialtest) und Weboberfläche angepasst; Status `park_corner_mm` statt `safe_zone_xy_mm`. Die Android-App folgt.

- **Notbetrieb mit dem Atomstack-Board (Grbl):** Das SKR ist defekt. Der Pi steuert jetzt auch das Original-Board der A5 Pro (ESP32, Grbl ab Werk) über eine Brücke (`grbl_bridge.py`), die sich wie LumaCut-Marlin verhält: Laser, Fahren, Referenzieren, Not-Aus gehen weiter über LumaCut (App, Web). Ohne Z-Treiber ist Z fest von Hand eingestellt; Z-Fahrten und Abtasten werden nur gespielt. Ist das SKR wieder dran, nimmt der Pi es zuerst.
- **Grbl-Brücke robuster:** Vorschub wird auf das Board-Maximum (`$110/$111`, 6000 mm/min) gedeckelt – darüber senkte der dynamische Lasermodus die Leistung unter die Zündgrenze. Ein stummer USB-Port (CH340 nach „urb stopped“) wird nach 7 s neu geöffnet, verlorene Bestätigungen werden nachgeholt, sobald Grbl Idle meldet.
- **Kreise am Atomstack-Board ruckelten:** Die Brücke hielt jedes „ok“ von Grbl bis zu 50 ms zurück (Lesen wartete auf 256 Bytes), und 4 Zeilen Fenster reichten für kurze Kreissegmente nicht (0,4 mm bei 4400 mm/min ≈ 180 Zeilen/s). Grbls Planer lief leer, der Kopf fuhr stotternd und zeichnete Wellen. Jetzt liest die Brücke sofort, was ankommt, und der Pi streamt durch sie mit 16 Zeilen Fenster.
- **Rahmen mit glimmendem Laser:** Neue Pi-Einstellung `frame_power_pct` (0..1 %, 0 = aus, auf der Maschine 0,5 %). Die Fahrt zum Rahmen bleibt dunkel, jede Kante läuft mit dieser Leistung und mindestens 1200 mm/min, ohne Fokusfahrt.
- **Kreise am Atomstack-Board runder:** Die App schreibt Kreise in Stücken bis hinunter auf 0,175 mm (bei 4400 mm/min ~420 Zeilen/s) – mehr, als die USB-Leitung zum Board trägt; der Kreis lief eckig. Der Pi fasst am Board jetzt Folgen kurzer G1-Züge gleicher Leistung zusammen, solange kein Punkt mehr als 0,01 mm abweicht (275 → ~80 Züge).
- **Laser am Atomstack-Board:** Über den „+12V“-Ausgang des Boards versorgt, feuerte der Laser nur sporadisch und das Board fiel vom USB. Mit der LaserTree-Adapterplatine direkt am 24-V-Netzteil (Board liefert nur TTL) brennen alle Stufen 30–100 %.

## 2026-10-30

- **Kopf v6: Z mit 80 Schritten/mm.** Die Zahnstange (GT2-Riemen, Ritzel GT2 20 Z = 40 mm je Umdrehung) braucht 80 statt 380 Schritte/mm der alten Gewindespindel. Firmware-Vorgabe geändert; der Pi sendet zusätzlich bei jedem Verbinden `M92 Z80`, weil ein alter EEPROM-Wert sonst gilt – Z stimmt damit schon ohne Flashen.
- **Doku:** `docs/STAND.md` ist die vollständige Übergabe (Projekt, Zugang, Regeln, Chronik, laufende v6-Umstellung, Fahrplan); `CLAUDE.md` verweist neue Chats darauf.

## 2026-10-29

- **Projekte auf dem Pi speichern und öffnen:** Editor → Mehr → „Auf dem Pi speichern …“ legt das Projekt unter einem Namen auf dem Pi ab (gleicher Name ersetzt nach Hinweis), „Vom Pi öffnen …“ zeigt die Liste aller Geräte mit Datum, Gerät und Elementzahl, Löschen mit Rückfrage. Neue Pi-Ablage `/api/projects` (Merkmal `projects`); Speichern/Öffnen als Datei auf dem Gerät bleibt.
- **Regler „präziser ↔ schneller“ und „heller ↔ dunkler“ (App, Ebenen-Fenster):** Tempo und Leistung ändern sich zusammen. Der erste hält die Schwärze gleich (gleiche Energie je mm), der zweite folgt der Schwärze-Kurve aus dem Materialtest mit Kamera. Die Leistung geht nie unter 8 %: darunter zündet der Laser nicht sicher (Einladungskarte mit 6 % war unlesbar). Der Pi speichert die Kurve je Material (`tone_curve`), der Materialtest sucht nicht mehr unter 8 %.
- **Sperrholz Mittel/Hell korrigiert:** 8 % / 4000 und 8 % / 5300 mm/min statt 6 % und 4,5 % bei 3000.
- **Bettkarte (Pi):** Der Taster tastet das leere Bett einmal an 6 × 6 Punkten ab (`op=bedmap`, Laser aus), der Pi speichert die Karte (`GET /api/bedmap`, Status `bed_map`). Danach meldet jedes Abtasten auch die Dicke über dem Bett (`workpiece_above_bed_mm`). Weboberfläche: Karte als Farbraster unter Einstellungen.
- **Materialtest mit Kamera (`op=matcal`):** Der Pi kalibriert ein Material selbst. Gravur Feld für Feld (lasern, fotografieren, Ton/Streifen/Rauchrand messen, nächste Leistung rechnen) bis Dunkel, Mittel und Hell; Schnitt auf hochgelegter Platte Durchgang für Durchgang, bis die Kamera das Loch offen sieht – gespeichert wird die Einstellung mit der wenigsten Energie. Ergebnisse landen als Materialien auf dem Pi. Karte in der Weboberfläche (Einstellungen) und in der App (Kalibrieren → Je Material → Automatisch mit Kamera).
- **Sperrholz kalibriert (4 mm, 10 W ohne Air Assist):** Gravur dunkel 12,8 % / 4500 mm/min; Schnitt hochgelegt 500 mm/min × 2. Flach auf der Opferplatte verkohlte die Rückseite (Messwerte in `docs/MATERIAL_KALIBRIERUNG.md`).
- **Kameralicht automatisch:** Jedes Kamerabild über den Pi (Live-Bild im Browser, Scans, Messungen) schaltet die LEDs mit der Helligkeit der Lichtkalibrierung ein und 8 s nach dem letzten Bild wieder zurück.
- **Abtasten unter Z0:** Das leere Bett liegt 0,7–1,2 mm unter Z0 (Z0 ist der Schaltpunkt beim Referenzieren). Kontakte bis −3 mm gelten jetzt als gültig; vorher verwarf der Pi jedes Antasten auf dem leeren Bett.

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
