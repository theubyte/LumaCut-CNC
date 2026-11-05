// Receive side between the USB interrupt and the main loop. M112 and M410 are
// recognised here, on arrival, and never reach the line store.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define RX_LINE_MAX 96
#define RX_REPORTED_LINES 16
#define RX_RESERVE_LINES 32 // one 64-byte packet can hold this many short lines
#define RX_SLOTS (RX_REPORTED_LINES + RX_RESERVE_LINES)
#define RX_RAW_SIZE 4096u

void rx_init(void);

// USB interrupt side. rx_can_take_packet decides the USB NAK.
void rx_feed(const uint8_t *data, size_t len);
bool rx_can_take_packet(void);

// Main loop side.
const char *rx_peek(bool *too_long, bool *discard); // NULL when empty
void rx_pop(void);
uint8_t rx_free_lines(void);
uint32_t rx_last_line_ms(void);
void rx_mark_discard(void); // lines already received get a bare ok only

// Raw mode for the self-update.
void rx_set_raw(bool on);
size_t rx_raw_read(uint8_t *dst, size_t max);

// Provided by the command layer, called from the USB interrupt.
void cmd_rt_m112(void);
void cmd_rt_m410(void);
