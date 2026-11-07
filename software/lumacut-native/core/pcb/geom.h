#pragma once
/**
 * Clipper2 helpers for the PCB code, in millimetres. Output rings are closed (first point repeated), outers
 * counter-clockwise, holes clockwise (Y up), so even-odd fill and the shoelace area both work directly.
 * Resolution 0.1 um, arcs within 2 um.
 */
#include "core/model.h"
#include <optional>
#include <vector>

namespace lumacut::pcb {

using Polys = std::vector<Poly>;

/** Union with the non-zero rule: expects outers CCW and holes CW (or one self-consistent keyhole). */
Polys unionPolys(const Polys& polys);
/** Cleans one contour, or a set read as even-odd. Holes come back with the right orientation. */
Polys cleanEvenOdd(const Polys& polys);
Polys addPolys(const Polys& a, const Polys& b);
Polys subtractPolys(const Polys& a, const Polys& b);
Polys intersectPolys(const Polys& a, const Polys& b);
/** Grow (delta > 0) or shrink closed polygons with round corners. */
Polys offsetPolys(const Polys& polys, double deltaMm);
/** Area covered by a round pen of this diameter along an open polyline. */
Polys strokePolyline(const Poly& line, double diameterMm);
/** Cuts lines to the inside of region. Result: open polylines. */
Polys clipLines(const Polys& lines, const Polys& region);

/** Signed shoelace area, closed or not. */
double ringArea(const Poly& p);
/** Net area in mm2: holes count negative. */
double polysArea(const Polys& polys);
/** Even-odd point test over all rings. */
bool pointInPolys(double x, double y, const Polys& polys);
/** Regular polygon, CCW, not closed; corners on the extremes so the bounds stay true. */
Poly circle(double cx, double cy, double r, double tolMm = 0.002);
std::optional<Box> boundsOfPolys(const Polys& polys);
inline Poly closed(Poly p) {
    if (!p.empty() && !(p.front() == p.back())) p.push_back(p.front());
    return p;
}

}  // namespace lumacut::pcb
