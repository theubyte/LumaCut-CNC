#include "core/contour.h"
#include "core/geometry.h"
#include "core/parallel.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace lumacut {
namespace {

constexpr double kSimplifyMm = 0.05;

struct Flood {
    std::vector<int32_t> queue;
    size_t head = 0, tail = 0;
    explicit Flood(size_t n) : queue(n) {}
};

std::vector<uint8_t> background(std::span<const uint32_t> argb, int w, int h, int tol) {
    const auto A = [](uint32_t c) { return int((c >> 24) & 255); };
    const auto R = [](uint32_t c) { return int((c >> 16) & 255); };
    const auto G = [](uint32_t c) { return int((c >> 8) & 255); };
    const auto B = [](uint32_t c) { return int(c & 255); };
    struct Bin { int key; int count = 0; qint64 r = 0, g = 0, b = 0; };
    std::vector<int> slot(4096, -1);
    std::vector<Bin> bins;
    const auto border = [&](size_t i) {
        const uint32_t c = argb[i];
        if (A(c) < 128) return;
        const int key = ((R(c) >> 4) << 8) | ((G(c) >> 4) << 4) | (B(c) >> 4);
        if (slot[size_t(key)] < 0) { slot[size_t(key)] = int(bins.size()); bins.push_back({key}); }
        Bin& e = bins[size_t(slot[size_t(key)])];
        e.count++; e.r += R(c); e.g += G(c); e.b += B(c);
    };
    for (int x = 0; x < w; ++x) { border(size_t(x)); border(size_t(h - 1) * w + x); }
    for (int y = 1; y < h - 1; ++y) { border(size_t(y) * w); border(size_t(y) * w + w - 1); }
    // Gleichstand wie bei Javas HashMap: Reihenfolge nach Bucket, dann nach Einfügen.
    size_t table = 16;
    while (double(bins.size()) > double(table) * 0.75) table *= 2;
    std::stable_sort(bins.begin(), bins.end(), [&](const Bin& p, const Bin& q) { return (size_t(p.key) & (table - 1)) < (size_t(q.key) & (table - 1)); });
    const Bin* top = nullptr;
    for (const Bin& v : bins) if (!top || v.count > top->count) top = &v;
    const int rr = top ? int(top->r / top->count) : -1, rg = top ? int(top->g / top->count) : -1, rb = top ? int(top->b / top->count) : -1;
    const auto similar = [&](uint32_t c) {
        if (A(c) < 128) return true;
        if (!top) return false;
        return std::abs(R(c) - rr) <= tol && std::abs(G(c) - rg) <= tol && std::abs(B(c) - rb) <= tol;
    };
    std::vector<uint8_t> bg(size_t(w) * h, 0);
    Flood f(size_t(w) * h);
    const auto push = [&](size_t i) { if (!bg[i] && similar(argb[i])) { bg[i] = 1; f.queue[f.tail++] = int32_t(i); } };
    for (int x = 0; x < w; ++x) { push(size_t(x)); push(size_t(h - 1) * w + x); }
    for (int y = 0; y < h; ++y) { push(size_t(y) * w); push(size_t(y) * w + w - 1); }
    while (f.head < f.tail) {
        const size_t i = size_t(f.queue[f.head++]);
        const int x = int(i % size_t(w)), y = int(i / size_t(w));
        if (x > 0) push(i - 1);
        if (x < w - 1) push(i + 1);
        if (y > 0) push(i - w);
        if (y < h - 1) push(i + w);
    }
    return bg;
}

/** Euklidischer Abstand zum nächsten gesetzten Pixel (Felzenszwalb-Huttenlocher), Spalten und Zeilen mehrkernig. */
std::vector<float> edt(const std::vector<uint8_t>& feature, int w, int h) {
    constexpr double inf = 1e10, far_ = 1e20;
    std::vector<double> sq(feature.size());
    for (size_t i = 0; i < sq.size(); ++i) sq[i] = feature[i] ? 0 : inf;
    const int n = std::max(w, h);
    struct Work_ {
        std::vector<double> f, d, z;
        std::vector<int> v;
        explicit Work_(int n) : f(size_t(n)), d(size_t(n)), z(size_t(n) + 1), v(size_t(n)) {}
        void line(int len) {
            int k = 0;
            v[0] = 0; z[0] = -far_; z[1] = far_;
            for (int q = 1; q < len; ++q) {
                double s = ((f[size_t(q)] + double(q) * q) - (f[size_t(v[size_t(k)])] + double(v[size_t(k)]) * v[size_t(k)])) / (2.0 * q - 2.0 * v[size_t(k)]);
                while (s <= z[size_t(k)]) {
                    --k;
                    s = ((f[size_t(q)] + double(q) * q) - (f[size_t(v[size_t(k)])] + double(v[size_t(k)]) * v[size_t(k)])) / (2.0 * q - 2.0 * v[size_t(k)]);
                }
                ++k;
                v[size_t(k)] = q; z[size_t(k)] = s; z[size_t(k) + 1] = far_;
            }
            k = 0;
            for (int q = 0; q < len; ++q) {
                while (z[size_t(k) + 1] < q) ++k;
                const double dq = q - v[size_t(k)];
                d[size_t(q)] = dq * dq + f[size_t(v[size_t(k)])];
            }
        }
    };
    parallelBlocks(w, 16, [&](std::ptrdiff_t x0, std::ptrdiff_t x1) {
        Work_ t(n);
        for (std::ptrdiff_t x = x0; x < x1; ++x) {
            for (int y = 0; y < h; ++y) t.f[size_t(y)] = sq[size_t(y) * w + size_t(x)];
            t.line(h);
            for (int y = 0; y < h; ++y) sq[size_t(y) * w + size_t(x)] = t.d[size_t(y)];
        }
    });
    parallelBlocks(h, 16, [&](std::ptrdiff_t y0, std::ptrdiff_t y1) {
        Work_ t(n);
        for (std::ptrdiff_t y = y0; y < y1; ++y) {
            double* row = sq.data() + size_t(y) * w;
            std::copy(row, row + w, t.f.begin());
            t.line(w);
            std::copy(t.d.begin(), t.d.begin() + w, row);
        }
    });
    std::vector<float> out(sq.size());
    for (size_t i = 0; i < out.size(); ++i) out[i] = float(std::sqrt(std::min(sq[i], inf)));
    return out;
}

std::vector<float> sdf(const Mask& m, int pad) {
    const int w = m.w + 2 * pad, h = m.h + 2 * pad;
    std::vector<uint8_t> fg(size_t(w) * h, 0), inv(size_t(w) * h);
    for (int y = 0; y < m.h; ++y)
        std::copy_n(m.data.data() + size_t(y) * m.w, m.w, fg.data() + size_t(y + pad) * w + pad);
    for (size_t i = 0; i < inv.size(); ++i) inv[i] = fg[i] ? 0 : 1;
    const std::vector<float> toFg = edt(fg, w, h), toBg = edt(inv, w, h);
    std::vector<float> out(fg.size());
    for (size_t i = 0; i < out.size(); ++i) out[i] = fg[i] ? -toBg[i] : toFg[i];
    return out;
}

/** Marching Squares: geschlossene Schleifen (Rasterkoordinaten), wo das Feld iso kreuzt. */
std::vector<Poly> trace(const std::vector<float>& f, int w, int h, float iso) {
    struct Seg { int64_t from, to; double x, y; };
    std::vector<Seg> segs;
    const auto hk = [&](int x, int y) { return (int64_t(y) * w + x) * 2; };
    const auto vk = [&](int x, int y) { return (int64_t(y) * w + x) * 2 + 1; };
    const auto t = [&](float p, float q) { return (iso - p) / (q - p); };
    for (int j = 0; j < h - 1; ++j) {
        const float* r0 = f.data() + size_t(j) * w;
        const float* r1 = r0 + w;
        for (int i = 0; i < w - 1; ++i) {
            const float a = r0[i], b = r0[i + 1], c = r1[i + 1], d = r1[i];
            const int code = (a < iso ? 1 : 0) | (b < iso ? 2 : 0) | (c < iso ? 4 : 0) | (d < iso ? 8 : 0);
            if (code == 0 || code == 15) continue;
            const auto key = [&](char e) { return e == 'T' ? hk(i, j) : e == 'B' ? hk(i, j + 1) : e == 'L' ? vk(i, j) : vk(i + 1, j); };
            const auto seg = [&](char from, char to) {
                Seg s{key(from), key(to), 0, 0};
                if (from == 'T') { s.x = i + double(t(a, b)); s.y = j; }
                else if (from == 'B') { s.x = i + double(t(d, c)); s.y = j + 1; }
                else if (from == 'L') { s.x = i; s.y = j + double(t(a, d)); }
                else { s.x = i + 1; s.y = j + double(t(b, c)); }
                segs.push_back(s);
            };
            const bool centreInside = (a + b + c + d) / 4 < iso;
            switch (code) {
                case 1: seg('T', 'L'); break;
                case 2: seg('R', 'T'); break;
                case 4: seg('B', 'R'); break;
                case 8: seg('L', 'B'); break;
                case 3: seg('R', 'L'); break;
                case 6: seg('B', 'T'); break;
                case 12: seg('L', 'R'); break;
                case 9: seg('T', 'B'); break;
                case 7: seg('B', 'L'); break;
                case 11: seg('R', 'B'); break;
                case 13: seg('T', 'R'); break;
                case 14: seg('L', 'T'); break;
                case 5: if (centreInside) { seg('T', 'R'); seg('B', 'L'); } else { seg('T', 'L'); seg('B', 'R'); } break;
                case 10: if (centreInside) { seg('L', 'T'); seg('R', 'B'); } else { seg('R', 'T'); seg('L', 'B'); } break;
            }
        }
    }
    // Schlüssel → Segment, das dort beginnt; bei zwei Anfängen zählt das letzte, wie in Kotlins HashMap.
    std::vector<int32_t> byStart((size_t(w) * h + 1) * 2 + 2, -1);
    for (size_t i = 0; i < segs.size(); ++i) byStart[size_t(segs[i].from)] = int32_t(i);
    std::vector<uint8_t> used(segs.size(), 0);
    std::vector<Poly> loops;
    for (size_t first = 0; first < segs.size(); ++first) {
        if (used[first]) continue;
        Poly pts;
        int32_t cur = int32_t(first);
        while (cur >= 0 && !used[size_t(cur)]) {
            used[size_t(cur)] = 1;
            pts.push_back({segs[size_t(cur)].x, segs[size_t(cur)].y});
            cur = byStart[size_t(segs[size_t(cur)].to)];
        }
        if (pts.size() >= 3) {
            pts.push_back(pts.front());
            loops.push_back(std::move(pts));
        }
    }
    return loops;
}

PolySet finish(const std::vector<Poly>& loops, const Mask& base, int padPx, double p, bool outerOnly, double minAreaMm2) {
    std::vector<Poly> out;
    for (const Poly& loop : loops) {
        const size_t n = loop.size() - 1;
        Poly mm(n + 1);
        for (size_t i = 0; i < n; ++i) {
            const Pt a = loop[(i + n - 1) % n], b = loop[i], c = loop[(i + 1) % n];
            mm[i] = {base.x0 + (0.25 * a.x + 0.5 * b.x + 0.25 * c.x - padPx + 0.5) / p,
                     base.y0 + (0.25 * a.y + 0.5 * b.y + 0.25 * c.y - padPx + 0.5) / p};
        }
        mm[n] = mm[0];
        Poly s = simplify(mm, kSimplifyMm);
        if (s.size() >= 4 && std::fabs(polyArea(s)) >= minAreaMm2) {
            if (!(dist(s.front(), s.back()) < 1e-9)) s.push_back(s.front());
            out.push_back(std::move(s));
        }
    }
    PolySet result;
    if (!outerOnly || out.empty()) {
        for (const Poly& q : out) result.add(q);
        return result;
    }
    const Poly* largest = &out[0];
    for (const Poly& q : out) if (std::fabs(polyArea(q)) > std::fabs(polyArea(*largest))) largest = &q;
    const bool sign = polyArea(*largest) > 0;
    for (const Poly& q : out) if ((polyArea(q) > 0) == sign) result.add(q);
    return result;
}

}  // namespace

