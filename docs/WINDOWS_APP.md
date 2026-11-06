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
