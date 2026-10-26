# LumaCut für Android (Tablet)

Native App (Kotlin, Jetpack Compose, Material 3), von Grund auf neu geschrieben. Sie steuert die Maschine über die Pi-API (Port 8080) und ersetzt LightBurn am Tablet. Alle Sicherheitsregeln bleiben auf dem Pi.

## Bedienung: drei Schritte

Die Leiste links führt durch den Hauptweg, mehr braucht ein Neuling nicht:

| Schritt | Inhalt |
|---|---|
| **1 · Material** | Liste aus der Pi-Datenbank (`/api/materials`, gleiche Liste wie Windows-App und Web-Oberfläche), mit Suche. Antippen setzt Leistung, Tempo, Durchgänge und Z-Absenkung der Ebenen Gravieren / Markieren / Schneiden. Ohne Verbindung gilt die zuletzt gespeicherte Liste (nur lesbar). Unter „Erweitert“ lassen sich Materialwerte ändern, anlegen und löschen (`base_revision`, bei 409 wird neu geladen). |
| **2 · Motiv** | Bild, SVG/DXF importieren, Text und Formen; verschieben, drehen, skalieren. Eine einzige Laserwahl: Gravieren, Markieren oder Schneiden (Werte kommen vom Material). Bilder landen automatisch auf Gravieren. „Arbeitsplatz scannen“ ist ein einzelner optionaler Knopf; „Mehr“ enthält Gruppen, Mehrfachauswahl, Materialtest und Projekte. Ebenen und Laserwerte je Ebene stehen unter „Erweitert“. |
| **3 · Starten** | Vorschau, Material, Laserzeit und Größe; „Rahmen zeigen“ (Laser aus, referenziert vorher selbst) und ein Knopf **Starten**. Die App baut den Auftrag ohne Höhenmesh, lädt ihn hoch und startet `op=autorun`. Der Pi referenziert bei Bedarf, tastet ab, korrigiert die Höhe, lasert und parkt. Fortschritt aus `/api/status`: `job.state` (homing, probing, running, complete, error) und `job.probe {done,total}`. Fehler erscheinen in einem Satz mit nächstem Schritt. Starten sperrt, bis der Pi `autorun_mesh` meldet. |

**Neu im Motiv-Schritt (2026-10-26):**

| Knopf | Was er tut |
|---|---|
| **Importieren** | Ein Knopf für alles, das Format wird am Inhalt erkannt: SVG, DXF, xTool Studio `.xs` (ZIP), xTool Creative Space `.xcs`, LightBurn `.lbrn`/`.lbrn2`, HPGL `.plt`/`.hpgl` (40 Einheiten/mm), PDF und Illustrator `.ai` (erste Seite über `PdfRenderer` als Bild), Bilder (PNG, JPG, WebP, BMP, GIF, HEIC soweit Android sie liest), LumaCut-Projekt. Unbekanntes Format: ein Satz mit der Liste der unterstützten. Nicht lesbare Elemente (z. B. Text in `.xcs`/`.lbrn`) werden übersprungen und in einem Satz genannt. xTool-Dateien (`.xs`: `project.json`, `canvases/<id>.json`, alle `displays-N.json`; `.xcs`: dieselben Displays als JSON) werden mit den Transformationen des xTool-Editors platziert (lokales Skew, Umriss auf 0/0, Skalierung/Skew/Drehung, dann x/y; Skew π mit lokalem Skew π heben sich auf, x/y ist dann die Unterkante). Pfade, Rechtecke, Kreise, Bilder (Base64 oder Datei im ZIP) und Text, sofern Pfaddaten da sind; je xTool-Farbe eine eigene Ebene (Name = Farbe, Reihenfolge aus der Datei; Linien nehmen die Werte von Schneiden, Füllungen die von Gravieren, beide aus dem gewählten Material), Gruppen der Datei werden unsere äußersten Gruppen. An der Beispieldatei mit zwei Tablet-Ständern geprüft (Flex-Muster liegt in den Ständern, Linien ragen höchstens ca. 2 mm über die Kontur); `.xcs` nur mit selbst erzeugten Dateien.

