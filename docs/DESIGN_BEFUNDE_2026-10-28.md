# Android-App: Design-Überarbeitung und Befunde (2026-10-28)

Ziel: sauber, modern, geordnet und praktisch, angelehnt an zwei Referenzen –
einen hellen Grundriss-Editor (gepunktete Fläche, schmale weiße Werkzeugleiste,
schwebende Info-Karte, schwarze Kontext-Pille, blauer Hauptknopf) und ein
Lavendel/Weiß-Dashboard (runde Icon-Navigation mit Beschriftung, weiche Karten,
Schalter, Ringanzeige). Geprüft wurde jede Seite als Nutzer und als Neuling, auf
Tablet und Handy, hoch und quer, hell und dunkel.

Vorher/Nachher-Screenshots rendert der Workflow „LumaCut Android Screenshots“
(Robolectric + Roborazzi, `android/app/src/test/.../ScreenshotTest.kt`). Die PNGs
liegen als Artefakt am Lauf und auf den Branches `screenshots-design-vorher`
(altes Design) und `screenshots-main` (neues Design).

## Befunde am alten Design

Kritisch (Sicherheit/Bedienbarkeit):

1. **NOT-AUS fehlte auf dem Handy.** Die Kopfzeile lief über den Rand, der rote
   Knopf war im Hochformat gar nicht zu sehen.
2. **Editor auf dem Handy unbenutzbar.** Werkzeugleiste (70 dp) und Seitenleiste
   (320 dp) ließen der Arbeitsfläche 0 dp Breite – das Motiv war nicht sichtbar.
3. **Überschriften unlesbar.** Text ohne eigene Farbe fiel auf Schwarz zurück
   (kein `LocalContentColor`), auf dem dunklen Hintergrund also schwarz auf fast
   schwarz: „3 · Starten“, alle Kartentitel („1 · Kopfkamera“, „Laser“, …),
   Elementname im Inspektor.
4. **Starten auf dem Handy ohne Vorschau.** Die feste 380-dp-Spalte drückte die
   Bahnvorschau auf null Breite.

Layout und Größen:

5. Alle Seiten waren fest auf Tablet-Querformat gebaut: Aufträge (330 dp + Rest),
   Scan (Rest + 390 dp), Kalibrieren und Einstellungen (zwei Spalten), Material
   (Suchfeld 260 dp + großer Knopf in einer Zeile), Dialoge Kopfkamera/Kamerafoto/
   Taster-Versatz (400/360/420 dp feste Spalten), Ebenen-Dialog (600 dp).
6. Steuerung: Jog-Kreuz 3 × 88 dp + Z-Tasten passten auf dem Handy nicht in die
   Karte; vier Statuskacheln in einer Zeile schnitten die Werte ab;
   „Referenzieren / Abtasten / Parken“ nebeneinander wurden abgekürzt.
7. Maschine: vier Reiter mit langen Namen liefen auf dem Handy aus dem Bild.
8. Navigation: „Einstellungen“ in der Leiste abgeschnitten („Einstellunge“).
9. Editor-Werkzeugzeile: „Personalisieren“ abgeschnitten, Kopieren/Löschen/
   Zentrieren belegten Platz, obwohl sie nur mit Auswahl wirken.
10. Zoom ließ sich nur per Zwei-Finger-Geste ändern und nicht zurücksetzen.

Darstellung:

11. Nur ein dunkles Design; in der hellen Werkstatt schlecht ablesbar, keine Wahl.
12. Messlinien (gelb) und Abtastkreuze (weiß) wären auf einer hellen Fläche
    unsichtbar gewesen; einzelne Farben waren fest im Code statt im Theme.
13. Launcher-Icon nutzte die Hintergrundfarbe der App (hell → Icon verschwindet).
14. Beschriftung der Arbeitsfläche („0/0“, „360 × 340 mm“) in Pixeln statt dp:
    auf dem mdpi-Tablet riesig, auf dem Handy winzig.
15. Neuling-Einstieg: ohne Pi-Adresse stand nur „Nicht eingerichtet“ im Chip;
    wohin man zum Verbinden muss, sagte erst der Starten-Schritt.

## Was geändert wurde

Designsystem (`ui/Theme.kt`, `ui/Components.kt`):

- Zwei Paletten: **Hell** (Lavendel-Weiß, Indigo-Akzent `#4A57E3`, weiche
  getönte Schatten) und **Dunkel** (gleiche Ordnung auf fast Schwarz, Akzent
  `#8F9BFF`). Umschaltbar unter Einstellungen → Darstellung (Wie System / Hell /
  Dunkel), gespeichert je Gerät. Statusleisten-Icons passen sich an.
- `Lc`-Farben lesen die aktive Palette (Snapshot-State), damit auch Zeichenflächen
  sofort umschalten; `LocalContentColor` folgt dem Theme (Befund 3).
- Kontrast nachgerechnet (WCAG): Fließtext `muted` ≥ 6:1, Hinweistext `faint`
  ≥ 4,6:1 auf allen hellen Flächen (Weiß 5,5:1), dunkel ≥ 5,6:1; Akzent-Knopf 5,6:1;
  Warn-Banner zeigen Text in Textfarbe, der Ton steckt in Symbol und Rahmen.
