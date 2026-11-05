#include "planner.h"
#include "hal.h"
#include "stepgen.h"
#include <math.h>

static block_t q[QUEUE_SLOTS];
static volatile uint32_t tail;   // owned by the step interrupt
static volatile uint32_t frozen; // first block not frozen yet
static uint32_t head;            // next free slot; main loop only

static const limits_t *lim;
static int32_t pos[AXES];
static float prev_unit[AXES];
static float prev_accel, prev_nominal_sqr;
static bool prev_valid;
static float pin_sqr; // exit speed^2 of the last frozen block
static bool gate_open, flush_req;
static uint32_t first_ms;
static uint32_t frozen_total_us; // wraps; minus sg_started_us() = frozen, not started

static uint32_t next_i(uint32_t i) { return (i + 1) % QUEUE_SLOTS; }
static uint32_t prev_i(uint32_t i) { return (i + QUEUE_SLOTS - 1) % QUEUE_SLOTS; }

void planner_init(const limits_t *limits)
{
    lim = limits;
    for (int a = 0; a < AXES; a++) pos[a] = 0;
    planner_flush();
}

void planner_flush(void)
{
    head = tail = frozen = 0;
    prev_valid = false;
    pin_sqr = 0.0f;
    gate_open = false;
    flush_req = false;
    frozen_total_us = sg_started_us();
}

void planner_set_position(const int32_t steps[AXES])
{
    for (int a = 0; a < AXES; a++) pos[a] = steps[a];
    prev_valid = false;
}

int32_t planner_position(int axis) { return pos[axis]; }

uint32_t planner_used(void) { return (head + QUEUE_SLOTS - tail) % QUEUE_SLOTS; }
uint32_t planner_free(void) { return QUEUE_SLOTS - 1 - planner_used(); }
void planner_request_flush(void) { flush_req = true; }

const block_t *planner_isr_next(void) { return tail == frozen ? 0 : &q[tail]; }
bool planner_isr_waiting(void) { return tail != head; }
void planner_isr_release(void) { tail = next_i(tail); }

// Backward pass limits entries by what the following blocks can brake to; it
// stops where nothing changes. Forward pass then limits by what can be reached.
static void replan(void)
{
    uint32_t newest = prev_i(head);
    uint32_t first = frozen;
    block_t *n = &q[newest];
    float limit = 2.0f * n->accel * n->mm;
    n->back_sqr = n->max_entry_sqr < limit ? n->max_entry_sqr : limit;

    uint32_t start = newest;
    while (start != first) {
        uint32_t i = prev_i(start);
        block_t *b = &q[i];
        float cap = q[start].back_sqr + 2.0f * b->accel * b->mm;
        if (cap > b->max_entry_sqr) cap = b->max_entry_sqr;
        start = i;
        if (cap == b->back_sqr) break;
        b->back_sqr = cap;
    }

    for (uint32_t i = start;; i = next_i(i)) {
        block_t *b = &q[i];
        if (i == first) {
            b->entry_sqr = pin_sqr;
        } else {
            const block_t *p = &q[prev_i(i)];
            float reach = p->entry_sqr + 2.0f * p->accel * p->mm;
            b->entry_sqr = b->back_sqr < reach ? b->back_sqr : reach;
        }
        if (i == newest) break;
    }
}

static float junction_sqr(const float unit[AXES], float accel)
{
    float dot = 0.0f;
    for (int a = 0; a < AXES; a++) dot += prev_unit[a] * unit[a];
    if (dot > 0.99999f) return 1e12f;
    if (dot < -0.99999f) return 0.0f;
    // Corner angle t between the two segments: cos t = -dot.
    float sin_half = sqrtf(0.5f * (1.0f + dot));
    float a = accel < prev_accel ? accel : prev_accel;
    return a * JUNCTION_DEV_MM * sin_half / (1.0f - sin_half);
}

bool planner_line(const int32_t target[AXES], float speed, float accel, uint8_t power,
                  uint8_t flags)
{
    if (planner_free() == 0) return false;

    int32_t delta[AXES];
    uint32_t count = 0;
    float sum = 0.0f;
    float mm_axis[AXES];
    for (int a = 0; a < AXES; a++) {
        delta[a] = target[a] - pos[a];
        uint32_t s = (uint32_t)(delta[a] < 0 ? -delta[a] : delta[a]);
        if (s > count) count = s;
        mm_axis[a] = (float)delta[a] / lim->steps_mm[a];
        sum += mm_axis[a] * mm_axis[a];
    }
    if (count == 0) return true;

    if (head == tail) {
        first_ms = hal_ms();
        gate_open = false;
    }

    block_t *b = &q[head];
    float mm = sqrtf(sum);
    float unit[AXES];
    b->neg_mask = 0;
    b->stop_mask = 0;
    for (int a = 0; a < AXES; a++) {
        b->steps[a] = (uint32_t)(delta[a] < 0 ? -delta[a] : delta[a]);
        unit[a] = mm_axis[a] / mm;
        if (delta[a] < 0) {
            b->neg_mask |= (uint8_t)(1u << a);
            b->stop_mask |= (uint8_t)(1u << a);
        }
        if (b->steps[a]) {
            float u = fabsf(unit[a]);
            float v = lim->max_feed[a] / u;
            if (v < speed) speed = v;
            v = (float)MAX_STEP_RATE / lim->steps_mm[a] / u;
            if (v < speed) speed = v;
            v = lim->max_accel[a] / u;
            if (v < accel) accel = v;
        }
    }

    b->count = count;
    b->mm = mm;
    b->rate_per_mm = (float)count / mm;
    b->accel = accel;
    b->nominal_sqr = speed * speed;
    b->power = power;
    b->flags = flags;
    b->dwell_ticks = 0;

    float entry = 0.0f;
    if (prev_valid && head != tail) {
        entry = junction_sqr(unit, accel);
        if (entry > b->nominal_sqr) entry = b->nominal_sqr;
        if (entry > prev_nominal_sqr) entry = prev_nominal_sqr;
    }
    b->max_entry_sqr = entry;
    b->back_sqr = 0.0f;
    b->entry_sqr = 0.0f;
    b->duration_us = 0u;

    for (int a = 0; a < AXES; a++) {
        prev_unit[a] = unit[a];
        pos[a] = target[a];
    }
    prev_accel = accel;
    prev_nominal_sqr = b->nominal_sqr;
    prev_valid = true;

    head = next_i(head);
    replan();
    return true;
}

