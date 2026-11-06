/** Wie src/core/export.ts: eine Platte in mm. Texte der Elemente werden je Element mehrkernig gebaut, dann in Reihenfolge verbunden. */
#include "core/export.h"
#include "core/parallel.h"

#include <QBuffer>
#include <QHash>
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include <QPolygonF>
#include <QTransform>
#include <algorithm>
#include <climits>
#include <cmath>
#include <cstring>

namespace lumacut {
namespace {

constexpr double DEG = 3.14159265358979323846 / 180;

/** Höchstens 3 Nachkommastellen, ohne Nullen am Ende: "1.5", "10", "0". */
inline void appendNum(QByteArray& out, double v) {
    char buf[352];
    char* end = fmt3Into(buf, v);
    char* dot = static_cast<char*>(std::memchr(buf, '.', size_t(end - buf)));
    if (dot) {
        while (end > dot + 1 && end[-1] == '0') --end;
        if (end == dot + 1) end = dot;
    }
    if (end - buf == 2 && buf[0] == '-' && buf[1] == '0') { out += '0'; return; }
    out.append(buf, end - buf);
}
QByteArray num(double v) {
    QByteArray out;
    appendNum(out, v);
    return out;
}
QByteArray esc(const QString& s) {
    return s.toUtf8().replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;");
}
QByteArray layerCss(const Layer& l) {
    return QStringLiteral("#%1").arg(uint(l.color) & 0xFFFFFFu, 6, 16, QLatin1Char('0')).toLatin1();
}

struct Group {
    const Layer* layer;
    std::vector<const Element*> elements;
};
std::vector<Group> visibleByLayer(const Document& doc, int plate) {
    std::vector<Group> out;
    for (const Layer& l : doc.layers) {
        if (!l.visible) continue;
        Group g{&l, {}};
        for (const Element& e : doc.elements) if (e.plate == plate && e.layerId == l.id) g.elements.push_back(&e);
        if (!g.elements.empty()) out.push_back(std::move(g));
    }
    return out;
}

/** fn(element) für alle Elemente aller Gruppen, Ergebnis je Element in Reihenfolge. */
template <class Fn>
std::vector<QByteArray> renderAll(const std::vector<Group>& groups, Fn&& fn) {
    std::vector<std::pair<const Layer*, const Element*>> jobs;
    for (const Group& g : groups) for (const Element* e : g.elements) jobs.push_back({g.layer, e});
    std::vector<QByteArray> parts(jobs.size());
    parallelBlocks(std::ptrdiff_t(jobs.size()), 32, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) parts[size_t(i)] = fn(*jobs[size_t(i)].first, *jobs[size_t(i)].second);
    });
    return parts;
}

QByteArray svgElement(const Element& e) {
    if (e.isImage()) {
        const Transform& t = e.transform;
        const double r = t.rotation * DEG;
        const double m[6] = {t.scaleX * std::cos(r), t.scaleX * std::sin(r), -t.scaleY * std::sin(r), t.scaleY * std::cos(r), t.x, t.y};
        QByteArray out = "<image transform=\"matrix(";
        for (int i = 0; i < 6; ++i) { if (i) out += ' '; appendNum(out, m[i]); }
        out += ")\" width=\"";
        appendNum(out, e.imageWidthMm);
        out += "\" height=\"";
        appendNum(out, e.imageHeightMm);
        out += "\" href=\"data:image/png;base64,";
        out += encodeGrayPng(e.raster.gray(), e.raster.width(), e.raster.height()).toBase64();
        out += "\"/>\n";
        return out;
    }
    const PolySet world = e.worldPaths();
    QByteArray d;
    d.reserve(qsizetype(world.pointCount()) * 14 + 16);
    for (PolyView p : world) {
        if (p.size() < 2) continue;
        const bool closed = isClosed(p);
        const size_t n = closed ? p.size() - 1 : p.size();
        for (size_t i = 0; i < n; ++i) {
            d += i ? 'L' : 'M';
            appendNum(d, p[i].x);
            d += ' ';
            appendNum(d, p[i].y);
        }
        if (closed) d += 'Z';
    }
    if (d.isEmpty()) return {};
    QByteArray out;
    out.reserve(d.size() + 16);
    out += "<path d=\"";
    out += d;
    out += "\"/>\n";
    return out;
}

