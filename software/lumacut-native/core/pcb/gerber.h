#pragma once
/**
 * Gerber RS-274X reader. Text in, polygons in millimetres out, in the file's coordinates (Y up, seen from the
 * top of the board).
 *
 * Supported: %FS (L/T, A/I), %MO, %AD with C, R, O, P and macros, %AM with primitives 1, 2/20, 21, 22, 4, 5, 6, 7,
 * variables and arithmetic, D01/D02/D03, G01/G02/G03 with G74/G75, G36/G37, %LP, %LM/%LR/%LS, %SR, %OF, G70/G71,
 * G90/G91, modal coordinates and D codes, X2 %TF.FileFunction.
 * Not supported, reported as a warning: %AB block apertures, %IPNEG, %MI, %SF, %IR.
 */
#include "core/pcb/geom.h"
#include <QString>
#include <QStringList>
#include <map>
#include <stdexcept>
#include <string_view>

namespace lumacut::pcb {

struct GerberFlash { double x = 0, y = 0, w = 0, h = 0; int code = 0; };
struct GerberStroke { Poly pts; double width = 0; };

struct GerberResult {
    bool inch = false;
    Polys polys;                      // final image: closed rings, outers CCW, holes CW
    std::optional<Box> bounds;
    double area = 0;                  // mm2
    std::vector<GerberFlash> flashes;
    std::vector<GerberStroke> strokes;   // centre lines of everything drawn dark (finds the board outline)
    std::optional<double> minStrokeWidth;   // the design's trace width
    int regionCount = 0;
    QStringList warnings;
    QString fileFunction;             // X2 %TF.FileFunction, empty if none
};

class GerberError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

/** Throws GerberError when the text holds no Gerber data. */
GerberResult parseGerber(std::string_view text);
/** Macro arithmetic: + - x X / with parentheses, unary sign and $n. Throws GerberError. */
double evalMacroExpr(std::string_view src, const std::map<int, double>& vars);

}  // namespace lumacut::pcb
