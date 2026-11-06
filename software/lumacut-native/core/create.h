#pragma once
/** Wie Create.kt: Formen, Catmull-Rom, Personalisierung (Anhänger, Emblem, Rahmen, Lineal, Puzzle). */
#include "core/model.h"
#include <QString>
#include <optional>
#include <utility>
#include <vector>

namespace lumacut {

enum class ShapeKind { Star, Heart, Arrow, Bubble, Cross, Drop };
Poly makeShape(ShapeKind kind, double w, double h);

namespace Curves {
/** Glatte Kurve durch getippte Punkte. */
Poly catmullRom(PolyView points, bool closed, int steps = 12);
}

struct Parts {
    PolySet engrave, cut, marks;
    std::vector<std::pair<Pt, QString>> labels;
};
/** Dieselben Teile mit der Gesamt-Ecke oben links auf (0, 0). */
Parts normalizeParts(const Parts& q);

enum class TagStyle { Keychain, Plate, Heart, Round };
enum class FrameStyle { Simple, Rounded, Double, Oval, Dashed };

/** Kotlins Random(seed) (XorWow): Puzzle mit gleichem Startwert ergibt dieselben Knöpfe wie Android. */
class KotlinRandom {
public:
    explicit KotlinRandom(int seed);
    int nextInt();
    bool nextBoolean();
private:
    uint32_t x, y, z = 0, w = 0, v, addend;
};

namespace Personalize {
PolySet fitHeight(const PolySet& paths, double h);
/** Namensschild: Text wird graviert, Umriss und Loch werden geschnitten. */
Parts tag(const PolySet& text, TagStyle style, std::optional<double> holeMm);
/** Rundes Emblem: Initialen groß, optional Text oben und unten am Rand. */
Parts emblem(const PolySet& initials, const std::optional<PolySet>& top, const std::optional<PolySet>& bottom, double diameter);
/** Rahmen mit Abstand um box. */
PolySet frame(const Box& box, FrameStyle style, double marginMm);
/** Stücke von dash mm mit gap mm dazwischen. */
PolySet dashes(PolyView poly, double dash, double gap);
/** Lineal: Umriss (schneiden), Striche (markieren), Positionen der cm-Zahlen. */
Parts ruler(int lengthMm, double widthMm, std::optional<double> holeMm);
/** Puzzle: Umriss plus innere Schnittlinien mit Knöpfen. */
PolySet puzzle(double w, double h, int cols, int rows, int seed = 7);
}

}  // namespace lumacut
