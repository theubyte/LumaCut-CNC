// Everything the logic modules need from the hardware. Implemented by src/hw
// on the target and by test/mock_hal.c on the PC.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

uint32_t hal_ms(void);
const char *hal_reset_cause(void);

// Critical sections are a few instructions only; TIM1/TIM8 run in hardware.
uint32_t hal_cs_enter(void);
void hal_cs_exit(uint32_t state);

// Outputs. hal_all_off() may run from any interrupt or fault context.
void hal_all_off(void);
void hal_outputs_arm(void); // after M999: PA9/PC8 back to timer output at 0
void hal_laser_pwm(uint8_t s);
void hal_relay(bool on);
void hal_exhaust(bool on);
void hal_light(uint8_t level);

void hal_motors(bool on);
uint8_t hal_endstops(void); // bit per axis, 1 = triggered (switch open)

// Step timer. hal_step_start fires the first tick after `ticks`.
void hal_step_start(uint32_t ticks);
void hal_step_stop(void);

// USB. Writes never block for long and drop data when no host reads.
void hal_usb_write(const char *data, size_t len);
bool hal_usb_tx_idle(void);
bool hal_usb_link_ok(void);
void hal_usb_rx_resume(void); // call after freeing receive space

// TMC UART, polled.
void hal_tmc_send(const uint8_t *data, size_t len);
size_t hal_tmc_recv(uint8_t *data, size_t max, uint32_t timeout_us);

// Update stage in upper flash.
uint32_t hal_flash_kb(void);
bool hal_stage_erase_page(uint32_t offset);
bool hal_stage_write(uint32_t offset, const uint8_t *data, size_t len);
const uint8_t *hal_stage_data(void);
void hal_selfcopy_and_reset(uint32_t bytes); // never returns on target
