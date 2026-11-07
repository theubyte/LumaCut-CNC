#pragma once
/**
 * Kopfkamera und Arbeitsplatz-Scan wie Android (core Scan.kt, Lens.kt, CameraLight.kt): Kalibrierung aus dem Feld
 * `android` von /api/camera/calibration, Kachelplan über das Bett, Mosaik in Arbeitsflächen-mm, Helligkeitsausgleich,
 * entzerrtes Einzelbild für das Live-Bild. Pixel als ARGB32 (0xAARRGGBB, wie QImage::Format_ARGB32). Mehrkernig.
 */
#include "core/model.h"
#include <QJsonObject>
#include <QString>
#include <QStringList>
#include <array>
#include <optional>
#include <vector>

namespace lumacut::Camera {

using Mat3 = std::array<double, 9>;   /// zeilenweise
Pt apply(const Mat3& m, Pt p);
std::optional<Mat3> inverse(const Mat3& m);
/** Homographie aus genau vier Punktpaaren (src → dst). */
std::optional<Mat3> homography(const std::vector<Pt>& src, const std::vector<Pt>& dst);

/** Weitwinkel: Homographie mm → normierte Bildkoordinaten, dann radiale Verzeichnung (OpenCV k1, k2, k3). */
struct Lens {
    double cx = 0, cy = 0, f = 1, k1 = 0, k2 = 0, k3 = 0;
    Mat3 g{1, 0, 0, 0, 1, 0, 0, 0, 1};
    Box valid;
    Pt toPixel(Pt rel) const;
    Pt toRel(Pt px) const;
    double undistortRadius(double rd) const;
};

/** Helligkeitsabfall zum Rand, je Kanal auf grobem Raster (u, v in 0..1). */
struct Shading {
    int cols = 0, rows = 0;
    std::vector<float> gain;   /// cols × rows × 3
    double at(double u, double v, int ch) const;
    uint32_t correct(uint32_t argb, double u, double v) const;
};

struct Calibration {
    int photoWidth = 0, photoHeight = 0;
    double scanZ = 20;
    std::optional<double> aboveSurface;
    std::optional<Lens> lens;
    std::optional<Shading> shading;
    std::vector<Pt> photo, relMm;   /// vier Marken, wenn kein Linsenmodell

    /** Aus dem Android-Modell; nichts, wenn es fehlt oder unbrauchbar ist (`why` sagt warum). */
    static std::optional<Calibration> fromJson(const QJsonObject& android, QString* why = nullptr);
    /** Vier Marken: Fotoecken und dieselben Punkte in mm relativ zum Kopf. */
    static Calibration fromMarks(int w, int h, std::vector<Pt> photo, std::vector<Pt> relMm, double scanZ = 20);

    Box validPx() const;
    Pt pixelToWork(Pt px, Pt head) const;
    Pt workToPixel(Pt work, Pt head) const;
    /** Fläche des Bildes relativ zum Kopf (achsparallel). */
    Box footprint() const;
    /** Größte achsparallele Box ganz im Bild, relativ zum Kopf, um insetFraction verkleinert. */
    Box usable(double insetFraction = 0.08) const;

private:
    Mat3 m_toRel{}, m_toPhoto{};
    std::vector<Pt> m_outline;
    void prepare();
};

struct TilePlan {
    std::vector<Pt> heads;     /// Arbeitsflächen-mm, Schlangenlinie
    QStringList uncovered;     /// Ränder, die die Kamera nicht erreicht
};
/** Kopfpositionen, damit der nutzbare Bildteil `area` mit `overlap` überdeckt. Wirft std::invalid_argument. */
TilePlan plan(const Calibration& cal, Box area, double overlap = 0.25);

/** Mosaik der Arbeitsfläche, Kachel für Kachel; Zeile 0 = Arbeits-Y 0, unbedeckt = durchsichtig. */
class Mosaic {
public:
    Mosaic(const Calibration& cal, double pxPerMm, const std::vector<uint32_t>* base = nullptr);
    int width() const { return m_w; }
    int height() const { return m_h; }
    double pxPerMm() const { return m_ppm; }
    const std::vector<uint32_t>& pixels() const { return m_px; }
    /** Ein Foto in Kalibriergröße (photoWidth × photoHeight), aufgenommen mit dem Kopf bei head. */
    void add(const uint32_t* argb, int w, int h, Pt head);
    std::array<double, 3> lastGain() const { return m_gain; }
private:
    Calibration m_cal;
    double m_ppm;
    int m_w, m_h;
    std::vector<uint32_t> m_px;
    std::vector<float> m_weight;
    std::array<double, 3> m_gain{1, 1, 1};
};

/** Auflösung des Mosaiks wie Android: 0,8 × die der Kamera, 2 bis 5 px/mm. */
double mosaicResolution(const Calibration& cal);
/** Gleichmäßiger Hintergrund: langsame Helligkeitsänderungen über das Bett gehen, Marken bleiben. */
std::vector<uint32_t> level(const std::vector<uint32_t>& argb, int w, int h, double pxPerMm, double cellMm = 10);

/**
 * Kamerahöhe für den Scan wie Android (cameraOver): gemessene Oberfläche + aboveSurface, sonst scanZ der Kalibrierung,
 * höchstens zTop. Der Pi fährt Z nur mit gemessener Oberfläche: fehlt sie, geht der Scan nur, wenn Z schon auf ±1 mm an
 * der Scanhöhe steht (dann bleibt Z, wie es ist). Sonst `lock` mit dem Satz, was zu tun ist.
 */
struct ScanHeight {
    std::optional<double> z;   /// Ziel-Z, wenn der Scan gehen kann
    bool jog = false;          /// Z muss dafür bewegt werden
    QString lock;
};
ScanHeight scanHeight(const Calibration& cal, std::optional<double> surface, double currentZ, double zTop = Limits::Z_MAX_MM);
/** Z-Jog-Schritte (±10, ±1, ±0,1 mm) für delta, wie CameraFocus.jogSteps. */
std::vector<double> jogSteps(double delta);

/** Entzerrtes Einzelbild in Arbeitsflächen-mm: area = was es zeigt (Kopf + nutzbarer Bereich). */
struct Rectified {
    std::vector<uint32_t> argb;
    int width = 0, height = 0;
    Box area;
};
Rectified rectify(const Calibration& cal, const uint32_t* argb, int w, int h, Pt head, double pxPerMm);

}  // namespace lumacut::Camera
