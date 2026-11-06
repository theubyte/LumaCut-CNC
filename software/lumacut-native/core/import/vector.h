#pragma once
/**
 * Innenleben des Imports, für die Einleser und ihre Tests. Von außen gilt core/import/import.h.
 * Port von SvgImport.kt, DxfImport.kt, ImportFormats.kt, XTool.kt, ImportLayout.kt und src/core/import/*.ts.
 * Wo sich beide unterscheiden, gilt der neuere Stand; Abweichungen stehen beim Code.
 */
#include "core/model.h"
#include <QByteArray>
#include <QByteArrayView>
#include <QImage>
#include <QString>
#include <QStringList>
#include <atomic>
#include <memory>
#include <optional>
#include <stdexcept>
#include <vector>

namespace lumacut::import {

/** Fehlermeldung für den Bediener, ein Satz. */
class ImportError : public std::runtime_error {
public:
    explicit ImportError(const QString& sentence) : std::runtime_error(sentence.toStdString()), m_sentence(sentence) {}
    QString sentence() const { return m_sentence; }
private:
    QString m_sentence;
};

/** Obergrenze je Datei. Android: 400.000; nativ reicht der Speicher weiter, gegen Bomben bleibt eine Grenze. */
inline constexpr qint64 MAX_POINTS = 20'000'000;

/** Punktebudget über alle Threads eines Imports. Wirft "zu komplex". */
class PointBudget {
public:
    explicit PointBudget(const QString& complaint) : m_complaint(complaint) {}
    void take(qint64 n) {
        if (m_left.fetch_sub(n, std::memory_order_relaxed) < n) throw ImportError(m_complaint);
    }
private:
    QString m_complaint;
    std::atomic<qint64> m_left{MAX_POINTS};
};

struct Matrix {
    double a = 1, b = 0, c = 0, d = 1, e = 0, f = 0;
    Matrix operator*(const Matrix& o) const {
        return {a * o.a + c * o.b, b * o.a + d * o.b, a * o.c + c * o.d, b * o.c + d * o.d, a * o.e + c * o.f + e, b * o.e + d * o.f + f};
    }
    Pt apply(Pt p) const { return {a * p.x + c * p.y + e, b * p.x + d * p.y + f}; }
    /** Mittlerer Maßstab, fürs Abflachen. */
    double scale() const;
};

enum class FileKind { Svg, Dxf, Xcs, Xs, Lbrn, Hpgl, Pdf, Image, Project, Unknown };
QString kindLabel(FileKind kind);
FileKind detectKind(const QByteArray& bytes);

/** Eingebettetes Bild, auf der Fläche platziert (mm). */
struct EmbeddedImage {
    QByteArray bytes;
    Box box;
};
/** Ein Zeichenobjekt: Pfade, Ebene der Quelle (Farbe), Füllung oder Linie, Gruppen (außen zuerst). */
struct ImportItem {
    PolySet polys;
    std::optional<QString> layerKey;
    bool fill = false;
    QStringList groups;
    std::optional<QString> name;
    Box box;    /// von unitsOf gefüllt
};
struct ImportLayerInfo {
    QString key, name;
    int order = 0;
    bool visible = true;
};
/**
 * Vektoren (mm, Y nach unten) plus Bilder. Formate ohne Struktur liefern `polys` und lassen `items` leer,
 * unitsOf macht daraus Teile. `skipped`: was nicht übernommen werden konnte.
 */
struct VectorImport {
    PolySet polys;
    std::vector<EmbeddedImage> images;
    QStringList skipped;
    std::vector<ImportItem> items;
    std::vector<ImportLayerInfo> layers;
    QStringList notes;
    /** Alle Pfade in Reihenfolge. */
    PolySet allPolys() const;
    std::optional<QString> skippedSentence() const;
};

/** Parst ein Vektorformat. Wirft ImportError. */
VectorImport parseVector(FileKind kind, const QByteArray& bytes);

// ---- SVG ----
VectorImport parseSvg(const QByteArray& bytes);
/** Pfaddaten nach Linienzügen (Benutzereinheiten). segment: Sehnenlänge beim Abflachen. Wirft ImportError. */
PolySet pathData(QByteArrayView d, double segment = 0.2, PointBudget* budget = nullptr);
Matrix svgTransform(QByteArrayView s);
/** CSS-Farbe: 0xRRGGBB, COLOUR_NONE oder COLOUR_OTHER (Verlauf, currentColor). */
inline constexpr int COLOUR_NONE = -2, COLOUR_OTHER = -1;
int parseColour(QByteArrayView value, int inherited);
QString colourKey(int rgb);     /// "#rrggbb"
QString colourName(int rgb);    /// nächster Name: "Rot", "Blau", ...
/** Roh-Zeichenobjekte zu Items und Ebenen: Gruppe um alles entfällt, zwei Farben werden Ebenen, Weiß ausgeblendet. */
struct RawDrawable {
    PolySet polys;
    int colour = COLOUR_OTHER;
    bool fill = false;
    QStringList groups;
    std::optional<QString> name;
};
void finishDrawables(std::vector<RawDrawable>& raw, VectorImport& out);

// ---- DXF, HPGL, LightBurn, xTool ----
VectorImport parseDxf(const QByteArray& bytes);
PolySet parseHpgl(const QByteArray& bytes);
VectorImport parseLbrn(const QByteArray& bytes);
VectorImport parseXcs(const QByteArray& bytes);
VectorImport parseXs(const QByteArray& bytes);
bool isXs(const QByteArray& bytes);

// ---- Gemeinsame Geometrie ----
/** Bis zu 20.000 Stützpunkte, auch bei absurden Maßen; leer bei NaN oder Unendlich. */
Poly safeEllipse(double w, double h, double segment = 0.4);
/** Wie Javas Math.ceil(v).toInt().coerceIn(lo, hi), aber sicher bei NaN und Unendlich. */
int clampSteps(double v, int lo, int hi);
/** Dezimalzahl am Anfang (wie parseFloat), sonst fallback. */
double parseFloatOr(QByteArrayView s, double fallback);
/** Standard-Base64, Leerraum erlaubt, data:-Vorspann erlaubt. Leer, wenn kaputt oder zu kurz für eine Datei. */
QByteArray decodeBase64Loose(QByteArrayView text);
/** Bytes nach UTF-8: beachtet BOM und die Kodierung der XML-Deklaration. */
QByteArray decodeText(const QByteArray& bytes);

// ---- Anordnen ----
inline constexpr double LAYOUT_GAP = 5.0;
struct ImportUnit {
    std::vector<uint32_t> items, images;
    Box box;
};
using Units = std::shared_ptr<const std::vector<ImportUnit>>;
enum class FitKind { AsIs, Packed, Partial };
struct Layout {
    FitKind kind = FitKind::AsIs;
    Units units;
    std::vector<std::optional<Pt>> offsets;     /// je Einheit, leer = passt nicht
    int leftOut() const;
};
struct Spread {
    std::vector<Layout> plates;
    int leftOut = 0;
};
/** Bildet die Einheiten; füllt r.items, wenn das Format keine Struktur hat. Leer, wenn nichts da ist. */
Units unitsOf(VectorImport& r);
Box unionOf(const std::vector<ImportUnit>& units);
Layout arrange(const VectorImport& r, const Units& units, std::optional<double> w = {}, std::optional<double> h = {});
Spread spread(const VectorImport& r, const Units& units, std::optional<double> w = {}, std::optional<double> h = {}, int maxPlates = 20);
double shrinkFactor(const std::vector<ImportUnit>& units, std::optional<double> w = {}, std::optional<double> h = {}, double border = 5);
std::vector<std::optional<Pt>> shelf(const std::vector<Box>& boxes, double w, double h, double gap = LAYOUT_GAP);

// ---- Bilder ----
inline constexpr int MAX_RASTER_SIDE = 1600;
inline constexpr double DEFAULT_IMAGE_WIDTH_MM = 80;
/** Auflösung aus der Datei (PNG pHYs, JPEG JFIF), keine Angabe oder Bildschirm-Vorgabe 72/96 = leer. */
std::optional<double> readDpi(const QByteArray& bytes);
/** EXIF-Drehung aus JPEG, PNG oder WebP, 1 = keine. */
int exifOrientation(const QByteArray& bytes);
struct DecodedImage {
    Raster raster;
    int originalWidth = 0, originalHeight = 0;  /// nach der EXIF-Drehung, vor dem Verkleinern
    int frames = 1;
};
/** Dekodiert mit QImage, dreht nach EXIF, Graustufen, längste Seite höchstens maxSide. Wirft ImportError. */
DecodedImage decodeImage(const QByteArray& bytes, int maxSide = MAX_RASTER_SIDE);
/** Durchsichtig zählt als Weiß, Flächenmittel beim Verkleinern. */
Raster rasterFromImage(const QImage& image, int maxSide = MAX_RASTER_SIDE);
struct PdfPage {
    Raster raster;
    double widthMm = 0, heightMm = 0;
    int pages = 1;
};
/** Seite 1 über das Qt-PDF-Bildformat. Wirft ImportError, auch wenn das Modul fehlt. */
PdfPage renderPdf(const QByteArray& bytes);

}  // namespace lumacut::import
