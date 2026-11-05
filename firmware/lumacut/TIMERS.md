# Timer- und Interrupt-Belegung

Takt: HSE 8 MHz, PLL ×9 = 72 MHz. APB2 72 MHz (TIM1, TIM8), APB1 36 MHz, Timer an APB1 damit 72 MHz (TIM2). USB 48 MHz.

## Timer

| Timer | Aufgabe | Pin | Einstellung | Interrupt |
|---|---|---|---|---|
| TIM1 CH2 | Laser-PWM | PA9 | PWM1, PSC 281, ARR 254 = 1001 Hz. Vergleich 0..255: 0 nie high, 255 > ARR immer high. Preload an (OC2PE, ARPE), MOE gesetzt, Break aus | keiner |
| TIM8 CH3 | Licht | PC8 | wie TIM1, 1001 Hz, MOE gesetzt | keiner |
| TIM2 | Schritt-Takt | keiner | PSC 35 = 2 MHz (0,5 µs), ARR ohne Preload, Ein-Intervall pro Tick | Update, Priorität 0 |
| SysTick | ms-Zähler | keiner | 1 kHz | Priorität 0x80 |

TIM3, TIM4, TIM5, TIM6, TIM7 sind frei. UART4 (TMC) läuft ohne Interrupt, in der Hauptschleife abgefragt.

## Prioritäten (kleiner = wichtiger)

| Priorität | Quelle | Laufzeit und Wirkung |
|---|---|---|
| fest | HardFault, NMI, MemManage, BusFault, UsageFault | setzen Stack neu, schalten Ausgänge per Register aus, Reset |
| 0x00 | TIM2 Schritt-Interrupt | unterbricht alles andere, unter 5 µs je Tick (Annahme, ohne Oszilloskop nicht gemessen) |
| 0x80 | SysTick | ein Zähler |
| 0xC0 | USB_LP (CDC) | wird vom Schritt-Interrupt unterbrochen. M112 und M410 wirken hier beim Empfang |
| keine | Hauptschleife | Planer, Befehle, TMC, Flash, Watchdog-Bedienung |

Kritische Abschnitte sperren nur wenige Befehle lang (Laserwert setzen, Stepper starten). Kein Interrupt läuft auf Schrittzeit-Dauer gesperrt, außer beim Flash-Kopieren im Stillstand.

## Warum nichts das PWM stört

- TIM1 läuft in Hardware. Kein Interrupt und kein Hauptschleifen-Code fasst den Zähler an; M114, USB und TMC berühren TIM1 nicht.
- Nur `hal_laser_pwm` schreibt `CCR2`, und nur bei Blockstart, Blockende, M3/M5 oder Abschaltung. Änderungen zwischen zwei Werten > 0 greifen durch Preload am Periodenende. Der Wechsel von oder auf 0 löst ein Update (UG) aus: Der Strahl geht sofort aus und startet mit voller erster Periode.
- `M114` liest nur Variablen des Hauptprogramms, nicht einmal die Schrittzähler.

## Reihenfolge nach Reset (Regel 1)

1. `reset_handler` setzt den Stack, `board_start` schaltet als Erstes per Register PA9, PC6, PC8, PC9 auf Ausgang Low und hält TIM2 an. Kein RAM-Inhalt, kein Takt und kein Bootloader-Rest wird vorausgesetzt.
2. Interrupts aus, NVIC und SysTick leer, Vektortabelle auf `0x08007000`, `.data` und `.bss`.
3. Takt über HSI neu aufsetzen (der Bootloader kann schon auf der PLL laufen), TIM1, TIM8, TIM2, UART4, USB zurücksetzen.
4. TIM1 und TIM8 starten mit Vergleich 0 (UG lädt die Schatten), MOE an. **Erst danach** werden PA9 und PC8 auf Timer-Ausgang umgestellt.
5. EN der Treiber High, dann Ausgang. D+ für den Host abziehen (PA14 High und PA12 Low), Watchdog, Interrupts.

## Schritt-Timing (TMC2209)

Datenblatt: STEP high und DIR-Vorlauf je mindestens 20 ns; Vertrag: je 100 ns.

- STEP high: `GPIOB_BSRR`, dann feste 36 NOP (≥ 500 ns, ein NOP kann nicht schneller als ein Takt sein), dann die Rechenarbeit, erst dann Low.
- DIR ändert sich nur beim Laden eines Blocks, und nur nach STEP Low plus 8 NOP (≥ 111 ns). Der nächste STEP folgt frühestens 8 Timer-Ticks (4 µs) später (`ARM_MARGIN`), im Betrieb nach einem vollen Intervall.
- Höchstrate 15 kHz je Achse: Der Planer begrenzt die Hauptachse; das Intervall wird aufgerundet, die Rate liegt nie darüber.

## Warten, Grenzen

- Intervalle über 60000 Ticks (30 ms) laufen in Stücken, so gehen auch sehr langsame Vorschübe und `G4`.
- Reißt der Vorrat an fertig geplanten Blöcken ab (Hauptschleife zu spät), wartet der Interrupt in 100-µs-Schritten mit Laser 0. Das ist ein Ruckler, kein Fehler, und bei den eingeplanten 15 ms Vorlauf nur bei blockierter Hauptschleife denkbar.
