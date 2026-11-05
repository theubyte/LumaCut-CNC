// UART4 to the TMC2209 drivers, polled from the main loop. PC10 TX and PC11 RX
// share one wire through the board, so RX also hears what TX sends. No interrupt:
// a late byte only costs a retry, it can never touch steps or the laser PWM.
#include "../hal.h"
#include "board.h"
#include <libopencm3/cm3/nvic.h>
#include <libopencm3/stm32/usart.h>

// 115200: TMC_BAUD_RATE default for hardware serial, Marlin 2.1.2.9 trinamic.cpp.
// APB1 is 36 MHz.
#define UART_BRR 313u
#define PC10 (1u << 10)
#define PC11 (1u << 11)
#define LOOPS_PER_US 7u // rough; a polling pass takes at least 10 cycles, so waits only run long

void tmc_uart_init(void)
{
    RCC_APB1ENR |= RCC_APB1ENR_UART4EN;
    gpio_set_mode(GPIOC, GPIO_MODE_OUTPUT_50_MHZ, GPIO_CNF_OUTPUT_ALTFN_PUSHPULL, PC10);
    gpio_set_mode(GPIOC, GPIO_MODE_INPUT, GPIO_CNF_INPUT_PULL_UPDOWN, PC11);
    GPIO_BSRR(GPIOC) = PC11;
    USART_BRR(UART4) = UART_BRR;
    USART_CR1(UART4) = USART_CR1_UE | USART_CR1_TE | USART_CR1_RE;
}

void hal_tmc_bus_lock(bool locked)
{
    if (locked) nvic_disable_irq(NVIC_USB_LP_CAN_RX0_IRQ);
    else nvic_enable_irq(NVIC_USB_LP_CAN_RX0_IRQ);
}

void hal_tmc_send(const uint8_t *data, size_t len)
{
    while (USART_SR(UART4) & (USART_SR_RXNE | USART_SR_ORE)) (void)USART_DR(UART4);
    for (size_t i = 0; i < len; i++) {
        uint32_t guard = 300u * LOOPS_PER_US;
        while (!(USART_SR(UART4) & USART_SR_TXE) && guard--) {
        }
        USART_DR(UART4) = data[i];
        guard = 300u * LOOPS_PER_US;
        while (!(USART_SR(UART4) & USART_SR_TC) && guard--) {
        }
        (void)USART_SR(UART4);
        (void)USART_DR(UART4); // our own echo
    }
    // The last echo can land just after TC; a reply needs over 150 us at the earliest.
    uint32_t guard = 30u * LOOPS_PER_US;
    while (guard--) {
        if (USART_SR(UART4) & (USART_SR_RXNE | USART_SR_ORE)) (void)USART_DR(UART4);
    }
}

size_t hal_tmc_recv(uint8_t *data, size_t max, uint32_t timeout_us)
{
    size_t n = 0;
    uint32_t guard = timeout_us * LOOPS_PER_US;
    while (n < max && guard--) {
        uint32_t sr = USART_SR(UART4);
        if (sr & (USART_SR_RXNE | USART_SR_ORE)) {
            uint8_t byte = (uint8_t)USART_DR(UART4);
            if (sr & USART_SR_RXNE) data[n++] = byte;
        }
    }
    return n;
}