**Originalgröße:** Vektor- und Projektimporte werden nie verkleinert. Was nicht als Ganzes in 360 × 340 mm passt, wird gruppenweise in Reihen angeordnet (5 mm Abstand, ohne Drehen). Passt auch das nicht: Dialog „Nur Teile nehmen, die passen“ / „Verkleinern auf X %“ / „Abbrechen“. Bilder dürfen weiter skaliert werden. |
| **Importierte Dateien** | Jeder Import legt Einzelteile an, die zusammen eine Gruppe bilden: eine äußere geschlossene Kontur mit den Löchern darin (Buchstabe O, Ring, Teil mit Bohrung) ist ein Teil, ein offener Pfad ist ein Teil, ein Bild bleibt ein Element, Text bleibt ein Element. „Gruppe auflösen“ (Mehr) macht die Teile einzeln wählbar, „Gruppieren“ fasst sie wieder zusammen. Mehr als 500 Teile: ein Element mit Hinweis. |
| **Kontur** | Bild: Hintergrund erkennen (Transparenz, sonst Randfarbe per Flood-Fill, Toleranz einstellbar), nur Außenkontur, Teile je eine Kontur oder verbunden; „Sticker“ (Rand 1–10 mm nach außen, runde Ecken, kleine Lücken geschlossen) oder „Am Rand entlang“ (optional 0,2 mm Einzug). Vorschau, dann Übernehmen: Bild auf Gravieren, Kontur auf Schneiden, gruppiert; oder „Nur Kontur“. Vektoren und Text: Umriss −10…+10 mm. Rechnung: Rastermaske (6 px/mm), Distanzfeld, Marching Squares, Glätten, Vereinfachen auf 0,05 mm, nur Linien (keine G2/G3). |
| **Bild anpassen** (in der Auswahl) | Dithering Floyd-Steinberg, Jarvis, Stucki, S/W, Graustufen; Helligkeit, Kontrast, Schärfe, Invertieren mit Vorschau dessen, was gelasert wird. |
| **QR-Code** | Text/URL, Stufe M, Version 1–10 (bis 213 Byte), gefüllte Rechtecke auf Gravieren; Warnung unter 0,8 mm Punktgröße. Intern gegen Reed-Solomon-Beispiel, Format-BCH und Rücklesen der Codewörter geprüft, aber noch nicht mit einem echten Scanner. |
| **Formen** | Herz, Stern, abgerundetes Rechteck, Anhänger mit Loch. |
| **Mehr** | Vervielfältigen als Raster (Anzahl, Abstand; Kopien außerhalb des Arbeitsbereichs entfallen), Mehrfachauswahl, Gruppen, Materialtest, Projekte. Text-Dialog: „Auf dem Bogen“ (Radius, minus = unten). |

Unter **Maschine** liegt alles Übrige: Steuerung (Status, Steuerkreuz, Referenzieren, Abtasten, Parken, Licht/Abluft, Notstopp quittieren), Arbeitsplatz scannen (Kopfkamera kalibrieren, Mosaik, Werkstücke markieren, Höhenmesh, geführter Ablauf – nur für Fachleute) und die Auftragsliste des Pi. **Einstellungen**: Pi-Adresse, Fokus & Taster, SKR-Firmware, Version. NOT-AUS ist immer oben rechts.

## Verbindung zum Laser

Die App sucht und wechselt **nie** von selbst. Die gespeicherte Adresse wird beim Start einfach benutzt. Unter Einstellungen → **Laser**: aktuelle Adresse mit Zustand, „Laser suchen“ (fragt parallel alle Adressen des eigenen /24-Netzes auf Port 8080 mit `GET /api/status`, ca. 3 s, zeigt nur Geräte, die wie ein LumaCut-Pi antworten: Adresse, Name, Zustand; Antippen speichert und verbindet) und das Feld „Adresse eingeben“. Berechtigungen: INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, kein Standort; nur lokale IPv4.