Mask::Mask(int w_, int h_, std::vector<uint8_t> d, double p, double x, double y) : w(w_), h(h_), data(std::move(d)), pxPerMm(p), x0(x), y0(y) {
    if (qint64(data.size()) != qint64(w) * h) throw std::invalid_argument("Ungültige Maske");
}
Mask Mask::fromArgb(std::span<const uint32_t> argb, int w, int h, double widthMm, double heightMm, double pxPerMm, int tolerance) {
    if (!(w > 0 && h > 0) || qint64(argb.size()) != qint64(w) * h) throw std::invalid_argument("Ungültige Bilddaten");
    const std::vector<uint8_t> bg = background(argb, w, h, tolerance);
    const double p = std::min(pxPerMm, std::min(3000 / widthMm, 3000 / heightMm));
    const int gw = std::max(1, int(std::ceil(widthMm * p))), gh = std::max(1, int(std::ceil(heightMm * p)));
    std::vector<uint8_t> out(size_t(gw) * gh);
    for (int gy = 0; gy < gh; ++gy) {
        const int sy = std::min(h - 1, int((gy + 0.5) / gh * h));
        for (int gx = 0; gx < gw; ++gx) {
            const int sx = std::min(w - 1, int((gx + 0.5) / gw * w));
            out[size_t(gy) * gw + gx] = bg[size_t(sy) * w + sx] ? 0 : 1;
        }
    }
    return Mask(gw, gh, std::move(out), gw / widthMm, 0, 0);
}
Mask Mask::fromRgba(std::span<const uint8_t> rgba, int w, int h, double widthMm, double heightMm, double pxPerMm, int tolerance) {
    if (!(w > 0 && h > 0) || qint64(rgba.size()) != qint64(w) * h * 4) throw std::invalid_argument("Ungültige Bilddaten");
    std::vector<uint32_t> argb(size_t(w) * h);
    for (size_t i = 0; i < argb.size(); ++i) {
        const uint8_t* p = rgba.data() + i * 4;
        argb[i] = (uint32_t(p[3]) << 24) | (uint32_t(p[0]) << 16) | (uint32_t(p[1]) << 8) | p[2];
    }
    return fromArgb(argb, w, h, widthMm, heightMm, pxPerMm, tolerance);
}
int Mask::count() const {
    int n = 0;
    for (const uint8_t v : data) n += v;
    return n;
}
Mask Mask::filled() const {
    std::vector<uint8_t> outside(data.size(), 0);
    Flood f(data.size());
    const auto push = [&](size_t i) { if (!outside[i] && !data[i]) { outside[i] = 1; f.queue[f.tail++] = int32_t(i); } };
    for (int x = 0; x < w; ++x) { push(size_t(x)); push(size_t(h - 1) * w + x); }
    for (int y = 0; y < h; ++y) { push(size_t(y) * w); push(size_t(y) * w + w - 1); }
    while (f.head < f.tail) {
        const size_t i = size_t(f.queue[f.head++]);
        const int x = int(i % size_t(w)), y = int(i / size_t(w));
        if (x > 0) push(i - 1);
        if (x < w - 1) push(i + 1);
        if (y > 0) push(i - w);
        if (y < h - 1) push(i + w);
    }
    std::vector<uint8_t> out(data.size());
    for (size_t i = 0; i < out.size(); ++i) out[i] = outside[i] ? 0 : 1;
    return Mask(w, h, std::move(out), pxPerMm, x0, y0);
}
Mask Mask::withoutSpecks(double minAreaMm2) const {
    const int minPx = int(minAreaMm2 * pxPerMm * pxPerMm);
    if (minPx <= 1) return *this;
    std::vector<uint8_t> seen(data.size(), 0), keep(data.size(), 0);
    std::vector<int32_t> queue(data.size());
    for (size_t start = 0; start < data.size(); ++start) {
        if (!data[start] || seen[start]) continue;
        size_t head = 0, tail = 0;
        queue[tail++] = int32_t(start);
        seen[start] = 1;
        const auto go = [&](size_t j) { if (data[j] && !seen[j]) { seen[j] = 1; queue[tail++] = int32_t(j); } };
        while (head < tail) {
            const size_t i = size_t(queue[head++]);
            const int x = int(i % size_t(w)), y = int(i / size_t(w));
            if (x > 0) go(i - 1);
            if (x < w - 1) go(i + 1);
            if (y > 0) go(i - w);
            if (y < h - 1) go(i + w);
        }
        if (int(tail) >= minPx) for (size_t k = 0; k < tail; ++k) keep[size_t(queue[k])] = 1;
    }
    return Mask(w, h, std::move(keep), pxPerMm, x0, y0);
}