int aciOf(qint64 argb) {
    static const int table[][4] = {{1, 255, 0, 0}, {2, 255, 255, 0}, {3, 0, 255, 0}, {4, 0, 255, 255}, {5, 0, 0, 255}, {6, 255, 0, 255}, {7, 0, 0, 0}, {8, 128, 128, 128}};
    const int r = int(argb >> 16 & 255), g = int(argb >> 8 & 255), b = int(argb & 255);
    int best = 7, bd = INT_MAX;
    for (const auto& t : table) {
        const int d = (r - t[1]) * (r - t[1]) + (g - t[2]) * (g - t[2]) + (b - t[3]) * (b - t[3]);
        if (d < bd) { bd = d; best = t[0]; }
    }
    return best;
}
QByteArray dxfName(const QString& s) {
    QString t = s;
    t.replace(QChar(0xE4), QStringLiteral("ae")).replace(QChar(0xF6), QStringLiteral("oe")).replace(QChar(0xFC), QStringLiteral("ue"));
    t.replace(QChar(0xC4), QStringLiteral("Ae")).replace(QChar(0xD6), QStringLiteral("Oe")).replace(QChar(0xDC), QStringLiteral("Ue")).replace(QChar(0xDF), QStringLiteral("ss"));
    QByteArray out;
    bool gap = false;
    for (const QChar c : t) {
        const ushort u = c.unicode();
        const bool ok = (u >= 'A' && u <= 'Z') || (u >= 'a' && u <= 'z') || (u >= '0' && u <= '9') || u == '_' || u == '-';
        if (ok) { if (gap) out += '_'; gap = false; out += char(u); }
        else gap = true;
    }
    if (gap) out += '_';
    out.truncate(31);
    return out.isEmpty() ? QByteArray("Ebene") : out;
}
inline void pair(QByteArray& o, int code, QByteArrayView v) {
    o += QByteArray::number(code);
    o += '\n';
    o.append(v.data(), v.size());
    o += '\n';
}

}  // namespace

QByteArray encodeGrayPng(GrayView gray, int w, int h) {
    QImage img(gray.data(), w, h, w, QImage::Format_Grayscale8);
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "PNG");
    return out;
}

QByteArray exportSvg(const Document& doc, std::optional<int> plateIn) {
    const int plate = plateIn.value_or(doc.activePlate);
    const std::vector<Group> groups = visibleByLayer(doc, plate);
    std::vector<QByteArray> parts = renderAll(groups, [](const Layer&, const Element& e) { return svgElement(e); });
    qsizetype total = 512;
    for (const QByteArray& p : parts) total += p.size();
    QByteArray out;
    out.reserve(total + qsizetype(groups.size()) * 128);
    const QByteArray W = num(Bed::width()), H = num(Bed::height());
    out += "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"" + W + "mm\" height=\"" + H + "mm\" viewBox=\"0 0 " + W + " " + H + "\">\n";
    out += "<title>" + esc(doc.title) + "</title>\n";
    size_t k = 0;
    for (const Group& g : groups) {
        const QByteArray c = layerCss(*g.layer);
        out += "<g data-name=\"" + esc(g.layer->name) + "\" ";
        if (g.layer->mode == LayerMode::Fill) out += "fill=\"" + c + "\" fill-rule=\"evenodd\" stroke=\"none\">\n";
        else out += "fill=\"none\" stroke=\"" + c + "\" stroke-width=\"0.1\">\n";
        for (size_t i = 0; i < g.elements.size(); ++i) { out += parts[k]; parts[k] = QByteArray(); ++k; }
        out += "</g>\n";
    }
    out += "</svg>\n";
    return out;
}

QByteArray exportDxf(const Document& doc, std::optional<int> plateIn) {
    const int plate = plateIn.value_or(doc.activePlate);
    const std::vector<Group> groups = visibleByLayer(doc, plate);
    QHash<QString, QByteArray> names;
    QByteArray head;
    pair(head, 0, "SECTION"); pair(head, 2, "HEADER");
    pair(head, 9, "$ACADVER"); pair(head, 1, "AC1009");
    pair(head, 9, "$INSUNITS"); pair(head, 70, "4");
    pair(head, 0, "ENDSEC");
    pair(head, 0, "SECTION"); pair(head, 2, "TABLES");
    pair(head, 0, "TABLE"); pair(head, 2, "LAYER"); pair(head, 70, QByteArray::number(qsizetype(groups.size())));
    QList<QByteArray> taken;
    for (const Group& g : groups) {
        const QByteArray base = dxfName(g.layer->name);
        QByteArray name = base;
        for (int n = 2; taken.contains(name); ++n) name = base + '_' + QByteArray::number(n);
        taken.push_back(name);
        names.insert(g.layer->id, name);
        pair(head, 0, "LAYER"); pair(head, 2, name); pair(head, 70, "0");
        pair(head, 62, QByteArray::number(aciOf(g.layer->color))); pair(head, 6, "CONTINUOUS");
    }
    pair(head, 0, "ENDTAB"); pair(head, 0, "ENDSEC");
    pair(head, 0, "SECTION"); pair(head, 2, "ENTITIES");

    const double bedH = Bed::height();
    std::vector<QByteArray> parts = renderAll(groups, [&](const Layer& l, const Element& e) -> QByteArray {
        if (e.isImage()) return {};
        const QByteArray name = names.value(l.id);
        const PolySet world = e.worldPaths();
        QByteArray o;
        o.reserve(qsizetype(world.pointCount()) * 48);
        for (PolyView p : world) {
            if (p.size() < 2) continue;
            const bool closed = isClosed(p);
            const size_t n = closed ? p.size() - 1 : p.size();
            pair(o, 0, "POLYLINE"); pair(o, 8, name); pair(o, 66, "1"); pair(o, 70, closed ? "1" : "0");
            for (size_t i = 0; i < n; ++i) {
                pair(o, 0, "VERTEX"); pair(o, 8, name);
                o += "10\n"; appendNum(o, p[i].x); o += "\n20\n"; appendNum(o, bedH - p[i].y); o += "\n30\n0\n";
            }
            pair(o, 0, "SEQEND"); pair(o, 8, name);
        }
        return o;
    });
    qsizetype total = head.size() + 64;
    for (const QByteArray& p : parts) total += p.size();
    QByteArray out;
    out.reserve(total);
    out += head;
    for (QByteArray& p : parts) { out += p; p = QByteArray(); }
    pair(out, 0, "ENDSEC");
    pair(out, 0, "EOF");
    return out;
}

