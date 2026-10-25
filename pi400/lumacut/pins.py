"""SKR Mini MZ v1.0 electrical capability map.

Physical signal ownership stays in firmware. The Pi is the single policy,
authorization and orchestration authority. Only implemented, nonconflicting
firmware-controlled accessory channels can be assigned in this release.
Pins reserved for motion, hard limits, USB and laser safety cannot be
repurposed by the web UI.
"""
from __future__ import annotations

DEFAULT_ROLES = {"lights": "M7", "exhaust": "M8"}
ASSIGNABLE = {
    "M7": {"pin": "PC8", "connector": "HE0", "kind": "24V low-side MOSFET"},
    "M8": {"pin": "PC9", "connector": "BED", "kind": "24V low-side MOSFET"},
}
PINS = (
    ("PA1", "Laser PWM", "laser_pwm", "reserved"),
    ("PC9", "BED / M8 exhaust", "accessory", "assignable"),
    ("PC8", "HE0 / M7", "accessory", "assignable"),
    ("PC6", "FAN0 / $LCIO", "digital_output", "assignable"),
    ("PC7", "FAN1 laser supply enable", "laser_supply", "reserved"),
    ("PC2", "Z limit", "hard_limit", "reserved"),
    ("X-STOP", "X limit connector", "hard_limit", "reserved"),
    ("Y-STOP", "Y limit connector", "hard_limit", "reserved"),
    ("PC10/PC11", "TMC2209 UART", "stepper_bus", "reserved"),
    ("PA11/PA12", "USB data", "usb", "reserved"),
    ("STEP/DIR/EN", "X, Y, Z stepper signals", "motion", "reserved"),
)


def validate_roles(value):
    """Require a bijection: never drive both accessories from one channel."""
    if not isinstance(value, dict) or set(value) != set(DEFAULT_ROLES):
        raise ValueError("Es müssen genau LEDs und Abluft konfiguriert sein")
    if set(value.values()) != set(ASSIGNABLE):
        raise ValueError("Nur eine eindeutige Zuordnung M7 / M8 ist erlaubt")
    return dict(value)


def effective_roles(value):
    try:
        return validate_roles(value)
    except ValueError:
        return dict(DEFAULT_ROLES)


def manifest(roles):
    roles = effective_roles(roles)
    return {
        "board": "BTT SKR Mini MZ V1.0 / STM32F103RC",
        "mode": "Pi control plane / grblHAL real-time executor",
        "roles": roles,
        "channels": ASSIGNABLE,
        "pins": [{"pin": pin, "function": function, "class": group,
                  "availability": availability}
                 for pin, function, group, availability in PINS],
        "limitations": [
            "M7/M8 unterstützen logische Rollentausch-Konfiguration.",
            "PC6/FAN0 unterstützt über die neue STM32-Firmware $LCIO=0/1 und $LCIO-Abfrage.",
            "Die physische STM32-Pinbelegung ist weiterhin im grblHAL-Build festgelegt.",
            "FAN0, FAN1, HE0 und BED sind MOSFET-Leistungsausgänge, keine Logik-GPIOs.",
            "Laserfreigabe und Not-Aus müssen hardwareseitig unabhängig wirken. FAN1-Minus braucht eine isolierte PWM-Schnittstelle zu PA1.",
            "Nicht vorhandene und sicherheitsrelevante GPIOs lassen sich nicht als frei verfügbaren Pin zuweisen.",
        ],
    }


def accessories_for_roles(physical, roles):
    mapping = {"M7": bool(physical.get("lights")),
               "M8": bool(physical.get("exhaust"))}
    return {name: mapping[channel] for name, channel in effective_roles(roles).items()}


def override_for_role(role, roles):
    channel = effective_roles(roles)[role]
    return bytes((0xA1,)) if channel == "M7" else bytes((0xA0,))


SPARE_PC7_ROLES = ("custom", "air_assist", "worklight", "signal", "exhaust2")


def validate_spare_config(data):
    """Only the one board-verified spare output may receive a custom role."""
    if not isinstance(data, dict):
        raise ValueError("Ungültiges GPIO-Profil")
    if set(data) != {"pin", "role", "name"}:
        raise ValueError("Unbekannte GPIO-Konfigurationsfelder")
    if data["pin"] != "PC6" or data["role"] not in SPARE_PC7_ROLES:
        raise ValueError("Nur freier Ausgang PC6 mit gültigem Funktionsprofil")
    name = data["name"]
    if not isinstance(name, str) or not 1 <= len(name) <= 24:
        raise ValueError("Name des Ausgangs: 1–24 Zeichen")
    if not all(ch.isalnum() or ch in " -_" for ch in name):
        raise ValueError("Im Namen nur Buchstaben, Zahlen, Leerzeichen, - und _")
    return {"pin": "PC6", "role": data["role"], "name": name.strip()}


DEFAULT_SPARE = {"pin": "PC6", "role": "custom", "name": "FAN0 Zusatzgerät"}
