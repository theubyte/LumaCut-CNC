#include "laser.h"
#include "hal.h"

static volatile bool inline_mode;
static volatile bool gate; // closed by laser_kill until the next M3
static volatile uint8_t modal_s;
static volatile uint8_t cont_power;

static void end_continuous(void)
{
    if (cont_power) {
        cont_power = 0;
        hal_laser_pwm(0);
    }
}

void laser_init(void)
{
    inline_mode = false;
    gate = false;
    modal_s = 0;
    cont_power = 0;
    hal_laser_pwm(0);
}

void laser_m3_inline(void)
{
    end_continuous();
    gate = true;
    inline_mode = true;
}

// Blocks already queued keep their power ("die Leistung gehoert zum Block"):
// a job's tail must still burn although M5 I does not wait for the queue.
// M410 and M112 are the commands that cut the beam at once.
void laser_m5_inline(void)
{
    laser_m5();
    inline_mode = false;
}

void laser_m5(void)
{
    modal_s = 0;
    end_continuous();
}

void laser_m3_continuous(uint8_t s)
{
    // A kill from an interrupt must not land between flag and output.
    uint32_t cs = hal_cs_enter();
    inline_mode = false;
    gate = s > 0;
    cont_power = s;
    hal_laser_pwm(s);
    hal_cs_exit(cs);
}

void laser_set_modal(uint8_t s) { modal_s = s; }

uint8_t laser_block_power(bool rapid)
{
    if (rapid || !inline_mode) return 0;
    return modal_s;
}

void laser_motion_queued(void) { end_continuous(); }

void laser_first_step(uint8_t power) { hal_laser_pwm(gate ? power : 0); }

void laser_dwell(void)
{
    if (!cont_power) hal_laser_pwm(0);
}

void laser_block_gap(void)
{
    if (!cont_power) hal_laser_pwm(0);
}

void laser_kill(void)
{
    gate = false;
    inline_mode = false;
    modal_s = 0;
    cont_power = 0;
    hal_laser_pwm(0);
}

bool laser_is_inline(void) { return inline_mode; }
uint8_t laser_continuous(void) { return cont_power; }
