/**
 * xTool Studio (.xs, ZIP aus JSON) und Creative Space (.xcs, JSON) wie XTool.kt. Ihre Zeichenobjekte sehen gleich aus und
 * werden mit den Transformationen des Editors (PixiJS) platziert: lokale Scherung, Umriss auf 0/0, dann Maßstab, Scherung,
 * Drehung, dann (x, y). Die Objekte laufen mehrkernig, die Reihenfolge bleibt.
 */
#include "core/geometry.h"
#include "core/import/vector.h"
#include "core/import/zip.h"
#include "core/parallel.h"

#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QHash>
#include <QSet>
#include <algorithm>
#include <cmath>
#include <map>

namespace lumacut::import {
namespace {

constexpr double PI = 3.14159265358979323846;
constexpr int MAX_JSON_DEPTH = 256;

std::optional<double> num(const QJsonObject& o, QLatin1StringView k) {
    const QJsonValue v = o.value(k);
    if (v.isDouble()) return v.toDouble();
    if (v.isString()) {
        const QByteArray s = v.toString().toUtf8();
        const double d = parseFloatOr(s, std::nan(""));
        if (!std::isnan(d)) return d;
    }
    return std::nullopt;
}
std::optional<QString> str(const QJsonObject& o, QLatin1StringView k) {
    const QJsonValue v = o.value(k);
    if (v.isString()) return v.toString();
    if (v.isDouble()) return QString::number(v.toDouble());
    if (v.isBool()) return v.toBool() ? QStringLiteral("true") : QStringLiteral("false");
    return std::nullopt;
}
std::pair<double, double> pairOf(const QJsonObject& o, QLatin1StringView k, double dx, double dy) {
    const QJsonValue s = o.value(k);
    if (!s.isObject()) return {dx, dy};
    const QJsonObject so = s.toObject();
    return {num(so, QLatin1StringView("x")).value_or(dx), num(so, QLatin1StringView("y")).value_or(dy)};
}

using L = QLatin1StringView;

/** Lokaler Umriss zur Fläche (mm, Y unten). Mit skew.x und localSkew.x gleich π heben sich die Spiegelungen auf, (x, y) ist die Unterkante. */
PolySet toPlane(const PolySet& local, const QJsonObject& o) {
    const auto [lkx, lky] = pairOf(o, L("localSkew"), 0, 0);
    const Matrix lm{std::cos(lky), std::sin(lky), -std::sin(-lkx), std::cos(-lkx), 0, 0};
    PolySet flat = local;
    for (Pt& q : flat.allPoints()) q = lm.apply(q);
    const std::optional<Box> b = boundsOf(flat);
    if (!b) return {};
    const double r = num(o, L("angle")).value_or(0) * PI / 180;
    const auto [kx, ky] = pairOf(o, L("skew"), 0, 0);
    const auto [sx, sy] = pairOf(o, L("scale"), 1, 1);
    const Matrix dm{std::cos(r + ky) * sx, std::sin(r + ky) * sx, -std::sin(r - kx) * sy, std::cos(r - kx) * sy, 0, 0};
    const double x = num(o, L("x")).value_or(0), y = num(o, L("y")).value_or(0);
    for (Pt& q : flat.allPoints()) {
        const Pt m = dm.apply({q.x - b->minX, q.y - b->minY});
        q = {m.x + x, m.y + y};
    }
    return flat;
}

std::vector<ImportLayerInfo> layerInfos(const QJsonValue& data) {
    std::vector<ImportLayerInfo> out;
    if (!data.isObject()) return out;
    const QJsonObject o = data.toObject();
    for (auto it = o.begin(); it != o.end(); ++it) {
        if (!it.value().isObject()) continue;
        const QJsonObject v = it.value().toObject();
        const QJsonValue vis = v.value(L("visible"));
        const double order = num(v, L("order")).value_or(0);
        out.push_back({it.key(), str(v, L("name")).value_or(it.key()), order >= -2e9 && order <= 2e9 ? int(order) : 0, vis.isBool() ? vis.toBool() : true});
    }
    std::stable_sort(out.begin(), out.end(), [](const ImportLayerInfo& a, const ImportLayerInfo& b) { return a.order < b.order; });
    return out;
}

QString typeLabel(const QString& t) {
    return t.isEmpty() ? t : t.left(1).toUpper() + t.mid(1).toLower();
}

struct Parsed {
    enum { Hidden, Skip, Item, Image } what = Hidden;
    QString type;
    PolySet polys;
    QString layerKey;
    bool fill = false;
    QStringList groups;
    std::optional<QString> name;
    EmbeddedImage image;
};

Parsed readDisplay(const QJsonObject& o, const QHash<QString, QByteArray>& resources, PointBudget& budget) {
    Parsed out;
    out.type = str(o, L("type")).value_or(QStringLiteral("?")).toUpper();
    const QJsonValue vis = o.value(L("visible")), visState = o.value(L("visibleState"));
    if ((vis.isBool() && !vis.toBool()) || (visState.isBool() && !visState.toBool())) return out;
    out.what = Parsed::Skip;
    const double w = num(o, L("width")).value_or(0), h = num(o, L("height")).value_or(0);
    const auto [sx, sy] = pairOf(o, L("scale"), 1, 1);
    const double lw = sx != 0 ? w / std::fabs(sx) : w, lh = sy != 0 ? h / std::fabs(sy) : h;
    if (out.type == QLatin1String("BITMAP") || out.type == QLatin1String("IMAGE")) {
        QByteArray bytes;
        static const char* const keys[] = {"base64", "src", "data", "image", "url", "resource", "resourcePath", "path"};
        for (const char* k : keys) {
            const std::optional<QString> v = str(o, QLatin1StringView(k));
            if (!v || v->isEmpty()) continue;
            if (const auto it = resources.constFind(*v); it != resources.constEnd()) bytes = *it;
            else if (const auto it2 = resources.constFind(QStringLiteral("resources/") + *v); it2 != resources.constEnd()) bytes = *it2;
            else if (v->size() > 64) bytes = decodeBase64Loose(v->toLatin1());
            if (!bytes.isEmpty()) break;
        }
        if (bytes.isEmpty() || !(lw > 0) || !(lh > 0)) return out;
        PolySet outline;
        outline.add({{0, 0}, {lw, 0}, {lw, lh}, {0, lh}, {0, 0}});
        const std::optional<Box> box = boundsOf(toPlane(outline, o));
        if (!box) return out;
        out.what = Parsed::Image;
        out.image = {bytes, *box};
        return out;
    }
    PolySet local;
    const std::optional<QString> d = str(o, L("dPath"));
    bool haveLocal = false;
    if (d && !d->trimmed().isEmpty()) {
        try {
            const QByteArray u = d->toUtf8();
            const double k = std::max(std::fabs(sx), std::fabs(sy));
            local = pathData(u, k > 1 ? 0.2 / k : 0.2, &budget);
            haveLocal = true;
        } catch (const ImportError&) {
        }
    } else if (out.type == QLatin1String("RECT") && lw > 0 && lh > 0) {
        local.add(PolyView(Shapes::rect(lw, lh, num(o, L("radius")).value_or(num(o, L("rx")).value_or(0)))));
        haveLocal = true;
    } else if ((out.type == QLatin1String("CIRCLE") || out.type == QLatin1String("ELLIPSE")) && lw > 0 && lh > 0) {
        const Poly e = safeEllipse(lw, lh);
        if (!e.empty()) { local.add(PolyView(e)); haveLocal = true; }
    }
    if (!haveLocal || local.empty()) return out;
    if (!d || d->trimmed().isEmpty()) budget.take(qint64(local.pointCount()));
    PolySet polys = toPlane(local, o);
    if (polys.empty()) return out;
    out.what = Parsed::Item;
    out.polys = std::move(polys);
    out.layerKey = str(o, L("layerTag")).value_or(str(o, L("layerColor")).value_or(str(o, L("originColor")).value_or(QStringLiteral("#000000"))));
    const QJsonValue fill = o.value(L("fill"));
    out.fill = fill.isObject() && fill.toObject().value(L("visible")).toBool(false);
    const QJsonValue tags = o.value(L("groupTags"));
    if (tags.isArray()) {
        const QJsonArray arr = tags.toArray();
        for (qsizetype i = arr.size() - 1; i >= 0; --i) if (arr[i].isString()) out.groups.push_back(arr[i].toString());
    }
    out.name = str(o, L("name"));
    return out;
}

VectorImport read(const std::vector<QJsonObject>& displays, const std::vector<ImportLayerInfo>& layers, const QHash<QString, QByteArray>& resources) {
    PointBudget budget(QStringLiteral("Die xTool-Datei ist zu komplex"));
    std::vector<Parsed> parsed(displays.size());
    parallelBlocks(std::ptrdiff_t(displays.size()), 32, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) parsed[size_t(i)] = readDisplay(displays[size_t(i)], resources, budget);
    });
    VectorImport r;
    std::vector<std::pair<QString, int>> skipped;
    std::vector<QString> used;
    QSet<QString> usedSet;
    for (Parsed& p : parsed) {
        if (p.what == Parsed::Hidden) continue;
        if (p.what == Parsed::Skip) {
            const QString k = typeLabel(p.type);
            bool found = false;
            for (auto& e : skipped) if (e.first == k) { ++e.second; found = true; break; }
            if (!found) skipped.push_back({k, 1});
        } else if (p.what == Parsed::Image) {
            r.images.push_back(std::move(p.image));
        } else {
            if (!usedSet.contains(p.layerKey)) { usedSet.insert(p.layerKey); used.push_back(p.layerKey); }
            ImportItem it;
            it.polys = std::move(p.polys);
            it.layerKey = p.layerKey;
            it.fill = p.fill;
            it.groups = std::move(p.groups);
            it.name = std::move(p.name);
            r.items.push_back(std::move(it));
        }
    }
    for (size_t i = 0; i < used.size(); ++i) {
        const auto known = std::find_if(layers.begin(), layers.end(), [&](const ImportLayerInfo& l) { return l.key == used[i]; });
        r.layers.push_back(known != layers.end() ? *known : ImportLayerInfo{used[i], used[i], 1000 + int(i), true});
    }
    std::stable_sort(r.layers.begin(), r.layers.end(), [](const ImportLayerInfo& a, const ImportLayerInfo& b) { return a.order < b.order; });
    for (const auto& [k, n] : skipped) r.skipped.push_back(QStringLiteral("%1× %2").arg(n).arg(k));
    return r;
}

