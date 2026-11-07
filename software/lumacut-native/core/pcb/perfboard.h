#pragma once
/**
 * Perfboards (Lochraster): plan where parts go and how they are wired, then MARK it on the solder mask with low power.
 * The diode only discolours or removes lacquer. There is no copper between the pads, so no traces come out of this:
 * connections are solder bridges or wires, the laser only shows their way. Nothing is ever cut.
 *
 * Board-local millimetres, origin top left of the board, y down, seen from the component side. Holes are addressed as
 * columns A, B, ... and rows 1, 2, ... like the print on the board. Every marking is an open or closed polyline that is
 * clipped away from all pads plus a safety margin, so tin and solderability do not suffer.
 */
#include "core/pcb/geom.h"
#include <QByteArray>
#include <QString>
#include <QStringList>
#include <optional>
#include <stdexcept>
#include <vector>

namespace lumacut::pcb {

struct GridPt {
    int c = 0, r = 0;
    bool operator==(const GridPt&) const = default;
};

struct PerfBoard {
    QString name = QStringLiteral("50 × 70");
    double width = 50, height = 70, pitch = 2.54;
    int cols = 18, rows = 24;
    double padDia = 1.8, holeDia = 1.0;
    double mountDia = 2.0, mountInset = 2.0;   // corner mounting holes: diameter, centre distance from both edges
    bool edgeRows = true;                       // first and last row are oblong bus pads

    /** Centre of a hole; the grid sits in the middle of the board. */
    Pt hole(int c, int r) const;
    Pt hole(GridPt g) const { return hole(g.c, g.r); }
    bool contains(GridPt g) const { return g.c >= 0 && g.r >= 0 && g.c < cols && g.r < rows; }
    bool isEdge(GridPt g) const { return edgeRows && (g.r == 0 || g.r == rows - 1); }
    std::vector<Pt> mountHoles() const;
    /** The pad would touch a mounting hole. */
    bool blockedByMount(GridPt g) const;
    /** Nearest hole to a board point, if within half a pitch. */
    std::optional<GridPt> holeAt(Pt p) const;
    /** Outline of one pad (round, or oblong in an edge row). */
    Poly padShape(GridPt g, double grow = 0) const;

