// Copies the verified image from the stage to the application slot, then resets.
//
// ram_copy lives in RAM (.ramfunc, copied at start with .data). With interrupts
// and faults masked it erases the running program, so it must not touch flash in
// any way: no calls (helpers are forced inline, scripts/check_ramfunc.py checks
// the built image), no const data, literals inside the section. The watchdog is
// fed throughout. A power cut here is what the SD card rescue is for.
#include "../config.h"
#include "../hal.h"
#include "board.h"
#include <libopencm3/cm3/scb.h>
#include <libopencm3/stm32/flash.h>
#include <libopencm3/stm32/iwdg.h>

#define COPY_ATTEMPTS 3

__attribute__((always_inline)) static inline void wait_flash(void)
{
    while (FLASH_SR & FLASH_SR_BSY) IWDG_KR = IWDG_KR_RESET;
}

__attribute__((section(".ramfunc"), noinline, long_call, noreturn, used,
               optimize("no-tree-loop-distribute-patterns")))
static void ram_copy(const volatile uint16_t *src, volatile uint16_t *dst, uint32_t bytes)
{
    __asm__ volatile("cpsid i\n cpsid f");
    IWDG_KR = IWDG_KR_RESET;
    wait_flash();
    FLASH_KEYR = FLASH_KEYR_KEY1;
    FLASH_KEYR = FLASH_KEYR_KEY2;

    uint32_t halves = (bytes + 1u) / 2u;
    for (int attempt = 0; attempt < COPY_ATTEMPTS; attempt++) {
        for (uint32_t off = 0; off < bytes; off += FLASH_PAGE) {
            FLASH_SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
            FLASH_CR = FLASH_CR_PER;
            FLASH_AR = APP_ADDR + off;
            FLASH_CR = FLASH_CR_PER | FLASH_CR_STRT;
            wait_flash();
        }
        FLASH_SR = FLASH_SR_EOP | FLASH_SR_PGERR | FLASH_SR_WRPRTERR;
        FLASH_CR = FLASH_CR_PG;
        for (uint32_t i = 0; i < halves; i++) {
            dst[i] = src[i];
            wait_flash();
        }
        FLASH_CR = 0;
        uint32_t bad = 0;
        for (uint32_t i = 0; i < halves; i++) {
            if (dst[i] != src[i]) bad++;
            IWDG_KR = IWDG_KR_RESET;
        }
        if (bad == 0) break;
    }
    FLASH_CR = FLASH_CR_LOCK;
    SCB_AIRCR = SCB_AIRCR_VECTKEY | SCB_AIRCR_SYSRESETREQ;
    for (;;) {
    }
}

void hal_selfcopy_and_reset(uint32_t bytes)
{
    (void)hal_cs_enter();
    hal_all_off();
    hal_motors(false);
    usb_cdc_shutdown();
    ram_copy((const volatile uint16_t *)UPDATE_STAGE_ADDR, (volatile uint16_t *)APP_ADDR, bytes);
}
