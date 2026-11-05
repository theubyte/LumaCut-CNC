// Laser PWM (TIM1), light (TIM8), plain outputs, motor enables, endstops.
// Timer plan: see TIMERS.md.
#include "../hal.h"
#include "board.h"

// 72 MHz / 282 / 255 = 1001 Hz. Compare 0..255: 0 never high, 255 > ARR always high.
#define PWM_PSC 281u
#define PWM_ARR 254u

#define OCxM_PWM1 6u
#define CCMR_OC2PE (1u << 11)
#define CCMR_OC3PE (1u << 3)
#define CCER_CC2E (1u << 4)
#define CCER_CC3E (1u << 8)

static volatile uint8_t laser_now;

static void timers_start_at_zero(void)
{
    RCC_APB2ENR |= RCC_APB2ENR_TIM1EN | RCC_APB2ENR_TIM8EN;

    TIM_CR1(TIM1) = TIM_CR1_ARPE;
    TIM_PSC(TIM1) = PWM_PSC;
    TIM_ARR(TIM1) = PWM_ARR;
    TIM_CCR2(TIM1) = 0;
    TIM_CCMR1(TIM1) = (OCxM_PWM1 << 12) | CCMR_OC2PE; // preload: changes wait for the period end
    TIM_CCER(TIM1) = CCER_CC2E;
    TIM_BDTR(TIM1) = TIM_BDTR_MOE; // advanced timer: no output without MOE; no break input
    TIM_EGR(TIM1) = TIM_EGR_UG;    // load PSC, ARR and CCR2 = 0 into the shadows
    TIM_CR1(TIM1) |= TIM_CR1_CEN;

    TIM_CR1(TIM8) = TIM_CR1_ARPE;
    TIM_PSC(TIM8) = PWM_PSC;
    TIM_ARR(TIM8) = PWM_ARR;
    TIM_CCR3(TIM8) = 0;
    TIM_CCMR2(TIM8) = (OCxM_PWM1 << 4) | CCMR_OC3PE;
    TIM_CCER(TIM8) = CCER_CC3E;
    TIM_BDTR(TIM8) = TIM_BDTR_MOE;
    TIM_EGR(TIM8) = TIM_EGR_UG;
    TIM_CR1(TIM8) |= TIM_CR1_CEN;
}

// PA9 and PC8 become timer outputs only here, with both timers running at 0.
void hal_outputs_arm(void)
{
    uint32_t cs = hal_cs_enter();
    laser_now = 0;
    TIM_CCR2(TIM1) = 0;
    TIM_CCR3(TIM8) = 0;
    TIM_EGR(TIM1) = TIM_EGR_UG;
    TIM_EGR(TIM8) = TIM_EGR_UG;
    GPIO_CRH(GPIOA) = (GPIO_CRH(GPIOA) & ~(0xFu << 4)) | (NIBBLE_AF_PP_2MHZ << 4);
    GPIO_CRH(GPIOC) = (GPIO_CRH(GPIOC) & ~0xFu) | NIBBLE_AF_PP_2MHZ;
    hal_cs_exit(cs);
}

void outputs_init(void)
{
    timers_start_at_zero();
    hal_outputs_arm();

    // Drivers off before the pins become outputs (EN is active low).
    GPIO_BSRR(GPIOB) = X_EN | Y_EN | Z_EN;
    GPIO_BRR(GPIOB) = X_STEP | Y_STEP | Z_STEP;
    gpio_set_mode(GPIOB, GPIO_MODE_OUTPUT_50_MHZ, GPIO_CNF_OUTPUT_PUSHPULL,
                  X_EN | Y_EN | Z_EN | X_STEP | Y_STEP | Z_STEP | X_DIR | Y_DIR);
    gpio_set_mode(GPIOC, GPIO_MODE_OUTPUT_50_MHZ, GPIO_CNF_OUTPUT_PUSHPULL, Z_DIR);

    // Pressed pulls the pin low, unpressed reads high: Marlin needed
    // *_ENDSTOP_INVERTING true here. A broken wire reads as not pressed.
    // ENDSTOPPULLUPS is on in the Configurations example.
    gpio_set_mode(GPIOC, GPIO_MODE_INPUT, GPIO_CNF_INPUT_PULL_UPDOWN, GPIO0 | GPIO1 | GPIO2);
    GPIO_BSRR(GPIOC) = GPIO0 | GPIO1 | GPIO2;
}

void hal_all_off(void)
{
    board_safe_off();
    laser_now = 0;
    TIM_CCR2(TIM1) = 0;
    TIM_CCR3(TIM8) = 0;
}

// Changes between nonzero values wait for the period end (preload). Going to or
// from 0 takes effect at once: the beam must not outlast its block by up to 1 ms.
void hal_laser_pwm(uint8_t s)
{
    uint32_t cs = hal_cs_enter();
    uint8_t old = laser_now;
    laser_now = s;
    TIM_CCR2(TIM1) = s;
    if ((old == 0) != (s == 0)) TIM_EGR(TIM1) = TIM_EGR_UG;
    hal_cs_exit(cs);
}

void hal_relay(bool on)
{
    if (on) GPIO_BSRR(GPIOC) = RELAY_PIN;
    else GPIO_BRR(GPIOC) = RELAY_PIN;
}

void hal_exhaust(bool on)
{
    if (on) GPIO_BSRR(GPIOC) = EXHAUST_PIN;
    else GPIO_BRR(GPIOC) = EXHAUST_PIN;
}

void hal_light(uint8_t level) { TIM_CCR3(TIM8) = level; }

void hal_motors(bool on)
{
    if (on) {
        GPIO_BRR(GPIOB) = X_EN | Y_EN | Z_EN;
        for (volatile uint32_t i = 0; i < 20000u; i++) { // about 1 ms for the drivers to energize
        }
    } else {
        GPIO_BSRR(GPIOB) = X_EN | Y_EN | Z_EN;
    }
}

uint8_t hal_endstops(void) { return (uint8_t)(~GPIO_IDR(GPIOC) & 7u); }
