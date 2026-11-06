#pragma once
/**
 * Bearbeitbare kubische Umrisse (`Element::curves`, nur Windows) und ihre Abflachung nach `paths`.
 * Griffe sind absolute Koordinaten im Element: h1 kommt am Knoten an, h2 geht ab.
 * `paths` bleibt die Wahrheit für die Ausgabe: auf jede Änderung hier folgt flattenCurves.
 */
#include "core/model.h"
#include <functional>
#include <optional>
#include <vector>

namespace lumacut {

inline constexpr double FLATTEN_TOL_MM = 0.02;
inline constexpr double HANDLE_K = 0.5522847498;  /// Grifflänge für einen Viertelkreis

/** Ein geschlossener Pfad endet genau auf seinem ersten Punkt, wie isClosed es erwartet. */
Poly flattenCurve(const CurvePath& path, double tol = FLATTEN_TOL_MM);
PolySet flattenCurves(const std::vector<CurvePath>& paths, double tol = FLATTEN_TOL_MM);
/** Eckknoten aus vorhandenen Linienzügen (Importe, Boolesches). Geschlossene verlieren den wiederholten Endpunkt. */
std::vector<CurvePath> curvesFromPaths(const PolySet& polys);
CurvePath ellipseCurve(double w, double h);
CurvePath rectCurve(double w, double h);
std::vector<CurvePath> mapCurves(const std::vector<CurvePath>& paths, const std::function<Pt(Pt)>& f);

/** Verschiebt einen Knoten mit seinen Griffen. */
CurvePath moveNode(const CurvePath& path, size_t i, Pt to);
/** Verschiebt einen Griff. Ein glatter Knoten hält den Gegengriff in Linie, bei dessen eigener Länge. */
CurvePath moveHandle(const CurvePath& path, size_t i, bool outHandle, Pt to);
/** Ecke ohne Griffe, oder glatt mit Griffen entlang der Nachbarn. */
CurvePath toggleSmooth(const CurvePath& path, size_t i);
/** Hält mindestens zwei Knoten offen und drei geschlossen; sonst nichts. */
std::optional<CurvePath> deleteNode(const CurvePath& path, size_t i);

struct CurveHit {
    size_t span;
    double t;
    double dist;
};
/** Nächste Stelle auf einem Pfad. */
std::optional<CurveHit> nearestOnCurve(const CurvePath& path, Pt p);
/** Teilt einen Abschnitt bei t, ohne die Form zu ändern (de Casteljau). */
CurvePath insertNode(const CurvePath& path, size_t span, double t);
size_t nodeCount(const std::vector<CurvePath>& paths);

}  // namespace lumacut
