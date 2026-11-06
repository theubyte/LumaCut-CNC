/**
 * Projekt-JSON: eigener Lese-Schritt statt QJsonDocument, weil große Dateien fast nur aus Punkten und Base64
 * bestehen. Bekannte Felder gehen direkt ins Modell, Unbekanntes wird als QJsonValue aufgehoben.
 * Schreiben: gleiche Feldreihenfolge und Zahlenform wie kotlinx.serialization (Double.toString).
 */
#include "core/fastnum.h"
#include "core/model.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonValue>
#include <charconv>
#include <cmath>
#include <cstring>
#include <string>
#include <string_view>

namespace lumacut {
namespace {

class Reader {
public:
    explicit Reader(QByteArrayView t) : m_p(t.data()), m_begin(t.data()), m_e(t.data() + t.size()) {}

    [[noreturn]] void fail(const char* what) const {
        throw JsonError(std::string("Projektdatei ungültig: ") + what + " bei Byte " + std::to_string(m_p - m_begin));
    }
    void ws() {
        while (m_p < m_e && (*m_p == ' ' || *m_p == '\n' || *m_p == '\r' || *m_p == '\t')) ++m_p;
    }
    char peek() {
        ws();
        if (m_p >= m_e) fail("Ende der Datei");
        return *m_p;
    }
    void expect(char c) {
        if (peek() != c) fail("Zeichen erwartet");
        ++m_p;
    }
    bool accept(char c) {
        if (peek() == c) { ++m_p; return true; }
        return false;
    }
    bool atEnd() { ws(); return m_p >= m_e; }

    bool acceptNull() {
        if (peek() == 'n' && m_e - m_p >= 4 && std::memcmp(m_p, "null", 4) == 0) { m_p += 4; return true; }
        return false;
    }
    bool boolean() {
        if (peek() == 't' && m_e - m_p >= 4 && std::memcmp(m_p, "true", 4) == 0) { m_p += 4; return true; }
        if (peek() == 'f' && m_e - m_p >= 5 && std::memcmp(m_p, "false", 5) == 0) { m_p += 5; return false; }
        fail("true/false erwartet");
    }
    double number() {
        ws();
        double v = 0;
        const char* q = detail::parseDouble(m_p, m_e, v);
        if (!q) fail("Zahl erwartet");
        m_p = q;
        return v;
    }
    int integer() { return int(number()); }

    /** Rohtext eines Strings ohne Anführungszeichen; Fluchtzeichen werden in `scratch` aufgelöst. */
    std::string_view rawString(std::string& scratch) {
        if (peek() != '"') fail("Text erwartet");
        const char* s = ++m_p;
        const char* q = s;
        while (q < m_e && *q != '"' && *q != '\\') ++q;
        if (q >= m_e) fail("Text nicht beendet");
        if (*q == '"') { m_p = q + 1; return {s, size_t(q - s)}; }
        scratch.assign(s, q);
        m_p = q;
        while (true) {
            if (m_p >= m_e) fail("Text nicht beendet");
            const char c = *m_p++;
            if (c == '"') break;
            if (c != '\\') { scratch.push_back(c); continue; }
            if (m_p >= m_e) fail("Text nicht beendet");
            const char x = *m_p++;
            switch (x) {
                case 'n': scratch.push_back('\n'); break;
                case 't': scratch.push_back('\t'); break;
                case 'r': scratch.push_back('\r'); break;
                case 'b': scratch.push_back('\b'); break;
                case 'f': scratch.push_back('\f'); break;
                case '"': case '\\': case '/': scratch.push_back(x); break;
                case 'u': {
                    uint32_t cp = hex4();
                    if (cp >= 0xD800 && cp < 0xDC00 && m_e - m_p >= 6 && m_p[0] == '\\' && m_p[1] == 'u') {
                        m_p += 2;
                        const uint32_t lo = hex4();
                        if (lo >= 0xDC00 && lo < 0xE000) cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                    }
                    utf8(scratch, cp);
                    break;
                }
                default: fail("unbekanntes Fluchtzeichen");
            }
        }
        return scratch;
    }
    QString string() {
        std::string tmp;
        const std::string_view v = rawString(tmp);
        return QString::fromUtf8(v.data(), qsizetype(v.size()));
    }
    std::optional<QString> optString() {
        if (acceptNull()) return std::nullopt;
        return string();
    }

