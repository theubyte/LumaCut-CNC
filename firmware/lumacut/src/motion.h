// Machine position, limits and modal motion state. Main loop only.
#pragma once
#include "config.h"
#include "planner.h"
#include <stdbool.h>
#include <stdint.h>

typedef enum { MOVE_OK, MOVE_FULL, MOVE_OUT_OF_BOUNDS } move_result_t;

void motion_init(void);
limits_t *motion_limits(void);

int32_t motion_pos(int axis); // planned position, 1e-5 mm
bool motion_in_bounds(const int32_t target[AXES]);

// Straight move to a target in 1e-5 mm. Checks bounds, queues the block.
move_result_t motion_move(const int32_t target[AXES], float speed, float accel, uint8_t power);

// Move bypassing the travel check, for homing and probing. Relative, in mm.
bool motion_seek(int axis, float delta_mm, float speed, bool stop_on_switch);

// Machine stopped: drop all blocks, position comes from the step counters.
void motion_resync(void);

// G92 for one axis. Stepper idle. False when outside the axis travel.
bool motion_set_position(int axis, int32_t fix);
// Homing finished: this spot is now physically 0.
void motion_zero_axis(int axis);
// M92. Stepper idle. The position in mm stays.
void motion_set_steps_mm(int axis, float steps_mm);

bool motion_homed(int axis);
void motion_set_unhomed(uint8_t axes);
int32_t motion_fix_from_steps(int axis, int32_t steps);

bool motion_idle(void); // queue empty and stepper stopped

// Motor current: configures drivers before the first enable (rule 8).
bool motors_ensure(uint8_t *failed_axis);
bool motors_are_on(void);
void motors_off(void);
