"""„Nur Auswahl senden“ – Auftrag nur aus den ausgewählten Objekten (Qt-frei).

Wie LightBurns *Cut Selected Graphics* bzw. xTool *Nur Auswahl bearbeiten*:
Die Kopie behält alle Ebenen (Reihenfolge, Leistung, Schnittoptionen),
enthält aber nur die ausgewählten Objekte. Das Original bleibt unverändert.
Ausgeblendete Ebenen werden wie beim normalen Auftrag nicht gelasert.
"""

from __future__ import annotations

from typing import Iterable

from lumacut_canvas.model import Document


def selection_document(doc: Document, ids: Iterable[str]) -> Document:
    """Kopie von ``doc`` nur mit den Objekten ``ids``; ValueError ohne Auswahl."""
    wanted = set(ids)
    if not wanted:
        raise ValueError("„Nur Auswahl“ ist an, aber nichts ausgewählt")
    data = doc.to_dict()
    data["objects"] = [o for o in data["objects"] if o.get("id") in wanted]
    if not data["objects"]:
        raise ValueError("„Nur Auswahl“: ausgewählte Objekte nicht gefunden")
    out = Document(with_default_layer=False)
    out.load_dict(data)
    return out
