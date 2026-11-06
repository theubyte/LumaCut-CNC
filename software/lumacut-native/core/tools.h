#pragma once
/** Wie Tools.kt: Ausrichten, Verschweißen auf Raster, Haltestege, Schachteln, Fingerzinken-Box; dazu ImportLayout.shelf. */
#include "core/model.h"
#include <QString>
#include <optional>
#include <utility>
#include <vector>

namespace lumacut {

enum class AlignMode { Left, CenterX, Right, Top, CenterY, Bottom };
namespace Align {
/** Verschiebt jede Box auf die Kante oder Mittellinie von ref. */
std::vector<Pt> offsets(const std::vector<Box>& boxes, AlignMode mode, const Box& ref);
/** Gleiche Abstände; die äußeren beiden bleiben. */
std::vector<Pt> distribute(const std::vector<Box>& boxes, bool horizontal);
}

enum class RasterBooleanOp { Union, Subtract, Intersect };
/** Android-Verfahren auf 0,1-mm-Raster. Für exakte Kanten: core/boolean.h. */
namespace Booleans {
PolySet apply(const std::vector<PolySet>& shapes, RasterBooleanOp op, double pxPerMm = 10);
}

namespace Tabs {
/** Geschlossene Pfade bekommen count Lücken der Breite widthMm; offene oder zu kurze bleiben. */
PolySet apply(const PolySet& polys, int count, double widthMm);
}

inline constexpr double SHELF_GAP = 5;
/** Regal-Packung, höchste zuerst, Reihen von oben links; hält die Park-Ecke frei. Verschiebung je Box oder nichts. */
std::vector<std::optional<Pt>> shelf(const std::vector<Box>& boxes, double w, double h, double gap = SHELF_GAP);

namespace Nest {
struct Placed { int plate; Pt offset; };
/** Platte und Verschiebung je Box; nichts = zu groß oder zu viele Platten. w, h ≤ 0: Arbeitsfläche. */
std::vector<std::optional<Placed>> place(const std::vector<Box>& boxes, double w = 0, double h = 0, int maxPlates = 20);
}

struct BoxSpec {
    double w = 0, d = 0, h = 0, t = 0, finger = 0;
    bool closed = false;
};
namespace BoxMaker {
/** Ungerade Anzahl Stücke, je etwa finger lang. */
int segments(double len, double finger);
/** Teile als geschlossene Linien mit Namen, Ursprung oben links je Teil. Wirft std::invalid_argument. */
std::vector<std::pair<QString, Poly>> panels(const BoxSpec& s);
}

}  // namespace lumacut
