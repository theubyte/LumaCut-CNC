#pragma once
/**
 * QR-Code (ISO/IEC 18004), eigene Umsetzung wie Qr.kt und qr.ts: Byte-Modus (UTF-8), Fehlerkorrektur M,
 * Versionen 1 bis 10 (bis 213 Bytes), Maske nach der kleinsten Strafpunktzahl.
 */
#include "core/model.h"
#include <QString>
#include <cstdint>
#include <vector>

namespace lumacut::Qr {

inline constexpr int MAX_VERSION = 10;
/** Kleinste Punktkante, die graviert noch sicher lesbar bleibt. */
inline constexpr double MIN_MODULE_MM = 0.8;

struct Code {
    int version = 0, size = 0, mask = 0;
    std::vector<uint8_t> modules;   /// size × size, Zeile für Zeile, 1 = dunkel
    bool dark(int x, int y) const { return modules[size_t(y) * size_t(size) + size_t(x)] != 0; }
};

/** Nutzbare Bytes einer Version bei Stufe M. */
int capacity(int version);
std::vector<int> rsDivisor(int degree);
std::vector<int> rsRemainder(const std::vector<int>& data, const std::vector<int>& divisor);
bool maskBit(int mask, int x, int y);
/** Wirft std::invalid_argument mit deutschem Satz (leer, zu lang). */
Code encode(const QString& text);
/** Gefüllte Rechtecke, eines je waagerechtem Lauf dunkler Punkte, Ecke oben links auf (0, 0). Ohne Ruhezone. */
PolySet polys(const Code& code, double moduleMm);

}  // namespace lumacut::Qr
