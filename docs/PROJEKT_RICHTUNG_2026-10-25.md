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

## Prinzip

Jede Änderung wird mit einer Commit-Message committed, die erklärt **was** und **warum**. Der main-Branch bleibt die Quelle der Wahrheit. Keine stillen Abweichungen von den festgelegten Maschinenabläufen (Homing-Reihenfolge, Safezone, Parkpunkt).

---
*Fortlaufende Umsetzung entsprechend der Anforderungsakte vom 25.10.2026.*
