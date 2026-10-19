# Annahmen und noch offene Fragen

**Bestätigt aus Projektkontext:** Atomstack A5 Pro; LaserTree LT-80W-AA-Pro; SKR Mini MZ V1.0 STM32F103RC TMC2209; Waveshare ESP32-S3-Touch-LCD-7 Rev1.2; USB zu LightBurn; keine Pi-Laufzeitabhängigkeit.

**Nur Kandidaten / nicht elektrisch geprüft:** PC2 Z-Endschalter, PC14 Taster, PA1 PWM, EXP1 UART, UART-TTL-Weg, RS485-Fallback. Y-/Z-TMC-Konfiguration ist gegenüber SKR Mini E3 V2 zu untersuchen.

**Nicht bekannt:** Arbeitsraum, Z-Richtung, Fokusdistanz, Taster-X/Y/Z-Offset, mechanische Endlagen, Schlüssel-/Interlock-Beschaltung, Air Assist/Absaugung und optischer Datums-Bezug.

**Wichtige Designentscheidung:** Edge-Offsets in Maschinen- und Werkstückkoordinaten, Laserhead- und Tastpunkt-Grenzprüfung, getrennter Z-Home und Surface-Probe. Kein generisches grblHAL-Plugin verspricht von selbst eine dauerhafte Höhenkarte.