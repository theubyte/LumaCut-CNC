# LumaCut CNC – schneller Fahrbetrieb und Offset-Raster (24.10.2026)

## Geschwindigkeit: Maschine bestimmt das Maximum, nicht das HMI

Das Jog-Tempo basiert jetzt auf dem **tatsaechlichen, per GRBL `$$`
gelesenen** Achsmaximum: `$110` X, `$111` Y, `$112` Z.
Am HMI wird mit **100 % / 50 % / 25 %** lediglich ein frei waehlbarer
Prozentfaktor angewendet; Startwert ist 100 %. Es existiert kein
zusaetzlicher 240/700-mm/min-Speed-Cap fuer Jog oder ein
600-mm/min-Cap fuer den Z-Sicherheitsrueckzug mehr. Die SKR-Firmware
hat X/Y-Werkseinstellungen 6000 mm/min (aus dem urspruenglichen
Atomstack-A5-Pro-Profil); bereits gespeicherte SKR-`$110/$111`-Werte
haben Vorrang. `$112` wird wegen der anderen Anet-Spindel nicht
blind angehoben.

**Maximum der Motoren** ist nicht gleich Leerlauf-Maximum des
Treibers: bei montierter Last/Spindel/Leitung gelten Drehmomentkurve,
Beschleunigung, Eingangsspannung, Riemenspannung, TMC2209-Strom und
thermische Grenzen. Die volle Maschinengeschwindigkeit ist daher ein
messbarer Betriebsparameter und wird nicht als fester theoretischer
Wert behauptet. Schrittverluste, haeufige Stall-Alarme und Hitze
sind Zeichen zu hoher Werte. Mechanische Limits, M5, Homing und
Kollisionserkennung bleiben bestehen.

## Parameteroberflaeche

**Setup / Parameter** enthaelt sieben Kategorien mit je sechs Zeilen.
Links erscheinen `$ID` und Name, rechts ein Eingabefeld und ein
Haken zum expliziten Setzen. Werte stammen aus der tatsaechlichen
SKR-`$$`-Rueckmeldung (unbekannte Parameter bleiben mit `?`).
Nach Haken bestaetigt erst der SKR-Readback den Erfolg. Editierte
Werte bleiben bei UI-Refresh erhalten. Die Bildschirmtastatur passt
in 800 × 480 Pixel.

Die frueheren Buttons `Z-Test 0,5 mm` und `Z-Richtung OK` sind aus
dem regulaeren Bedienablauf entfernt. Fuer die automatische 20-mm-
Vor-XY-Homingbewegung bleibt aus physikalischen Gruenden eine
Z-Schritte/mm-Kalibrierung erforderlich, weil falsche `$102`-Werte
sonst zu unkontrolliert langen Fahrten fuehren koennen.

## Offset-korrekter Ganzflaechen-Rasterplan

In **Fokus/Taster → Abtastfeld/XY-Offset** koennen folgende Werte
dauerhaft im ESP32 gespeichert werden:
- Start X / Start Y des Werkstueckbereichs im positiven HMI-Koordinatensystem
- Werkstueckbreite und -hoehe in mm
- Tasterversatz X / Y gegenueber der Laserspitze (positiv, falls der
  Taster in dieser Achsenrichtung *weiter rechts/oben* liegt)
- Punktabstand des Rasters in mm

Fuer jeden gewuenschten Schaltpunkt gilt:
`Laserposition = Tasterpunkt – Tasteroffset`.
Die Scanplanung bildet die Schnittmenge von gewuenschtem Rechteck,
Maschinenvolumen und dem um X/Y-Offset verschobenen erreichbaren
Tasterbereich. Dadurch wird keine Position ausserhalb
`$130/$131` eingeplant, auch wenn der Taster nicht genau auf der
Laserspitze sitzt. Eine 0,5-mm-Innenreserve bleibt wegen der
Schalter-/Homing-Freifahrt. Zeilen werden serpentin angeordnet,
also abwechselnd links→rechts und rechts→links, damit keine
langen leeren Rueckfahrten zwischen Reihen noetig sind.

**Raster berechnen** schreibt die geplanten Punkte als CSV nach
`/logs/probe_plan.csv` (microSD, falls installiert, sonst LittleFS).
Dateiinhalt: Tasterpunkt X/Y, Laserspitze X/Y und rohe GRBL-MPos X/Y.
Das ist ein **geometrisch gueltiger Mess- und Bewegungsplan, keine
gemessene Hoehenkarte**. Nur ausserhalb der erreichbaren Grenzen liegende
Teile des gewuenschten Werkstuecks werden automatisch abgeschnitten;
der Status sagt explizit, ob das Rechteck beschnitten wurde.

