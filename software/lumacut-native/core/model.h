#pragma once
/**
 * Projektmodell. JSON kompatibel zu Androids `Document` (android/core Design.kt, Geometry.kt) in beide
 * Richtungen: gleiche Feldnamen, gleiche Reihenfolge, unbekannte Felder bleiben erhalten (`extra`).
 * Punkte liegen in zusammenhängendem Speicher (PolySet), Bilder werden nur einmal dekodiert (Raster).
 * Alle Koordinaten in Arbeitsflächen-mm: Ursprung oben links von der Tür gesehen, Maschine x = Breite - x.
 */
#include <QByteArray>
#include <QJsonObject>
#include <QString>
#include <cstdint>
#include <initializer_list>
#include <memory>
#include <optional>
#include <set>
#include <span>
#include <stdexcept>
#include <vector>

namespace lumacut {

struct Pt {
    double x = 0, y = 0;
    bool operator==(const Pt&) const = default;
};
using Poly = std::vector<Pt>;
using PolyView = std::span<const Pt>;

struct Box {
    double minX = 0, minY = 0, maxX = 0, maxY = 0;
    double width() const { return maxX - minX; }
    double height() const { return maxY - minY; }
    Pt center() const { return {(minX + maxX) / 2, (minY + maxY) / 2}; }
    Box united(const Box& o) const;
    bool contains(Pt p) const { return p.x >= minX && p.x <= maxX && p.y >= minY && p.y <= maxY; }
    bool operator==(const Box&) const = default;
};

/** Javas Math.hypot (fdlibm), bitgleich: `std::hypot` kippt sonst Gleichstände in der Pfadreihenfolge. */
double hypotJ(double x, double y);
inline double dist(Pt a, Pt b) { return hypotJ(a.x - b.x, a.y - b.y); }

/**
 * Viele Linienzüge in einem Stück Speicher. Index liefert eine Sicht, gültig bis zur nächsten Änderung.
 * Geschlossene Formen wiederholen den ersten Punkt am Ende.
 */
class PolySet {
public:
    PolySet() = default;
    PolySet(std::initializer_list<Poly> polys);
    explicit PolySet(const std::vector<Poly>& polys);

    size_t size() const { return m_starts.size() - 1; }
    bool empty() const { return size() == 0; }
    size_t pointCount() const { return m_points.size(); }
    PolyView operator[](size_t i) const { return {m_points.data() + m_starts[i], m_starts[i + 1] - m_starts[i]}; }
    std::span<Pt> mutablePoly(size_t i) { return {m_points.data() + m_starts[i], m_starts[i + 1] - m_starts[i]}; }
    /** Alle Punkte am Stück, Reihenfolge der Linienzüge. */
    PolyView allPoints() const { return m_points; }
    std::span<Pt> allPoints() { return m_points; }

    void clear();
    void reserve(size_t polys, size_t points);
    void add(PolyView poly);
    void add(std::initializer_list<Pt> poly) { add(PolyView(poly.begin(), poly.size())); }
    void append(const PolySet& other);
    /** Fügt einen Linienzug aus n Punkten an; der Aufrufer füllt die Sicht. */
    std::span<Pt> addUninitialized(size_t n);
    std::vector<Poly> toPolys() const;

    class const_iterator {
    public:
        using value_type = PolyView;
        using difference_type = std::ptrdiff_t;
        const_iterator(const PolySet* s, size_t i) : m_s(s), m_i(i) {}
        PolyView operator*() const { return (*m_s)[m_i]; }
        const_iterator& operator++() { ++m_i; return *this; }
        bool operator!=(const const_iterator& o) const { return m_i != o.m_i; }
        bool operator==(const const_iterator& o) const { return m_i == o.m_i; }
    private:
        const PolySet* m_s;
        size_t m_i;
    };
    const_iterator begin() const { return {this, 0}; }
    const_iterator end() const { return {this, size()}; }

