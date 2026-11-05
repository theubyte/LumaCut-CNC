// G2/G3 split into chords. Points are computed from the centre by index, so no
// error accumulates along the arc; the last point is exactly the target.
#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int32_t cx, cy; // centre, 1e-5 mm
    int32_t tx, ty; // target
    float radius_mm;
    float start_angle;
    float sweep; // signed, radians
    uint32_t segments;
} arc_t;

// False when the end point is not on the circle (> 0.5 mm off) or radius is 0.
bool arc_plan(arc_t *a, int32_t sx, int32_t sy, int32_t tx, int32_t ty, int32_t i, int32_t j,
              bool clockwise);
// Point k of 1..segments.
void arc_point(const arc_t *a, uint32_t k, int32_t *x, int32_t *y);
