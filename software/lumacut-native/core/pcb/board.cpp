#include "core/pcb/board.h"

#include "core/import/zip.h"
#include "core/parallel.h"
#include <QFile>
#include <QRegularExpression>
#include <algorithm>
#include <cmath>
#include <mutex>
#include <unordered_map>

namespace lumacut::pcb {

PcbFile parseAs(const PcbFile& file, LayerKind kind) {
    PcbFile out{file.name, file.text, kind, nullptr, nullptr, {}};
    if (kind == LayerKind::Other) return out;
    const std::string_view text(file.text.constData(), size_t(file.text.size()));
    try {
        if (kind == LayerKind::Drill) out.drill = file.drill ? file.drill : std::make_shared<const ExcellonResult>(parseExcellon(text));
        else out.gerber = file.gerber ? file.gerber : std::make_shared<const GerberResult>(parseGerber(text));
    } catch (const std::exception& e) {
        out.error = QString::fromUtf8(e.what());
    }
    return out;
}

PcbFile readPcbFile(const QString& name, const QByteArray& text, std::optional<LayerKind> kind) {
    const LayerKind k = kind ? *kind : classifyLayer(name, std::string_view(text.constData(), size_t(text.size())));
    return parseAs(PcbFile{name, text, k, nullptr, nullptr, {}}, k);
}

std::vector<PcbFile> readPcbFiles(const std::vector<std::pair<QString, QByteArray>>& files) {
    std::vector<PcbFile> out(files.size());
    parallelFor(std::ptrdiff_t(files.size()), [&](std::ptrdiff_t i) { out[size_t(i)] = readPcbFile(files[size_t(i)].first, files[size_t(i)].second); });
    return out;
}

Polys stitchLoops(const Polys& lines, double tolMm) {
    std::vector<Poly> open;
    for (const Poly& l : lines) if (l.size() >= 2) open.push_back(l);
    const auto same = [tolMm](const Pt& a, const Pt& b) { return std::hypot(a.x - b.x, a.y - b.y) <= tolMm; };
    Polys loops;
    while (!open.empty()) {
        Poly cur = std::move(open.back());
        open.pop_back();
        bool grew = true;
        while (grew && !same(cur.front(), cur.back())) {
            grew = false;
            for (size_t i = open.size(); i-- > 0;) {
                const Poly& c = open[i];
                const Pt end = cur.back();
                if (same(c.front(), end)) cur.insert(cur.end(), c.begin() + 1, c.end());
                else if (same(c.back(), end)) cur.insert(cur.end(), c.rbegin() + 1, c.rend());
                else continue;
                open.erase(open.begin() + ptrdiff_t(i));
                grew = true;
                break;
            }
        }
        if (cur.size() >= 4 && same(cur.front(), cur.back())) { cur.back() = cur.front(); loops.push_back(std::move(cur)); }
    }
    std::sort(loops.begin(), loops.end(), [](const Poly& a, const Poly& b) { return std::abs(ringArea(a)) > std::abs(ringArea(b)); });
    return loops;
}

namespace {

std::optional<SideArt> art(const std::vector<PcbFile>& files, LayerKind kind) {
    std::vector<const GerberResult*> gs;
    for (const PcbFile& f : files) if (f.kind == kind && f.gerber) gs.push_back(f.gerber.get());
    if (gs.empty()) return std::nullopt;
    SideArt a;
    if (gs.size() == 1) a.polys = gs[0]->polys;
    else for (const GerberResult* g : gs) a.polys = addPolys(a.polys, g->polys);
    for (const GerberResult* g : gs)
        if (g->minStrokeWidth && (!a.minStroke || *g->minStrokeWidth < *a.minStroke)) a.minStroke = g->minStrokeWidth;
    a.area = polysArea(a.polys);
    return a;
}

}  // namespace

std::optional<Board> buildBoard(const std::vector<PcbFile>& files) {
    Board b;
    const LayerKind cu[2] = {LayerKind::CopperTop, LayerKind::CopperBottom}, ma[2] = {LayerKind::MaskTop, LayerKind::MaskBottom},
                    si[2] = {LayerKind::SilkTop, LayerKind::SilkBottom};
    for (int s = 0; s < 2; ++s) { b.copper[s] = art(files, cu[s]); b.mask[s] = art(files, ma[s]); b.silk[s] = art(files, si[s]); }
    for (const PcbFile& f : files)
        if (f.kind == LayerKind::Drill && f.drill) {
            b.drills.insert(b.drills.end(), f.drill->hits.begin(), f.drill->hits.end());
            b.slotHoles.insert(b.slotHoles.end(), f.drill->slotHoles.begin(), f.drill->slotHoles.end());
        }

    std::vector<const GerberResult*> outlineFiles;
    for (const PcbFile& f : files) if (f.kind == LayerKind::Outline && f.gerber) outlineFiles.push_back(f.gerber.get());
    Polys strokes;
    for (const GerberResult* g : outlineFiles) for (const GerberStroke& s : g->strokes) strokes.push_back(s.pts);
    b.outline = stitchLoops(strokes);
    if (b.outline.empty()) {
        for (const GerberResult* g : outlineFiles) for (const Poly& p : g->polys) if (ringArea(p) > 0) b.outline.push_back(p);
        std::sort(b.outline.begin(), b.outline.end(), [](const Poly& x, const Poly& y) { return ringArea(x) > ringArea(y); });
    }
    b.outlineFromFile = !b.outline.empty();
    if (!outlineFiles.empty() && !b.outlineFromFile)
        b.warnings << QStringLiteral("Die Umrissdatei ergibt keine geschlossene Kontur. Der Umriss ist aus dem Kupfer geschätzt.");

    std::optional<Box> box;
    if (b.outlineFromFile) box = boundsOfPolys({b.outline[0]});
    else {
        Polys all;
        for (int s = 0; s < 2; ++s)
            for (const auto* a : {&b.copper[s], &b.mask[s], &b.silk[s]})
                if (*a) all.insert(all.end(), (*a)->polys.begin(), (*a)->polys.end());
        for (const DrillHit& d : b.drills) all.push_back({{d.x, d.y}});
        box = boundsOfPolys(all);
    }
    if (!box) return std::nullopt;
    if (!b.outlineFromFile) {
        const double m = 1;
        const Box r{box->minX - m, box->minY - m, box->maxX + m, box->maxY + m};
        b.outline = {{{r.minX, r.minY}, {r.maxX, r.minY}, {r.maxX, r.maxY}, {r.minX, r.maxY}, {r.minX, r.minY}}};
        if (outlineFiles.empty()) b.warnings << QStringLiteral("Keine Umrissdatei: als Umriss gilt ein Rechteck 1 mm um das Kupfer.");
        b.bounds = r;
    } else {
        b.bounds = *box;
    }
    return b;
}

std::optional<Clearance> minClearance(const Polys& polys, double limitMm) {
    constexpr double cell = 0.5;
    struct Edge { double ax, ay, bx, by; int loop; };
    std::vector<Edge> edges;
    std::unordered_map<int64_t, std::vector<int>> grid;
    const auto key = [](int64_t x, int64_t y) { return (x + 2000000) * 4000000 + (y + 2000000); };
    for (size_t loop = 0; loop < polys.size(); ++loop) {
        const Poly& p = polys[loop];
        for (size_t i = 1; i < p.size(); ++i) {
            const Pt a = p[i - 1], b = p[i];
            if (a == b) continue;
            const int id = int(edges.size());
            edges.push_back({a.x, a.y, b.x, b.y, int(loop)});
            const int64_t x0 = int64_t(std::floor(std::min(a.x, b.x) / cell)), x1 = int64_t(std::floor(std::max(a.x, b.x) / cell));
            const int64_t y0 = int64_t(std::floor(std::min(a.y, b.y) / cell)), y1 = int64_t(std::floor(std::max(a.y, b.y) / cell));
            for (int64_t x = x0; x <= x1; ++x) for (int64_t y = y0; y <= y1; ++y) grid[key(x, y)].push_back(id);
        }
    }
    std::mutex mu;
    double globalBest = limitMm;
    std::optional<Pt> globalAt;
    parallelBlocks(std::ptrdiff_t(polys.size()), 8, [&](std::ptrdiff_t from, std::ptrdiff_t to) {
        double best = limitMm;
        std::optional<Pt> at;
        for (std::ptrdiff_t loop = from; loop < to; ++loop) {
            const Poly& p = polys[size_t(loop)];
            if (p.size() < 4) continue;
            const size_t n = p.size() - 1;   // closed ring: last point repeats the first
            for (size_t i = 0; i < n; ++i) {
                const Pt v = p[i], prev = p[(i + n - 1) % n], next = p[(i + 1) % n];
                const double e1x = v.x - prev.x, e1y = v.y - prev.y, e2x = next.x - v.x, e2y = next.y - v.y;
                const bool convex = e1x * e2y - e1y * e2x >= 0;
                const int64_t gx = int64_t(std::floor(v.x / cell)), gy = int64_t(std::floor(v.y / cell));
                const int64_t reach = int64_t(std::ceil(best / cell));
                for (int64_t dx = -reach; dx <= reach; ++dx)
                    for (int64_t dy = -reach; dy <= reach; ++dy) {
                        auto it = grid.find(key(gx + dx, gy + dy));
                        if (it == grid.end()) continue;
                        for (int id : it->second) {
                            const Edge& e = edges[size_t(id)];
                            if (e.loop == int(loop)) continue;
                            const double ex = e.bx - e.ax, ey = e.by - e.ay;
                            const double t = std::clamp(((v.x - e.ax) * ex + (v.y - e.ay) * ey) / (ex * ex + ey * ey), 0.0, 1.0);
                            const double cx = e.ax + t * ex - v.x, cy = e.ay + t * ey - v.y;
                            const double d = std::hypot(cx, cy);
                            if (d >= best || d < 1e-6) continue;
                            if (ex * (v.y - e.ay) - ey * (v.x - e.ax) > 0) continue;   // v lies on the copper side of that edge
                            const bool r1 = e1x * cy - e1y * cx < 0, r2 = e2x * cy - e2y * cx < 0;
                            if (!(convex ? r1 || r2 : r1 && r2)) continue;          // the line leaves v into its own copper
                            best = d;
                            at = Pt{v.x + cx / 2, v.y + cy / 2};
                        }
                    }
            }
        }
        if (at) {
            std::lock_guard lock(mu);
            if (best < globalBest) { globalBest = best; globalAt = at; }
        }
    });
    if (!globalAt) return std::nullopt;
    return Clearance{globalBest, *globalAt};
}

std::vector<std::pair<QString, QByteArray>> unpackPcbInputs(const std::vector<std::pair<QString, QByteArray>>& picked) {
    static const QRegularExpression skip(QStringLiteral("\\.(pdf|png|jpe?g|gbrjob|rpt|csv|pos|html|md|zip|step|stp|kicad_\\w+)$"),
                                         QRegularExpression::CaseInsensitiveOption);
    std::vector<std::pair<QString, QByteArray>> out;
    for (const auto& [name, bytes] : picked) {
        if (import::isZip(bytes)) {
            QHash<QString, QByteArray> entries;
            try {
                entries = import::readZip(bytes);
            } catch (const std::exception& e) {
                throw std::runtime_error(std::string("Die ZIP-Datei ist beschädigt: ") + e.what());
            }
            QStringList names = entries.keys();
            names.sort();
            for (const QString& n : names) {
                if (n.endsWith(QLatin1Char('/')) || skip.match(n).hasMatch()) continue;
                out.emplace_back(n.section(QLatin1Char('/'), -1), entries.value(n));
            }
        } else if (!skip.match(name).hasMatch()) {
            out.emplace_back(name, bytes);
        }
    }
    return out;
}

std::vector<std::pair<QString, QByteArray>> exampleBoardFiles() {
    std::vector<std::pair<QString, QByteArray>> out;
    for (const char* n : {"beispiel.GTL", "beispiel.GBL", "beispiel.GTS", "beispiel.GBS", "beispiel.GTO", "beispiel.GKO", "beispiel.DRL"}) {
        QFile f(QStringLiteral(":/pcb/") + QLatin1String(n));
        if (f.open(QIODevice::ReadOnly)) out.emplace_back(QLatin1String(n), f.readAll());
    }
    return out;
}

}  // namespace lumacut::pcb
