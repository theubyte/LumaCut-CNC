#pragma once
/**
 * Exakte boolesche Operationen und Offset mit Clipper2. Eingaben sind geschlossene Polygone (even-odd: ein Loch
 * ist einfach ein weiterer Ring). Ergebnis: geschlossene Polygone mit wiederholtem ersten Punkt, jede
 * Außenkontur direkt vor ihren Löchern. Auflösung 0,1 µm.
 */
#include "core/model.h"
#include <vector>

namespace lumacut {

enum class BooleanOp { Union, Intersect, Subtract, Xor };
enum class JoinKind { Round, Miter, Square };

/** Subjekt und Clip als je eine Form (even-odd in sich). */
PolySet booleanOp(BooleanOp op, const PolySet& subject, const PolySet& clip);
/** Mehrere Formen: Vereinigen alle, Abziehen alle anderen von der ersten, Schneiden und Exklusiv der Reihe nach. */
PolySet booleanShapes(BooleanOp op, const std::vector<PolySet>& shapes);
/** Positiv wächst die Fläche, negativ schrumpft sie; Löcher verhalten sich umgekehrt. Offene Pfade werden ignoriert. */
PolySet offsetPolys(const PolySet& polys, double deltaMm, JoinKind join = JoinKind::Round);

}  // namespace lumacut
