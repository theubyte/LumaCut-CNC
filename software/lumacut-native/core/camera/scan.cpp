#include "core/camera/scan.h"
#include "core/parallel.h"
#include <QJsonArray>
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace lumacut::Camera {

namespace {
Pt operator+(Pt a, Pt b) { return {a.x + b.x, a.y + b.y}; }
Pt operator-(Pt a, Pt b) { return {a.x - b.x, a.y - b.y}; }

bool pointInOutline(Pt p, const std::vector<Pt>& poly) {
    bool c = false;
    for (size_t i = 0, j = poly.size() - 1; i < poly.size(); j = i++) {
        const Pt a = poly[i], b = poly[j];
        if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) c = !c;
    }
    return c;
}
int luminance(uint32_t c) { return int((((c >> 16) & 255) * 299 + ((c >> 8) & 255) * 587 + (c & 255) * 114) / 1000); }

/** Bilinear in all four channels; x0 + 1 and y0 + 1 must lie in the picture. */
uint32_t sample(const uint32_t* px, int w, int x0, int y0, double fx, double fy) {
    const uint32_t c00 = px[size_t(y0) * size_t(w) + size_t(x0)], c10 = px[size_t(y0) * size_t(w) + size_t(x0) + 1];
    const uint32_t c01 = px[size_t(y0 + 1) * size_t(w) + size_t(x0)], c11 = px[size_t(y0 + 1) * size_t(w) + size_t(x0) + 1];
    uint32_t r = 0;
    for (const int shift : {24, 16, 8, 0}) {
        const auto ch = [shift](uint32_t c) { return double((c >> shift) & 0xFF); };
        const double top = ch(c00) + (ch(c10) - ch(c00)) * fx, bottom = ch(c01) + (ch(c11) - ch(c01)) * fx;
        r |= uint32_t(std::clamp(int(top + (bottom - top) * fy), 0, 255)) << shift;
    }
    return r;
}

std::optional<std::vector<double>> solve(std::vector<std::vector<double>> m, std::vector<double> b) {
    const size_t n = b.size();
    for (size_t col = 0; col < n; ++col) {
        size_t p = col;
        for (size_t r = col + 1; r < n; ++r) if (std::abs(m[r][col]) > std::abs(m[p][col])) p = r;
        if (std::abs(m[p][col]) < 1e-14) return std::nullopt;
        std::swap(m[p], m[col]);
        std::swap(b[p], b[col]);
        for (size_t r = 0; r < n; ++r) {
            if (r == col) continue;
            const double k = m[r][col] / m[col][col];
            if (k == 0) continue;
            for (size_t c = col; c < n; ++c) m[r][c] -= k * m[col][c];
            b[r] -= k * b[col];
        }
    }
    std::vector<double> x(n);
    for (size_t i = 0; i < n; ++i) x[i] = b[i] / m[i][i];
    return x;
}
}  // namespace

