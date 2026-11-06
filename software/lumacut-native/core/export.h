#pragma once
/**
 * Export einer Platte in echten Millimetern. SVG behält Ebenen und Bilder, DXF hat nur Linien, PNG ist ein Bild der
 * Platte mit eingetragener Auflösung. Ausgeblendete Ebenen fehlen; was verloren geht, sagt exportWarnings.
 * Threadsicher, große Projekte laufen mehrkernig.
 */
#include "core/image.h"
#include "core/model.h"
#include <QByteArray>
#include <QStringList>
#include <optional>

namespace lumacut {

enum class ExportFormat { Svg, Dxf, Png };

/** plate leer = aktive Platte. */
QByteArray exportSvg(const Document& doc, std::optional<int> plate = std::nullopt);
/** ASCII-DXF (R12, $INSUNITS = mm), Y nach oben. Bilder fehlen, siehe exportWarnings. */
QByteArray exportDxf(const Document& doc, std::optional<int> plate = std::nullopt);
/** Die ganze Platte, pxPerMm Pixel je mm, Auflösung in der Datei. */
QByteArray exportPng(const Document& doc, std::optional<int> plate = std::nullopt, double pxPerMm = 10);
QStringList exportWarnings(const Document& doc, ExportFormat format, std::optional<int> plate = std::nullopt);
QByteArray encodeGrayPng(GrayView gray, int w, int h);

}  // namespace lumacut
