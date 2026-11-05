// Step generation core: Bresenham, trapezoid rates, endstop stops, tones.
// All integer, no hardware access except through hal.h. src/hw/step_timer.c
// calls sg_pre and sg_post from the step interrupt; tests call them directly.
#pragma once
#include "config.h"
#include <stdbool.h>
#include <stdint.h>

typedef enum {
    SG_STOP_NONE = 0,
    SG_STOP_ENDSTOP, // rule 7: a switch in the driving direction opened
    SG_STOP_SEEK,    // homing or probing block reached its switch
    SG_STOP_ABORT,   // M112 or M410
    SG_STOP_UNDERRUN // block planned to run on, but the next one was not ready
} sg_stop_t;

void sg_init(void);

// Tick, part one: endstops, then the step mask to pulse now.
uint8_t sg_pre(uint8_t endstops_raw);
// Tick, part two: prepares the next tick. Returns its delay in timer ticks, or
// 0 when the stepper went idle. DIR changes (sg_dir) happen here, so they lead
// the next step by a full interval.
uint32_t sg_post(void);
uint8_t sg_dir(void); // axes in minus direction
bool sg_dir_changed(void); // reads and clears

// Main loop.
void sg_kick(void); // start ticking if frozen blocks wait and nothing is stopped
bool sg_running(void);
uint32_t sg_left_us(void);    // rough time left in the running block
uint32_t sg_started_us(void); // wrapping sum of planned durations of started blocks
void sg_tone_start(uint8_t axes, uint32_t half_period_ticks, uint32_t steps);

// Any context below the step interrupt.
void sg_abort(void);

sg_stop_t sg_stop_reason(void);
uint8_t sg_stop_axes(void);
void sg_stop_clear(void);

int32_t sg_count(int axis);
void sg_set_count(int axis, int32_t value); // stepper idle only
void sg_set_switch_zone(int axis, int32_t steps); // switch ignored at or below this count, -1 = never