Pt apply(const Mat3& m, Pt p) {
    const double w = m[6] * p.x + m[7] * p.y + m[8];
    if (std::abs(w) < 1e-15) return {NAN, NAN};
    return {(m[0] * p.x + m[1] * p.y + m[2]) / w, (m[3] * p.x + m[4] * p.y + m[5]) / w};
}
std::optional<Mat3> inverse(const Mat3& m) {
    const double a = m[0], b = m[1], c = m[2], d = m[3], e = m[4], f = m[5], g = m[6], h = m[7], i = m[8];
    const double det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if (std::abs(det) < 1e-18) return std::nullopt;
    return Mat3{(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det, (f * g - d * i) / det, (a * i - c * g) / det,
                (c * d - a * f) / det, (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det};
}
std::optional<Mat3> homography(const std::vector<Pt>& src, const std::vector<Pt>& dst) {
    if (src.size() != 4 || dst.size() != 4) return std::nullopt;
    std::vector<std::vector<double>> a(8, std::vector<double>(8));
    std::vector<double> b(8);
    for (size_t i = 0; i < 4; ++i) {
        const double x = src[i].x, y = src[i].y, u = dst[i].x, v = dst[i].y;
        a[2 * i] = {x, y, 1, 0, 0, 0, -u * x, -u * y};
        b[2 * i] = u;
        a[2 * i + 1] = {0, 0, 0, x, y, 1, -v * x, -v * y};
        b[2 * i + 1] = v;
    }
    const auto h = solve(a, b);
    if (!h) return std::nullopt;
    return Mat3{(*h)[0], (*h)[1], (*h)[2], (*h)[3], (*h)[4], (*h)[5], (*h)[6], (*h)[7], 1};
}

// ---- Lens and shading ----

Pt Lens::toPixel(Pt rel) const {
    const Pt u = apply(g, rel);
    const double r2 = u.x * u.x + u.y * u.y, d = 1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2;
    return {cx + f * u.x * d, cy + f * u.y * d};
}
double Lens::undistortRadius(double rd) const {
    double r = rd;
    for (int it = 0; it < 30; ++it) {
        const double r2 = r * r;
        const double fr = r * (1 + k1 * r2 + k2 * r2 * r2 + k3 * r2 * r2 * r2) - rd;
        const double d = 1 + 3 * k1 * r2 + 5 * k2 * r2 * r2 + 7 * k3 * r2 * r2 * r2;
        if (std::abs(d) < 1e-9) return r;
        const double next = r - fr / d;
        if (std::abs(next - r) < 1e-13) return next;
        r = next;
    }
    return r;
}
Pt Lens::toRel(Pt p) const {
    const double qx = (p.x - cx) / f, qy = (p.y - cy) / f, rd = std::hypot(qx, qy);
    const double s = rd < 1e-12 ? 1.0 : undistortRadius(rd) / rd;
    const auto inv = inverse(g);
    return inv ? apply(*inv, {qx * s, qy * s}) : Pt{NAN, NAN};
}

double Shading::at(double u, double v, int ch) const {
    const double x = std::clamp(u * (cols - 1), 0.0, cols - 1.0), y = std::clamp(v * (rows - 1), 0.0, rows - 1.0);
    const int x0 = std::min(int(x), cols - 2), y0 = std::min(int(y), rows - 2);
    const double fx = x - x0, fy = y - y0;
    const auto gv = [&](int i, int j) { return double(gain[size_t((j * cols + i) * 3 + ch)]); };
    const double top = gv(x0, y0) + (gv(x0 + 1, y0) - gv(x0, y0)) * fx, bottom = gv(x0, y0 + 1) + (gv(x0 + 1, y0 + 1) - gv(x0, y0 + 1)) * fx;
    return top + (bottom - top) * fy;
}
uint32_t Shading::correct(uint32_t c, double u, double v) const {
    const auto ch = [&](int shift, int k) { return uint32_t(std::clamp(int(std::lround(((c >> shift) & 255) * at(u, v, k))), 0, 255)) << shift; };
    return (c & 0xFF000000u) | ch(16, 0) | ch(8, 1) | ch(0, 2);
}

// ---- Calibration ----

namespace {
Pt ptOf(const QJsonValue& v) { const QJsonObject o = v.toObject(); return {o.value("x").toDouble(NAN), o.value("y").toDouble(NAN)}; }
std::vector<Pt> ptsOf(const QJsonValue& v) {
    std::vector<Pt> out;
    for (const QJsonValue& p : v.toArray()) out.push_back(ptOf(p));
    return out;
}
bool finitePt(Pt p) { return std::isfinite(p.x) && std::isfinite(p.y); }
}  // namespace

std::optional<Calibration> Calibration::fromJson(const QJsonObject& a, QString* why) {
    const auto fail = [&](const char* text) { if (why) *why = QString::fromUtf8(text); return std::optional<Calibration>(); };
    if (a.isEmpty()) return fail("Die Kopfkamera ist noch nicht kalibriert.");
    Calibration c;
    c.photoWidth = a.value("photoWidth").toInt();
    c.photoHeight = a.value("photoHeight").toInt();
    if (c.photoWidth < 160 || c.photoHeight < 120) return fail("Kamera-Kalibrierung ohne gültige Bildgröße.");
    c.scanZ = a.value("scanZ").toDouble(20);
    if (a.value("aboveSurface").isDouble()) c.aboveSurface = a.value("aboveSurface").toDouble();
    const QJsonObject lens = a.value("lens").toObject();
    if (!lens.isEmpty()) {
        Lens l;
        l.cx = lens.value("cx").toDouble(); l.cy = lens.value("cy").toDouble(); l.f = lens.value("f").toDouble();
        l.k1 = lens.value("k1").toDouble(); l.k2 = lens.value("k2").toDouble(); l.k3 = lens.value("k3").toDouble();
        const QJsonArray g = lens.value("g").toArray();
        if (g.size() != 9 || !(l.f > 0)) return fail("Linsenmodell der Kamera ist unvollständig.");
        for (int i = 0; i < 9; ++i) l.g[size_t(i)] = g[i].toDouble();
        const QJsonObject v = lens.value("valid").toObject();
        l.valid = {v.value("minX").toDouble(), v.value("minY").toDouble(), v.value("maxX").toDouble(c.photoWidth), v.value("maxY").toDouble(c.photoHeight)};
        if (!inverse(l.g)) return fail("Linsenmodell der Kamera ist nicht umkehrbar.");
        c.lens = l;
    } else {
        c.photo = ptsOf(a.value("photo"));
        c.relMm = ptsOf(a.value("relMm"));
        if (c.photo.size() != 4 || c.relMm.size() != 4 || !std::all_of(c.photo.begin(), c.photo.end(), finitePt) || !std::all_of(c.relMm.begin(), c.relMm.end(), finitePt))
            return fail("Kamera-Kalibrierung braucht ein Linsenmodell oder vier Marken.");
    }
    const QJsonObject sh = a.value("shading").toObject();
    if (!sh.isEmpty()) {
        Shading s;
        s.cols = sh.value("cols").toInt(); s.rows = sh.value("rows").toInt();
        for (const QJsonValue& v : sh.value("gain").toArray()) s.gain.push_back(float(v.toDouble()));
        if (s.cols >= 2 && s.rows >= 2 && s.gain.size() == size_t(s.cols * s.rows * 3)) c.shading = std::move(s);
    }
    c.prepare();
    if (!c.lens && (!homography(c.photo, c.relMm) || !homography(c.relMm, c.photo))) return fail("Kamera-Kalibrierung ist unplausibel.");
    if (!(c.footprint().width() >= 1 && c.footprint().height() >= 1)) return fail("Kamera-Kalibrierung ist unplausibel.");
    return c;
}
Calibration Calibration::fromMarks(int w, int h, std::vector<Pt> photo, std::vector<Pt> relMm, double scanZ) {
    Calibration c;
    c.photoWidth = w; c.photoHeight = h; c.scanZ = scanZ;
    c.photo = std::move(photo);
    c.relMm = std::move(relMm);
    c.prepare();
    return c;
}
void Calibration::prepare() {
    if (!lens) {
        if (const auto h = homography(photo, relMm)) m_toRel = *h;
        if (const auto h = homography(relMm, photo)) m_toPhoto = *h;
    }
    const Box v = validPx();
    const int n = lens ? 24 : 1;
    const Pt corners[4] = {{v.minX, v.minY}, {v.maxX, v.minY}, {v.maxX, v.maxY}, {v.minX, v.maxY}};
    m_outline.clear();
    for (int e = 0; e < 4; ++e) {
        const Pt a = corners[e], b = corners[(e + 1) % 4];
        for (int k = 0; k < n; ++k) m_outline.push_back(pixelToWork({a.x + (b.x - a.x) * k / n, a.y + (b.y - a.y) * k / n}, {0, 0}));
    }
}
Box Calibration::validPx() const { return lens ? lens->valid : Box{0, 0, double(photoWidth), double(photoHeight)}; }
Pt Calibration::pixelToWork(Pt p, Pt head) const { return (lens ? lens->toRel(p) : apply(m_toRel, p)) + head; }
Pt Calibration::workToPixel(Pt w, Pt head) const { return lens ? lens->toPixel(w - head) : apply(m_toPhoto, w - head); }
Box Calibration::footprint() const {
    Box b{1e300, 1e300, -1e300, -1e300};
    for (const Pt& p : m_outline) b = {std::min(b.minX, p.x), std::min(b.minY, p.y), std::max(b.maxX, p.x), std::max(b.maxY, p.y)};
    return b;
}
Box Calibration::usable(double inset) const {
    Box f = footprint();
    if (lens) {
        const Pt c = pixelToWork(validPx().center(), {0, 0});
        const double hx = f.width() / 2, hy = f.height() / 2;
        Box found{c.x - 1, c.y - 1, c.x + 1, c.y + 1};
        for (double t = 1.0; t > 0.05; t *= 0.98) {
            const Box b{c.x - hx * t, c.y - hy * t, c.x + hx * t, c.y + hy * t};
            if (pointInOutline({b.minX, b.minY}, m_outline) && pointInOutline({b.maxX, b.minY}, m_outline) && pointInOutline({b.maxX, b.maxY}, m_outline)
                && pointInOutline({b.minX, b.maxY}, m_outline)) { found = b; break; }
        }
        f = found;
    }
    const double dx = f.width() * inset, dy = f.height() * inset;
    return {f.minX + dx, f.minY + dy, f.maxX - dx, f.maxY - dy};
}

// ---- Plan ----

TilePlan plan(const Calibration& cal, Box area, double overlap) {
    const double W = Work::width(), H = Work::height();
    const Box a{std::clamp(area.minX, 0.0, W), std::clamp(area.minY, 0.0, H), std::clamp(area.maxX, 0.0, W), std::clamp(area.maxY, 0.0, H)};
    if (!(a.width() > 0.5 && a.height() > 0.5)) throw std::invalid_argument("Scanbereich liegt nicht in der Arbeitsfläche");
    const Box u = cal.usable();
    const double ov = std::clamp(overlap, 0.0, 0.5), stepX = u.width() * (1 - ov), stepY = u.height() * (1 - ov);
    if (!(stepX > 1 && stepY > 1)) throw std::invalid_argument("Kamera-Kalibrierung unplausibel (Bildausschnitt zu klein)");
    const int cols = std::max(1, int(std::ceil((a.width() - u.width()) / stepX)) + 1);
    const int rows = std::max(1, int(std::ceil((a.height() - u.height()) / stepY)) + 1);
    // Head travel in work mm: machine 0..travel, X reversed. The laser is off, the park corner may be crossed.
    const double minHx = Work::fromMachine({Bed::width(), 0}).x, maxHx = Work::fromMachine({0, 0}).x;
    const double minHy = 0, maxHy = Bed::height();
    TilePlan out;
    for (int r = 0; r < rows; ++r) {
        const double ty = rows == 1 ? a.center().y - u.height() / 2 : a.minY + (a.height() - u.height()) * r / (rows - 1);
        for (int k = 0; k < cols; ++k) {
            const int c = r % 2 == 0 ? k : cols - 1 - k;
            const double tx = cols == 1 ? a.center().x - u.width() / 2 : a.minX + (a.width() - u.width()) * c / (cols - 1);
            out.heads.push_back({std::clamp(tx - u.minX, minHx, maxHx), std::clamp(ty - u.minY, minHy, maxHy)});
        }
    }
    Box cover{1e300, 1e300, -1e300, -1e300};
    for (const Pt& h : out.heads) cover = {std::min(cover.minX, h.x + u.minX), std::min(cover.minY, h.y + u.minY), std::max(cover.maxX, h.x + u.maxX), std::max(cover.maxY, h.y + u.maxY)};
    const auto mm = [](double v) { return QString::number(std::lround(v)); };
    if (cover.minX > a.minX + 0.5) out.uncovered << QStringLiteral("linker Rand (%1 mm)").arg(mm(cover.minX - a.minX));
    if (cover.minY > a.minY + 0.5) out.uncovered << QStringLiteral("oberer Rand (%1 mm)").arg(mm(cover.minY - a.minY));
    if (cover.maxX < a.maxX - 0.5) out.uncovered << QStringLiteral("rechter Rand (%1 mm)").arg(mm(a.maxX - cover.maxX));
    if (cover.maxY < a.maxY - 0.5) out.uncovered << QStringLiteral("unterer Rand (%1 mm)").arg(mm(a.maxY - cover.maxY));
    return out;
}

// ---- Mosaic ----

Mosaic::Mosaic(const Calibration& cal, double pxPerMm, const std::vector<uint32_t>* base)
    : m_cal(cal), m_ppm(pxPerMm), m_w(int(Work::width() * pxPerMm)), m_h(int(Work::height() * pxPerMm)) {
    if (base && base->size() == size_t(m_w) * size_t(m_h)) m_px = *base;
    else m_px.assign(size_t(m_w) * size_t(m_h), 0);
    m_weight.assign(m_px.size(), 0.f);
}

void Mosaic::add(const uint32_t* argb, int tw, int th, Pt head) {
    const Box reach = m_cal.footprint(), valid = m_cal.validPx();
    const int i0 = std::max(0, int(std::floor((head.x + reach.minX) * m_ppm))), i1 = std::min(m_w - 1, int(std::ceil((head.x + reach.maxX) * m_ppm)));
    const int j0 = std::max(0, int(std::floor((head.y + reach.minY) * m_ppm))), j1 = std::min(m_h - 1, int(std::ceil((head.y + reach.maxY) * m_ppm)));
    const double minX = std::max(0.0, valid.minX), minY = std::max(0.0, valid.minY);
    const double maxX = std::min(tw - 1.0, valid.maxX - 1), maxY = std::min(th - 1.0, valid.maxY - 1);
    const double halfW = (maxX - minX) / 2, halfH = (maxY - minY) / 2;
    if (halfW <= 0 || halfH <= 0 || i1 < i0 || j1 < j0) return;
    const int cw = i1 - i0 + 1, chh = j1 - j0 + 1;
    const size_t cap = size_t(cw) * size_t(chh);
    // 1. project, on all cores: corrected colour and edge weight for every mosaic pixel the photo shows (weight 0 = not)
    std::vector<uint32_t> col(cap);
    std::vector<float> wt(cap, 0.f);
    parallelBlocks(chh, 8, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t jj = a; jj < b; ++jj) {
            const int j = j0 + int(jj);
            const double wy = (j + 0.5) / m_ppm;
            for (int i = i0; i <= i1; ++i) {
                const Pt p = m_cal.workToPixel({(i + 0.5) / m_ppm, wy}, head);
                const double x = p.x - 0.5, y = p.y - 0.5;
                if (!(x >= minX && y >= minY && x < maxX && y < maxY)) continue;
                const int x0 = int(std::floor(x)), y0 = int(std::floor(y));
                uint32_t c = sample(argb, tw, x0, y0, x - x0, y - y0);
                if (m_cal.shading) c = m_cal.shading->correct(c, p.x / tw, p.y / th);
                const double e = std::clamp(std::min(std::min(x - minX, maxX - x) / halfW, std::min(y - minY, maxY - y) / halfH), 0.0, 1.0);
                const size_t q = size_t(jj) * size_t(cw) + size_t(i - i0);
                col[q] = c;
                wt[q] = float(e * e + 1e-4);
            }
        }
    });
    // 2. gain per channel from the overlap with what is already there (clipped and dark pixels left out)
    double sumTile[3] = {0, 0, 0}, sumMosaic[3] = {0, 0, 0};
    int shared = 0;
    for (size_t q = 0; q < cap; ++q) {
        if (wt[q] < 0.05f) continue;
        const size_t k = size_t(j0 + int(q / size_t(cw))) * size_t(m_w) + size_t(i0 + int(q % size_t(cw)));
        if (m_weight[k] < 0.05f) continue;
        const uint32_t a = col[q], b = m_px[k];
        const int la = luminance(a), lb = luminance(b);
        if (la < 15 || la > 240 || lb < 15 || lb > 240) continue;
        for (int ch = 0; ch < 3; ++ch) { const int sh = 16 - 8 * ch; sumTile[ch] += (a >> sh) & 255; sumMosaic[ch] += (b >> sh) & 255; }
        ++shared;
    }
    for (int ch = 0; ch < 3; ++ch) m_gain[size_t(ch)] = shared < 200 || sumTile[ch] <= 0 ? 1.0 : std::clamp(sumMosaic[ch] / sumTile[ch], 0.7, 1.4);
    // 3. blend: running weighted mean, so a pixel ends up as the weighted mean of all photos showing it
    parallelBlocks(chh, 8, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t jj = a; jj < b; ++jj) {
            for (int ii = 0; ii < cw; ++ii) {
                const size_t q = size_t(jj) * size_t(cw) + size_t(ii);
                const float w = wt[q];
                if (w <= 0.f) continue;
                const size_t k = size_t(j0 + int(jj)) * size_t(m_w) + size_t(i0 + ii);
                const float total = m_weight[k] + w;
                const double f = w / total;
                const uint32_t c = col[q], old = m_px[k];
                uint32_t out = 0xFF000000u;
                for (int ch = 0; ch < 3; ++ch) {
                    const int sh = 16 - 8 * ch;
                    const double v = ((c >> sh) & 255) * m_gain[size_t(ch)], o = (old >> sh) & 255;
                    const double blended = m_weight[k] == 0.f ? v : o + (v - o) * f;
                    out |= uint32_t(std::clamp(int(blended + 0.5), 0, 255)) << sh;
                }
                m_px[k] = out;
                m_weight[k] = total;
            }
        }
    });
}

