#pragma once
/**
 * Werkstatt-Generatoren, rein: Einstellungen hinein, Geometrie heraus. Fachlich wie die Tauri-Fassung
 * (src/core/generators) und Android (Frame.kt, Tools.kt, Create.kt). Die App legt ein Ergebnis als Elemente ins Projekt.
 * Fehler: GenError mit einem deutschen Satz. Text kommt über einen TextShaper, damit Tests keine Schrift brauchen.
 */
#include "core/model.h"
#include <QString>
#include <QStringList>
#include <functional>
#include <optional>
#include <stdexcept>
#include <vector>

namespace lumacut::Werkstatt {

class GenError : public std::runtime_error {
public:
    explicit GenError(const QString& text) : std::runtime_error(text.toStdString()) {}
};

/** Text als geschlossene Umrisse in mm, y nach unten, Ecke oben links auf (0, 0); heightMm etwa die Versalhöhe. */
using TextShaper = std::function<PolySet(const QString& text, double heightMm, bool bold)>;

/** Ein Teil: Pfade in Ergebnis-mm. layer = "Gravieren", "Linie" (Markieren), "Schneiden" oder der Name einer Ergebnis-Ebene. */
struct GenPart {
    QString name, layer;
    PolySet paths;
    int plate = 0;
    QString group;   /// gleiche Gruppe auf derselben Platte = eine Gruppe im Projekt
};
struct GenResult {
    std::vector<GenPart> parts;
    /** Ebenen, die das Ergebnis mitbringt; gleichnamige im Projekt werden wiederverwendet. */
    std::vector<Layer> layers;
    QStringList notes, warnings;
    /** true: Inhalt je Platte in die Mitte der Arbeitsfläche; false: Koordinaten sind schon Arbeitsflächen-mm. */
    bool center = true;
    /** Bei belegter aktiver Platte auf einer neuen anfangen. */
    bool freshPlate = false;
};
std::optional<Box> partsBounds(const GenResult& r, std::optional<int> plate = std::nullopt);
int plateCount(const GenResult& r);
/** Verschiebung je Platte: Mitte der Arbeitsfläche bei center, sonst 0. */
Pt plateOffset(const GenResult& r, int plate);
/**
 * Elemente wie Android: lokale Pfade ab (0, 0), Lage im Transform, Platte = Ergebnisplatte (Aufrufer verschiebt).
 * layerId bildet Ebenen-Namen auf Projekt-IDs ab.
 */
std::vector<Element> toElements(const GenResult& r, const std::function<QString(const QString&)>& layerId);

/** Leistung × Tempo; jedes Feld auf eigener Ebene mit seinen Werten, Beschriftung auf "Beschriftung". */
struct MatGridSpec {
    double powerFrom = 20, powerTo = 100;
    int powerSteps = 5;
    double speedFrom = 300, speedTo = 3000;
    int speedSteps = 5;
    bool fill = true;
    double cellMm = 10, gapMm = 4;
    int passes = 1;
    double intervalMm = 0.1;
};
GenResult matGrid(const MatGridSpec& s, const TextShaper& shape);

enum class BoxLid { None, Joined, Loose };
struct BoxGenSpec {
    double w = 100, d = 80, h = 60, t = 3, finger = 10;
    BoxLid lid = BoxLid::None;
    bool inner = false;
    double kerf = 0;
};
struct Size3 { double w, d, h; };
Size3 boxOuter(const BoxGenSpec& s);
/** Teile mit Namen, Ursprung oben links je Teil, ohne Kerf. */
std::vector<std::pair<QString, Poly>> boxPanels(const BoxGenSpec& s);
GenResult box(const BoxGenSpec& s);

struct GearSpec {
    double module = 2;
    int teeth = 24;
    double pressureDeg = 20, boreMm = 6, kerf = 0;
};
struct GearDims { double pitch, outer, root, base; };
GearDims gearDims(const GearSpec& s);
/** Geschlossener Umriss, Mitte bei (outer/2, outer/2), ein Zahn zeigt nach oben. Ohne Unterschnitt-Ausgleich. */
Poly gearOutline(const GearSpec& s);
GenResult gear(const GearSpec& s);

struct RulerSpec { double lengthMm = 150, widthMm = 30, holeMm = 5; QString title; };
GenResult ruler(const RulerSpec& s, const TextShaper& shape);

struct ScaleBarSpec { double scale = 50, realLengthM = 5; int segments = 5; double heightMm = 3; };
GenResult scaleBar(const ScaleBarSpec& s, const TextShaper& shape);

/** Stil wie Personalize::frame: 0 Rechteck, 1 abgerundet, 2 doppelt, 3 oval, 4 gestrichelt. */
struct FrameGenSpec {
    std::optional<Box> around;   /// gesetzt: um diese Box (Arbeitsflächen-mm), sonst freie Maße
    double widthMm = 100, heightMm = 60, marginMm = 5;
    int style = 1;
    bool cut = true;
};
GenResult frame(const FrameGenSpec& s);

struct SerialTemplate { QString before, after; qint64 start = 0; int width = 1; };
/** "SN-{0001}" → Start 1, vier Stellen. Wirft GenError ohne Platzhalter. */
SerialTemplate parseTemplate(const QString& t);
QString serialText(const SerialTemplate& t, int i, int step = 1);
inline constexpr int MAX_SERIALS = 500;
struct SerialSpec {
    QString templ = QStringLiteral("SN-{0001}");
    int count = 24, step = 1;
    double textHeightMm = 6;
    double tagWidthMm = 50, tagHeightMm = 16, holeMm = 3, gapMm = 2;   /// Schild 0 × 0 = nur Text
};
GenResult serials(const SerialSpec& s, const TextShaper& shape, double plateW, double plateH);

enum class StampMotif { None, Star, Heart, Drop };
struct StampSpec {
    double widthMm = 60, heightMm = 25;
    bool round = false;
    QStringList lines;
    bool bold = true;
    StampMotif motif = StampMotif::None;
    double borderMm = 0.8;
    bool inverted = true, mirrored = true;
};
GenResult stamp(const StampSpec& s, const TextShaper& shape);

struct QrSpec { QString text; double moduleMm = 1; bool plate = false; };
GenResult qr(const QrSpec& s);

/**
 * Halterung für Lochrasterplatinen: Rahmen aus Plattenmaterial mit Tasche, deren Mitte an der gemeinsamen Lage liegt
 * (AppSettings perfboard/x, perfboard/y). Spiel = Tasche minus Platine je Richtung. Kerf: die Tasche wird um die halbe
 * Schnittbreite kleiner gezeichnet, der Außenumriss um die halbe größer, damit die fertigen Maße stimmen.
 */
struct PerfboardSize { double w, h; };
inline constexpr PerfboardSize PERFBOARD_SIZES[] = {{20, 80}, {30, 70}, {40, 60}, {50, 70}, {70, 90}};
inline constexpr double PERFBOARD_X = 185, PERFBOARD_Y = 197.5;
struct HolderSpec {
    double boardW = 50, boardH = 70;
    double centerX = PERFBOARD_X, centerY = PERFBOARD_Y;
    double playMm = 0.3, kerfMm = 0.15, rimMm = 15;
};
struct HolderGeometry {
    Box pocket;        /// fertige Tasche (nach dem Schnitt), Arbeitsflächen-mm
    Box pocketPath;    /// gezeichnete Tasche ohne Griffmulde
    Box outer;         /// gezeichneter Außenumriss
    double gripRadius = 0;
};
/** Wirft GenError bei unsinnigen Maßen, außerhalb der Arbeitsfläche oder im gesperrten Bereich. */
HolderGeometry holderGeometry(const HolderSpec& s);
/** Eigene Ebene des Rahmens, damit die Ebene Schneiden des Projekts unberührt bleibt. */
inline const QString HOLDER_LAYER = QStringLiteral("Halterung schneiden");
GenResult perfboardHolder(const HolderSpec& s, const TextShaper& shape);

/**
 * Materialtest für Lötstopplack: kleine Felder aus Linien (Prozess Markieren), jedes auf eigener Ebene, Mitte an der
 * gemeinsamen Lochraster-Lage. Werte sind Vorschläge, keine geprüften.
 */
struct MaskTestSpec {
    double powerFrom = 8, powerTo = 20;
    int powerSteps = 4;
    double speedFrom = 3000, speedTo = 1000;
    int speedSteps = 3;
    double cellMm = 4, gapMm = 1.5, lineMm = 0.3;
    double centerX = PERFBOARD_X, centerY = PERFBOARD_Y;
};
GenResult maskTest(const MaskTestSpec& s, const TextShaper& shape);

/** Deutsches Zahlenformat ohne überflüssige Nullen: 12,5. */
QString num(double v, int digits = 1);

}  // namespace lumacut::Werkstatt
