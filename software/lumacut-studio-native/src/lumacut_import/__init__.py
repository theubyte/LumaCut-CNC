"""Import von Vektor- und Bilddateien in den Canvas (SVG, DXF, PNG/JPG/BMP).

* :mod:`.vector` – SVG (svgelements) und DXF (ezdxf) → Polylinien in mm,
  Qt-frei.
* :mod:`.placement` – Polylinien → ``polygon``/``path``-Objekte, gemeinsam
  in die Arbeitsfläche eingepasst und gruppiert.
* :mod:`.image` – Bitmap → Bildobjekt (``kind == "image"``) mit Größe in mm
  aus der Datei-DPI.
* :mod:`.qt` – Menü Datei → Importieren (Strg+I), Drag & Drop und der
  Bildeinstellungs-Dialog.
"""

from .placement import ImportResult, import_file, VECTOR_SUFFIXES, IMAGE_SUFFIXES, ALL_SUFFIXES

__all__ = ["ImportResult", "import_file", "VECTOR_SUFFIXES", "IMAGE_SUFFIXES", "ALL_SUFFIXES"]