    bool operator==(const PolySet& o) const { return m_points == o.m_points && m_starts == o.m_starts; }

private:
    std::vector<Pt> m_points;
    std::vector<uint32_t> m_starts{0};
};

std::optional<Box> boundsOf(PolyView poly);
std::optional<Box> boundsOf(const PolySet& polys);
bool isClosed(PolyView poly, double eps = 1e-6);
double polyLength(PolyView poly);

/** Liang-Barsky: reicht die Linie ins Innere von b? Berühren von außen zählt nicht. */
bool segmentCrosses(double x0, double y0, double x1, double y1, const Box& b);

/** Maßstab, dann Drehung (Grad, um den Ursprung), dann Verschiebung. */
struct Transform {
    double x = 0, y = 0, scaleX = 1, scaleY = 1, rotation = 0;
    Pt apply(Pt p) const;
    Pt invert(Pt p) const;
    bool operator==(const Transform&) const = default;
};

/**
 * Maschinen-Verfahrweg, wie Androids `Bed`. Kommt vom Pi (config travels, park_corner_mm), Werte außerhalb
 * der Bereiche werden ignoriert. parkX bis 600: der Pi kann mit op=work_band die ganze X-Breite sperren.
 * Ein Vorgabewert je Prozess, threadsicher zu lesen.
 */
namespace Bed {
double width();
double height();
double parkX();
double parkY();
void configure(std::optional<double> w, std::optional<double> h, std::optional<double> px, std::optional<double> py);
bool inPark(double x, double y);                /// Maschinen-mm
bool touchesPark(const Box& machineBox);
bool inWorkArea(double x, double y);            /// Maschinen-mm
bool segmentInPark(double x0, double y0, double x1, double y1);  /// Maschinen-mm
}
/** Kurzform für die App: übernimmt, was der Pi meldet. */
inline void configureBed(std::optional<double> w, std::optional<double> h, std::optional<double> px, std::optional<double> py) {
    Bed::configure(w, h, px, py);
}

/** Die Fläche, wie der Bediener sie sieht. Einzige Umrechnung nach Maschinen-mm. */
namespace Work {
double width();
double height();
Pt toMachine(Pt p);
Pt fromMachine(Pt p);
QString sizeLabel();             /// "370 × 360 mm"
Box park();                      /// Park-Ecke in Arbeits-mm (oben rechts auf dem Schirm)
bool touchesPark(const Box& b);
bool contains(Pt p);
bool contains(const Box& b);
bool bandBlocked();              /// Park-Ecke reicht über die ganze Breite (op=work_band)
QString parkName();              /// "gesperrter Streifen" oder "Park-Ecke"
double usableHeight();
Pt center();                     /// Mitte dessen, was gelasert werden kann
}

/** Grenzen wie Androids `Limits`. */
namespace Limits {
inline constexpr double POWER_MIN = 0, POWER_MAX = 100;
inline constexpr double SPEED_MIN = 1, SPEED_MAX = 30000;
inline constexpr int PASSES_MIN = 1, PASSES_MAX = 30;
inline constexpr double Z_STEP_MIN = 0, Z_STEP_MAX = 2;
inline constexpr double MAX_FOCUS_DROP_MM = 3;
inline constexpr double THICKNESS_MIN = 0, THICKNESS_MAX = 60;
inline constexpr double Z_MAX_MM = 80;
inline constexpr double DEPTH_PER_PASS_MIN = 0, DEPTH_PER_PASS_MAX = 10;
/** Unter etwa 6 % zündet der Laser nicht sicher (STAND.md §4): Untergrenze für brennende Ebenen. */
inline constexpr double MIN_RELIABLE_POWER_PCT = 8;
}

enum class LayerMode { Line, Fill };
enum class ImageMode { Grayscale, Dither, Threshold, DitherJarvis, DitherStucki };

/** Ein Feld der Kamera-Kalibrierung (Pi op=matcal): tone 0 = unberührt, 1 = schwarz. */
struct DarknessPoint {
    double power = 0, speed = 0, tone = 0;
    bool clean = true;
    QJsonObject extra;
};
/** Schwärze-Kurve eines Materials (Pi tone_curve). Rechnen: core/darkness.h. */
struct DarknessCurve {
    std::vector<DarknessPoint> points;
    double minPowerPct = Limits::MIN_RELIABLE_POWER_PCT;
    double intervalMm = 0.1;
    double speedMin = 1500, speedMax = 6000;
    QJsonObject extra;
};

/** Laser-Werte aller Elemente einer Ebene. powerPct in Prozent von S255. */
struct Layer {
    QString id;                 /// neu: newId()
    QString name;
    qint64 color = 0;           /// ARGB wie Kotlin (0xFF4FD8B4)
    LayerMode mode = LayerMode::Line;
    double powerPct = 50, minPowerPct = 0, speed = 1500;
    int passes = 1;
    double intervalMm = 0.1, overscanMm = 2.5, zStepMm = 0;
    bool output = true, visible = true, locked = false;
    std::optional<QString> materialName;
    double thicknessMm = 0, depthPerPassMm = 0;
    std::vector<double> toneCurve;
    std::optional<DarknessCurve> darkness;
    QJsonObject extra;          /// unbekannte Felder

    double focusDropMm() const { return zStepMm * (passes - 1); }
    /** Anteil der Leistung für relative Dunkelheit (0 = weiß, 1 = schwarz) über die Tonkurve. */
    double powerShare(double dark) const;
    /** Name in der Oberfläche: die Standardebene "Linie" heißt "Markieren". */
    QString label() const;
};

/**
 * Graustufenbild: 0 = schwarz = volle Leistung, 255 = weiß = aus. Unveränderlich und billig zu kopieren.
 * Dekodiert höchstens einmal (auch über Kopien und Threads), Base64 entsteht erst beim Speichern.
 */
class Raster {
public:
    Raster() = default;
    static Raster fromBase64(int width, int height, QByteArray grayBase64);
    /** Wirft std::invalid_argument("Ungültige Bilddaten") bei falscher Größe. */
    static Raster ofGray(int width, int height, std::vector<uint8_t> gray);

