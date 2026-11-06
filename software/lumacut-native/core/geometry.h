#pragma once
/** Wie Geometry.kt und orderForCutting aus ImportLayout.kt: Schraffur, Pfadreihenfolge, Vereinfachen, Grundformen. */
#include "core/model.h"
#include <cstdint>
#include <vector>

namespace lumacut {

/** Waagerechte Schraffur (even-odd) mit abwechselnder Richtung, je Stück 2 Punkte. Wirft std::invalid_argument. */
PolySet hatch(const PolySet& polys, double spacing);

/** Ein Pfad in der gefundenen Reihenfolge. */
struct PathOrder {
    uint32_t index;
    bool reversed;
};
/** Nächster Nachbar: offene Pfade dürfen umgedreht werden, geschlossene beginnen, wo sie beginnen. Pfade unter 2 Punkten entfallen. */
std::vector<PathOrder> orderPathsIndexed(const PolySet& paths, Pt start = {});
/** Innere Pfade vor den geschlossenen Konturen um sie herum: ein Teil fällt nie vor seinen Innenschnitten heraus. */
std::vector<PathOrder> orderForCuttingIndexed(const PolySet& paths, Pt start);
PolySet orderPaths(const PolySet& paths, Pt start = {});
PolySet orderForCutting(const PolySet& paths, Pt start);
/** Die gefundene Reihenfolge als neuer Satz. */
PolySet applyOrder(const PolySet& paths, const std::vector<PathOrder>& order);

/** Douglas-Peucker. */
Poly simplify(PolyView points, double tolerance);

namespace Shapes {
Poly rect(double w, double h, double radius = 0);
Poly ellipse(double w, double h, double segmentMm = 0.4);
Poly polygon(int sides, double w, double h);
}

}  // namespace lumacut
