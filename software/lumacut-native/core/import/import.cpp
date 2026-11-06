/** Einstieg: Typ erkennen, einlesen, prüfen, anordnen, Elemente bauen (Port von addImported, EditorViewModel.kt). */
#include "core/import/import.h"
#include "core/import/vector.h"
#include "core/parallel.h"

#include <QFile>
#include <QFileInfo>
#include <QHash>
#include <QSet>
#include <QtConcurrent/QtConcurrentRun>
#include <algorithm>
#include <cmath>
#include <new>

namespace lumacut {
using namespace import;

namespace {

const char* const SUPPORTED = "SVG, DXF, PDF, xTool (.xs, .xcs), LightBurn (.lbrn, .lbrn2), HPGL und Bilder (PNG, JPG, WebP, BMP, GIF)";
/** Weiter draußen als 10 km ist kein Maß, sondern eine kaputte Datei. */
constexpr double MAX_COORD = 1e7;

bool usable(PolyView poly) {
    if (poly.size() < 2) return false;
    for (const Pt& p : poly) if (!(std::fabs(p.x) <= MAX_COORD) || !(std::fabs(p.y) <= MAX_COORD)) return false;
    return true;
}
bool usable(const Box& b) {
    return std::fabs(b.minX) <= MAX_COORD && std::fabs(b.minY) <= MAX_COORD && std::fabs(b.maxX) <= MAX_COORD && std::fabs(b.maxY) <= MAX_COORD && b.width() > 1e-6 && b.height() > 1e-6;
}
PolySet filtered(const PolySet& in, size_t& dropped) {
    PolySet out;
    out.reserve(in.size(), in.pointCount());
    for (PolyView p : in) {
        if (usable(p)) out.add(p);
        else ++dropped;
    }
    return out;
}
/** Entfernt NaN, Unendlich und absurde Werte, bevor sie Anordnung oder G-Code erreichen. Meldet, wie viel es war. */
void sanitize(VectorImport& r, QStringList& warnings) {
    size_t dropped = 0;
    const auto clean = [](const PolySet& s) {
        for (PolyView p : s) if (!usable(p)) return false;
        return true;
    };
    if (!clean(r.polys)) r.polys = filtered(r.polys, dropped);
    std::vector<uint8_t> ok(r.items.size(), 1);
    parallelBlocks(std::ptrdiff_t(r.items.size()), 256, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
        for (std::ptrdiff_t i = a; i < b; ++i) ok[size_t(i)] = clean(r.items[size_t(i)].polys);
    });
    if (std::find(ok.begin(), ok.end(), uint8_t(0)) != ok.end()) {
        std::vector<ImportItem> kept;
        kept.reserve(r.items.size());
        for (size_t i = 0; i < r.items.size(); ++i) {
            if (!ok[i]) r.items[i].polys = filtered(r.items[i].polys, dropped);
            if (!r.items[i].polys.empty()) kept.push_back(std::move(r.items[i]));
        }
        r.items = std::move(kept);
    }
    std::erase_if(r.images, [&](const EmbeddedImage& img) {
        if (usable(img.box)) return false;
        ++dropped;
        return true;
    });
    if (dropped) warnings.push_back(QStringLiteral("%1 Pfade mit ungültigen Koordinaten wurden ausgelassen. Datei prüfen.").arg(dropped));
}

qint64 parseKeyColour(const QString& key, qint64 fallback) {
    if (key.size() == 7 && key[0] == QLatin1Char('#')) {
        bool ok = false;
        const uint v = QStringView(key).sliced(1).toUInt(&ok, 16);
        if (ok) return 0xFF000000LL + v;
    }
    return fallback;
}

const Layer* byName(const std::vector<Layer>& layers, QLatin1StringView name) {
    for (const Layer& l : layers) if (l.name == name) return &l;
    return nullptr;
}

/** Aktive Ebene, wenn beschreibbar, sonst die erste beschreibbare (wie writableLayer). */
QString fallbackLayer(const std::vector<Layer>& layers, const QString& active) {
    for (const Layer& l : layers) if (l.id == active && l.visible && !l.locked) return l.id;
    for (const Layer& l : layers) if (l.visible && !l.locked) return l.id;
    return active.isEmpty() && !layers.empty() ? layers.front().id : active;
}

struct Builder {
    const VectorImport& r;
    const std::vector<std::optional<Raster>>& rasters;
    const ImportContext& ctx;
    QString label;
    FileKind kind;
    std::vector<Layer> known;       /// Projekt plus schon neu angelegte
    ImportResult& out;
    bool merged = false;
    size_t mergedFrom = 0;

