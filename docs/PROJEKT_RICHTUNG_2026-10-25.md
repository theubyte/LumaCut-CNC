# LumaCut CNC – Projektausrichtung und Umsetzung (25.10.2026)

## Verbindliche Nutzeranforderungen

Aus der vollständigen Anforderungsakte:

- Das System soll mit der **aktuellen Firmware und aktuellen Verdrahtung** funktionieren.
- Keine künstlichen Sperren oder "erstmal nicht anschließen"-Hinweise, die den gewünschten Betrieb blockieren.
- Endprodukt: hochwertige, zuverlässige CNC-Laserlösung mit eigener Software.
- LightBurn bleibt vorläufig nutzbar, soll aber durch **LumaCut Studio** (Windows) abgelöst werden.
- Später: Handy-/Tablet-App.
- Homing: **XY zuerst**, dann Z, dann 20 mm Rückzug (editierbar).
- 30 mm L-förmige Safezone, Park auf X0/Y0.
- G30 mit dem vorhandenen Z-Taster für Werkstückoberfläche, Fokus standardmäßig 7 mm.
- Laser-PWM (PA1 / M3 I / S0..255), getrennte Steuerung von Licht und Abluft.
- Motor-Melodien nach Homing und Jobende.
- Alle Änderungen in GitHub nachvollziehbar dokumentieren (Commit-Message erklärt Warum).

## Aktueller Ist-Zustand (25.10.2026)

- Pi-Dienst zuletzt im Crashloop wegen `ImportError: cannot import name 'MarlinTransport'` + beschädigtem lokalem Git-Objekt.
- Im GitHub-Stand existiert die Klasse korrekt.
- G30 endete mehrfach mit "Probing Failed", obwohl der Taster korrekt schaltete (Cap:Z_PROBE:0 in früheren M115).
- Einzelne Fahr- und Homingbewegungen wurden beobachtet.
- Windows Studio ist Preview, kein fertiges Produkt.

## Bereits umgesetzt (dieser Commit-Serie)

1. **`pi400/recover.sh`** – Repariert beschädigten Git-Checkout durch frischen Clone, sichert Config und Nutzerdaten, prüft Import und startet den Dienst.
   - Aufruf auf dem Pi: `sudo bash /opt/lumacut/pi400/recover.sh`
   - Behebt den unmittelbaren Startausfall.

## Nächste Umsetzungsschritte (in dieser Reihenfolge)

### Priorität 0 – Dienst wieder lauffähig
- Auf dem Pi `recover.sh` ausführen.
- Danach HTTP 8080 und TCP 23 prüfen.

### Priorität 1 – G30 / Probing zuverlässig machen
- Sicherstellen, dass die geflashte Marlin-Firmware `Cap:Z_PROBE:1` meldet.
- Die bereits im `build.py` vorhandenen Anpassungen (Z_CLEARANCE_MULTI_PROBE=16, Z_PROBE_LOW_POINT=-2, gemeinsame Z_MIN-Probe) müssen auf dem Board sein.
- Gateway-Logik so anpassen, dass ein echter Kontakt nicht als Fehler gewertet wird und der Messwert korrekt zurückgegeben wird.

### Priorität 2 – Gateway und Web-UI an die exakten Vorgaben anpassen
- Homing-Reihenfolge XY→Z→Rückzug ist bereits im Code; Dokumentation und UI klar machen.
- LightBurn Custom-GCode-Ablauf (G28, G30, M3 I, M2-Park) stabilisieren.
- Keine unnötigen Sperren, die den gewünschten Ein-Klick-Workflow blockieren.

### Priorität 3 – Eigene Software (LumaCut Studio)
- Windows Studio um echte Maschinenanbindung an den Pi erweitern (Status, Home, Jog, Job senden).
- Vektor- und Raster-CAM so weit bringen, dass ein vollständiger Job ohne LightBurn möglich ist.
- Später mobile App auf der gleichen API.

### Priorität 4 – Elektrik und Feinabstimmung
- Mit der aktuellen Verdrahtung PWM, Licht, Abluft und Kühlnachlauf verifizieren.
- Motor-Melodien real testen und ggf. anpassen.
- Updates und Recovery robust halten.