QByteArray exportPng(const Document& doc, std::optional<int> plateIn, double pxPerMmIn) {
    const int plate = plateIn.value_or(doc.activePlate);
    const double pxPerMm = std::clamp(pxPerMmIn, 0.5, 40.0);
    QImage img(int(std::ceil(Bed::width() * pxPerMm)), int(std::ceil(Bed::height() * pxPerMm)), QImage::Format_RGB32);
    img.fill(Qt::white);
    img.setDotsPerMeterX(int(std::lround(pxPerMm * 1000)));
    img.setDotsPerMeterY(int(std::lround(pxPerMm * 1000)));
    {
        QPainter painter(&img);
        painter.setRenderHint(QPainter::Antialiasing);
        painter.setRenderHint(QPainter::SmoothPixmapTransform);
        const QTransform world = QTransform::fromScale(pxPerMm, pxPerMm);
        for (const Group& g : visibleByLayer(doc, plate)) {
            const QColor colour = QColor::fromRgb(QRgb(uint(g.layer->color) | 0xFF000000u));
            for (const Element* e : g.elements) {
                if (e->isImage()) {
                    const Transform& t = e->transform;
                    const double r = t.rotation * DEG;
                    const QTransform m(t.scaleX * std::cos(r), t.scaleX * std::sin(r), -t.scaleY * std::sin(r), t.scaleY * std::cos(r), t.x, t.y);
                    painter.setTransform(m * world);
                    const std::vector<uint8_t>& gray = e->raster.gray();
                    const QImage pic(gray.data(), e->raster.width(), e->raster.height(), e->raster.width(), QImage::Format_Grayscale8);
                    painter.drawImage(QRectF(0, 0, e->imageWidthMm, e->imageHeightMm), pic);
                    continue;
                }
                painter.setTransform(world);
                const PolySet paths = e->worldPaths();
                if (g.layer->mode == LayerMode::Fill) {
                    QPainterPath path;
                    path.setFillRule(Qt::OddEvenFill);
                    for (PolyView p : paths) {
                        if (p.size() < 3) continue;     // eine Strecke hat keine Fläche
                        path.moveTo(p[0].x, p[0].y);
                        for (size_t i = 1; i < p.size(); ++i) path.lineTo(p[i].x, p[i].y);
                    }
                    painter.fillPath(path, colour);
                } else {
                    painter.setPen(QPen(colour, std::max(0.1, 1 / pxPerMm), Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
                    painter.setBrush(Qt::NoBrush);
                    QPolygonF line;
                    for (PolyView p : paths) {
                        if (p.size() < 2) continue;
                        line.resize(qsizetype(p.size()));
                        for (size_t i = 0; i < p.size(); ++i) line[qsizetype(i)] = QPointF(p[i].x, p[i].y);
                        painter.drawPolyline(line);
                    }
                }
            }
        }
    }
    QByteArray out;
    QBuffer buf(&out);
    buf.open(QIODevice::WriteOnly);
    img.save(&buf, "PNG");
    return out;
}

QStringList exportWarnings(const Document& doc, ExportFormat format, std::optional<int> plateIn) {
    const int plate = plateIn.value_or(doc.activePlate);
    int pictures = 0, hidden = 0;
    for (const Element& e : doc.elements) {
        if (e.plate != plate) continue;
        if (e.isImage()) ++pictures;
        const Layer* l = doc.layer(e.layerId);
        if (!l || !l->visible) ++hidden;
    }
    QStringList out;
    if (format == ExportFormat::Dxf && pictures)
        out.push_back(pictures > 1 ? QStringLiteral("DXF kennt keine Bilder: %1 Bilder fehlen in der Datei. Für Bilder SVG wählen.").arg(pictures)
                                   : QStringLiteral("DXF kennt keine Bilder: 1 Bild fehlt in der Datei. Für Bilder SVG wählen."));
    if (hidden) out.push_back(QStringLiteral("%1 Elemente auf ausgeblendeten Ebenen wurden nicht exportiert.").arg(hidden));
    return out;
}

}  // namespace lumacut
