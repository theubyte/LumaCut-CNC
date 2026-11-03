// Waveshare ESP32-S3-Touch-LCD-7: RGB panel 800x480, GT911 touch, CH422G IO expander.
#pragma once

#include <stdbool.h>
#include "esp_err.h"

esp_err_t board_init(void);        // display, touch and LVGL; backlight on
void board_backlight(bool on);