    /** Überspringt einen Wert und gibt ihn als QJsonValue zurück (für Unbekanntes). */
    QJsonValue value() {
        ws();
        const char* s = m_p;
        skip();
        QByteArray wrapped;
        wrapped.reserve((m_p - s) + 2);
        wrapped.append('[').append(s, m_p - s).append(']');
        QJsonParseError err{};
        const QJsonDocument d = QJsonDocument::fromJson(wrapped, &err);
        if (err.error != QJsonParseError::NoError) fail("unbekanntes Feld nicht lesbar");
        return d.array().at(0);
    }
    /** Liest einen Wert ohne ihn aufzuheben. */
    void skip() {
        const char c = peek();
        if (c == '{') {
            ++m_p;
            if (accept('}')) return;
            std::string tmp;
            do { rawString(tmp); expect(':'); skip(); } while (accept(','));
            expect('}');
        } else if (c == '[') {
            ++m_p;
            if (accept(']')) return;
            do { skip(); } while (accept(','));
            expect(']');
        } else if (c == '"') {
            std::string tmp;
            rawString(tmp);
        } else if (c == 't' || c == 'f') {
            boolean();
        } else if (!acceptNull()) {
            number();
        }
    }

    /** Ruft fn(key) je Feld; fn muss den Wert lesen. */
    template <class Fn>
    void object(Fn&& fn) {
        expect('{');
        if (accept('}')) return;
        std::string tmp;
        do {
            const std::string_view raw = rawString(tmp);
            const std::string key(raw);  // kurz, und der Wert kann tmp überschreiben
            expect(':');
            fn(std::string_view(key));
        } while (accept(','));
        expect('}');
    }
    template <class Fn>
    void array(Fn&& fn) {
        expect('[');
        if (accept(']')) return;
        do { fn(); } while (accept(','));
        expect(']');
    }

