// Laser rules 4, 5 and 6 of the contract, without hardware access.
#pragma once
#include <stdbool.h>
#include <stdint.h>

void laser_init(void);

// Commands (main loop).
void laser_m3_inline(void);          // M3 I
void laser_m5_inline(void);          // M5 I: mode off, new moves carry no power
void laser_m5(void);                 // M5: power off, mode stays
void laser_m3_continuous(uint8_t s); // M3 S<n>, only called at standstill
void laser_set_modal(uint8_t s);     // S word on G1/G2/G3

// Power a new block gets. G0 is always 0, outside inline mode too.
uint8_t laser_block_power(bool rapid);
void laser_motion_queued(void); // rule 5: a move ends continuous power

// Step interrupt.
void laser_block_load(uint8_t power);
void laser_first_step(uint8_t power);
void laser_dwell(void);
void laser_block_gap(void); // no block running

// Any context: M410, endstop, USB loss, silence.
void laser_kill(void);

bool laser_is_inline(void);
uint8_t laser_continuous(void);
