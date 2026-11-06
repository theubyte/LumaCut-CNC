#include "core/parts.h"
#include "core/contour.h"

#include <algorithm>
#include <cmath>
#include <map>

namespace lumacut {
namespace {

bool containsPt(PolyView poly, Pt p) {
    bool c = false;
    for (size_t i = 1; i < poly.size(); ++i) {
        const Pt a = poly[i - 1], b = poly[i];
        if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
}
bool insidePoly(PolyView inner, PolyView outer) {
    const size_t step = std::max<size_t>(1, inner.size() / 8);
    int n = 0, hit = 0;
    for (size_t i = 0; i < inner.size(); i += step) {
        ++n;
        if (containsPt(outer, inner[i])) ++hit;
    }
    return hit * 2 > n;
}

}  // namespace

namespace PartSplitter {
Split split(const PolySet& polys) {
    PolySet usable;
    for (PolyView p : polys) if (p.size() >= 2) usable.add(p);
    std::vector<uint8_t> isC(usable.size());
    std::vector<uint32_t> closed;
    for (size_t i = 0; i < usable.size(); ++i) {
        isC[i] = usable[i].size() >= 4 && isClosed(usable[i]);
        if (isC[i]) closed.push_back(uint32_t(i));
    }
    Split out;
    if (int(closed.size()) > MAX_CLOSED) {
        out.parts.push_back(usable);
        out.tooMany = true;
        return out;
    }
    const size_t n = closed.size();
    std::vector<Box> boxes(n);
    std::vector<double> area(n);
    for (size_t i = 0; i < n; ++i) {
        boxes[i] = *boundsOf(usable[closed[i]]);
        area[i] = std::fabs(polyArea(usable[closed[i]]));
    }
    std::vector<std::vector<int>> containers(n);
    for (size_t i = 0; i < n; ++i) {
        for (size_t j = 0; j < n; ++j) {
            if (j != i && area[j] > area[i] && boxes[j].contains({boxes[i].minX, boxes[i].minY}) && boxes[j].contains({boxes[i].maxX, boxes[i].maxY}) &&
                insidePoly(usable[closed[i]], usable[closed[j]]))
                containers[i].push_back(int(j));
        }
    }
    std::map<int, std::vector<int>> holesOf;
    for (size_t i = 0; i < n; ++i) {
        if (containers[i].size() % 2 != 1) continue;
        int parent = containers[i][0];
        for (const int c : containers[i]) if (containers[size_t(c)].size() > containers[size_t(parent)].size()) parent = c;
        holesOf[parent].push_back(int(i));
    }
    size_t ci = 0;
    for (size_t k = 0; k < usable.size(); ++k) {
        if (isC[k]) {
            const size_t i = ci++;
            if (containers[i].size() % 2 == 0) {
                PolySet part;
                part.add(usable[k]);
                const auto it = holesOf.find(int(i));
                if (it != holesOf.end()) for (const int h : it->second) part.add(usable[closed[size_t(h)]]);
                out.parts.push_back(std::move(part));
            }
        } else {
            PolySet part;
            part.add(usable[k]);
            out.parts.push_back(std::move(part));
        }
    }
    if (int(out.parts.size()) > MAX_PARTS) {
        out.parts.clear();
        out.parts.push_back(usable);
        out.tooMany = true;
    }
    return out;
}
}  // namespace PartSplitter

std::vector<Element> splitParts(const Element& e) {
    if (e.isImage() || e.text || e.paths.size() < 2) return {e};
    const PolySet world = e.worldPaths();
    PartSplitter::Split split = PartSplitter::split(world);
    std::vector<PolySet> parts;
    if (split.tooMany || split.parts.size() < 2) {
        for (PolyView p : world) { PolySet s; s.add(p); parts.push_back(std::move(s)); }
    } else {
        parts = std::move(split.parts);
    }
    std::vector<Element> out;
    for (PolySet& part : parts) {
        const auto box = boundsOf(part);
        if (!box) continue;
        for (Pt& p : part.allPoints()) p = {p.x - box->minX, p.y - box->minY};
        Element c = e;
        c.id = newId();
        c.curves.reset();
        c.transform = Transform{box->minX, box->minY};
        c.paths = std::move(part);
        out.push_back(std::move(c));
    }
    return out;
}

}  // namespace lumacut
