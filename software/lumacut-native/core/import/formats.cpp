/** Dateityp am Inhalt erkennen, HPGL, LightBurn. Wie ImportFormats.kt und formats.ts. */
#include "core/fastnum.h"
#include "core/geometry.h"
#include "core/import/vector.h"
#include "core/import/xml.h"
#include "core/import/zip.h"

#include <QRegularExpression>
#include <QStringDecoder>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <map>

namespace lumacut::import {
namespace {
constexpr double HPGL_UNITS = 40;
constexpr double LB_CURVE_MM = 0.15;
inline bool isLetter(char c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
}

QString kindLabel(FileKind kind) {
    switch (kind) {
    case FileKind::Svg: return QStringLiteral("SVG");
    case FileKind::Dxf: return QStringLiteral("DXF");
    case FileKind::Xcs: return QStringLiteral("xTool Creative Space");
    case FileKind::Xs: return QStringLiteral("xTool Studio");
    case FileKind::Lbrn: return QStringLiteral("LightBurn");
    case FileKind::Hpgl: return QStringLiteral("HPGL");
    case FileKind::Pdf: return QStringLiteral("PDF");
    case FileKind::Image: return QStringLiteral("Bild");
    case FileKind::Project: return QStringLiteral("LumaCut-Projekt");
    case FileKind::Unknown: break;
    }
    return QStringLiteral("Unbekannt");
}

QByteArray decodeText(const QByteArray& bytes) {
    if (bytes.size() >= 2 && uint8_t(bytes[0]) == 0xFF && uint8_t(bytes[1]) == 0xFE)
        return QString::fromUtf16(reinterpret_cast<const char16_t*>(bytes.constData() + 2), (bytes.size() - 2) / 2).toUtf8();
    if (bytes.size() >= 2 && uint8_t(bytes[0]) == 0xFE && uint8_t(bytes[1]) == 0xFF) {
        QStringDecoder dec(QStringDecoder::Utf16BE);
        return QString(dec(QByteArrayView(bytes).sliced(2))).toUtf8();
    }
    QByteArrayView view = bytes;
    if (view.size() >= 3 && uint8_t(view[0]) == 0xEF && uint8_t(view[1]) == 0xBB && uint8_t(view[2]) == 0xBF) return bytes.mid(3);
    const QByteArray head = bytes.left(120);
    const qsizetype decl = head.indexOf("<?xml");
    if (decl >= 0) {
        const qsizetype enc = head.indexOf("encoding=", decl);
        const qsizetype close = head.indexOf("?>", decl);
        if (enc >= 0 && (close < 0 || enc < close) && enc + 10 < head.size()) {
            const char q = head[enc + 9];
            const qsizetype stop = head.indexOf(q, enc + 10);
            if ((q == '"' || q == '\'') && stop > 0) {
                const QByteArray name = head.mid(enc + 10, stop - enc - 10).toLower();
                if (name != "utf-8" && name != "utf8") {
                    QStringDecoder dec(name.constData());
                    if (dec.isValid()) return QString(dec(view)).toUtf8();
                }
            }
        }
    }
    return bytes;
}

FileKind detectKind(const QByteArray& bytes) {
    if (bytes.size() < 4) return FileKind::Unknown;
    const auto ascii = [&](qsizetype from, qsizetype n) { return bytes.size() >= from + n ? QByteArrayView(bytes).sliced(from, n) : QByteArrayView(); };
    const auto u = [&](qsizetype i) { return uint8_t(bytes[i]); };
    if (bytes[0] == 'P' && bytes[1] == 'K') return isXs(bytes) ? FileKind::Xs : FileKind::Unknown;
    if (ascii(0, 4) == "%PDF") return FileKind::Pdf;
    if (u(0) == 0x89 && ascii(1, 3) == "PNG") return FileKind::Image;
    if (u(0) == 0xFF && u(1) == 0xD8 && u(2) == 0xFF) return FileKind::Image;
    if (ascii(0, 4) == "GIF8") return FileKind::Image;
    if (ascii(0, 2) == "BM" && bytes.size() > 30) return FileKind::Image;
    if (ascii(0, 4) == "RIFF" && ascii(8, 4) == "WEBP") return FileKind::Image;
    if (ascii(4, 4) == "ftyp") {
        const QByteArrayView brand = ascii(8, 4);
        if (brand.startsWith("hei") || brand.startsWith("mif") || brand.startsWith("avi")) return FileKind::Image;
    }
    // UTF-16 mit BOM erkennt die Vorlage nicht; hier zählt es als Text.
    const bool utf16 = (u(0) == 0xFF && u(1) == 0xFE) || (u(0) == 0xFE && u(1) == 0xFF);
    const QString head = utf16 ? QString::fromUtf8(decodeText(bytes.left(65536))) : QString::fromUtf8(bytes.constData(), std::min<qsizetype>(bytes.size(), 65536));
    qsizetype start = 0;
    while (start < head.size() && (head[start] == QChar(0xFEFF) || head[start] == QLatin1Char(' ') || head[start] == QLatin1Char('\t') || head[start] == QLatin1Char('\r') || head[start] == QLatin1Char('\n'))) ++start;
    const QString text = head.mid(start);
    const QString lower = text.toLower();
    if (lower.contains(QLatin1String("<lightburnproject"))) return FileKind::Lbrn;
    if (lower.contains(QLatin1String("<svg"))) return FileKind::Svg;
    const bool json = text.startsWith(QLatin1Char('{'));
    if (json && lower.contains(QLatin1String("\"layers\"")) && lower.contains(QLatin1String("\"title\""))) return FileKind::Project;
    if (json && (lower.contains(QLatin1String("\"displays\"")) || lower.contains(QLatin1String("\"canvas\"")) || lower.contains(QLatin1String("\"dpath\"")))) return FileKind::Xcs;
    const QRegularExpression dxf1(QStringLiteral("^0\\s*\\r?\\n\\s*SECTION"), QRegularExpression::CaseInsensitiveOption);
    const QRegularExpression dxf2(QStringLiteral("\\r?\\n\\s*0\\s*\\r?\\n\\s*SECTION\\s*\\r?\\n"));
    if (dxf1.match(text).hasMatch() || dxf2.match(text).hasMatch()) return FileKind::Dxf;
    const QRegularExpression hpgl(QStringLiteral("^\\s*(IN|SP\\d?|PU|PD|PA)\\b[;\\d\\s,-]"), QRegularExpression::MultilineOption);
    if (hpgl.match(text.toUpper()).hasMatch()) return FileKind::Hpgl;
    return FileKind::Unknown;
}

// ---- HPGL ----

PolySet parseHpgl(const QByteArray& bytes) {
    PolySet out;
    Poly cur;
    bool down = false, absolute = true;
    double x = 0, y = 0;
    PointBudget budget(QStringLiteral("HPGL zu komplex"));
    const auto flush = [&] {
        if (cur.size() >= 2) { budget.take(qint64(cur.size())); out.add(PolyView(cur)); }
        cur.clear();
    };
    std::vector<double> args;
    const auto moves = [&] {
        for (size_t i = 0; i + 1 < args.size(); i += 2) {
            const double nx = absolute ? args[i] : x + args[i], ny = absolute ? args[i + 1] : y + args[i + 1];
            if (down) {
                if (cur.empty()) cur.push_back({x / HPGL_UNITS, -y / HPGL_UNITS});
                cur.push_back({nx / HPGL_UNITS, -ny / HPGL_UNITS});
                if (cur.size() > size_t(MAX_POINTS)) throw ImportError(QStringLiteral("HPGL zu komplex"));
            } else {
                flush();
            }
            x = nx;
            y = ny;
        }
    };
    const char* p = bytes.constData();
    const char* end = p + bytes.size();
    // Befehl = zwei Buchstaben, Zahlen bis zum nächsten Buchstaben. So klappt auch "PU0,0PD40,0" ohne Semikolon.
    while (p < end) {
        if (!isLetter(*p)) { ++p; continue; }
        if (p + 1 >= end || !isLetter(p[1])) { ++p; continue; }
        const char a = char(std::toupper(uint8_t(p[0]))), b = char(std::toupper(uint8_t(p[1])));
        p += 2;
        args.clear();
        while (p < end && !isLetter(*p) && *p != ';') {
            const char c = *p;
            double v = 0;
            const char* q = (c == '-' || c == '+' || c == '.' || (c >= '0' && c <= '9')) ? detail::parseDouble(p, end, v) : nullptr;
            if (!q) { ++p; continue; }
            if (std::isfinite(v)) args.push_back(v);
            p = q;
        }
        if (a == 'I' && b == 'N') { flush(); down = false; absolute = true; }
        else if (a == 'P' && b == 'A') { absolute = true; moves(); }
        else if (a == 'P' && b == 'R') { absolute = false; moves(); }
        else if (a == 'P' && b == 'U') { flush(); down = false; moves(); }
        else if (a == 'P' && b == 'D') { down = true; moves(); }
    }
    flush();
    if (out.empty()) throw ImportError(QStringLiteral("Keine Linien in der HPGL-Datei gefunden"));
    const Box box = *boundsOf(out);
    for (Pt& q : out.allPoints()) q = {q.x - box.minX, q.y - box.minY};
    return out;
}

// ---- LightBurn ----

namespace {

struct Vert {
    Pt p;
    std::optional<Pt> c0, c1;
};

template <class To>
void bezierTo(Pt p0, Pt c1, Pt c2, Pt p1, To&& to) {
    const double approx = dist(p0, c1) + dist(c1, c2) + dist(c2, p1);
    const int n = clampSteps(approx / (LB_CURVE_MM * 4), 2, 400);
    for (int k = 1; k <= n; ++k) {
        const double t = double(k) / n, u = 1 - t;
        to(Pt{u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
              u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y});
    }
}

std::vector<Vert> readVerts(QByteArrayView text) {
    std::vector<Vert> verts;
    std::optional<double> c0x, c0y, c1x, c1y;
    const auto flush = [&] {
        if (verts.empty()) return;
        if (c0x && c0y) verts.back().c0 = Pt{*c0x, *c0y};
        if (c1x && c1y) verts.back().c1 = Pt{*c1x, *c1y};
        c0x.reset(); c0y.reset(); c1x.reset(); c1y.reset();
    };
    const char* p = text.data();
    const char* end = p + text.size();
    while (p < end) {
        if (*p == 'V') {
            double x = 0, y = 0;
            const char* q = detail::parseDouble(p + 1, end, x);
            if (q) {
                const char* s = q;
                while (s < end && std::isspace(uint8_t(*s))) ++s;
                const char* r = s > q ? detail::parseDouble(s, end, y) : nullptr;
                if (r) {
                    flush();
                    verts.push_back({{x, y}, {}, {}});
                    p = r;
                    continue;
                }
            }
            ++p;
        } else if (*p == 'c' && end - p >= 3 && (p[1] == '0' || p[1] == '1') && (p[2] == 'x' || p[2] == 'y')) {
            double v = 0;
            const char* q = detail::parseDouble(p + 3, end, v);
            if (q) {
                std::optional<double>& slot = p[1] == '0' ? (p[2] == 'x' ? c0x : c0y) : (p[2] == 'x' ? c1x : c1y);
                slot = v;
                p = q;
            } else {
                p += 3;
            }
        } else {
            ++p;
        }
    }
    flush();
    return verts;
}

void lbPath(QByteArrayView vertText, QByteArrayView primText, PolySet& out, PointBudget& budget) {
    const std::vector<Vert> verts = readVerts(vertText);
    const QByteArrayView shortForm = trimmedView(primText);
    Poly cur;
    const auto flush = [&] {
        if (cur.size() >= 2) { budget.take(qint64(cur.size())); out.add(PolyView(cur)); }
        cur.clear();
    };
    // Kurzformen aus .lbrn2: alle Punkte nacheinander.
    if (shortForm == "LineClosed" || shortForm == "Line") {
        for (const Vert& v : verts) cur.push_back(v.p);
        if (shortForm == "LineClosed" && !cur.empty()) cur.push_back(cur.front());
        flush();
        return;
    }
    const char* p = primText.data();
    const char* end = p + primText.size();
    const auto integer = [&](const char*& s, int& v) {
        const char* a = s;
        v = 0;
        while (s < end && *s >= '0' && *s <= '9' && s - a < 9) v = v * 10 + (*s++ - '0');
        return s > a;
    };
    int last = -1;
    while (p < end) {
        const char kind = *p++;
        if (kind != 'L' && kind != 'B') continue;
        const char* s = p;
        while (s < end && std::isspace(uint8_t(*s))) ++s;
        int i = 0, j = 0;
        if (!integer(s, i)) continue;
        const char* gap = s;
        while (s < end && std::isspace(uint8_t(*s))) ++s;
        if (s == gap || !integer(s, j)) continue;
        p = s;
        if (size_t(i) >= verts.size() || size_t(j) >= verts.size()) continue;
        if (i != last) { flush(); cur.push_back(verts[size_t(i)].p); }
        const Vert& a = verts[size_t(i)];
        const Vert& b = verts[size_t(j)];
        if (kind == 'L') cur.push_back(b.p);
        else bezierTo(a.p, a.c1.value_or(a.p), b.c0.value_or(b.p), b.p, [&](Pt q) { cur.push_back(q); });
        if (cur.size() > size_t(MAX_POINTS)) throw ImportError(QStringLiteral("LightBurn-Datei zu komplex"));
        last = j;
    }
    flush();
}

struct LbCtx {
    const XmlDoc& doc;
    PolySet polys;
    std::vector<EmbeddedImage> images;
    std::vector<std::pair<QString, int>> skipped;
    int textPaths = 0;
    PointBudget budget{QStringLiteral("LightBurn-Datei zu komplex")};
    /** Kopien einer Form tragen nur VertID und PrimID; die Listen stehen bei der ersten. */
    std::map<QByteArray, QByteArray> vertLists, primLists;

