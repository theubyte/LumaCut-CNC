// Machine constants from docs/FIRMWARE_EIGEN.md. Nothing here is persistent.
#pragma once
#include <stdint.h>

#define AXES 3
enum { AX_X = 0, AX_Y = 1, AX_Z = 2 };

// Positions are integers in 1e-5 mm, so relative moves never accumulate
// rounding errors from decimal input.
#define FIX_PER_MM 100000
#define MM_FIX(mm) ((int32_t)((mm) * FIX_PER_MM))

#define Z_HARD_MAX_MM 80     // head leaves the Z rail above this; not changeable
#define Z_HARD_MAX_FEED 9.0f // mm/s, M203 Z cannot exceed it
// Without a Z reference the real height is unknown: Z may rise at most this far
// above where it stood when the reference was lost. Owner's value, only here.
#define Z_UNHOMED_LIFT_MM 25
#define STEPS_MM_MIN 1      // M92 plausibility
#define STEPS_MM_MAX 5000
#define DRIVER_CHECK_MS 1000u // GSTAT.reset at most this often

#define STEP_TICK_HZ 2000000u // TIM2 tick, see TIMERS.md
#define MAX_STEP_RATE 15000u  // steps/s per axis

#define QUEUE_SLOTS 128       // planner ring; 127 usable, contract asks >= 32; must span
                              // the braking distance plus the frozen PLAN_HORIZON_US
#define PLAN_GATE_BLOCKS 8    // start stepping once this many blocks wait...
#define PLAN_GATE_MS 30u      // ...or the oldest waited this long
#define PLAN_HORIZON_US 50000u // freeze blocks this far ahead of the stepper

#define JUNCTION_DEV_MM 0.05f
#define ARC_TOLERANCE_MM 0.02f // stricter than the contract's 0.1 mm

#define HOME_BACKOFF_MM 5.0f
#define HOME_OVERTRAVEL_MM 10.0f // search = travel + this
#define PROBE_FEED_MM_MIN 216.0f
#define PROBE_MIN_Z_FIX MM_FIX(-2)

#define USB_SILENCE_MS 5000u // rule 6
#define ARC_CHECK_SLICE 16u  // chords checked per main-loop pass
#define BUSY_PERIOD_MS 1000u
#define TONE_MAX_MS 2000u
#define TONE_MIN_HZ 40u
#define TONE_MAX_HZ 5000u

#define UPDATE_MAX_BYTES (196u * 1024u)
#define UPDATE_CHUNK 1024u
#define UPDATE_STAGE_ADDR 0x08040000u
#define APP_ADDR 0x08007000u
#define FLASH_PAGE 2048u
#define UPDATE_MIN_FLASH_KB 512u
#define UPDATE_TIMEOUT_MS 10000u
