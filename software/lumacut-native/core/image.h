#pragma once
/**
 * Bildwerkzeuge wie android/core ImageTools.kt: Grauwerte 0..255, 0 = schwarz = volle Leistung.
 * Ergebnisse bis aufs Bit gleich Kotlin. Zeilenweise Schritte laufen mehrkernig; die Fehlerdiffusion ist
 * je Bild seriell (float-Summen hängen von der Reihenfolge ab), mehrere Bilder laufen nebeneinander.
 */
#include "core/model.h"
#include <cstdint>
#include <span>
#include <vector>

namespace lumacut {

using GrayView = std::span<const uint8_t>;
using Gray = std::vector<uint8_t>;

/** Unschärfemaske mit 3×3-Box; amount 0..1 (bis zum Doppelten des Details). */
Gray sharpen(GrayView src, int w, int h, double amount);
/** Schärfe, Kontrast, Helligkeit, Invertieren in dieser Reihenfolge. */
Gray adjustGray(GrayView gray, int w, int h, const ImageAdjust& a);
/** Schwarz/Weiß (0/255) durch Schwelle oder Fehlerdiffusion; Grayscale gibt eine Kopie zurück. */
Gray binarize(GrayView src, int w, int h, ImageMode mode);
/** Nächster-Nachbar-Abtastung wie im Raster-Teil von MarlinWriter.kt. */
Gray sampleGray(GrayView gray, int width, int height, int cols, int rows);
/** Abtasten, Anpassen, Binarisieren: das Raster, das der Auftrag brennt. */
Gray jobLevels(const Raster& r, int cols, int rows, const ImageAdjust& a, ImageMode mode);

QByteArray encodeBase64(GrayView bytes);
/** Wirft std::invalid_argument("Ungültige Bilddaten"). */
Gray decodeBase64(QByteArrayView b64);

/** Helligkeit wie Importers.toRaster auf Android: Durchsichtiges zählt als weiß. rgba: 4 Bytes je Pixel. */
Gray grayFromRgba(std::span<const uint8_t> rgba, int w, int h);

struct PreviewOptions {
    ImageMode mode = ImageMode::Grayscale;
    ImageAdjust adjust;
    /** Wie der Auftrag abtasten (Spalten/Zeilen = Maß / Zeilenabstand). 0 = ganzes Bild, höchstens maxPixels. */
    int cols = 0, rows = 0;
    qint64 maxPixels = 4'000'000;
    /** Weiß durchsichtig, Dunkles als Deckkraft: für die Vorschau auf der Arbeitsfläche. */
    bool transparentWhite = false;
};
struct PreviewImage {
    std::vector<uint8_t> rgba;  /// 4 Bytes je Pixel, nicht vormultipliziert
    int width = 0, height = 0;
};
PreviewImage previewRgba(const Raster& r, const PreviewOptions& options = {});

}  // namespace lumacut
