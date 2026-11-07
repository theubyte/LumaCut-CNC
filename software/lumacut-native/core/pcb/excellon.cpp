#include "core/pcb/excellon.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <string>

namespace lumacut::pcb {
namespace {

std::string trim(std::string_view s) {
    size_t a = 0, b = s.size();
    while (a < b && std::isspace(uchar(s[a]))) ++a;
    while (b > a && std::isspace(uchar(s[b - 1]))) --b;
    return std::string(s.substr(a, b - a));
}
std::string upper(std::string s) {
    for (char& c : s) c = char(std::toupper(uchar(c)));
    return s;
}
bool startsWith(const std::string& s, std::string_view p) { return s.rfind(p, 0) == 0; }
/** Number right after position p: [+-]?[\d.]+ ; empty if none. */
std::string numberAt(const std::string& s, size_t p) {
    size_t e = p;
    if (e < s.size() && (s[e] == '+' || s[e] == '-')) ++e;
    const size_t digits = e;
    while (e < s.size() && (std::isdigit(uchar(s[e])) || s[e] == '.')) ++e;
    return e > digits ? s.substr(p, e - p) : std::string();
}
/** "FILE_FORMAT=2:5" or "FORMAT={2:5": the two digit counts. */
bool formatComment(const std::string& line, int& ints, int& decs) {
    const std::string u = upper(line);
    size_t p = u.find("FORMAT");
    if (p == std::string::npos) return false;
    p += 6;
    while (p < u.size() && (u[p] == ' ' || u[p] == '=' || u[p] == '{')) ++p;
    size_t q = p;
    while (q < u.size() && std::isdigit(uchar(u[q]))) ++q;
    if (q == p || q >= u.size() || u[q] != ':') return false;
    size_t r = q + 1;
    while (r < u.size() && std::isdigit(uchar(u[r]))) ++r;
    if (r == q + 1) return false;
    ints = std::atoi(u.c_str() + p);
    decs = std::atoi(u.c_str() + q + 1);
    return true;
}

}  // namespace

ExcellonResult parseExcellon(std::string_view text) {
    ExcellonResult res;
    const auto warn = [&res](const QString& s) { if (!res.warnings.contains(s)) res.warnings.push_back(s); };
    double unit = 1;
    int zeros = 0;   // 0 unknown, 1 LZ (leading zeros kept), 2 TZ
    int intDigits = -1, decDigits = -1;
    int tool = 0;
    double x = 0, y = 0;
    bool incremental = false, routing = false, plunged = false, repeatSeen = false, implicit = false;

    const auto coord = [&](const std::string& raw) -> double {
        if (raw.find('.') != std::string::npos) return std::strtod(raw.c_str(), nullptr) * unit;
        implicit = true;
        const bool neg = !raw.empty() && raw[0] == '-';
        std::string digits = raw.substr(!raw.empty() && (raw[0] == '-' || raw[0] == '+') ? 1 : 0);
        int i = intDigits, d = decDigits;
        if (i < 0 || d < 0) { if (res.inch) { i = 2; d = 4; } else { i = 3; d = 3; } }
        // LZ: leading zeros kept, trailing ones may be missing, so the point counts from the left.
        // TZ (and no statement): the point counts from the right.
        if (zeros == 1 && int(digits.size()) < i + d) digits.append(size_t(i + d) - digits.size(), '0');
        const double v = std::strtod(digits.empty() ? "0" : digits.c_str(), nullptr) / std::pow(10.0, d);
        return (neg ? -v : v) * unit;
    };
    struct XY { double x, y; bool any; };
    const auto readXY = [&](const std::string& s, double fromX, double fromY) -> XY {
        XY r{fromX, fromY, false};
        const size_t px = s.find('X'), py = s.find('Y');
        if (px != std::string::npos) { const std::string n = numberAt(s, px + 1); if (!n.empty()) { r.x = (incremental ? fromX : 0) + coord(n); r.any = true; } }
        if (py != std::string::npos) { const std::string n = numberAt(s, py + 1); if (!n.empty()) { r.y = (incremental ? fromY : 0) + coord(n); r.any = true; } }
        return r;
    };
    const auto toolDia = [&](int t) { auto it = res.tools.find(t); return it == res.tools.end() ? 0.0 : it->second; };

    size_t pos = 0;
    while (pos <= text.size()) {
        size_t end = text.find_first_of("\r\n", pos);
        if (end == std::string_view::npos) end = text.size();
        const std::string line = trim(text.substr(pos, end - pos));
        pos = end + 1;
        if (line.empty()) { if (end == text.size()) break; continue; }
        if (line[0] == ';') { formatComment(line, intDigits, decDigits); continue; }
        std::string up = upper(line);
        if (startsWith(up, "METRIC") || startsWith(up, "INCH") || up == "M71" || up == "M72") {
            if (startsWith(up, "INCH") || up == "M72") { unit = 25.4; res.inch = true; } else { unit = 1; res.inch = false; }
            if (up.find("LZ") != std::string::npos) zeros = 1;
            else if (up.find("TZ") != std::string::npos) zeros = 2;
            // ",000.00": digit counts
            const size_t c = up.find(',');
            for (size_t k = c; k != std::string::npos; k = up.find(',', k + 1)) {
                size_t a = k + 1, b = a;
                while (b < up.size() && up[b] == '0') ++b;
                if (b > a && b < up.size() && up[b] == '.') {
                    size_t e = b + 1;
                    while (e < up.size() && up[e] == '0') ++e;
                    if (e > b + 1) { intDigits = int(b - a); decDigits = int(e - b - 1); }
                }
            }
            continue;
        }
        if (up == "ICI,ON" || up == "G91") { incremental = true; continue; }
        if (up == "ICI,OFF" || up == "G90") { incremental = false; continue; }
        if (startsWith(up, "M30") || up == "M00") break;
        if (up == "M15") { plunged = true; continue; }
        if (up == "M16" || up == "M17") { plunged = false; continue; }
        if (up == "G05") { routing = false; continue; }
        if (startsWith(up, "M48") || up == "%") continue;
        static const char* skip[] = {"FMAT", "VER", "ATC", "TCST", "DETECT", "AFS", "CCW", "CP", "BLKD", "SBK", "SG", "OSTOP", "PF", "LN", "EXTC", "MI"};
        if (std::any_of(std::begin(skip), std::end(skip), [&](const char* k) { return startsWith(up, k); })) continue;

        if (up[0] == 'T' && up.size() > 1 && std::isdigit(uchar(up[1]))) {
            size_t e = 1;
            while (e < up.size() && std::isdigit(uchar(up[e]))) ++e;
            const int t = std::atoi(up.c_str() + 1);
            if (e == up.size()) {
                tool = t;
                if (tool && !res.tools.count(tool)) warn(QStringLiteral("Werkzeug T%1 hat keinen Durchmesser.").arg(tool));
                continue;
            }
            const size_t c = up.find('C', e);
            if (c != std::string::npos) {
                const std::string n = numberAt(up, c + 1);
                if (!n.empty()) { tool = t; res.tools[t] = std::strtod(n.c_str(), nullptr) * unit; continue; }
            }
        }

        if (up[0] == 'R' && up.size() > 1 && std::isdigit(uchar(up[1]))) {
            repeatSeen = true;
            size_t e = 1;
            while (e < up.size() && std::isdigit(uchar(up[e]))) ++e;
            up = up.substr(e);
        }

        if (const size_t g85 = up.find("G85"); g85 != std::string::npos) {
            const XY a = readXY(up.substr(0, g85), x, y);
            const XY b = readXY(up.substr(g85 + 3), a.x, a.y);
            res.slotHoles.push_back({{a.x, a.y}, {b.x, b.y}, toolDia(tool), tool});
            x = b.x; y = b.y;
            continue;
        }
        if (up.size() >= 2 && up[0] == 'G') {
            const size_t s = up.size() > 2 && up[1] == '0' ? 2 : 1;
            if (s < up.size() && up[s] >= '0' && up[s] <= '3') routing = true;
        }
        const XY p = readXY(up, x, y);
        if (!p.any) {
            if (up[0] != 'G' && up[0] != 'M') warn(QStringLiteral("Zeile nicht verstanden: %1").arg(QString::fromStdString(line.substr(0, 30))));
            continue;
        }
        if (routing) {
            if (plunged) res.slotHoles.push_back({{x, y}, {p.x, p.y}, toolDia(tool), tool});
        } else {
            res.hits.push_back({p.x, p.y, toolDia(tool), tool});
        }
        x = p.x; y = p.y;
    }
    if (repeatSeen) warn(QStringLiteral("Wiederholungen (R) werden nicht unterstützt: nur der erste Treffer zählt."));
    if (implicit && zeros == 0 && intDigits < 0) warn(QStringLiteral("Datei nennt kein Zahlenformat: Standardformat angenommen, Maße prüfen."));
    const auto grow = [&](double px, double py, double d) {
        const Box b{px - d / 2, py - d / 2, px + d / 2, py + d / 2};
        res.bounds = res.bounds ? res.bounds->united(b) : b;
    };
    for (const DrillHit& h : res.hits) grow(h.x, h.y, h.dia);
    for (const DrillSlot& s : res.slotHoles) { grow(s.a.x, s.a.y, s.dia); grow(s.b.x, s.b.y, s.dia); }
    return res;
}

}  // namespace lumacut::pcb
