/**
 * ASCII-DXF wie DxfImport.kt und dxf.ts: Linienzüge in mm, Y nach unten. LINE, LWPOLYLINE und POLYLINE mit Bögen, CIRCLE,
 * ARC, ELLIPSE, SPLINE, INSERT von Blöcken. Einheiten aus $INSUNITS (keine = mm). Alles andere wird gezählt und gemeldet.
 * Paare liegen als Sichten in einem flachen Feld; die Elemente der obersten Ebene laufen mehrkernig, Reihenfolge wie in der Datei.
 */
#include "core/fastnum.h"
#include "core/import/vector.h"
#include "core/import/xml.h"
#include "core/parallel.h"

#include <QHash>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <map>
#include <mutex>

namespace lumacut::import {
namespace {

constexpr double SEG_MM = 0.25;
constexpr double PI = 3.14159265358979323846;
constexpr qint64 MAX_INSERTS = 50'000'000;
constexpr int MAX_DEGREE = 32;

QString tooComplex() { return QStringLiteral("DXF zu komplex"); }

struct Pair {
    int code;
    QByteArrayView value;
};
struct Entity {
    QByteArrayView type;
    uint32_t begin, end;    /// Paare ohne das einleitende (0, Typ)
};
using EntityList = std::vector<Entity>;

struct Reader {
    std::vector<Pair> pairs;

