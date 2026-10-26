/**
 * LumaCut: M300 S<Hz> P<ms> [X] [Y] - loud tones from the stepper coils
 * without moving the head (the board has no buzzer, so HAS_SOUND is off).
 *
 * Each tone alternates one microstep forward and one back, so the coil
 * current flips at the tone frequency while the net travel is exactly zero
 * (0.0125 mm peak at 80 steps/mm x16). The drivers switch from silent
 * StealthChop to SpreadCycle for the tone and back afterwards; currents and
 * Marlin's position counters are never touched.
 *
 * Refused while the laser is on. Waits until every planned move is done.
 * S0 is a rest of P ms. One call plays at most 2 s (watchdog), longer
 * melodies are a sequence of calls. Copied into Marlin by build.py.
 */
#include "../inc/MarlinConfig.h"

#if !HAS_SOUND

#include "../HAL/shared/Delay.h"
#include "../gcode/gcode.h"
#include "../module/planner.h"
#include "../module/stepper.h"
#include "../module/stepper/indirection.h"
#if HAS_TRINAMIC_CONFIG
  #include "../module/stepper/trinamic.h"
#endif
#if HAS_CUTTER
  #include "../feature/spindle_laser.h"
#endif

#ifndef INVERT_X_STEP_PIN
  #define INVERT_X_STEP_PIN false
#endif
#ifndef INVERT_Y_STEP_PIN
  #define INVERT_Y_STEP_PIN false
#endif

static void wait_us(uint32_t us) {
  // Long waits in slices so the watchdog keeps being fed.
  while (us > 1000) { DELAY_US(1000); hal.watchdog_refresh(); us -= 1000; }
  if (us) DELAY_US(us);
}

void GcodeSuite::M300() {
  const uint16_t freq = parser.ushortval('S', 440);
  const uint16_t ms = _MIN(parser.ushortval('P', 200), uint16_t(2000));
  // Without X/Y both axes sing (louder, same pitch).
  const bool any = parser.seen('X') || parser.seen('Y');
  const bool use_x = !any || parser.seen('X'), use_y = !any || parser.seen('Y');

  #if HAS_CUTTER
    if (cutter.enabled() || cutter.power) {
      SERIAL_ECHOLNPGM("echo:LumaCut M300 refused: laser on");
      return;
    }
  #endif

  planner.synchronize();
  if (freq == 0 || ms == 0) { wait_us(uint32_t(ms) * 1000UL); return; }
  if (freq < 40 || freq > 5000) { SERIAL_ECHOLNPGM("echo:LumaCut M300 S must be 40..5000 Hz"); return; }

  // Marlin only rewrites DIR when its own idea of the direction changes, so
  // the pins must end exactly as found or the next move could run backwards.
  const bool x_dir = READ(X_DIR_PIN), y_dir = READ(Y_DIR_PIN);

  if (use_x) stepper.enable_axis(X_AXIS);
  if (use_y) stepper.enable_axis(Y_AXIS);

  #if AXIS_IS_TMC(X)
    if (use_x) stepperX.en_spreadCycle(true);
  #endif
  #if AXIS_IS_TMC(Y)
    if (use_y) stepperY.en_spreadCycle(true);
  #endif

  // Two steps (forward + back) per period: one step every half period.
  const uint32_t half_us = 500000UL / freq;
  uint32_t steps = (uint32_t(ms) * freq) / 500UL;
  steps &= ~uint32_t(1);                 // even count: always back where it started

  bool forward = true;
  for (uint32_t i = 0; i < steps; i++) {
    if (use_x) X_DIR_WRITE(forward);
    if (use_y) Y_DIR_WRITE(forward);
    DELAY_US(1);
    if (use_x) X_STEP_WRITE(!INVERT_X_STEP_PIN);
    if (use_y) Y_STEP_WRITE(!INVERT_Y_STEP_PIN);
    DELAY_US(2);
    if (use_x) X_STEP_WRITE(INVERT_X_STEP_PIN);
    if (use_y) Y_STEP_WRITE(INVERT_Y_STEP_PIN);
    forward = !forward;
    wait_us(half_us > 3 ? half_us - 3 : 0);
    if ((i & 63) == 0) hal.watchdog_refresh();
  }

  X_DIR_WRITE(x_dir);
  Y_DIR_WRITE(y_dir);

  #if AXIS_IS_TMC(X)
    if (use_x) stepperX.refresh_stepping_mode();
  #endif
  #if AXIS_IS_TMC(Y)
    if (use_y) stepperY.refresh_stepping_mode();
  #endif
}

#endif // !HAS_SOUND