**Echte Hoehenabtastung ist noch nicht vorhanden:** Das derzeitige
SKR-Profil hat nur den mit dem Z-Homing geteilten Taster an PC2
(`PROBE_ENABLE=0`); ein separater PC14-G38-Eingang ist nicht
verdrahtet. `$HZ` setzt die Maschinen-Z-Referenz neu und darf
nicht als Ersatz fuer eine echte flaechenhafte G38-Messung
missbraucht werden. Eine physisch verdrahtete, gepruefte und getrennt
auswertbare Probe, GRBL Probe-Signalerfassung, Resultat-Speicherung
und eine sichere Mess-Z-Rueckzugsmethode sind fuer reale
mehrpunktige Hoehenkarten noch umzusetzen. Die neue Oberflaeche
loest deshalb **keine unbeaufsichtigten Abtastfahrten** aus.

---
# LumaCut CNC – Atomstack X/Y + Anet-Z: verifizierte Inbetriebnahme (24.10.2026)

## Änderungen am aktuellen Softwarestand

Die vorhandenen Atomstack-A5-Pro-Riemenachsen X/Y erhalten im SKR-Build
**Werkseinstellungs-Defaults** `$100=80`, `$101=80` steps/mm. Dieser
Wert gilt nur bei derselben Schrittmotor- und Mikroschrittauflösung wie
an der Originalmechanik. **Vorhandene NVS-Werte überschreibt ein
Firmwareflash nicht.** Zur Prüfung die realen `$100` und `$101` über
`$ Lesen` ansehen.

**Z:** Motor und Spindel stammen vom Anet A8, aber aus Motorfoto und
Antriebsausführung lässt sich nicht erkennen, ob die Spindel
2, 4 oder 8 mm pro Umdrehung führt und mit welcher TMC2209-
Mikroschrittauflösung das Board arbeitet. `$102` wird daher **nicht**
mit einem geratenen Wert überschrieben. Für alle Achsen gilt:

`neue Schritte/mm = vorhandene Schritte/mm × befohlener Weg / gemessener Weg`.

### Jog nach erfolgreichem Homing

Nach einer erfolgreichen XYZ-Referenzfahrt, gültiger MPos, bekannten
XYZ-Verfahrwegen und aktivierten Motoren darf das **Jog-Menü** einfache,
berechnete `$J`-Schritte schicken. Der zusätzliche Workflow
`Limits EIN` ist für Jog allein nicht mehr zwingend erforderlich.
Der HMI-Code prüft die Endposition weiterhin selbst gegen
`$130/$131/$132`; G0-Jobs und Flächenfahrt behalten den strengeren
Soft-Limits-Check. Die Start-Schrittweite beträgt 0,1 mm. X+/Y+/Z+
bezieht sich auf **positive angezeigte HMI-Koordinaten**, nicht die
internen negativen GRBL-MPos. Jede Jogfahrt sendet zuerst `M5`.

Die Taste **Leiser Jog / Normal** schaltet XY 240/Z 90 oder
XY 700/Z 180 mm/min um. Das verringert möglicherweise Resonanzen
während der Fahrt, verändert aber keine unbekannten TMC2209-Motorströme.
Haltefrequenz-Geräusche können auch durch Choppermodus,
Treiber-UART, Stromgrenze, mechanische Resonanzen oder lose Verdrahtung
entstehen; ohne Treiberstatus/Strommessung ist eine dauerhafte
Geräuschbeseitigung nicht nachgewiesen.

### Einmalige echte Schrittkalibrierung

1. Laser elektrisch stromlos lassen, Mechanik im freien Arbeitsraum
   aufbauen und Homing aller drei Endschalter prüfen.
2. Im **Jog** erst 0,1 mm in genügend Abstand von allen Anschlägen
   testen. Dann eine gut messbare Sollfahrt ausführen (X/Y z. B. 10 mm,
   Z zunächst 1 mm). Den **wirklichen** Weg mit Messschieber/Messuhr
   messen, nicht aus der HMI-Anzeige abschätzen.
3. **Jog → Wege kalibrieren**, befohlenen *Sollweg* und gemessenen
   *Istweg* eintragen. Pro Achse **X/Y/Z korrigieren** wählen.
   Das HMI berechnet die neuen Werte `$100/$101/$102`, schreibt sie in
   die SKR-Konfiguration und liest sie zur Bestätigung zurück.
4. Bewegung mit verschiedenen Strecken wiederholen, um mechanische
   Fehler, falsche TMC-Mikroschritte und Umkehrspiel auszuschließen.
   Besonders Z im gesamten vorgesehenen 20-mm-Abschnitt überprüfen.

### Z zuerst, 20 mm Sicherheitsabstand, danach XY

Die aktualisierte **SKR-Firmware** ergänzt eine Systembewegung direkt
zwischen grblHALs üblicher Z-Homingphase und der anschließenden
XY-Homingphase. Die SKR-Firmware prüft den konfigurierten Z-Fahrweg
`$132` (mindestens 21 mm) und begrenzt die Zwischenfahrt auf maximal
600 mm/min, zusätzlich zur kleineren tatsächlichen `$112`-Grenze.

