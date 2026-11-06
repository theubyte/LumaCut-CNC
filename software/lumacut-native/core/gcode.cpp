#include "core/gcode.h"
#include "core/geometry.h"
#include "core/image.h"
#include "core/parallel.h"

#include <QHash>
#include <QSet>
#include <algorithm>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstring>
#include <memory>

namespace lumacut {
namespace {

inline double clamp(double v, double lo, double hi) { return v < lo ? lo : v > hi ? hi : v; }
inline int jroundInt(double x) {
    const double f = std::floor(x);
    return int(x - f >= 0.5 ? f + 1 : f);
}
inline int powerS(double pct) { return jroundInt(clamp(pct, 0.0, 100.0) / 100.0 * 255); }
inline int feedOf(const Layer& l) { return jroundInt(clamp(l.speed, Limits::SPEED_MIN, Limits::SPEED_MAX)); }
inline bool inRange(double v, double lo, double hi) { return v >= lo && v <= hi; }

/** Wachsender Puffer ohne Nullen vorab. */
class Buf {
public:
    explicit Buf(size_t cap = 1 << 16) : m_data(new char[cap]), m_cap(cap) {}
    /** Mindestens n freie Bytes; Schreibposition. */
    char* room(size_t n) {
        if (m_len + n > m_cap) {
            const size_t cap = std::max(m_cap * 2, m_len + n);
            std::unique_ptr<char[]> d(new char[cap]);
            std::memcpy(d.get(), m_data.get(), m_len);
            m_data = std::move(d);
            m_cap = cap;
        }
        return m_data.get() + m_len;
    }
    void setEnd(char* p) { m_len = size_t(p - m_data.get()); }
    void append(const char* s, size_t n) { std::memcpy(room(n), s, n); m_len += n; }
    void append(QByteArrayView s) { append(s.data(), size_t(s.size())); }
    void line(QByteArrayView s) { append(s); append("\n", 1); }
    const char* data() const { return m_data.get(); }
    size_t size() const { return m_len; }
private:
    std::unique_ptr<char[]> m_data;
    size_t m_cap, m_len = 0;
};

inline char* put(char* p, const char* s, size_t n) { std::memcpy(p, s, n); return p + n; }

/** "S" und Leistung 0..255 samt Zeilenende, fest vorberechnet. */
struct PowerText {
    char s[6];
    uint8_t len;
};
const PowerText* powerTable() {
    static const auto table = [] {
        auto t = std::make_unique<PowerText[]>(256);
        for (int i = 0; i < 256; ++i) {
            char* p = t[i].s;
            *p++ = 'S';
            p = std::to_chars(p, p + 3, i).ptr;
            *p++ = '\n';
            t[i].len = uint8_t(p - t[i].s);
        }
        return t;
    }();
    return table.get();
}

/** " F3000 " je Ebene. */
struct FeedText {
    char s[16];
    size_t len;
    explicit FeedText(int feed) {
        char* p = s;
        *p++ = ' ';
        *p++ = 'F';
        p = std::to_chars(p, s + sizeof s, feed).ptr;
        *p++ = ' ';
        len = size_t(p - s);
    }
};

/** Schreibt G0/G1-Zeilen, merkt sich die Position. Y wiederholt sich oft und wird nur bei Änderung formatiert. */
class Emit {
public:
    Emit(Buf& out, double w, double h) : m_out(out), m_w(w), m_h(h) {}
    bool hasAt = false;
    double atX = 0, atY = 0;

