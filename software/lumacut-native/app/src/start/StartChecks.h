#pragma once
#include <QString>
#include <QStringList>
#include <QVariantList>
#include <QVariantMap>
#include <optional>
#include <vector>
#include "core/gcode.h"
#include "core/model.h"
#include "core/toolpath.h"

/**
 * Everything that speaks against this start, most serious first, as plain sentences with the next step.
 * Pure functions, no Qt objects: the part that walks the geometry runs on the worker (docFindings), the part that
 * looks at the machine runs on every status (computeChecks).
 */
namespace startchecks {

struct Check {
    QString id;
    QString tone;     // bad, warn, info
    QString text;
    QString goLabel;  // optional link
    QString goDest;   // material, motiv, maschine
};

/** Findings on the plate's elements. `hasDoc` false = a saved job, no statement. */
struct Findings {
    bool hasDoc = false;
    bool ownFinding = false;    // a sentence naming the element exists: the writer's refusal adds nothing
    bool empty = false;
    std::vector<Check> checks;
    QVariantList layerRows;     // {id, name, color, on, power, speed, passes, interval, weak}
};
Findings docFindings(const lumacut::Document& plateDoc, int plate, bool multi, const lumacut::Motion& motion);

struct Input {
    Findings findings;
    bool hasToolpath = false;
    std::optional<lumacut::Box> bounds;     // machine mm
    QStringList warnings;
    qint64 gcodeBytes = 0;
    QString buildError;
    QString rejection;
    QVariantMap status;
    bool online = false;
    bool jobActive = false, frameActive = false;
    bool materialKnown = false;             // false: still unknown, no statement
    bool hasMaterial = false;
    QString materialName;
    std::optional<bool> materialTested;     // nullopt: unknown, no statement
};
std::vector<Check> computeChecks(const Input& in);

/** The sentence that says why the machine cannot start, with the next step. Empty when it can. */
QString machineBlocker(const QVariantMap& status, bool online, bool jobActive, bool frameActive);
bool blocksStart(const std::vector<Check>& checks);
inline constexpr qint64 kMaxUploadBytes = 32 * 1024 * 1024;

}  // namespace startchecks
