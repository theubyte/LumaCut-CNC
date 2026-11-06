/**
 * Anordnen wie ImportLayout.kt (aktueller Stand mit Fläche und Park-Ecke). Vektoren behalten ihre Größe. Passt es wie gezeichnet:
 * mittig, und neben die Park-Ecke, wenn es dort hineinreichte. Zu groß: die obersten Gruppen in Reihen (5 mm Abstand, ohne Drehen).
 * Geht auch das nicht, entscheidet der Aufrufer zwischen Verkleinern und Verteilen.
 */
#include "core/import/vector.h"
#include "core/parallel.h"
#include "core/parts.h"

#include <QHash>
#include <algorithm>
#include <numeric>

namespace lumacut::import {
namespace {

constexpr double MARGIN = 1.0;

Box itemBoxUnion(const VectorImport& r, const ImportUnit& u) {
    std::optional<Box> b;
    for (const uint32_t i : u.items) b = b ? b->united(r.items[i].box) : r.items[i].box;
    for (const uint32_t i : u.images) b = b ? b->united(r.images[i].box) : r.images[i].box;
    return b.value_or(Box{});
}

/** Eine große Gruppe: ihre Teile werden die Einheiten. */
Units explode(const VectorImport& r, const Units& units0) {
    if (units0->size() != 1) return units0;
    auto units = std::make_shared<std::vector<ImportUnit>>();
    const ImportUnit& u = units0->front();
    units->reserve(u.items.size() + u.images.size());
    for (const uint32_t i : u.items) units->push_back({{i}, {}, r.items[i].box});
    for (const uint32_t i : u.images) units->push_back({{}, {i}, r.images[i].box});
    return units;
}

}  // namespace

int Layout::leftOut() const {
    return int(std::count_if(offsets.begin(), offsets.end(), [](const std::optional<Pt>& o) { return !o.has_value(); }));
}

Units unitsOf(VectorImport& r) {
    if (r.items.empty() && !r.polys.empty()) {
        PartSplitter::Split split = PartSplitter::split(r.polys);
        const QStringList group = split.parts.size() > 1 ? QStringList{QStringLiteral("*")} : QStringList{};
        r.items.resize(split.parts.size());
        for (size_t i = 0; i < split.parts.size(); ++i) {
            r.items[i].polys = std::move(split.parts[i]);
            r.items[i].groups = group;
        }
    }
    parallelBlocks(std::ptrdiff_t(r.items.size()), 256, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) r.items[size_t(i)].box = boundsOf(r.items[size_t(i)].polys).value_or(Box{});
    });
    auto units = std::make_shared<std::vector<ImportUnit>>();
    QHash<QString, uint32_t> byTop;
    for (uint32_t i = 0; i < r.items.size(); ++i) {
        const ImportItem& item = r.items[i];
        if (item.groups.isEmpty()) {
            units->push_back({{i}, {}, {}});
        } else {
            const QString& key = item.groups.first();
            auto it = byTop.constFind(key);
            if (it == byTop.constEnd()) {
                it = byTop.insert(key, uint32_t(units->size()));
                units->push_back({});
            }
            (*units)[it.value()].items.push_back(i);
        }
    }
    for (uint32_t i = 0; i < r.images.size(); ++i) units->push_back({{}, {i}, {}});
    for (ImportUnit& u : *units) u.box = itemBoxUnion(r, u);
    return units;
}

Box unionOf(const std::vector<ImportUnit>& units) {
    Box b = units.front().box;
    for (const ImportUnit& u : units) b = b.united(u.box);
    return b;
}

