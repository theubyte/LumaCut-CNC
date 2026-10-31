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
| Kopf-Konstruktion (CAD) | `A:\mfw\zmount\v6\build_kopf_v6.py` (CadQuery, erzeugt STEP/STL/Vorschaubilder), auch auf dem NAS unter `Export\kopf_v6`; ältere Stände `v5`, Idee des Besitzers `A:\mfw\zmount\in\new_laser_head.step` |
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
- App-Arbeitsfläche: Nullpunkt oben links wie von der Tür gesehen;
  `Maschine X = 390 − x`, `Maschine Y = y + 30`.
- **Seit 31.10. (Pi):** Fahrwege **X 370 / Y 360** (Besitzer mit den
  Steuerkreuzen bis an die Enden gefahren, Pi-Einstellung `travel_x_mm`/
  `travel_y_mm`). Statt der 30-mm-L-Zone gilt nur noch die **Park-Ecke
  X0–78 / Y0–35** (Kopf v6 laut `build_kopf_v6.py`: 67 mm in +X, 24 mm in +Y
  vom Strahl, +10 mm); überall sonst darf gelasert werden. Weboberfläche
  zeigt das so. **Offen:** Android-App rechnet noch mit der alten Fläche
  (Arbeits-0/0 = Maschine X390/Y30, L-Zone); Bettkarte und Abtastraster
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
- **Android-App 1.0.49** (auf dem Pi bereit): Editor mit Ebenen,
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
  **Am 31.10. an der Maschine geprüft:** Verbinden, Referenzfahrt (sauber
  hinten rechts), Fahrt auf X100/Y100 (Richtung stimmt). **Laser:** am
  „+12V“-Ausgang des Boards (gibt 24 V durch) zündete er nur bei wenig
  Leistung oder gar nicht, das Board verlor dabei auch die USB-Verbindung.
  Lösung: **Laser über die LaserTree-Adapterplatine direkt am 24-V-Netzteil**,
  vom Board nur TTL (+ Signal, − Masse). Danach Leistungstest 30–100 % alle
  Stufen sauber (31.10., 11:03), USB ohne Fehler. **Testkreis Ø 20 mm in
  MDF 3 mm (300 mm/min, 100 %, 2×) durch und fällt raus (11:05).** Die Brücke fragt verlorene
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
      Kurzschluss. Bereit liegt die
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
- Bettkarte in der App anzeigen; Materialstärke mit der Bettkarte prüfen.
- Später: Windows-Studio nach dem Vorbild der Android-App neu bauen.
- Weitere Pi-Punkte: [PI_STATUS_UND_OFFENE_PUNKTE.md §4](PI_STATUS_UND_OFFENE_PUNKTE.md#4-offene-punkte).

## 11. Offene Fragen und Messungen

- Abstand Tasterspitze ↔ Düsenspitze mit Hut (Besitzer misst).
- Realer Y-Weg (alt ~350 statt 370) und X-Weg mit v6.
- Kopftiefe in Y für die Breite des Parkbands.
- Einladungskarte Smaragd: Ergebnis der gelaserten Karte noch nicht besprochen.

## 12. Ideen (noch nicht geplant)

- Infrarot-LEDs im Kopfgehäuse als Licht für die Kamera (Besitzer, 30.10.: „erstmal noch nicht“).
- Roter Linienlaser für 3D-Höhenmessung ohne Brennen (Pi-Unterstützung `op=line_laser` existiert).
- X-Motor ans Trägerende verlegen (Riemenschleife), um den Kopf leichter zu machen.
- Weitere Ideen zu Höhe/Kollision: [IDEE_HOEHE_KOLLISION_KAMERA_3D.md](IDEE_HOEHE_KOLLISION_KAMERA_3D.md).

## 13. Nebenprojekte im Ordner

| Ordner | Inhalt |
|---|---|
| `A:\LumaCut\Einladung-Maxim` | Einladungskarte „Smaragd“ (Minecraft-Party). `make_smaragd_laser.py` erzeugt Gravur (Füllfläche) und Schnitt in Endgröße 78,8 × 100 mm. Projekt liegt im Arbeitsstand des Pi. |
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
