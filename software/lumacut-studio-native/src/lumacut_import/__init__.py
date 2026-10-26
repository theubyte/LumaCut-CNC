"""Import von Vektor- und Bilddateien in den Canvas (SVG, DXF, PDF, PNG/JPG/BMP).

* :mod:`.vector` – SVG (svgelements) und DXF (ezdxf) → Polylinien in mm,
  Qt-frei.
* :mod:`.pdf` – PDF-Vektorpfade (pypdf + eigene Pfad-Interpretation), Qt-frei.
* :mod:`.placement` – Polylinien → ``polygon``/``path``-Objekte, gemeinsam
  in die Arbeitsfläche eingepasst und gruppiert.
* :mod:`.image` – Bitmap → Bildobjekt (``kind == "image"``) mit Größe in mm
  aus der Datei-DPI.
* :mod:`.trace` – Bild nachzeichnen (Bitmap → Polygone mit Löchern), Qt-frei
  (OpenCV + shapely); :mod:`.trace_qt` – Dialog mit Vorschau.
* :mod:`.qt` – Menü Datei → Importieren (Strg+I), Drag & Drop, der
  Bildeinstellungs-Dialog und „Bild nachzeichnen …“ (Alt+T).
"""

from .placement import ImportResult, import_file, VECTOR_SUFFIXES, IMAGE_SUFFIXES, ALL_SUFFIXES

__all__ = ["ImportResult", "import_file", "VECTOR_SUFFIXES", "IMAGE_SUFFIXES", "ALL_SUFFIXES"]
