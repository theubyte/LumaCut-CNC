#include "stepgen.h"
#include "hal.h"
#include "laser.h"
#include "planner.h"

#define STARVE_TICKS 200u // 100 us: re-check for a frozen block

static const block_t *volatile cur;
static uint32_t ev_done;
static volatile uint32_t ev_left;
static uint32_t err[AXES];
static uint32_t rate;
static uint32_t phase_ticks; // time in the current ramp
static uint32_t last_interval;
static uint32_t decel_from;
static bool decel_started;
static uint8_t next_mask;
static bool first_step;
static uint8_t prev_raw;

static volatile bool running;
static uint8_t dir_neg;
static bool dir_dirty;
static volatile int32_t counts[AXES];
static volatile uint32_t started_us;

static volatile uint32_t tone_left;
static uint32_t tone_half;
static uint8_t tone_axes;

static volatile sg_stop_t stop_reason;
static volatile uint8_t stop_axes;

void sg_init(void)
{
    cur = 0;
    next_mask = 0;
    running = false;
    dir_neg = 0;
    dir_dirty = true;
    tone_left = 0;
    stop_reason = SG_STOP_NONE;
    stop_axes = 0;
    ev_left = 0;
    started_us = 0;
    for (int a = 0; a < AXES; a++) counts[a] = 0;
}

static void halt(sg_stop_t reason, uint8_t axes)
{
    hal_step_stop();
    cur = 0;
    next_mask = 0;
    running = false;
    tone_left = 0;
    ev_left = 0;
    if (stop_reason == SG_STOP_NONE || reason == SG_STOP_ABORT) {
        stop_axes = axes;
        stop_reason = reason;
    }
}

uint8_t sg_pre(uint8_t endstops_raw)
{
    if (tone_left) return tone_axes;

    uint8_t stable = endstops_raw & prev_raw; // two samples in a row filter spikes
    prev_raw = endstops_raw;
    const block_t *b = cur;
    if (!b) return 0;
    uint8_t hit = stable & b->stop_mask;
    if (hit) {
        bool seek = (b->flags & B_SEEK) != 0;
        if (seek) laser_block_gap();
        else laser_kill();
        halt(seek ? SG_STOP_SEEK : SG_STOP_ENDSTOP, hit);
        return 0;
    }
    uint8_t mask = next_mask;
    if (mask) {
        for (int a = 0; a < AXES; a++) {
            if (mask & (1u << a)) counts[a] += (dir_neg & (1u << a)) ? -1 : 1;
        }
        if (first_step) {
            first_step = false;
            laser_first_step(b->power);
        }
    }
    return mask;
}

static uint8_t bresenham(const block_t *b)
{
    uint8_t mask = 0;
    for (int a = 0; a < AXES; a++) {
        err[a] += b->steps[a];
        if (err[a] >= b->count) {
            err[a] -= b->count;
            mask |= (uint8_t)(1u << a);
        }
    }
    return mask;
}

// (accel_q * ticks) >> 32 is the speed gained in `ticks`, without a division.
static uint32_t ramp(uint32_t accel_q, uint32_t ticks)
{
    return (uint32_t)(((uint64_t)accel_q * ticks) >> 32);
}

static void update_rate(const block_t *b)
{
    if (ev_done < b->accel_until) {
        phase_ticks += last_interval;
        rate = b->entry_rate + ramp(b->accel_q, phase_ticks);
        if (rate > b->nominal_rate) rate = b->nominal_rate;
    } else if (ev_done >= b->decel_after) {
        if (!decel_started) {
            decel_started = true;
            decel_from = rate;
            phase_ticks = 0;
        } else {
            phase_ticks += last_interval;
        }
        uint32_t lost = ramp(b->accel_q, phase_ticks);
        rate = decel_from > lost + b->exit_rate ? decel_from - lost : b->exit_rate;
    } else {
        rate = b->nominal_rate;
    }
    if (rate < b->floor_rate) rate = b->floor_rate;
}

static uint32_t load_next(void)
{
    const block_t *b = planner_isr_next();
    if (!b) {
        laser_block_gap();
        if (planner_isr_waiting()) return STARVE_TICKS;
        running = false;
        return 0;
    }
    started_us += b->duration_us;
    cur = b;
    if (b->flags & B_DWELL) {
        laser_dwell();
        next_mask = 0;
        ev_left = 0;
        return b->dwell_ticks ? b->dwell_ticks : 1u;
    }
    if (dir_neg != b->neg_mask) dir_dirty = true;
    dir_neg = b->neg_mask;
    ev_done = 0;
    ev_left = b->count;
    for (int a = 0; a < AXES; a++) err[a] = b->count / 2;
    rate = b->entry_rate;
    phase_ticks = 0;
    decel_started = false;
    first_step = true;
    next_mask = bresenham(b);
    last_interval = (STEP_TICK_HZ + rate - 1u) / rate; // rounded up: never above the rate limit
    return last_interval;
}

uint32_t sg_post(void)
{
    if (!running) return 0;
    if (tone_left) {
        if (--tone_left == 0) {
            running = false;
            return 0;
        }
        dir_neg ^= tone_axes;
        dir_dirty = true;
        return tone_half;
    }
    const block_t *b = cur;
    if (!b) return load_next();
    if (b->flags & B_DWELL) {
        cur = 0;
        planner_isr_release();
        return load_next();
    }
    ev_done++;
    ev_left = b->count - ev_done;
    if (ev_done >= b->count) {
        cur = 0;
        next_mask = 0;
        planner_isr_release();
        return load_next();
    }
    update_rate(b);
    next_mask = bresenham(b);
    last_interval = (STEP_TICK_HZ + rate - 1u) / rate; // rounded up: never above the rate limit
    return last_interval;
}

uint8_t sg_dir(void) { return dir_neg; }

bool sg_dir_changed(void)
{
    bool d = dir_dirty;
    dir_dirty = false;
    return d;
}

void sg_kick(void)
{
    uint32_t cs = hal_cs_enter();
    if (!running && stop_reason == SG_STOP_NONE && planner_isr_next()) {
        running = true;
        prev_raw = 0;
        hal_step_start(20);
    }
    hal_cs_exit(cs);
}

bool sg_running(void) { return running; }

uint32_t sg_left_us(void)
{
    const block_t *b = cur;
    if (!b) return 0u;
    if (b->flags & B_DWELL) return b->duration_us;
    return (uint32_t)((uint64_t)b->duration_us * ev_left / b->count);
}

uint32_t sg_started_us(void) { return started_us; }

void sg_tone_start(uint8_t axes, uint32_t half_period_ticks, uint32_t steps)
{
    uint32_t cs = hal_cs_enter();
    if (!running && stop_reason == SG_STOP_NONE) {
        tone_axes = axes;
        tone_half = half_period_ticks;
        tone_left = steps;
        dir_neg = 0;
        dir_dirty = true;
        running = true;
        hal_step_start(half_period_ticks);
    }
    hal_cs_exit(cs);
}

void sg_abort(void) { halt(SG_STOP_ABORT, 0); }

sg_stop_t sg_stop_reason(void) { return stop_reason; }
uint8_t sg_stop_axes(void) { return stop_axes; }

void sg_stop_clear(void)
{
    stop_reason = SG_STOP_NONE;
    stop_axes = 0;
}

int32_t sg_count(int axis) { return counts[axis]; }
void sg_set_count(int axis, int32_t value) { counts[axis] = value; }
