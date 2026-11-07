# LumaCut: aktueller Stand und Übergabe

**Diese Datei ist der eine Ort für „was gilt gerade“.** Wer neu dazukommt –
ein Mensch oder ein neuer Claude-Chat – liest zuerst diese Datei. Sie
erklärt, was das Projekt ist, wo alles liegt, welche Regeln gelten, was
schon passiert ist, was gerade läuft und was als Nächstes kommt.

Stand: **31.10.2026**. Wird mit jeder Änderung im selben Commit nachgezogen
(siehe [Pflege dieser Datei](#14-pflege-dieser-datei)).

Inhalt:
1. [Das Projekt in Kürze](#1-das-projekt-in-kürze)
2. [Wo liegt was](#2-wo-liegt-was)
3. [Zugang und Arbeitsweise](#3-zugang-und-arbeitsweise)
4. [Verbindliche Sicherheitsregeln](#4-verbindliche-sicherheitsregeln)
5. [Grundsätze und Entscheidungen](#5-grundsätze-und-entscheidungen)
6. [Maschine heute](#6-maschine-heute)
7. [Software heute](#7-software-heute)
8. [Chronik: was bisher geschah](#8-chronik-was-bisher-geschah)
9. [Gerade in Arbeit: Umstellung auf Kopf v6](#9-gerade-in-arbeit-umstellung-auf-kopf-v6)
10. [Danach: Fahrplan](#10-danach-fahrplan)
11. [Offene Fragen und Messungen](#11-offene-fragen-und-messungen)
12. [Ideen (noch nicht geplant)](#12-ideen-noch-nicht-geplant)
13. [Nebenprojekte im Ordner](#13-nebenprojekte-im-ordner)
14. [Pflege dieser Datei](#14-pflege-dieser-datei)

---

## 1. Das Projekt in Kürze

LumaCut ist ein selbst gebauter Diodenlaser (Gravieren und Schneiden) mit
**eigener Steuerung und eigener Software**. Ziel: LightBurn vollständig
ablösen; der Besitzer bedient alles vom Tablet aus.

```
 Android-App (Tablet, Hauptgerät)   Browser (Web-Oberfläche)   [Windows-Studio: ruht]
                 │  HTTP :8080 (Pi-API)          │
                 ▼                               ▼
 ┌──────────────────────── Raspberry Pi 400 ─────────────────────────┐
 │ „Gehirn“: speichert ALLES (Einstellungen, Materialien, Projekte,  │
 │ Kalibrierungen, Scans) und setzt alle Sicherheitsgrenzen durch.   │
 │ Homing, Abtasten, Fokus, Parken, Auftrag streamen, Kamera.        │
 └──────────────────────────────┬────────────────────────────────────┘
                                │ USB
                                ▼
            BTT SKR Mini MZ V1.0 · Marlin 2.1.2.9 (Motoren, Laser-PWM)
```

- Das Tablet entwirft (Editor), erzeugt den G-Code und schickt ihn an den Pi.
- Der Pi führt aus und passt auf. Kein Gerät darf an ihm vorbei.
- Die Kopfkamera hängt per USB am Pi.

## 2. Wo liegt was

| Was | Ort |
|---|---|
| **Haupt-Repository** (hier arbeiten) | `A:\LumaCut\LumaCut-CNC-android` → GitHub `theubyte/LumaCut-CNC`, Zweig `main` |
| Zweiter, älterer Klon desselben Repos | `A:\LumaCut\LumaCut-CNC` (vor Benutzung `git pull`) |
| Pi-Dienst (Python/Flask) | `pi400/marlin/` (`web.py` API, `transport.py` Maschinenlogik + Sicherheit, `index.html` Web-Oberfläche) |
| Android-App | `android/core` (reines Kotlin: G-Code, Geometrie, Pi-Client, lokal testbar), `android/app` (Oberfläche) |
| Firmware | `firmware/marlin/build.py` (baut Marlin reproduzierbar aus dem Beispiel-Config + Patches) |
| Tests Pi | `tests/` (Python unittest/pytest) |
| Windows-Studio (ruht) | `software/lumacut-studio-native` |
| Doku | `docs/` – Einstieg ist diese Datei |
| Auf dem Pi | Programm `/opt/lumacut` (Git-Checkout), Dienst `lumacut-marlin`, Daten `/var/lib/lumacut/marlin/` (`config.json`, Materialien, Projekte, Bettkarte …) |
| Kopf-Konstruktion (CAD) | `A:\mfw\zmount\v6\build_kopf_v6.py` (CadQuery, erzeugt STEP/STL/Vorschaubilder), auch auf dem NAS unter `Export\kopf_v6`; ältere Stände `v5`, Idee des Besitzers `A:\mfw\zmount\in\new_laser_head.step`. **Entwurf v7** (Schneckenlift, nicht gebaut): `A:\mfw\zmount\v7\build_kopf_v7.py`, Anleitung `LIESMICH.md` dort |
| Firmware-Build-Ablage | `A:\mfw\pio`, `A:\mfw\dist`, `A:\mfw\up` |
| Signatur-Schlüssel Android | `A:\LumaCut\android-signing` – **Passwort nie lesen oder ausgeben** |

Nicht ins Repo: die `.xs`-Datei des Besitzers; das Bild `61h3r1EOoeL._SL1500_.jpg` im Repo-Wurzelordner ignorieren.

## 3. Zugang und Arbeitsweise

- **Pi:** SSH `lumacut@192.168.2.89` mit Schlüssel `~/.ssh/lumacut_pi`.
  Web/API: `http://192.168.2.89:8080`. `/opt/lumacut` gehört `lumacut`
  (git ohne sudo). sudo nur für `sudo -n systemctl restart lumacut-marlin.service`
  – **nie während ein Auftrag läuft** (vorher `GET /api/status` prüfen:
  `activity` idle, `busy` false). Seit 31.10. Freigabe des Besitzers: ist
  nichts aktiv, ohne Nachfrage neu starten. Fahr- und Laseraufträge brauchen
  weiter jedes Mal das Go (§4).
- **GitHub:** Deploy-Key `GIT_SSH_COMMAND="ssh -i ~/.ssh/lumacut_github"`.
  Kein `gh`-CLI; CI-Status per GitHub-API mit `curl`.
- **Commits:** `git -c user.name=TheUByte -c user.email=83143005+theubyte@users.noreply.github.com commit …`,
  Nachricht auf Deutsch mit Was und Warum, endet mit
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Alles auf `main`.
- **Mehrere Sitzungen arbeiten parallel** auf `main` (andere Claude-Chats,
  früher Grok). Deshalb **vor jeder Änderung `git fetch` + `pull`**, fremde
  Änderungen nicht zurückdrehen.
- **Tests:** Pi `python3 -m pytest tests` (unter Windows `PYTHONUTF8=1`);
  Android-Kern `gradle :core:test` im Ordner `android`. Vorbekannte
  Windows-Fehlschläge: `camera_calibration` Speicherort (2×), `marlin_gateway` (2×).
- **CI (GitHub Actions):** Pi-Tests, Android-APK + Screenshots, Firmware-Build.
- **Pi aktualisieren:** auf dem Pi `cd /opt/lumacut && git pull`, dann
  Dienst neu starten (nur wenn nichts läuft). Alternativ `sudo bash /opt/lumacut/pi400/update.sh`.
- **App verteilen:** CI baut die signierte APK als GitHub-Release, der Pi
  holt sie, die App bietet „Update 1.0.N“ an (Einstellungen → App-Update).
- **Firmware flashen:** über den Pi (`/api/firmware`), **nur wenn der Besitzer daneben steht**.
- Geheimnisse (GitHub-Secrets, Passwörter) trägt **nur der Besitzer** ein.

## 4. Verbindliche Sicherheitsregeln

Diese Regeln sind aus echten Vorfällen entstanden und gelten immer:

1. **Vor JEDEM Laser- oder Fahrauftrag ein ausdrückliches Go** einholen:
   „Hände raus, Deckel zu, Brille – starten?“ Eine Antwort auf eine andere
   Frage ist kein Go. (29.10.: Hand unter dem Kopf während eines S1-Laufs.)
2. **Nie auf ungetestetem Material lasern**, auch kein „Glimmen“. Erst ein
   Leistungstest auf genau diesem Material an einer vom Besitzer gewählten
   Stelle. (29.10.: S3-Punktlinien haben ein schwarzes Kunststoffgehäuse angeschmolzen.)
3. **Vor jedem Abtasten oder Lasern auf einem Objekt neu scannen** – der
   Besitzer kann es zwischendurch verschoben haben. (29.10.: Linien landeten neben dem Objekt.)
4. Keine Maschinenbewegung und kein Flashen ohne den Besitzer vor Ort.
5. Kein Dienst-Neustart während eines Auftrags.
6. Der Laser zündet unter etwa 6 % nicht sicher; **Untergrenze 8 %**.
7. Keine Passwörter/Schlüssel eingeben oder ins Repo schreiben.
8. **Kopf nie schnell von Hand bewegen oder fallen lassen** (an oder aus):
   ein gedrehter Schrittmotor speist Spannung auf die Motorversorgung zurück,
   über 29 V sterben TMC2209-Treiber. Der Z-Kopf v6 dreht beim Fallen den
   Motor über die Zahnstange schnell. (30./31.10.: SKR defekt, Extruder-Treiber
   warm nur an USB – Ursache Rückspannung oder Kühlkörper-Kurzschluss.)

## 5. Grundsätze und Entscheidungen

- **Der Pi ist die Zentrale.** Jede Einstellung, Kalibrierung, jedes
  Material, Projekt und jede Grenze liegt auf dem Pi; Apps lesen und
  synchronisieren nur. Grenzen (Z ≤ 80 mm, Material ≤ 60 mm, Sperrzonen)
  setzt der Pi selbst durch.
- **Android zuerst.** Die Android-App ist die Referenz; das Windows-Studio
  ruht und wird später nach ihrem Vorbild neu gebaut.
- **Web-Oberfläche des Pi** (`index.html`) pflegt seit 28.10. Claude (vorher Grok).
- **Kalibrieren adaptiv:** Feld für Feld lasern → fotografieren → messen →
  nächsten Wert rechnen; platzsparend. Schnitt-Tests auf hochgelegter Platte,
  bis die Kamera das Loch offen sieht.
- **Kopf nur aus vorhandenen Teilen** (Anet-A8-Bausatz, GT2-Riemen, NEMA17 …), nichts kaufen.
- Bedienung so einfach wie möglich: Material wählen → Motiv → Starten.

## 6. Maschine heute

**Hardware**
- Rahmen Atomstack A5 Pro (X-Träger 2020 × 525 mm, X-Motor fährt auf dem
  Wagen mit, Y ein Motor + Synchronwelle).
- Laser LaserTree LT-80W-AA-PRO (10 W optisch), Fokus 7 mm unter der Düse.
- SKR Mini MZ V1.0 (TMC2209), Marlin 2.1.2.9; Belegung in [MASCHINE.md](MASCHINE.md). **Seit 31.10. defekt.**
- **Notbetrieb seit 31.10.:** Original-Atomstack-Board „Laser 32-A5 V1.0“
  (ESP32, Grbl ab Werk, USB-Chip CH340) fährt X, Y und den Laser. Es hat
  keinen Z-Treiber: Z-Motor abgesteckt, **Kopf mit Klebeband auf
  Fokushöhe fixiert** (Fokus von Hand je Material). Der Pi spricht über
  `pi400/marlin/grbl_bridge.py` mit ihm (siehe §7). Abtasten und Z-Fahrten
  sind in dieser Zeit nur gespielt – Material muss so dick sein wie beim
  Fixieren des Kopfes.
- Pi 400 mit USB-Kopfkamera, LED-Licht (dimmbar), Abluft.
- **Kopf v6 ist seit 30.10. eingebaut:** Z über Zahnstange (GT2-Riemen auf
  gedruckter Leiste, Ritzel GT2 20 Z) statt Gewindespindel; der ganze Kopf
  (Laser, Z-Motor, Kamera, Taster, GY-521) fährt auf einer MGN9H-Schiene in Z.
  Reibbremse (PETG-Blattfeder) hält ihn ohne Strom – **greift, seit die
  Vorspannschraube angezogen ist**. Bewegte Masse ca. 0,9 kg.
- GY-521 (Beschleunigungssensor) sitzt im Kopf, **nicht angeschlossen**.

**Koordinaten** (Details [ZUSAMMENARBEIT_CLAUDE_GROK.md](ZUSAMMENARBEIT_CLAUDE_GROK.md) §2)
- Maschine 0/0 = Endschalter-Ecke, von der Tür aus **hinten rechts**. Z0 =
  Taster schaltet am Referenzpunkt; positives Z = weg vom Material.
- App-Arbeitsfläche (seit 31.10.): die ganze Maschine, Nullpunkt oben links
  wie von der Tür gesehen; `Maschine X = Fahrweg X − x`, `Maschine Y = y`
  (vorher `390 − x` / `y + 30`). Fahrwege und Park-Ecke liest die App vom Pi.
- **Seit 31.10. (Pi):** Fahrwege **X 370 / Y 360** (Besitzer mit den
  Steuerkreuzen bis an die Enden gefahren, Pi-Einstellung `travel_x_mm`/
  `travel_y_mm`). Statt der 30-mm-L-Zone gilt nur noch die **Park-Ecke
  X0–78 / Y0–35** (Kopf v6 laut `build_kopf_v6.py`: 67 mm in +X, 24 mm in +Y
  vom Strahl, +10 mm); überall sonst darf gelasert werden. Weboberfläche
  zeigt das so, die Android-App ab 31.10. auch (Park-Ecke schraffiert oben
  rechts). Alte Projekte und Scans liegen dadurch um 20 mm in X / 30 mm in Y
  versetzt: neu ausrichten bzw. neu scannen. Bettkarte und Abtastraster
  behalten vorerst den 30-mm-Rand.

**Kalibrier- und Messwerte (noch für den alten Kopf!)**
- Tasterversatz X −23 / Y +15 mm, Schalter→Laserspitze 1,5 mm, Fokus 7 mm.
- Bettkarte (29.10.): leeres Bett 0,7–1,8 mm unter Z0, Stufe ~0,7 mm links zwischen Y96 und Y152.
- Kopf schwingt bei ~12,5 Hz in Y (wellige Linien); Input Shaping für Y ist
  einkompiliert, aber aus (`M593 Y F0`).
- Firmware Z: 380 Schritte/mm (Spindel) – **für v6 falsch, muss 80 werden**.

**Materialien (auf dem Pi)**
- Sperrholz 4 mm: Gravur dunkel 12,8 % / 4500 mm/min, Mittel 8 % / 4000,
  Hell 8 % / 5300; Schnitt hochgelegt 500 mm/min × 2.

## 7. Software heute

- **Pi-Dienst:** `main` bis `c3645b7` auf dem Pi (Code-Stand `6cc2826`),
  Dienst neu gestartet am 30.10. Merkmale u. a.: Projektablage
  (`/api/projects`), Regler für gleiche Schwärze (Tonkurve je Material),
  Materialtest mit Kamera (`op=matcal`), Bettkarte (`op=bedmap`),
  Arbeitsstand-Sync (`/api/workspace…`), App-Update-Verteilung,
  Firmware-Flash. Vollständig: [PI_API_REFERENZ.md](PI_API_REFERENZ.md).
- **Android-App 1.0.52** (auf dem Pi bereit seit 31.10.; Arbeitsfläche 370 × 360 mit Park-Ecke, Werte vom Pi; realistische Zeitschätzung): Editor mit Ebenen,
  Text/Bild/SVG/xTool-Import, Regler „präziser ↔ schneller“ / „heller ↔
  dunkler“, Projekte auf dem Pi speichern/öffnen, Kalibrier-Assistenten,
  Arbeitsplatz-Scan mit der Kopfkamera. Am Tablet noch nicht ausprobiert:
  der Projekte-Dialog.
- **Web-Oberfläche** (Browser auf Port 8080): gleiches Design wie die App.
- **Grbl-Brücke (Notbetrieb, 31.10.):** Findet der Pi das SKR nicht am
  eingestellten Port, nimmt er das Atomstack-Board (CH340, `/dev/ttyUSB*`)
  und übersetzt Marlin → Grbl: `M3 I` → `M4 S0`, S 0..255 → 0..`$30`,
  `G28 X Y` → `$H` + `G10 L20 P1 X0 Y0`, `M400/M114/M119` über `?`,
  `M112` → `!` + Strg-X. Achsen, die in Grbl nach + referenzieren (`$23`),
  werden gespiegelt. Z: nur gemerkt; `G30` meldet Bettkarte-Mittel +
  Materialstärke. Tests: `tests/test_grbl_bridge.py`. Wieder SKR: einfach
  wieder anstecken, der Pi nimmt es zuerst.
  Board-Werte (`$$`, 31.10.): Grbl 1.1h (Build 2022050902), `$32=1`
  Lasermodus, `$30=1000`, `$100/$101=80`, `$110/$111=6000`, `$120/$121=1000`,
  `$22=1` Homing, `$23=3` (X/Y nach −, also nicht gespiegelt), `$21=1`
  Hardlimits, `$20=0`, `$130/$131=395/365`, `$27=1`. Es startet im Zustand
  `Door` und nimmt erst nach `~` Befehle an – die Brücke setzt fort, wenn der
  Türeingang geschlossen ist. DTR/RTS müssen aus bleiben (ESP32-Reset).
  Vorschub wird auf `$110/$111` gedeckelt (sonst senkt M4 die Leistung),
  ein stummer USB-Port wird nach 7 s neu geöffnet. Damit kurze Segmente
  (Kreise) flüssig laufen, liest die Brücke jedes „ok“ sofort und der Pi
  streamt durch sie mit 16 Zeilen / 600 Bytes Fenster (SKR: 4 / 200).
  Zusätzlich fasst der Pi am Board winzige G1-Stücke gleicher Leistung
  zusammen (`merge_short_moves`, höchstens 0,01 mm Abweichung, max. 3 mm):
  ein Kreis aus 275 × 0,175 mm wird zu ~80 Zügen – mehr als ~200 Zeilen/s
  trägt die 115200-Baud-Leitung nicht, die Kreise wurden sonst eckig.
- **Raster-Durchsatz (31.10.):** Engpass bei Graustufen war die USB-Strecke
  (Grbl-Puffer 128 Byte laut `$I` `[OPT:VZ,15,128]`, Zeilen ~38 Byte → 3 in
  Flug, ~80 Zeilen/s). Die Brücke sendet kompakt/modal (~13 Byte, `self.modal`,
  gelöscht bei $-Befehlen, Alarm, Not-Aus, M5, G90/G91), Puffer 127 Byte;
  `merge_power_steps` fasst Pixel gleicher Zeile mit ±3 S zusammen (Vorschub
  modal, wie ihn die Fokus-Kompensation schreibt). **Gemessen 31.10.: Max-geb
  31 min** (vorher Hochrechnung > 80 min, App schätzte 2 h 4 min). Pi-Software
  schafft ~1600 Zeilen/s (gemessen auf dem Pi), ist also kein Engpass.
  Offen/Idee: Board hat „Direct SD“ (`[ESP800]`) – Auftrag von SD statt Streamen.
- **Rahmen mit Glimmen (31.10.):** Pi-Einstellung `frame_power_pct` (0..1 %),
  auf Wunsch des Besitzers 0,5 %: die Rahmenkanten laufen mit sichtbarem
  Laserpunkt (≥ 1200 mm/min), die Anfahrt bleibt dunkel. `M3 I` ohne
  abgetastete Oberfläche ist nur dem Besitzer `frame` erlaubt. Auf dunklem
  Kunststoff vorher testen (S3 hat am 29.10. ein Gehäuse angeschmolzen).
  **Am 31.10. an der Maschine geprüft:** Verbinden, Referenzfahrt (sauber
  hinten rechts), Fahrt auf X100/Y100 (Richtung stimmt). **Laser:** am
  „+12V“-Ausgang des Boards (gibt 24 V durch) zündete er nur bei wenig
  Leistung oder gar nicht, das Board verlor dabei auch die USB-Verbindung.
  Lösung: **Laser über die LaserTree-Adapterplatine direkt am 24-V-Netzteil**,
  vom Board nur TTL (+ Signal, − Masse). Danach Leistungstest 30–100 % alle
  Stufen sauber (31.10., 11:03), USB ohne Fehler. **Testkreis Ø 20 mm in
  MDF 3 mm (300 mm/min, 100 %, 2×) durch und fällt raus (11:05).**
  12:35 erste App-Gravur abgebrochen: USB-Empfang tot („urb stopped“, Linux
  liest dann nichts mehr bis zum Neuöffnen) und F10199 > Board-Maximum 6000,
  wodurch der M4-Lasermodus die Leistung auf ~8 % senkte. Brücke deckelt F
  jetzt auf `$110/$111`, öffnet einen 7 s stummen Port neu und quittiert
  Zeilen, deren ok verloren ging, sobald Grbl Idle meldet. Die Brücke fragt verlorene
  Statusmeldungen dreimal nach und meldet ein getrenntes Board sofort.
- **Windows-Studio:** ruht.
- **LightBurn** geht übergangsweise noch über TCP 23.

## 8. Chronik: was bisher geschah

Ausführlich pro Tag im [CHANGELOG](../CHANGELOG.md); hier der rote Faden.

- **19.–23.10.:** Start mit grblHAL auf dem SKR und einem
  Waveshare-Touch-Display (ESP32) als Bedienteil, Build-Lab auf dem
  Unraid-NAS, LightBurn über WLAN. Hardware ehrlich erfasst (3 Motoren, ein
  Z-Schalter = auch Werkstücktaster).
- **24.10.:** Pi 400 als Steuerrechner, Licht/Abluft-Ausgänge, Fahrwege gemessen.
- **25.10.:** **Umstieg auf Marlin 2.1.2.9**; grblHAL, ESP32-Bedienteil,
  Build-Lab und alte Doku entfernt. Firmware-Flash über den Pi, Ein-Klick-
  Ablauf (Homing → Abtasten → Fokus → Auftrag → Parken), Safezone-Prüfung.
  `transport.py` war durch einen Commit beschädigt und wurde repariert.
- **26.10.:** Windows-Studio stark ausgebaut; Android-Kern (Import, Kontur,
  Raster, Formen); Motor-Melodien; Material-API.
- **27.10.:** Windows ruht, **Android ist Hauptgerät**. Pi wird Zentrale
  (Arbeitsstand, Projekt, Scan auf dem Pi), App-Update über den Pi, Z ≤ 80 mm,
  Referenz nur mit gedrückten X/Y-Schaltern, Kalibrier-Assistenten
  (Kamera-Licht, Taster, Fokus, Gravur, Bewegung, Schnitt).
- **28.10.:** Neues App-Design hell/dunkel, Pi-Web-Oberfläche neu,
  Screenshot-Tests, Input Shaping einkompiliert. Kopf v5/v6 konstruiert.
- **29.10.:** Bettkarte, Abtasten unter Z0, Kameralicht automatisch,
  Materialtest mit Kamera, Sperrholz kalibriert, Vorfälle mit geschmolzenem
  Gehäuse und Hand unter dem Kopf (→ Regeln §4). Einladungskarte „Smaragd“
  war unlesbar (6 % zündet nicht, Umrisslinien statt Füllung) → Regler für
  gleiche Schwärze (nie unter 8 %), Projekte auf dem Pi.
- **30.10.:** Karte neu aufgebaut (Füllung, größere Pixel), Probestreifen
  scharf, Karte gelasert. Pi-Dienst neu gestartet (Projekte aktiv). **Kopf v6
  eingebaut:** Taster zu hoch, Bremse nachgestellt. Plan für die Umstellung
  (§9) mit dem Besitzer abgestimmt. Diese Datei angelegt.
- **30./31.10.:** SKR Mini MZ defekt (Kühlkörper auf Pins, Achsen von Hand
  geschoben). Für ein Geschenk am 31.10. Notbetrieb mit dem
  Atomstack-Board über die neue Grbl-Brücke auf dem Pi, Z mit Klebeband fixiert.

## 9. Gerade in Arbeit: Umstellung auf Kopf v6

Reihenfolge; jeder Schritt erst, wenn der vorige an der Maschine passt.
Fahrten, Messungen und Flashen nur mit dem Besitzer daneben.

**Schritt 1 – Taster tiefer als die Düse**
Der Tasterknopf sitzt zu hoch; die Laserdüse berührt das Material zuerst.
Entscheidung: **gedruckter Hut auf den Knopf** (ca. 7 mm). Verworfen:
Sensorless-Antasten über den Z-Motor – drückt die Düse mit Motorkraft ins
Material, ist ungenauer (±0,3 statt ±0,05 mm), und der Knopf ist zugleich
der Z-Endschalter.
- [x] Bremse greift (Vorspannschraube angezogen)
- [x] Hut gedruckt und montiert (30.10.): Wenn der Knopf schaltet, passen
      2 mm unter die Düse; Schaltweg des Knopfs ca. 1 mm.
- [x] Pi (30.10.): `z_switch_tip_offset_mm` 1,5 → **2,0**, `focus_gap_mm`
      10,1 (alter Fokus-Test) → **7,0** (Herstellerwert, Fokus-Test verfeinert später).
- [ ] Taster-X/Y-Versatz steht noch auf dem alten Kopf (−27,4 / +13,0) – neu
      kalibrieren (Kalibrieren → Taster-Versatz), bis dahin Abtastpunkte ungenau.
- [x] Prüfen (kein genaues Messen nötig): Kopf auf eine glatte Platte
      absenken, bis der Knopf klickt – ein Blatt Papier muss dann noch unter
      der Düse durchgehen. Abstand grob schätzen (Lineal, ±1 mm reicht), Ziel ~2 mm.
- [x] Schätzwert auf dem Pi eintragen (`probe_tip_offset_mm`: 2,0, siehe oben)
- [ ] Genauigkeit holt der **Fokus-Test** (Kalibrieren → Fokus): er lasert
      13 Linien in 0,5-mm-Stufen von −3 bis +3 mm, die Kamera sucht die
      schmalste, und der Pi korrigiert `focus_gap_mm` selbst. Ein Fehler im
      Tasterversatz wird dabei mit ausgeglichen. Voraussetzung: Firmware
      (Schritt 2) und Kamera (Schritt 6) sind schon umgestellt.

> **Achtung, bis Schritt 2 erledigt ist:** Die Firmware rechnet für Z noch
> mit 380 Schritten/mm (alte Gewindespindel). Mit der Zahnstange sind es 80 –
> jede Z-Fahrt ist dadurch **4,75-mal so weit und so schnell** wie befohlen
> (Referenzfahrt, Abtasten, Fokus, Jog). Z nicht über die Software bewegen,
> bis der Pi mit `M92 Z80` läuft (oder die neue Firmware drauf ist).

**Schritt 2 – Firmware für v6**
- [x] `build.py`: Z 380 → 80 Schritte/mm (GT2 20 Z = 40 mm/Umdrehung) – 30.10.
- [x] Pi sendet beim Verbinden `M92 Z80` (alter EEPROM-Wert wäre sonst wirksam).
      Damit stimmt Z schon **ohne Flashen**, sobald der Pi aktualisiert ist – 30.10.
- [ ] Z-Höchsttempo, Homing- und Antast-Tempo neu festlegen (Pi setzt heute `M203 Z9`)
- [ ] Z-Motor nie abschalten
- [ ] Flashen (Besitzer vor Ort), danach Z-Weg mit Messschieber prüfen

**Schritt 3 – Fahrwege aller Achsen messen** (vorgezogen, Besitzer 30.10.)

Voraussetzungen:
- [x] Pi mit `M92 Z80` beim Verbinden installiert und Dienst neu gestartet (2471c3f, 30.10.)
- [ ] SKR eingeschaltet und per USB am Pi. **Störung 30./31.10.:** Der lose
      Kühlkörper des STM32 fiel auf die Nachbar-Pins (Kurzschluss). Danach
      blinken die LEDs schnell (Neustart-Schleife), der Pi meldet beim
      Anmelden `error -32/-71`. Kühlkörper entfernt (STM32 braucht keinen),
      blinkt weiter. Nur an USB: rote Strom-LED und grüne LED blinken, der
      **Extruder-Treiber (unbenutzt) wird warm** → vermutlich schließt ein
      defekter Treiber 3,3/5 V kurz. **Nachtrag 31.10.:** STM32 und der
      3,3-V-Regler daneben werden nur an USB sehr heiß → STM32 vermutlich
      intern durchgeschlagen, Board defekt. Ersatz: gleiches SKR Mini MZ V1.0
      (Firmware und Gehäuse passen unverändert), sonst SKR Mini E3 V3
      (Firmware-Port nötig). USB abgezogen. Weiter: Foto, Widerstand
      3,3 V/5 V gegen Masse messen; Treiber ablöten lassen oder Ersatz-Board
      (z. B. SKR Mini E3 V3). SD-Neuaufspielen hilft erst nach behobenem
      Kurzschluss. **Reparatur 02.11.:** STM32 ausgelötet; ohne Chip nur an
      USB: AMS1117 (U4) 5 V rein, 3,33 V raus → Versorgung heil, der STM32
      war der Kurzschluss. Ersatz: STM32F103RET6 aus der Platine einer Gasheizung
      (gleiches LQFP-64, mehr Flash/RAM), danach per ST-Link V2 an der
      SWD-Leiste entsperren + BTT-Bootloader, Firmware wie gehabt (RC-Build).
      **02.11. abends:** RET6 eingelötet, per ST-Link V2 (WinUSB via Zadig,
      xPack OpenOCD) gelesen: ID 0x10036414, 512 KB, kein Lese-/Schreibschutz.
      Komplett gelöscht, BTT-Bootloader SKR Mini MZ (Sicherung GadgetAngel,
      15 520 B, sha256 78fe4c2f…0e9c2ed4) an 0x08000000 geschrieben, Verify OK.
      marlin-59 SKR (sha256 db1c9a8e…) per ST-Link ab 0x08007000 geschrieben,
      Verify OK. Nach dem Start reißt die SWD-Verbindung ab (Marlin belegt die
      SWD-Pins) – erneutes ST-Link-Flashen nur mit RST (connect under reset).
      SKR meldet sich am Pi (LeafLabs Maple, /dev/ttyACM0), `op=connect` OK,
      M115: Marlin 2.1.2.9 vom 01.11. 20:47 (marlin-59). `M122` ist jetzt als
      reine Abfrage freigegeben (`op=report`, Diagnose-Knopf „Treiber M122“).
      M122 mit 24 V (02.11.): X, Y, Z „connection OK“ – Treiber überlebt.
      E-Treiber (früher warm) ist in der Firmware nicht angelegt, ungeprüft.
      Eingebaut, Laser-Minus direkt am Netzteil. Erste Referenzfahrt (Go)
      02.11.: Z lief falsch herum, Marlin `kill()` (Homing failed). Die
      SKR-Firmware stand noch auf Kopf v6 mit Zahnstange. Neu im SKR-Build
      (wie Anet): `INVERT_Z_DIR true`, Z 1018,59 Schritte/mm (Schnecke),
      Z-Wächter (`ENDSTOPS_ALWAYS_ON_DEFAULT` + endstops.cpp-Patch); der Pi
      sendet `M120` jetzt bei beiden Boards. **marlin-60 geflasht (02.11.)**,
      Referenzfahrt (Go) OK: X/Y, Z-Boden, Rückzug; Z fährt zum Schalter.
      Achstest X±10, Y±10 OK; Kopf hob dabei auf Z23 (Freifahrhöhe).
      Z-Jog ohne Werkstückhöhe vom Pi gesperrt (gewollt). Offen: Relais und
      PWM ohne Laser prüfen (`op=service_supply`, `op=ttl_test` messen),
      dann Laser anstecken. **03.11.:** Relais-Test 2× 30 s (Messwert offen).
      Besitzer gab versehentlich 24 V auf R1 (470 Ω) des Optokopplers; LED
      danach im Diodentest über R1 1,35 V / Sperrrichtung OL → lebt. Laser
      flackerte, sobald PA1 angeschlossen war, obwohl Relais aus und M5
      (Pi-Status) → Rot hängt nicht hinter Relais-NO? prüfen. MASCHINE.md
      korrigiert: PA1 liegt am BL_Touch-Header (Pin 3 von 5; Marlin
      SERVO0_PIN), nicht an PWR-DET (PC12). PA2 ist TX2 (Serial 2 aktiv) → nicht verwenden.
      Laser zeichnete bei S255 Punkte statt Linie und glimmte nach dem
      Auftrag (Gelb 0,05 V, 24 V stabil): PWM-Teiler zu hochohmig. Neu:
      **Laser-Interface V2** (`hardware/laser-interface-v2/`): Relais G5LE-1
      + Sicherung + SFH618A/PC817 + 7805 (5 V geregelt) + 2,2 kΩ Pull-down
      auf einer Platine; KiCad-Platine (DRC 0) mit Gerber-ZIP für JLCPCB und
      Lochraster-Bauplan 7 × 9 cm. Kopie: `\\NAS\Projekte\Lasercut Projekte\Laser-Interface-V2`.
      Lochraster seit 03.11. mit **LM317T** (aus der Gasheizungsplatine, Besitzer hat keinen
      7805) und R6 220 Ω / R7 680 Ω stehend → 5,1 V; Fahne = Ausgang. Platine (JLCPCB) bleibt 7805.
      04.11.: Besitzer bestückt; Relais ist ein NAIS JS1-24V (Pins vor dem Verdrahten messen),
      R5 = 5,6 kΩ (kein 4,7 k da), C1 104K63, C2 1M63, C3 Elko 47–56 µF. Klemmen-Etiketten 1:1:
      `beschriftung_anschluesse.pdf`.
      **Laser flackert im Takt der Motoren (04.11.) – Ursache Firmware:** PA1 ist TIM2 CH2, TIM2
      ist im Maple-HAL der Temperatur-Timer (72 kHz, ISR setzt den Zähler alle ~72 Takte zurück).
      Folge: S ≥ 72 war schon volle Leistung, und weil die Schrittmotor-ISR (höhere Priorität)
      das Zurücksetzen verzögert, schwankte die PWM mit jeder Motorbewegung. Fix in `build.py`
      (`patch_laser_pwm_timer`): TIM2 läuft frei 0..254 bei ~1 kHz, CH1 = Temperatur-ISR,
      CH2 = Laser-PWM in Hardware, S 0..255 linear. Lokal gebaut (SHA `b9156d10…`); kommt als
      Firmware-Update per Knopf. Danach Leistungen auf dem SKR neu prüfen (vorher zu stark).
      05.11.: marlin-61 per Knopf geflasht. Testauftrag (Kreis, S255, F6000) graviert nichts und
      flackert weiter. Bei S255 ist die PWM dauerhaft an, die Firmware scheidet damit aus. Verdacht:
      Kabel/Klemmen (Kabelkette) oder Netzteil; Laser und SKR hängen am selben 24-V-Netzteil
      (Typenschild offen). Nächster Schritt: Kabel durchpiepsen, Kopf von Hand verfahren.
      **05.11. Messungen und Pinwechsel:** V2 ohne Laser, Signal vom Pi: D'R 50 % → 2,5 V, 100 % → 3,7 V
      (Soll laut Bauplan ~4,7 V). Originalboard TTL ohne Last: 5 V (Besitzer; ob Ruhepegel oder Befehl, offen).
      Nächster Schritt: TQ messen (4,9–5,3 V), dann 680 Ω parallel zu R1 (340 Ω); U1-Typ ablesen.
      Treiber ZY62 (Laser aus, `hardware/laser-treiber-zy62/`): J3 = vom Adapter, J2 = Lüfter (Besitzer).
      J3: A-B 1,28 kΩ, B-C 14,53 kΩ, A-C 64,7 kΩ, A-X 43,1 kΩ, sonst > 200 MΩ. Diodentest: T1 222, D6 648/916,
      C5 218, C6 OL. Kein Kurzschluss auf dem Treiber; die 0,3 („00.3“) am Stecker sind ungeklärt (Einheit?
      Kabel/Adapter?), Messung Kabel ohne/mit Treiber offen. Am Diodenstecker ohne Diode bei 20 %: ~1,2 V.
      **Besitzer misst an PA1: Schuss 5 s geht nur kurz an und wieder aus.** Ursache offen (`fire_test` hält M3 S
      über G4; `LASER_SAFETY_TIMEOUT_MS` ist nur Verdacht, keine abschaltende Stelle gefunden). Darum Laser-PWM auf
      **PA9 (EXP3, TIM1 CH2, 1 kHz)**: SKR-Plan des Besitzers (Mini MZ V1.0), EXP3 obere Reihe GND, PB8, PA10, PA9, PB5.
      Für dieses Board gilt der BTT-Plan, nicht Marlins E3-Pin-Datei (dort heißt der Stecker EXP1, andere Belegung).
      marlin-62 geflasht, PA9/GND am Stecker geprüft, Signal an EXP3 (Besitzer). `ttl_test` 2 × 10 s an PA9 lief, Messwert offen.
      PWM geht laut Besitzer später an und früher aus als die 24 V: Beim Schuss war das Absicht (0,8 s Wartezeit, 24 V blieben stehen).
      **Service-Menü (Besitzer):** Regler 0–100 %, keine Zeitgrenze, 24 V an/aus (`op=service_laser` statt `service_fire`, 24-V-Timer entfällt).
      Strahl aus bei 24-V-Schalten und wenn die Seite 5 s schweigt (Wächter im `monitor_loop`). Offen: Etiketten ändern, TQ/R1.
      Besitzer sah 17:13–17:16 den Laser im Takt des Protokolls wechseln. Pi-Log: Leistung sprang von einer IP zwischen 23 % und dem Reglerwert
      (mein Fehler: Seite wiederholte den Wert, vermutlich zwei Tabs). Behoben mit `op=service_laser_ping`. Offen: ob das Flackern damit weg ist;
      das M114 alle 2 s (Monitor) schaltet laut Marlin-Quelltext nichts ab, im Stillstand mit festem Wert nachprüfen.
      Besitzer danach: Bei festem Wert und einem Tab geht der Laser weiter im Takt des Protokolls aus und an. Ursache offen. Am Laser liegen laut Besitzer jetzt 5 V an, R1 bleibt.
      **Eigene Firmware (Auftrag Besitzer 05.11.):** Zweig `eigene-firmware`, Vertrag `docs/FIRMWARE_EIGEN.md`, Code `firmware/lumacut/`, für den RET6 (Marlin lief als RC-Build). Nur am PC geprüft, nie auf Hardware. Inbetriebnahme mit dem Besitzer, Rückweg Marlin per SD und alter Pi-Stand.
      Parallel auf main: Weboberfläche, Pi-Betrieb, Panel 1.3 (siehe CHANGELOG). Achtung: `update.sh` holt `main` jede Nacht ~04:15. Dienstdatei ist gehärtet, Stop löst bei aktivem Strahl M112 aus.
      Unabhängiges Review: 12 Funde behoben (Commit 4566d10, 811 Host-Prüfungen, 432 Pi-Tests). Z ohne Referenz höchstens 25 mm (Besitzer). Abbilder `A:\mfw\lumacut-fw\`, Ablauf `docs/INBETRIEBNAHME_FIRMWARE.md`. **Wechsel nur mit dem Besitzer: `eigene-firmware` erst dann nach main.**
      Panel 1.3 am echten Gerät bestätigt (Bild, Touch, Seite System, Update über den Pi). **Eigene Firmware 0.2.0 läuft auf dem RET6** (Besitzer per SD): USB meldet sich als `LumaCut CNC`, M115 und M119 antworten. Fehler am Gerät: Endschalter verkehrt herum (gedrückt = Low, Vertrag war falsch), TMC-Antworten sporadisch (SENDDELAY erst nach dem Einrichten), Startmeldung kam als Echo in den ersten Befehl, Pi suchte den alten Maple-Namen. Korrigiert in 0.2.1. Weiter nach `docs/INBETRIEBNAHME_FIRMWARE.md`.
      0.2.2 per SD (Selbst-Update brach ab, weil der Pi den Port nach `ok DONE` schloss, behoben, noch nicht erneut getestet). Am Board bestanden: Schritte 1–4: Endschalter X, Y, Z richtig (M119), Relais, Licht, Abluft einzeln; PA9 0/1,4/2,6 V; V2 D'R 0/2,7/4,9 V, kein Zucken im Protokolltakt. Treiber antworten, 1 Aussetzer in 15 Lesungen. Motoren laufen, Richtung laut Besitzer richtig. **0.2.1/0.2.2 hatten die Schalter nur in M119 korrigiert, im Schritt-Interrupt falsch herum:** Referenz dort ungültig, Fahrt zum Schalter stoppt am ungedrückten und läuft durch den gedrückten. Korrigiert in 0.2.3, Selbst-Update über den Pi am Board bestanden. Schalter-Test in Fahrt bestanden (X, Y, Z stoppen sofort), erste echte Referenz gelungen. Danach am Tablet-Auftrag: Taster 17 mm und 8,2 mm auf 3 mm MDF, Z-Stopp bei Z 14,84 in der Ecke. Verdacht Störungen, 0.2.4 filtert 1 ms. Besitzer danach: Zahnrad beschädigt (wohl vom Lauf gegen den Rahmen mit 0.2.2), das erklärt die Werte vermutlich. Materialtest läuft wieder, brach aber beim Parken an Y0.038 ab (Pi bewertete den Treffer nach dem alten Ziel); behoben, 0.2.5 fährt die letzten 0,5 mm weiter. 0.2.5 per Selbst-Update drauf, danach `Driver not responding` wechselnd X, Y, Z bei jeder Fahrt, obwohl Lesen 60/60 klappt und die Register stehen. Ursache nicht belegt; 0.2.6 wiederholt die Einrichtung und meldet die Stufe in M122 (am Board: 1 Wiederholung, Treiber Z, Stufe IFCNT).
      **Kalibrierung 05.11. abends:** Fokus-Test bei X310 Y180 (25 %, −3…+3 mm) und X200 Y290 (18 %, 0…+6 mm, je 1200 mm/min): schmalste Linien +1,5…+2,5 bzw. +3…+5 mm, Vorschlag Fokusabstand 10 statt 7 mm, noch nicht eingetragen. Kamera lag fest −9,99/−9,62 mm daneben (beide Fotos gleich, Streuung ≤ 0,4 mm): Lage in `android.lens.g` korrigiert (Revision 9, Sicherung `A:\mfw\lumacut-fw\camera_calibration_vor_kamerakorrektur.json`), kein neues Punktraster. Live-Prüfung bestanden: Kameramarke des L-Musters 0,2/0,04 mm neben der Bildmitte. Taster: 5× auf Plexiglas (2,66 mm) Mittel 2,885, Spanne 0,045; 5× ohne Mittel −0,259, Spanne 0,025; Differenz 3,144 mm, Ursache offen (Plexiglas lag auf dem unebenen Bettstreifen?). Z-Weg: 20 mm gefahren, 19,82 mm mit Messschieber. Keine Änderung an Schritten/mm. Spiel aus der Noniusskala: X ca. 0,24 mm, Y ca. 0,22 mm, noch keine Kompensation. L-Muster auf dem MDF bei X60 Y122, X160 Y122, X60 Y222; Messschieber laut Besitzer „passt“ (keine Zahlen genannt). Direkter Fokus-Vergleich (12 %, 1200 mm/min, je 3 Linien gemischt, bei X87–133 Y147): 7 mm 0,221 / 9 mm 0,224 / 10 mm 0,216 / 11 mm 0,224 / 12 mm 0,212 mm, Streuung je Abstand bis 0,07 mm: kein Unterschied messbar, Kamera am Limit (0,06 mm/Pixel). Kontrast bei 7 mm am höchsten. Fokusabstand blieb danach 7 mm (am 06.11. abends steht er auf dem Pi auf 10 mm, siehe Schnitt-Test). Tempo-Test bei 150 mm/s: sauber bis 3000 mm/s², bei 4500 Schrittverlust; eingetragen 2100 mm/s², 150 mm/s (`op=motion_limits`, vorher 500). Über 150 mm/s ungetestet. Erster Materialtest MDF unbrauchbar: Felder wurden daneben gemessen, 80 % als „hell“ gespeichert; Werte gelöscht, Sicherung der alten Materialien `A:\mfw\lumacut-fw\materials_backup.json`. Ursache laut Foto vom 06.11.: Die Testfotos entstanden auf Z 23, dort liegt das Kameramodell bis 180 Pixel (rund 6 mm) neben den Feldern, auf der kalibrierten Höhe (Z 54,3) etwa 10 Pixel. Das 10-%-Feld ist entgegen der ersten Annahme gut sichtbar (Handmessung Ton: 10 % 0,39, 29 % 0,44, 80 % 0,63–0,77). Behoben: Der Test fotografiert jetzt auf Oberfläche + kalibrierte Höhe und bricht bei falscher Kamerahöhe ab; außerdem kein Versatz aus Feldern ohne Färbung, und weit daneben liegende Töne werden nicht gespeichert. Zweiter Lauf 06.11. (X172–223 Y176–197, 9 Felder): Messung plausibel, Töne steigen mit der Leistung und wiederholen sich (8 % bei 5486 mm/min 0,34; 10 % 0,44; 20,8 % 0,46; 37,8–42,1 % 0,53–0,58; 76,5 % 0,67; alle anderen bei 4500 mm/min), Versatz höchstens 0,5 mm. Abbruch ohne Speichern durch die Tonprüfung: „dunkel 0,46 statt 0,85“. Zwei Fehler der Suche, behoben und im dritten Lauf bestätigt: Sie wurde bei 4500 mm/min nicht langsamer, obwohl Dunkel dort nicht erreicht wurde (jetzt bis 1500 mm/min), und sie bevorzugte ein „sauberes“ Feld auch weit neben dem Ziel. Die Grenze für Streifen (0,08) lag bei den meisten Feldern darunter; ob das Holzstruktur oder Flackern ist, ist offen. **Dritter Lauf 06.11. (X172–223 Y200–221, 7 Felder), gespeichert:** MDF 80 % / 2823 mm/min Ton 0,84; MDF (mittel) 43,6 % / 4500 mm/min Ton 0,56, Streifen 0,083, Hinweis „fleckig/streifig“; MDF (hell) 8 % / 5494 mm/min Ton 0,31. Töne gegenüber dem zweiten Lauf bei ähnlicher Leistung bis 0,02 anders. Streifen 0,04 bis 0,113, am höchsten bei 42,5 % / 4500 mm/min, am niedrigsten beim langsamen dunklen Feld; ob Flackern oder Materialstruktur, ist offen. Scharfes Foto danach: Töne sichtbar abgestuft, kleiner Rauchfleck am Dunkel-Feld. Zweitmessung von der Fotohöhe weicht bis 0,07 ab (Dunkel 0,91 statt 0,84), so genau ist die Messung also. Streifenwert der Felder 0,048–0,117, unverbranntes MDF 0,018–0,025; keine gemeinsame Periode über die Zeilen. Das Foto kann Flackern weder belegen noch ausschließen, weil verbrannte Fasern stärker hervortreten und die Zeilen in wechselnder Richtung laufen. **Linientest 06.11.** (X175–215 Y220–232, je 3 Linien 1200 mm/min 12 %, 2400 mm/min 25 %, 4500 mm/min 43,6 %, gleiche Energie je mm): keine Lücke, keine Stelle unter 50 % Dunkelheit, Streuung 5–6 % wie bei einer gezeichneten gleichmäßigen Linie. Starkes Flackern und Aussetzer sind damit für diese Läufe ausgeschlossen; kleine Leistungsschwankungen nicht, weil die Linien fast schwarz sind. Schwache Spitzen um 4 Hz in allen drei Tempi liegen im Bereich der Vergleichslinie, nicht belegt. Neu: Die Linien sind leicht wellig, RMS 0,03–0,06 mm. Nur bei 4500 mm/min ähnelt sich die Welle von Linie zu Linie (Korrelation um 0,5, Periode etwa 3,6 mm, rund 21 Hz). Vermutung, nicht belegt: mechanische Schwingung; sie könnte die höheren Streifenwerte der Felder bei 4500 mm/min erklären. Noch kein echtes Motiv damit graviert, vom Besitzer noch nicht beurteilt. **Schnitt-Test MDF 3 mm 06.11.** (hochgelegt, X173–217 Y186–194, Oberfläche Z 5,52, 100 %): gespeichert 800 mm/min × 6 Durchgänge. Vorsicht, wohl nicht das beste Ergebnis: Bei 350 und 500 mm/min fällt die Helligkeit schon im 3. Durchgang sprunghaft (Verhältnis 0,52 und 0,56), die Grenze „halb so hell wie am Anfang“ wurde knapp verfehlt, deshalb liefen dort 10 und 7 Durchgänge. Vermutlich reichen 500 mm/min × 3; ob die Teile da fielen, ist nicht geprüft, die Grenze ist nicht geändert. Der Lauf fand mit Fokusabstand 10 mm statt und nach Kamera-Revision 10 (Punktraster vom Tablet, 06.11. 17:25); die Gravur-Werte stammen von Fokusabstand 7 mm und Revision 9. Beides habe nicht ich geändert. Sperrholz steht noch aus; die alten Materialien sind gelöscht (Sicherung s. o.). Oberfläche des MDF je Stelle Z 2,45 bis 3,09. `CAMERA_ABOVE_Z_MM` (88,6) passt nicht mehr und ist nicht neu gemessen; der Materialtest braucht den Wert auf der Fotohöhe nicht mehr.
      Offen: bauen, ohne Laser testen (D'R ≈ 4,7 V).
      Bereit liegt die
      v6-Firmware `A:\mfw\dist-v6\firmware.bin` (Z 80 Schritte/mm, gebaut
      31.10., SHA-256 `96ca4fc6…6a9`).
- [x] Hut auf dem Taster, Papier-Probe bestanden – sonst drückt die
      Z-Referenzfahrt (G28 Z an X0/Y0 über den Taster) die Düse ins Bett
- [ ] `M503` lesen: `M92 X80 Y80 Z80`

Ablauf (jede Fahrt mit Go, langsam F1500, Besitzer beobachtet):
1. Referenzfahrt (X/Y, dann Z über den Taster an X0/Y0).
2. Z: auf 70, 75, 80 mm – Abstand zum oberen Schienenende/Anschlag ansehen.
3. X: auf 300, 350, dann in 5-mm-Schritten bis zum Anschlag am Rahmen
   (Besitzer sagt Stopp); Z dabei auf Fahrhöhe.
4. Y: genauso (alter Kopf lief bei ~350 an).
5. Kopfmaß für das Parkband: Abstand Düsenmitte → Gehäusekante zur Tür hin
   (Y+), mit dem Lineal.
- Ergebnis eintragen: X max ___, Y max ___, Z max ___, Kopfkante Y+ ___ mm
- [ ] Firmware/Pi-Grenzen auf die gemessenen Werte (minus Reserve) setzen

**Schritt 4 – neue Aufteilung der Fläche**
- Die 30-mm-Zone in L-Form **entfällt**.
- Neu: **Parkband** über die ganze X-Breite auf der Y-Referenzseite, so tief
  wie der Kopf + 10 mm. Dort wird referenziert und geparkt; dort liegt nie Material.
- **Alles andere ist Arbeitsfläche** (auch die volle X-Breite).
- Randstreifen, die der Laser erreicht, Taster/Kamera aber nicht, werden angezeigt statt still gesperrt.
- [ ] Pi: Fahrwege, Sperrzone, Parken, Antast-Grenzen (`transport.py`, `web.py`, `placement.py`)
- [ ] Firmware: Bettgröße, Antast-Grenzen
- [ ] App: Arbeitsfläche im Editor genau wie die Maschine, Kamerabild, Rahmen, Scan, Import (Fläche vom Pi lesen)
- [ ] Web-Oberfläche
- [ ] Doku: README, MASCHINE.md, ANDROID_APP.md

**Schritt 5 – Parken nach jedem Auftrag**
- [ ] Laser aus → hoch → ins Parkband → absenken, bis der Taster das Bett
      berührt; Z-Motor bleibt bestromt. Vor dem nächsten Auftrag erst hoch, dann raus.

**Schritt 6 – Kamera neu kalibrieren** (fährt jetzt mit Z mit)
- [ ] Versatz zum Laser, mm pro Pixel, Scanhöhe

**Schritt 7 – G-Code-Optimierer auf dem Pi** (für jeden Auftrag, auch LightBurn)
- [ ] Innenteile vor Außenkontur (die App macht das schon; der Pi soll es für alle Quellen)
- [ ] Weniger Leerfahrten
- [ ] Geradenstücke zu Bögen G2/G3 (weniger Zeilen über USB, flüssigere Fahrt)
- [ ] Leere Rasterzeilen und Ränder überspringen
- [ ] Genaue Restzeit

## 10. Danach: Fahrplan

- **GY-521 anschließen** an den Pi (VCC 3,3 V Pin 1, GND Pin 6, SDA Pin 3,
  SCL Pin 5, INT optional Pin 7; XDA/XCL frei). Verdrilltes Kabel, nicht neben
  Motorleitungen, I²C langsam. Nutzen: Schwingung messen und Input Shaping
  (`M593`) selbst einstellen; Abrutschen von Z und Stöße erkennen; Verschleiß bemerken.
- Projekte-Dialog am Tablet ausprobieren (App 1.0.49).
- Materialtest mit Kamera (`op=matcal`) einmal echt an der Maschine laufen lassen.
- Oberer Streifen gesperrt (06.11.): Pi `blocked_band_y_mm` = 35, nutzbar 370 × 325 mm. Aufgeklebter MDF-Streifen 3 × 3 mm als Anschlag; muss von der Parkposition des Kopfs frei bleiben (Y um 32–35), Parkhöhe sonst über 3 mm stellen. Geplant: Schwamm zum Säubern der Kameralinse auf der Achse.
- Android-App, Arbeitsbereich geprüft (06.11.): Fläche und Park-Ecke kommen vom Pi und stimmen (370 × 360, Ecke oben rechts, Maschine X0–78 / Y0–35). Korrigiert: alte Angabe 360 × 340 in zehn Texten und der 30-mm-Rand in den Einstellungen, Park-Ecke unter dem Kamerafoto verdeckt, Import und „im Bereich halten“ legten Teile in die Ecke, Prüfungen nach der ganzen Umrissbox statt nach der echten Bahn. Am Tablet noch nicht geprüft.
- **Messung am Brand 06.11. (`kalibrierung-versatz`, X225–331 Y87–123, MDF):** Hin minus Rück bei F1000 −0,44, F1500 −0,50, F3000 −0,64 mm (linke und rechte Kante gleich, Streuung 0,02–0,09); bei F4500 und F5500 um −0,5 bis −0,6 mit großer Streuung (bis 0,57). Die Zeilen wellen quer zur Fahrt mit rund 20 Hz, RMS 0,014 mm (F1000) bis 0,076 mm (F5500); in einer Richtung bei F3000 0,026 statt 0,035 mm. Damit ist Punkt 1 unten am Brand belegt und größer als gedacht; das Spiel allein von 0,24 mm erklärt es nicht, das Tempo wirkt mit. Ausgleich `scan_offset.py` am Brand geprüft (X297–355 Y200–226, Tabelle 1000:−0,44, 1500:−0,495, 3000:−0,64): Rest bei F1500 ±0,04 mm, bei F3000 +0,10 mm. F3000 streut also je Stelle (−0,64 bei X270, −0,54 bei X320), auf dem Pi steht jetzt −0,59. **Ausgleich ist an.** Über F3000 gilt dieser Wert unverändert, dort ist der Versatz nicht sicher gemessen (F4500/F5500 Streuung bis 0,57). **Wellen-Test 06.11. (X293–351 Y232–268, 3 Läufe):** Welle RMS bei F3000: 2100 mm/s² 0,038, 1050 0,022, 500 0,018 mm; bei F4500: 0,052 / 0,038 / 0,028 mm. Bei 2100 ist sie am Zeilenanfang fast doppelt so stark wie am Ende (0,046 → 0,027), langer Vorlauf 25 mm drückt sie auf 0,021 mm, kostet aber viel Zeit. Sanfterer Zeilenwechsel (Y mit F300) brachte nichts. Je Variante nur ein Block, Messrauschen rund 0,01 mm. **Seit 07.11. steht die Beschleunigung auf 1050 mm/s²** (Besitzer), Höchsttempo 150 mm/s. **Brand bei 1050 am 07.11. (X285–359 Y271–297):** Tabelle unverändert, Hin minus Rück an linkem/rechtem Blockende mit 8 mm Vorlauf: F1000 0,00/−0,01, F1500 0,00/+0,01, F3000 +0,04/−0,01 mm. Ein Ausreißer im Einrichtungs-Block F3000 (Streuung 0,18 mm links) ist im Foto nicht als Kammung zu sehen, vermutlich ein Fleck. Die Linienziele mit nur 4 mm Vorlauf zeigen bei F3000 weiter Zickzack an den breiten Balken, die Welle in Y ist sichtbar. Vermutung, nicht belegt: Einschwingen nach der Umkehr bei kurzem Vorlauf (die App schreibt bei diesem Tempo rund 2,5 mm). Offen: Vorlauf der App prüfen, App-Bildkette (Dither, Abtastung).

**Netzteil 07.11.:** Altes 24-V-Netzteil laut Besitzer 60 W (Laser 80 W angegeben, SKR am selben Netzteil), getauscht gegen das 24-V-Netzteil des Anet A8 (Typenschild nicht genannt, Spannung nicht gemessen). Materialtest Gravur MDF danach (X274–325 Y318–339, Fokusabstand 10 mm): 10 % / 4500 Ton 0,535 (vorher 0,438), Dunkel 73,4 % / 4500 Ton 0,868 (vorher 80 % / 2823 für 0,842), Mittel 11,3 % / 4500 Ton 0,572, Hell 8 % / 6000 Ton 0,315, gespeichert. Gleicher Ton braucht grob 40 % weniger Energie je mm; Fokusabstand (7 → 10 mm) und Kamera-Revision haben sich seit dem alten Test auch geändert, der Unterschied ist also nicht allein dem Netzteil zuzuordnen. Die Kurve ist unten sehr steil (Mittel liegt bei 11 %, Hell braucht 6000 mm/min). Schnittwert 800 × 6 stammt vom alten Netzteil, ein neuer Schnitttest braucht die hochgelegte Platte. **Offen, auffällig:** Taster an derselben Stelle (Mitte X299,5 Y328,5) kurz hintereinander Z 1,798 (`op=probe`) und 0,824 (Materialtest), die Gravur lief also mit Fokus rund 1 mm tiefer. Ursache unklar, Wiederholungstest steht aus. Sicherung der Materialien vor dem Test: Scratchpad `materials_vor_netzteil.json`. **07.11.:** Der Hin/Rück-Ausgleich war seit dem Nacht-Update 04:28 aus, weil die Prüfung beim Laden die Tabelle verwarf. Behoben, Tabelle 1000:−0,44, 1500:−0,495, 3000:−0,59 wieder eingetragen. Gravuren zwischen 04:28 und der Korrektur liefen ohne Ausgleich.
- **Gravurqualität, Befund 06.11. (fünf Prüfungen, Modelle und Nachrechnung, kein Foto ausgewertet):** Reihenfolge nach Rang: (1) X-Spiel 0,24 mm ohne Ausgleich bei wechselnder Zeilenrichtung, im Modell Kante 0,16 → 0,34 mm, am 28.10. noch 0,11 mm gemessen, andere Methode. (2) Bild als Jarvis-Dither mit 0,1-mm-Zellen bei rund 0,21 mm Strahl: 91 % der Brennstücke kürzer als der Strahl, Schrift nicht geschlossen; Bildkette skaliert dreimal, Nächster Nachbar. (3) Eigene Fehler vom 06.11.: Z-Toleranz, Planung (zurückgenommen). (4) Firmware: Trapez statt S-Kurve bei 2100 mm/s², Vorlauf ohne Einschwingen, Planer-Gatter nach leerer Warteschlange, 1 kHz PWM bei hohem Tempo. Noch offen: Zahnrad und Riemen seit dem Lauf gegen den Rahmen am 05.11. nicht geprüft. Fokus 10 mm vom Tablet (Assistent am Bereichsende), Kamera Revision 10 nicht gegengeprüft.
- Auftragsplanung auf dem Pi (`job_optimizer.py`, 06.11., **zurückgenommen, standardmäßig aus**; die Schätzung unten sagt nichts über Qualität): Am Auftrag `Neues-Projekt` (41 102 Zeilen) rechnerisch 2680 s mit alter Z-Regel und Reihenfolge, 1427 s mit neuer; nur geschätzt, am Board noch nicht gemessen. Rechenzeit am Pi 9 s. Auf einer flachen Platte hebt der Kopf bei langen Fahrten nicht mehr an (`op=job_optimizer lift=1` schaltet das Anheben wieder ein): Ein Hindernis zwischen Motivteilen, höher als der Fokusabstand, würde dann getroffen.
- Android-App 1.0.56, Ebenen neu (06.11., auf dem Pi bereit): Leere Ebenen verschwinden von selbst, Liste zeigt nur Ebenen mit Inhalt, Antippen wählt die Teile, Zahnrad öffnet die Werte, Aktionen in der Liste. Core-Tests grün, Bedienung am Tablet vom Besitzer noch nicht geprüft.
- Android-App, SVG (06.11.): Struktur, Farb-Ebenen, Aufteilen, Gruppen-Teil antippen (siehe CHANGELOG). Core-Tests grün, am Tablet und mit echten SVG-Dateien noch nicht geprüft. DXF und HPGL bleiben ohne Farben/Ebenen.
- Bettkarte in der App anzeigen; Materialstärke mit der Bettkarte prüfen.
- Später: Windows-Studio nach dem Vorbild der Android-App neu bauen.
- Weitere Pi-Punkte: [PI_STATUS_UND_OFFENE_PUNKTE.md §4](PI_STATUS_UND_OFFENE_PUNKTE.md#4-offene-punkte).

## 11. Offene Fragen und Messungen

- Abstand Tasterspitze ↔ Düsenspitze mit Hut (Besitzer misst).
- Kopftiefe in Y für die Breite des Parkbands.
- Einladungskarte Smaragd: Ergebnis der gelaserten Karte noch nicht besprochen.
- **Anet V1.7 als Ersatz mit Z (31.10. am PC ausgelesen, nichts geschrieben):**
  ATmega1284P (Signatur 1E 97 05), Bootloader vorhanden (avrdude `-c arduino`
  115200 antwortet, FW 5.0) – Flashen per USB möglich. Drauf: Marlin 2.0.9.7
  „Anet A8 plus“ (Zemistr, 13.10.2023), 115200 Baud, SD-Unterstützung, freier
  RAM 11 KB, `M92 Z400` (Spindel; Kopf v6 braucht 80). Plan, falls genutzt:
  (überholt, siehe unten: Board an 24 V) Board an eigenem 12-V-Netzteil, Laser weiter über
  LaserTree am 24-V-Netzteil, **GND beider Netzteile verbinden**, TTL an einen
  freien Hardware-PWM-Pin, abgespeckte LumaCut-Marlin. Schwäche: 8 Bit, wenig
  Zeilen/s bei Graustufen.
  **Firmware vorbereitet (31.10., nicht geflasht):** `firmware/marlin/build_anet.py`
  (Marlin 2.1.2.9 aus dem Anet-A8-Beispiel, Env `sanguino1284p_optimized`,
  46 KB Flash / 4,9 KB RAM; CI baut sie mit). Kopflos, ohne Heizungen/SD,
  250000 Baud, Planer 32 / BUFSIZE 16 / RX 256, Z 80 Schritte, Taster am
  Z-Min wie beim SKR, M300-Motortöne. **Laser-TTL an ISP-Stecker MISO = D6/PB6** (seit 01.11. SCK = D7/PB7, ISP-Pin 3)
  (Timer3-Hardware-PWM; Marlins PWM-Liste für den 1284P wird dafür im Build
  ergänzt) + ISP-GND, **10 kΩ Pull-down TTL→GND** (Pin schwebt beim Reset).
  Optional Relais für 24 V Laser am FAN-Ausgang D4 (M106/M107). Pi erkennt das
  Board: CH340 erst als Grbl gefragt, antwortet dort keiner, `M115` bei
  250000 Baud (`open_controller`).
  **Flashen über den Pi wie beim SKR:** Weboberfläche → System → Firmware,
  `firmware.hex` wählen (`/api/firmware`, `avr_flash.py`: STK500 direkt über
  den Bootloader, auch über die fremde Firmware; Signatur 1E 97 05 geprüft,
  alles zurückgelesen). Am PC mit dem echten Board nur lesend geprüft: Sync,
  Signatur, 8 KB identisch mit der avrdude-Sicherung; der Bootloader hört
  ~0,45 s nach dem DTR-Reset. **Sicherung Original-Firmware + EEPROM:**
  `A:\mfw\anet-backup\` (zurück nur per avrdude am PC, enthält den Bootloader).
  **31.10. 18:20 über den Pi geflasht** (182 Seiten, zurückgelesen), Pi
  verbindet sich: `MACHINE_TYPE:LumaCut CNC Marlin Anet`, Build Oct 31 2026
  16:54:31, `ok P31 B15` (Planer 32, BUFSIZE 16). M503: M92 80/80/80. M119 ohne
  angeschlossene Schalter: alle `open`. **Achtung:** Der Pi schickt beim
  Verbinden `config.motion` = 2100 mm/s² / 200 mm/s (SKR-Kalibrierung, 24 V,
  TMC2209) – für A4988 an 12 V vermutlich zu viel; vor dem ersten Fahren
  niedriger setzen oder mit Bewegungstest prüfen.
  Vor dem ersten Fahren prüfen: M119 mit Schaltern (Logik), Motorrichtungen.
  **Verkabelung festgelegt (31.10., Besitzer):** Board an **24 V** (das
  Original-Netzteil des Anet war 24 V), Laser am selben Netzteil. Der
  FAN-Stecker (D4, FAN0) schaltet die Spule eines **24-V-Relais** (Diode
  1N4007 parallel, falls kein Modul), dessen Kontakt die **+24 V des Lasers**
  (nicht GND, sonst schwebt die Laser-Masse gegen TTL). Firmware hat FAN0 = D4
  (M106 P0 / M107 P0, geprüft im Build); der Pi schaltet es schon wie beim SKR
  vor `M3 I` ein und nach dem Auftrag/Not-Aus aus. TTL = ISP-MISO, GND =
  ISP-GND, 10 kΩ Pull-down. Netzteil ≥ 8–10 A. GY-521 (MPU-6050) am Pi-I2C
  geplant (Resonanzmessung, später Stillstands-Wächter); I2C ist auf dem Pi
  noch aus (`sudo raspi-config nonint do_i2c 0` macht der Besitzer).
  **Firmware-Update per Knopf (31.10.):** CI → Release `marlin-<Nr.>`, Pi lädt
  und prüft es (`firmware_release.py`), Weboberfläche meldet „Firmware-Update
  verfügbar“ und flasht auf Knopfdruck (`op=firmware_update_install`). Ein
  Release entsteht nur bei Änderungen unter `firmware/marlin/` (oder manuell).
  **Am Anet getestet (31.10. 22:53):** Release `marlin-53` per Knopf geflasht,
  Board meldet Build Oct 31 2026 21:41:46, kein Update mehr angeboten.
  **Z-Richtung getauscht (31.10., Besitzer):** `INVERT_Z_DIR true` in
  `build_anet.py`; kommt als nächstes Firmware-Release per Knopf.
  **Anet geflasht (Build 22:15:10).** Halten der Motoren: `M84 S0` beim
  Verbinden (kein Abschalten im Leerlauf). Stromlos sind sie bei Not-Aus
  (`M112`), Board-Neustart (Flashen, Port-Öffnen) und Stromausfall; Z an der
  Zahnstange kann dann fallen. Abhilfe ab 31.10.: **Parken 1 mm über dem Bett**
  (`park_z_mm`, nur an X0/Y0, Pi hebt vor jeder X/Y-Fahrt auf Fahrhöhe).
  Offen (Vorschlag, wartet auf Besitzer): Feder/Gummizug am Kopf; Not-Aus am
  Anet mit `M410` + Relais aus statt `M112`; Port öffnen ohne Reset.
  **Licht am Bett-Ausgang (31.10.):** D12 (Bett-MOSFET, 24-V-LED-Streifen),
  `M355 S1/S0`, nur an/aus (Timer1 = Motortakt, kein PWM); Lichteffekte
  werden dort zu an/aus. Hotend-Ausgang D13 ist noch frei (z. B. Abluft).

## 12. Ideen (noch nicht geplant)

- **Bedienpanel 7 Zoll am Gehäuse (Design 03.11.):** Waveshare ESP32-S3-Touch-LCD-7
  (vorhanden) per USB-C am Pi, nur Oberfläche, Pi bleibt Zentrale; Start nur mit Go-Abfrage.
  Metall-Mockup mit 4 Bildschirmen in `hardware/display-7zoll/` (NAS: `Lasercut Projekte\Display-7-Zoll`).
  Zwei Varianten: A Metall, B Weiß (Besitzer 03.11.: „moderner und cleaner, Richtung weiß“).
  **Firmware fertig gebaut (03.11.)**, helles Design: `firmware/panel/` (LVGL, PlatformIO/ESP-IDF 5.3),
  Pi-Seite `pi400/marlin/panel.py` (läuft in `lumacut-marlin` mit, USB-JSON-Zeilen, nur erlaubte Aktionen),
  Freigabe per Popup statt drei Schaltern (Besitzer). Abbild `lumacut-panel.bin` auf dem NAS.
  **Update über den Pi (03.11.):** Firmware 1.1 liegt in `pi400/marlin/panel_fw/` und kommt mit jedem
  Deploy; die Panel-Brücke flasht das Panel per esptool über dasselbe USB-Kabel, automatisch im Leerlauf
  (abschaltbar, Karte „Bedienpanel“ unter System, `op=panel_update`/`panel_auto`). Neue Version:
  `PANEL_VERSION` in `src/version.h` hochzählen, `tools/release.sh`, committen. Erstes Flashen am PC. esptool 5.6
  auf dem Pi in `/var/lib/lumacut/pylib` (Dienst sieht kein Home).
  Offen: auf dem echten Panel flashen und testen (Bild, Touch, USB zum Pi, Kamerabild).
  Gehäuse-Idee: Dibond schwarz/anthrazit + Alu-Winkel + gedruckte Ecken (Besitzer: kein Holz).
- Infrarot-LEDs im Kopfgehäuse als Licht für die Kamera (Besitzer, 30.10.: „erstmal noch nicht“).
- Roter Linienlaser für 3D-Höhenmessung ohne Brennen (Pi-Unterstützung `op=line_laser` existiert).
- X-Motor ans Trägerende verlegen (Riemenschleife), um den Kopf leichter zu machen.
- **Kopf v7 „Schneckenlift“ (konstruiert 01.11., nicht gedruckt):** Schnecke auf der
  Motorwelle → Schneckenrad 20 Z → GT2-Ritzel auf flacher Zahnstange. Selbsthemmend
  (Steigung 4,8°): Kopf fällt ohne Strom nicht, keine Rückspannung beim Schieben,
  Bremse entfällt. 2 mm/Umdrehung, `M92 Z1600`, bis ~25 mm/s. Neu: T2, T3 (Lasche),
  T5, T7, T8; T1/T4 bleiben. Alle CAD-Prüfungen OK. Nächster Schritt: Prüfstück
  T7+T8 drucken und Selbsthemmung mit 0,9 kg testen. Details `A:\mfw\zmount\v7\LIESMICH.md`.
  **Bevorzugt (Besitzer: so wenig PLA wie möglich): Nachrüstsatz für den
  vorhandenen v6-Kopf**, `A:\mfw\zmount\v7\nachruest\` – ohne Schnitte, ca. 14 g:
  Schnecke, Rad 10 Z mit Ritzel, gedruckte Zahnstange (Modul 1, kein Riemen),
  Getriebebock hinten an der Wand (Stift + Zapfen in den Senklöchern der linken
  Motorschrauben, obere wird M3×20). `M92 Z1018.59`. Alle CAD-Prüfungen OK, jedes
  Teil ein Körper, STL in Drucklage; offen: Platz hinter der Plattenunterkante
  für das Zahnstangenende. Komplett-v7 nicht drucken (T2 bräuchte Stützen).
  **Eingebaut 01.11.** (Besitzer). Z fuhr danach sehr langsam: der Pi sendete beim Verbinden
  noch `M92 Z80` (Riemen) → Z nur 1/12,7 der Strecke. Jetzt `M92 Z1018.59` (Pi und Anet-Firmware).
  Z-Richtung geprüft 01.11. (`op=z_test` +1 mm: fährt hoch, 1019 Schritte – passt, Firmware bleibt). +10 mm: ruhig, 10 mm am Kopf
  nachgemessen (Besitzer) – `M92 Z1018.59` bestätigt. Anet V1.7: Treiber aufgelötet, Strom fest
  (kein Poti) – Z-Taster per M119 geprüft, erste Referenzfahrt mit Schneckenlift OK, parkt auf Z 1.
  Z-Tempo-Stufen 15/20/25/30 mm/s je ±10 mm sauber (Besitzer, 01.11.) → `z_speed_mm_s` = 25 gesetzt
  (M203 Z25 bestätigt). Z-Dauerwächter (`ENDSTOPS_ALWAYS_ON_DEFAULT`, Anet) gebaut: Taster stoppt Z bei
  jeder Fahrt, Pi bricht bei „endstops hit: Z“ ab (X/Y-Treffer beim Parken kein Fehler) – marlin-57
  geflasht, Test: Taster gehalten, Z fuhr trotzdem 10 mm (Marlin prüft Z_MIN als Tasterpin nur beim
  Abtasten). Fix: endstops.cpp-Patch (marlin-58, geflasht) – Test wieder ohne Stopp:
  `ENDSTOPS_ALWAYS_ON_DEFAULT` wirkt nur bei EEPROM-Reset, das gültige EEPROM lädt ohne. Pi sendet jetzt
  beim Verbinden `M120` (Anet). Wächter-Test damit noch offen. Besitzer: Kopf fuhr beim letzten Test
  nicht, obwohl Marlin 10 186 Schritte zählte – Z-Treiber prüfen (Überhitzung?).
  Kamera-Kalibrierung 01.11. begonnen: Abtasten fuhr den Kopf in die X-Ecke (Marlin nach abgelehntem
  Jog in G91 geblieben) – behoben; Mechanik heil (Besitzer). Objektiv von Hand scharf
  gestellt, beste Scanhöhe **Z 53** (Kopf X210/Y190 über Rastermitte). App-Auswertung kippte am Rand → App-Fix
  (Glättung, k3, Feld am Faltrand zuschneiden). **Gespeichert** (App 1.0.54, Rev. 8): 76 Punkte, 0,22 mm,
  scan_z 53, aboveSurface 51,32. Offen: Versatz Kamera↔Laser prüfen (Raster lag evtl. nicht exakt wie gelasert). Offen: Z-Beschleunigung (steht auf 100 mm/s², 30 mm/s erst nach 4,5 mm erreicht).
  **Laser zündet nicht (01.11. 19:57, Fokus-Test):** Auftrag lief ohne Fehler durch, Board blieb verbunden, kein Strahl; Lüfter am Lasermodul dreht beim Start nur kurz (Besitzer: Spannungsfall). Verdacht: 24-V-Laserzweig (Relais an FAN0) bricht beim Einschalten ein. Neu: `op=supply_test` (`seconds` 1..30) schaltet nur das Relais ein (M5 I, kein Strahl, keine Fahrt, ohne Referenz) und wieder aus – zum Messen der 24 V. Ergebnis 01.11. 20:14: am Laser nur **2,9 V**, Lüfter dreht langsam → Fehler im 24-V-Zweig (Relais/Verkabelung). Neu: `op=fire_test` (`percent` ≤ 2, `seconds` ≤ 5) feuert im Stillstand (`M3 S`), danach immer `M5` + Relais aus. Besitzer 20:35: der TTL-Pin gibt nichts mehr aus. Firmware gibt auf **MISO** (ISP-Pin 1, D6/PB6) aus, nicht MOSI (Pin 4). Neu: `op=ttl_test` (≤ 10 s) – Relais aus, Pin auf S255 (~5 V) zum Messen. Messung: zwischen +24 V und PWM immer −24 V → MISO bleibt auf 0 V, auch bei S255 (Pin defekt oder Firmware schaltet nicht; Vorschlag SCK/D7 + M42-Direkttest, wartet auf Besitzer). **Service-Menü (System → Service: Laser, 01.11.):** eigenes Passwort (nur PBKDF2-Hash in `service_password.json`, vergibt der Besitzer selbst), 24 V an/aus (schaltet nach 5 min selbst ab), Feuern im Stillstand bis 20 % / 5 s (`op=service_fire`, ersetzt `op=fire_test`). Adapter P-DA-01 (Handbuch LT-80W-AA-PRO): reine Verteilerplatine ohne Trennung, GND überall gemeinsam, PWM/TTL durchgereicht, Schalter EXT (DC-Buchse) / INT (12V/24V-Pin des Eingangssteckers); Laser-PWM 0/3–12 V, 0–5 kHz. **Laser-PWM auf SCK umgezogen (Besitzer 01.11.):** ISP-Pin 3 = D7/PB7 (OC3B, Timer3), `SPINDLE_LASER_PWM_PIN 7`; TTL-Kabel und 10-kΩ-Pull-down von Pin 1 (MISO) auf Pin 3, GND Pin 6. Vorher klären, wie MISO beschädigt wurde (Verdacht: 12V/24V-Pin am Adaptereingang). **marlin-59 (SCK) geflasht 01.11.**; danach Service-Feuern 20 % / 5 s (21:51, Pi meldet ausgeführt), ab 21:53 antwortet Marlin nicht mehr, der CH340 meldet sich noch an, Besitzer: Board „durch“. Verdacht: Laserstrom fließt über die Logik-Masse des Boards (P-DA-01 verbindet alle GND), weil das Laser-Minus nicht direkt am Netzteil hängt. Vor jedem neuen Board: Laser-Minus und Adapter-DC direkt ans Netzteil, Board nur Signal + GND. Prüfung 22:10 (nur USB, 24 V aus, Laser ab): CH340 meldet sich, 5 V an ISP-Pin 2 und LED an, aber weder Bootloader (STK500-Sync) noch Marlin antworten → ATmega1284P vermutlich zerstört; Neuflashen per ISP geht nicht, weil MISO tot ist. Anet gilt als ausgefallen. **Plan (01.11., Vorschlag):** Arduino Uno mit Grbl 1.1 als neues Gehirn, Anet nur noch Treiberplatine (Uno an die beschrifteten Pads STEP/DIR/ENABLE/STOP, Anet-Chip im Reset oder ausgelötet), Laser-24 V über Relais NAIS JS1-24V (aus Honeywell-Platine) am FAN-Ausgang, Laser-PWM über Optokoppler LTV-817 (aus Waschmaschinen-Platine), Laser-Minus direkt ans Netzteil. Schaltplan: [schaltplan_laser_relais_optokoppler.png](schaltplan_laser_relais_optokoppler.png). Grbl-Pinbelegung D11/D13 vor dem Löten gegen den Quelltext prüfen. **Anet-Pads verworfen (02.11.):** Pads/Pins zu klein zum Anlöten (Besitzer). Neuer Vorschlag: Uno + CNC-Shield V3 mit steckbaren Treibern (A4988/DRV8825, X/Y/Z) – Kauf entscheidet der Besitzer; Relais-Spule über den vorhandenen ULN2003AN (interne Freilaufdiode, COM an +24 V) statt Anet-FAN-MOSFET; Optokoppler-Laser-PWM bleibt. Massehinweis: Uno-GND hängt über Treiber/Shield ohnehin am Netzteil-Minus – verboten ist nur ein zusätzlicher Draht von Uno-GND/Opto-Pin 2 zur Laserseite; Laserstrom nur direkt zum Netzteil-Minus.
- **Testerfindung „Schwerkraft-Schleppklinke“ (01.11., Teststand konstruiert, nicht gedruckt):**
  `A:\mfw\zmount\v_test_erfindung_1.0\`. Statt Selbsthemmung (Wirkungsgrad < 50 %, Aufprall >250 N)
  bleibt der schnelle v6-Direktantrieb. Eine Klinke, die ihr Gewicht offen hält und die ein
  Schleppfinger nur bei Abwärtsbewegung zuzieht, fängt den Kopf erst beim Fall (ab ~0,26 g, Fang nach
  ≤ 6 mm, Rückspannung ~8 V statt ~28 V). Schwachstelle: Schwelle hängt vom Reibwert ab, daher drei
  Abstimm-Klinken. Tischtest ca. 42 g; Einbau in den Kopf erst nach bestandenem Test (1.1).
  Besitzer (01.11.): Klinke ist kein selbsthaltender Antrieb – gewünscht ist ein selbsthaltender,
  schrittverlustsicherer Nachrüst-Antrieb.
- **Testerfindung 2.0 „Lastbremsende Schnecke“ (01.11., konstruiert, nicht gedruckt) – aktueller Vorschlag:**
  `A:\mfw\zmount\v_test_erfindung_2.0\`. Nachrüstsatz + Bremsscheibe vor dem Motorbund: Die Kopflast
  drückt die Schnecke immer zum Motor; dieser Schub bremst sie über die Scheibe selbst (Bremsmoment wächst mit
  der Last). Hält ab μ 0,045 statt 0,076, kein Axialspiel. +3 g, ohne Schnitte. Motorstrom-Empfehlung ~100 mNm
  (Reserve ×2,6, Aufprall < 50 N). Offen (Software, braucht Z-Treiber): Taster als Dauerwächter
  (`ENDSTOPS_ALWAYS_ON`), Referenz-Prüfung vor/nach Auftrag, Haltetest per `M18 Z`.
- **Schnecke rutscht nicht mehr (01.11., Besitzer: T7n verrutschte, Madenschraube hielt nicht):** T7n hat jetzt
  eine **Kappe auf der Wellenspitze** (nimmt den Lastschub zum Motor auf, dreht mit, reibt nicht), D-Bohrung
  gegen Durchdrehen und eine **eingelegte M3-Mutter** für die Madenschraube (Stahl- statt Kunststoffgewinde).
  T7e (2.0) bekommt nur die Mutter, Anschlag ist dort die Bremsscheibe. Beide Prüfberichte OK, nicht gedruckt.
- Weitere Ideen zu Höhe/Kollision: [IDEE_HOEHE_KOLLISION_KAMERA_3D.md](IDEE_HOEHE_KOLLISION_KAMERA_3D.md).

## 13. Nebenprojekte im Ordner

| Ordner | Inhalt |
|---|---|
| `A:\LumaCut\Einladung-Maxim` | Einladungskarte „Smaragd“ (Minecraft-Party). `make_smaragd_laser.py` erzeugt Gravur (Füllfläche) und Schnitt in Endgröße 78,8 × 100 mm. Projekt liegt im Arbeitsstand des Pi. |
| `A:\LumaCut\Projekte\Paar-Hund-Glas` | Geschenk: Paar auf lackiertem Glas 152,5 × 110,5 (gespiegelt, 254 dpi, 1 bit), Hund als Figur aus 3 mm MDF (Gravur + Schnitt), Standfuß „Bühne“ als STEP/STL (CadQuery `build_fuss.py`). Freistellen lokal mit ISNet-Modell (`segment.py`). Anleitung `ANLEITUNG.md`. |
| `A:\LumaCut\Materialtest`, `Einmesstest` | Testmuster und Anleitungen für Kalibrier-Läufe |
| `A:\LumaCut\Gehaeuse-SKR-Mini-MZ` | Gehäuse für das SKR-Board |
| `A:\LumaCut\SKR-Firmware` | ältere Firmware-Stände |
| `A:\LumaCut\LumaDeck-Garmin` | eigenes Projekt: Garmin nüvi 150 als USB-Tastenfeld (nichts mit dem Laser zu tun) |

## 14. Pflege dieser Datei

- Bei **jeder** Änderung am Projekt im selben Commit nachziehen: Häkchen in
  §9 setzen, Neues in §8 (Chronik) und §6/§7 (Ist-Stand) eintragen, Datum oben
  ändern.
- Zusätzlich: [CHANGELOG](../CHANGELOG.md) (was, wann, warum) und bei
  Pi-Themen [PI_STATUS_UND_OFFENE_PUNKTE.md](PI_STATUS_UND_OFFENE_PUNKTE.md).
- Ideen des Besitzers sofort unter §12, auch wenn sie „erst später“ kommen.
- Nur Belegtes eintragen; Ungeprüftes als „nicht ausprobiert“ kennzeichnen.
