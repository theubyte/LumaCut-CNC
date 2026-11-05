// Text output without printf, so no float formatting code ends up in the image.
#pragma once
#include <stdint.h>

void out_str(const char *s);
void out_u32(uint32_t v);
void out_i32(int32_t v);
void out_hex(uint32_t v);
void out_fix3(int32_t fix); // 1e-5 mm units as "-12.345"
void out_nl(void);