    void rapid(double x, double y) {
        if (!hasAt || hypotJ(x - atX, y - atY) > 1e-6) {
            char* p = m_out.room(64);
            p = put(p, "G0 ", 3);
            p = xy(p, x, y);
            *p++ = '\n';
            m_out.setEnd(p);
        }
        hasAt = true; atX = x; atY = y;
    }
    void burn(double x, double y, int power, const FeedText& feed) {
        static const PowerText* const table = powerTable();
        char* p = m_out.room(80);
        p = put(p, "G1 ", 3);
        p = xy(p, x, y);
        p = put(p, feed.s, feed.len);
        p = put(p, table[power].s, table[power].len);
        m_out.setEnd(p);
        hasAt = true; atX = x; atY = y;
    }
private:
    char* xy(char* p, double x, double y) {
        const double my = clamp(y, 0.0, m_h);
        if (std::memcmp(&my, &m_lastY, sizeof(double)) != 0 || m_yLen == 0) {
            m_lastY = my;
            char* e = fmt3Into(m_yText, my);
            m_yLen = size_t(e - m_yText);
        }
        *p++ = 'X';
        p = fmt3Into(p, m_w - clamp(x, 0.0, m_w));
        *p++ = ' ';
        *p++ = 'Y';
        return put(p, m_yText, m_yLen);
    }
    Buf& m_out;
    double m_w, m_h;
    double m_lastY = 0;
    size_t m_yLen = 0;
    char m_yText[32];
};

/** Ein Bild, fertig formatiert: bleibt über alle Durchgänge gleich, nur das erste G0 hängt vom Vorgänger ab. */
struct RasterText {
    std::vector<Buf> parts;
    size_t firstG0Len = 0;
    double startX = 0, startY = 0, endX = 0, endY = 0;
    bool any = false;
};

/** Spalte → vorformatiertes "X123.456" und die Lage in Arbeits-mm. */
struct ColumnText {
    double x;
    char s[14];
    uint8_t len;
};

RasterText rasterText(const Element& el, const Box& box, const Layer& layer, const Motion& motion, double W, double H) {
    RasterText out;
    const double interval = clamp(layer.intervalMm, 0.03, 2.0);
    const double bw = box.width(), bh = box.height();
    const int rows = std::max(1, int(bh / interval)), cols = std::max(1, int(bw / interval));
    const Gray levels = jobLevels(el.raster, cols, rows, el.adjust, el.imageMode);

    const int maxS = powerS(layer.powerPct), minS = powerS(layer.minPowerPct);
    int power[256];
    for (int g = 0; g < 256; ++g)
        power[g] = g >= 250 ? 0 : jroundInt(minS + (maxS - minS) * layer.powerShare((255 - g) / 255.0));

    const int feed = feedOf(layer);
    const FeedText feedText(feed);
    const double over = std::min(std::max(clamp(layer.overscanMm, 0.0, 10.0), motion.runUp(double(feed))), 40.0);

    const double cell = bw / cols;
    std::vector<ColumnText> columns(static_cast<size_t>(cols) + 1);
    parallelBlocks(cols + 1, 1024, [&](std::ptrdiff_t c0, std::ptrdiff_t c1) {
        for (std::ptrdiff_t c = c0; c < c1; ++c) {
            ColumnText& t = columns[size_t(c)];
            t.x = box.minX + double(c) * cell;
            t.s[0] = 'X';
            t.len = uint8_t(fmt3Into(t.s + 1, W - clamp(t.x, 0.0, W)) - t.s);
        }
    });

    struct Run { int c0, c1, power; };
    const int blocks = std::min(rows, idealThreads() * 8);
    out.parts.reserve(size_t(blocks));
    const size_t perRowGuess = 64;
    for (int b = 0; b < blocks; ++b) out.parts.emplace_back(perRowGuess * size_t(cols / 8 + 4) * size_t(rows / blocks + 1));
    struct BlockInfo { bool any = false; size_t g0 = 0; double sx = 0, sy = 0, ex = 0, ey = 0; };
    std::vector<BlockInfo> infos(static_cast<size_t>(blocks));

    const PowerText* const powers = powerTable();
    const auto work = [&](int b) {
        Buf& buf = out.parts[size_t(b)];
        BlockInfo& info = infos[size_t(b)];
        const int r0 = int(qint64(rows) * b / blocks), r1 = int(qint64(rows) * (b + 1) / blocks);
        std::vector<Run> runs;
        for (int r = r0; r < r1; ++r) {
            const uint8_t* row = levels.data() + size_t(r) * cols;
            runs.clear();
            int first = -1, last = -1;
            for (int c = 0; c < cols;) {
                const uint8_t level = row[c];
                int e = c + 1;
                while (e < cols && row[e] == level) ++e;
                const int p = power[level];
                if (p > 0) {
                    if (first < 0) first = int(runs.size());
                    last = int(runs.size());
                }
                runs.push_back({c, e, p});
                c = e;
            }
            if (first < 0) continue;
            const double y = box.minY + (r + 0.5) * bh / rows;
            const bool forward = r % 2 == 0;
            char yText[40];
            yText[0] = ' ';
            yText[1] = 'Y';
            const size_t yLen = size_t(fmt3Into(yText + 2, clamp(y, 0.0, H)) - yText);

            const int firstCol = forward ? runs[size_t(first)].c0 : runs[size_t(last)].c1;
            const int lastCol = forward ? runs[size_t(last)].c1 : runs[size_t(first)].c0;
            const double dir = (forward ? columns[size_t(runs[size_t(first)].c1)].x >= columns[size_t(runs[size_t(first)].c0)].x : columns[size_t(runs[size_t(last)].c0)].x >= columns[size_t(runs[size_t(last)].c1)].x) ? 1.0 : -1.0;
            const double startX = clamp(columns[size_t(firstCol)].x - dir * over, 0.0, W);
            const double endX = clamp(columns[size_t(lastCol)].x + dir * over, 0.0, W);

            const auto g1Col = [&](char* p, int col, int pw) {
                const ColumnText& t = columns[size_t(col)];
                p = put(p, "G1 ", 3);
                p = put(p, t.s, t.len);
                p = put(p, yText, yLen);
                p = put(p, feedText.s, feedText.len);
                return put(p, powers[pw].s, powers[pw].len);
            };
            const auto g1Free = [&](char* p, double x) {
                p = put(p, "G1 X", 4);
                p = fmt3Into(p, W - clamp(x, 0.0, W));
                p = put(p, yText, yLen);
                p = put(p, feedText.s, feedText.len);
                return put(p, powers[0].s, powers[0].len);
            };

            const size_t before = buf.size();
            char* p = buf.room(64 * (size_t(last - first + 1) * 2 + 4));
            p = put(p, "G0 X", 4);
            p = fmt3Into(p, W - clamp(startX, 0.0, W));
            p = put(p, yText, yLen);
            *p++ = '\n';
            const size_t g0Len = size_t(p - buf.data()) - before;
            double atX = startX;
            if (startX != columns[size_t(firstCol)].x) {
                p = g1Col(p, firstCol, 0);
                atX = columns[size_t(firstCol)].x;
            }
            const auto one = [&](int from, int to, int pw) {
                if (std::fabs(atX - columns[size_t(from)].x) > 1e-6) p = g1Col(p, from, 0);
                p = g1Col(p, to, pw);
                atX = columns[size_t(to)].x;
            };
            if (forward) for (int k = first; k <= last; ++k) one(runs[size_t(k)].c0, runs[size_t(k)].c1, runs[size_t(k)].power);
            else for (int k = last; k >= first; --k) one(runs[size_t(k)].c1, runs[size_t(k)].c0, runs[size_t(k)].power);
            if (endX != atX) {
                p = g1Free(p, endX);
                atX = endX;
            }
            buf.setEnd(p);
            if (!info.any) {
                info.any = true;
                info.g0 = g0Len;
                info.sx = startX;
                info.sy = y;
            }
            info.ex = atX;
            info.ey = y;
        }
    };
    if (blocks == 1) work(0);
    else parallelFor(blocks, [&](std::ptrdiff_t b) { work(int(b)); });

    for (const BlockInfo& i : infos) {
        if (!i.any) continue;
        if (!out.any) {
            out.any = true;
            out.firstG0Len = i.g0;
            out.startX = i.sx;
            out.startY = i.sy;
        }
        out.endX = i.ex;
        out.endY = i.ey;
    }
    return out;
}

}  // namespace

QByteArray writeMarlin(const Document& doc, const WriteOptions& options) {
    const Motion& motion = options.motion;
    const double W = Bed::width(), H = Bed::height();

    QSet<QString> active;
    for (const Layer& l : doc.layers) if (l.output && l.visible) active.insert(l.id);
    std::vector<const Element*> content;
    for (const Element& e : doc.elements) if (active.contains(e.layerId)) content.push_back(&e);
    if (content.empty()) throw JobBuildError(QStringLiteral("Nichts zu lasern: keine Elemente auf sichtbaren Ebenen"));

    // Weltkoordinaten nur einmal rechnen: Prüfung und Ausgabe brauchen sie beide.
    std::vector<PolySet> world(content.size());
    std::vector<std::optional<Box>> boxes(content.size());
    parallelBlocks(std::ptrdiff_t(content.size()), 16, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
        for (std::ptrdiff_t i = i0; i < i1; ++i) {
            const Element& e = *content[size_t(i)];
            if (e.isImage()) boxes[size_t(i)] = e.worldBounds();
            else {
                world[size_t(i)] = e.worldPaths();
                boxes[size_t(i)] = boundsOf(world[size_t(i)]);
            }
        }
    });
    for (size_t i = 0; i < content.size(); ++i) {
        const Element& e = *content[i];
        if (!boxes[i]) continue;
        const QString name = e.text.value_or(e.kind);
        if (!Work::contains(*boxes[i]))
            throw JobBuildError(QStringLiteral("„%1“ ragt über die Arbeitsfläche hinaus").arg(name));
        if (e.touchesPark())
            throw JobBuildError(QStringLiteral("„%1“ liegt im Bereich %2 (oben) – dort wird nicht gelasert").arg(name, Work::parkName()));
        if (e.isImage() && std::fabs(e.transform.rotation) > 1e-6)
            throw JobBuildError(QStringLiteral("Gedrehte Bilder werden noch nicht unterstützt – Drehung auf 0° setzen"));
    }
    std::vector<const Layer*> activeLayers;
    for (const Layer& l : doc.layers) if (active.contains(l.id)) activeLayers.push_back(&l);
    for (const Layer* l : activeLayers) {
        if (!inRange(l->powerPct, Limits::POWER_MIN, Limits::POWER_MAX) || !inRange(l->speed, Limits::SPEED_MIN, Limits::SPEED_MAX) ||
            l->passes < Limits::PASSES_MIN || l->passes > Limits::PASSES_MAX)
            throw JobBuildError(QStringLiteral("Ungültige Werte auf Ebene „%1“").arg(l->name));
        if (l->speed > motion.maxFeed() + 1e-6)
            throw JobBuildError(QStringLiteral("Ebene „%1“: %2 mm/min – die Maschine fährt höchstens %3 mm/min (Maschine → Kalibrieren → Bewegung)")
                                    .arg(l->name, QString::fromLatin1(fmtFixed(l->speed, 0, ',')), QString::fromLatin1(fmtFixed(motion.maxFeed(), 0, ','))));
        if (!inRange(l->zStepMm, Limits::Z_STEP_MIN, Limits::Z_STEP_MAX) || l->focusDropMm() > Limits::MAX_FOCUS_DROP_MM + 1e-6)
            throw JobBuildError(QStringLiteral("Fokus-Absenkung zu groß auf „%1“ (%2 mm > %3 mm)")
                                    .arg(l->name, QString::fromLatin1(fmtFixed(l->focusDropMm(), 2, ',')), QString::fromLatin1(fmtFixed(Limits::MAX_FOCUS_DROP_MM, 0, ','))));
    }

