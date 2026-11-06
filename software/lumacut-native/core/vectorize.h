#pragma once
/**
 * Bild zu Vektoren: Schwellwert, Rissverfolgung entlang der Pixelkanten, Douglas-Peucker.
 * Außenkonturen und Löcher liegen als eigene geschlossene Linien vor (even-odd), Außenkontur vor Loch.
 * An Diagonalen bleiben Pixel getrennt (4-Nachbarschaft), so kreuzt sich nie eine Kontur.
 */
#include "core/image.h"
#include "core/model.h"
#include <optional>

namespace lumacut {

struct VectorizeOptions {
    /** Pixel dunkler als dieser Wert (1..255) sind Motiv. */
    int threshold = 128;
    /** Helles statt Dunkles ist Motiv. */
    bool invert = false;
    /** Größe des Ergebnisses; ohne Angabe 1 Pixel = 1 mm. */
    std::optional<double> widthMm, heightMm;
    /** Vereinfachung; Standard 0,75 Pixel (nimmt die Pixeltreppen heraus). */
    std::optional<double> toleranceMm;
    /** Kleinere Flecken und Löcher entfallen. Standard 4 Pixel. */
    std::optional<double> minAreaMm2;
    /** Nur Außenkonturen. */
    bool outerOnly = false;
    /** Ecken leicht abrunden (ein Chaikin-Durchgang). */
    bool smooth = false;
};

/** Wirft std::invalid_argument("Ungültige Bilddaten"). */
PolySet vectorize(GrayView gray, int w, int h, const VectorizeOptions& options = {});
PolySet vectorizeRaster(const Raster& r, const VectorizeOptions& options = {});

}  // namespace lumacut
