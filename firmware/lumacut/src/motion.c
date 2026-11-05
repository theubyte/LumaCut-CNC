#include "motion.h"
#include "hal.h"
#include "stepgen.h"
#include "tmc.h"

static limits_t lim;
static int32_t pos_fix[AXES];
static int32_t z_offset_fix; // physical Z = logical Z + this, changed by G92 Z
static uint8_t homed;
static bool motors_on;

static const int32_t MIN_FIX[AXES] = {0, 0, MM_FIX(-2)};
static const int32_t MAX_FIX[AXES] = {MM_FIX(390), MM_FIX(370), MM_FIX(Z_HARD_MAX_MM)};

static int32_t round_to_i32(double v) { return (int32_t)(v < 0.0 ? v - 0.5 : v + 0.5); }

static int32_t steps_from_fix(int axis, int32_t fix)
{
    return round_to_i32((double)fix * (double)lim.steps_mm[axis] / FIX_PER_MM);
}

int32_t motion_fix_from_steps(int axis, int32_t steps)
{
    return round_to_i32((double)steps * FIX_PER_MM / (double)lim.steps_mm[axis]);
}

void motion_init(void)
{
    static const limits_t defaults = {
        .steps_mm = {80.0f, 80.0f, 1018.59f},
        .max_feed = {150.0f, 150.0f, Z_HARD_MAX_FEED},
        .max_accel = {500.0f, 500.0f, 100.0f},
    };
    lim = defaults;
    for (int a = 0; a < AXES; a++) pos_fix[a] = 0;
    z_offset_fix = 0;
    homed = 0;
    motors_on = false;
    hal_motors(false);
}

limits_t *motion_limits(void) { return &lim; }
int32_t motion_pos(int axis) { return pos_fix[axis]; }

bool motion_in_bounds(const int32_t target[AXES])
{
    for (int a = 0; a < AXES; a++) {
        if (target[a] == pos_fix[a]) continue;
        if (target[a] < MIN_FIX[a] || target[a] > MAX_FIX[a]) return false;
    }
    // After G92 Z the logical value is shifted; the physical limit still holds.
    if ((homed & (1u << AX_Z)) && target[AX_Z] != pos_fix[AX_Z] &&
        target[AX_Z] + z_offset_fix > MM_FIX(Z_HARD_MAX_MM)) {
        return false;
    }
    return true;
}

move_result_t motion_move(const int32_t target[AXES], float speed, float accel, uint8_t power)
{
    if (!motion_in_bounds(target)) return MOVE_OUT_OF_BOUNDS;
    int32_t steps[AXES];
    for (int a = 0; a < AXES; a++) steps[a] = steps_from_fix(a, target[a]);
    if (!planner_line(steps, speed, accel, power, 0)) return MOVE_FULL;
    for (int a = 0; a < AXES; a++) pos_fix[a] = target[a];
    return MOVE_OK;
}

bool motion_seek(int axis, float delta_mm, float speed, bool stop_on_switch)
{
    int32_t steps[AXES];
    for (int a = 0; a < AXES; a++) steps[a] = planner_position(a);
    steps[axis] += round_to_i32((double)delta_mm * (double)lim.steps_mm[axis]);
    float accel = lim.max_accel[axis];
    if (!planner_line(steps, speed, accel, 0, stop_on_switch ? B_SEEK : 0)) return false;
    pos_fix[axis] = motion_fix_from_steps(axis, steps[axis]);
    return true;
}

void motion_resync(void)
{
    planner_flush();
    int32_t steps[AXES];
    for (int a = 0; a < AXES; a++) {
        steps[a] = sg_count(a);
        pos_fix[a] = motion_fix_from_steps(a, steps[a]);
    }
    planner_set_position(steps);
}

static void apply_position(int axis, int32_t fix)
{
    pos_fix[axis] = fix;
    int32_t steps[AXES];
    for (int a = 0; a < AXES; a++) steps[a] = planner_position(a);
    steps[axis] = steps_from_fix(axis, fix);
    planner_set_position(steps);
    sg_set_count(axis, steps[axis]);
}

bool motion_set_position(int axis, int32_t fix)
{
    if (fix < MIN_FIX[axis] || fix > MAX_FIX[axis]) return false;
    if (axis == AX_Z) z_offset_fix += pos_fix[AX_Z] - fix;
    apply_position(axis, fix);
    return true;
}

void motion_zero_axis(int axis)
{
    if (axis == AX_Z) z_offset_fix = 0;
    apply_position(axis, 0);
    homed |= (uint8_t)(1u << axis);
}

void motion_set_steps_mm(int axis, float steps_mm)
{
    lim.steps_mm[axis] = steps_mm;
    apply_position(axis, pos_fix[axis]);
}

bool motion_homed(int axis) { return (homed >> axis) & 1u; }
void motion_set_unhomed(uint8_t axes) { homed &= (uint8_t)~axes; }

bool motion_idle(void) { return planner_empty() && !sg_running(); }

bool motors_ensure(uint8_t *failed_axis)
{
    if (motors_on) return true;
    if (!tmc_configure_all(failed_axis)) return false;
    hal_motors(true);
    motors_on = true;
    return true;
}

bool motors_are_on(void) { return motors_on; }

void motors_off(void)
{
    hal_motors(false);
    motors_on = false;
}
