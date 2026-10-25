> **PINBELEGUNG GEÄNDERT (25.10.2026):** Experimenteller neuer Build: FAN1/PC7 = Laserleistung, PA1 = PWM, BED/PC9 = Abluft M8, HE0/PC8 = Licht M7, FAN0/PC6 = Service-Zusatzausgang. Alte BED-Laser-/FAN0-Abluft-Anleitungen gelten für den neuen Build **nicht**. Eine direkte PWM-Verbindung zu einem auf FAN1− geschalteten Laser ist elektrisch nicht freigegeben. Siehe [FAN1-LASER Integration](FAN1_LASER_PI400_RELEASE.md). Automatischer SKR-Flash über USB fehlt weiterhin.\n\n# LumaCut Control OS – zentrale Pi-400-Maschinensteuerung

Entwicklungsstand: 24.10.2026. Diese Datei unterscheidet bewusst **implementiert**
von **nur entworfen**. Ein erfolgreicher Build ist keine Freigabe für Laserbetrieb.

## Zielarchitektur ohne parallelen HMI-Controller

```text
LightBurn ─────TCP23──┐
Weboberfläche ─HTTP───┼── Raspberry Pi 400 / LumaCut Control OS
Kamera/Dateien────────┘       │
                             │ Exklusive USB-CDC-Steuerleitung
                             ▼
                   BTT SKR Mini MZ V1.0 / grblHAL
                     ├─ TMC2209 X/Y/Z (Echtzeit-Step/Dir)
                     ├─ X/Y/Z-Endschalter
                     ├─ PA1 Laser-PWM
                     ├─ PC9 BED Laserstrom-Rückleitung (nur nach isolierter Verdrahtungsprüfung)
                     ├─ PC8 HE0 / M7, PC6 FAN0 / M8
                     └─ PC7 FAN1 Zusatz-Ausgang via $LCIO (Firmwarezustand rücklesbar)
```

Der Pi ist die **einzige übergeordnete Steuerinstanz**. Er besitzt Konfiguration,
G-Code-Verwaltung, Benutzeroberflächen, Freigaben, Jobs, Kamera, Diagnose,
LightBurn-Zugang und Serviceberechtigungen. Das SKR besitzt die elektrischen
Signale und die zeitkritische Bewegungssteuerung. Die Motion-Planner-Ausführung
bleibt bis zu einer getrennt getesteten STM32-Peripheral-Firmware auf grblHAL;
Linux auf dem Pi darf keine zeitkritischen Step-Pulse über normales USB takten.

## Implementiert in main

- Responsives Service Studio unter `/service`, direkt aus dem Dashboard erreichbar.
- Servicepasswort `lumaservice` bei erster Inbetriebnahme, **nur als gehashter
  Wert** in `/var/lib/lumacut/service-auth.json`. Das Passwort ist ein
  Betreiberstandard und sollte nach dem ersten Zugriff geändert werden.
- Separate signierte Service-Sitzung mit 10 Minuten Laufzeit und
  serverseitiger Sperre nach fünf falschen Passwörtern innerhalb fünf Minuten.
- Kritische Motor-/Homing-/Richtungsfunktionen, Fahrwegparameter,
  Netzwerkwechsel und GRBL-Parameteränderungen nur im Service-Modus.
- Numerische Servicekonsole für `$ID=Wert`, `$$`, `$I`, `$G`, `$#`
  mit echter `ok`-Bestätigung; Einstellungsänderungen zusätzlich über
  `$$` zurückgelesen und mit dem Sollwert verglichen.
- SKR-Firmwarekennung aus echten `$I`-Meldungen (`[VER:]`, `[BOARD:]`,
  `[DRIVER:]`, `[FIRMWARE:]`).
- Zwei bereits von der Firmware schaltbare Kanäle M7 (HE0/PC8) und M8
  (FAN0/PC6) sind als logische Funktionen LED/Abluft neu zuordenbar,
  jeweils exklusiv und nur im Leerlauf bei ausgeschalteten Ausgängen.
- Hardware-Pinmatrix deklariert gesperrte Pins, elektrische Ausgabetypen
  und nicht implementierte Reserve-Pins.
- PC7/FAN1 ist über den exakt spezifizierten grblHAL-Befehl `$LCIO=0/1`
  schaltbar und über `$LCIO` rücklesbar. Das Service Studio kann für
  den Ausgang Funktionsname und Anwendungsprofil verwalten. Die Funktion
  verlangt echten SKR-Identitätsabgleich und einen unbelegten Controller.
- Der Pi analysiert G-Code-Geometrie für eine SVG-Vorschau mit relativen
  Bewegungen, Maßeinheiten und Kreisinterpolation;
- XY-Positionierung durch Tippen auf die virtuelle Arbeitsfläche (mit Servicefreigabe),
  nur nach XYZ-Homing und aktivierter Z-Freifahrt. Der Pi prüft die Grenzen,
  schaltet den Laser per M5 ab und fährt zunächst Z, dann XY in G53-Maschinenkoordinaten. komplexe, unbekannte
  Transformationen verweigern eine irreführende Vorschau.
