#include "../cmd.h"
#include "board.h"
#include <libopencm3/cm3/cortex.h>

int main(void)
{
    board_init();
    cmd_init();
    usb_cdc_init();
    board_iwdg_start();
    cm_enable_interrupts();
    for (;;) {
        board_iwdg_feed(); // only here: a stuck loop resets into the safe state
        cmd_poll();
    }
}
