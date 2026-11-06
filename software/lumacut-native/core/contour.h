#pragma once
/** Wie Contour.kt: Umrisse über Abstandsfeld und Marching Squares. Ergebnis nur geschlossene Linienzüge. */
#include "core/model.h"
#include <cstdint>
#include <span>
#include <vector>

namespace lumacut {

inline constexpr double DEFAULT_PX_PER_MM = 6;

/** Binärbild über der Fläche: 1 = Motiv. Ursprung (x0, y0) in mm. */
class Mask {
public:
    int w = 0, h = 0;
    std::vector<uint8_t> data;
    double pxPerMm = 1, x0 = 0, y0 = 0;

    Mask() = default;
    /** Wirft std::invalid_argument("Ungültige Maske"). */
    Mask(int w, int h, std::vector<uint8_t> data, double pxPerMm, double x0 = 0, double y0 = 0);

    /** Durchsichtige Pixel und alles, was mit dem Bildrand verbunden und randfarben ist, ist Hintergrund. argb wie Android. */
    static Mask fromArgb(std::span<const uint32_t> argb, int w, int h, double widthMm, double heightMm, double pxPerMm = DEFAULT_PX_PER_MM, int tolerance = 40);
    /** rgba: 4 Bytes je Pixel. */
    static Mask fromRgba(std::span<const uint8_t> rgba, int w, int h, double widthMm, double heightMm, double pxPerMm = DEFAULT_PX_PER_MM, int tolerance = 40);

    int count() const;
    /** Jedes eingeschlossene Loch wird Teil des Motivs. */
    Mask filled() const;
    /** Entfernt getrennte Flecken unter minAreaMm2. */
    Mask withoutSpecks(double minAreaMm2) const;
};

double polyArea(PolyView poly);

namespace Contour {
/** Geschlossene Umrisse, um offsetMm verschoben (positiv = außen). Lücken bis etwa 2 × closeGapMm werden geschlossen. */
PolySet fromMask(const Mask& mask, double offsetMm, double closeGapMm = 0, bool outerOnly = true, double minAreaMm2 = 1);
/** Umrisse geschlossener Formen (even-odd, Löcher bleiben, außer outerOnly). */
PolySet fromPolys(const PolySet& polys, double offsetMm, double pxPerMm = 8, bool outerOnly = false);
/** Even-odd-Füllung auf einem w × h-Raster ab (x0, y0) mm mit p Pixeln je mm. */
std::vector<uint8_t> rasterize(const PolySet& polys, double x0, double y0, int w, int h, double p);
/** Aufkleber: Umriss außerhalb des Motivs, kleine Lücken geschlossen. */
PolySet sticker(const Mask& mask, double offsetMm, bool join = false);
/** Folgt der Kante; insetMm zieht die Linie nach innen. */
PolySet edge(const Mask& mask, double insetMm = 0);
}

}  // namespace lumacut