    static QString colName(int c);                 // A..Z, AA, AB, ...
    QString holeName(GridPt g) const { return colName(g.c) + QString::number(g.r + 1); }
    /** The owner's boards: 20×80, 30×70, 40×60, 50×70, 70×90. */
    static std::vector<PerfBoard> templates();
};

/** A shape in pitch units relative to pin 1, before rotation. */
struct PartShape {
    enum Kind { Rect, Line, Circle, Plus } kind = Rect;
    double a = 0, b = 0, c = 0, d = 0;   // rect x0 y0 x1 y1, line x0 y0 x1 y1, circle cx cy r, plus cx cy size
};
struct PartDef {
    QString id, name, category, prefix, value, hint;
    int order = 50;                      // assembly order: low parts first
    std::vector<GridPt> pins;            // pin 1 first, relative to pin 1
    std::vector<PartShape> body, mark;   // outline; polarity or pin-1 marks
    bool polarized = false;
};
/** From the resource :/pcb/perfboard_parts.json. Throws std::runtime_error if it is broken. */
const std::vector<PartDef>& partLibrary();
const PartDef* findPart(const QString& id);
std::vector<PartDef> parsePartLibrary(const QByteArray& json);

struct Placed {
    QString id, partId, ref, value;
    GridPt at;       // pin 1
    int rot = 0;     // quarter turns clockwise as seen from the component side
};
struct Wire {
    QString id;
    bool solder = true;          // solder side: solder bridge; component side: wire bridge
    std::vector<GridPt> pts;     // orthogonal polyline through hole centres
};
struct Label {
    QString id, text;
    Pt at;                       // centre, board mm
    double heightMm = 1.5;
    bool solder = false;
};
struct PerfDesign {
    QString title = QStringLiteral("Lochraster");
    PerfBoard board;
    std::vector<Placed> parts;
    std::vector<Wire> wires;
    std::vector<Label> labels;
    bool holeNumbers = false;    // mark A, B, ... and 1, 2, ... in the margins
    bool markRefs = true;
    bool markValues = false;
};

/** Quarter turns clockwise on screen (y down). */
GridPt rotated(GridPt d, int rot);
std::vector<GridPt> pinsOf(const Placed& p, const PartDef& def);
/** Body rectangle in board mm (union of the rect shapes; pins if none). */
std::optional<Box> bodyBox(const Placed& p, const PartDef& def, const PerfBoard& b);
/** Body and polarity marks as polylines in board mm, unclipped (for the editor and the plan). */
Polys partOutline(const Placed& p, const PartDef& def, const PerfBoard& b);
/** Orthogonal route through a corner: horizontal first, or vertical first. */
std::vector<GridPt> route(GridPt a, GridPt b, bool verticalFirst = false);
QString nextRef(const PerfDesign& d, const QString& prefix);

struct MarkOptions {
    double beamMm = 0.15;
    double padClearMm = 0.2;     // lacquer kept around every pad, beyond half a beam
    double textMm = 1.2;         // reference and value height
};
inline double minTextHeight(double beamMm) { return std::max(1.0, 8 * beamMm); }
/** Where the laser may mark: the board minus every pad and mounting hole grown by clearance plus half a beam. */
Polys markRegion(const PerfDesign& d, const MarkOptions& o);
Polys padKeepOut(const PerfDesign& d, double grow);
/** The marked way of a connection: in the lacquer channel half a pitch beside the holes it joins. */
Poly wireMarkLine(const Wire& w, const PerfBoard& b);

struct PerfMarks {
    Polys component;   // component side, board mm, as seen from the top
    Polys solder;      // solder side, board mm, as seen from the top through the board (not yet mirrored)
    double textLostShare = 0;   // part of the marked text length that falls on pads and is dropped
};
/** All markings, already clipped to markRegion. Text glyphs on the solder side are pre-mirrored to read right after turning. */
PerfMarks buildMarks(const PerfDesign& d, const MarkOptions& o);
/** Text outlines centred on `at`, unclipped. Needs a running QGuiApplication. */
Polys textAt(const QString& text, Pt at, double heightMm, bool mirrored = false);
/** For lasering the solder side from above after turning the board about its vertical centre axis. */
inline Pt mirrorX(Pt p, double width) { return {width - p.x, p.y}; }
Polys mirrored(const Polys& polys, double width);

enum class PerfTone { Info, Warn, Bad };
struct PerfCheck {
    QString id;
    PerfTone tone = PerfTone::Info;
    QString text;
    QStringList refs;
};
/** Bed placement (centre of the board in work mm) is checked too if given. */
std::vector<PerfCheck> perfChecks(const PerfDesign& d, const MarkOptions& o, std::optional<Pt> bedCentre = std::nullopt);

struct BomRow { QString part, value; QStringList refs; int count = 0; int order = 50; };
std::vector<BomRow> bom(const PerfDesign& d);
QByteArray bomCsv(const PerfDesign& d);
/** Assembly order: parts sorted low to high, then by reference. Indices into d.parts. */
std::vector<int> assemblyOrder(const PerfDesign& d);

/** `.lumaraster`: {"format":"lumaraster","version":1,...}. */
QByteArray perfToJson(const PerfDesign& d);
/** Throws std::runtime_error with a German sentence. */
PerfDesign perfFromJson(const QByteArray& json);

/** Assembly plan at board size: board, pads, bodies, references, wires. Highlights `highlight` (part indices). */
QByteArray assemblySvg(const PerfDesign& d, bool fromBelow = false);
QByteArray assemblyPng(const PerfDesign& d, double pxPerMm = 12, bool fromBelow = false);

/** Layer names in the project. */
QString perfLayerName(bool solder);
/**
 * Elements for the project: component side on `plateTop`, solder side mirrored on `plateBottom`, the board centre at
 * `centre` (work mm). Creates or updates the two layers (process Markieren, line mode) in `layers`.
 */
std::vector<Element> perfElements(std::vector<Layer>& layers, const PerfMarks& m, const PerfDesign& d, int plateTop,
                                  int plateBottom, Pt centre, double powerPct, double speed);

}  // namespace lumacut::pcb