    void plate(const Layout& layout, double scale, int plateIndex) {
        const std::vector<ImportUnit>& units = *layout.units;
        const Pt all = unionOf(units).center();
        const Pt center = Work::center();
        const auto mapPt = [&, scale](Pt p, const Pt& o) {
            return scale == 1 ? Pt{p.x + o.x, p.y + o.y} : Pt{center.x + (p.x - all.x) * scale, center.y + (p.y - all.y) * scale};
        };
        std::vector<uint32_t> placed;
        placed.reserve(units.size());
        for (uint32_t u = 0; u < units.size(); ++u) if (layout.offsets[u]) placed.push_back(u);

        // SVG-Farben sagen nichts übers Schneiden: Linien beginnen mit den sanften Markier-Werten.
        const Layer* cutBase = byName(known, kind == FileKind::Svg ? QLatin1StringView("Linie") : QLatin1StringView("Schneiden"));
        if (!cutBase) cutBase = &known.back();
        const Layer* engraveBase = byName(known, QLatin1StringView("Gravieren"));
        if (!engraveBase) engraveBase = &known.front();
        const Layer cutCopy = *cutBase, engraveCopy = *engraveBase;

        // Benutzte Ebenen in der Reihenfolge der Quelle; gleichnamige gibt es schon.
        QHash<QString, const ImportLayerInfo*> info;
        for (const ImportLayerInfo& l : r.layers) info.insert(l.key, &l);
        struct Used { QString key; bool fill; int order; };
        std::vector<Used> used;
        {
            QSet<QString> seen;
            for (const uint32_t u : placed) for (const uint32_t i : units[u].items) {
                const ImportItem& item = r.items[i];
                if (!item.layerKey) continue;
                const QString id = *item.layerKey + (item.fill ? QLatin1String("|1") : QLatin1String("|0"));
                if (seen.contains(id)) continue;
                seen.insert(id);
                const auto it = info.constFind(*item.layerKey);
                used.push_back({*item.layerKey, item.fill, it != info.constEnd() ? (*it)->order : 1000});
            }
        }
        std::stable_sort(used.begin(), used.end(), [](const Used& a, const Used& b) { return a.order < b.order; });
        QHash<QString, QString> layerIds;
        for (const Used& u : used) {
            const auto it = info.constFind(u.key);
            const QString name = (it != info.constEnd() ? (*it)->name : u.key) + (u.fill ? QStringLiteral(" (Füllen)") : QString());
            const auto hit = std::find_if(known.begin(), known.end(), [&](const Layer& l) { return l.name == name; });
            const QString mapKey = u.key + (u.fill ? QLatin1String("|1") : QLatin1String("|0"));
            if (hit != known.end()) { layerIds.insert(mapKey, hit->id); continue; }
            const Layer& base = u.fill ? engraveCopy : cutCopy;
            Layer layer = base;
            layer.id = newId();
            layer.name = name;
            layer.color = parseKeyColour(u.key, base.color);
            layer.mode = u.fill ? LayerMode::Fill : LayerMode::Line;
            layer.visible = it != info.constEnd() ? (*it)->visible : true;
            layerIds.insert(mapKey, layer.id);
            known.push_back(layer);
            out.layers.push_back(std::move(layer));
        }

        // Gruppen: nur, wenn auf dieser Platte mindestens zwei dazugehören.
        QHash<QString, int> groupSize;
        size_t itemCount = 0;
        for (const uint32_t u : placed) {
            itemCount += units[u].items.size();
            for (const uint32_t i : units[u].items) if (!r.items[i].groups.isEmpty()) ++groupSize[r.items[i].groups.first()];
        }
        QHash<QString, QString> groupIds;
        for (auto it = groupSize.constBegin(); it != groupSize.constEnd(); ++it) if (it.value() >= 2) groupIds.insert(it.key(), newId());

        const QString fallback = fallbackLayer(known, ctx.activeLayerId);
        const auto layerIdOf = [&](const ImportItem& item) {
            if (!item.layerKey) return fallback;
            return layerIds.value(*item.layerKey + (item.fill ? QLatin1String("|1") : QLatin1String("|0")), fallback);
        };

        struct Job { uint32_t unit, item; };
        std::vector<Job> jobs;
        jobs.reserve(itemCount);
        for (const uint32_t u : placed) for (const uint32_t i : units[u].items) jobs.push_back({u, i});
        const size_t base = out.elements.size();

        if (ctx.maxElements > 0 && jobs.size() > size_t(ctx.maxElements)) {
            // Zu viele Einzelteile: je Ebene ein Element. Reihenfolge der Datei bleibt innerhalb der Ebene.
            merged = true;
            mergedFrom += jobs.size();
            std::vector<std::pair<QString, std::vector<uint32_t>>> byLayer;
            QHash<QString, size_t> indexOf;
            for (size_t j = 0; j < jobs.size(); ++j) {
                const QString id = layerIdOf(r.items[jobs[j].item]);
                auto it = indexOf.constFind(id);
                if (it == indexOf.constEnd()) {
                    it = indexOf.insert(id, byLayer.size());
                    byLayer.push_back({id, {}});
                }
                byLayer[it.value()].second.push_back(uint32_t(j));
            }
            out.elements.resize(base + byLayer.size());
            parallelFor(std::ptrdiff_t(byLayer.size()), [&](std::ptrdiff_t k) {
                const auto& [layerId, list] = byLayer[size_t(k)];
                size_t polys = 0, points = 0;
                for (const uint32_t j : list) {
                    polys += r.items[jobs[j].item].polys.size();
                    points += r.items[jobs[j].item].polys.pointCount();
                }
                PolySet world;
                world.reserve(polys, points);
                for (const uint32_t j : list) {
                    const Pt o = layout.offsets[jobs[j].unit].value_or(Pt{});
                    for (PolyView poly : r.items[jobs[j].item].polys) {
                        std::span<Pt> d = world.addUninitialized(poly.size());
                        for (size_t i = 0; i < poly.size(); ++i) d[i] = mapPt(poly[i], o);
                    }
                }
                const Box box = boundsOf(world).value_or(Box{});
                for (Pt& p : world.allPoints()) p = {p.x - box.minX, p.y - box.minY};
                Element e = newElement(layerId, label);
                e.transform = Transform{box.minX, box.minY};
                e.paths = std::move(world);
                e.plate = plateIndex;
                out.elements[base + size_t(k)] = std::move(e);
            });
        } else {
            out.elements.resize(base + jobs.size());
            parallelBlocks(std::ptrdiff_t(jobs.size()), 128, [&](std::ptrdiff_t a, std::ptrdiff_t b) {
                for (std::ptrdiff_t j = a; j < b; ++j) {
                    const Job& job = jobs[size_t(j)];
                    const ImportItem& item = r.items[job.item];
                    const Pt o = layout.offsets[job.unit].value_or(Pt{});
                    PolySet world = item.polys;
                    for (Pt& p : world.allPoints()) p = mapPt(p, o);
                    const Box box = boundsOf(world).value_or(Box{});
                    for (Pt& p : world.allPoints()) p = {p.x - box.minX, p.y - box.minY};
                    const bool named = item.name && !item.name->trimmed().isEmpty();
                    Element e = newElement(layerIdOf(item), named ? *item.name : label);
                    e.transform = Transform{box.minX, box.minY};
                    e.paths = std::move(world);
                    if (!item.groups.isEmpty()) {
                        const auto g = groupIds.constFind(item.groups.first());
                        if (g != groupIds.constEnd()) e.groupId = *g;
                    }
                    e.plate = plateIndex;
                    out.elements[base + size_t(j)] = std::move(e);
                }
            });
        }
        for (const uint32_t u : placed) {
            const Pt o = layout.offsets[u].value_or(Pt{});
            for (const uint32_t i : units[u].images) {
                if (i >= rasters.size() || !rasters[i]) continue;
                const Box& b = r.images[i].box;
                const Pt a = mapPt({b.minX, b.minY}, o), c = mapPt({b.maxX, b.maxY}, o);
                Element e = newElement(engraveCopy.id, QStringLiteral("Bild"));
                e.transform = Transform{a.x, a.y};
                e.raster = *rasters[i];
                e.imageWidthMm = c.x - a.x;
                e.imageHeightMm = c.y - a.y;
                e.plate = plateIndex;
                out.elements.push_back(std::move(e));
            }
        }
    }
};

/** Ebenen, auf die der Import aufsetzt; ohne Projekt die Standardebenen, die dann mit herauskommen. */
std::vector<Layer> startLayers(const ImportContext& ctx, ImportResult& out) {
    if (!ctx.layers.empty()) return ctx.layers;
    std::vector<Layer> defaults = Document::defaultLayers();
    out.layers = defaults;
    return defaults;
}

void warnPark(ImportResult& out) {
    int n = 0;
    for (const Element& e : out.elements) if (e.touchesPark()) ++n;
    if (n > 0) out.warnings.push_back(QStringLiteral("%1 Elemente liegen in der %2 und brennen dort nicht. Bitte verschieben.").arg(n).arg(Work::parkName()));
}

void placeVector(FileKind kind, VectorImport r, const ImportContext& ctx, ImportResult& out) {
    QStringList warnings = r.notes;
    sanitize(r, warnings);
    if (const auto s = r.skippedSentence()) warnings.push_back(*s);

    // Eingebettete Bilder zuerst: was sich nicht lesen lässt, zählt auch beim Anordnen nicht mit.
    std::vector<std::optional<Raster>> rasters(r.images.size());
    parallelFor(std::ptrdiff_t(r.images.size()), [&](std::ptrdiff_t i) {
        try {
            rasters[size_t(i)] = decodeImage(r.images[size_t(i)].bytes).raster;
        } catch (const std::exception&) {
            rasters[size_t(i)].reset();
        }
    });
    {
        std::vector<EmbeddedImage> keptImages;
        std::vector<std::optional<Raster>> keptRasters;
        int failed = 0;
        for (size_t i = 0; i < r.images.size(); ++i) {
            if (rasters[i]) { keptImages.push_back(std::move(r.images[i])); keptRasters.push_back(std::move(rasters[i])); }
            else ++failed;
        }
        r.images = std::move(keptImages);
        rasters = std::move(keptRasters);
        if (failed) warnings.push_back(failed == 1 ? QStringLiteral("Ein eingebettetes Bild ließ sich nicht lesen und fehlt.")
                                                   : QStringLiteral("%1 eingebettete Bilder ließen sich nicht lesen und fehlen.").arg(failed));
    }

    const Units units = unitsOf(r);
    if (units->empty()) throw ImportError(QStringLiteral("Nichts Lasertaugliches gefunden."));

    std::vector<Layer> known = startLayers(ctx, out);
    Builder builder{r, rasters, ctx, kindLabel(kind), kind, std::move(known), out};
    const int first = std::max(0, ctx.activePlate);
    const int nextNew = std::max(ctx.plateCount, first + 1);

    const Layout layout = arrange(r, units);
    if (layout.kind == FitKind::AsIs) {
        out.fit = ImportFit::AsIs;
        builder.plate(layout, 1, first);
    } else if (layout.kind == FitKind::Packed) {
        out.fit = ImportFit::Packed;
        warnings.push_back(QStringLiteral("Das Motiv ist größer als die Arbeitsfläche. Die Teile wurden in Originalgröße nebeneinander angeordnet."));
        builder.plate(layout, 1, first);
    } else {
        const Spread sp = spread(r, units);
        const double k = shrinkFactor(*units);
        const int percent = int(k * 100);
        out.partial = {int(layout.units->size()), int(layout.units->size()) - layout.leftOut(), percent, int(sp.plates.size()), sp.leftOut};
        PartialFit choice = ctx.partial;
        if (choice == PartialFit::Auto) choice = sp.plates.size() > 1 && sp.leftOut == 0 ? PartialFit::Plates : PartialFit::Shrink;
        if (choice == PartialFit::Plates && sp.plates.empty()) choice = PartialFit::Shrink;
        if (choice == PartialFit::Plates) {
            out.fit = ImportFit::Plates;
            warnings.push_back(sp.leftOut > 0
                ? QStringLiteral("Die Teile passen nicht auf eine Platte und wurden in Originalgröße auf %1 Platten verteilt. %2 zu große Teile fehlen.").arg(sp.plates.size()).arg(sp.leftOut)
                : QStringLiteral("Die Teile passen nicht auf eine Platte und wurden in Originalgröße auf %1 Platten verteilt.").arg(sp.plates.size()));
            for (size_t i = 0; i < sp.plates.size(); ++i) builder.plate(sp.plates[i], 1, i == 0 ? first : nextNew + int(i) - 1);
            out.addedPlates = int(sp.plates.size()) - 1;
        } else if (choice == PartialFit::OnlyFitting) {
            out.fit = ImportFit::OnlyFitting;
            warnings.push_back(QStringLiteral("In Originalgröße passen %1 von %2 Teilen auf die Platte. Die übrigen fehlen.").arg(out.partial.fitting).arg(out.partial.units));
            builder.plate(layout, 1, first);
        } else {
            out.fit = ImportFit::Shrunk;
            warnings.push_back(QStringLiteral("Das Motiv ist größer als die Arbeitsfläche und wurde auf %1 % verkleinert. Maße prüfen.").arg(percent));
            Layout all{FitKind::AsIs, units, std::vector<std::optional<Pt>>(units->size(), Pt{})};
            builder.plate(all, k, first);
        }
    }
    if (out.elements.empty()) throw ImportError(QStringLiteral("Nichts Lasertaugliches gefunden."));

    if (builder.merged)
        warnings.push_back(QStringLiteral("Die Datei enthält %1 Formen. Sie wurden je Ebene zu einem Element zusammengefasst, damit das Projekt flüssig bleibt.").arg(builder.mergedFrom));
    for (const ImportLayerInfo& l : r.layers) {
        if (l.visible) continue;
        const auto used = std::find_if(out.layers.begin(), out.layers.end(), [&](const Layer& x) { return x.name == l.name || x.name == l.name + QStringLiteral(" (Füllen)"); });
        if (used == out.layers.end()) continue;
        warnings.push_back(l.key == QLatin1String("#ffffff")
            ? QStringLiteral("Weiß gilt als Hintergrund: die Ebene „%1“ ist ausgeblendet und brennt nicht.").arg(l.name)
            : QStringLiteral("Die Ebene „%1“ ist in der Datei ausgeblendet und brennt nicht.").arg(l.name));
    }
    out.warnings = warnings;
    warnPark(out);
}

void placedImage(const Raster& raster, double widthMm, double heightMm, const ImportContext& ctx, ImportResult& out) {
    double w = widthMm, h = heightMm;
    const double k = std::min({1.0, (Work::width() - 10) / w, (Work::usableHeight() - 10) / h});
    if (k < 1) out.warnings.push_back(QStringLiteral("Das Bild ist größer als die Arbeitsfläche und wurde auf %1 % verkleinert.").arg(int(k * 100)));
    w *= k;
    h *= k;
    const std::vector<Layer> layers = startLayers(ctx, out);
    const Layer* engrave = byName(layers, QLatin1StringView("Gravieren"));
    Element e = newElement(engrave ? engrave->id : layers.front().id, QStringLiteral("Bild"));
    const Pt c = Work::center();
    e.transform = Transform{c.x - w / 2, c.y - h / 2};
    e.raster = raster;
    e.imageWidthMm = w;
    e.imageHeightMm = h;
    e.plate = std::max(0, ctx.activePlate);
    out.elements.push_back(std::move(e));
    out.fit = ImportFit::Image;
    warnPark(out);
}

void importImage(const QByteArray& bytes, const ImportContext& ctx, ImportResult& out) {
    const DecodedImage img = decodeImage(bytes);
    const std::optional<double> dpi = readDpi(bytes);
    const double width = dpi ? img.originalWidth / *dpi * 25.4 : DEFAULT_IMAGE_WIDTH_MM;
    if (img.raster.width() != img.originalWidth)
        out.warnings.push_back(QStringLiteral("Das Bild wurde von %1 auf %2 Pixel Breite verkleinert.").arg(img.originalWidth).arg(img.raster.width()));
    if (img.frames > 1) out.warnings.push_back(QStringLiteral("Die Datei enthält %1 Bilder, übernommen wurde das erste.").arg(img.frames));
    placedImage(img.raster, width, width * img.originalHeight / img.originalWidth, ctx, out);    // Seitenverhältnis des Originals, nicht des gerundeten Rasters
}

void importPdf(const QByteArray& bytes, const ImportContext& ctx, ImportResult& out) {
    const PdfPage page = renderPdf(bytes);
    if (page.pages > 1) out.warnings.push_back(QStringLiteral("Von %1 Seiten wurde nur Seite 1 übernommen.").arg(page.pages));
    out.warnings.push_back(QStringLiteral("Das PDF wurde als Bild übernommen, Vektoren werden noch nicht gelesen. Zum Schneiden die Datei als SVG oder DXF speichern."));
    placedImage(page.raster, page.widthMm, page.heightMm, ctx, out);
}

/** Kein Inhalt erkannt: die Endung darf entscheiden, dann sagt der Einleser genauer, was fehlt. */
FileKind kindFromName(const QString& name) {
    const QString ext = QFileInfo(name).suffix().toLower();
    if (ext == QLatin1String("svg")) return FileKind::Svg;
    if (ext == QLatin1String("dxf")) return FileKind::Dxf;
    if (ext == QLatin1String("hpgl") || ext == QLatin1String("plt")) return FileKind::Hpgl;
    if (ext == QLatin1String("lbrn") || ext == QLatin1String("lbrn2")) return FileKind::Lbrn;
    if (ext == QLatin1String("xs")) return FileKind::Xs;
    if (ext == QLatin1String("xcs")) return FileKind::Xcs;
    return FileKind::Unknown;
}

void run(const QString& name, const QByteArray& bytes, const ImportContext& ctx, ImportResult& out) {
    if (bytes.isEmpty()) throw ImportError(QStringLiteral("Die Datei ist leer oder lässt sich nicht lesen."));
    FileKind kind = detectKind(bytes);
    if (kind == FileKind::Unknown) kind = kindFromName(name);
    out.kind = kindLabel(kind);
    switch (kind) {
    case FileKind::Image: importImage(bytes, ctx, out); break;
    case FileKind::Pdf: importPdf(bytes, ctx, out); break;
    case FileKind::Project: throw ImportError(QStringLiteral("Das ist ein LumaCut-Projekt. Bitte über „Projekt öffnen“ laden."));
    case FileKind::Unknown: throw ImportError(QStringLiteral("Dieses Format kenne ich nicht. Unterstützt: %1.").arg(QString::fromUtf8(SUPPORTED)));
    default: placeVector(kind, parseVector(kind, bytes), ctx, out);
    }
}

}  // namespace