    void skip(const QString& t) {
        for (auto& e : skipped) if (e.first == t) { ++e.second; return; }
        skipped.push_back({t, 1});
    }
    double num(int el, QByteArrayView name) const { return parseFloatOr(doc.rawAttr(el, name), 0); }

    Matrix xform(int el) const {
        const int x = doc.child(el, "XForm");
        if (x >= 0) {
            const QByteArray text = doc.text(x);
            std::vector<double> v;
            const char* p = text.constData();
            const char* end = p + text.size();
            while (p < end && v.size() < 7) {
                while (p < end && std::isspace(uint8_t(*p))) ++p;
                if (p >= end) break;
                double d = 0;
                const char* q = detail::parseDouble(p, end, d);
                if (!q) return {};
                v.push_back(d);
                p = q;
            }
            if (v.size() == 6) return {v[0], v[1], v[2], v[3], v[4], v[5]};
        }
        return {};
    }
    void add(const PolySet& local, const Matrix& m) {
        for (PolyView poly : local) {
            std::span<Pt> o = polys.addUninitialized(poly.size());
            for (size_t i = 0; i < poly.size(); ++i) o[i] = m.apply(poly[i]);
        }
    }
    void pathOf(int el, const Matrix& m) {
        const int vl = doc.child(el, "VertList"), pl = doc.child(el, "PrimList");
        const QByteArray vid = doc.attr(el, "VertID"), pid = doc.attr(el, "PrimID");
        QByteArray verts = vl >= 0 ? doc.text(vl) : QByteArray(), prims = pl >= 0 ? doc.text(pl) : QByteArray();
        if (!vid.isEmpty()) {
            if (vl >= 0) vertLists[QByteArray(vid.constData(), vid.size())] = verts;
            else if (const auto it = vertLists.find(vid); it != vertLists.end()) verts = it->second;
        }
        if (!pid.isEmpty()) {
            if (pl >= 0) primLists[QByteArray(pid.constData(), pid.size())] = prims;
            else if (const auto it = primLists.find(pid); it != primLists.end()) prims = it->second;
        }
        PolySet local;
        lbPath(verts, prims, local, budget);
        add(local, m);
    }
    void shape(int el, const Matrix& parent, int depth) {
        if (depth > XmlDoc::MAX_DEPTH) return;
        const Matrix m = parent * xform(el);
        const QByteArray typeRaw = doc.attr(el, "Type");
        const QByteArrayView type = typeRaw;
        if (type == "Rect") {
            const double w = num(el, "W"), h = num(el, "H");
            const Poly r = Shapes::rect(w, h, num(el, "Cr"));
            budget.take(qint64(r.size()));
            PolySet local;
            std::span<Pt> o = local.addUninitialized(r.size());
            for (size_t i = 0; i < r.size(); ++i) o[i] = {r[i].x - w / 2, r[i].y - h / 2};
            add(local, m);
        } else if (type == "Ellipse") {
            const double rx = num(el, "Rx"), ry = num(el, "Ry");
            const Poly r = safeEllipse(2 * rx, 2 * ry);
            budget.take(qint64(r.size()));
            PolySet local;
            std::span<Pt> o = local.addUninitialized(r.size());
            for (size_t i = 0; i < r.size(); ++i) o[i] = {r[i].x - rx, r[i].y - ry};
            add(local, m);
        } else if (type == "Path") {
            pathOf(el, m);
        } else if (type == "Bitmap") {
            const QByteArray data = decodeBase64Loose(doc.rawAttr(el, "Data"));
            const double w = num(el, "W"), h = num(el, "H");
            if (data.isEmpty() || w <= 0 || h <= 0) { skip(QStringLiteral("Bitmap")); return; }
            const Pt c[4] = {m.apply({-w / 2, -h / 2}), m.apply({w / 2, -h / 2}), m.apply({w / 2, h / 2}), m.apply({-w / 2, h / 2})};
            images.push_back({data, *boundsOf(PolyView(c, 4))});
        } else if (type == "Group") {
            const int kids = doc.child(el, "Children");
            if (kids >= 0) {
                for (int k = doc.node(kids).firstChild; k >= 0; k = doc.node(k).nextSibling)
                    if (doc.node(k).tag == "Shape") shape(k, m, depth + 1);
            }
        } else if (type == "Text") {
            const int backup = doc.child(el, "BackupPath");
            if (backup >= 0) {
                ++textPaths;
                pathOf(backup, m);
            } else {
                skip(QStringLiteral("Text"));
            }
        } else {
            skip(type.isEmpty() ? QStringLiteral("Element") : QString::fromUtf8(type.left(40)));
        }
    }
    void shapes(int parent, const Matrix& m) {
        for (int el = doc.node(parent).firstChild; el >= 0; el = doc.node(el).nextSibling) {
            const QByteArrayView tag = doc.node(el).tag;
            if (tag == "Shape") shape(el, m, 0);
            else if (tag != "XForm" && tag != "CutSetting" && tag != "Notes") shapes(el, m);
        }
    }
};

}  // namespace

VectorImport parseLbrn(const QByteArray& bytes) {
    const QByteArray text = decodeText(bytes);
    std::optional<XmlDoc> doc;
    try {
        doc.emplace(text);
    } catch (const XmlError&) {
        throw ImportError(QStringLiteral("Die Datei konnte nicht gelesen werden"));
    }
    const int root = doc->root();
    if (QByteArray(doc->node(root).tag.data(), doc->node(root).tag.size()).toLower() != "lightburnproject")
        throw ImportError(QStringLiteral("Keine LightBurn-Datei"));
    LbCtx ctx{*doc};
    ctx.shapes(root, Matrix{});
    if (ctx.polys.empty() && ctx.images.empty()) {
        QStringList names;
        for (const auto& e : ctx.skipped) names.push_back(e.first);
        const QString what = names.isEmpty() ? QStringLiteral("Keine Formen gefunden") : QStringLiteral("Nur %1 gefunden (nicht lesbar)").arg(names.join(QStringLiteral(", ")));
        throw ImportError(what + QStringLiteral(". In LightBurn Text in Pfade umwandeln (Rechtsklick) und erneut speichern."));
    }
    VectorImport r;
    r.polys = std::move(ctx.polys);
    r.images = std::move(ctx.images);
    for (const auto& [name, n] : ctx.skipped) r.skipped.push_back(QStringLiteral("%1× %2").arg(n).arg(name));
    if (ctx.textPaths) r.notes.push_back(QStringLiteral("Text in Pfade umgewandelt (%1)").arg(ctx.textPaths));
    return r;
}

VectorImport parseVector(FileKind kind, const QByteArray& bytes) {
    switch (kind) {
    case FileKind::Svg: return parseSvg(bytes);
    case FileKind::Dxf: return parseDxf(bytes);
    case FileKind::Xcs: return parseXcs(bytes);
    case FileKind::Xs: return parseXs(bytes);
    case FileKind::Lbrn: return parseLbrn(bytes);
    case FileKind::Hpgl: { VectorImport r; r.polys = parseHpgl(bytes); return r; }
    default: throw ImportError(QStringLiteral("Dieses Format wird nicht als Vektor gelesen"));
    }
}

PolySet VectorImport::allPolys() const {
    if (items.empty()) return polys;
    PolySet out;
    for (const ImportItem& i : items) out.append(i.polys);
    return out;
}
std::optional<QString> VectorImport::skippedSentence() const {
    if (skipped.isEmpty()) return std::nullopt;
    return QStringLiteral("Übersprungen: %1 (in Pfade bzw. Bild umwandeln)").arg(skipped.join(QStringLiteral(", ")));
}

}  // namespace lumacut::import
