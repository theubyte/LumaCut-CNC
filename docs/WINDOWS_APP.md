# LumaCut Studio für Windows: Aufbau, Design, Regeln

Neu gebaut unter `software/lumacut-windows` (Zweig `windows-app`). Die alten Stände
`software/lumacut-studio` (kleines Tauri-Muster) und `software/lumacut-studio-native` (PySide6)
sind überholt und werden nicht weiterentwickelt.

## Warum neu und warum dieser Technik-Stack

- **Tauri 2 + React + TypeScript, Oberfläche im WebView2.** Klein (MSI ca. 5 MB statt 150 MB beim
  alten PySide-Stand), startet schnell, zeichnet flüssig (Canvas), sieht auf großen Monitoren und
  Laptops gleich aus. Die Oberfläche lässt sich echt mit Screenshots prüfen, auch in CI.
- **Rust nur als dünne Hülle:** Pi-Verbindung (ohne CORS/Origin-Sperre, nur Heimnetz), Schriften,
  Update, MSI per WiX. Keine Maschinenlogik auf dem PC.
- **Der Pi bleibt die Zentrale.** Grenzen, Kalibrierungen, Materialien, Projekte liegen dort.
- **Projektdatei wie Android.** `src/core/model.ts` entspricht `Design.kt`; Projekte gehen über den
  Pi zwischen Tablet und PC hin und her. Zusätze nur als optionale Felder.

## Informationsarchitektur

Linke Leiste, gleiche Wörter und Reihenfolge wie die Android-App, dazu zwei neue Bereiche:

| Strg | Bereich | Inhalt |
|---|---|---|
| 1 | **Material** | Materialbibliothek des Pi, Wahl des aktuellen Materials, Prozesse (Gravieren, Markieren, Schneiden), Tonkurve |
| 2 | **Motiv** | Design-Editor: Werkzeuge links, Arbeitsfläche Mitte, Ebenen und Eigenschaften rechts, Platten unten |
| 3 | **Starten** | Vorschau mit Zeitschätzung und Prüfungen, Rahmen, Start mit Freigabe, laufender Auftrag, Warteschlange, gespeicherte Aufträge |
| 4 | **Platine** | PCB: Gerber/Excellon, Isolationsbahnen, Lötstopp, Spiegeln, Passmarken, Prozess-Assistent |
| 5 | **Werkstatt** | Assistenten und Generatoren: Materialtest, Fotogravur, Stempel, Seriennummern, Boxen, QR, Vorlagen |
| 6 | **Maschine** | Steuerung (Jog, Referenz, Abtasten, Licht, Abluft), Kamera, Kalibrieren, System (Firmware, Pi, Verbindung) |
| | **Optionen** | Pi-Adresse, Hell/Dunkel, Update, Über |

Immer sichtbar: Kopfzeile mit Verbindungsstatus und **NOT-AUS** (auch über jedem Dialog, Taste
**Pause**), bei laufendem Auftrag darunter ein Fortschrittsstreifen mit Abbrechen, unten die
Statuszeile mit Position.

## Designsystem

Quelle: `src/ui/tokens.css`, `src/ui/base.css`, `src/ui/kit.tsx`. Farben aus der Familie der
Android-App (Indigo-Akzent auf ruhigen Flächen), hell und dunkel. Schrift Segoe UI Variable, Zahlen
tabellarisch, Maschinenwerte in Cascadia Mono.

Regeln für jede Ansicht:
1. Keine freien Farben, Abstände oder Schriftgrößen: nur Tokens und Kit-Bausteine.
2. Eine Primäraktion je Ansicht; Rot nur für Laser-Start, Löschen und NOT-AUS.
3. Hierarchie durch Abstand und Schrift, nicht durch Rahmen in Rahmen. Karten nicht verschachteln.
4. Dichte für Maus und Tastatur: Bedienelemente 30 px, Basisschrift 13 px. Jede häufige Funktion hat
   ein Tastenkürzel, das im Tooltip steht.
5. Zahlenfelder: Enter übernimmt, Pfeile verändern, Komma und Punkt gehen, Einheit im Feld.
6. Leere Zustände sagen, was als Nächstes zu tun ist. Fehler sind ein Satz mit dem nächsten Schritt.
7. Funktioniert von 1000 × 640 bis 4K. Panels scrollen, das Fenster nicht.
8. Keine fremde Software nachbilden: eigene Bedienung, eigene Gestaltung.

## Sicherheit in der App

- `src/pi/actions.ts` ist der einzige Weg zu Maschinenaktionen. Jede Fahr- und Laseraktion geht durch
  den Go-Dialog (Hände raus, Deckel zu, Brille); Enter löst ihn nicht aus. Ausnahmen: einzelne
  Jog-Schritte, Licht, Abluft, Abbrechen, NOT-AUS. Unbekannte `op` werden abgelehnt.
