#pragma once
/** Parser wie android/core Toolpath.kt: Marlin-2.1-Lasersemantik, Zeitschätzung gleich wie Android. */
#include "core/model.h"
#include <QByteArrayView>
#include <QString>
#include <QStringList>
#include <cstdint>
#include <optional>
#include <type_traits>
#include <vector>

namespace lumacut {

struct ToolpathStats {
    double cutMm = 0, travelMm = 0, seconds = 0;
    int maxPower = 0;           /// 0..255
    QStringList warnings;
};

/** Kompakt: Segment i liegt in xy[4i..4i+3], Maschinen-mm in 32 Bit wie Android. */
struct Toolpath {
    std::vector<float> xy;       /// x0, y0, x1, y1 je Segment
    std::vector<uint8_t> power;  /// S 0..255; 0 = Leerfahrt (cut == power > 0)
    std::vector<uint32_t> line;  /// Zeile im G-Code, ab 1
    std::optional<Box> bounds;   /// nur brennende Segmente
    ToolpathStats stats;
    int lineCount = 0;

    size_t count() const { return power.size(); }
    bool cut(size_t i) const { return power[i] > 0; }
    /** Geschätzte Restzeit, wenn die Maschine bei Zeile `atLine` von lineCount ist. */
    double remainingSeconds(int atLine) const;
};

/** Text in einem Stück, beliebiges Zeilenende (\n, \r\n, \r). */
Toolpath parseToolpath(QByteArrayView gcode);

/** "1 h 02 min", "3 min 07 s", "12 s". */
QString formatDuration(double seconds);

void fillGpuSegments(const Toolpath& tp, float* outStride5);

/**
 * Für `SegmentsItem::setSegments`: `auto v = toGpuSegments<GpuSegment>(tp);`
 * Layout {float x0,y0,x1,y1,power}, power normiert 0..1, 0 = Leerfahrt. Mehrkernig.
 */
template <class Segment>
std::vector<Segment> toGpuSegments(const Toolpath& tp) {
    static_assert(sizeof(Segment) == 5 * sizeof(float) && std::is_trivially_copyable_v<Segment>,
                  "erwartet struct { float x0, y0, x1, y1, power; }");
    std::vector<Segment> out(tp.count());
    if (!out.empty()) fillGpuSegments(tp, reinterpret_cast<float*>(out.data()));
    return out;
}

}  // namespace lumacut