**Aus Sicherheitsgründen zuerst deaktiviert.** Den 20-mm-Zwischenschritt
nur nach reproduzierbar gemessener Z-Kalibrierung und sichtbarem
0,5-mm-Z-Richtungstest freischalten:

1. Neue gepaarte HMI/SKR-Firmware installieren; vor Tests Laser physisch AUS.
2. XYZ homen und **Jog → Wege kalibrieren → Z korrigieren** mit echtem
   Soll/Ist-Weg durchführen, bis die HMI die bestätigte SKR-Rücklesung
   meldet. In **Fokus/Taster** `Z-Test 0,5 mm` und anschließend
   `Z-Richtung OK` nur nach Prüfung der tatsächlichen Bewegung drücken.
3. Z-Fahrweg `$132` inklusive Sicherheitsreserve prüfen; erneut homen.
   Danach **Jog → Wege kalibrieren → Z20 aktivieren** innerhalb von 15
   Sekunden **zweimal** bestätigen. Das HMI setzt `$27=2.5` und liest
   die SKR-Bestätigung. Dies ist der explizite Freigabewert der
   LumaCut-SKR-Homing-Routine. `$27` ist zugleich der reguläre
   grblHAL-Pull-off-Wert und gilt auch für X/Y (2,5 mm).
4. Beim **nächsten** `$H` homt grblHAL erst Z, fährt um den
   noch fehlenden Weg von Z-Pull-off auf 20 mm (relativ zur
   Schalterreferenz) und homt **erst dann XY**. Der Schritt wird nicht
   bei einem einzelnen `$HZ` (Werkstückkontakt) ausgeführt.
   Bei zu kurzem Z-Fahrweg wird die Gesamt-Referenzfahrt mit Fehler
   abgebrochen, ohne blind nach XY weiterzufahren.

**Deaktivieren:** Wenn die Z-Kalibrierung verändert werden muss,
wählt die HMI davor `$27=1.0` (vor dem neuen `$102`-Befehl).
Ebenso kann `$27=1.0` nach Sicherung der Maschine über
`Setup → Parameter-ID 27 → Setzen` eingetragen werden.
Bei einem Firmware-Flash bleibt ein schon gesetzter `$27`-Wert
im SKR-NVS normalerweise erhalten. Bei abweichender Firmware oder
anderen Homing-Parametern ist die Vor-XY-Bewegung nicht hardwareverifiziert.

Das alte HMI führt zur Sicherheit nach dem Gesamt-Homing weiterhin
einen Z-Rückzug aus; in der neuen Firmware wird diese nachträgliche
Bewegung nicht mehr nach **unten** auf einen gespeicherten
7-mm-Fokusabstand zurückgeführt, sondern mindestens auf 20 mm begrenzt.

---
# LumaCut Studio – Maschinen-Setup und Live-Arbeitsfläche

Stand 23.10.2026. **Entwicklungs-/Laborfirmware; keine Freigabe für Betrieb des bestromten Lasers.** Ein erfolgreiches CI-Build prüft Compiler und Tests, nicht die sichere reale Achsbewegung.

## Hardware der LumaCut
- BTT SKR Mini MZ V1.0 mit genau **einem** Motor pro X/Y/Z-Achse. E-Treiber unbenutzt.
- Drei mechanische Endschalter: **X PC0 / Y PC1 / Z PC2**.
- Waveshare ESP32-S3-Touch-LCD-7 Rev1.2, 800 × 480, UART2 auf SKR PA9/PA10.
- Ein zusätzlicher Werkstücksensor existiert nicht. Der Z-Taster soll später beide Aufgaben übernehmen; **G38-Probe-Funktion ist derzeit nicht implementiert.**

## Achsen invertieren: Motor $3 und Homing $23
Die Setup-Taste **XYZ** invertiert die X-, Y- und Z-Drehrichtung bezogen auf die aktuell aus `$$` gelesenen Werte. Intern wird `$3 = alterWert XOR 7` gespeichert. **Gleichzeitig** invertiert das HMI die entsprechenden `$23`-Bits, damit die physische Richtung *zur bereits montierten Endschalterposition* gleich bleibt. Das ist für die aktuelle Verdrahtung sinnvoller als blindes `$3=7`, denn die bisherige `$3`-Maske könnte schon andere Bits gesetzt haben.

Die X-/Y-/Z-Tasten ändern je eine Achse. Rechts lassen sich die Homing-Suchrichtungen in `$23` unabhängig feinjustieren. Homing und Bewegung sind **nicht** dieselbe logische Richtung. Unbedingt physische Schaltereingänge, Polung, zulässige Achsbewegungen und `$23` prüfen, bevor `$H` gestartet wird. Das Setup liest nach Speicherung jeweils erneut die Einstellungen.