    /** Punktliste; der Regelfall {"x":1.0,"y":2.0} läuft ohne Umweg. */
    void points(PolySet& out, std::vector<Pt>& buf) {
        buf.clear();
        array([&] {
            Pt p;
            ws();
            if (m_e - m_p > 5 && std::memcmp(m_p, "{\"x\":", 5) == 0) {
                m_p += 5;
                const char* q = detail::parseDouble(m_p, m_e, p.x);
                if (q && m_e - q > 5 && std::memcmp(q, ",\"y\":", 5) == 0) {
                    q += 5;
                    q = detail::parseDouble(q, m_e, p.y);
                    if (q && q < m_e && *q == '}') {
                        m_p = q + 1;
                        buf.push_back(p);
                        return;
                    }
                }
                m_p -= 5;
            }
            object([&](std::string_view k) {
                if (k == "x") p.x = number();
                else if (k == "y") p.y = number();
                else skip();
            });
            buf.push_back(p);
        });
        out.add(buf);
    }

private:
    uint32_t hex4() {
        if (m_e - m_p < 4) fail("Fluchtzeichen unvollständig");
        uint32_t v = 0;
        for (int i = 0; i < 4; ++i) {
            const char c = *m_p++;
            v <<= 4;
            if (c >= '0' && c <= '9') v |= uint32_t(c - '0');
            else if (c >= 'a' && c <= 'f') v |= uint32_t(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') v |= uint32_t(c - 'A' + 10);
            else fail("Fluchtzeichen ungültig");
        }
        return v;
    }
    static void utf8(std::string& s, uint32_t cp) {
        if (cp < 0x80) s.push_back(char(cp));
        else if (cp < 0x800) { s.push_back(char(0xC0 | (cp >> 6))); s.push_back(char(0x80 | (cp & 63))); }
        else if (cp < 0x10000) { s.push_back(char(0xE0 | (cp >> 12))); s.push_back(char(0x80 | ((cp >> 6) & 63))); s.push_back(char(0x80 | (cp & 63))); }
        else { s.push_back(char(0xF0 | (cp >> 18))); s.push_back(char(0x80 | ((cp >> 12) & 63))); s.push_back(char(0x80 | ((cp >> 6) & 63))); s.push_back(char(0x80 | (cp & 63))); }
    }
    const char* m_p;
    const char* m_begin;
    const char* m_e;
};

inline QString qkey(std::string_view k) { return QString::fromUtf8(k.data(), qsizetype(k.size())); }

Transform readTransform(Reader& r) {
    Transform t;
    r.object([&](std::string_view k) {
        if (k == "x") t.x = r.number();
        else if (k == "y") t.y = r.number();
        else if (k == "scaleX") t.scaleX = r.number();
        else if (k == "scaleY") t.scaleY = r.number();
        else if (k == "rotation") t.rotation = r.number();
        else r.skip();
    });
    return t;
}
DarknessPoint readDarkPoint(Reader& r) {
    DarknessPoint p;
    r.object([&](std::string_view k) {
        if (k == "power") p.power = r.number();
        else if (k == "speed") p.speed = r.number();
        else if (k == "tone") p.tone = r.number();
        else if (k == "clean") p.clean = r.boolean();
        else p.extra.insert(qkey(k), r.value());
    });
    return p;
}
DarknessCurve readDarkness(Reader& r) {
    DarknessCurve c;
    r.object([&](std::string_view k) {
        if (k == "points") r.array([&] { c.points.push_back(readDarkPoint(r)); });
        else if (k == "min_power_pct") c.minPowerPct = r.number();
        else if (k == "interval_mm") c.intervalMm = r.number();
        else if (k == "speed_min") c.speedMin = r.number();
        else if (k == "speed_max") c.speedMax = r.number();
        else c.extra.insert(qkey(k), r.value());
    });
    return c;
}
LayerMode readMode(Reader& r) {
    const QString s = r.string();
    if (s == QLatin1String("LINE")) return LayerMode::Line;
    if (s == QLatin1String("FILL")) return LayerMode::Fill;
    r.fail("unbekannte Ebenenart");
}
ImageMode readImageMode(Reader& r) {
    const QString s = r.string();
    if (s == QLatin1String("GRAYSCALE")) return ImageMode::Grayscale;
    if (s == QLatin1String("DITHER")) return ImageMode::Dither;
    if (s == QLatin1String("THRESHOLD")) return ImageMode::Threshold;
    if (s == QLatin1String("DITHER_JARVIS")) return ImageMode::DitherJarvis;
    if (s == QLatin1String("DITHER_STUCKI")) return ImageMode::DitherStucki;
    r.fail("unbekannte Bildart");
}
Layer readLayer(Reader& r) {
    Layer l;
    bool hasId = false;
    r.object([&](std::string_view k) {
        if (k == "id") { l.id = r.string(); hasId = true; }
        else if (k == "name") l.name = r.string();
        else if (k == "color") l.color = qint64(r.number());
        else if (k == "mode") l.mode = readMode(r);
        else if (k == "powerPct") l.powerPct = r.number();
        else if (k == "minPowerPct") l.minPowerPct = r.number();
        else if (k == "speed") l.speed = r.number();
        else if (k == "passes") l.passes = r.integer();
        else if (k == "intervalMm") l.intervalMm = r.number();
        else if (k == "overscanMm") l.overscanMm = r.number();
        else if (k == "zStepMm") l.zStepMm = r.number();
        else if (k == "output") l.output = r.boolean();
        else if (k == "visible") l.visible = r.boolean();
        else if (k == "locked") l.locked = r.boolean();
        else if (k == "materialName") l.materialName = r.optString();
        else if (k == "thicknessMm") l.thicknessMm = r.number();
        else if (k == "depthPerPassMm") l.depthPerPassMm = r.number();
        else if (k == "toneCurve") r.array([&] { l.toneCurve.push_back(r.number()); });
        else if (k == "darkness") { if (!r.acceptNull()) l.darkness = readDarkness(r); }
        else l.extra.insert(qkey(k), r.value());
    });
    if (!hasId) l.id = newId();
    return l;
}
std::vector<CurvePath> readCurves(Reader& r) {
    std::vector<CurvePath> out;
    r.array([&] {
        CurvePath c;
        r.object([&](std::string_view k) {
            if (k == "closed") c.closed = r.boolean();
            else if (k == "nodes") r.array([&] {
                CurveNode n;
                r.object([&](std::string_view f) {
                    if (f == "x") n.x = r.number();
                    else if (f == "y") n.y = r.number();
                    else if (f == "smooth") n.smooth = r.boolean();
                    else if (r.acceptNull()) return;
                    else if (f == "hx1") n.hx1 = r.number();
                    else if (f == "hy1") n.hy1 = r.number();
                    else if (f == "hx2") n.hx2 = r.number();
                    else if (f == "hy2") n.hy2 = r.number();
                    else r.skip();
                });
                c.nodes.push_back(n);
            });
            else r.skip();
        });
        out.push_back(std::move(c));
    });
    return out;
}
Element readElement(Reader& r) {
    Element e;
    bool hasId = false;
    std::vector<Pt> buf;
    r.object([&](std::string_view k) {
        if (k == "paths") r.array([&] { r.points(e.paths, buf); });
        else if (k == "id") { e.id = r.string(); hasId = true; }
        else if (k == "layerId") e.layerId = r.string();
        else if (k == "kind") e.kind = r.string();
        else if (k == "transform") e.transform = readTransform(r);
        else if (k == "text") e.text = r.optString();
        else if (k == "fontSizeMm") e.fontSizeMm = r.number();
        else if (k == "bold") e.bold = r.boolean();
        else if (k == "fontFamily") e.fontFamily = r.string();
        else if (k == "raster") {
            if (r.acceptNull()) return;
            int w = 0, h = 0;
            QByteArray b64;
            r.object([&](std::string_view f) {
                if (f == "width") w = r.integer();
                else if (f == "height") h = r.integer();
                else if (f == "grayBase64") { std::string tmp; const auto v = r.rawString(tmp); b64 = QByteArray(v.data(), qsizetype(v.size())); }
                else r.skip();
            });
            e.raster = Raster::fromBase64(w, h, std::move(b64));
        }
        else if (k == "imageWidthMm") e.imageWidthMm = r.number();
        else if (k == "imageHeightMm") e.imageHeightMm = r.number();
        else if (k == "imageMode") e.imageMode = readImageMode(r);
        else if (k == "adjust") r.object([&](std::string_view f) {
            if (f == "brightness") e.adjust.brightness = r.integer();
            else if (f == "contrast") e.adjust.contrast = r.integer();
            else if (f == "sharpen") e.adjust.sharpen = r.integer();
            else if (f == "invert") e.adjust.invert = r.boolean();
            else e.adjust.extra.insert(qkey(f), r.value());
        });
        else if (k == "groupId") e.groupId = r.optString();
        else if (k == "plate") e.plate = r.integer();
        else if (k == "curves") { if (!r.acceptNull()) e.curves = readCurves(r); }
        else e.extra.insert(qkey(k), r.value());
    });
    if (!hasId) e.id = newId();
    return e;
}

// ---- Schreiben ----

class Writer {
public:
    std::string s;
    void raw(std::string_view v) { s.append(v); }
    /** Wie Javas Double.toString: "1.0", "0.001", "1.0E-4", "1.2345675E7". */
    void num(double d) {
        if (d == 0) { s.append(std::signbit(d) ? "-0.0" : "0.0"); return; }
        char buf[64];
        const double a = std::fabs(d);
        if (a >= 1e-3 && a < 1e7) {
            const auto r = std::to_chars(buf, buf + sizeof buf, d, std::chars_format::fixed);
            s.append(buf, size_t(r.ptr - buf));
            if (!std::memchr(buf, '.', size_t(r.ptr - buf))) s.append(".0");
            return;
        }
        const auto r = std::to_chars(buf, buf + sizeof buf, d, std::chars_format::scientific);
        const char* e = static_cast<const char*>(std::memchr(buf, 'e', size_t(r.ptr - buf)));
        s.append(buf, size_t(e - buf));
        if (!std::memchr(buf, '.', size_t(e - buf))) s.append(".0");
        s.push_back('E');
        const char* x = e + 1;
        if (*x == '-') s.push_back(*x);
        if (*x == '-' || *x == '+') ++x;
        while (x + 1 < r.ptr && *x == '0') ++x;
        s.append(x, size_t(r.ptr - x));
    }
    void integer(qint64 v) {
        char buf[32];
        const auto r = std::to_chars(buf, buf + sizeof buf, v);
        s.append(buf, size_t(r.ptr - buf));
    }
    void boolean(bool v) { s.append(v ? "true" : "false"); }
    void str(const QString& v) {
        const QByteArray u = v.toUtf8();
        s.push_back('"');
        for (const char c : u) {
            switch (c) {
                case '"': s.append("\\\""); break;
                case '\\': s.append("\\\\"); break;
                case '\n': s.append("\\n"); break;
                case '\r': s.append("\\r"); break;
                case '\t': s.append("\\t"); break;
                case '\b': s.append("\\b"); break;
                case '\f': s.append("\\f"); break;
                default:
                    if (static_cast<unsigned char>(c) < 0x20) {
                        static const char* hex = "0123456789abcdef";
                        s.append("\\u00");
                        s.push_back(hex[(c >> 4) & 15]);
                        s.push_back(hex[c & 15]);
                    } else s.push_back(c);
            }
        }
        s.push_back('"');
    }
    void optStr(const std::optional<QString>& v) {
        if (v) str(*v); else s.append("null");
    }
    void extra(const QJsonObject& o) {
        for (auto it = o.begin(); it != o.end(); ++it) {
            s.push_back(',');
            str(it.key());
            s.push_back(':');
            QJsonArray wrap;
            wrap.append(it.value());
            const QByteArray j = QJsonDocument(wrap).toJson(QJsonDocument::Compact);
            s.append(j.constData() + 1, size_t(j.size() - 2));
        }
    }
};

void writeLayer(Writer& w, const Layer& l) {
    w.raw("{\"id\":"); w.str(l.id);
    w.raw(",\"name\":"); w.str(l.name);
    w.raw(",\"color\":"); w.integer(l.color);
    w.raw(",\"mode\":"); w.raw(l.mode == LayerMode::Line ? "\"LINE\"" : "\"FILL\"");
    w.raw(",\"powerPct\":"); w.num(l.powerPct);
    w.raw(",\"minPowerPct\":"); w.num(l.minPowerPct);
    w.raw(",\"speed\":"); w.num(l.speed);
    w.raw(",\"passes\":"); w.integer(l.passes);
    w.raw(",\"intervalMm\":"); w.num(l.intervalMm);
    w.raw(",\"overscanMm\":"); w.num(l.overscanMm);
    w.raw(",\"zStepMm\":"); w.num(l.zStepMm);
    w.raw(",\"output\":"); w.boolean(l.output);
    w.raw(",\"visible\":"); w.boolean(l.visible);
    w.raw(",\"locked\":"); w.boolean(l.locked);
    w.raw(",\"materialName\":"); w.optStr(l.materialName);
    w.raw(",\"thicknessMm\":"); w.num(l.thicknessMm);
    w.raw(",\"depthPerPassMm\":"); w.num(l.depthPerPassMm);
    w.raw(",\"toneCurve\":[");
    for (size_t i = 0; i < l.toneCurve.size(); ++i) { if (i) w.raw(","); w.num(l.toneCurve[i]); }
    w.raw("],\"darkness\":");
    if (!l.darkness) w.raw("null");
    else {
        const DarknessCurve& c = *l.darkness;
        w.raw("{\"points\":[");
        for (size_t i = 0; i < c.points.size(); ++i) {
            const DarknessPoint& p = c.points[i];
            if (i) w.raw(",");
            w.raw("{\"power\":"); w.num(p.power);
            w.raw(",\"speed\":"); w.num(p.speed);
            w.raw(",\"tone\":"); w.num(p.tone);
            w.raw(",\"clean\":"); w.boolean(p.clean);
            w.extra(p.extra);
            w.raw("}");
        }
        w.raw("],\"min_power_pct\":"); w.num(c.minPowerPct);
        w.raw(",\"interval_mm\":"); w.num(c.intervalMm);
        w.raw(",\"speed_min\":"); w.num(c.speedMin);
        w.raw(",\"speed_max\":"); w.num(c.speedMax);
        w.extra(c.extra);
        w.raw("}");
    }
    w.extra(l.extra);
    w.raw("}");
}
const char* imageModeName(ImageMode m) {
    switch (m) {
        case ImageMode::Dither: return "\"DITHER\"";
        case ImageMode::Threshold: return "\"THRESHOLD\"";
        case ImageMode::DitherJarvis: return "\"DITHER_JARVIS\"";
        case ImageMode::DitherStucki: return "\"DITHER_STUCKI\"";
        default: return "\"GRAYSCALE\"";
    }
}
void writeElement(Writer& w, const Element& e) {
    w.raw("{\"id\":"); w.str(e.id);
    w.raw(",\"layerId\":"); w.str(e.layerId);
    w.raw(",\"kind\":"); w.str(e.kind);
    w.raw(",\"transform\":{\"x\":"); w.num(e.transform.x);
    w.raw(",\"y\":"); w.num(e.transform.y);
    w.raw(",\"scaleX\":"); w.num(e.transform.scaleX);
    w.raw(",\"scaleY\":"); w.num(e.transform.scaleY);
    w.raw(",\"rotation\":"); w.num(e.transform.rotation);
    w.raw("},\"paths\":[");
    bool firstPoly = true;
    for (PolyView poly : e.paths) {
        if (!firstPoly) w.raw(",");
        firstPoly = false;
        w.raw("[");
        for (size_t i = 0; i < poly.size(); ++i) {
            if (i) w.raw(",");
            w.raw("{\"x\":"); w.num(poly[i].x);
            w.raw(",\"y\":"); w.num(poly[i].y);
            w.raw("}");
        }
        w.raw("]");
    }
    w.raw("],\"text\":"); w.optStr(e.text);
    w.raw(",\"fontSizeMm\":"); w.num(e.fontSizeMm);
    w.raw(",\"bold\":"); w.boolean(e.bold);
    w.raw(",\"fontFamily\":"); w.str(e.fontFamily);
    w.raw(",\"raster\":");
    if (!e.raster) w.raw("null");
    else {
        w.raw("{\"width\":"); w.integer(e.raster.width());
        w.raw(",\"height\":"); w.integer(e.raster.height());
        w.raw(",\"grayBase64\":\"");
        const QByteArray b = e.raster.grayBase64();
        w.s.append(b.constData(), size_t(b.size()));
        w.raw("\"}");
    }
    w.raw(",\"imageWidthMm\":"); w.num(e.imageWidthMm);
    w.raw(",\"imageHeightMm\":"); w.num(e.imageHeightMm);
    w.raw(",\"imageMode\":"); w.raw(imageModeName(e.imageMode));
    w.raw(",\"adjust\":{\"brightness\":"); w.integer(e.adjust.brightness);
    w.raw(",\"contrast\":"); w.integer(e.adjust.contrast);
    w.raw(",\"sharpen\":"); w.integer(e.adjust.sharpen);
    w.raw(",\"invert\":"); w.boolean(e.adjust.invert);
    w.extra(e.adjust.extra);
    w.raw("},\"groupId\":"); w.optStr(e.groupId);
    w.raw(",\"plate\":"); w.integer(e.plate);
    if (e.curves) {
        w.raw(",\"curves\":[");
        for (size_t i = 0; i < e.curves->size(); ++i) {
            const CurvePath& c = (*e.curves)[i];
            if (i) w.raw(",");
            w.raw("{\"nodes\":[");
            for (size_t k = 0; k < c.nodes.size(); ++k) {
                const CurveNode& n = c.nodes[k];
                if (k) w.raw(",");
                w.raw("{\"x\":"); w.num(n.x);
                w.raw(",\"y\":"); w.num(n.y);
                if (n.hx1) { w.raw(",\"hx1\":"); w.num(*n.hx1); }
                if (n.hy1) { w.raw(",\"hy1\":"); w.num(*n.hy1); }
                if (n.hx2) { w.raw(",\"hx2\":"); w.num(*n.hx2); }
                if (n.hy2) { w.raw(",\"hy2\":"); w.num(*n.hy2); }
                if (n.smooth) w.raw(",\"smooth\":true");
                w.raw("}");
            }
            w.raw("],\"closed\":"); w.boolean(c.closed);
            w.raw("}");
        }
        w.raw("]");
    }
    w.extra(e.extra);
    w.raw("}");
}

}  // namespace

Document Document::fromJson(QByteArrayView text) {
    Reader r(text);
    Document d;
    bool hasLayers = false;
    r.object([&](std::string_view k) {
        if (k == "title") d.title = r.string();
        else if (k == "layers") {
            hasLayers = true;
            d.layers.clear();
            r.array([&] { d.layers.push_back(readLayer(r)); });
        }
        else if (k == "elements") r.array([&] { d.elements.push_back(readElement(r)); });
        else if (k == "plateCount") d.plateCount = r.integer();
        else if (k == "activePlate") d.activePlate = r.integer();
        else d.extra.insert(qkey(k), r.value());
    });
    if (!r.atEnd()) r.fail("Text nach dem Projekt");
    (void)hasLayers;
    // Wie normalized(), aber ohne Kopie.
    int maxPlate = 0;
    for (Element& e : d.elements) {
        maxPlate = std::max(maxPlate, e.plate);
        if (e.plate < 0) e.plate = 0;
    }
    d.plateCount = std::max({d.plateCount, maxPlate + 1, 1});
    d.activePlate = std::clamp(d.activePlate, 0, d.plateCount - 1);
    return d;
}

QByteArray Document::toJson() const {
    Writer w;
    size_t estimate = 256;
    for (const Element& e : elements) estimate += 400 + e.paths.pointCount() * 32 + (e.raster ? size_t(e.raster.width()) * e.raster.height() * 3 / 2 : 0);
    w.s.reserve(estimate);
    w.raw("{\"title\":"); w.str(title);
    w.raw(",\"layers\":[");
    for (size_t i = 0; i < layers.size(); ++i) { if (i) w.raw(","); writeLayer(w, layers[i]); }
    w.raw("],\"elements\":[");
    for (size_t i = 0; i < elements.size(); ++i) { if (i) w.raw(","); writeElement(w, elements[i]); }
    w.raw("],\"plateCount\":"); w.integer(plateCount);
    w.raw(",\"activePlate\":"); w.integer(activePlate);
    w.extra(extra);
    w.raw("}");
    return QByteArray(w.s.data(), qsizetype(w.s.size()));
}

}  // namespace lumacut
