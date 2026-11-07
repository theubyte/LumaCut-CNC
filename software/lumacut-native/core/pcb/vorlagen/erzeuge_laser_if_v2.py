"""Builds laser-interface-v2.lumaraster from hardware/laser-interface-v2/lochraster_liste.txt (output of
build_perfboard.py) and checks every pin against the list before writing.

    python erzeuge_laser_if_v2.py [path/to/lochraster_liste.txt]

Board as in build_perfboard.py: 90 x 70 mm lying across, 32 columns (A..Z, A'..F') x 26 rows (A..Z), pitch 2.54,
grid centred, corner holes 2 mm from the edges. Hole name = column + row, e.g. GS = column G, row S.
Values are those the owner built on 04.11.2026, not the plan's (see BUILT below).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIST = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"A:\LumaCut\LumaCut-CNC-android\hardware\laser-interface-v2\lochraster_liste.txt")
LIB = json.loads((HERE.parent / "perfboard_parts.json").read_text(encoding="utf-8"))["parts"]
COLS, ROWS = 32, 26


def hole(name):
    m = re.fullmatch(r"([A-Z]'?)([A-Z])", name)
    assert m, name
    c = ord(m.group(1)[0]) - 65 + (26 if m.group(1).endswith("'") else 0)
    r = ord(m.group(2)) - 65
    assert 0 <= c < COLS and 0 <= r < ROWS, name
    return c, r


def name(c, r):
    return chr(65 + c % 26) + "'" * (c // 26) + chr(65 + r)


def pins_of(lib_id, at, rot):
    part = next(p for p in LIB if p["id"] == lib_id)
    pins = []
    for c0, r0, dc, dr, n in part["pins"]:
        for i in range(n):
            pins.append((c0 + i * dc, r0 + i * dr))
    out = []
    for c, r in pins:
        for _ in range(rot % 4):
            c, r = -r, c
        out.append((at[0] + c, at[1] + r))
    return out


# ref: library part, value as built, hole of library pin 1, quarter turns, list pin number for each library pin
PLACE = {
    "C1": ("cap-508", "100n", "VO", 1, ["1", "2"]),
    "C2": ("cap-508", "1µ", "RS", 1, ["1", "2"]),
    "C3": ("elko-254", "47µ", "XO", 1, ["1", "2"]),
    "D1": ("diode", "1N4007", "GJ", 3, ["2", "1"]),        # KiCad pad 1 is the cathode; ours is the anode
    "F1": ("fuse-5x20", "2A T", "PC", 0, ["1", "1", "2", "2"]),
    "J1": ("term-2", "Netzteil", "D'E", 3, ["1", "2"]),
    "J2": ("term-3", "Laser", "D'R", 3, ["1", "2", "3"]),
    "J3": ("term-2", "SKR BL_Touch", "CR", 1, ["1", "2"]),
    "J4": ("term-2", "SKR FAN1", "CF", 1, ["1", "2"]),
    "K1": ("relay-g5le", "NAIS JS1-24V", "II", 0, ["1", "2", "3", "4", "5"]),
    "LED1": ("led-3", "LED", "A'T", 0, ["2", "1"]),       # KiCad pad 1 is the cathode; ours is the anode
    "R1": ("res-1016", "680", "GS", 0, ["1", "2"]),
    "R4": ("res-1016", "2k2", "YX", 3, ["1", "2"]),
    "R5": ("res-1016", "5k6", "A'O", 1, ["1", "2"]),
    "R6": ("res-254", "220", "TS", 0, ["1", "2"]),
    "R7": ("res-254", "680", "UT", 1, ["1", "2"]),
    "U1": ("dip4", "SFH618A/PC817", "MS", 0, ["1", "2", "3", "4"]),
    "U2": ("to220", "LM317T", "UQ", 2, ["1", "2", "3"]),
}
BUILT = {"R5": ("4k7", "5k6"), "C2": ("100n", "1µ"), "C3": ("10u", "47µ"), "K1": ("G5LE-1 24VDC", "NAIS JS1-24V")}

text = LIST.read_text(encoding="utf-8")
parts_txt, wires_txt = text.split("DRAEHTE")
listed = {}
for line in parts_txt.splitlines():
    m = re.match(r"\s+(\S+)\s+(.+?)\s+((?:\d+:\S+\s*)+)$", line)
    if m:
        listed[m.group(1)] = (m.group(2).strip(), [tuple(x.split(":")) for x in m.group(3).split()])
assert set(listed) == set(PLACE), (set(listed) ^ set(PLACE))

parts, pin_holes, notes = [], {}, []
for ref, (lib_id, value, at, rot, numbers) in PLACE.items():
    plan_value, plan_pins = listed[ref]
    want_value = BUILT.get(ref, (plan_value, plan_value))[0]
    assert plan_value == want_value, (ref, plan_value, want_value)
    assert value == BUILT.get(ref, (plan_value, plan_value))[1], (ref, value)
    got = pins_of(lib_id, hole(at), rot)
    expect = [hole(h.rstrip("~")) for _, h in plan_pins]
    by_num = {}
    for num, g in zip(numbers, got):
        by_num.setdefault(num, set()).add(g)
    for num, h in plan_pins:
        assert hole(h.rstrip("~")) in by_num[num], (ref, num, h, [name(*x) for x in by_num[num]])
    assert sorted(got) == sorted(expect), (ref, got, expect)
    if any(h.endswith("~") for _, h in plan_pins):
        notes.append(ref)
    pin_holes[ref] = {num: sorted(by_num[num]) for num in by_num}
    parts.append({"id": ref.lower(), "part": lib_id, "ref": ref, "value": value, "col": hole(at)[0], "row": hole(at)[1], "rot": rot})

wires = []
for line in wires_txt.splitlines()[1:]:
    m = re.match(r"\s+(\S+)\s+(.+?)(?:\s+\[(.+)\])?$", line)
    if not m:
        continue
    net, path, flags = m.group(1), m.group(2), m.group(3) or ""
    pts = []
    for p in path.split(" -> "):
        k = re.fullmatch(r"(\w+)-Pin(\d)", p)
        pts.append(list(pin_holes[k.group(1)][k.group(2)][0]) if k else list(hole(p)))
    w = {"id": "w%d" % (len(wires) + 1), "side": "loet", "points": pts, "net": net}
    if "dick" in flags:
        w["width"] = 1.4
    wires.append(w)

PITCH, X0, Y0 = 2.54, (90 - 31 * 2.54) / 2, (70 - 25 * 2.54) / 2
gx = lambda c: X0 + c * PITCH
gy = lambda r: Y0 + r * PITCH
right, left = (gx(31) + 0.85 + 90) / 2, (gx(0) - 0.85) / 2
top, bottom = (gy(0) - 0.85) / 2, (gy(25) + 0.85 + 70) / 2
labels = [
    ("+24V", right, gy(2)), ("GND", right, gy(4)), ("+24V", right, gy(13)), ("GND", right, gy(15)), ("PWM", right, gy(17)),
    ("FAN+", left, gy(5)), ("FAN-", left, gy(7)), ("PA1", left, gy(17)), ("GND", left, gy(19)),
    ("J1 Netzteil", gx(29), top), ("J4 SKR FAN1", gx(2) + 3, top),
    ("J3 SKR BL_Touch", gx(2) + 5, bottom), ("J2 Laser", gx(29), bottom), ("LumaCut Laser-IF V2", 45, bottom),
]
design = {
    "format": "lumaraster", "version": 2, "title": "Laser-Interface V2",
    "note": "Wie am 04.11. gebaut: Relais NAIS JS1-24V statt G5LE-1, andere Pinbelegung: Pins vor dem Verdrahten messen. "
            "R5 5,6 kΩ, C1 100 nF, C2 1 µF, C3 Elko 47 µF, U2 LM317T mit R6 220 Ω und R7 680 Ω. "
            "Noch nicht lasern: Z-Antrieb unzuverlässig, Materialtest auf Lötstopplack fehlt.",
    "board": {"name": "Laser-Interface V2, 90 × 70", "width": 90, "height": 70, "pitch": 2.54, "cols": COLS, "rows": ROWS,
              "padDia": 1.7, "holeDia": 1.0, "mountDia": 2.0, "mountInset": 2.0, "edgeRows": False, "rowLetters": True},
    "parts": parts, "wires": wires,
    "labels": [{"id": "t%d" % (i + 1), "text": t, "x": round(x, 3), "y": round(y, 3), "height": 1.2, "side": "bestueckung"} for i, (t, x, y) in enumerate(labels)],
    "holeNumbers": False, "markRefs": True, "markValues": True,
}
out = HERE / "laser-interface-v2.lumaraster"
out.write_text(json.dumps(design, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("geschrieben", out, "-", len(parts), "Bauteile,", len(wires), "Drähte; Pins neben dem Raster bei:", ", ".join(notes))
