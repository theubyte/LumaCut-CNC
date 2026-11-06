#pragma once
/** Wie Extras.kt: Text am Bogen, Anordnen im Gitter, Herz und Stern, Anhänger. */
#include "core/model.h"
#include <vector>

namespace lumacut {

namespace ArcText {
/** radiusMm > 0: Text oben auf dem Kreis; < 0: unten am Kreis, Buchstaben zur Mitte. Wirft std::invalid_argument. */
PolySet bend(const PolySet& paths, double radiusMm);
}
namespace Arrange {
/** Versätze aller Kopien außer dem Original. Wirft std::invalid_argument. */
std::vector<Pt> gridOffsets(const Box& piece, int nx, int ny, double gapX, double gapY);
/** Versätze, bei denen das Stück in der Arbeitsfläche bleibt. */
std::vector<Pt> inside(const Box& piece, const std::vector<Pt>& offsets);
}
namespace ShapeLib {
Poly heart(double w, double h);
Poly star(int points, double w, double h, double innerRatio = 0.45);
/** Umriss und Loch als zwei geschlossene Linien. */
PolySet pendant(double w, double h, double holeDiameter = 4);
}

}  // namespace lumacut