Ruhige Statusabfrage: höchstens eine Anfrage zugleich, alle 1,5 s, 5 s Zeitlimit, „offline“ erst nach 3 Fehlschlägen in Folge. Läuft ein Auftrag und die Verbindung reißt ab, kommt nur der Hinweis „Verbindung zum Pi kurz weg – der Auftrag läuft auf dem Pi weiter“. Die App schickt nach einem Abriss nie von selbst abort, start oder park.

## Licht

Werkstatt → Zubehör: Schalter und darunter ein Helligkeitsregler 1–100 % (gesendet erst beim Loslassen, `op=light` mit `on=1` und `brightness`; Wert aus `light_brightness` im Status). Der Regler erscheint nur, wenn `light_dimmable` nicht `false` ist. Einstellungen → Licht: Schalter „Lichteffekte“ (`effects=1|0`); bei alter Firmware der Hinweis „Für Dimmen und Lichteffekte die neue Firmware flashen.“ `PiClient.light(on, brightness, effects)`.

## Updates

Die App holt neue Versionen vom Pi, ohne Deinstallieren. Der Pi (`features` enthält `app_update`) lädt die APK aus dem GitHub-Release und liefert sie unter `GET /api/app/android` (Metadaten) und `GET /api/app/android.apk`. Die App fragt beim Start und danach alle 6 h nach (nie während ein Auftrag läuft) und zeigt bei höherem `version_code` einen ruhigen Hinweis „Update 1.0.N verfügbar“ auf dem Startbildschirm. Einstellungen → **App-Update** zeigt installierte und angebotene Version, „Jetzt prüfen“ (`op=app_update_check`, der Pi schaut sofort auf GitHub) und „Aktualisieren“.

Aktualisieren lädt die APK mit Fortschrittsanzeige in den Cache, prüft Größe und SHA-256 gegen die Metadaten (bei Abweichung wird die Datei verworfen) und übergibt sie einer PackageInstaller-Sitzung. Android fragt dann einmal nach der Bestätigung; stilles Installieren gibt es nicht. Fehlt die Erlaubnis „Unbekannte Apps installieren“, führt ein Satz einmal in die Systemeinstellung. Während eines Auftrags wird nichts geprüft und nichts installiert.

Wichtig: Ein Update lässt sich nur über eine APK installieren, die mit **demselben Schlüssel** signiert ist. Die erste Installation nach dem Umstieg auf den festen Schlüssel (Secret `ANDROID_KEYSTORE_B64`) braucht deshalb noch einmal Deinstallieren der alten, mit einem Wegwerf-Schlüssel signierten App (die Einstellungen und Entwürfe gehen dabei verloren). Danach reicht Aktualisieren.

## Aufbau

```
android/
  core/   reines Kotlin (JVM, lokal testbar): PiClient, Toolpath (G-Code-Modell),
          Document/Layer/Element, MarlinWriter (Design → G-Code), SvgImport,
          Geometrie (Schraffur, Wegoptimierung), Homography (Kamera)
  app/    Android-Oberfläche: Screens, ViewModels, Text/Bild/Kamera-Import
```

Prinzipien:
- **Arbeitsbereich 360 × 340 mm, Nullpunkt oben links, Y nach unten – so, wie man die Maschine von der Tür aus sieht.** Die Endschalter-Ecke (Maschine 0/0) liegt von dort hinten rechts: X+ fährt nach links, Y+ zur Tür. Umrechnung nur in `Work.toMachine`/`Work.fromMachine`: `maschine_x = 390 − x`, `maschine_y = 30 + y` (Drehung um 180°, keine Spiegelung, Text wird lesbar gelasert; `docs/ZUSAMMENARBEIT_CLAUDE_GROK.md` Abschnitt 2). Der 30-mm-Rand der Maschine (Safezone, oben und rechts auf dem Bildschirm) gehört dem Laser (Referenzieren, Parken) und ist unsichtbar. Rasterbilder: Spalte 0 liegt links auf dem Bildschirm, also bei großem Maschinen-X. Steuerkreuz: links = X+, unten = Y+.
- **Schneidreihenfolge:** Auf Linien-Ebenen werden innere Konturen und Linien vor den Konturen geschnitten, die sie umschließen (Ebenenhöhe der Verschachtelung, innerhalb einer Stufe nächster Nachbar), damit Teile nicht vor den Innenschnitten herausfallen.
- Der `MarlinWriter` erzeugt genau, was der Pi annimmt: ein `M3 I`, S in jedem G1, Überlauf mit `G1 … S0`. Jeder Punkt, auch der Überlauf, bleibt im Arbeitsbereich – nie in der Safezone. Elemente lassen sich nicht über den Rand schieben. Homing, Abtasten, Fokus und Parken macht der Pi. `core` prüft jede erzeugte Zeile in den Tests gegen die Regeln des Pi.
- **Höhenkorrektur im Hauptweg macht der Pi** (Abtastraster je Motivbereich, tiefster Punkt zuletzt, Fokus folgt der Oberfläche). Die App schickt den Auftrag ohne absolutes Z; nur die relativen Fokus-Absenkungen je Durchgang (`G91 / G0 Z-… / G90`) bleiben darin. Die Mesh-Abtastung und `FocusCompensation` in der App bleiben unter Maschine → Arbeitsplatz für Fachleute (Start mit `op=start`).

