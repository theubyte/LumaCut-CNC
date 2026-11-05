// G28 and G30 as polled state machines, so the main loop keeps running.
#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef enum { SEEK_BUSY, SEEK_DONE, SEEK_FAILED } seek_status_t;

void homing_start(uint8_t axes);
seek_status_t homing_poll(void);

// False when the switch is already open ("Probe already triggered").
bool probe_start(void);
seek_status_t probe_poll(void);

// Set by the command layer when a seek block stopped on its switch.
void homing_note_switch_hit(void);
