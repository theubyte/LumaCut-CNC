#include "arc.h"
#include "config.h"
#include <math.h>

#define TWO_PI 6.2831853f

bool arc_plan(arc_t *a, int32_t sx, int32_t sy, int32_t tx, int32_t ty, int32_t i, int32_t j,
              bool clockwise)
{
    if (i == 0 && j == 0) return false;
    a->cx = sx + i;
    a->cy = sy + j;
    a->tx = tx;
    a->ty = ty;
    float fi = (float)i / FIX_PER_MM, fj = (float)j / FIX_PER_MM;
    float rs = sqrtf(fi * fi + fj * fj);
    float ex = (float)(tx - a->cx) / FIX_PER_MM, ey = (float)(ty - a->cy) / FIX_PER_MM;
    float re = sqrtf(ex * ex + ey * ey);
    if (rs < 0.001f || fabsf(rs - re) > 0.5f) return false;
    a->radius_mm = rs;
    a->start_angle = atan2f(-fj, -fi);
    float sweep = atan2f(ey, ex) - a->start_angle;
    if (clockwise) {
        if (sweep >= 0.0f) sweep -= TWO_PI;
    } else {
        if (sweep <= 0.0f) sweep += TWO_PI;
    }
    a->sweep = sweep;
    // Sagitta e = r(1-cos(t/2)), so chord angle t = 2 acos(1 - e/r).
    float step = (rs <= ARC_TOLERANCE_MM) ? TWO_PI : 2.0f * acosf(1.0f - ARC_TOLERANCE_MM / rs);
    uint32_t n = (uint32_t)ceilf(fabsf(sweep) / step);
    a->segments = n ? n : 1;
    return true;
}

void arc_point(const arc_t *a, uint32_t k, int32_t *x, int32_t *y)
{
    if (k >= a->segments) {
        *x = a->tx;
        *y = a->ty;
        return;
    }
    float t = a->start_angle + a->sweep * (float)k / (float)a->segments;
    *x = a->cx + (int32_t)lroundf(cosf(t) * a->radius_mm * FIX_PER_MM);
    *y = a->cy + (int32_t)lroundf(sinf(t) * a->radius_mm * FIX_PER_MM);
}
