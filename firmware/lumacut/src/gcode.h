// G-code line parser. Pure text handling, no machine state.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define GC_UNIT 100000 // numbers are kept in 1e-5 units

typedef struct {
    char letter;      // 'G' or 'M'
    uint16_t code;
    uint32_t seen;    // bit per letter
    uint32_t numeric; // bit per letter that carried a number
    int64_t val[26];
} gcode_t;

typedef enum { GC_OK, GC_EMPTY, GC_BAD } gcode_status_t;

gcode_status_t gcode_parse(const char *line, gcode_t *out);

static inline bool gc_has(const gcode_t *g, char c) { return (g->seen >> (c - 'A')) & 1u; }
static inline bool gc_num(const gcode_t *g, char c) { return (g->numeric >> (c - 'A')) & 1u; }
static inline int64_t gc_fix(const gcode_t *g, char c) { return g->val[c - 'A']; }
// Whole-number value, rounded toward zero.
static inline int64_t gc_int(const gcode_t *g, char c) { return g->val[c - 'A'] / GC_UNIT; }

// 112 or 410 when the line is exactly that M code (comments allowed), else 0.
// Interrupt safe: no floats, no state.
int gcode_realtime(const char *line, size_t len);