    Buf out(1 << 20);
    Emit gw(out, W, H);
    QByteArray title = doc.title.toUtf8();
    title.replace('\r', ' ');
    title.replace('\n', ' ');
    out.append("; LumaCut App ", 14);
    out.append(options.appVersion);
    out.append(QByteArrayView(" – "));
    out.line(title);
    out.line("G21");
    out.line("G90");
    out.line("M5 I");
    out.line("M3 I");

    for (const Layer* layerPtr : activeLayers) {
        const Layer& layer = *layerPtr;
        std::vector<size_t> images, vectors;
        for (size_t i = 0; i < content.size(); ++i) {
            if (content[i]->layerId != layer.id) continue;
            (content[i]->isImage() ? images : vectors).push_back(i);
        }
        if (images.empty() && vectors.empty()) continue;
        out.append("; Ebene ", 8);
        out.line(layer.name.toUtf8());

        // Bilder einmal berechnen, je Bild parallel: die Diffusion ist in sich seriell.
        std::vector<RasterText> rasters(images.size());
        std::atomic_bool badImage{false};
        parallelBlocks(std::ptrdiff_t(images.size()), 1, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
            for (std::ptrdiff_t i = i0; i < i1; ++i) {
                const size_t k = images[size_t(i)];
                if (!boxes[k]) continue;
                try {
                    rasters[size_t(i)] = rasterText(*content[k], *boxes[k], layer, motion, W, H);
                } catch (const std::exception&) {
                    badImage = true;
                }
            }
        });
        if (badImage) throw JobBuildError(QStringLiteral("Ungültige Bilddaten"));

