# LumaCut für Android (Tablet)

Native App (Kotlin, Jetpack Compose, Material 3), von Grund auf neu geschrieben. Sie steuert die Maschine über die Pi-API (Port 8080) und ersetzt LightBurn am Tablet. Alle Sicherheitsregeln bleiben auf dem Pi.

## Bereiche

| Bereich | Inhalt |
|---|---|
| **Werkstatt** | Live-Status (1 s), kontextabhängige Hauptaktion (Referenzieren → Abtasten → Parken), Steuerkreuz X/Y/Z mit 0,1/1/10 mm, Parken, Licht/Abluft, Notstopp quittieren, Controller-Meldungen. NOT-AUS ist immer oben rechts. |
| **Aufträge** | Liste vom Pi, Hochladen von `.gcode`, Bahnvorschau (Laser nach Leistung abgestuft, Leerfahrten, erledigter Teil live), Dauer, Laser-/Leerweg, Abtastpunkt per Antippen, Ein-Klick-Start, Fortschritt mit Restzeit, Abbrechen, Löschen. |
| **Editor** | Rechteck, Ellipse, Vieleck, Linie, Freihand, Text (Systemschriften), SVG- und DXF-Import, Bild-Import mit DPI aus der Datei (Graustufen/Dither/SW), Mehrfachauswahl (Antippen oder Rahmen), Gruppen, Drehgriff und Eckgriff zum Skalieren, Verschieben in 0,1/1/10 mm, Ebenen sichtbar/gesperrt/lasern, Leistung, Tempo, Durchgänge, Zeilenabstand, Überlauf, Materialstärke mit Tiefe pro Durchgang und Z-Absenkung je Durchgang (max. 3 mm), Material übernehmen, Rückgängig/Wiederholen, Zentrieren, Projekte speichern/öffnen (Autosave), Kamera-Hintergrund per Tablet-Foto, „An Laser senden“ mit Höhenkorrektur. |
| **Arbeitsplatz** | Kopfkamera kalibrieren, Arbeitsfläche scannen (Kachelbilder → maßstäbliches Mosaik), Werkstücke markieren (aus dem Motiv oder Rahmen ziehen), Höhenmesh abtasten, geführter Ablauf Referenzieren → Scannen → Markieren → Abtasten → Fokus → Rahmen → Auftrag → Parken. |
| **Material** | Bibliothek mit Startwerten, eigene Profile mit Tiefe pro Durchgang und Z-Absenkung anlegen/ändern/löschen. |
| **Einstellungen** | Pi-Adresse, Fokus & Taster, SKR-Firmware flashen, Versionsinfo. |

## Aufbau

```
android/
  core/   reines Kotlin (JVM, lokal testbar): PiClient, Toolpath (G-Code-Modell),
          Document/Layer/Element, MarlinWriter (Design → G-Code), SvgImport,
          Geometrie (Schraffur, Wegoptimierung), Homography (Kamera)
  app/    Android-Oberfläche: Screens, ViewModels, Text/Bild/Kamera-Import
```

Prinzipien:
- **Arbeitsbereich 360 × 340 mm, Nullpunkt oben links, Y nach unten** – wie in der Windows-App. Der 30-mm-Rand der Maschine (Safezone) gehört dem Laser (Referenzieren, Parken) und ist in der App unsichtbar. Maschine = Arbeitsbereich + 30 mm; umgerechnet wird nur in `Work.toMachine`/`Work.fromMachine`.
- Der `MarlinWriter` erzeugt genau, was der Pi annimmt: ein `M3 I`, S in jedem G1, Überlauf mit `G1 … S0`. Jeder Punkt, auch der Überlauf, bleibt im Arbeitsbereich – nie in der Safezone. Elemente lassen sich nicht über den Rand schieben. Homing, Abtasten, Fokus und Parken macht der Pi. `core` prüft jede erzeugte Zeile in den Tests gegen die Regeln des Pi.
- **Höhenkorrektur:** Mit Höhenmesh bekommt jedes höchstens 2 mm lange Laserstück sein eigenes Z (Oberfläche + Fokusabstand − Schalter→Spitze, nie näher als 2 mm). Der tiefste Punkt wird zuletzt angetastet, damit die Z-Sperre des Pi (Oberfläche + 2 mm) für alle Höhen passt. Aufträge mit eigenem Z überspringen den automatischen Einzelfokus des Pi; der Pi prüft absolute Z-Ziele ohne den Planer anzuhalten.

## Bauen und installieren

Die APK baut GitHub Actions (`.github/workflows/android.yml`) bei jeder Änderung unter `android/`: erst die Kern-Tests, dann `assembleRelease`. Die Datei `LumaCut-1.0.<Nr>.apk` liegt 30 Tage im Lauf unter **Artifacts**.

Installation auf dem Tablet: APK herunterladen, öffnen, „Installation aus unbekannten Quellen“ für den Browser oder Dateimanager erlauben.

**Signatur:** Ohne Secrets signiert die CI mit einem Wegwerf-Schlüssel. Dann muss vor jedem Update deinstalliert werden. Für Updates ohne Neuinstallation einmalig in GitHub unter *Settings → Secrets and variables → Actions* anlegen:
- `ANDROID_KEYSTORE_B64`: Keystore (Alias `lumacut`) als Base64
- `ANDROID_KEYSTORE_PASSWORD`: Passwort des Keystores

Lokal: `core` testen geht mit JDK 17+ und Gradle (`gradle :core:test` im Ordner `android`). Für die App braucht es Android SDK 35.

## Erste Schritte am Tablet

1. Einstellungen → IP des Pi (z. B. `192.168.2.89`) → Verbinden.
2. Werkstatt → Referenzieren. Dann im Editor gestalten → An Laser senden → Aufträge → Ein-Klick-Start.
3. Oder Arbeitsplatz → geführter Ablauf: Scannen, Werkstücke markieren, Höhenmesh, Rahmen, Starten, Parken.
4. Kopfkamera einmalig: Arbeitsplatz → Kalibrieren → Rechteck lasern → Kopf darüber → Kamerabild → vier Marker auf die Ecken → Speichern. Die Kamera hängt per USB am Pi (`LUMACUT_CAMERA`, Standard `/dev/video0`).
5. Ohne Kopfkamera: Editor → Kamera → Kalibrier-Rechteck lasern, mit dem Tablet fotografieren, Marker setzen.

## Grenzen der ersten Version

- Bilder lassen sich nicht drehen (Position und Größe schon) – die Rastergravur läuft zeilenweise.
- Projekte aus der ersten App-Version (Maschinenkoordinaten) erscheinen um 30 mm verschoben; einmal zurechtrücken.
- Texte werden beim Einfügen in Konturen umgewandelt. Zum Ändern neu einfügen.
- Der Kachel-Scan braucht eine USB-Kamera am Kopf, die der Pi als v4l2-Gerät sieht. Bis eine angeschlossen ist, ist der Scan nur in Tests geprüft.
- Rastergravur: Der Pi schickt eine Zeile pro `ok`. Wie schnell feine Graustufen damit laufen, muss an der Maschine gemessen werden.
