#include "core/boolean.h"

#include <clipper2/clipper.h>
#include <algorithm>
#include <cmath>

namespace lumacut {
namespace {

using namespace Clipper2Lib;

constexpr double kScale = 10000;
constexpr double kArcToleranceMm = 0.01;
constexpr double kCleanMm = 0.0005;

inline int64_t toInt(double v) {
    const double x = v * kScale, f = std::floor(x);
    return int64_t(x - f >= 0.5 ? f + 1 : f);
}
Paths64 toPaths(const PolySet& polys) {
    Paths64 out;
    out.reserve(polys.size());
    for (PolyView poly : polys) {
        Path64 path;
        path.reserve(poly.size());
        for (const Pt& p : poly) {
            const Point64 q(toInt(p.x), toInt(p.y));
            if (path.empty() || path.back() != q) path.push_back(q);
        }
        if (path.size() > 1 && path.front() == path.back()) path.pop_back();
        if (path.size() >= 3) out.push_back(std::move(path));
    }
    return out;
}
/** Vorwärts durch den Baum: jede Außenkontur vor ihren Löchern. */
void walk(const PolyPath64& node, Paths64& out) {
    for (const auto& child : node) {
        out.push_back(child->Polygon());
        walk(*child, out);
    }
}
PolySet fromTree(const PolyTree64& tree) {
    Paths64 paths;
    walk(tree, paths);
    PolySet out;
    Poly buf;
    for (const Path64& raw : paths) {
        // Entfernt fast deckungsgleiche Punkte und Geraden-Zwischenpunkte, Punkt für Punkt in Bahnreihenfolge.
        const Path64 path = SimplifyPath(raw, kCleanMm * kScale, true);
        if (path.size() < 3) continue;
        buf.clear();
        for (const Point64& p : path) buf.push_back({double(p.x) / kScale, double(p.y) / kScale});
        buf.push_back(buf.front());
        out.add(buf);
    }
    return out;
}
ClipType clipType(BooleanOp op) {
    switch (op) {
        case BooleanOp::Union: return ClipType::Union;
        case BooleanOp::Intersect: return ClipType::Intersection;
        case BooleanOp::Subtract: return ClipType::Difference;
        case BooleanOp::Xor: return ClipType::Xor;
    }
    return ClipType::Union;
}
void runInto(BooleanOp op, const Paths64& subject, const Paths64& clip, PolyTree64& tree) {
    Clipper64 c;
    c.AddSubject(subject);
    if (!clip.empty()) c.AddClip(clip);
    Paths64 open;
    c.Execute(clipType(op), FillRule::EvenOdd, tree, open);
}

}  // namespace

PolySet booleanOp(BooleanOp op, const PolySet& subject, const PolySet& clip) {
    const Paths64 s = toPaths(subject), c = toPaths(clip);
    if (s.empty() && (op == BooleanOp::Intersect || op == BooleanOp::Subtract)) return {};
    PolyTree64 tree;
    runInto(op, s, c, tree);
    return fromTree(tree);
}

PolySet booleanShapes(BooleanOp op, const std::vector<PolySet>& shapes) {
    std::vector<const PolySet*> list;
    for (const PolySet& s : shapes) if (!s.empty()) list.push_back(&s);
    if (list.empty()) return {};
    PolyTree64 first;
    runInto(BooleanOp::Union, toPaths(*list[0]), {}, first);
    PolySet acc = fromTree(first);
    if (op == BooleanOp::Subtract) {
        std::vector<PolySet> rest;
        for (size_t i = 1; i < list.size(); ++i) rest.push_back(*list[i]);
        return booleanOp(BooleanOp::Subtract, acc, booleanShapes(BooleanOp::Union, rest));
    }
    for (size_t i = 1; i < list.size(); ++i) acc = booleanOp(op, acc, *list[i]);
    return acc;
}

PolySet offsetPolys(const PolySet& polys, double deltaMm, JoinKind join) {
    const Paths64 paths = toPaths(polys);
    if (paths.empty()) return {};
    PolyTree64 normal;
    runInto(BooleanOp::Union, paths, {}, normal);
    Paths64 flat;
    walk(normal, flat);
    const JoinType jt = join == JoinKind::Round ? JoinType::Round : join == JoinKind::Miter ? JoinType::Miter : JoinType::Square;
    ClipperOffset co(2.0, kArcToleranceMm * kScale);
    co.AddPaths(flat, jt, EndType::Polygon);
    PolyTree64 tree;
    co.Execute(deltaMm * kScale, tree);
    return fromTree(tree);
}

}  // namespace lumacut
