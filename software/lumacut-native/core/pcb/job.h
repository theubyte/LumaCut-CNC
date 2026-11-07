#pragma once
/**
 * From a board to laser work. The diode does not remove copper: it removes lacquer (or exposes film), the board is
 * etched afterwards. One plan layer per process, in board coordinates (Y up, seen from the top), then placed on the
 * bed as document elements on their own layers and plate. Power and speed here are STARTING VALUES only; the real
 * values come from the owner's material test on the same lacquer.
 *
 *  - Raster negative: everything inside the board except copper grown by half a beam (beam edge stops at copper).
 *  - Isolation: closed lines around the copper at half a beam plus offset, then one spacing further per pass.
 *  - Exposure of negative dry film: the copper itself, shrunk by half a beam.
 */
#include "core/pcb/board.h"

namespace lumacut::pcb {

enum class ResistMethod { Raster, Isolation, Expose };
enum class ProcessKey { Resist, Drill, Fiducial, Outline, Mask, Silk };
inline constexpr int kProcessCount = 6;
enum class Stage { Resist, Mask, Silk };

struct JobSettings {
    Side side = Side::Top;
    bool mirror = false;              // bottom layers are seen through the board: mirror them to laser from above
    double beamMm = 0.15;
    double overlapPct = 25;
    bool resist = true;
    ResistMethod method = ResistMethod::Raster;
    int passes = 3;                   // isolation lines around the copper
    double passSpacingMm = 0;         // between isolation lines, 0 = the line interval
    double isolationOffsetMm = 0;     // extra gap between copper edge and the first line's beam edge
    bool removeRest = false;
    bool drillMarks = true;
    bool drillCross = false;          // false: dot
    double drillMarkMm = 0.5;
    bool mask = false;
    bool silk = false;
    int fiducials = 4;                // 0, 2 or 4
    double fiducialDiaMm = 1;
    double fiducialOffsetMm = 3;
    bool outlineMark = false;
    double power[kProcessCount] = {20, 20, 20, 12, 30, 12};
    double speed[kProcessCount] = {2000, 2000, 2000, 2000, 1500, 3000};
};
/** Starting values, never presented as proven; all above the 8 % floor for burning work. */
JobSettings defaultSettings();

struct PlanLayer {
    ProcessKey key = ProcessKey::Resist;
    QString name;                     // document layer name, e.g. "Platine Ätzresist"
    Stage stage = Stage::Resist;
    LayerMode mode = LayerMode::Fill;
    QString process;                  // "Gravieren", "Markieren" or "Schneiden"
    qint64 color = 0;
    Polys polys;
    double intervalMm = 0.1, powerPct = 20, speed = 2000;
    bool output = true;
};
struct Plan {
    std::vector<PlanLayer> layers;
    Box bounds;                       // board plus fiducials
    std::vector<Pt> fiducials;
    QStringList warnings;
};

double lineInterval(double beamMm, double overlapPct);
double passSpacing(const JobSettings& s);
/** Marks on or symmetric to the vertical centre line, so they still line up when the board is turned over. */
std::vector<Pt> fiducialPoints(const Box& b, int count, double offset);
Polys drillMarkPolys(const Board& board, const JobSettings& s);
/** Heavy: offsets and booleans, isolation passes on all cores. */
Plan buildPlan(const Board& board, const JobSettings& s);

/** Board coordinates to job coordinates: Y down like the bed; mirrored about the job's centre if asked. */
Pt toJob(Pt p, const Box& b, bool mirror);
/** Top left corner of the job so it sits in the middle of the usable work area. */
Pt centeredOnBed(const Plan& plan);

enum class Tone { Ok, Warn, Bad };
struct DesignCheck { QString id; Tone tone = Tone::Ok; QString title, text; };
struct DesignFacts { std::optional<double> minTrace; std::optional<Clearance> clearance; double copperArea = 0; };
DesignFacts designFacts(const Board& board, Side side);
/** Compares the design with the beam width and the work area (job placed at origin). */
std::vector<DesignCheck> designChecks(const DesignFacts& f, const JobSettings& s, const Plan& plan, Pt origin);
/** Burn length and travel for a rough time estimate, no acceleration. */
double estimateSeconds(const PlanLayer& layer, double overscanMm = 2.5);

QString stageLabel(Stage s);
QString processLabel(ProcessKey k);
/** Names of all PCB layers in the document. */
QStringList platineLayerNames();

/**
 * Creates or updates the PCB layers in `layers` (by name) and returns the new elements on `plate`, moved to origin.
 * Only the chosen work stage has output on, so a later stage cannot be burned before its turn.
 */
std::vector<Element> planElements(std::vector<Layer>& layers, const Plan& plan, const JobSettings& s, Stage stage, int plate, Pt origin);
/** Same on a model document: replaces earlier PCB elements on that plate. Returns the ids of the new elements. */
QStringList applyPlanToDoc(Document& doc, const Plan& plan, const JobSettings& s, Stage stage, int plate, Pt origin);

}  // namespace lumacut::pcb