[[noreturn]] void fail(const VectorImport& r) {
    const QString what = r.skipped.isEmpty() ? QStringLiteral("Keine Formen gefunden") : QStringLiteral("Nur %1 gefunden (nicht lesbar)").arg(r.skipped.join(QStringLiteral(", ")));
    throw ImportError(what + QStringLiteral(". In xTool Text in Pfade umwandeln und erneut speichern."));
}

void visit(const QJsonValue& e, std::vector<QJsonObject>& displays, QJsonValue& layerData, int depth) {
    if (depth > MAX_JSON_DEPTH) return;
    if (e.isArray()) {
        const QJsonArray a = e.toArray();
        for (const QJsonValue v : a) visit(v, displays, layerData, depth + 1);
        return;
    }
    if (!e.isObject()) return;
    const QJsonObject o = e.toObject();
    if (layerData.isUndefined() && o.value(L("layerData")).isObject()) layerData = o.value(L("layerData"));
    const bool isDisplay = str(o, L("type")).has_value() && (o.contains(L("width")) || o.contains(L("dPath")));
    if (isDisplay) { displays.push_back(o); return; }
    for (auto it = o.begin(); it != o.end(); ++it) visit(it.value(), displays, layerData, depth + 1);
}

QByteArrayView skipBom(const QByteArray& b) {
    QByteArrayView v = b;
    if (v.size() >= 3 && uint8_t(v[0]) == 0xEF && uint8_t(v[1]) == 0xBB && uint8_t(v[2]) == 0xBF) return v.sliced(3);
    return v;
}
QJsonDocument parseJson(const QByteArray& b, bool& ok) {
    QJsonParseError err;
    const QByteArrayView v = skipBom(b);
    QJsonDocument doc = QJsonDocument::fromJson(QByteArray::fromRawData(v.data(), v.size()), &err);
    ok = err.error == QJsonParseError::NoError;
    return doc;
}

}  // namespace

