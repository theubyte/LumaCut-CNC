// Pin map and the register-level safe state, usable from any context.
#pragma once
#include <libopencm3/stm32/gpio.h>
#include <libopencm3/stm32/rcc.h>
#include <libopencm3/stm32/timer.h>
#include <stdint.h>

// Pins follow docs/FIRMWARE_EIGEN.md (BTT plan of the Mini MZ V1.0).
#define LASER_PIN (1u << 9)  // PA9, TIM1 CH2
#define RELAY_PIN (1u << 6)  // PC6, FAN1 terminal
#define LIGHT_PIN (1u << 8)  // PC8, HE0, TIM8 CH3
#define EXHAUST_PIN (1u << 9) // PC9, BED
#define USB_PULLUP_PIN (1u << 13) // PC13, high = D+ pull-up off
#define USB_DP_PIN (1u << 12) // PA12

#define X_STEP (1u << 13) // PB
#define Y_STEP (1u << 10) // PB
#define Z_STEP (1u << 0)  // PB
#define X_DIR (1u << 12)  // PB
#define Y_DIR (1u << 2)   // PB
#define Z_DIR (1u << 5)   // PC
#define X_EN (1u << 14)   // PB, active low
#define Y_EN (1u << 11)   // PB, active low
#define Z_EN (1u << 1)    // PB, active low

// GPIO mode nibbles, RM0008 9.2.1.
#define NIBBLE_OUT_PP_2MHZ 0x2u
#define NIBBLE_AF_PP_2MHZ 0xAu
#define NIBBLE_IN_FLOAT 0x4u

// Beam, relay, light and exhaust off, step timer stopped. No function calls,
// no data access outside peripheral registers, no dependence on any clock or
// on what ran before: this runs first after reset and inside fault handlers.
// ODR goes low before the mode changes, so a pin never drives high in between.
__attribute__((always_inline)) static inline void board_safe_off(void)
{
    RCC_APB2ENR |= RCC_APB2ENR_IOPAEN | RCC_APB2ENR_IOPBEN | RCC_APB2ENR_IOPCEN;
    GPIO_BRR(GPIOA) = LASER_PIN;
    GPIO_BRR(GPIOC) = RELAY_PIN | LIGHT_PIN | EXHAUST_PIN;
    GPIO_CRH(GPIOA) = (GPIO_CRH(GPIOA) & ~(0xFu << 4)) | (NIBBLE_OUT_PP_2MHZ << 4); // PA9
    GPIO_CRL(GPIOC) = (GPIO_CRL(GPIOC) & ~(0xFu << 24)) | (NIBBLE_OUT_PP_2MHZ << 24); // PC6
    GPIO_CRH(GPIOC) = (GPIO_CRH(GPIOC) & ~0xFFu) | (NIBBLE_OUT_PP_2MHZ << 0) |
                      (NIBBLE_OUT_PP_2MHZ << 4); // PC8, PC9
    TIM_CR1(TIM2) = 0;
}

void board_init(void);
void board_iwdg_start(void);
void board_iwdg_feed(void);
void board_usb_disconnect(void); // D+ down, however the board pulls it up
void board_usb_release(void);    // D+ back to the USB peripheral

void outputs_init(void);
void step_timer_init(void);
void tmc_uart_init(void);
void usb_cdc_init(void);
void usb_cdc_shutdown(void);
void selfcopy_run(uint32_t bytes) __attribute__((noreturn));