bool planner_dwell(uint32_t ms)
{
    if (planner_free() == 0) return false;
    if (head == tail) {
        first_ms = hal_ms();
        gate_open = false;
    }
    block_t *b = &q[head];
    b->steps[0] = b->steps[1] = b->steps[2] = 0;
    b->count = 0;
    b->neg_mask = 0;
    b->stop_mask = 0;
    b->power = 0;
    b->flags = B_DWELL;
    b->dwell_ticks = ms * (STEP_TICK_HZ / 1000u);
    b->mm = 0.0f;
    b->rate_per_mm = 0.0f;
    b->accel = 1.0f;
    b->nominal_sqr = 0.0f;
    b->max_entry_sqr = 0.0f;
    b->back_sqr = 0.0f;
    b->entry_sqr = 0.0f;
    b->duration_us = 0u;
    prev_valid = false;
    head = next_i(head);
    replan();
    return true;
}

// Integer trapezoid for a block whose entry and exit speeds are final.
static void freeze_one(void)
{
    block_t *b = &q[frozen];
    uint32_t after = next_i(frozen);
    float exit_sqr = (after == head) ? 0.0f : q[after].entry_sqr;

    if (b->flags & B_DWELL) {
        b->duration_us = b->dwell_ticks / (STEP_TICK_HZ / 1000000u);
    } else {
        float k = b->rate_per_mm;
        float a = b->accel * k; // steps/s^2
        float n = (float)b->count;
        float e2 = b->entry_sqr * k * k, x2 = exit_sqr * k * k, v2 = b->nominal_sqr * k * k;
        float up = (v2 - e2) / (2.0f * a);
        float down = (v2 - x2) / (2.0f * a);
        if (up < 0.0f) up = 0.0f;
        if (down < 0.0f) down = 0.0f;
        if (up + down > n) {
            up = 0.5f * (n + (x2 - e2) / (2.0f * a));
            if (up < 0.0f) up = 0.0f;
            if (up > n) up = n;
            down = n - up;
            v2 = e2 + 2.0f * a * up;
            if (x2 > v2) v2 = x2;
        }
        uint32_t floor_rate = (uint32_t)sqrtf(0.5f * a);
        uint32_t nominal = (uint32_t)sqrtf(v2);
        if (nominal < 1u) nominal = 1u;
        if (floor_rate < 1u) floor_rate = 1u;
        if (floor_rate > nominal) floor_rate = nominal;
        uint32_t entry = (uint32_t)sqrtf(e2), exit_rate = (uint32_t)sqrtf(x2);
        if (entry < floor_rate) entry = floor_rate;
        if (exit_rate < floor_rate) exit_rate = floor_rate;
        if (entry > nominal) entry = nominal;
        if (exit_rate > nominal) exit_rate = nominal;
        b->entry_rate = entry;
        b->nominal_rate = nominal;
        b->exit_rate = exit_rate;
        b->floor_rate = floor_rate;
        float aq = a * (4294967296.0f / (float)STEP_TICK_HZ);
        b->accel_q = aq < 4.0e9f ? (uint32_t)aq : 4000000000u;
        b->accel_until = (uint32_t)(up + 0.5f);
        uint32_t d = (uint32_t)(down + 0.5f);
        b->decel_after = d >= b->count ? 0u : b->count - d;
        if (b->decel_after < b->accel_until) b->decel_after = b->accel_until;
        float mean = 0.25f * (float)(entry + exit_rate) + 0.5f * (float)nominal;
        float us = n / mean * 1e6f;
        b->duration_us = us < 4.0e9f ? (uint32_t)us : 4000000000u;
    }
    pin_sqr = exit_sqr;
    frozen_total_us += b->duration_us;
    frozen = after; // publishes the block to the step interrupt
}

void planner_poll(uint32_t now_ms)
{
    if (frozen != head) {
        if (!gate_open && (flush_req || sg_running() || planner_used() >= PLAN_GATE_BLOCKS ||
                           now_ms - first_ms >= PLAN_GATE_MS)) {
            gate_open = true;
        }
        if (gate_open) {
            // Time still ahead of the stepper: frozen blocks not started yet
            // plus the rest of the running one.
            uint32_t left = (frozen_total_us - sg_started_us()) + sg_left_us();
            while (frozen != head && left < PLAN_HORIZON_US) {
                const block_t *b = &q[frozen];
                freeze_one();
                left += b->duration_us;
            }
        }
    }
    if (tail != frozen) sg_kick();
    if (tail == head) flush_req = false;
}