    const Pair* find(const Entity& e, int code) const {
        for (uint32_t i = e.begin; i < e.end; ++i) if (pairs[i].code == code) return &pairs[i];
        return nullptr;
    }
    double d(const Entity& e, int code, double dflt = 0) const {
        const Pair* p = find(e, code);
        return p ? parseFloatOr(p->value, dflt) : dflt;
    }
    int i(const Entity& e, int code, int dflt = 0) const {
        const double v = d(e, code, dflt);
        return v >= -2e9 && v <= 2e9 ? int(v) : dflt;
    }
    QByteArrayView s(const Entity& e, int code) const {
        const Pair* p = find(e, code);
        return p ? trimmedView(p->value) : QByteArrayView();
    }
    std::vector<double> all(const Entity& e, int code) const {
        std::vector<double> out;
        for (uint32_t i = e.begin; i < e.end; ++i) {
            if (pairs[i].code != code) continue;
            const double v = parseFloatOr(pairs[i].value, std::nan(""));
            if (!std::isnan(v)) out.push_back(v);
        }
        return out;
    }
};

struct Vertex {
    Pt p;
    double bulge;
};

/** Linienzug mit Bögen (bulge = tan(Winkel / 4), positiv gegen den Uhrzeigersinn). */
Poly bulgePath(const std::vector<Vertex>& pts, bool closed) {
    if (pts.empty()) return {};
    Poly out{pts[0].p};
    const size_t count = closed ? pts.size() : pts.size() - 1;
    for (size_t k = 0; k < count; ++k) {
        const Pt p0 = pts[k].p, p1 = pts[(k + 1) % pts.size()].p;
        const double bulge = pts[k].bulge;
        const double chord = std::hypot(p1.x - p0.x, p1.y - p0.y);
        if (std::fabs(bulge) < 1e-9 || chord < 1e-12) { out.push_back(p1); continue; }
        const double theta = 4 * std::atan(bulge);
        const double r = chord / (2 * std::sin(std::fabs(theta) / 2));
        const double h = r * std::cos(theta / 2);
        const double nx = -(p1.y - p0.y) / chord, ny = (p1.x - p0.x) / chord, sgn = bulge > 0 ? 1 : -1;
        const Pt c{(p0.x + p1.x) / 2 + nx * h * sgn, (p0.y + p1.y) / 2 + ny * h * sgn};
        const double a0 = std::atan2(p0.y - c.y, p0.x - c.x);
        const int n = clampSteps(std::fabs(theta) * r / SEG_MM, 4, 720);
        for (int s = 1; s <= n; ++s) {
            const double a = a0 + theta * s / n;
            out.push_back(s == n ? p1 : Pt{c.x + r * std::cos(a), c.y + r * std::sin(a)});
        }
    }
    if (closed && out.front() != out.back()) out.push_back(out.front());
    return out;
}

Poly arc(Pt c, double r, double a0, double a1) {
    const int n = clampSteps((a1 - a0) * r / SEG_MM, 12, 2000);
    Poly out;
    out.reserve(size_t(n) + 1);
    for (int s = 0; s <= n; ++s) {
        const double a = a0 + (a1 - a0) * s / n;
        out.push_back({c.x + r * std::cos(a), c.y + r * std::sin(a)});
    }
    return out;
}

/** B-Spline (de Boor) aus Kontrollpunkten und Knoten; sonst die Stützpunkte. */
Poly spline(const Reader& rd, const Entity& e) {
    const int degree = rd.i(e, 71, 3);
    const std::vector<double> knots = rd.all(e, 40), cx = rd.all(e, 10), cy = rd.all(e, 20);
    Poly ctrl;
    for (size_t i = 0; i < std::min(cx.size(), cy.size()); ++i) ctrl.push_back({cx[i], cy[i]});
    if (degree < 1 || degree > MAX_DEGREE || ctrl.size() < 2 || ctrl.size() <= size_t(degree) || knots.size() != ctrl.size() + size_t(degree) + 1) {
        const std::vector<double> fx = rd.all(e, 11), fy = rd.all(e, 21);
        Poly fit;
        for (size_t i = 0; i < std::min(fx.size(), fy.size()); ++i) fit.push_back({fx[i], fy[i]});
        return fit.empty() ? ctrl : fit;
    }
    const double t0 = knots[size_t(degree)], t1 = knots[ctrl.size()];
    double approx = 0;
    for (size_t i = 1; i < ctrl.size(); ++i) approx += std::hypot(ctrl[i].x - ctrl[i - 1].x, ctrl[i].y - ctrl[i - 1].y);
    const int n = clampSteps(approx / SEG_MM, 16, 4000);
    Poly out;
    out.reserve(size_t(n) + 1);
    Pt d[MAX_DEGREE + 1];
    for (int s = 0; s <= n; ++s) {
        const double t = s == n ? t1 - 1e-9 * (t1 - t0) : t0 + (t1 - t0) * s / n;
        size_t span = size_t(degree);
        while (span < ctrl.size() - 1 && t >= knots[span + 1]) ++span;
        for (int j = 0; j <= degree; ++j) d[j] = ctrl[span - size_t(degree) + size_t(j)];
        for (int r = 1; r <= degree; ++r) {
            for (int j = degree; j >= r; --j) {
                const size_t i = span - size_t(degree) + size_t(j);
                const double denom = knots[i + size_t(degree - r) + 1] - knots[i];
                const double alpha = denom == 0 ? 0 : (t - knots[i]) / denom;
                d[j] = {(1 - alpha) * d[j - 1].x + alpha * d[j].x, (1 - alpha) * d[j - 1].y + alpha * d[j].y};
            }
        }
        out.push_back(d[degree]);
    }
    return out;
}

bool ignored(QByteArrayView t) {
    return t == "VERTEX" || t == "SEQEND" || t == "POINT" || t == "VIEWPORT" || t == "ATTDEF" || t == "ATTRIB" || t == "ENDBLK" || t == "BLOCK" ||
           t == "SECTION" || t == "ENDSEC" || t == "EOF";
}
QString entityLabel(QByteArrayView t) {
    if (t == "TEXT" || t == "MTEXT") return QStringLiteral("Text");
    if (t == "HATCH") return QStringLiteral("Schraffur");
    if (t == "DIMENSION") return QStringLiteral("Bemaßung");
    if (t == "LEADER") return QStringLiteral("Hinweislinie");
    if (t == "IMAGE") return QStringLiteral("Bild");
    if (t == "SOLID") return QStringLiteral("Fläche");
    return QString::fromUtf8(t.left(40));
}

struct Skipped {
    std::vector<std::pair<QString, int>> list;
    void add(const QString& name, int n = 1) {
        for (auto& e : list) if (e.first == name) { e.second += n; return; }
        list.push_back({name, n});
    }
};

struct Emitter {
    const Reader& rd;
    const QHash<QByteArray, EntityList>& blocks;
    PointBudget& budget;
    std::atomic<qint64>& inserts;

