#include "homing.h"
#include "config.h"
#include "hal.h"
#include "motion.h"

typedef enum { H_NEXT_AXIS, H_FAST, H_BACKOFF, H_SLOW } home_state_t;

static const uint8_t ORDER[AXES] = {AX_Z, AX_X, AX_Y};
static const float FEED_MM_S[AXES] = {3000.0f / 60.0f, 3000.0f / 60.0f, 432.0f / 60.0f};
static const float TRAVEL_MM[AXES] = {390.0f, 370.0f, 82.0f};

static uint8_t pending;
static uint8_t order_i;
static int axis;
static home_state_t state;
static bool hit;

void homing_note_switch_hit(void) { hit = true; }

static bool triggered(int a) { return (hal_endstops() >> a) & 1u; }

void homing_start(uint8_t axes)
{
    pending = axes;
    order_i = 0;
    state = H_NEXT_AXIS;
    hit = false;
}

static seek_status_t queue_or_fail(float delta, float speed, bool to_switch)
{
    hit = false;
    if (!motion_seek(axis, delta, speed, to_switch)) return SEEK_FAILED;
    planner_request_flush();
    return SEEK_BUSY;
}

seek_status_t homing_poll(void)
{
    if (!motion_idle()) {
        planner_request_flush();
        return SEEK_BUSY;
    }
    switch (state) {
    case H_NEXT_AXIS:
        while (order_i < AXES && !(pending & (1u << ORDER[order_i]))) order_i++;
        if (order_i == AXES) return SEEK_DONE;
        axis = ORDER[order_i++];
        motion_set_unhomed((uint8_t)(1u << axis));
        if (triggered(axis)) {
            state = H_BACKOFF;
            return queue_or_fail(HOME_BACKOFF_MM, FEED_MM_S[axis], false);
        }
        state = H_FAST;
        return queue_or_fail(-(TRAVEL_MM[axis] + HOME_OVERTRAVEL_MM), FEED_MM_S[axis], true);
    case H_FAST:
        if (!hit) return SEEK_FAILED;
        state = H_BACKOFF;
        return queue_or_fail(HOME_BACKOFF_MM, FEED_MM_S[axis], false);
    case H_BACKOFF:
        if (triggered(axis)) return SEEK_FAILED;
        state = H_SLOW;
        return queue_or_fail(-2.0f * HOME_BACKOFF_MM, FEED_MM_S[axis] / 4.0f, true);
    case H_SLOW:
        if (!hit) return SEEK_FAILED;
        motion_zero_axis(axis);
        state = H_NEXT_AXIS;
        return SEEK_BUSY;
    }
    return SEEK_FAILED;
}

static bool probe_moving;

bool probe_start(void)
{
    hit = false;
    probe_moving = false;
    return !triggered(AX_Z);
}

seek_status_t probe_poll(void)
{
    if (!motion_idle()) {
        planner_request_flush();
        return SEEK_BUSY;
    }
    if (!probe_moving) {
        float delta = (float)(PROBE_MIN_Z_FIX - motion_pos(AX_Z)) / FIX_PER_MM;
        if (delta >= 0.0f) return SEEK_FAILED;
        probe_moving = true;
        if (!motion_seek(AX_Z, delta, PROBE_FEED_MM_MIN / 60.0f, true)) return SEEK_FAILED;
        planner_request_flush();
        return SEEK_BUSY;
    }
    return hit ? SEEK_DONE : SEEK_FAILED;
}