double mosaicResolution(const Calibration& cal) {
    const double native = cal.photoWidth / std::max(1.0, cal.footprint().width());
    return std::clamp(native * 0.8, 2.0, 5.0);
}

std::vector<uint32_t> level(const std::vector<uint32_t>& argb, int w, int h, double pxPerMm, double cellMm) {
    if (argb.size() != size_t(w) * size_t(h)) throw std::invalid_argument("Ungültige Bilddaten");
    const int c = std::max(8, int(std::lround(cellMm * pxPerMm)));
    const int gw = (w + c - 1) / c, gh = (h + c - 1) / c;
    std::vector<uint32_t> out = argb;
    std::vector<double> bgs[3];
    double targets[3] = {0, 0, 0};
    for (int ch = 0; ch < 3; ++ch) {
        const int sh = 16 - 8 * ch;
        std::vector<double> cell(size_t(gw * gh), NAN);
        parallelFor(gh, [&](std::ptrdiff_t gj) {
            int hist[256];
            for (int gi = 0; gi < gw; ++gi) {
                std::fill(std::begin(hist), std::end(hist), 0);
                int n = 0;
                for (int y = int(gj) * c; y < std::min(h, int(gj + 1) * c); ++y)
                    for (int x = gi * c; x < std::min(w, (gi + 1) * c); ++x) {
                        const uint32_t v = argb[size_t(y) * size_t(w) + size_t(x)];
                        if ((v >> 24) == 0) continue;
                        ++hist[(v >> sh) & 255];
                        ++n;
                    }
                if (n < c * c / 4) continue;
                int acc = 0, k = 0;
                while (k < 255) { acc += hist[k]; if (acc >= n * 0.7) break; ++k; }
                cell[size_t(gj) * size_t(gw) + size_t(gi)] = k;
            }
        });
        std::vector<double> validCells;
        for (double v : cell) if (!std::isnan(v)) validCells.push_back(v);
        if (validCells.empty()) return out;
        std::sort(validCells.begin(), validCells.end());
        targets[ch] = validCells[std::min(validCells.size() - 1, size_t(validCells.size() * 0.9))];
        for (int rep = 0; rep < gw + gh; ++rep) {
            if (std::none_of(cell.begin(), cell.end(), [](double v) { return std::isnan(v); })) break;
            const std::vector<double> prev = cell;
            for (int j = 0; j < gh; ++j)
                for (int i = 0; i < gw; ++i) {
                    if (!std::isnan(prev[size_t(j * gw + i)])) continue;
                    double sum = 0;
                    int cnt = 0;
                    const int nb[4][2] = {{i - 1, j}, {i + 1, j}, {i, j - 1}, {i, j + 1}};
                    for (const auto& q : nb)
                        if (q[0] >= 0 && q[0] < gw && q[1] >= 0 && q[1] < gh && !std::isnan(prev[size_t(q[1] * gw + q[0])])) { sum += prev[size_t(q[1] * gw + q[0])]; ++cnt; }
                    if (cnt) cell[size_t(j * gw + i)] = sum / cnt;
                }
        }
        const auto around = [&](const std::vector<double>& src, int i, int j) {
            std::vector<double> v;
            for (int dy = -1; dy <= 1; ++dy)
                for (int dx = -1; dx <= 1; ++dx) {
                    const int x = i + dx, y = j + dy;
                    if (x >= 0 && x < gw && y >= 0 && y < gh) v.push_back(src[size_t(y * gw + x)]);
                }
            return v;
        };
        std::vector<double> med(cell.size()), bg(cell.size());
        for (size_t k = 0; k < cell.size(); ++k) {
            auto a = around(cell, int(k % size_t(gw)), int(k / size_t(gw)));
            if (a.size() < 9) med[k] = cell[k];
            else { std::sort(a.begin(), a.end()); med[k] = a[4]; }
        }
        for (size_t k = 0; k < cell.size(); ++k) {
            const auto a = around(med, int(k % size_t(gw)), int(k / size_t(gw)));
            if (a.size() < 9) bg[k] = med[k];
            else { double s = 0; for (double v : a) s += v; bg[k] = s / double(a.size()); }
        }
        bgs[ch] = std::move(bg);
    }
    parallelFor(h, [&](std::ptrdiff_t yy) {
        const int y = int(yy);
        const double fy = std::clamp((y + 0.5) / c - 0.5, 0.0, gh - 1.0);
        const int j0 = std::min(int(fy), std::max(0, gh - 2)), j1 = std::min(j0 + 1, gh - 1);
        const double ty = gh > 1 ? fy - j0 : 0.0;
        for (int x = 0; x < w; ++x) {
            const uint32_t v = argb[size_t(y) * size_t(w) + size_t(x)];
            if ((v >> 24) == 0) continue;
            const double fx = std::clamp((x + 0.5) / c - 0.5, 0.0, gw - 1.0);
            const int i0 = std::min(int(fx), std::max(0, gw - 2)), i1 = std::min(i0 + 1, gw - 1);
            const double tx = gw > 1 ? fx - i0 : 0.0;
            uint32_t o = v & 0xFF000000u;
            for (int ch = 0; ch < 3; ++ch) {
                const auto& bg = bgs[ch];
                const int sh = 16 - 8 * ch;
                const double top = bg[size_t(j0 * gw + i0)] + (bg[size_t(j0 * gw + i1)] - bg[size_t(j0 * gw + i0)]) * tx;
                const double bottom = bg[size_t(j1 * gw + i0)] + (bg[size_t(j1 * gw + i1)] - bg[size_t(j1 * gw + i0)]) * tx;
                const double gain = targets[ch] / std::max(8.0, top + (bottom - top) * ty);
                o |= uint32_t(std::clamp(int(((v >> sh) & 255) * gain + 0.5), 0, 255)) << sh;
            }
            out[size_t(y) * size_t(w) + size_t(x)] = o;
        }
    });
    return out;
}

