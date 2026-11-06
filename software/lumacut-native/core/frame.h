#pragma once
/** Wie Frame.kt: Rahmenfahrt ohne Laser (Pi op=frame) und Materialtest. */
#include "core/model.h"
#include "core/toolpath.h"
#include <QByteArray>
#include <functional>
#include <vector>

namespace lumacut {

enum class FrameMode { Box, Hull };

/** Andrews Monotone Chain, gegen den Uhrzeigersinn, ohne wiederholten Endpunkt. */
std::vector<Pt> convexHull(PolyView points);
/** Nur G21/G90/M5 I und absolute G0: das akzeptiert frame_program() auf dem Pi. Punkte in Maschinen-mm. Wirft std::invalid_argument. */
QByteArray frameProgram(PolyView points, FrameMode mode, int feed = 3000);
/** Punkte, an denen wirklich gebrannt wird (Maschinen-mm), in 32-Bit-Genauigkeit wie Android. */
std::vector<Pt> cutPoints(const Toolpath& tp);

struct MaterialTestSpec {
    double powerFrom = 20, powerTo = 100;
    int powerSteps = 5;
    double speedFrom = 300, speedTo = 3000;
    int speedSteps = 5;
    LayerMode mode = LayerMode::Fill;
    double cellMm = 10, gapMm = 4;
    int passes = 1;
    double intervalMm = 0.1, originX = 10, originY = 10;
};
std::vector<double> testSteps(double from, double to, int n);
/** Raster Leistung × Tempo, eine Ebene je Feld; `label` wandelt Text in Umrisse. Wirft std::invalid_argument mit deutschem Text. */
Document buildMaterialTest(const MaterialTestSpec& spec, const std::function<PolySet(const QString& text, double heightMm)>& label);

}  // namespace lumacut