double polyArea(PolyView poly) {
    double s = 0;
    for (size_t i = 1; i < poly.size(); ++i) s += poly[i - 1].x * poly[i].y - poly[i].x * poly[i - 1].y;
    return s / 2;
}

namespace Contour {
PolySet fromMask(const Mask& mask, double offsetMm, double closeGapMm, bool outerOnly, double minAreaMm2) {
    const Mask base = outerOnly ? mask.filled() : mask;
    if (base.count() == 0) return {};
    const double p = base.pxPerMm, gap = std::max(0.0, closeGapMm);
    const int pad = int(std::ceil((std::max(offsetMm, 0.0) + gap) * p)) + 4;
    std::vector<float> field = sdf(base, pad);
    int pw = base.w + 2 * pad, ph = base.h + 2 * pad;
    if (gap > 0) {
        const double limit = (offsetMm + gap) * p;
        std::vector<uint8_t> grown(field.size());
        for (size_t i = 0; i < grown.size(); ++i) grown[i] = double(field[i]) <= limit ? 1 : 0;
        Mask gm(pw, ph, std::move(grown), p);
        if (outerOnly) gm = gm.filled();
        field = sdf(gm, 4);
        pw += 8;
        ph += 8;
        return finish(trace(field, pw, ph, float(-gap * p)), base, pad + 4, p, outerOnly, minAreaMm2);
    }
    return finish(trace(field, pw, ph, float(offsetMm * p)), base, pad, p, outerOnly, minAreaMm2);
}
PolySet fromPolys(const PolySet& polys, double offsetMm, double pxPerMm, bool outerOnly) {
    PolySet closed;
    for (PolyView q : polys) if (q.size() >= 3) closed.add(q);
    const auto box = boundsOf(closed);
    if (!box) return {};
    const double bw = box->width(), bh = box->height();
    const double p = std::min(pxPerMm, 3000 / std::max(std::max(bw, bh), 1.0));
    const double m = 2, x0 = box->minX - m, y0 = box->minY - m;
    const int w = int(std::ceil((bw + 2 * m) * p)) + 1, h = int(std::ceil((bh + 2 * m) * p)) + 1;
    return fromMask(Mask(w, h, rasterize(closed, x0, y0, w, h, p), p, x0, y0), offsetMm, 0, outerOnly, 0);
}
std::vector<uint8_t> rasterize(const PolySet& polys, double x0, double y0, int w, int h, double p) {
    std::vector<std::vector<double>> rows(static_cast<size_t>(h));
    const auto edge = [&](Pt a, Pt b) {
        if (a.y == b.y) return;
        const int ja = std::max(0, int(std::ceil((std::min(a.y, b.y) - y0) * p - 0.5)));
        const int jb = std::min(h - 1, int(std::floor((std::max(a.y, b.y) - y0) * p - 0.5)));
        for (int j = ja; j <= jb; ++j) {
            const double y = y0 + (j + 0.5) / p;
            if ((a.y <= y && b.y > y) || (b.y <= y && a.y > y)) rows[size_t(j)].push_back(a.x + (y - a.y) * (b.x - a.x) / (b.y - a.y));
        }
    };
    for (PolyView poly : polys) {
        if (poly.size() < 3) continue;
        for (size_t e = 1; e < poly.size(); ++e) edge(poly[e - 1], poly[e]);
        if (!isClosed(poly)) edge(poly.back(), poly.front());
    }
    std::vector<uint8_t> data(size_t(w) * h, 0);
    parallelBlocks(h, 16, [&](std::ptrdiff_t j0, std::ptrdiff_t j1) {
        for (std::ptrdiff_t j = j0; j < j1; ++j) {
            std::vector<double>& xs = rows[size_t(j)];
            std::sort(xs.begin(), xs.end());
            for (size_t k = 0; k + 1 < xs.size(); k += 2) {
                const int i0 = std::max(0, int(std::ceil((xs[k] - x0) * p - 0.5)));
                const int i1 = std::min(w - 1, int(std::floor((xs[k + 1] - x0) * p - 0.5)));
                if (i1 >= i0) std::fill_n(data.data() + size_t(j) * w + i0, i1 - i0 + 1, uint8_t(1));
            }
        }
    });
    return data;
}
PolySet sticker(const Mask& mask, double offsetMm, bool join) { return fromMask(mask.withoutSpecks(0.5), offsetMm, join ? 8 : 2, true); }
PolySet edge(const Mask& mask, double insetMm) { return fromMask(mask.withoutSpecks(0.5), -std::max(0.0, insetMm), 0, true); }
}  // namespace Contour

}  // namespace lumacut
