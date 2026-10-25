"""Machine connection for the native LumaCut Studio (Pi 400 / Marlin API).

Layers:
    client  – plain HTTP client for the Pi API, no Qt dependency
    worker  – non-blocking status polling and command execution (Qt threads)
    settings – persisted connection settings (QSettings)
    panel   – the "Maschine" widget used by the main window
"""
