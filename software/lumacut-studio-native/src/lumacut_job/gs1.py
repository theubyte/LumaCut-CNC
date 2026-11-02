"""GS1 element strings in the human-readable "(AI)data" form – shared by GS1-128 and GS1 DataMatrix.

The user types the element string the way it is printed under a GS1 code,
e.g. ``(01)09501101530003(17)261231(10)AB-12``. :func:`parse` splits it into
application identifiers (AI) and data, checks the parts a laser user is
likely to get wrong (AI form, the length of fixed-length AIs, digits-only
fields, the GS1 mod-10 check digit of SSCC / GTIN / GLN, the GS1 character
set) and :func:`sequence` produces the data stream for the encoders: the
leading FNC1 that marks the symbol as GS1, then AI + data, with an FNC1
separator after every variable-length field that is not the last one.

FNC1 is represented by :data:`FNC1` (an ``int`` outside the byte range) so
the encoders can map it to their own codeword (Code 128: symbol value 102,
Data Matrix: codeword 232 / C40 Shift 2 + 27). Pure Python, no Qt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

FNC1 = 256

# Total length (AI + data) of the AIs with a predefined length, by their first two
# digits (GS1 General Specifications, figure 5.10.1-2). These need no separator.
PREDEFINED = {"00": 20, "01": 16, "02": 16, "03": 16, "04": 18, "11": 8, "12": 8, "13": 8,
              "14": 8, "15": 8, "16": 8, "17": 8, "18": 8, "19": 8, "20": 4, "31": 10,
              "32": 10, "33": 10, "34": 10, "35": 10, "36": 10, "41": 16}
# AI length (digits) for these prefixes.
AI_DIGITS = {**{p: 2 for p in ("00", "01", "02", "03", "04", "11", "12", "13", "14", "15",
                               "16", "17", "18", "19", "20")},
             **{p: 4 for p in ("31", "32", "33", "34", "35", "36")}, "41": 3}
# Fields that end in a GS1 mod-10 check digit (SSCC, GTIN, content GTIN, GLNs).
CHECK_DIGIT_AIS = ("00", "01", "02", "410", "411", "412", "413", "414", "415", "416", "417")
# GS1 AI encodable character set 82.
CHARSET = frozenset("!\"%&'()*+,-./0123456789:;<=>?ABCDEFGHIJKLMNOPQRSTUVWXYZ_"
                    "abcdefghijklmnopqrstuvwxyz")
MAX_FIELD = 90
EXAMPLE = "(01)09501101530003(17)261231(10)AB-12"

_TOKEN = re.compile(r"\(([^()]*)\)([^()]*)")


@dataclass(frozen=True)
class Element:
    ai: str
    data: str

    @property
    def fixed(self) -> bool:
        return self.ai[:2] in PREDEFINED


def check_digit(digits: str) -> int:
    """GS1 mod-10 check digit for ``digits`` (without the check digit)."""
    total = sum(int(d) * (3 if k % 2 == 0 else 1) for k, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def parse(text: str) -> list[Element]:
    """Elements of a "(AI)data(AI)data…" string; ``ValueError`` (German) on errors."""
    s = "".join(str(text or "").split())
    if not s:
        raise ValueError("Keine GS1-Daten – Form (AI)Wert, z. B. " + EXAMPLE)
    if not s.startswith("("):
        raise ValueError("GS1-Daten beginnen mit einem Datenbezeichner in Klammern, z. B. (01)")
    out: list[Element] = []
    pos = 0
    for m in _TOKEN.finditer(s):
        if m.start() != pos:
            break
        pos = m.end()
        ai, data = m.group(1), m.group(2)
        if not (ai.isascii() and ai.isdigit() and 2 <= len(ai) <= 4):
            raise ValueError(f"Datenbezeichner „({ai})“ ungültig – 2 bis 4 Ziffern erwartet")
        want_ai = AI_DIGITS.get(ai[:2])
        if want_ai and len(ai) != want_ai:
            raise ValueError(f"Datenbezeichner „({ai})“ muss {want_ai} Ziffern haben")
        if not data:
            raise ValueError(f"Kein Wert nach ({ai})")
        bad = sorted({c for c in data if c not in CHARSET})
        if bad:
            raise ValueError(f"Zeichen {', '.join(repr(c) for c in bad[:5])} in ({ai}) sind in "
                             "GS1 nicht erlaubt (keine Umlaute, Leerzeichen oder #, $, @)")
        total = PREDEFINED.get(ai[:2])
        if total is not None:
            n = total - len(ai)
            if len(data) != n:
                raise ValueError(f"({ai}) braucht genau {n} Ziffern, nicht {len(data)}")
            if not data.isdigit():
                raise ValueError(f"({ai}) erlaubt nur Ziffern")
        elif len(data) > MAX_FIELD:
            raise ValueError(f"Wert von ({ai}) ist zu lang (höchstens {MAX_FIELD} Zeichen)")
        if ai in CHECK_DIGIT_AIS:
            want = check_digit(data[:-1])
            if int(data[-1]) != want:
                raise ValueError(f"Prüfziffer in ({ai}) falsch: {data[-1]}, richtig wäre {want}")
        out.append(Element(ai, data))
    if pos != len(s):
        rest = s[pos:]
        if "(" not in rest and ")" not in rest:
            raise ValueError("GS1-Daten beginnen mit einem Datenbezeichner in Klammern, z. B. (01)")
        raise ValueError(f"Klammern stimmen nicht bei „{rest[:12]}“ – Klammern sind nur um "
                         "Datenbezeichner erlaubt")
    return out


def sequence(elements: list[Element]) -> list[int]:
    """FNC1, then AI + data with FNC1 after each variable-length field but the last."""
    out = [FNC1]
    for k, e in enumerate(elements):
        out += [ord(c) for c in e.ai + e.data]
        if not e.fixed and k < len(elements) - 1:
            out.append(FNC1)
    return out


def hri(elements: list[Element]) -> str:
    """Human-readable interpretation, e.g. ``(01)09501101530003(17)261231``."""
    return "".join(f"({e.ai}){e.data}" for e in elements)


__all__ = ["CHARSET", "EXAMPLE", "Element", "FNC1", "check_digit", "hri", "parse", "sequence"]