- Der LightBurn-TCP-Server blockiert unerlaubte Service- und GPIO-Befehle,
  während reguläre G-Code-Aufträge übertragen werden können.
- Das Service Studio exportiert die realen SKR-Parameter und das gespeicherte
  Maschinenprofil über `/api/service/backup` als JSON ohne Zugangscodes,
  Schlüssel oder Servicepasswort. Ein Hardware-Reset wird dadurch nicht
  ausgeführt.
- Der Pi verlangt beim USB-Verbindungsaufbau eine echte `$I`-/`$`-
  Identifikation mit passender LumaCut-SKR-Boardkennung und gültigen
  Maschinenparametern, bevor lokale Befehle oder LightBurn freigegeben werden.
- G-Code-Dateien werden **vor** dem Streaming auf unerlaubte Service- und
  I/O-Kommandos geprüft, damit eine Datei keine Servicefreigabe umgeht.
- Der SKR-Build erzeugt `capabilities.json` mit einer SHA-256-Prüfsumme
  der dazugehörigen `firmware.bin`. GitHub CI prüft die Übereinstimmung
  und packt beide Dateien gemeinsam in das Pi400/SKR-USB-Archiv.
- Automatisierte Python-Tests prüfen Authentifizierung, falsche Pinbelegung,
  überschneidungsfreie Ausgänge, Kennung und GRBL-Hosttransport.

## Funktionen, die NOCH NICHT funktionieren

- Allgemeine beliebige Umbelegung weiterer physischer SKR-Pins zur Laufzeit.
  Dazu ist ein passendes **STM32-Firmwareprotokoll** mit Pinmux-Whitelist,
  digitalem Ein-/Ausgang, PWM, Konfliktprüfung, persistentem Zustand und
  definiertem Reset-Verhalten erforderlich.
- Unabhängiger Echtzeit-Step-Generator als vollständiger Ersatz von grblHAL;
  die vorliegende USB-Firmware ist weiterhin grblHAL-basiert.
- Digitales Echtzeit-Heartbeat mit eindeutigem Abschaltverhalten nach USB-
  Ausfall. Die bestehende GRBL-USB-Brücke stoppt bei Verbindungsausfall
  softwareseitig, ersetzt aber keinen hardwareseitigen Laser-Interlock.
- Getrennte Probe-Eingangserfassung und echte abgetastete Höhenkarte.
- Physischer Nachweis der STM32-Pinbelegung, USB-/PWM-Pegel,
  Motorströme und Laser-Abschaltung auf der realen LumaCut CNC.
- Automatisches STM32-Firmware-Update über die Pi-USB-Verbindung.

Keine dieser Funktionen wird durch die Existenz eines UI-Menüs als
`implementiert` ausgegeben.

## Bedienung

1. Auf dem Pi `pi400/install.sh` installieren und die Ausgabe
   `http://lumacut.local:8080` öffnen.
2. Maschinen-Zugangscode im normalen Dashboard eingeben.
3. Navigation **Service Studio** öffnen; denselben Zugangscode verwenden,
   zusätzlich das Servicepasswort `lumaservice`.
4. Im Service Studio alle reservierten Pins prüfen, M7/M8 zuweisen
   und über **GRBL-Servicekonsole** ausschließlich sichere Parameter
   mit echten SKR-Rückmeldungen konfigurieren.
5. Servicepasswort vor regelmäßigem Einsatz gegen ein individuelles,
   mindestens 12-stelliges Passwort ändern.

Der Pi dient im vertrauenswürdigen LAN. HTTP/TCP23 nicht aus dem Internet
erreichbar machen. Für entfernte Zugriffe VPN mit Zugriffsschutz und HTTPS-
Terminierung verwenden. Die Standard-Servicedaten ersetzen keinen
hardwareseitigen Zugriffsschutz.

## Hardware- und Abnahmeregeln

- Bei ersten Tests Laser-Stromversorgung und TTL/PWM physisch trennen.
- Der vorhandene PC9-BED-Low-Side-Ausgang unterbricht den Bezugspunkt des
  LaserTree-Moduls; niemals ohne elektrische Isolation und überprüfte
  Gehäusemasse die PWM direkt vom SKR auf die schwebende Laser-Masse legen.
- Schrittrichtung, homing-/limit-Polarität, Anet-Z-Spindel, Schritte/mm,
  Z20-Sicherheitsbewegung, Maximalgeschwindigkeiten und TMC2209-Strom am
  Aufbau kalibrieren und messen.
- Not-Aus, Schlüssel und Tür-/Hauben-Interlock müssen die Laserenergie
  unabhängig von Pi und SKR zuverlässig unterbrechen.
- Erst nach realen Hardwaretests darf die experimentelle SKR-Firmware
  freigegeben werden.
