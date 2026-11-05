// TMC2209 drivers on the shared UART: frames, register values, setup, M122.
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

uint8_t tmc_crc8(const uint8_t *data, size_t len);
size_t tmc_frame_write(uint8_t *buf, uint8_t addr, uint8_t reg, uint32_t value); // 8 bytes
size_t tmc_frame_read(uint8_t *buf, uint8_t addr, uint8_t reg);                  // 4 bytes
// Finds the 8-byte reply in received bytes, which also hold our own echo.
bool tmc_find_reply(const uint8_t *rx, size_t n, uint8_t reg, uint32_t *value);

uint32_t tmc_gconf(bool spreadcycle);
uint32_t tmc_chopconf(void);
uint32_t tmc_ihold_irun(void);
uint32_t tmc_pwmconf(void);

// Writes the whole setup to all axes and reads it back. On failure returns
// false and names the first axis that did not answer correctly.
bool tmc_configure_all(uint8_t *failed_axis);
void tmc_spreadcycle(uint8_t axes, bool on);
void tmc_report(void); // M122