    explicit operator bool() const { return bool(m_d); }
    int width() const;
    int height() const;
    /** Beim ersten Aufruf dekodiert. Wirft std::invalid_argument bei kaputtem Base64. */
    const std::vector<uint8_t>& gray() const;
    QByteArray grayBase64() const;

private:
    struct Data;
    std::shared_ptr<Data> m_d;
};

/** Korrekturen fürs Fotogravieren, alles 0/false = unverändert. */
struct ImageAdjust {
    int brightness = 0, contrast = 0, sharpen = 0;
    bool invert = false;
    QJsonObject extra;
    bool isDefault() const { return brightness == 0 && contrast == 0 && sharpen == 0 && !invert; }
};

/** Nur Windows, optional: kubischer Knoten für den Pfad-Editor. `paths` bleibt die Wahrheit für die Ausgabe. */
struct CurveNode {
    double x = 0, y = 0;
    std::optional<double> hx1, hy1, hx2, hy2;   /// Griffe absolut: h1 kommt an, h2 geht ab
    bool smooth = false;
    bool hasIn() const { return hx1 && hy1; }
    bool hasOut() const { return hx2 && hy2; }
    Pt handleIn() const { return hasIn() ? Pt{*hx1, *hy1} : Pt{x, y}; }
    Pt handleOut() const { return hasOut() ? Pt{*hx2, *hy2} : Pt{x, y}; }
};
struct CurvePath {
    std::vector<CurveNode> nodes;
    bool closed = false;
};

/**
 * Etwas auf der Arbeitsfläche. Vektorinhalt in `paths` (lokale mm, vor `transform`), Bilder in `raster`
 * über imageWidthMm × imageHeightMm gestreckt. plate = Platte, auf der gelasert wird.
 */
struct Element {
    QString id;
    QString layerId;
    QString kind;
    Transform transform;
    PolySet paths;
    std::optional<QString> text;
    double fontSizeMm = 10;
    bool bold = false;
    QString fontFamily = QStringLiteral("sans-serif");
    Raster raster;
    double imageWidthMm = 0, imageHeightMm = 0;
    ImageMode imageMode = ImageMode::Grayscale;
    ImageAdjust adjust;
    std::optional<QString> groupId;
    int plate = 0;
    std::optional<std::vector<CurvePath>> curves;   /// nur Windows, wird nur geschrieben, wenn gesetzt
    QJsonObject extra;

    bool isImage() const { return bool(raster); }
    PolySet worldPaths() const;
    std::vector<Pt> imageCorners() const;
    std::optional<Box> worldBounds() const;
    /** Brennt in der Park-Ecke: Linie hindurch, geschlossene Form darum, Bild darüber. Die Box allein sagt zu wenig. */
    bool touchesPark() const;
};

/** Ein Projekt. Ebenen gelten für alle Platten. */
struct Document {
    QString title = QStringLiteral("Neues Projekt");
    std::vector<Layer> layers = defaultLayers();
    std::vector<Element> elements;
    int plateCount = 1;
    int activePlate = 0;
    QJsonObject extra;

    const Layer* layer(const QString& id) const;
    std::optional<Box> bounds() const;
    /** Nur die Elemente von Platte i, ohne Angabe der aktiven (was beim Start dieser Platte gelasert wird). */
    Document plateView(std::optional<int> i = std::nullopt) const;
    int plateSize(int i) const;
    Document withPlate(const Document& view) const;
    Document addPlate() const;
    Document removePlate(int i) const;
    Document moveToPlate(const std::set<QString>& ids, int target) const;
    Document withoutEmptyLayers(const std::set<QString>& keep = {}) const;
    std::vector<Layer> shownLayers(const std::set<QString>& keep = {}) const;
    Document deletingLayer(const QString& id) const;
    Document movingLayer(const QString& id, bool up, const std::vector<QString>& shown) const;
    /** Alte oder handbearbeitete Dateien: Platten-Indizes in den gültigen Bereich. */
    Document normalized() const;

    /** Kompakt, Feldreihenfolge wie Kotlin. Ohne unbekannte Felder bis aufs Byte gleich `Document.toJson()`. */
    QByteArray toJson() const;
    /** Wirft JsonError. Unbekannte Felder bleiben erhalten; das Ergebnis ist normalized(). */
    static Document fromJson(QByteArrayView text);

    static std::vector<Layer> defaultLayers();
    static bool isStandardLayer(const QString& name);
    static int passesFor(double depthMm, double depthPerPassMm);
};

class JsonError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

QString newId();
Layer newLayer(const QString& name, qint64 color, LayerMode mode);
Element newElement(const QString& layerId, const QString& kind);

/** Wie Java `%.nf`: HALF_UP auf den kürzesten Dezimalziffern (1.0005 → "1.001"), Vorzeichen bleibt ("-0.000"). */
QByteArray fmtFixed(double v, int digits, char sep = '.');
inline QByteArray fmt3(double v) { return fmtFixed(v, 3); }
/** Schreibt fmtFixed(v, 3) ab out, gibt das Ende zurück. Platz: 340 Bytes bei beliebigem v, 32 bei |v| < 1e9. */
char* fmt3Into(char* out, double v);

}  // namespace lumacut