## Stand nach Überarbeitung (25.10.2026, abends)

Befunde und Korrekturen:

- **Crash-Ursache im Code:** Die fünf G30-Commits (`645ea43`…`db8b0ef`) hatten `transport.py` aus einem älteren Stand neu geschrieben. Dabei fehlten `safe_home()` (Web-Home und LightBurn-G28 liefen in einen `AttributeError`), die G90/G91-Verfolgung, die M112-Sperre und die LightBurn-Präambel (`G00 G17 G40 G21`, `G54`). Wiederhergestellt aus `8bdb5d0`.
- **„Probing Failed“ trotz schaltendem Taster:** Marlin 2.1.2.9 (`Probe::run_z_probe`, nur ein Tastvorgang) meldet Fehler, wenn der Kontakt über `Z_CLEARANCE_MULTI_PROBE` liegt (Stock-Firmware 5 mm). Der Kopf bleibt dann exakt am Kontaktpunkt stehen. Der Pi wertet diesen Fall jetzt aus: M114 liefert die Kontakthöhe, M119 muss `z_min: TRIGGERED` zeigen, sonst bleibt es ein Fehler. Funktioniert mit der aktuell geflashten Firmware, egal ob 5 oder 16 mm einkompiliert ist.
- **Alter EEPROM-Tasterversatz:** Beim Verbinden setzt der Pi `M851 X0 Y0 Z0` (nur zur Laufzeit). Der Mega-Zero-Beispielwert `{-40, -10, 2}` aus einem älteren EEPROM hätte jedes G30 um X+40/Y+10 verschoben und die Fehlergrenze um 2 mm gesenkt.
- **Schnittqualität:** Vor jedem Laser-G1 lief `M400` + `M114`. Dadurch hielt der Kopf an jedem Segment an (Brennpunkte, ungleichmäßige Linien). Der Startpunkt kommt jetzt aus den vom Pi selbst gesendeten Koordinaten; die 30-mm-Safezone wird weiter geprüft, jetzt auch für G2/G3-Bögen.
- **Laser-Netzteil:** PC6 schaltet die 24 V des Lasermoduls. Nach dem Einschalten wartet der Pi 800 ms, bevor `M3 I` kommt, damit die erste Linie nicht zu schwach brennt.
- **Studio-Postprozessor:** Nur noch ein `M3 I` pro Auftrag (vorher pro Pfad/Rasterzeile, jeweils mit Planer-Stopp durch Marlin).

Neu:
- Web-UI: „Werkstück abtasten (G30)“, „Ein-Klick: Homing → Abtasten → Fokus → Auftrag → Park“, „Auftrag abbrechen“.
- Bei Jobfehlern oder Abbruch: Laser aus und Parken statt M112 (M112 nur, wenn das nicht mehr klappt).
- Upload prüft vorab, ob das Motiv in der 30-mm-Safezone liegt.
- LumaCut Studio, Reiter „Maschine“: Status, Referenzieren, Joggen, Abtasten, Licht/Abluft, Projekt senden, Ein-Klick-Start, Abbruch, Notstopp (Tauri-Befehle `pi_action`, `pi_upload_job`).

Noch offen / an der Maschine zu prüfen:
- Probelauf auf Material: Fokus 7 mm und `z_switch_tip_offset_mm` (Standard 1,5) einmessen.
- Y-Ausrichtung Studio ↔ Maschine (Studio zeichnet Y nach unten) an einem Testmotiv prüfen.
- `lightburn/LumaCut-CNC-USB.lbdev` ist noch das alte GRBL-Profil (M4, S-Max 1000) und passt nicht zum Marlin-Gateway; in LightBurn ein Marlin-Gerät über TCP mit S-Max 255 verwenden.

## Prinzip

Jede Änderung wird mit einer Commit-Message committed, die erklärt **was** und **warum**. Der main-Branch bleibt die Quelle der Wahrheit. Keine stillen Abweichungen von den festgelegten Maschinenabläufen (Homing-Reihenfolge, Safezone, Parkpunkt).

---
*Fortlaufende Umsetzung entsprechend der Anforderungsakte vom 25.10.2026.*