- Service-Funktionen, die den Laser direkt zünden, bietet die App nicht an.
- Entwicklung nur gegen den Simulator `tools/sim_pi.py` (der echte `web.py` mit simuliertem Controller).

## Entwickeln

```bash
cd software/lumacut-windows
npm install
python tools/sim_pi.py   # braucht flask und pyserial
npm run dev              # http://localhost:5183, /api geht an den Simulator
npm test                 # Kern-Tests
npm run shots            # Screenshots aller Ansichten nach tests/e2e/screenshots
npx tauri build          # MSI
```

Das echte App-Fenster prüfen (immer gegen den Simulator):
`node tests/tauri/real.mjs src-tauri/target/release/lumacut-studio.exe http://127.0.0.1:8090`.
Die CI macht das mit der installierten MSI.

## Stand der ersten Etappe (06.11.2026)

Nichts davon lief bisher an der echten Maschine. Vom echten Pi wurde nur `/api/status` gelesen.

**Fertig und gegen den Simulator oder Kotlin geprüft**
- G-Code zeichengenau wie Android (Golden-Dateien aus dem echten Kotlin-Code, 2000 Zufallsprojekte).
  Projektformat in beide Richtungen zwischen Kotlin und TypeScript geprüft.
- Maschine: Status, Referenz, Jog mit Tastatur, Abtasten, Parken, Fahren, Licht, Abluft, Ursprung,
  Bettkarte, NOT-AUS mit Quittieren, Kamera-Live-Bild, System-Anzeige, Backup.
- Material: Bibliothek vom Pi, Prozesse, Verwenden.
- Motiv: Formen, Text mit Systemschriften, Stift und Knoten mit Bézier-Griffen, Ebenen, Boolesche
  Operationen, Kontur, Ausrichten, Spiegeln, Platten, Bilder mit Dithering, Vektorisieren, Import, Export.
- Starten: Vorschau mit Abspielen, Zeitschätzung, Prüfungen, Rahmen, Start mit Go, Warteschlange, Aufträge.
- Werkstatt: Materialtest-Raster, Fotogravur, Stempel, Box, Zahnrad, Lineal, Maßstab, Rahmen, QR,
  Seriennummern, Schachteln (Rechteck-Regal), vier Vorlagen.
- Platine: Gerber und Excellon, Isolationsbahnen und Negativ-Raster, Lötstopp, Bohrmarken, Beschriftung,
  Spiegeln, Passmarken, Prüfung gegen die Strahlbreite, Assistent.

**Begonnen oder eingeschränkt**
- Kalibrier-Assistenten nur für Bewegung, Bettkarte und Materialtest; Kamera, Licht, Taster, Fokus zeigen
  den Stand und verweisen aufs Tablet.
- Arbeitsplatz-Scan läuft nur am Tablet; das Scanbild erscheint am PC als Hintergrund, aber Einmessen und
  Platzieren per Kamera fehlen.
- Einstellungen auf dem Pi (Gerätename, Abluft-Automatik) nur als Anzeige. Firmware nur als Anzeige.
- Materialtest mit Kamera kommt an zwei Stellen vor (Werkstatt, Kalibrieren).
- Schachteln nur nach Umriss-Rechtecken. Platine: je Seite ein Durchgang, zweite Seite von Hand;
  große Platinen rechnen ohne Worker (frieren einige Sekunden).
- PDF: nur Seite 1, Text und Bilder im Vektor-PDF werden gemeldet, nicht übernommen.

**Nicht geprüft**
- Echte Maschine, echtes Lasern und Ätzen, alle Startwerte für Platinen.
- Erfolgreicher Materialtest-Lauf mit Ergebnisanzeige (dem Simulator fehlt das Kamerafoto).
- Echte Dateien aus LightBurn, xTool, KiCad, EasyEDA: nur mit nachgebauten Testdaten.
- Auto-Update von Version zu Version (Code steht, ein echter Sprung steht aus).

**Nächste Etappen**
1. Am echten Pi mit dem Besitzer vor Ort: lesen, Verbinden, Referenz, Jog, dann ein kleiner Auftrag auf Testmaterial.
2. Arbeitsplatz-Scan und Platzierung per Kamera, restliche Kalibrier-Assistenten.
3. Pi-Einstellungen bearbeiten, Firmware-Anzeige mit Update vor Ort.
4. Platine: Rechnen im Worker, beidseitiger Ablauf, reale Testplatine mit Materialtest auf Lack.
5. Schachteln nach echter Kontur, gedrehte Bilder.
6. Code-Signing, wenn der Besitzer ein Zertifikat kauft.

Rotary gibt es hardwareseitig nicht (`docs/MASCHINE.md`), daher nur ein Hinweis in der App.
