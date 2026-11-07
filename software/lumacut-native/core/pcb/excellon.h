#pragma once
/**
 * Excellon drill file reader: tools, METRIC/INCH, LZ/TZ, decimal or implicit coordinates, modal coordinates,
 * G85 slots and simple routed slots (M15/M16). Result in millimetres, Y up.
 */
#include "core/model.h"
#include <QStringList>
#include <map>
#include <optional>
#include <string_view>
#include <vector>

namespace lumacut::pcb {

struct DrillHit { double x = 0, y = 0, dia = 0; int tool = 0; };
struct DrillSlot { Pt a, b; double dia = 0; int tool = 0; };

struct ExcellonResult {
    bool inch = false;
    std::map<int, double> tools;      // tool number to diameter in mm
    std::vector<DrillHit> hits;
    std::vector<DrillSlot> slotHoles;
    std::optional<Box> bounds;
    QStringList warnings;
};

ExcellonResult parseExcellon(std::string_view text);

}  // namespace lumacut::pcb