ScanHeight scanHeight(const Calibration& cal, std::optional<double> surface, double z, double zTop) {
    const auto mm = [](double v) { return QString::number(v, 'f', 1).replace(QLatin1Char('.'), QLatin1Char(',')); };
    ScanHeight h;
    if (surface) {
        const double target = cal.aboveSurface ? *surface + *cal.aboveSurface : cal.scanZ;
        if (target > zTop + 0.01) { h.lock = QStringLiteral("Material zu hoch für die Kamera: Scanhöhe Z %1 liegt über der Höchstgrenze Z %2.").arg(mm(target), mm(zTop)); return h; }
        if (target < *surface + 3) { h.lock = QStringLiteral("Die Kamerahöhe der Kalibrierung liegt zu nah am Material. Kamera neu kalibrieren."); return h; }
        h.z = target;
        h.jog = std::abs(target - z) > 0.05;
        return h;
    }
    if (cal.aboveSurface) {
        h.lock = QStringLiteral("Zuerst abtasten: die Scanhöhe hängt von der Materialoberfläche ab, und ohne gemessene Oberfläche fährt der Pi Z nicht.");
        return h;
    }
    if (std::abs(z - cal.scanZ) > 1.0) {
        h.lock = QStringLiteral("Zuerst abtasten: Z steht auf %1, gescannt wird auf Z %2. Ohne gemessene Oberfläche fährt der Pi Z nicht, und flach über dem Bett könnte der Kopf an Objekte stoßen.")
                     .arg(mm(z), mm(cal.scanZ));
        return h;
    }
    h.z = z;   // close enough, and Z cannot move without a surface: stay
    return h;
}
std::vector<double> jogSteps(double delta) {
    long tenths = std::lround(delta * 10);
    std::vector<double> out;
    for (const long unit : {100L, 10L, 1L})
        while (std::labs(tenths) >= unit) {
            const long s = tenths > 0 ? unit : -unit;
            out.push_back(double(s) / 10.0);
            tenths -= s;
        }
    return out;
}