## Verfahrwege und Soft Limits
Das HMI liest `$130`, `$131`, `$132` aus dem SKR, zeigt die gespeicherte Fläche an und kann neue **vorher tatsächlich gemessene** Werte speichern. Nicht die äußere Rahmengröße als Arbeitsweg ausgeben: nutzbarer Verfahrweg berücksichtigt Anschläge, Endschalterfreifahrt und mechanische Reserve. Auf dem Laborstand *ohne Laserenergie* Schalter überprüfen und anschließend die zulässigen Achswege unabhängig ermitteln.

Der Button **Limits EIN** sendet bei bekanntem X/Y/Z-Weg `$22=1`, `$20=1` und `$21=1`. Damit sind sowohl die Soft-Limit-Verfahrwegprüfung als auch die X-/Y-/Z-Endschalter für Hard-Limit-Alarme eingeschaltet. Soft Limits benötigen kalibrierte Schritte/mm, überprüfte Richtungen und erfolgreiche Referenzfahrt. Die Endschalterüberwachung über Hard Limits (`$21`) muss bezüglich Schalterpolung, Kontaktentprellung und Homing-Freifahrt separat überprüft werden. Die HMI-Grundfunktionen verweigern eigene Job-, Jog-, Rahmen- und Parkbewegungen, wenn aktuelle Positionsdaten, Homing oder Soft Limits fehlen. Der SKR bleibt für seine eigenen Limitmeldungen und Alarme zuständig. Software kann **keine absolute Garantie** geben, dass der Laser nie mechanisch überfährt (z. B. nach Schrittverlust, Fehlkonfiguration oder Treiberfehler).

## Live-Karte mit rotem Positionspunkt
Register **Flaeche** zeichnet einen quadratischen Positionsbereich mit rotem Punkt aus den kontinuierlichen grblHAL-Statusmeldungen `MPos:X,Y,Z`. Die Achsgröße wird aus `$130` und `$131` gewonnen; die Karte wird **erst nach erfolgter Referenzfahrt** angezeigt. Die Position wird nicht auf die Kante geklemmt, wenn die Koordinaten außerhalb des konfigurierten Maschinenbereichs liegen: der Punkt verschwindet und es erscheint ein Hinweis.

Standard-Grbl hat oft negativen Maschinenraum von `-Verfahrweg` bis `0`. Für auf `0..Verfahrweg` konfigurierte grblHAL-Setups kann mit **Koordinatennullpunkt** umgeschaltet werden. Diese Umschaltung beeinflusst ausschließlich die Darstellung im HMI, nicht die Firmware-Koordinaten.

Das mobile HMI bietet dieselbe Live-Fläche und den authentifizierten Endpunkt `GET /api/machine`. Er liefert `work_area.x_mm / y_mm / z_mm`, `homed`, `soft_limits_enabled`, `direction_mask`, `homing_direction_mask` sowie `coordinates`. Der Zugriff benötigt den HTTP-Header `X-LumaCut-Key`. Andere eigene Software kann diese JSON-Daten lesen. **LightBurn übernimmt aus dem Standard-GRBL-Protokoll die eigenen Geräteabmessungen nicht garantiert automatisch**; deshalb X/Y-Arbeitsfläche in den LightBurn-Geräteeinstellungen entsprechend setzen. Keine ungesicherte LAN-Freigabe nach außen.

## Weiteres Maschinen-Setup
Unter **Setup**:
- `$$ Lesen`: aktuell vom SKR gespeicherte Einstellungen synchronisieren.
- `XYZ`, `X`, `Y`, `Z`: Motor- und gekoppelte Homing-Drehrichtung invertieren.
- `Homing X/Y/Z`: `$23` gezielt pro Achse ändern.
- Eingabefelder `X/Y/Z [mm]` und **Verfahrwege speichern**: `$130/$131/$132`.
- **Parameter-ID/Wert**: nummerierte GRBL-Einstellungen (z. B. `100..102` Schritte/mm, `110..112` Maximalgeschwindigkeit, `120..122` Beschleunigung, `24..27` Homingwerte). Parameterbereiche und Fehlermeldungen werden weiterhin vom Controller verifiziert. Das HMI verhindert bei `$20/$21/$22` die Deaktivierung bestehender Homing-/Limitfunktionen per Setup-Maske.
- **180 Grad**: persistente Landscape-Displaydrehung; Touchkoordinaten werden ebenfalls gedreht. 90°/270° (Porträt) braucht ein anderes UI-Layout und wird bewusst nicht als implementiert bezeichnet.

## Option Sensorless Homing / Verfahrweg erkennen
Die integrierten TMC2209 unterstützen StallGuard4. grblHAL Plugins_motor stellt Parameter für Empfindlichkeit und `$339` als Achsmaske bereit. Das **aktuelle LumaCut-SKR-Build enthält diese Sensorless-Erweiterung nicht**. Es ist auch nicht bestätigt, dass beim Mini MZ V1.0 jeder TMC2209-DIAG-Ausgang getrennt an einen geeigneten Eingang geführt ist. Sensorless Homing kann abhängig von Beschleunigung, Antriebsstrom, Reibung und Geschwindigkeit fehlauslösen bzw. einen Stall verpassen. Die bereits vorhandenen physischen Endschalter bleiben für Homing der bevorzugte und reproduzierbare Referenzweg.

