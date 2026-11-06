#pragma once
/** Wie Parts.kt und Element.splitParts aus Design.kt. */
#include "core/model.h"
#include <vector>

namespace lumacut {

namespace PartSplitter {
inline constexpr int MAX_PARTS = 500, MAX_CLOSED = 2000;
struct Split {
    std::vector<PolySet> parts;
    bool tooMany = false;
};
/** Jede äußere geschlossene Kontur mit den Löchern darin ist ein Teil, jeder offene Pfad auch. Ein O bleibt ganz. */
Split split(const PolySet& polys);
}

/** Das Element als kleinere Teile, an Ort und Stelle. Text und Bilder bleiben ganz. Ergebnis 1 = nichts zu teilen. */
std::vector<Element> splitParts(const Element& e);

}  // namespace lumacut
