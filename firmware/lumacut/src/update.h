// Self-update: receives the image into upper flash, verifies it, then hands
// over to the RAM copy routine. Polled from the main loop.
#pragma once
#include <stdbool.h>
#include <stdint.h>

// Answers its own ok lines. Returns false when the arguments are refused; the
// caller already wrote nothing, the error text is in *error.
bool update_begin(uint32_t bytes, uint32_t crc, const char **error);
bool update_active(void);
void update_poll(uint32_t now_ms);
void update_cancel(void);

// True when an image passes every check. Exposed for tests.
bool update_image_valid(const uint8_t *image, uint32_t bytes);
