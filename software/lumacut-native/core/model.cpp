#include "core/model.h"
#include "core/image.h"

#include <QUuid>
#include <algorithm>
#include <atomic>
#include <bit>
#include <charconv>
#include <cmath>
#include <cstring>
#include <mutex>

namespace lumacut {

namespace {
constexpr double kDegToRad = 0.017453292519943295;  // Math.toRadians ab Java 9
constexpr double kEps = 1e-6;

inline uint32_t highWord(double d) { return uint32_t(std::bit_cast<uint64_t>(d) >> 32); }
inline double withHigh(uint32_t hi) { return std::bit_cast<double>(uint64_t(hi) << 32); }
}  // namespace

Box Box::united(const Box& o) const {
    return {std::min(minX, o.minX), std::min(minY, o.minY), std::max(maxX, o.maxX), std::max(maxY, o.maxY)};
}

double hypotJ(double x, double y) {
    double a = std::fabs(x), b = std::fabs(y);
    if (b > a) std::swap(a, b);
    if (!(a < HUGE_VAL)) return std::hypot(x, y);
    if (b == 0) return a;
    const uint32_t ha = highWord(a), hb = highWord(b);
    if (int32_t(ha - hb) > 0x3c00000) return a + b;
    if (a > 1e150 || b < 3e-151) return std::hypot(x, y);  // außerhalb jeder Werkstückgröße
    const double w = a - b;
    if (w > b) {
        const double t1 = withHigh(ha), t2 = a - t1;
        return std::sqrt(t1 * t1 - (b * -b - t2 * (a + t1)));
    }
    a = a + a;
    const double y1 = withHigh(hb), y2 = b - y1, t1 = withHigh(ha + 0x00100000), t2 = a - t1;
    return std::sqrt(t1 * y1 - (w * -w - (t1 * y2 + t2 * b)));
}

// ---- PolySet ----

PolySet::PolySet(std::initializer_list<Poly> polys) {
    for (const Poly& p : polys) add(p);
}
PolySet::PolySet(const std::vector<Poly>& polys) {
    size_t n = 0;
    for (const Poly& p : polys) n += p.size();
    reserve(polys.size(), n);
    for (const Poly& p : polys) add(p);
}
void PolySet::clear() {
    m_points.clear();
    m_starts.assign(1, 0);
}
void PolySet::reserve(size_t polys, size_t points) {
    m_starts.reserve(polys + 1);
    m_points.reserve(points);
}
void PolySet::add(PolyView poly) {
    m_points.insert(m_points.end(), poly.begin(), poly.end());
    m_starts.push_back(uint32_t(m_points.size()));
}
void PolySet::append(const PolySet& other) {
    const uint32_t base = uint32_t(m_points.size());
    m_points.insert(m_points.end(), other.m_points.begin(), other.m_points.end());
    m_starts.reserve(m_starts.size() + other.size());
    for (size_t i = 1; i < other.m_starts.size(); ++i) m_starts.push_back(base + other.m_starts[i]);
}
std::span<Pt> PolySet::addUninitialized(size_t n) {
    m_points.resize(m_points.size() + n);
    m_starts.push_back(uint32_t(m_points.size()));
    return {m_points.data() + m_points.size() - n, n};
}
std::vector<Poly> PolySet::toPolys() const {
    std::vector<Poly> out;
    out.reserve(size());
    for (PolyView p : *this) out.emplace_back(p.begin(), p.end());
    return out;
}

std::optional<Box> boundsOf(PolyView poly) {
    if (poly.empty()) return std::nullopt;
    Box b{poly[0].x, poly[0].y, poly[0].x, poly[0].y};
    for (const Pt& p : poly) {
        if (p.x < b.minX) b.minX = p.x;
        if (p.x > b.maxX) b.maxX = p.x;
        if (p.y < b.minY) b.minY = p.y;
        if (p.y > b.maxY) b.maxY = p.y;
    }
    return b;
}
std::optional<Box> boundsOf(const PolySet& polys) { return boundsOf(polys.allPoints()); }

bool isClosed(PolyView p, double eps) { return p.size() > 2 && dist(p.front(), p.back()) < eps; }

double polyLength(PolyView p) {
    double s = 0;
    for (size_t i = 1; i < p.size(); ++i) s += dist(p[i - 1], p[i]);
    return s;
}

bool segmentCrosses(double x0, double y0, double x1, double y1, const Box& b) {
    double t0 = 0, t1 = 1;
    const double dx = x1 - x0, dy = y1 - y0;
    const double ps[4] = {-dx, dx, -dy, dy};
    const double qs[4] = {x0 - b.minX, b.maxX - x0, y0 - b.minY, b.maxY - y0};
    for (int i = 0; i < 4; ++i) {
        const double p = ps[i], q = qs[i];
        if (p == 0.0) {
            if (q <= 0.0) return false;
        } else {
            const double r = q / p;
            if (p < 0) { if (r > t0) t0 = r; } else { if (r < t1) t1 = r; }
            if (t0 >= t1) return false;
        }
    }
    return true;
}

// ---- Transform ----

Pt Transform::apply(Pt p) const {
    const double sx = p.x * scaleX, sy = p.y * scaleY, r = rotation * kDegToRad, c = std::cos(r), s = std::sin(r);
    return {sx * c - sy * s + x, sx * s + sy * c + y};
}
Pt Transform::invert(Pt p) const {
    const double r = rotation * kDegToRad, c = std::cos(r), s = std::sin(r), dx = p.x - x, dy = p.y - y;
    const double sx = dx * c + dy * s, sy = -dx * s + dy * c;
    return {scaleX == 0.0 ? 0.0 : sx / scaleX, scaleY == 0.0 ? 0.0 : sy / scaleY};
}

// ---- Bed, Work ----

namespace {
std::atomic<double> gWidth{370.0}, gHeight{360.0}, gParkX{78.0}, gParkY{35.0};
}
namespace Bed {
double width() { return gWidth.load(std::memory_order_relaxed); }
double height() { return gHeight.load(std::memory_order_relaxed); }
double parkX() { return gParkX.load(std::memory_order_relaxed); }
double parkY() { return gParkY.load(std::memory_order_relaxed); }
void configure(std::optional<double> w, std::optional<double> h, std::optional<double> px, std::optional<double> py) {
    if (w && *w >= 100.0 && *w <= 600.0) gWidth = *w;
    if (h && *h >= 100.0 && *h <= 600.0) gHeight = *h;
    if (px && *px >= 0.0 && *px <= 600.0) gParkX = *px;  // der Pi darf die ganze Breite sperren (op=work_band)
    if (py && *py >= 0.0 && *py <= 200.0) gParkY = *py;
}
bool inPark(double x, double y) { return x < parkX() && y < parkY(); }
bool touchesPark(const Box& b) { return b.minX < parkX() && b.minY < parkY(); }
bool inWorkArea(double x, double y) { return x >= 0.0 && y >= 0.0 && x <= width() && y <= height() && !inPark(x, y); }
bool segmentInPark(double x0, double y0, double x1, double y1) {
    return segmentCrosses(x0, y0, x1, y1, Box{0.0, 0.0, parkX(), parkY()});
}
}  // namespace Bed

namespace Work {
double width() { return Bed::width(); }
double height() { return Bed::height(); }
Pt toMachine(Pt p) { return {Bed::width() - p.x, p.y}; }
Pt fromMachine(Pt p) { return {Bed::width() - p.x, p.y}; }
QString sizeLabel() {
    return QString::fromUtf8(fmtFixed(width(), 0)) + QStringLiteral(" × ") + QString::fromUtf8(fmtFixed(height(), 0)) + QStringLiteral(" mm");
}
Box park() { return {width() - Bed::parkX(), 0.0, width(), Bed::parkY()}; }
bool touchesPark(const Box& b) {
    const Box k = park();
    return b.maxX > k.minX + kEps && b.minY < k.maxY - kEps;
}
bool contains(Pt p) { return p.x >= -kEps && p.y >= -kEps && p.x <= width() + kEps && p.y <= height() + kEps; }
bool contains(const Box& b) { return b.minX >= -kEps && b.minY >= -kEps && b.maxX <= width() + kEps && b.maxY <= height() + kEps; }
bool bandBlocked() { return Bed::parkX() >= width(); }
QString parkName() { return bandBlocked() ? QStringLiteral("gesperrter Streifen") : QStringLiteral("Park-Ecke"); }
double usableHeight() { return bandBlocked() ? height() - Bed::parkY() : height(); }
Pt center() { return {width() / 2, (height() - usableHeight() + height()) / 2}; }
}  // namespace Work

// ---- Layer ----

double Layer::powerShare(double dark) const {
    const double d = dark < 0.0 ? 0.0 : dark > 1.0 ? 1.0 : dark;
    const size_t n = toneCurve.size();
    if (n < 2) return d;
    const double x = d * double(n - 1);
    const size_t i = std::min(size_t(x), n - 2);
    const double v = toneCurve[i] + (toneCurve[i + 1] - toneCurve[i]) * (x - double(i));
    return v < 0.0 ? 0.0 : v > 1.0 ? 1.0 : v;
}
QString Layer::label() const { return name == QLatin1String("Linie") ? QStringLiteral("Markieren") : name; }

// ---- Raster ----

struct Raster::Data {
    int w = 0, h = 0;
    QByteArray b64;
    std::vector<uint8_t> gray;
    std::once_flag grayOnce, b64Once;
};
Raster Raster::fromBase64(int width, int height, QByteArray grayBase64) {
    Raster r;
    r.m_d = std::make_shared<Data>();
    r.m_d->w = width;
    r.m_d->h = height;
    r.m_d->b64 = std::move(grayBase64);
    std::call_once(r.m_d->b64Once, [] {});
    return r;
}
Raster Raster::ofGray(int width, int height, std::vector<uint8_t> gray) {
    if (width <= 0 || height <= 0 || qint64(gray.size()) != qint64(width) * height) throw std::invalid_argument("Ungültige Bilddaten");
    Raster r;
    r.m_d = std::make_shared<Data>();
    r.m_d->w = width;
    r.m_d->h = height;
    r.m_d->gray = std::move(gray);
    std::call_once(r.m_d->grayOnce, [] {});
    return r;
}
int Raster::width() const { return m_d ? m_d->w : 0; }
int Raster::height() const { return m_d ? m_d->h : 0; }
const std::vector<uint8_t>& Raster::gray() const {
    static const std::vector<uint8_t> empty;
    if (!m_d) return empty;
    std::call_once(m_d->grayOnce, [this] { m_d->gray = decodeBase64(m_d->b64); });
    return m_d->gray;
}
QByteArray Raster::grayBase64() const {
    if (!m_d) return {};
    std::call_once(m_d->b64Once, [this] { m_d->b64 = encodeBase64(m_d->gray); });
    return m_d->b64;
}

// ---- Element ----

PolySet Element::worldPaths() const {
    PolySet out = paths;
    const double r = transform.rotation * kDegToRad, c = std::cos(r), s = std::sin(r);
    const double kx = transform.scaleX, ky = transform.scaleY, tx = transform.x, ty = transform.y;
    for (Pt& p : out.allPoints()) {
        const double sx = p.x * kx, sy = p.y * ky;
        p = {sx * c - sy * s + tx, sx * s + sy * c + ty};
    }
    return out;
}
std::vector<Pt> Element::imageCorners() const {
    return {transform.apply({0.0, 0.0}), transform.apply({imageWidthMm, 0.0}), transform.apply({imageWidthMm, imageHeightMm}), transform.apply({0.0, imageHeightMm})};
}
std::optional<Box> Element::worldBounds() const {
    if (isImage()) return boundsOf(PolyView(imageCorners()));
    if (paths.pointCount() == 0) return std::nullopt;
    const PolySet w = worldPaths();
    return boundsOf(w);
}
bool Element::touchesPark() const {
    const auto box = worldBounds();
    if (!box || !Work::touchesPark(*box)) return false;
    if (isImage()) return true;
    const Box park = Work::park();
    const PolySet world = worldPaths();
    for (PolyView poly : world)
        for (size_t i = 1; i < poly.size(); ++i)
            if (segmentCrosses(poly[i - 1].x, poly[i - 1].y, poly[i].x, poly[i].y, park)) return true;
    const Pt c = park.center();
    for (PolyView poly : world) {
        if (!isClosed(poly)) continue;
        int crossings = 0;
        for (size_t i = 1; i < poly.size(); ++i) {
            const Pt a = poly[i - 1], b = poly[i];
            if ((a.y > c.y) != (b.y > c.y) && c.x < a.x + (c.y - a.y) * (b.x - a.x) / (b.y - a.y)) ++crossings;
        }
        if (crossings % 2 == 1) return true;
    }
    return false;
}

// ---- Document ----

const Layer* Document::layer(const QString& id) const {
    for (const Layer& l : layers) if (l.id == id) return &l;
    return nullptr;
}
std::optional<Box> Document::bounds() const {
    std::optional<Box> out;
    for (const Element& e : elements) {
        const auto b = e.worldBounds();
        if (!b) continue;
        out = out ? out->united(*b) : *b;
    }
    return out;
}
Document Document::plateView(std::optional<int> i) const {
    const int plate = i.value_or(activePlate);
    Document d;
    d.title = title;
    d.layers = layers;
    d.plateCount = plateCount;
    d.activePlate = activePlate;
    d.extra = extra;
    for (const Element& e : elements) if (e.plate == plate) d.elements.push_back(e);
    return d;
}
int Document::plateSize(int i) const {
    int n = 0;
    for (const Element& e : elements) if (e.plate == i) ++n;
    return n;
}
Document Document::withPlate(const Document& view) const {
    Document d = *this;
    d.title = view.title;
    d.layers = view.layers;
    d.elements.clear();
    for (const Element& e : elements) if (e.plate != activePlate) d.elements.push_back(e);
    for (Element e : view.elements) { e.plate = activePlate; d.elements.push_back(std::move(e)); }
    return d;
}
Document Document::addPlate() const {
    Document d = *this;
    d.activePlate = plateCount;
    d.plateCount = plateCount + 1;
    return d;
}
Document Document::removePlate(int i) const {
    if (plateCount <= 1 || i < 0 || i >= plateCount) return *this;
    Document d = *this;
    d.elements.clear();
    for (Element e : elements) {
        if (e.plate == i) continue;
        if (e.plate > i) e.plate -= 1;
        d.elements.push_back(std::move(e));
    }
    d.plateCount = plateCount - 1;
    d.activePlate = activePlate >= i ? std::max(0, activePlate - 1) : activePlate;
    return d;
}
Document Document::moveToPlate(const std::set<QString>& ids, int target) const {
    if (target < 0 || target >= plateCount) return *this;
    Document d = *this;
    for (Element& e : d.elements) if (ids.count(e.id)) e.plate = target;
    return d;
}
Document Document::withoutEmptyLayers(const std::set<QString>& keep) const {
    std::set<QString> used;
    for (const Element& e : elements) used.insert(e.layerId);
    std::vector<Layer> left;
    for (const Layer& l : layers) if (used.count(l.id) || keep.count(l.id) || isStandardLayer(l.name)) left.push_back(l);
    if (left.size() == layers.size()) return *this;
    Document d = *this;
    d.layers = left.empty() ? defaultLayers() : std::move(left);
    return d;
}
std::vector<Layer> Document::shownLayers(const std::set<QString>& keep) const {
    std::set<QString> used;
    for (const Element& e : elements) used.insert(e.layerId);
    std::vector<Layer> out;
    for (const Layer& l : layers) if (used.count(l.id) || keep.count(l.id)) out.push_back(l);
    return out;
}
Document Document::deletingLayer(const QString& id) const {
    Document d = *this;
    d.elements.clear();
    for (const Element& e : elements) if (e.layerId != id) d.elements.push_back(e);
    d.layers.clear();
    for (const Layer& l : layers) if (!(l.id == id && !isStandardLayer(l.name))) d.layers.push_back(l);
    return d;
}
Document Document::movingLayer(const QString& id, bool up, const std::vector<QString>& shown) const {
    const auto it = std::find(shown.begin(), shown.end(), id);
    if (it == shown.end()) return *this;
    const std::ptrdiff_t k = it - shown.begin(), nk = up ? k - 1 : k + 1;
    if (nk < 0 || nk >= std::ptrdiff_t(shown.size())) return *this;
    const Layer* self = layer(id);
    if (!self) return *this;
    const Layer moved = *self;
    std::vector<Layer> list;
    for (const Layer& l : layers) if (l.id != id) list.push_back(l);
    std::ptrdiff_t n = -1;
    for (size_t i = 0; i < list.size(); ++i) if (list[i].id == shown[size_t(nk)]) { n = std::ptrdiff_t(i); break; }
    list.insert(list.begin() + (up ? n : n + 1), moved);
    Document d = *this;
    d.layers = std::move(list);
    return d;
}
Document Document::normalized() const {
    int maxPlate = 0;
    for (const Element& e : elements) maxPlate = std::max(maxPlate, e.plate);
    const int n = std::max({plateCount, maxPlate + 1, 1});
    Document d = *this;
    d.plateCount = n;
    d.activePlate = std::clamp(activePlate, 0, n - 1);
    for (Element& e : d.elements) if (e.plate < 0) e.plate = 0;
    return d;
}
std::vector<Layer> Document::defaultLayers() {
    std::vector<Layer> out;
    Layer a = newLayer(QStringLiteral("Gravieren"), 0xFF4FD8B4LL, LayerMode::Fill);
    a.powerPct = 25; a.speed = 3000; a.intervalMm = 0.1;
    out.push_back(std::move(a));
    Layer b = newLayer(QStringLiteral("Linie"), 0xFF6CB6FFLL, LayerMode::Line);
    b.powerPct = 40; b.speed = 1500;
    out.push_back(std::move(b));
    Layer c = newLayer(QStringLiteral("Schneiden"), 0xFFFF6B70LL, LayerMode::Line);
    c.powerPct = 85; c.speed = 400; c.passes = 2;
    out.push_back(std::move(c));
    return out;
}
bool Document::isStandardLayer(const QString& name) {
    return name == QLatin1String("Gravieren") || name == QLatin1String("Linie") || name == QLatin1String("Schneiden");
}
int Document::passesFor(double depthMm, double depthPerPassMm) {
    if (depthPerPassMm <= 0.0 || depthMm <= 0.0) return 1;
    return std::clamp(int(std::ceil(depthMm / depthPerPassMm - 1e-9)), Limits::PASSES_MIN, Limits::PASSES_MAX);
}

QString newId() { return QUuid::createUuid().toString(QUuid::WithoutBraces); }
Layer newLayer(const QString& name, qint64 color, LayerMode mode) {
    Layer l;
    l.id = newId();
    l.name = name;
    l.color = color;
    l.mode = mode;
    return l;
}
Element newElement(const QString& layerId, const QString& kind) {
    Element e;
    e.id = newId();
    e.layerId = layerId;
    e.kind = kind;
    return e;
}

// ---- Zahlenformat ----

namespace {
char* fmtInto(char* out, double v, int digits, char sep) {
    if (std::isnan(v)) { std::memcpy(out, "NaN", 3); return out + 3; }
    if (std::signbit(v)) *out++ = '-';
    const double a = std::fabs(v);
    if (a == HUGE_VAL) { std::memcpy(out, "Infinity", 8); return out + 8; }
    char buf[340];
    const auto r = std::to_chars(buf, buf + sizeof buf, a, std::chars_format::fixed);
    const char* const end = r.ptr;
    const char* dot = static_cast<const char*>(std::memchr(buf, '.', size_t(end - buf)));
    const size_t intLen = dot ? size_t(dot - buf) : size_t(end - buf);
    const size_t fracLen = dot ? size_t(end - dot - 1) : 0;
    const char* frac = dot ? dot + 1 : end;
    if (fracLen <= size_t(digits)) {
        std::memcpy(out, buf, intLen);
        out += intLen;
        if (digits > 0) {
            *out++ = sep;
            std::memcpy(out, frac, fracLen);
            out += fracLen;
            for (size_t i = fracLen; i < size_t(digits); ++i) *out++ = '0';
        }
        return out;
    }
    // Ziffern ohne Komma, ein Platz vorn frei für den Übertrag.
    char* head = out;
    *head = '0';
    std::memcpy(head + 1, buf, intLen);
    std::memcpy(head + 1 + intLen, frac, size_t(digits));
    const size_t n = 1 + intLen + size_t(digits);
    if (frac[digits] >= '5') {
        size_t i = n;
        while (i-- > 0) {
            if (head[i] == '9') { head[i] = '0'; continue; }
            ++head[i];
            break;
        }
    }
    const size_t skip = head[0] == '0' ? 1 : 0;
    if (skip) std::memmove(head, head + 1, n - 1);
    const size_t have = n - skip;
    if (digits == 0) return head + have;
    const size_t cut = have - size_t(digits);
    std::memmove(head + cut + 1, head + cut, size_t(digits));
    head[cut] = sep;
    return head + have + 1;
}
}  // namespace

QByteArray fmtFixed(double v, int digits, char sep) {
    char buf[400];
    return QByteArray(buf, fmtInto(buf, v, digits, sep) - buf);
}
char* fmt3Into(char* out, double v) { return fmtInto(out, v, 3, '.'); }

}  // namespace lumacut
