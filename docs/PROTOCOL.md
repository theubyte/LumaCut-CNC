# HMI-Protokoll und Quellen-Arbitration

LightBurn spricht direkt mit grblHAL am SKR über USB. Waveshare ESP32-S3 stellt Touch-Oberfläche dar und ist keine eigenständige zweite G-Code-Streaming-Instanz.

Geplant:
- HMI erhält Statuszustände IDLE, HOMING, PROBING, RUN, HOLD, ALARM, ESTOP; Ausgabe mit Positionskoordinaten und Quelle.
- Benutzer kann nur in IDLE gezielte Job- oder Maschinenbefehle anfordern; während RUN ausschließlich rechtlich und technisch geeignete Hold/Stop-Interaktion.
- Eingaben werden am Steuerungs-Firmwareende validiert; Touch-Kommandos niemals ungeprüft als raw G-Code einspeisen.
- Hardware-Not-Aus benötigt keine serielle Kommunikation.
- Read-only Status polling darf laufenden G-Code nicht blockieren.
- Verbindungsausfall, Neustart, UART-Überlauf, Störungen und USB-Reconnect dürfen weder Bewegungen starten noch Laser aktivieren.
- Protokollversion, Nachrichtengröße, CRC und Watchdog werden im kommenden Firmwarezweig definiert.

Transport: geprüfter TTL UART-Header oder RS485 mit eigenem Transceiver. Direkte Verdrahtung ESP32 RS485 ↔ SKR TTL zerstörungsgefährdet.

Umsetzung noch nicht vorhanden.