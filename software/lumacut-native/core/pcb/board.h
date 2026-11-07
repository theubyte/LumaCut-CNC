#pragma once
/** A set of fabrication files as one board: copper, mask, silk, outline, drills, and design checks. */
#include "core/pcb/excellon.h"
#include "core/pcb/gerber.h"
#include "core/pcb/layers.h"
#include <QByteArray>
#include <memory>

namespace lumacut::pcb {

enum class Side { Top, Bottom };

struct PcbFile {
    QString name;
    QByteArray text;
    LayerKind kind = LayerKind::Other;
    std::shared_ptr<const GerberResult> gerber;
    std::shared_ptr<const ExcellonResult> drill;
    QString error;              // parse error, shown in the file list instead of failing
    int pending = 0;            // for callers that parse later: 1 classify and parse, 2 parse as `kind`
};

struct SideArt {
    Polys polys;
    std::optional<double> minStroke;
    double area = 0;
};

struct Board {
    std::optional<SideArt> copper[2], mask[2], silk[2];   // index Side
    Polys outline;              // closed loops, largest first; the first is the board edge
    bool outlineFromFile = false;
    std::vector<DrillHit> drills;
    std::vector<DrillSlot> slotHoles;
    Box bounds;
    QStringList warnings;

    const std::optional<SideArt>& copperOf(Side s) const { return copper[int(s)]; }
    const std::optional<SideArt>& maskOf(Side s) const { return mask[int(s)]; }
    const std::optional<SideArt>& silkOf(Side s) const { return silk[int(s)]; }
};

/** Reads one file; kind Other is classified from name and content. Never throws. */
PcbFile readPcbFile(const QString& name, const QByteArray& text, std::optional<LayerKind> kind = std::nullopt);
/** The same file read as another layer type (a drill file parses differently from Gerber). */
PcbFile parseAs(const PcbFile& file, LayerKind kind);
/** Several files at once, on all cores. */
std::vector<PcbFile> readPcbFiles(const std::vector<std::pair<QString, QByteArray>>& files);

/** Joins drawn lines end to end. Returns closed loops, largest first. */
Polys stitchLoops(const Polys& lines, double tolMm = 0.02);
std::optional<Board> buildBoard(const std::vector<PcbFile>& files);

struct Clearance { double mm = 0; Pt at; };
/**
 * Smallest gap between separate copper edges, looking up to limitMm far. Rings have copper on their left (outers CCW,
 * holes CW), so a line across copper is told from a line across a gap at both ends, locally. Runs on all cores.
 * Returns nullopt when everything is further apart than the limit.
 */
std::optional<Clearance> minClearance(const Polys& polys, double limitMm = 2);

/** ZIP archives unpacked, things that cannot be fabrication data skipped. Throws std::runtime_error on a broken ZIP. */
std::vector<std::pair<QString, QByteArray>> unpackPcbInputs(const std::vector<std::pair<QString, QByteArray>>& picked);
/** The built-in example board (LED blinker, 60 x 40 mm), self-made test material. */
std::vector<std::pair<QString, QByteArray>> exampleBoardFiles();

}  // namespace lumacut::pcb