Layout arrange(const VectorImport& r, const Units& units0, std::optional<double> wIn, std::optional<double> hIn) {
    const double w = wIn.value_or(Work::width()), h = hIn.value_or(Work::height());
    const Box all = unionOf(*units0);
    if (all.width() <= w && all.height() <= h) {
        Pt d{w / 2 - all.center().x, h / 2 - all.center().y};
        const Box placed{all.minX + d.x, all.minY + d.y, all.maxX + d.x, all.maxY + d.y};
        if (Work::touchesPark(placed)) {    // mittig reichte es in die Park-Ecke: daneben, wenn es passt
            const Box park = Work::park();
            const double left = park.minX - placed.maxX, down = park.maxY - placed.minY;
            const bool canLeft = placed.minX + left >= 0, canDown = placed.maxY + down <= h;
            if (canLeft && (!canDown || -left <= down)) d.x += left;
            else if (canDown) d.y += down;
        }
        return {FitKind::AsIs, units0, std::vector<std::optional<Pt>>(units0->size(), d)};
    }
    const Units units = explode(r, units0);
    std::vector<Box> boxes;
    boxes.reserve(units->size());
    for (const ImportUnit& u : *units) boxes.push_back(u.box);
    std::vector<std::optional<Pt>> packed = shelf(boxes, w, h);
    const bool allPlaced = std::all_of(packed.begin(), packed.end(), [](const std::optional<Pt>& o) { return o.has_value(); });
    return {allPlaced ? FitKind::Packed : FitKind::Partial, units, std::move(packed)};
}

Spread spread(const VectorImport& r, const Units& units0, std::optional<double> wIn, std::optional<double> hIn, int maxPlates) {
    const double w = wIn.value_or(Work::width()), h = hIn.value_or(Work::height());
    const Units units = explode(r, units0);
    std::vector<uint32_t> rest;
    for (uint32_t i = 0; i < units->size(); ++i) {
        const Box& b = (*units)[i].box;
        if (b.width() <= w - 2 * MARGIN && b.height() <= h - 2 * MARGIN) rest.push_back(i);
    }
    const int tooBig = int(units->size() - rest.size());
    Spread out;
    while (!rest.empty() && int(out.plates.size()) < maxPlates) {
        std::vector<Box> boxes;
        boxes.reserve(rest.size());
        for (const uint32_t i : rest) boxes.push_back((*units)[i].box);
        const std::vector<std::optional<Pt>> packed = shelf(boxes, w, h);
        std::vector<std::optional<Pt>> offsets(units->size());
        std::vector<uint32_t> next;
        for (size_t k = 0; k < rest.size(); ++k) {
            offsets[rest[k]] = packed[k];
            if (!packed[k]) next.push_back(rest[k]);
        }
        // Passt in dieser Runde nichts mehr auf eine leere Platte, hilft auch keine weitere.
        if (next.size() == rest.size()) break;
        out.plates.push_back({FitKind::Packed, units, std::move(offsets)});
        rest = std::move(next);
    }
    out.leftOut = tooBig + int(rest.size());
    return out;
}

double shrinkFactor(const std::vector<ImportUnit>& units, std::optional<double> w, std::optional<double> h, double border) {
    const Box all = unionOf(units);
    return std::min({1.0, (w.value_or(Work::width()) - 2 * border) / std::max(all.width(), 1e-9),
                     (h.value_or(Work::usableHeight()) - 2 * border) / std::max(all.height(), 1e-9)});
}

std::vector<std::optional<Pt>> shelf(const std::vector<Box>& boxes, double w, double h, double gap) {
    std::vector<std::optional<Pt>> out(boxes.size());
    double x = MARGIN, y = MARGIN, rowH = 0;
    std::vector<uint32_t> order(boxes.size());
    std::iota(order.begin(), order.end(), 0u);
    std::stable_sort(order.begin(), order.end(), [&](uint32_t a, uint32_t b) { return boxes[a].height() > boxes[b].height(); });
    // Die Park-Ecke sitzt am rechten Ende der oberen Reihen.
    const double parkY = Bed::parkY(), parkX = Bed::parkX();
    const auto rightEnd = [&](double top) { return top < parkY ? w - parkX : w - MARGIN; };
    for (const uint32_t i : order) {
        const Box& b = boxes[i];
        const double bw = b.width(), bh = b.height();
        if (bw > w - 2 * MARGIN || bh > h - 2 * MARGIN) continue;
        double px = x, py = y;
        bool newRow = false;
        if (px + bw > rightEnd(py)) {
            px = MARGIN;
            py = y + rowH + gap;
            newRow = true;
            if (px + bw > rightEnd(py)) py = std::max(py, parkY);
        }
        if (py + bh > h - MARGIN) continue;
        out[i] = Pt{px - b.minX, py - b.minY};
        x = px + bw + gap;
        if (newRow) { y = py; rowH = bh; }
        else rowH = std::max(rowH, bh);
    }
    return out;
}

}  // namespace lumacut::import