- Karten 24 dp rund mit weichem Schatten (hell) bzw. Haarlinie (dunkel); runde
  Icon-Knöpfe, Pillen-Reiter mit Symbolen, Schalter-Kacheln mit Kreis-Icon,
  Ringanzeige für den Fortschritt, Schrittnummern an den Seitentiteln.
- Neue Bausteine: `SplitPane` (Hauptfläche + Seitenspalte, auf schmalen Geräten
  gestapelt, beide scrollen getrennt), `CanvasSurface`/`DottedBackground`,
  `ContextPill`/`PillBtn`, `PillTabs`, `ProgressRing`, `ScreenTitle`.

Rahmen (`ui/Shell.kt`):

- Tablet: links runde Icon-Navigation mit Beschriftung, Schritt-Plaketten 1–3 am
  Hauptweg, Logo oben; bei wenig Höhe (Handy quer) kompakter und scrollbar.
- Handy (< 600 dp): untere Navigationsleiste mit allen fünf Zielen.
- Kopfzeile: Verbindung + Status als Chips, Kopfposition als Pille (ab 980 dp),
  **NOT-AUS immer sichtbar** auf jeder Größe (Befund 1).
- Meldungen als dunkle Pille, Fehler rot; auf dem Handy über der Navigation.
- **Neu: Einstiegshinweis.** Ohne Pi-Adresse zeigt jede Seite oben „Noch kein
  Laser verbunden“ mit Knopf „Laser verbinden“ (führt zu Einstellungen).
- Handy quer (wenig Höhe): flachere Kopfzeile, kompakte Navigation.

Seiten:

- **Material**: Karten mit Stärke groß, Prozess-Chips, Häkchen an der Auswahl;
  auf dem Handy Suche oben, „Weiter: Motiv“ als breiter Knopf unten.
- **Motiv (Editor)**: gepunktete Arbeitsfläche, Arbeitsbereich als weißes Blatt
  mit Schatten; schwebende weiße Werkzeugleiste in Gruppen (Auswählen,
  Zeichnen, Anwenden, Messen; auf dem Handy nur Symbole); **schwarze Kontext-
  Pille** unter der Auswahl mit Duplizieren, 90° drehen, Spiegeln (neu direkt
  erreichbar), Zentrieren, Gruppieren, Kontur, Löschen; ohne Auswahl ein
  Hinweis zum aktiven Werkzeug. **Neu: Zoom-Pille** (−, %, +, Einpassen).
  Seitenleiste (Laser & Ebenen, Messwerte) schwebt rechts; auf dem Handy als
  Blatt von unten, standardmäßig zu (offen erst ab 1000 dp Breite).
  Werkzeugzeile kürzer beschriftet („Import“, „Vorlagen“ statt
  „Personalisieren“), passt so auf dem Tablet bis „Mehr“; die Platten-Auswahl
  steht am Ende, ein Verlauf am Rand zeigt, dass die Zeile weiterscrollt.
  „Alles zentrieren“ zusätzlich unter Mehr, „Kontur“ zusätzlich unter
  Werkzeuge – nichts ist weggefallen. Beschriftung der Arbeitsfläche in dp.
- **Starten**: Vorschau auf gepunkteter Fläche, Zusammenfassung als Karte,
  Ablauf nach dem Start als nummerierte Liste (Referenzieren, Abtasten, Höhe,
  Lasern, Parken); laufender Auftrag mit Ringanzeige und Restzeit. Alle
  Sicherheitsabfragen (Material liegt? Bereich frei?) unverändert.
- **Maschine**: Reiter als Pillen mit Symbolen (scrollen auf dem Handy);
  Steuerung mit 2 × 2 Kacheln und kleineren Jog-Tasten auf dem Handy, Aktionen
  untereinander; Zubehör als Schalter-Kacheln.
- **Kalibrieren, Einstellungen**: zwei Spalten ab 840 dp, sonst eine.
  Alle sieben Kalibrierungen und alle Felder unverändert vorhanden.
- **Scan, Aufträge**: `SplitPane` statt fester Spalten; Abtastkreuze in
  Theme-Farbe.
- **Dialoge** Kopfkamera, Kamerafoto, Taster-Versatz, Ebene: auf dem Handy
  gestapelt bzw. bis 600 dp breit statt fest.
- Messfarben im hellen Design dunkler (Bernstein/Grün), damit sie auf Weiß
  lesbar bleiben; Launcher-Icon weiß auf Indigo.

Unverändert (bewusst): Referenzierungs-Abfrage „Steht der Kopf frei?“,
Material-Hinweis vor dem Start, Z ≤ 80 mm und Material ≤ 60 mm (Core/Pi),
alle Kalibrierungen, Not-Aus-Verhalten, Pi als zentrale Quelle.

## Offene Punkte / Ideen für später

- Ebenenfarben kommen aus dem Projekt; sehr helle Ebenenfarben (z. B. Gelb)
  sind auf dem weißen Blatt schwächer – ggf. Kontur im Canvas abdunkeln.
- Ein Maßstabsbalken (wie im Referenzbild) neben der Zoom-Pille.
- Echte Emulator-Prüfung der Gesten (Pinch, Ziehen) auf dem Handy.
