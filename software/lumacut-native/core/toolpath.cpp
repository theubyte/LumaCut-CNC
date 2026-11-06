#include "core/toolpath.h"
#include "core/fastnum.h"
#include "core/parallel.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <numbers>
#include <string>

namespace lumacut {
namespace {

constexpr double kTravelFeed = 9000;  // der Pi ergänzt F9000 an XY-Eilgängen ohne F
constexpr double kAccel = 1000;
constexpr double kArcMm = 0.5;

/** Eine Zeile, entschlüsselt. Rechnet nichts, darum mehrkernig; der Zustand läuft danach seriell durch. */
struct Cmd {
    enum Kind : uint8_t { Arm, Disarm, Words };
    enum Flag : uint16_t { HasX = 1, HasY = 2, HasF = 4, HasS = 8, HasI = 16, HasJ = 32, G20 = 64, G21 = 128, G90 = 256, G91 = 512 };
    double x, y, f, s, i, j;
    uint32_t line;
    uint16_t flags;
    int8_t motion;   // -1 = keine Bewegung
    Kind kind;
};

inline int toIntJ(double v) {  // Java: abschneiden, Sättigung, NaN = 0
    if (!(v == v)) return 0;
    if (v >= 2147483647.0) return std::numeric_limits<int>::max();
    if (v <= -2147483648.0) return std::numeric_limits<int>::min();
    return int(v);
}
inline bool isSpace(char c) { return c == ' ' || (c >= 9 && c <= 13); }
inline bool isWordChar(char c) { return (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '_'; }
inline char upper(char c) { return c >= 'a' && c <= 'z' ? char(c - 32) : c; }

/** Zahl ohne Exponent: "X1E5" sind zwei Wörter, wie bei der Regex von Kotlin. */
inline const char* wordNumber(const char* p, const char* end, double& v) {
    const char* q = p;
    if (q < end && (*q == '-' || *q == '+')) ++q;
    const char* d = q;
    while (q < end && *q >= '0' && *q <= '9') ++q;
    if (q < end && *q == '.') {
        const char* f = q + 1;
        while (f < end && *f >= '0' && *f <= '9') ++f;
        if (q > d || f > q + 1) q = f;
    }
    if (q == d) return nullptr;
    // Grenze setzen, damit parseDouble kein E dahinter mitnimmt.
    return detail::parseDouble(p, q, v);
}

/** Entschlüsselt [b, e). Rückgabe nur, wenn die Zeile etwas bewirkt. */
void decodeLine(const char* b, const char* e, uint32_t lineIndex, std::vector<Cmd>& out, std::string& tmp) {
    // Klammerkommentare zuerst, dann ab Semikolon abschneiden: "(;) G1" bleibt G1.
    const void* paren = std::memchr(b, '(', size_t(e - b));
    if (paren) {
        tmp.clear();
        const char* p = b;
        while (p < e) {
            if (*p == '(') {
                const char* close = static_cast<const char*>(std::memchr(p, ')', size_t(e - p)));
                if (close) { p = close + 1; continue; }
            }
            tmp.push_back(*p++);
        }
        b = tmp.data();
        e = b + tmp.size();
    }
    if (const void* semi = std::memchr(b, ';', size_t(e - b))) e = static_cast<const char*>(semi);
    while (b < e && isSpace(*b)) ++b;
    while (e > b && isSpace(e[-1])) --e;
    if (b == e) return;
    const auto n = e - b;
    if (n >= 2 && upper(b[0]) == 'M') {
        if (b[1] == '3') {
            for (const char* p = b; p < e; ++p) {
                if (upper(*p) != 'I') continue;
                const bool lb = p == b || !isWordChar(p[-1]);
                const bool rb = p + 1 == e || !isWordChar(p[1]);
                if (lb && rb) {
                    Cmd c{};
                    c.kind = Cmd::Arm;
                    c.line = lineIndex;
                    out.push_back(c);
                    return;
                }
            }
        } else if (b[1] == '5') {
            Cmd c{};
            c.kind = Cmd::Disarm;
            c.line = lineIndex;
            out.push_back(c);
            return;
        }
    }
    Cmd c{};
    c.motion = -1;
    c.kind = Cmd::Words;
    c.line = lineIndex;
    const char* p = b;
    while (p < e) {
        const char l = upper(*p);
        if (l < 'A' || l > 'Z') { ++p; continue; }
        const char* q = p + 1;
        while (q < e && isSpace(*q)) ++q;
        double v;
        const char* after = wordNumber(q, e, v);
        if (!after) { ++p; continue; }
        switch (l) {
            case 'G': {
                const int g = toIntJ(v);
                if (g == 20) c.flags |= Cmd::G20;
                else if (g == 21) c.flags |= Cmd::G21;
                else if (g == 90) c.flags |= Cmd::G90;
                else if (g == 91) c.flags |= Cmd::G91;
                else if (c.motion < 0 && g >= 0 && g <= 3) c.motion = int8_t(g);
                break;
            }
            case 'M': break;
            case 'X': c.x = v; c.flags |= Cmd::HasX; break;
            case 'Y': c.y = v; c.flags |= Cmd::HasY; break;
            case 'F': c.f = v; c.flags |= Cmd::HasF; break;
            case 'S': c.s = v; c.flags |= Cmd::HasS; break;
            case 'I': c.i = v; c.flags |= Cmd::HasI; break;
            case 'J': c.j = v; c.flags |= Cmd::HasJ; break;
            default: break;
        }
        p = after;
    }
    if (c.motion >= 0 || (c.flags & (Cmd::G20 | Cmd::G21 | Cmd::G90 | Cmd::G91))) out.push_back(c);
}

/** Text in Stücken, die an Zeilengrenzen enden. Eine Stückgröße, die viele Zeilen je Thread und wenig Speicher gibt. */
struct Block {
    const char* begin;
    const char* end;
    std::vector<Cmd> cmds;
    uint32_t lines = 0;  // Zeilenenden in diesem Stück
};
constexpr qsizetype kBlockBytes = 1 << 19;

void decodeBlock(Block& bl, bool isLast) {
    bl.cmds.clear();
    bl.lines = 0;
    std::string tmp;
    const char* p = bl.begin;
    const char* const end = bl.end;
    while (p < end) {
        const char* q = p;
        while (q < end && *q != '\n' && *q != '\r') ++q;
        decodeLine(p, q, bl.lines, bl.cmds, tmp);
        if (q >= end) { p = q; break; }
        ++bl.lines;
        p = (*q == '\r' && q + 1 < end && q[1] == '\n') ? q + 2 : q + 1;
    }
    (void)isLast;
}

/** Der Zustand der Maschine, wie Toolpath.parse in Kotlin. */
struct State {
    Toolpath& tp;
    double x = 0, y = 0, scale = 1, feed = 1000;
    bool absolute = true, armed = false;
    int power = 0, maxPower = 0, unpowered = 0;
    double cutMm = 0, travelMm = 0, seconds = 0, dirX = 0, dirY = 0;
    double bMinX = HUGE_VAL, bMinY = HUGE_VAL, bMaxX = -HUGE_VAL, bMaxY = -HUGE_VAL;
    bool inPark = false;
    Box park;

    void step(double px, double py, double qx, double qy, bool cut, double speed, uint32_t lineNo) {
        const double len = hypotJ(qx - px, qy - py);
        if (!(len > 0)) return;
        tp.xy.push_back(float(px));
        tp.xy.push_back(float(py));
        tp.xy.push_back(float(qx));
        tp.xy.push_back(float(qy));
        tp.power.push_back(cut ? uint8_t(power) : uint8_t(0));
        tp.line.push_back(lineNo);
        if (cut) {
            cutMm += len;
            if (power > maxPower) maxPower = power;
            const double loX = px < qx ? px : qx, hiX = px > qx ? px : qx, loY = py < qy ? py : qy, hiY = py > qy ? py : qy;
            if (loX < bMinX) bMinX = loX;
            if (hiX > bMaxX) bMaxX = hiX;
            if (loY < bMinY) bMinY = loY;
            if (hiY > bMaxY) bMaxY = hiY;
            if (!inPark && segmentCrosses(px, py, qx, qy, park)) inPark = true;
        } else {
            travelMm += len;
        }
        seconds += len / std::max(speed, 1.0) * 60;
        const double ux = (qx - px) / len, uy = (qy - py) / len;
        if (ux * dirX + uy * dirY < 0.5) seconds += speed / 60.0 / kAccel;
        dirX = ux;
        dirY = uy;
    }

    void arc(double x0, double y0, double x1, double y1, double i, double j, bool cw, bool cut, double speed, uint32_t lineNo) {
        const double pi = std::numbers::pi;
        const double cx = x0 + i, cy = y0 + j, r = hypotJ(i, j);
        const double a0 = std::atan2(y0 - cy, x0 - cx);
        double a1 = std::atan2(y1 - cy, x1 - cx);
        if (cw) { if (a1 >= a0) a1 -= 2 * pi; } else if (a1 <= a0) a1 += 2 * pi;
        const int n = std::max(2, toIntJ(std::ceil(std::fabs(a1 - a0) * r / kArcMm)));
        double px = x0, py = y0;
        for (int k = 1; k <= n; ++k) {
            double qx = x1, qy = y1;
            if (k != n) {
                const double a = a0 + (a1 - a0) * k / n;
                qx = cx + r * std::cos(a);
                qy = cy + r * std::sin(a);
            }
            step(px, py, qx, qy, cut, speed, lineNo);
            px = qx;
            py = qy;
        }
    }

    void run(const Cmd& c, uint32_t lineNo) {
        if (c.kind == Cmd::Arm) { armed = true; return; }
        if (c.kind == Cmd::Disarm) { armed = false; power = 0; return; }
        if (c.flags & Cmd::G20) scale = 25.4;
        if (c.flags & Cmd::G21) scale = 1.0;
        if (c.flags & Cmd::G90) absolute = true;
        if (c.flags & Cmd::G91) absolute = false;
        if (c.motion < 0) return;
        if (c.flags & Cmd::HasF) feed = c.f * scale;
        const double nx = (c.flags & Cmd::HasX) ? (absolute ? c.x * scale : x + c.x * scale) : x;
        const double ny = (c.flags & Cmd::HasY) ? (absolute ? c.y * scale : y + c.y * scale) : y;
        const bool rapid = c.motion == 0;
        if (rapid) power = 0;
        else if (c.flags & Cmd::HasS) power = std::clamp(toIntJ(c.s), 0, 255);
        else if (armed && power == 0) ++unpowered;
        const bool cut = !rapid && armed && power > 0;
        const double speed = rapid && !(c.flags & Cmd::HasF) ? kTravelFeed : feed;
        if ((c.motion == 2 || c.motion == 3) && (c.flags & (Cmd::HasI | Cmd::HasJ)))
            arc(x, y, nx, ny, ((c.flags & Cmd::HasI) ? c.i : 0.0) * scale, ((c.flags & Cmd::HasJ) ? c.j : 0.0) * scale, c.motion == 2, cut, speed, lineNo);
        else
            step(x, y, nx, ny, cut, speed, lineNo);
        x = nx;
        y = ny;
    }
};

}  // namespace

Toolpath parseToolpath(QByteArrayView gcode) {
    Toolpath tp;
    const char* const begin = gcode.data();
    const qsizetype size = gcode.size();
    // Grobe Vorbelegung: eine Zeile ist etwa 30 Bytes.
    const size_t guess = size_t(size / 28 + 16);
    tp.xy.reserve(guess * 4);
    tp.power.reserve(guess);
    tp.line.reserve(guess);

    State st{tp};
    st.park = Box{0.0, 0.0, Bed::parkX(), Bed::parkY()};

    const int threads = idealThreads();
    std::vector<Block> blocks(static_cast<size_t>(threads));
    qsizetype pos = 0;
    uint32_t lineBase = 0;
    while (pos < size) {
        // Ein Stapel Stücke, parallel entschlüsselt, dann der Reihe nach durch den Zustand.
        int used = 0;
        for (; used < threads && pos < size; ++used) {
            qsizetype e = std::min(size, pos + kBlockBytes);
            while (e < size && begin[e - 1] != '\n' && begin[e - 1] != '\r') ++e;
            if (e < size && begin[e - 1] == '\r' && begin[e] == '\n') ++e;
            blocks[size_t(used)].begin = begin + pos;
            blocks[size_t(used)].end = begin + e;
            pos = e;
        }
        if (used == 1) decodeBlock(blocks[0], pos >= size);
        else {
            parallelFor(used, [&](std::ptrdiff_t b) { decodeBlock(blocks[size_t(b)], false); });
        }
        for (int b = 0; b < used; ++b) {
            for (const Cmd& c : blocks[size_t(b)].cmds) st.run(c, lineBase + c.line + 1);
            lineBase += blocks[size_t(b)].lines;
        }
    }
    tp.lineCount = int(lineBase) + 1;

    tp.stats.cutMm = st.cutMm;
    tp.stats.travelMm = st.travelMm;
    tp.stats.seconds = st.seconds;
    tp.stats.maxPower = st.maxPower;
    if (st.unpowered > 0)
        tp.stats.warnings << QStringLiteral("%1 Laserfahrten nach Leerfahrt ohne S-Wert: Marlin lasert dort mit 0").arg(st.unpowered);
    if (st.bMinX == HUGE_VAL) {
        tp.stats.warnings << QStringLiteral("Keine Laserbewegung gefunden");
    } else {
        tp.bounds = Box{st.bMinX, st.bMinY, st.bMaxX, st.bMaxY};
        if (st.bMinX < 0.0 || st.bMinY < 0.0 || st.bMaxX > Bed::width() || st.bMaxY > Bed::height())
            tp.stats.warnings << QStringLiteral("Motiv liegt außerhalb der Arbeitsfläche");
    }
    if (st.inPark) tp.stats.warnings << QStringLiteral("Motiv läuft durch den Bereich %1, dort wird nicht gelasert").arg(Work::parkName());
    return tp;
}

double Toolpath::remainingSeconds(int atLine) const {
    if (lineCount <= 0) return 0;
    const double k = 1.0 - double(atLine) / lineCount;
    return stats.seconds * (k < 0.0 ? 0.0 : k > 1.0 ? 1.0 : k);
}

QString formatDuration(double seconds) {
    const qint64 s = qint64(std::max(0.0, seconds)), h = s / 3600, m = (s % 3600) / 60, r = s % 60;
    if (h > 0) return QStringLiteral("%1 h %2 min").arg(h).arg(m, 2, 10, QLatin1Char('0'));
    if (m > 0) return QStringLiteral("%1 min %2 s").arg(m).arg(r, 2, 10, QLatin1Char('0'));
    return QStringLiteral("%1 s").arg(r);
}

void fillGpuSegments(const Toolpath& tp, float* out) {
    parallelBlocks(std::ptrdiff_t(tp.count()), 1 << 15, [&](std::ptrdiff_t i0, std::ptrdiff_t i1) {
        for (std::ptrdiff_t i = i0; i < i1; ++i) {
            float* o = out + i * 5;
            std::memcpy(o, tp.xy.data() + i * 4, 4 * sizeof(float));
            o[4] = tp.power[size_t(i)] / 255.0f;
        }
    });
}

}  // namespace lumacut
