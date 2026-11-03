// LumaCut Bedienpanel: entry point.
#include "board.h"
#include "link.h"
#include "lvgl_port.h"
#include "ui.h"

void app_main(void)
{
    board_init();
    if (lvgl_port_lock(-1)) {
        ui_init();
        lvgl_port_unlock();
    }
    link_start();
}