Rectified rectify(const Calibration& cal, const uint32_t* argb, int w, int h, Pt head, double ppm) {
    Rectified r;
    const Box u = cal.usable(0.0);
    r.area = {head.x + u.minX, head.y + u.minY, head.x + u.maxX, head.y + u.maxY};
    r.width = std::max(1, int(std::ceil(r.area.width() * ppm)));
    r.height = std::max(1, int(std::ceil(r.area.height() * ppm)));
    r.argb.assign(size_t(r.width) * size_t(r.height), 0);
    const Box valid = cal.validPx();
    const double minX = std::max(0.0, valid.minX), minY = std::max(0.0, valid.minY);
    const double maxX = std::min(w - 1.0, valid.maxX - 1), maxY = std::min(h - 1.0, valid.maxY - 1);
    // The photo may come in another size than the calibration's: scale pixel positions.
    const double sx = double(w) / cal.photoWidth, sy = double(h) / cal.photoHeight;
    parallelBlocks(r.height, 8, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t j = a; j < b; ++j)
            for (int i = 0; i < r.width; ++i) {
                const Pt p = cal.workToPixel({r.area.minX + (i + 0.5) / ppm, r.area.minY + (double(j) + 0.5) / ppm}, head);
                const double x = p.x * sx - 0.5, y = p.y * sy - 0.5;
                if (!(x >= minX * sx && y >= minY * sy && x < maxX * sx && y < maxY * sy && x < w - 1 && y < h - 1)) continue;
                const int x0 = int(std::floor(x)), y0 = int(std::floor(y));
                r.argb[size_t(j) * size_t(r.width) + size_t(i)] = sample(argb, w, x0, y0, x - x0, y - y0) | 0xFF000000u;
            }
    });
    return r;
}

}  // namespace lumacut::Camera
