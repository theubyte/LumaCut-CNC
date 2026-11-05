#include "gcode.h"
#include <string.h>

static char upper(char c) { return (c >= 'a' && c <= 'z') ? (char)(c - 32) : c; }
static bool is_digit(char c) { return c >= '0' && c <= '9'; }

static const char *skip_blank(const char *p)
{
    for (;;) {
        if (*p == ' ' || *p == '\t' || *p == '\r') {
            p++;
        } else if (*p == '(') {
            while (*p && *p != ')') p++;
            if (*p) p++;
        } else {
            return p;
        }
    }
}

// Reads [+-]digits[.digits]. False when there is no number or it is too large.
static bool read_number(const char **pp, int64_t *out)
{
    const char *p = *pp;
    bool neg = false;
    if (*p == '+' || *p == '-') neg = (*p++ == '-');
    if (!is_digit(*p) && !(*p == '.' && is_digit(p[1]))) return false;
    int64_t whole = 0;
    while (is_digit(*p)) {
        if (whole > 10000000000000LL) return false;
        whole = whole * 10 + (*p++ - '0');
    }
    int64_t frac = 0;
    if (*p == '.') {
        p++;
        int places = 0;
        while (is_digit(*p)) {
            if (places < 5) frac = frac * 10 + (*p - '0');
            else if (places == 5 && *p >= '5') frac++;
            places++;
            p++;
        }
        for (; places < 5; places++) frac *= 10;
    }
    int64_t v = whole * GC_UNIT + frac;
    *out = neg ? -v : v;
    *pp = p;
    return true;
}

gcode_status_t gcode_parse(const char *line, gcode_t *out)
{
    memset(out, 0, sizeof *out);
    const char *p = line;
    for (;;) {
        p = skip_blank(p);
        if (*p == 0 || *p == ';') break;
        char c = upper(*p);
        if (c < 'A' || c > 'Z') return GC_BAD;
        p++;
        p = skip_blank(p);
        int64_t v = 0;
        bool has_num = read_number(&p, &v);
        if (c == 'G' || c == 'M') {
            if (out->letter || !has_num || v < 0 || v % GC_UNIT || v / GC_UNIT > 999) return GC_BAD;
            out->letter = c;
            out->code = (uint16_t)(v / GC_UNIT);
            continue;
        }
        if (!out->letter) return GC_BAD; // parameters before the command, N words
        uint32_t bit = 1u << (c - 'A');
        if (out->seen & bit) return GC_BAD;
        out->seen |= bit;
        if (has_num) {
            out->numeric |= bit;
            out->val[c - 'A'] = v;
        } else if (*p && *p != ' ' && *p != '\t' && *p != ';' && *p != '(' && *p != '\r' &&
                   !(upper(*p) >= 'A' && upper(*p) <= 'Z')) {
            return GC_BAD; // "X-" or "X." style garbage
        }
    }
    return out->letter ? GC_OK : GC_EMPTY;
}

int gcode_realtime(const char *line, size_t len)
{
    size_t i = 0;
    while (i < len && (line[i] == ' ' || line[i] == '\t')) i++;
    if (i >= len || upper(line[i]) != 'M') return 0;
    i++;
    int code = 0, digits = 0;
    while (i < len && is_digit(line[i]) && digits < 4) {
        code = code * 10 + (line[i] - '0');
        i++;
        digits++;
    }
    if (digits != 3 || (code != 112 && code != 410)) return 0;
    while (i < len && (line[i] == ' ' || line[i] == '\t' || line[i] == '\r')) i++;
    if (i >= len || line[i] == ';' || line[i] == '(') return code;
    return 0;
}