    /** list[from, to): wer an `from` beginnt, gehört hierher; ein POLYLINE nimmt seine Scheitel mit, auch über `to` hinaus. */
    void walk(const EntityList& list, size_t from, size_t to, const Matrix& m, PolySet& out, Skipped& skipped, int depth) const {
        if (depth > 8) return;
        for (size_t idx = from; idx < to; ++idx) {
            const Entity& e = list[idx];
            const QByteArrayView type = e.type;
            Poly local;
            if (type == "LINE") {
                const Pt p[2] = {m.apply({rd.d(e, 10), rd.d(e, 20)}), m.apply({rd.d(e, 11), rd.d(e, 21)})};
                budget.take(2);
                out.add(PolyView(p, 2));
                continue;
            } else if (type == "LWPOLYLINE") {
                std::vector<Vertex> pts;
                bool hasCur = false;
                Pt cur;
                double bulge = 0, x = 0;
                for (uint32_t i = e.begin; i < e.end; ++i) {
                    const Pair& pr = rd.pairs[i];
                    if (pr.code == 10) {
                        if (hasCur) pts.push_back({cur, bulge});
                        x = parseFloatOr(pr.value, 0);
                        bulge = 0;
                        hasCur = false;
                    } else if (pr.code == 20) {
                        cur = {x, parseFloatOr(pr.value, 0)};
                        hasCur = true;
                    } else if (pr.code == 42) {
                        bulge = parseFloatOr(pr.value, 0);
                    }
                }
                if (hasCur) pts.push_back({cur, bulge});
                local = bulgePath(pts, (rd.i(e, 70) & 1) == 1);
            } else if (type == "POLYLINE") {
                std::vector<Vertex> pts;
                size_t j = idx + 1;
                while (j < list.size() && list[j].type == "VERTEX") {
                    pts.push_back({{rd.d(list[j], 10), rd.d(list[j], 20)}, rd.d(list[j], 42)});
                    ++j;
                }
                if (j < list.size() && list[j].type == "SEQEND") ++j;
                idx = j - 1;
                local = bulgePath(pts, (rd.i(e, 70) & 1) == 1);
            } else if (type == "CIRCLE") {
                local = arc({rd.d(e, 10), rd.d(e, 20)}, rd.d(e, 40), 0, 2 * PI);
            } else if (type == "ARC") {
                const double a0 = rd.d(e, 50) * PI / 180;
                double a1 = rd.d(e, 51) * PI / 180;
                if (a1 <= a0) a1 += 2 * PI;
                local = arc({rd.d(e, 10), rd.d(e, 20)}, rd.d(e, 40), a0, a1);
            } else if (type == "ELLIPSE") {
                const Pt c{rd.d(e, 10), rd.d(e, 20)}, major{rd.d(e, 11), rd.d(e, 21)};
                const double ratio = rd.d(e, 40, 1), t0 = rd.d(e, 41, 0);
                double t1 = rd.d(e, 42, 2 * PI);
                if (t1 <= t0) t1 += 2 * PI;
                const double a = std::hypot(major.x, major.y), rot = std::atan2(major.y, major.x);
                const int n = clampSteps((t1 - t0) * a / SEG_MM, 24, 2000);
                local.reserve(size_t(n) + 1);
                for (int s = 0; s <= n; ++s) {
                    const double t = t0 + (t1 - t0) * s / n, ex = a * std::cos(t), ey = a * ratio * std::sin(t);
                    local.push_back({c.x + ex * std::cos(rot) - ey * std::sin(rot), c.y + ex * std::sin(rot) + ey * std::cos(rot)});
                }
            } else if (type == "SPLINE") {
                local = spline(rd, e);
            } else if (type == "INSERT") {
                if (inserts.fetch_add(1, std::memory_order_relaxed) > MAX_INSERTS) throw ImportError(tooComplex());
                const QByteArrayView name = rd.s(e, 2);
                const auto block = blocks.constFind(QByteArray::fromRawData(name.data(), name.size()));
                if (block != blocks.constEnd()) {
                    const double r = rd.d(e, 50) * PI / 180;
                    const Matrix t = m * Matrix{1, 0, 0, 1, rd.d(e, 10), rd.d(e, 20)} * Matrix{std::cos(r), std::sin(r), -std::sin(r), std::cos(r), 0, 0} *
                                     Matrix{rd.d(e, 41, 1), 0, 0, rd.d(e, 42, 1), 0, 0};
                    walk(*block, 0, block->size(), t, out, skipped, depth + 1);
                }
                continue;
            } else {
                if (!ignored(type)) skipped.add(entityLabel(type));
                continue;
            }
            if (local.size() >= 2) {
                budget.take(qint64(local.size()));
                std::span<Pt> o = out.addUninitialized(local.size());
                for (size_t i = 0; i < local.size(); ++i) o[i] = m.apply(local[i]);
            }
        }
    }
};

}  // namespace

VectorImport parseDxf(const QByteArray& bytes) {
    if (bytes.isEmpty()) throw ImportError(QStringLiteral("Leere Datei"));
    if (bytes.startsWith("AutoCAD Binary DXF")) throw ImportError(QStringLiteral("Binäres DXF wird nicht unterstützt, bitte als ASCII-DXF speichern"));

    // Zeilen zu Paaren. Nach (0, EOF) ist Schluss; leere Zeilen am Dateiende sind kein Fehler.
    Reader rd;
    rd.pairs.reserve(size_t(bytes.size() / 12 + 8));
    const char* p = bytes.constData();
    const char* end = p + bytes.size();
    const auto nextLine = [&](QByteArrayView& out) {
        if (p >= end) return false;
        const char* nl = static_cast<const char*>(std::memchr(p, '\n', size_t(end - p)));
        const char* stop = nl ? nl : end;
        out = QByteArrayView(p, (stop > p && stop[-1] == '\r') ? stop - p - 1 : stop - p);
        p = nl ? nl + 1 : end;
        return true;
    };
    for (;;) {
        QByteArrayView codeLine, valueLine;
        if (!nextLine(codeLine)) break;
        const bool hasValue = nextLine(valueLine);
        const QByteArrayView code = trimmedView(codeLine);
        if (code.isEmpty() && !hasValue) break;
        if (!hasValue) break;       // ungerade Zeilenzahl: das letzte Stück fehlt, wie in der Vorlage kein Fehler
        int value = 0;
        qsizetype i = 0;
        const bool neg = !code.isEmpty() && code[0] == '-';
        if (neg) i = 1;
        if (i >= code.size() || code.size() > 9) throw ImportError(QStringLiteral("Keine gültige DXF-Datei"));
        for (; i < code.size(); ++i) {
            if (code[i] < '0' || code[i] > '9') throw ImportError(QStringLiteral("Keine gültige DXF-Datei"));
            value = value * 10 + (code[i] - '0');
        }
        rd.pairs.push_back({neg ? -value : value, valueLine});
        if (value == 0 && !neg && trimmedView(valueLine) == "EOF") break;
    }

    double units = 1;
    QByteArrayView section;
    QHash<QByteArray, EntityList> blocks;
    EntityList entities;
    EntityList* currentBlock = nullptr;
    size_t i = 0;
    const size_t np = rd.pairs.size();
    entities.reserve(np / 6 + 4);
    while (i < np) {
        const int code = rd.pairs[i].code;
        const QByteArrayView v = trimmedView(rd.pairs[i].value);
        if (code == 0 && v == "SECTION") {
            section = i + 1 < np ? trimmedView(rd.pairs[i + 1].value) : QByteArrayView();
            i += 2;
            continue;
        }
        if (code == 0 && v == "ENDSEC") { section = {}; ++i; continue; }
        if (section == "HEADER" && code == 9 && v == "$INSUNITS") {
            const int u = i + 1 < np ? int(parseFloatOr(rd.pairs[i + 1].value, 0)) : 0;
            units = u == 1 ? 25.4 : u == 5 ? 10 : u == 6 ? 1000 : u == 2 ? 304.8 : 1;
            i += 2;
            continue;
        }
        if (code == 0 && (section == "ENTITIES" || section == "BLOCKS")) {
            size_t j = i + 1;
            while (j < np && rd.pairs[j].code != 0) ++j;
            const Entity e{v, uint32_t(i + 1), uint32_t(j)};
            if (section == "BLOCKS" && v == "BLOCK") currentBlock = &blocks[rd.s(e, 2).toByteArray()];
            else if (section == "BLOCKS" && v == "ENDBLK") currentBlock = nullptr;
            else if (section == "BLOCKS") { if (currentBlock) currentBlock->push_back(e); }
            else entities.push_back(e);
            i = j;
            continue;
        }
        ++i;
    }

    // Startpunkte: ein POLYLINE mit seinen Scheiteln bleibt beisammen.
    std::vector<uint32_t> starts;
    starts.reserve(entities.size());
    for (size_t k = 0; k < entities.size(); ++k) {
        const QByteArrayView t = entities[k].type;
        if (t != "VERTEX" && t != "SEQEND") starts.push_back(uint32_t(k));
    }
    PointBudget budget(tooComplex());
    std::atomic<qint64> inserts{0};
    const Emitter emitter{rd, blocks, budget, inserts};
    struct Chunk {
        PolySet polys;
        Skipped skipped;
    };
    std::map<std::ptrdiff_t, Chunk> chunks;
    std::mutex chunkLock;
    parallelBlocks(std::ptrdiff_t(starts.size()), 512, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        Chunk c;
        for (std::ptrdiff_t k = a; k < b; ++k) {
            const size_t s = starts[size_t(k)];
            emitter.walk(entities, s, s + 1, Matrix{}, c.polys, c.skipped, 0);
        }
        const std::lock_guard<std::mutex> lock(chunkLock);
        chunks.emplace(a, std::move(c));
    });

