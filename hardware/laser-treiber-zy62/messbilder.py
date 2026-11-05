#!/usr/bin/env python3
"""Measuring guides for the laser driver board ZY62 VER2 (photos with markers).

Usage: messbilder.py <top photo> <bottom photo>; writes messung_*.png next to it.
"""
import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps

HERE = pathlib.Path(__file__).resolve().parent
FONT = "C:/Windows/Fonts/arialbd.ttf"
RED, BLACK, YELLOW, WHITE = (220, 30, 30), (20, 20, 20), (255, 210, 0), (255, 255, 255)


def font(size):
    return ImageFont.truetype(FONT, size)


def crop(path, box, scale):
    """box in the 1500 px wide view of the upright photo."""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    k = im.size[0] / 1500
    part = im.crop(tuple(int(v * k) for v in box))
    return part.resize((part.width * scale, part.height * scale), Image.LANCZOS)


def marker(d, x, y, text, color=YELLOW, r=26):
    d.ellipse((x - r, y - r, x + r, y + r), outline=color, width=5)
    f = font(34)
    w = d.textlength(text, font=f)
    tx, ty = x + r + 6, y - 20
    d.rectangle((tx - 4, ty - 2, tx + w + 4, ty + 40), fill=BLACK)
    d.text((tx, ty), text, font=f, fill=color)


def meter(d, x, y, symbol, note):
    """Simple multimeter with the dial on the right setting."""
    d.rounded_rectangle((x, y, x + 300, y + 400), 24, fill=(245, 190, 30), outline=BLACK, width=4)
    d.rectangle((x + 30, y + 24, x + 270, y + 104), fill=(205, 220, 200), outline=BLACK, width=3)
    d.text((x + 44, y + 42), note, font=font(38), fill=BLACK)
    cx, cy = x + 150, y + 240
    d.ellipse((cx - 90, cy - 90, cx + 90, cy + 90), fill=(60, 60, 60), outline=BLACK, width=4)
    d.line((cx, cy, cx, cy - 86), fill=WHITE, width=10)
    w = d.textlength(symbol, font=font(50))
    d.text((cx - w / 2, cy + 94), symbol, font=font(50), fill=BLACK)


def sheet(photo, title, lines, symbol, note):
    width = max(photo.width + 360, 1500)
    height = max(photo.height, 420) + 110 + 50 * len(lines) + 30
    out = Image.new("RGB", (width, height), WHITE)
    d = ImageDraw.Draw(out)
    d.text((24, 24), title, font=font(46), fill=BLACK)
    out.paste(photo, (20, 100))
    meter(d, photo.width + 40, 110, symbol, note)
    y = max(photo.height, 420) + 120
    for line in lines:
        d.text((24, y), line, font=font(34), fill=BLACK)
        y += 50
    return out, d


def main(top, bottom):
    # 1: solder joints on the back, resistance between all pins
    photo = crop(bottom, (500, 870, 960, 1440), 2)
    pad = lambda x, y: (x * 2, y * 2)   # marker positions in pixels of the unscaled crop
    out, d = sheet(photo, "Messung 1: Rückseite, Ohm",
                   ["Netzteil aus. Messspitzen auf die Lötpunkte setzen, Farbe egal.",
                    "A-B, B-C, A-C     dann A-X, B-X, C-X     dann A-Y, B-Y, C-Y",
                    "Schreib mir alle Werte. 0 Ohm = verbunden, OL = offen.",
                    "Steigt der Wert ständig: Elko lädt sich, das ist normal."],
                   "Ohm", "0.3")
    for name, x, y in (("A", 352, 832), ("B", 403, 828), ("C", 450, 826),
                       ("X", 118, 568), ("Y", 165, 566)):
        px, py = pad(x, y)
        marker(d, 20 + px, 100 + py, name, r=18)
    out.save(HERE / "messung_1_ohm.png")

    # 2: input stage on the front, diode test; positions in the 2000 px wide view
    x0, y0, k = 700, 150, 2.048
    photo = crop(top, (x0 * 0.75, y0 * 0.75, 1400 * 0.75, 400 * 0.75), 1)
    out, d = sheet(photo, "Messung 2: Vorderseite, Diodentest",
                   ["Rot auf das eine Metallende, Schwarz auf das andere. Dann tauschen.",
                    "Reihenfolge: T1, dann D6, dann C5, dann C6.",
                    "T1 und D6 gesund: mindestens eine Richtung OL oder über 0,3 V.",
                    "C5 und C6 gesund: OL oder langsam steigend.",
                    "Defekt: beide Richtungen ca. 0. Dann die übrigen Teile trotzdem messen."],
                   "Diode", "0.55")
    for name, parts, lx, ly in (("T1", ((745, 315), (930, 307)), 825, 300),
                                ("D6", ((1117, 292), (1117, 352)), 1098, 365),
                                ("C5", ((1157, 305), (1157, 342)), 1150, 365),
                                ("C6", ((1237, 255), (1237, 290)), 1225, 212)):
        for x, y in parts:
            d.ellipse((20 + (x - x0) * k - 15, 100 + (y - y0) * k - 15,
                       20 + (x - x0) * k + 15, 100 + (y - y0) * k + 15), outline=YELLOW, width=4)
        f = font(34)
        tx, ty = 20 + (lx - x0) * k, 100 + (ly - y0) * k
        d.rectangle((tx - 4, ty - 2, tx + d.textlength(name, font=f) + 4, ty + 40), fill=BLACK)
        d.text((tx, ty), name, font=f, fill=YELLOW)
    out.save(HERE / "messung_2_diode.png")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
