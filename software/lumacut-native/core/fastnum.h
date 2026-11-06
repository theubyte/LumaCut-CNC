#pragma once
/** Dezimalzahl lesen, exakt wie ein korrekt rundender Parser (Javas toDouble), aber im Regelfall ohne Umweg. */
#include <charconv>
#include <cmath>
#include <cstdint>

namespace lumacut::detail {

inline const double kPow10[] = {1e0, 1e1, 1e2, 1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9, 1e10, 1e11, 1e12, 1e13, 1e14, 1e15, 1e16, 1e17, 1e18, 1e19, 1e20, 1e21, 1e22};

/**
 * Liest [-+]?ziffern[.ziffern][e[-+]ziffern] ab p. Gibt das Ende zurück oder nullptr, wenn dort keine Zahl steht.
 * Bis 15 Ziffern und Exponent bis 22: Mantisse und Zehnerpotenz sind exakte doubles, eine Rechnung rundet korrekt.
 */
inline const char* parseDouble(const char* p, const char* end, double& out) {
    const char* start = p;
    bool neg = false;
    if (p < end && (*p == '-' || *p == '+')) { neg = *p == '-'; ++p; }
    uint64_t m = 0;
    int digits = 0, scale = 0;
    const char* dstart = p;
    while (p < end && *p >= '0' && *p <= '9') {
        if (digits < 18) { m = m * 10 + uint64_t(*p - '0'); if (m) ++digits; } else digits = 99;
        ++p;
    }
    bool any = p > dstart;
    if (p < end && *p == '.') {
        const char* f = p + 1;
        while (f < end && *f >= '0' && *f <= '9') {
            if (digits < 18) { m = m * 10 + uint64_t(*f - '0'); if (m) ++digits; ++scale; } else digits = 99;
            ++f;
        }
        if (f > p + 1) any = true;
        if (any) p = f;
    }
    if (!any) return nullptr;
    int exp10 = 0;
    bool hasExp = false;
    if (p < end && (*p == 'e' || *p == 'E')) {
        const char* q = p + 1;
        bool eneg = false;
        if (q < end && (*q == '-' || *q == '+')) { eneg = *q == '-'; ++q; }
        if (q < end && *q >= '0' && *q <= '9') {
            while (q < end && *q >= '0' && *q <= '9') { if (exp10 < 100000) exp10 = exp10 * 10 + (*q - '0'); ++q; }
            if (eneg) exp10 = -exp10;
            p = q;
            hasExp = true;
        }
    }
    const int e = exp10 - scale;
    if (digits <= 15 && e >= -22 && e <= 22) {
        const double v = double(m);
        const double r = e < 0 ? v / kPow10[-e] : v * kPow10[e];
        out = neg ? -r : r;
        return p;
    }
    (void)hasExp;
    const char* s = start;
    if (*s == '+') ++s;
    const auto res = std::from_chars(s, p, out, std::chars_format::general);
    if (res.ec == std::errc::result_out_of_range) {
        // Wie Java: zu groß wird Unendlich, zu klein 0.
        out = (exp10 - scale > 0) ? (neg ? -HUGE_VAL : HUGE_VAL) : (neg ? -0.0 : 0.0);
        return p;
    }
    if (res.ec != std::errc()) return nullptr;
    return p;
}

}  // namespace lumacut::detail
