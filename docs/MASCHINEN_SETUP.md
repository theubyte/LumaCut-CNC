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

Der Button **Limits EIN** sendet bei bekanntem X/Y/Z-Weg `$22=1` und `$20=1`. Soft Limits benötigen kalibrierte Schritte/mm, überprüfte Richtungen und erfolgreiche Referenzfahrt. Hard Limits (`$21`) sind eine zusätzliche, separat zu prüfende Sicherheitsfunktion. Die HMI-Grundfunktionen verweigern eigene Job-, Jog-, Rahmen- und Parkbewegungen, wenn aktuelle Positionsdaten, Homing oder Soft Limits fehlen. Der SKR bleibt für seine eigenen Limitmeldungen und Alarme zuständig. Software kann **keine absolute Garantie** geben, dass der Laser nie mechanisch überfährt (z. B. nach Schrittverlust, Fehlkonfiguration oder Treiberfehler).

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
