#pragma once
#include <stddef.h>
#include <stdint.h>
// IEEE 802.3 CRC-32, same result as Python zlib.crc32. Start with 0.
uint32_t crc32_update(uint32_t crc, const uint8_t *data, size_t len);
