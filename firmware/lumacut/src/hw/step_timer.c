// TIM2 step interrupt, the highest interrupt priority. Timer plan: see TIMERS.md.
//
// TMC2209 needs STEP high and DIR setup of at least 20 ns; the contract asks for
// 100 ns each. STEP high is held by a fixed NOP count, which cannot run faster
// than one cycle (13.9 ns) per NOP. DIR only changes after STEP fell, and the
// next STEP is at least ARM_MARGIN ticks (4 us) away.
#include "../config.h"
#include "../hal.h"
#include "../stepgen.h"
#include "board.h"
#include <libopencm3/cm3/nvic.h>

#define PSC_2MHZ 35u      // timer clock 72 MHz (APB1 36 MHz, doubled for timers)
#define MAX_RELOAD 60000u // longer waits run in pieces
#define ARM_MARGIN 8u     // ticks; the reload must stay ahead of the counter

#define NOP4 "nop\n nop\n nop\n nop\n"
#define NOP36 NOP4 NOP4 NOP4 NOP4 NOP4 NOP4 NOP4 NOP4 NOP4 // >= 500 ns at 72 MHz
#define NOP8 NOP4 NOP4                                     // >= 111 ns at 72 MHz

static uint32_t wait_left;

// Directions as Marlin 2.1.2.9 stepper.cpp SET_STEP_DIR with firmware/marlin/build.py
// (INVERT_X_DIR false, INVERT_Y_DIR false, INVERT_Z_DIR true): plus direction
// writes !INVERT, so X+ and Y+ are DIR high, Z+ is DIR low.
static void dir_apply(uint8_t neg)
{
    uint32_t b_set = 0, b_clr = 0;
    if (neg & (1u << AX_X)) b_clr |= X_DIR;
    else b_set |= X_DIR;
    if (neg & (1u << AX_Y)) b_clr |= Y_DIR;
    else b_set |= Y_DIR;
    GPIO_BSRR(GPIOB) = b_set | (b_clr << 16);
    if (neg & (1u << AX_Z)) GPIO_BSRR(GPIOC) = Z_DIR;
    else GPIO_BRR(GPIOC) = Z_DIR;
}

static void arm(uint32_t ticks)
{
    if (ticks > MAX_RELOAD) {
        wait_left = ticks - MAX_RELOAD;
        ticks = MAX_RELOAD;
    }
    uint32_t now = TIM_CNT(TIM2);
    if (ticks < now + ARM_MARGIN) ticks = now + ARM_MARGIN;
    TIM_ARR(TIM2) = ticks - 1u;
}

void tim2_isr(void)
{
    TIM_SR(TIM2) = ~TIM_SR_UIF;
    if (wait_left) {
        uint32_t ticks = wait_left;
        wait_left = 0;
        arm(ticks);
        return;
    }

    static const uint16_t STEP_BITS[8] = {
        0,
        X_STEP,
        Y_STEP,
        X_STEP | Y_STEP,
        Z_STEP,
        X_STEP | Z_STEP,
        Y_STEP | Z_STEP,
        X_STEP | Y_STEP | Z_STEP,
    };
    uint32_t bits = STEP_BITS[sg_pre((uint8_t)(GPIO_IDR(GPIOC) & 7u)) & 7u];
    if (bits) {
        GPIO_BSRR(GPIOB) = bits;
        __asm__ volatile(NOP36);
    }
    uint32_t next = sg_post();
    if (bits) {
        GPIO_BRR(GPIOB) = bits;
    }
    if (sg_dir_changed()) {
        __asm__ volatile(NOP8);
        dir_apply(sg_dir());
    }
    if (next) arm(next);
    else hal_step_stop();
}

void step_timer_init(void)
{
    RCC_APB1ENR |= RCC_APB1ENR_TIM2EN;
    TIM_CR1(TIM2) = 0; // ARPE off: a new ARR counts for the running interval
    TIM_PSC(TIM2) = PSC_2MHZ;
    TIM_ARR(TIM2) = MAX_RELOAD;
    TIM_EGR(TIM2) = TIM_EGR_UG; // load the prescaler
    TIM_SR(TIM2) = 0;
    TIM_DIER(TIM2) = TIM_DIER_UIE;
    nvic_set_priority(NVIC_TIM2_IRQ, 0x00);
    nvic_enable_irq(NVIC_TIM2_IRQ);
}

void hal_step_start(uint32_t ticks)
{
    if (sg_dir_changed()) dir_apply(sg_dir());
    wait_left = 0;
    TIM_CNT(TIM2) = 0;
    arm(ticks);
    TIM_SR(TIM2) = 0;
    nvic_clear_pending_irq(NVIC_TIM2_IRQ);
    TIM_CR1(TIM2) |= TIM_CR1_CEN;
}

void hal_step_stop(void)
{
    TIM_CR1(TIM2) &= ~TIM_CR1_CEN;
    TIM_SR(TIM2) = 0;
    wait_left = 0;
    nvic_clear_pending_irq(NVIC_TIM2_IRQ);
}
