// Reset path, clocks, SysTick, watchdog and fault handlers.
#include "board.h"
#include "../config.h"
#include "../hal.h"
#include <libopencm3/cm3/cortex.h>
#include <libopencm3/cm3/nvic.h>
#include <libopencm3/cm3/scb.h>
#include <libopencm3/cm3/systick.h>
#include <libopencm3/stm32/flash.h>
#include <libopencm3/stm32/iwdg.h>

int main(void);
extern uint32_t _data_loadaddr, _data, _edata, _ebss;

#define FAULT_MAGIC 0xFA175AFEu
__attribute__((section(".noinit"))) static uint32_t fault_magic;

static const char *reset_cause = "unknown";
static volatile uint32_t ms_now;

// Runs on whatever the bootloader left behind: interrupts possibly on, timers
// possibly configured. The safe state comes before everything else.
static void __attribute__((used, noreturn)) board_start(void)
{
    board_safe_off();
    cm_disable_interrupts();
    for (int i = 0; i < 3; i++) {
        NVIC_ICER(i) = 0xFFFFFFFFu;
        NVIC_ICPR(i) = 0xFFFFFFFFu;
    }
    STK_CSR = 0;
    SCB_VTOR = APP_ADDR;
    SCB_CCR |= SCB_CCR_STKALIGN;

    uint32_t *src = &_data_loadaddr, *dst = &_data;
    while (dst < &_edata) *dst++ = *src++;
    while (dst < &_ebss) *dst++ = 0;

    (void)main();
    for (;;) {
    }
}

void __attribute__((naked)) reset_handler(void)
{
    __asm__("cpsid i\n"
            "ldr r0, =_stack_top\n"
            "msr msp, r0\n"
            "b board_start\n"
            ".ltorg\n");
}

// Same order as the start: outputs first, on a known good stack, then reset.
static void __attribute__((used, noreturn)) fault_common(void)
{
    board_safe_off();
    fault_magic = FAULT_MAGIC;
    SCB_AIRCR = SCB_AIRCR_VECTKEY | SCB_AIRCR_SYSRESETREQ;
    for (;;) {
    }
}

#define FAULT_HANDLER(name)                                                                       \
    void __attribute__((naked)) name(void)                                                        \
    {                                                                                             \
        __asm__("cpsid i\n"                                                                       \
                "ldr r0, =_stack_top\n"                                                               \
                "msr msp, r0\n"                                                                   \
                "b fault_common\n"                                                                \
                ".ltorg\n");                                                                      \
    }

FAULT_HANDLER(nmi_handler)
FAULT_HANDLER(hard_fault_handler)
FAULT_HANDLER(mem_manage_handler)
FAULT_HANDLER(bus_fault_handler)
FAULT_HANDLER(usage_fault_handler)

void sys_tick_handler(void) { ms_now = ms_now + 1; }

uint32_t hal_ms(void) { return ms_now; }

uint32_t hal_cs_enter(void)
{
    uint32_t state;
    __asm__ volatile("mrs %0, primask\n cpsid i" : "=r"(state));
    return state;
}

void hal_cs_exit(uint32_t state) { __asm__ volatile("msr primask, %0" : : "r"(state)); }

const char *hal_reset_cause(void) { return reset_cause; }

static void read_reset_cause(void)
{
    uint32_t csr = RCC_CSR;
    if (fault_magic == FAULT_MAGIC) reset_cause = "fault";
    else if (csr & RCC_CSR_IWDGRSTF) reset_cause = "watchdog";
    else if (csr & RCC_CSR_SFTRSTF) reset_cause = "software";
    else if (csr & RCC_CSR_PORRSTF) reset_cause = "power";
    else if (csr & RCC_CSR_PINRSTF) reset_cause = "pin";
    fault_magic = 0;
    RCC_CSR = csr | RCC_CSR_RMVF;
}

