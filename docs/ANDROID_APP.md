# LumaCut für Android (Tablet)

Native App (Kotlin, Jetpack Compose, Material 3), von Grund auf neu geschrieben. Sie steuert die Maschine über die Pi-API (Port 8080) und ersetzt LightBurn am Tablet. Alle Sicherheitsregeln bleiben auf dem Pi.

## Bereiche

| Bereich | Inhalt |
|---|---|
| **Werkstatt** | Live-Status (1 s), kontextabhängige Hauptaktion (Referenzieren → Abtasten → Parken), Steuerkreuz X/Y/Z mit 0,1/1/10 mm, Parken, Licht/Abluft, Notstopp quittieren, Controller-Meldungen. NOT-AUS ist immer oben rechts. |
| **Aufträge** | Liste vom Pi, Hochladen von `.gcode`, Bahnvorschau (Laser nach Leistung abgestuft, Leerfahrten, erledigter Teil live), Dauer, Laser-/Leerweg, Abtastpunkt per Antippen, Ein-Klick-Start, Fortschritt mit Restzeit, Abbrechen, Löschen. |
| **Editor** | Rechteck, Ellipse, Vieleck, Linie, Freihand, Text (Systemschriften), SVG-Import, Bild-Import (Graustufen/Dither/SW), Ebenen mit Linie/Füllen, Leistung, Tempo, Durchgänge, Zeilenabstand, Überlauf, Material übernehmen, Rückgängig/Wiederholen, Zentrieren, Projekte speichern/öffnen, Kamera-Hintergrund, „An Laser senden“. |
| **Material** | Bibliothek mit Startwerten, eigene Profile anlegen/ändern/löschen. |
| **Einstellungen** | Pi-Adresse, Ansicht (X0/Y0 oben/unten links), Fokus & Taster, SKR-Firmware flashen, Versionsinfo. |

## Aufbau

```
android/
  core/   reines Kotlin (JVM, lokal testbar): PiClient, Toolpath (G-Code-Modell),
          Document/Layer/Element, MarlinWriter (Design → G-Code), SvgImport,
          Geometrie (Schraffur, Wegoptimierung), Homography (Kamera)
  app/    Android-Oberfläche: Screens, ViewModels, Text/Bild/Kamera-Import
```

Prinzipien:
- **Dokumentkoordinaten = Maschinenkoordinaten.** Die Einstellung „X0/Y0 oben/unten links“ ändert nur die Darstellung. Importierte Texte, SVGs und Bilder werden so ausgerichtet, wie sie auf dem Bildschirm stehen.
- Der `MarlinWriter` erzeugt genau, was der Pi annimmt: ein `M3 I`, S in jedem G1, Überlauf mit `G1 … S0` (darf in die Safezone, brennt nie), Schnitte nur ab X/Y 30. Homing, Abtasten, Fokus und Parken macht der Pi. `core` prüft jede erzeugte Zeile in den Tests gegen die Regeln des Pi.

## Bauen und installieren

Die APK baut GitHub Actions (`.github/workflows/android.yml`) bei jeder Änderung unter `android/`: erst die Kern-Tests, dann `assembleRelease`. Die Datei `LumaCut-1.0.<Nr>.apk` liegt 30 Tage im Lauf unter **Artifacts**.

Installation auf dem Tablet: APK herunterladen, öffnen, „Installation aus unbekannten Quellen“ für den Browser oder Dateimanager erlauben.

**Signatur:** Ohne Secrets signiert die CI mit einem Wegwerf-Schlüssel. Dann muss vor jedem Update deinstalliert werden. Für Updates ohne Neuinstallation einmalig in GitHub unter *Settings → Secrets and variables → Actions* anlegen:
- `ANDROID_KEYSTORE_B64`: Keystore (Alias `lumacut`) als Base64
- `ANDROID_KEYSTORE_PASSWORD`: Passwort des Keystores

Lokal: `core` testen geht mit JDK 17+ und Gradle (`gradle :core:test` im Ordner `android`). Für die App braucht es Android SDK 35.

## Erste Schritte am Tablet

1. Einstellungen → IP des Pi (z. B. `192.168.2.89`) → Verbinden.
2. Einstellungen → Ansicht so wählen, dass die Fläche aussieht wie die Maschine von vorn.
3. Werkstatt → Referenzieren. Dann im Editor gestalten → An Laser senden → Aufträge → Ein-Klick-Start.
4. Optional Kamera: Editor → Kamera → Kalibrier-Rechteck an Laser senden und lasern, dann Foto, vier Marker auf die nummerierten Ecken ziehen, Übernehmen.

## Grenzen der ersten Version

- Bilder lassen sich nicht drehen (Position und Größe schon).
- Texte werden beim Einfügen in Konturen umgewandelt. Zum Ändern neu einfügen.
- Der Kamera-Hintergrund nutzt die Tablet-Kamera. Eine Kamera am Laserkopf (Kachel-Scan über den Pi) folgt später.
- Rastergravur: Der Pi schickt eine Zeile pro `ok`. Wie schnell feine Graustufen damit laufen, muss an der Maschine gemessen werden.
