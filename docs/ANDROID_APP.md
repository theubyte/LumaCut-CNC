# LumaCut für Android (Tablet)

Native App (Kotlin, Jetpack Compose, Material 3), von Grund auf neu geschrieben. Sie steuert die Maschine über die Pi-API (Port 8080) und ersetzt LightBurn am Tablet. Alle Sicherheitsregeln bleiben auf dem Pi.

## Bedienung: drei Schritte

Die Leiste links führt durch den Hauptweg, mehr braucht ein Neuling nicht:

| Schritt | Inhalt |
|---|---|
| **1 · Material** | Liste aus der Pi-Datenbank (`/api/materials`, gleiche Liste wie Windows-App und Web-Oberfläche), mit Suche. Antippen setzt Leistung, Tempo, Durchgänge und Z-Absenkung der Ebenen Gravieren / Markieren / Schneiden. Ohne Verbindung gilt die zuletzt gespeicherte Liste (nur lesbar). Unter „Erweitert“ lassen sich Materialwerte ändern, anlegen und löschen (`base_revision`, bei 409 wird neu geladen). |
| **2 · Motiv** | Bild, SVG/DXF importieren, Text und Formen; verschieben, drehen, skalieren. Eine einzige Laserwahl: Gravieren, Markieren oder Schneiden (Werte kommen vom Material). Bilder landen automatisch auf Gravieren. „Arbeitsplatz scannen“ ist ein einzelner optionaler Knopf; „Mehr“ enthält Gruppen, Mehrfachauswahl, Materialtest und Projekte. Ebenen und Laserwerte je Ebene stehen unter „Erweitert“. |
| **3 · Starten** | Vorschau, Material, Laserzeit und Größe; „Rahmen zeigen“ (Laser aus, referenziert vorher selbst) und ein Knopf **Starten**. Die App baut den Auftrag ohne Höhenmesh, lädt ihn hoch und startet `op=autorun`. Der Pi referenziert bei Bedarf, tastet ab, korrigiert die Höhe, lasert und parkt. Fortschritt aus `/api/status`: `job.state` (homing, probing, running, complete, error) und `job.probe {done,total}`. Fehler erscheinen in einem Satz mit nächstem Schritt. Starten sperrt, bis der Pi `autorun_mesh` meldet. |

Unter **Maschine** liegt alles Übrige: Steuerung (Status, Steuerkreuz, Referenzieren, Abtasten, Parken, Licht/Abluft, Notstopp quittieren), Arbeitsplatz scannen (Kopfkamera kalibrieren, Mosaik, Werkstücke markieren, Höhenmesh, geführter Ablauf – nur für Fachleute) und die Auftragsliste des Pi. **Einstellungen**: Pi-Adresse, Fokus & Taster, SKR-Firmware, Version. NOT-AUS ist immer oben rechts.

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
