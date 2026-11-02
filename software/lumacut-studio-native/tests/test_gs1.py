"""GS1 element strings: parsing, validation, FNC1 sequence and HRI."""

import pytest

from lumacut_job import gs1


def test_check_digit():
    assert gs1.check_digit("0950110153000") == 3
    assert gs1.check_digit("400638133393") == 1
    assert gs1.check_digit("00000000000000000") == 0


def test_parse_and_hri():
    els = gs1.parse(gs1.EXAMPLE)
    assert [(e.ai, e.data) for e in els] == [("01", "09501101530003"), ("17", "261231"),
                                            ("10", "AB-12")]
    assert [e.fixed for e in els] == [True, True, False]
    assert gs1.hri(els) == gs1.EXAMPLE
    assert gs1.hri(gs1.parse(" (01) 0950110153 0003 ")) == "(01)09501101530003"   # spaces ignored
    assert [e.ai for e in gs1.parse("(3103)001250(8200)http://x.example/a")] == ["3103", "8200"]


def test_sequence_fnc1_only_after_variable_fields_but_last():
    F = gs1.FNC1
    assert gs1.sequence(gs1.parse("(01)09501101530003(10)AB")) == (
        [F] + [ord(c) for c in "0109501101530003" "10AB"])
    seq = gs1.sequence(gs1.parse("(10)AB(21)7(17)261231"))
    assert seq == [F] + [ord(c) for c in "10AB"] + [F] + [ord(c) for c in "217"] + [F] + [
        ord(c) for c in "17261231"]


@pytest.mark.parametrize("text,msg", [
    ("", "Keine GS1-Daten"),
    ("0109501101530003", "beginnen mit"),
    ("(1)12", "ungültig"),
    ("(ab)12", "ungültig"),
    ("(310)001250", "muss 4 Ziffern"),
    ("(10)", "Kein Wert"),
    ("(10)Größe", "nicht erlaubt"),
    ("(10)A B#", "nicht erlaubt"),
    ("(01)0950110153000", "genau 14 Ziffern"),
    ("(17)26123A", "nur Ziffern"),
    ("(01)09501101530004", "richtig wäre 3"),
    ("(10)" + "A" * 91, "zu lang"),
    ("(10)AB(21", "Klammern"),
    ("(10)A)B", "Klammern"),
])
def test_parse_errors(text, msg):
    with pytest.raises(ValueError, match=msg):
        gs1.parse(text)
