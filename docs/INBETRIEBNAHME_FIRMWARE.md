# Inbetriebnahme der eigenen Firmware

Die Firmware lief bis jetzt nur am PC (Host-Tests, Build, CI). Alles in `firmware/lumacut/src/hw` läuft hier zum ersten Mal auf dem Chip.
Rechne mit Korrekturen. Wir gehen zusammen vor, jeder Schritt braucht ein Go, und bei einem Fehler bleiben wir stehen.

**Abbilder auf dem PC (`A:\mfw\lumacut-fw\`):**

| Datei | Zweck | SHA-256 |
|---|---|---|
| `firmware.bin` | eigene Firmware 0.2.0 (Commit 4566d10) | `fd1c115f…88aa` |
| `marlin-62-firmware.bin` | Rückweg: Marlin marlin-62 | `c8338e92…3e4e` |

Bereitlegen: FAT32-microSD, Multimeter, Hand am Not-Aus. Vor dem ersten Einschalten: **Laserdiode abgesteckt** und Z von Hand tief gestellt.

## Vorstufe: Web, Pi-Betrieb, Panel 1.3 (noch mit Marlin)

Damit sind neue Oberfläche und Dienst geprüft, bevor die Firmware wechselt. Das ist der Stand von `main`.

- [ ] `sudo bash /opt/lumacut/pi400/update.sh` im Leerlauf. Rollt selbst zurück, wenn der Dienst nicht startet.
- [ ] Web öffnen und neu laden, SKR verbunden, Kamera, Panel, Linienlaser arbeiten mit der gehärteten Dienstdatei.
- [ ] Panel 1.3: Bild, Touch, Seite System.
- [ ] `sudo -n systemctl restart lumacut-marlin.service` im Leerlauf: läuft, Laser bleibt aus.

## Wechsel (Pi und Firmware gehören zusammen)

Der neue Pi-Stand lehnt Marlin ab, der alte lehnt die neue Firmware ab. Darum beides direkt nacheinander.

1. [ ] Claude führt `eigene-firmware` in `main` zusammen und bringt den Stand auf den Pi. Der nächtliche Update-Lauf holt `main`, also zeigt `main` ab hier auf die neue Firmware.
2. [ ] 24 V **und** USB am SKR aus. `firmware.bin` ins Hauptverzeichnis der SD, Karte ins SKR, einschalten. Danach heißt die Datei `FIRMWARE.CUR`.
3. [ ] Pi verbindet sich von selbst. Web unter System: Kennung `LumaCut CNC 0.2.0`.

Kommt kein USB: nichts weiter versuchen, sondern Rückweg (unten) oder Messung mit Claude. SWD ist im Betrieb abgeschaltet, die Karte ist die Rettung.

## Schritte an der Maschine

| # | Prüfen | Erwartet |
|---|---|---|
| 1 | M115, M119, M122 unter System → Abfragen; Schalter einzeln von Hand betätigen | Kennung; `open`/`TRIGGERED` passt zum Schalter; alle drei TMC antworten |
| 2 | Relais (24 V an/aus), Licht, Abluft | jedes schaltet einzeln, Laser bleibt aus |
| 3 | PA9 gegen GND, Service-Regler, **24 V aus, Diode ab**: 0, 50, 100 % | ca. 0 / 1,65 / 3,3 V, **stehend, auch wenn das Protokoll läuft** |
| 4 | Ausgang V2 D'R, gleich wie 3, Relais an für die 5 V | ca. 0 / 2,5 / 5 V, kein Einbruch im Takt des Protokolls |
| 5 | Je Achse kleine Fahrt in Plusrichtung (Z-Test bzw. Jog) | Richtung wie bisher; Weg mit Maßband (X, Y 80, Z 1018,59 Schritte/mm). Hier zeigt sich auch, ob Schritte fehlen |
| 6 | Referenz einzeln: zuerst Z, Hand am Not-Aus, dann X, dann Y | Stoppt am Schalter, zurück, langsam wieder hin. Z-Schalter vorab von Hand testen: Mit überbrücktem Schalter erkennt die Firmware den Fehler nicht |
| 7 | Taster: G30 auf dem Bett, mehrmals | Stoppt am Kontakt, Streuung klein, Kopf bleibt dort |
| 8 | Rahmen, dann Auftrag mit S0 (Laser aus) über schnelle Strecken, Raster, Bögen | Kein Stocken, kein `Planner underrun`, Maße stimmen |
| 9 | Abbruch während Schritt 8 | Sofort Stopp (M410), Referenz bleibt |
| 10 | NOT-AUS, dann quittieren | Alles aus, M999 gibt frei, Referenz neu |
| 11 | **Diode anstecken nur bei 24 V aus**, einige Minuten nach dem Ausschalten | |
| 12 | Service-Regler mit geringem Wert auf getestetem Material, Brille, Deckel zu; eine Minute fester Wert | **Kein Flackern im Takt des Protokolls.** Ist es weiter da, liegt es nicht an der Firmware, dann suchen wir an Masse, USB und 24 V (Typenschild des Netzteils noch offen) |
| 13 | Materialtest mit neuer Leistungskurve: PWM ist jetzt echt 0–255 auf 1 kHz, alte Werte unter S72 waren verfälscht | Neue Werte je Material |
| 14 | Echter Auftrag auf getestetem Material, dabei fahren | Gleichmäßiger Strahl, kein Flackern im Takt der Achsen |
| 15 | Selbst-Update über den Pi, SD griffbereit | Build-Stempel stimmt danach, erst dann Release `lumacut-fw-1` anlegen |

Beim Parken beobachten: Löst ein Schalter kurz vor X0/Y0 aus, kann der Pi „Referenz verloren“ melden und vor dem nächsten Auftrag neu referenzieren. Das ist sicher, aber bei Häufung justieren wir.

## Rückweg zu Marlin

1. Claude setzt `main` auf den Stand vor dem Wechsel zurück und bringt ihn auf den Pi.
2. 24 V und USB aus, `marlin-62-firmware.bin` als `firmware.bin` auf die SD, einschalten.

## Noch offen, nach bestandener Inbetriebnahme

- Workflow für Release `lumacut-fw-*`; `.github/workflows/marlin.yml` und `firmware/marlin/` entfernen (der Publish-Schritt dort scheitert mit dem neuen Pi-Stand).
- `CHOPPER_DEFAULT_12V` bei 24 V übernommen wie bisher; prüfen, falls Motoren laut oder heiß sind.
- Anet- und Grbl-Zweig im Pi (`grbl_bridge.py`, `avr_flash.py`) sind nur noch Notbetrieb: entscheiden, ob sie wegkommen.
