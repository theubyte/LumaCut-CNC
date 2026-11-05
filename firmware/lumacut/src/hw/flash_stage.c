// Update stage in upper flash, written from the main loop. The CPU stalls while
// flash is busy, which is fine: the update only runs at standstill, laser off.
#include "../config.h"
#include "../hal.h"
#include <libopencm3/stm32/flash.h>

#define FLASH_SIZE_REG (*(volatile uint16_t *)0x1FFFF7E0u)
#define STAGE_BYTES (UPDATE_MAX_BYTES)

uint32_t hal_flash_kb(void) { return FLASH_SIZE_REG; }

const uint8_t *hal_stage_data(void) { return (const uint8_t *)UPDATE_STAGE_ADDR; }

static void flash_open(void)
{
    if (FLASH_CR & FLASH_CR_LOCK) {
        FLASH_KEYR = FLASH_KEYR_KEY1;
        FLASH_KEYR = FLASH_KEYR_KEY2;
    }
    FLASH_SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
}

static bool flash_wait_ok(void)
{
    while (FLASH_SR & FLASH_SR_BSY) {
    }
    return !(FLASH_SR & (FLASH_SR_PGERR | FLASH_SR_WRPRTERR));
}

bool hal_stage_erase_page(uint32_t offset)
{
    if (offset >= STAGE_BYTES) return false;
    flash_open();
    FLASH_CR = FLASH_CR_PER;
    FLASH_AR = UPDATE_STAGE_ADDR + offset;
    FLASH_CR = FLASH_CR_PER | FLASH_CR_STRT;
    bool ok = flash_wait_ok();
    FLASH_CR = FLASH_CR_LOCK;
    const volatile uint32_t *p = (const volatile uint32_t *)(UPDATE_STAGE_ADDR + offset);
    return ok && p[0] == 0xFFFFFFFFu;
}

bool hal_stage_write(uint32_t offset, const uint8_t *data, size_t len)
{
    if (offset + len > STAGE_BYTES || (offset & 1u)) return false;
    flash_open();
    FLASH_CR = FLASH_CR_PG;
    bool ok = true;
    volatile uint16_t *dst = (volatile uint16_t *)(UPDATE_STAGE_ADDR + offset);
    for (size_t i = 0; i < len && ok; i += 2) {
        uint16_t word = data[i];
        word |= (uint16_t)((i + 1 < len ? data[i + 1] : 0xFFu) << 8);
        dst[i / 2] = word;
        ok = flash_wait_ok() && dst[i / 2] == word;
    }
    FLASH_CR = FLASH_CR_LOCK;
    return ok;
}