ImportContext importContextFor(const Document& doc, const QString& activeLayerId) {
    ImportContext c;
    c.layers = doc.layers;
    c.activeLayerId = activeLayerId;
    c.activePlate = doc.activePlate;
    c.plateCount = doc.plateCount;
    return c;
}

ImportResult importFile(const QString& name, const QByteArray& bytes, const ImportContext& ctx) {
    ImportResult out;
    const auto failed = [&](const QString& sentence) {
        const QString kind = out.kind;
        out = ImportResult{};
        out.kind = kind;
        out.error = sentence;
    };
    try {
        run(name, bytes, ctx, out);
    } catch (const ImportError& e) {
        failed(e.sentence());
    } catch (const std::bad_alloc&) {
        failed(QStringLiteral("Die Datei ist zu groß für den freien Speicher."));
    } catch (const std::length_error&) {
        failed(QStringLiteral("Die Datei ist zu groß für den freien Speicher."));
    } catch (const std::exception&) {
        failed(QStringLiteral("Die Datei konnte nicht gelesen werden."));
    }
    return out;
}

ImportResult importPath(const QString& path, const ImportContext& ctx) {
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        ImportResult r;
        r.error = QStringLiteral("Die Datei ist leer oder lässt sich nicht lesen.");
        return r;
    }
    return importFile(QFileInfo(path).fileName(), f.readAll(), ctx);
}