        PolySet vector;
        for (const size_t i : vectors) vector.append(world[i]);

        // Füllung einmal schraffieren; nur die erste Leerfahrt hängt von der Position ab.
        PolySet hatched;
        if (layer.mode == LayerMode::Fill && !vector.empty()) {
            PolySet closed;
            for (PolyView p : vector) if (isClosed(p)) closed.add(p);
            if (!closed.empty()) hatched = hatch(closed, clamp(layer.intervalMm, 0.03, 2.0));
        }
        const int feed = feedOf(layer), power = powerS(layer.powerPct);
        const FeedText feedText(feed);
        const double over = std::min(std::max(clamp(layer.overscanMm, 0.0, 10.0), motion.runUp(double(feed))), 40.0);

        for (int pass = 0; pass < layer.passes; ++pass) {
            if (pass > 0 && layer.zStepMm > 0) {
                out.line("G91");
                out.line("G0 Z" + fmt3(-layer.zStepMm) + " F600");
                out.line("G90");
            }
            if (layer.passes > 1) out.line("; Durchgang " + QByteArray::number(pass + 1) + "/" + QByteArray::number(layer.passes));

            for (const RasterText& r : rasters) {
                if (!r.any) continue;
                const bool withG0 = !gw.hasAt || hypotJ(r.startX - gw.atX, r.startY - gw.atY) > 1e-6;
                bool first = true;
                for (const Buf& part : r.parts) {
                    if (part.size() == 0) continue;
                    const size_t skip = first && !withG0 ? r.firstG0Len : 0;
                    out.append(part.data() + skip, part.size() - skip);
                    first = false;
                }
                gw.hasAt = true;
                gw.atX = r.endX;
                gw.atY = r.endY;
            }

            if (layer.mode == LayerMode::Line) {
                const std::vector<PathOrder> order = orderForCuttingIndexed(vector, gw.hasAt ? Pt{gw.atX, gw.atY} : Pt{0, 0});
                for (const PathOrder& o : order) {
                    const PolyView path = vector[o.index];
                    if (o.reversed) {
                        const size_t n = path.size();
                        gw.rapid(path[n - 1].x, path[n - 1].y);
                        for (size_t i = n - 1; i-- > 0;) gw.burn(path[i].x, path[i].y, power, feedText);
                    } else {
                        gw.rapid(path[0].x, path[0].y);
                        for (size_t i = 1; i < path.size(); ++i) gw.burn(path[i].x, path[i].y, power, feedText);
                    }
                }
            } else {
                for (PolyView seg : hatched) {
                    const double y = seg.front().y, x0 = seg.front().x, x1 = seg.back().x;
                    const double dir = x1 >= x0 ? 1.0 : -1.0;
                    const double start = clamp(x0 - dir * over, 0.0, W), end = clamp(x1 + dir * over, 0.0, W);
                    gw.rapid(start, y);
                    if (start != x0) gw.burn(x0, y, 0, feedText);
                    if (std::fabs(gw.atX - x0) > 1e-6) gw.burn(x0, y, 0, feedText);
                    gw.burn(x1, y, power, feedText);
                    if (end != gw.atX) gw.burn(end, y, 0, feedText);
                }
            }
        }
        if (layer.zStepMm > 0 && layer.focusDropMm() > 0) {
            out.line("G91");
            out.line("G0 Z" + fmt3(layer.focusDropMm()) + " F600");
            out.line("G90");
        }
    }
    out.line("M5 I");
    out.line("M400");
    return QByteArray(out.data(), qsizetype(out.size()));
}

}  // namespace lumacut
