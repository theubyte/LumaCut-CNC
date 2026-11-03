# LumaCut Laser-Interface V2

Eine Platine für Laserversorgung (Relais G5LE-1 am SKR-FAN1, Sicherung 2 A T)
und Laser-PWM (PA1 → Optokoppler SFH618A/PC817 → geregelte 5 V vom 7805 →
gelber Laserdraht, 2,2 kΩ nach Masse). SKR-Seite und Laser-Seite haben keine
gemeinsame Leiterbahn.

| Datei | Inhalt |
|---|---|
| `schaltplan.svg/.png` | Schaltplan |
| `build_board.py` → `laser_interface_v2.kicad_pcb` | Platine zum Fertigen (90 × 64 mm, 2 Lagen, nur bedrahtet) |
| `LumaCut-Laser-IF-V2-gerber.zip` | Gerber + Bohrdaten für JLCPCB (Upload, kein Stencil nötig) |
| `render_top.png`, `render_bottom.png` | Vorschau Platine |
| `build_perfboard.py` → `lochraster.kicad_pcb` | gleiche Schaltung auf Lochraster 7 × 9 cm |
| `bauplan_lochraster.png` (`bauplan.html`) | Bauplan Lochraster: beide Seiten, Löcher, Drähte |
| `lochraster_liste.txt` | Bauteil- und Drahtliste aus dem Skript |

Skripte laufen mit KiCads Python (KiCad 10):
`"%LOCALAPPDATA%/Programs/KiCad/10.0/bin/python.exe" build_board.py`,
danach DRC/Gerber mit `kicad-cli pcb drc|export gerbers|export drill`.
DRC der Platine: 0 Verstöße, 0 offene Verbindungen (03.11.2026).
