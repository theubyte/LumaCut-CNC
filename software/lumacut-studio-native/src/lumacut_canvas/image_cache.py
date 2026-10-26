"""QImage-Cache für eingebettete Bildobjekte (Anzeige und Export).

Die PNG-Daten sind ``bytes``; Python cacht deren Hash, daher ist das
Nachschlagen auch bei großen Bildern billig. Klein gehalten (LRU).
"""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtGui import QImage

_CACHE: "OrderedDict[bytes, QImage]" = OrderedDict()
_MAX = 24


def qimage_for(png: bytes) -> QImage:
    img = _CACHE.get(png)
    if img is not None:
        _CACHE.move_to_end(png)
        return img
    img = QImage.fromData(png, "PNG")
    _CACHE[png] = img
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)
    return img