Das Abtasten eines Rahmenendes durch Motorstall ist **keine automatische präzise Arbeitsflächenkalibrierung**. Verfahrwege bleiben mess- und prüfpflichtig; die Firmware kann sie derzeit nicht ohne Eingabe entdecken. Sensorless erst nach bestätigter DIAG-Verdrahtung, Plugin-Firmware und ungefährlicher separater Motorprüfung erwägen, nicht als Ersatz für Endlagenkontrolle im laufenden Laserbetrieb.

## Flimmern / RGB-Streifen
Die ESP32-S3-HMI nutzt nun einen DRAM-*Bounce-Buffer* für RGB-Panel-DMA (`W*10` Pixel) und aktualisiert unveränderte Statuslabels nicht mehr ständig. Das reduziert PSRAM-Buskonkurrenz und unnötiges Neuzeichnen; Espressif dokumentiert Unterläufe bei gleichzeitiger PSRAM-, Wi-Fi- und Flash-Aktivität. Das ist ein **softwareseitiger Behebungsversuch**, keine Garantie. Bleiben horizontale Streifen, bei stromlosem SKR den Waveshare über eine stabile 5-V-USB-Versorgung prüfen. Permanentes Tearing erfordert gegebenenfalls eine validierte VSYNC-/Double-Buffer-Architektur am realen Board.