VectorImport parseXcs(const QByteArray& bytes) {
    bool ok = false;
    const QJsonDocument doc = parseJson(bytes, ok);
    if (!ok) throw ImportError(QStringLiteral("Keine gültige xTool-Datei"));
    std::vector<QJsonObject> displays;
    QJsonValue layerData(QJsonValue::Undefined);
    visit(doc.isArray() ? QJsonValue(doc.array()) : QJsonValue(doc.object()), displays, layerData, 0);
    VectorImport r = read(displays, layerInfos(layerData), {});
    if (r.items.empty() && r.images.empty()) fail(r);
    return r;
}

bool isXs(const QByteArray& bytes) {
    if (!isZip(bytes)) return false;
    try {
        const QStringList names = zipNames(bytes);
        if (!names.contains(QStringLiteral("project.json"))) return false;
        return std::any_of(names.begin(), names.end(), [](const QString& n) { return n.startsWith(QStringLiteral("canvases/")); });
    } catch (const ImportError&) {
        return false;
    }
}

VectorImport parseXs(const QByteArray& bytes) {
    QHash<QString, QByteArray> files;
    try {
        files = readZip(bytes);
    } catch (const ImportError& e) {
        if (e.sentence().contains(QStringLiteral("zu groß"))) throw;
        throw ImportError(QStringLiteral("Keine gültige xTool-Studio-Datei"));
    }
    const auto obj = [&](const QString& name) -> std::optional<QJsonObject> {
        const auto it = files.constFind(name);
        if (it == files.constEnd()) return std::nullopt;
        bool ok = false;
        const QJsonDocument d = parseJson(*it, ok);
        if (!ok || !d.isObject()) return std::nullopt;
        return d.object();
    };
    const std::optional<QJsonObject> project = obj(QStringLiteral("project.json"));
    if (!project) throw ImportError(QStringLiteral("Keine gültige xTool-Studio-Datei (project.json fehlt)"));
    QStringList canvases;
    const QJsonValue modules = project->value(L("modules"));
    if (modules.isObject()) {
        const QJsonValue c = modules.toObject().value(L("canvases"));
        if (c.isArray()) for (const QJsonValue v : c.toArray()) if (v.isString()) canvases.push_back(v.toString());
    }
    QString active = str(*project, L("activeCanvasId")).value_or(canvases.isEmpty() ? QString() : canvases.first());
    if (active.isEmpty()) throw ImportError(QStringLiteral("Die xTool-Datei enthält keine Zeichenfläche"));
    const std::optional<QJsonObject> canvas = obj(QStringLiteral("canvases/%1.json").arg(active));
    const QString prefix = QStringLiteral("canvases/%1/displays-").arg(active);
    std::map<qint64, QString> chunks;
    for (auto it = files.constBegin(); it != files.constEnd(); ++it) {
        const QString& n = it.key();
        if (!n.startsWith(prefix) || !n.endsWith(QStringLiteral(".json"))) continue;
        bool ok = false;
        const qint64 index = QStringView(n).sliced(prefix.size(), n.size() - prefix.size() - 5).toLongLong(&ok);
        if (ok) chunks[index] = n;
    }
    std::vector<QJsonObject> displays;
    for (const auto& [index, name] : chunks) {
        const std::optional<QJsonObject> chunk = obj(name);
        if (!chunk) continue;
        const QJsonValue d = chunk->value(L("displays"));
        if (d.isArray()) for (const QJsonValue v : d.toArray()) if (v.isObject()) displays.push_back(v.toObject());
    }
    VectorImport r = read(displays, canvas ? layerInfos(canvas->value(L("layerData"))) : std::vector<ImportLayerInfo>{}, files);
    if (r.items.empty() && r.images.empty()) fail(r);
    return r;
}

}  // namespace lumacut::import