## Bauen und installieren

Die APK baut GitHub Actions (`.github/workflows/android.yml`) bei jeder Änderung unter `android/`: erst die Kern-Tests, dann `assembleRelease`. Die Datei `LumaCut-1.0.<Nr>.apk` liegt 30 Tage im Lauf unter **Artifacts**.

Installation auf dem Tablet: APK herunterladen, öffnen, „Installation aus unbekannten Quellen“ für den Browser oder Dateimanager erlauben.

**Signatur:** Ohne Secrets signiert die CI mit einem Wegwerf-Schlüssel. Dann muss vor jedem Update deinstalliert werden. Für Updates ohne Neuinstallation einmalig in GitHub unter *Settings → Secrets and variables → Actions* anlegen:
- `ANDROID_KEYSTORE_B64`: Keystore (Alias `lumacut`) als Base64
- `ANDROID_KEYSTORE_PASSWORD`: Passwort des Keystores

Lokal: `core` testen geht mit JDK 17+ und Gradle (`gradle :core:test` im Ordner `android`). Für die App braucht es Android SDK 35.

## Erste Schritte am Tablet

1. Einstellungen → IP des Pi (z. B. `192.168.2.89`) → Verbinden.
2. Material wählen → Motiv gestalten → Starten. Mehr nicht.
3. Optional: „Arbeitsplatz scannen“ (Motiv-Seite) legt ein Foto der Arbeitsfläche als Hintergrund.
4. Kopfkamera einmalig: Maschine → Arbeitsplatz scannen → Kalibrieren → Rechteck lasern → Kopf darüber → Kamerabild → vier Marker auf die Ecken → Speichern. Die Kamera hängt per USB am Pi (`LUMACUT_CAMERA`, Standard `/dev/video0`).
5. Ohne Kopfkamera: Editor → Kamera → Kalibrier-Rechteck lasern, mit dem Tablet fotografieren, Marker setzen.

## Grenzen der ersten Version

- Bilder lassen sich nicht drehen (Position und Größe schon) – die Rastergravur läuft zeilenweise.
- Projekte aus der ersten App-Version (Maschinenkoordinaten) erscheinen um 30 mm verschoben; einmal zurechtrücken.
- Seit der Drehung um 180° (2026-10-26) sind frühere Kopfkamera-Kalibrierungen ungültig (gespiegeltes X) und werden verworfen: einmal neu kalibrieren. Projekte bleiben in Bildschirmkoordinaten, erscheinen also unverändert; nur der erzeugte G-Code liegt jetzt spiegelverkehrt zu früher (richtig herum).
- Texte werden beim Einfügen in Konturen umgewandelt. Zum Ändern neu einfügen.
- Der Kachel-Scan braucht eine USB-Kamera am Kopf, die der Pi als v4l2-Gerät sieht. Bis eine angeschlossen ist, ist der Scan nur in Tests geprüft.
- Rastergravur: Der Pi schickt eine Zeile pro `ok`. Wie schnell feine Graustufen damit laufen, muss an der Maschine gemessen werden.