QFuture<ImportResult> importFileAsync(const QString& name, const QByteArray& bytes, const ImportContext& ctx) {
    return QtConcurrent::run([name, bytes, ctx] { return importFile(name, bytes, ctx); });
}

Document applyImport(const Document& doc, const ImportResult& r) {
    Document d = doc;
    const auto afterEngrave = [&] {
        for (size_t i = 0; i < d.layers.size(); ++i) if (d.layers[i].name == QLatin1String("Gravieren")) return i + 1;
        return size_t(0);
    };
    if (d.layers.empty()) {
        d.layers = r.layers;
    } else {
        size_t insertAt = afterEngrave();
        for (const Layer& l : r.layers) if (l.mode == LayerMode::Fill) d.layers.insert(d.layers.begin() + std::ptrdiff_t(insertAt++), l);
        for (const Layer& l : r.layers) if (l.mode != LayerMode::Fill) d.layers.push_back(l);
    }
    d.plateCount = std::max(d.plateCount, d.activePlate + 1) + r.addedPlates;
    d.elements.reserve(d.elements.size() + r.elements.size());
    d.elements.insert(d.elements.end(), r.elements.begin(), r.elements.end());
    return d;
}

QStringList importExtensions() {
    return {QStringLiteral("svg"), QStringLiteral("dxf"), QStringLiteral("pdf"), QStringLiteral("ai"), QStringLiteral("png"), QStringLiteral("jpg"), QStringLiteral("jpeg"),
            QStringLiteral("webp"), QStringLiteral("bmp"), QStringLiteral("gif"), QStringLiteral("lbrn"), QStringLiteral("lbrn2"), QStringLiteral("xs"), QStringLiteral("xcs"),
            QStringLiteral("hpgl"), QStringLiteral("plt")};
}

QStringList importFilters() {
    QStringList all;
    for (const QString& e : importExtensions()) all.push_back(QStringLiteral("*.") + e);
    return {QStringLiteral("Alle Motive (%1)").arg(all.join(QLatin1Char(' '))),
            QStringLiteral("Vektor (*.svg *.dxf *.hpgl *.plt)"),
            QStringLiteral("xTool (*.xs *.xcs)"),
            QStringLiteral("LightBurn (*.lbrn *.lbrn2)"),
            QStringLiteral("Bilder (*.png *.jpg *.jpeg *.webp *.bmp *.gif)"),
            QStringLiteral("PDF (*.pdf *.ai)")};
}

}  // namespace lumacut
