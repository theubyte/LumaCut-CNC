// Lookahead motion planner. Runs in the main loop only; float math is fine here.
//
// Blocks wait in a ring. Entry speeds are replanned on every new block. Shortly
// before the stepper needs a block it is "frozen": its integer profile is
// computed once and never changes again, so the step interrupt reads frozen
// blocks without any locking.
#pragma once
#include "config.h"
#include <stdbool.h>
#include <stdint.h>

enum { B_DWELL = 1, B_SEEK = 2 };

typedef struct {
    // Frozen part, read by the step interrupt.
    uint32_t steps[AXES];
    uint32_t count; // step events, the largest of steps[]
    uint32_t entry_rate, nominal_rate, exit_rate, floor_rate; // steps/s of the major axis
    uint32_t accel_q;     // (steps/s^2) * 2^32 / STEP_TICK_HZ
    uint32_t accel_until; // events
    uint32_t decel_after; // events
    uint32_t dwell_ticks;
    uint32_t duration_us; // planned time, rough
    uint8_t neg_mask;  // axes running in minus direction
    uint8_t stop_mask; // axes whose switch stops this block (rule 7)
    uint8_t power;     // laser S for this block
    uint8_t flags;
    bool exit_moving; // planned to run straight into the next block
    // Planner part.
    float mm, rate_per_mm, accel;
    float nominal_sqr, max_entry_sqr, back_sqr, entry_sqr;
} block_t;

typedef struct {
    float steps_mm[AXES];
    float max_feed[AXES];  // mm/s
    float max_accel[AXES]; // mm/s^2
} limits_t;

void planner_init(const limits_t *limits);

// False when the ring is full. A move that rounds to no step is accepted and
// queues nothing. `target` is absolute, in steps.
bool planner_line(const int32_t target[AXES], float speed, float accel, uint8_t power,
                  uint8_t flags);
bool planner_dwell(uint32_t ms);

// Call often from the main loop: freezes blocks and starts the stepper.
void planner_poll(uint32_t now_ms);
// A command waits for standstill: start at once instead of waiting for more.
void planner_request_flush(void);

void planner_flush(void); // stepper must be stopped
void planner_set_position(const int32_t steps[AXES]);
int32_t planner_position(int axis); // planned end position in steps

uint32_t planner_used(void);
uint32_t planner_free(void);
static inline bool planner_empty(void) { return planner_used() == 0; }

// Step interrupt side.
const block_t *planner_isr_next(void); // oldest frozen block or NULL
bool planner_isr_waiting(void);        // blocks exist that are not frozen yet
void planner_isr_release(void);