    VectorImport r;
    Skipped skipped;
    size_t polyCount = 0, pointCount = 0;
    for (const auto& [at, c] : chunks) { polyCount += c.polys.size(); pointCount += c.polys.pointCount(); }
    if (polyCount == 0) throw ImportError(QStringLiteral("Keine unterstützten Zeichnungselemente gefunden"));
    r.polys.reserve(polyCount, pointCount);
    for (auto& [at, c] : chunks) {
        r.polys.append(c.polys);
        for (const auto& [name, n] : c.skipped.list) skipped.add(name, n);
        c.polys.clear();
    }
    // DXF: Y nach oben; die Fläche: Y nach unten.
    std::span<Pt> all = r.polys.allPoints();
    double maxY = -HUGE_VAL, minX = HUGE_VAL;
    for (Pt& q : all) {
        q = {q.x * units, q.y * units};
        if (std::isfinite(q.x) && std::isfinite(q.y)) { maxY = std::max(maxY, q.y); minX = std::min(minX, q.x); }
    }
    for (Pt& q : all) q = {q.x - minX, maxY - q.y};
    for (const auto& [name, n] : skipped.list) r.skipped.push_back(QStringLiteral("%1× %2").arg(n).arg(name));
    return r;
}

}  // namespace lumacut::import