// 8 MHz crystal, 72 MHz core, APB1 36, APB2 72, USB 48. The bootloader may
// already run on the PLL, so this goes through HSI first.
static void clock_setup(void)
{
    // USBPRE must not change while the USB clock runs; the bootloader may have left it on.
    RCC_APB1ENR &= ~RCC_APB1ENR_USBEN;
    RCC_CR |= RCC_CR_HSION;
    while (!(RCC_CR & RCC_CR_HSIRDY)) {
    }
    RCC_CFGR = 0; // SW = HSI, all prescalers 1
    while (RCC_CFGR & (3u << 2)) {
    }
    RCC_CR &= ~RCC_CR_PLLON;
    while (RCC_CR & RCC_CR_PLLRDY) {
    }
    RCC_CR |= RCC_CR_HSEON;
    while (!(RCC_CR & RCC_CR_HSERDY)) {
    }
    FLASH_ACR = FLASH_ACR_LATENCY_2WS | FLASH_ACR_PRFTBE;
    RCC_CFGR = (RCC_CFGR_PLLMUL_PLL_CLK_MUL9 << 18) | RCC_CFGR_PLLSRC | (4u << RCC_CFGR_PPRE1_SHIFT);
    RCC_CR |= RCC_CR_PLLON;
    while (!(RCC_CR & RCC_CR_PLLRDY)) {
    }
    RCC_CFGR |= 2u; // SW = PLL
    while ((RCC_CFGR & (3u << 2)) != (2u << 2)) {
    }
}

static void delay_cycles(uint32_t n)
{
    while (n--) __asm__ volatile("nop");
}

void board_usb_disconnect(void)
{
    // Marlin 2.1.2.9 HAL.cpp drives USB_CONNECT high to disconnect. PA14 is
    // SWCLK until AFIO releases it in board_init. PA12 low also pulls D+ down
    // directly, so the host sees the disconnect in any case.
    GPIO_BSRR(GPIOA) = USB_PULLUP_PIN;
    GPIO_CRH(GPIOA) = (GPIO_CRH(GPIOA) & ~(0xFu << 24)) | (NIBBLE_OUT_PP_2MHZ << 24);
    GPIO_BRR(GPIOA) = USB_DP_PIN;
    GPIO_CRH(GPIOA) = (GPIO_CRH(GPIOA) & ~(0xFu << 16)) | (NIBBLE_OUT_PP_2MHZ << 16);
}

void board_usb_release(void)
{
    GPIO_CRH(GPIOA) = (GPIO_CRH(GPIOA) & ~(0xFu << 16)) | (NIBBLE_IN_FLOAT << 16);
    GPIO_BRR(GPIOA) = USB_PULLUP_PIN;
}

void board_iwdg_start(void)
{
    // LSI 40 kHz / 64 = 625 Hz, reload 1250: about 2 s (LSI varies 30..60 kHz).
    // START first: it turns the LSI on, and without LSI the update flags in SR
    // never clear. Until the new values land the reset defaults give about 400 ms.
    IWDG_KR = IWDG_KR_START;
    IWDG_KR = IWDG_KR_UNLOCK;
    IWDG_PR = 4;
    IWDG_RLR = 1250;
    while (IWDG_SR) {
    }
    IWDG_KR = IWDG_KR_RESET;
}

void board_iwdg_feed(void) { IWDG_KR = IWDG_KR_RESET; }

void board_init(void)
{
    read_reset_cause();
    clock_setup();

    // Timers, UART and USB fresh from reset, whatever the bootloader did. PA9
    // and PC8 stay plain outputs at 0 until outputs_init has the timers at 0.
    RCC_APB2RSTR = RCC_APB2RSTR_TIM1RST | RCC_APB2RSTR_TIM8RST;
    RCC_APB2RSTR = 0;
    RCC_APB1RSTR = RCC_APB1RSTR_TIM2RST | RCC_APB1RSTR_UART4RST | RCC_APB1RSTR_USBRST;
    RCC_APB1RSTR = 0;
    RCC_APB2ENR |= RCC_APB2ENR_AFIOEN;
    // Release PA13/PA14 from SWD: PA14 switches the USB pull-up. Rescue is the SD card.
    AFIO_MAPR = (AFIO_MAPR & ~(7u << 24)) | (4u << 24);

    scb_set_priority_grouping(SCB_AIRCR_PRIGROUP_GROUP16_NOSUB);
    systick_set_clocksource(STK_CSR_CLKSOURCE_AHB);
    systick_set_reload(72000u - 1u);
    systick_clear();
    nvic_set_priority(NVIC_SYSTICK_IRQ, 0x80);
    systick_interrupt_enable();
    systick_counter_enable();

    outputs_init();
    step_timer_init();
    tmc_uart_init();

    // Host must notice the restart; about 250 ms at 72 MHz (at least 4 cycles a loop).
    board_usb_disconnect();
    delay_cycles(4500000u);
}