## Quelltexte
- [ESP32-S3 RGB LCD – Espressif](https://docs.espressif.com/projects/esp-idf/en/v5.4.2/esp32s3/api-reference/peripherals/lcd/rgb_lcd.html)
- [grblHAL Motor-Plugin Sensorless](https://github.com/grblHAL/Plugins_motor)
- [Mini MZ Klipper-Pins](https://github.com/Klipper3d/klipper/blob/master/config/generic-bigtreetech-skr-mini-mz.cfg)
- [LumaCut Hardwareprofil](HARDWARE.md)

## Touch-Tastatur und Eingabedialog (Revision 23.10.2026)

Auf Touch einer beliebigen HMI-Eingabe (WLAN, Passwort, Makroname, GRBL-ID/Wert, XYZ-Verfahrweg, Z-Rückzug, Fokusabstand oder mechanischer Tasteroffset) erscheint jetzt **ein vollständig bildschirmfüllender Editor** mit sichtbarem Textfeld oberhalb der Tastatur und großen Schaltflächen **Speichern** und **Zurück**. Die Verbindung nutzt LVGL-Ereignis `LV_EVENT_CLICKED`, nicht das auf dem GT911 vorher unzuverlässige FOCUS-Ereignis. Zahlfelder aktivieren ein numerisches Keyboard. Ohne Hardwaretest ist die Touch-Tastatur nicht als vollständig verifiziert anzusehen.

## Tastaturkorrektur (24.10.2026)

**Ursache der außerhalb des 800×480-Displays liegenden Tasten:**
`lv_keyboard_create()` setzt in LVGL 8 standardmäßig `LV_ALIGN_BOTTOM_MID`.
`lv_obj_set_pos(keyboard, margin, kbY)` ändert den Anker nicht: positive Y-Werte verschieben
somit die Tastatur **unter** den unteren Bildschirmrand. Auch eine nachträgliche
Höhenreduzierung kann den Fehler verschlimmern. Das HMI erzwingt jetzt im
vollbildigen Editor mit `lv_obj_align(keyboard, LV_ALIGN_TOP_LEFT, margin, kbY)`
den oberen linken Ursprung, auch nach Tastaturmoduswechsel, und prüft die
realen globalen Grenzen des Widgets. Speichern/Abbrechen bleiben oberhalb des
Sicherheitsabstands zum Displayrand sichtbar.

**Wichtig:** Der Fix wirkt erst nach dem Flashen des neuen HMI-Builds. GitHub-CI
kann Kompilierung und Quelltext-Regression prüfen, nicht die reale GT911-Touchfläche;
vor Maschinenbetrieb am stromlosen Laser prüfen.

## Fokusprofil und Z-Rückzug nach Homing

Das HMI speichert drei unabhängige Werte in den Preferences des Waveshare: **Z-Rückzug nach normalem XYZ-Homing**, **optischer Soll-Fokusabstand** (beide zunächst 7 mm) und **optischer Abstand des Laserkopf-Datums zur Werkstückoberfläche genau beim Tasterkontakt** (Tasteroffset, zunächst 0 mm als unkallibrierter Platzhalter). Negative Retractwerte erlauben abhängig von der tatsächlichen Achsorientierung Bewegungen in negativer Z-Richtung. Die Werte müssen anhand der Optik und des Tastpunkts gemessen werden.

Nach erfolgreichem **vom HMI gestarteten** `$H` sendet die HMI-Sequenz `$1=255` an den SKR und fordert – **nur wenn die aktuelle MPos-Position und die gespeicherten Soft Limits den Weg zulassen** – einen absoluten kleinen Z-Rückzug per GRBL-Jogging mit ausgeschaltetem Laser (`M5`) an. Ist der gewünschte Weg außerhalb `$132`, wird **nicht gefahren**, sondern die Bedienoberfläche zeigt eine konkrete Meldung. Gerade beim Z-Homing in positiver Richtung kann `Z+7` nach der Referenzfahrt gegen das obere Limit zeigen. Deshalb ist das Vorzeichen der Rückzugsstrecke im HMI einstellbar und darf nicht geraten werden. Die optische tatsächliche Brennweite wird dadurch nicht selbstkalibriert.

## Werkstückabtastung mit dem vorhandenen Z-Taster

Da an **PC2** derselbe mechanische Schalter für Z-Endstop und Werkstückkontakt hängt und **PC14** nicht belegt ist, bleibt echtes `G38.2`-Probing deaktiviert. Eine gemeinsame GPIO-Verwendung als Limit-Interrupt und Probe ohne definierte Umschaltung könnte den Lauf abbrechen oder einen mechanischen Fehler verursachen.

**Neu implementiert ist eine alternative Z-Werkstückreferenzierung über `$HZ`:** Nach vollständigem XYZ-Homing und gültigen Verfahrwegen kann im HMI unter **Fokus / Taster → Probe konfigurieren** der spezielle **Kopf-Taster-Modus** aktiviert werden. Dies ist nur sinnvoll, wenn der am Laserkopf montierte Z-Schalter tatsächlich die **Oberfläche des Werkstücks** tastet. Dann sendet das HMI in einer quittierten GRBL-Sequenz `M5`, `$22=3` (Homing plus achsspezifisches Homing), `$HZ` und `$1=255`. Danach wird bei gültigen Soft Limits ein konfigurierter optischer Rückzug von `Soll-Fokusabstand minus optischer Abstand beim Schalterkontakt` gefahren. Bei Standardwerten 7 mm - 0 mm sind das +7 mm. Ein Z-Homing verändert jedoch die Z-Maschinenreferenz und ist **kein metrisches G38-Probing mit separater Tastposition**. Die Z-Suchrichtung `$23`, `$24/$25`, der Schalterhub und reale Bewegungsgrenzen müssen vor dem ersten Versuch überprüft werden. Eine maximale Z-Taststrecke wird vom HMI aktuell **nicht separat auf z. B. 15 mm begrenzt**; `$HZ` nutzt die im SKR konfigurierten Homing-Grenzen. Es ist deshalb keine generell sichere automatische Vermessung beliebiger Werkstückhöhen.

Das SKR-Build enthält jetzt die zugehörigen Factory-Defaults `DEFAULT_HOMING_ENABLE=1`, `DEFAULT_HOMING_SINGLE_AXIS_COMMANDS=1` und `DEFAULT_STEPPER_IDLE_LOCK_TIME=255`. Bereits in grblHAL gespeicherte NVS/EEPROM-Einstellungen gehen Factory-Defaults vor; die HMI-Sequenz schreibt beim Z-Einzelhoming ausdrücklich `$22=3`.

## Haltemoment statt mechanischer Bremse

Unter **Fokus / Taster → Motoren halten** wird `$1=255` geschrieben. Die Schrittmotoren bleiben nach dem Stillstand im Haltestrom, soweit Treiberstrom, Temperatur und Controllerzustand das erlauben. **Handbewegung** sendet bei freier Maschine `M5` und **`$SLP`**. Der grblHAL-Schlafmodus deaktiviert die Motor-Treiber ausdrücklich; `$1=0` allein würde bei bereits stehenden Motoren nicht unbedingt sofort ein Abschaltsignal auslösen. Das HMI verwirft die Positionsreferenz und zeigt **Aufwecken** an. Ein zweites Tippen sendet einen Controller-Reset (Ctrl-X) und erfordert danach eine neue XYZ-Referenzfahrt. **Auch eine Wiederaufnahme ohne Homing ist nicht als positionsgenau zu betrachten.** Das ist **keine physische Bremse**: Überwindet äußere Kraft das Haltemoment, verliert die offene Schrittkette Schritte, ohne dass das Board es feststellen kann. Für eine echte Haltebremse ist zusätzliche Hardware mit sicherer Ansteuerung und meist Positionsrückmeldung notwendig.

## Touch auf das Live-Arbeitsfeld

Die 210×210-Ansicht besitzt eine transparente aktive Touchfläche. Nach erfolgreichem Homing, bei verfügbarer `MPos`, aktivem `$20` und bekannten `$130/$131/$132` wird die angetippte XY-Position in Maschinenkoordinaten (`G53`) abgebildet und mit einer 1-mm-Randreserve innerhalb der gemessenen Grenzen gehalten. Das HMI sendet `M5` und danach ein `G53 G0 X… Y…`. Ein nicht referenzierter oder mit einem externen Host beschäftigter Controller wird nicht für lokales Verfahren übernommen. Die Route ist damit **keine Hinderniserkennung**: vor der XY-Fahrt muss ausreichend Z-Freiheit bestehen. Das antippbare Quadrat ist eine grafische normierte Ansicht; das Seitenverhältnis der realen Fläche wird rechnerisch berücksichtigt.

## Parametervielfalt im HMI

Der gruppierte HMI-Katalog liest die tatsächlich vom SKR mit `$$` gemeldeten Werte und enthält Schrittpuls (µs), Schrittpuls- und Motor-Inversion, Motor-Haltestrom, Endstop-/Probe-Polarität, X/Y/Z-Schritte pro Millimeter, X/Y/Z-Höchstgeschwindigkeit, X/Y/Z-Beschleunigung, Verfahrwege, Homing-Such- und Tastgeschwindigkeit, Homing-Entprellung/Freifahrt, Laser-Leistungs-Minimum/Maximum, `$32` Lasermodus, `$33` PWM-Frequenz, Statusmasken und weitere Firmwareoptionen. TMC-Strom/Mikroschritte werden **nur gezeigt, wenn das SKR die entsprechenden erweiterten Parameter tatsächlich meldet**; mit dem installierten Firmwareprofil darf die Existenz des Motor-Plugins nicht vorausgesetzt werden. Für weitere Nummern gibt es im Setup den GRBL-Parametereditor `$ID=Wert`, der den Controller quittieren lässt.

## Fehlerdiagnose Revision 24.10.2026: Z-Lift / Parameter / Haltemoment

Ein früherer HMI-Build zeigte nach Z-Homing endlos **`Z-Lift wartet auf MPos, Z-Weg und Soft Limits.`**. Grund: Der automatische Z-Rückzug setzte fälschlich vollständige X/Y-Verfahrweg-Parameter voraus und behielt `postHomePending` in einer wiederholten Warte-/Meldeschleife. Zugleich überschrieb der alte `refreshSizeFields()` nach Eingabeschluss nicht fokussierte XY/Z-Textfelder mit den vorherigen `$$`-Werten. Einige Setzen-Aktionen meldeten Erfolg schon **vor** dem bestätigenden `ok`.

Die HMI-Firmware verwaltet die Eingaben jetzt als **ungespeicherte Änderungen**, bis alle drei `$130/$131/$132` geschrieben und per `$$` gelesen und verglichen wurden. Die gleiche GRBL-Bestätigung gilt für den Roh-Parametereditor, Homing-/Limitwerte und `$1=255` für Haltestrom. Fehlermeldungen werden nicht mehr pauschal als Erfolg ausgegeben. Antworten auf normale Einstellungsskripte erhalten ein Timeout, damit ein unterbrochener UART-Austausch nicht alle weiteren HMI-Aktionen blockiert.

**Z-Rückzug nach erfolgreichem Homing:** Die HMI prüft separat `MPos`, Z-Verfahrweg `$132`, Soft-Limit `$20` und die angeforderte Zielposition innerhalb der tatsächlichen Z-Grenzen. X/Y-Werte sind für eine reine Z-Fahrt nicht zusätzlich Voraussetzung. Bei unbekannten Werten wird **einmalig** die konkrete fehlende Voraussetzung angezeigt; die Schleife wird beendet. Ein Z-Rückzug wird **nicht** blind ohne Homing und gemessene Grenzen durchgeführt. Wird der positive 7-mm-Rückzug bei einer aktuellen Position nahe dem oberen Z-Endstop (`Z=-1` in einem `-Weg…0`-Koordinatensystem) verlangt, kann `+7` außerhalb der Verfahrgrenze liegen. Das bedeutet **nicht**, dass wir automatisch `-7` fahren dürfen: Vorzeichen nur nach Prüfung der physischen Endstop-Anordnung einstellen.

Unter **Fokus / Taster → Probe konfigurieren** ist dazu ein **Z-Test 0,5 mm** implementiert, mit dem bei *physisch stromlosem Laser*, korrekt referenzierter Maschine und aktivierten Soft Limits zunächst die Bewegungsrichtung beobachtet werden kann. Mit **Z-Richtung OK** bestätigt der Bediener die überprüfte Richtung ausdrücklich. Eine Änderung am Z-Rückzugswert hebt diese Bestätigung wieder auf. Der automatische Z-Rückzug wartet fortan nicht unendlich und wird ohne diese Bestätigung nicht ausgeführt. Damit ist die Testbestätigung ein **Bediener-Check**, keine automatische Drehrichtungserkennung.

**Motor-Halten:** Der Button setzt weiterhin `$1=255`, wertet nun aber den per `$` gelesenen Motor-Haltewert aus und meldet das Ergebnis. **Beim neuen HMI-Homing wird `$1=255` vor `$H` gesetzt**, damit die Achstreiber nach dem Bewegungsende nicht bereits von einer alten Idle-Zeit abgeschaltet sind. Ein reines `$1=255` nach bereits abgeschaltetem Treiber kann die Enable-Ausgänge erst nach dem nächsten Bewegungsvorgang beeinflussen. Dieser Controllerwert garantiert **kein** physisches Haltemoment. Prüfe im stromlosen Laser-Test die Versorgung der TMC2209-Treiber, ENABLE-Polarität und den tatsächlichen Motor-/Haltestrom. Ein Schrittmotor mit zu geringem Haltestrom ist durch äußere Kraft weiterhin verstellbar. Nicht versuchen, eine Achse gewaltsam am Haltemoment zu testen. Die HMI zeigt unter WLAN/System zusätzlich die GRBL-Werte `$1`, `$20` und `$132` an.

**Testabfolge ohne Laserenergie:** Zuerst im HMI **Setup → $$ Lesen** die realen `$1`, `$20`, `$130`, `$131`, `$132` kontrollieren; gemessene Achswege erst danach über die Felder **Speichern**; sicherstellen, dass der SKR bestätigt; Soft Limits bei geprüften Endschaltern aktivieren; dann XYZ referenzieren; Z-Test mit wenigen Zehntelmillimetern in bekannter Richtung; **Z-Richtung OK**; anschließend Auto-Z unter **Fokus/Taster** freigeben und unter Aufsicht testen. Wenn das HMI den Wert bestätigt, Motoren aber nicht halten, ist weitere Hardware-/Treiberdiagnose nötig.

Dies sind Quellcode- und Buildtests; eine reale Bewegungsprüfung auf der Maschine ist dadurch **nicht** ersetzt.

## Revision 24.10.2026: Positive HMI-Koordinaten und Z-Zielposition 7 mm

grblHAL verwendet standardmäßig einen **negativen Maschinenkoordinatenraum** von ungefähr `-Verfahrweg` bis `0`. Nach `$H` und einem `$27=1`-mm-Schalterrückzug kann die Rohposition deshalb beispielsweise `MPos Z=-1,00` sein, obwohl Homing und Bewegungsrichtung korrekt sind. **Das ist kein Vorzeichenfehler der Schrittmotoren.**

Das HMI zeigt bei der Grundeinstellung **`zero_at_max=true`** die positive Entfernung vom Maschinenreferenzpunkt:
`X_display=-MPos.X`, `Y_display=-MPos.Y`, `Z_display=-MPos.Z`. Beispiel: `MPos:-1,-1,-1` wird `X:+1,00 Y:+1,00 Z:+1,00`. Diese Umrechnung findet **nur** in der Bedienoberfläche und in den zusätzlich angebotenen `display_x_mm/display_y_mm/display_z_mm`-JSON-Feldern statt. Die nativen Werte `coordinates.x_mm/y_mm/z_mm`, Maschinenstatus und G-Code/LightBurn bleiben unverändert. Die bestehende XY-Arbeitsfeldkarte arbeitet weiterhin mit echten MPos-Werten.

Der HMI-Wert **Z-Rückzug 7 mm** ist jetzt eine **absolute positive Zielposition gemessen vom Maschinenreferenzpunkt**, nicht ein additiver relativer Hub nach der bereits ausgeführten Schalterfreifahrt. Beispiel: Z direkt nach Homing zeigt `+1,00` (MPos `-1,00`); Ziel Z `+7,00` entspricht MPos `-7,00`, also nur noch einem **6-mm-Bewegungsbefehl**. Motorpolung `$3` und Homingrichtung `$23` bleiben dabei unverändert.

Eine Z-Fahrt wird nur bei erfolgreichem Homing, gültiger Live-Maschinenposition, bekannter tatsächlicher Z-Verfahrlänge `$132`, freier GRBL-Steuerung und Ziel **innerhalb** des überprüften Maschinenraums ausgeführt. Für die aus dem HMI angeforderte, lokal begrenzte Z-Freifahrt ist `$20=1` nicht mehr zwingend, obwohl eingeschaltete Soft Limits im SKR ausdrücklich empfohlen bleiben. Wenn `$132` oder `MPos` fehlt, wird der spezifische fehlende Wert angezeigt statt einer endlosen Wartemeldung. Laser-Aus wird vor der Z-Bewegung gesendet.

**Wichtig:** Die 7 mm sind zunächst der Bezug zu der über den Endschalter festgelegten Z-Maschinenreferenz. Ob sie genau **7 mm optischen Abstand zum Werkstück** ergeben, ist eine andere Frage und muss mit dem Taster-/Werkstück-Offset kalibriert werden. Die neue Umrechnung ändert keine Motorpins und ist nicht die Einführung eines neuen GRBL-Koordinatensystems für LightBurn.
