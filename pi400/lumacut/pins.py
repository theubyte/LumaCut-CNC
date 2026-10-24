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
    "M8": {"pin": "PC6", "connector": "FAN0", "kind": "24V low-side MOSFET"},
}
PINS = (
    ("PA1", "Laser PWM", "laser_pwm", "reserved"),
    ("PC9", "BED laser supply", "laser_supply", "reserved"),
    ("PC8", "HE0 / M7", "accessory", "assignable"),
    ("PC6", "FAN0 / M8", "accessory", "assignable"),
    ("PC7", "FAN1 spare", "spare", "firmware support required"),
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
            "M7 und M8 sind die einzigen zur Laufzeit logisch zuweisbaren Zubehörkanäle.",
            "Die physische STM32-Pinbelegung ist weiterhin im grblHAL-Build festgelegt.",
            "FAN0, HE0 und BED sind MOSFET-Leistungsausgänge, keine Logik-GPIOs.",
            "Laserfreigabe und Not-Aus müssen hardwareseitig unabhängig wirken.",
            "PC7 ist derzeit nicht als dynamischer Ausgang im SKR-Protokoll implementiert.",
        ],
    }


def accessories_for_roles(physical, roles):
    mapping = {"M7": bool(physical.get("lights")),
               "M8": bool(physical.get("exhaust"))}
    return {name: mapping[channel] for name, channel in effective_roles(roles).items()}


def override_for_role(role, roles):
    channel = effective_roles(roles)[role]
    return bytes((0xA1,)) if channel == "M7" else bytes((0xA0,))
