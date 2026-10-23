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

**Motor-Halten:** Der Button setzt weiterhin `$1=255`, wertet nun aber den per `$$` gelesenen Motor-Haltewert aus und meldet das Ergebnis. Dieser Controllerwert garantiert **kein** physisches Haltemoment. Prüfe im stromlosen Laser-Test die Versorgung der TMC2209-Treiber, ENABLE-Polarität und den tatsächlichen Motor-/Haltestrom. Ein Schrittmotor mit zu geringem Haltestrom ist durch äußere Kraft weiterhin verstellbar. Nicht versuchen, eine Achse gewaltsam am Haltemoment zu testen. Die HMI zeigt unter WLAN/System zusätzlich die GRBL-Werte `$1`, `$20` und `$132` an.

**Testabfolge ohne Laserenergie:** Zuerst im HMI **Setup → $$ Lesen** die realen `$1`, `$20`, `$130`, `$131`, `$132` kontrollieren; gemessene Achswege erst danach über die Felder **Speichern**; sicherstellen, dass der SKR bestätigt; Soft Limits bei geprüften Endschaltern aktivieren; dann XYZ referenzieren; Z-Test mit wenigen Zehntelmillimetern in bekannter Richtung; **Z-Richtung OK**; anschließend Auto-Z unter **Fokus/Taster** freigeben und unter Aufsicht testen. Wenn das HMI den Wert bestätigt, Motoren aber nicht halten, ist weitere Hardware-/Treiberdiagnose nötig.

Dies sind Quellcode- und Buildtests; eine reale Bewegungsprüfung auf der Maschine ist dadurch **nicht** ersetzt.
