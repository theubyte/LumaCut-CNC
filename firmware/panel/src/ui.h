// LumaCut Bedienpanel: screens (light design, hardware/display-7zoll/design/mockup_weiss.html).
// All ui_* functions must be called with the LVGL lock held.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "cJSON.h"

void ui_init(void);
void ui_on_status(const cJSON *st);                               // {"t":"st",...}
void ui_on_result(const cJSON *res);                              // {"t":"res",...}
void ui_on_jobs(const cJSON *jobs);                               // {"t":"jobs",...}
void ui_on_image(const uint16_t *rgb565, int w, int h);           // decoded camera frame
bool ui_camera_wanted(void);                                      // camera screen open
