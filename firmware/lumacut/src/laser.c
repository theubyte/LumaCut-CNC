#include "laser.h"
#include "hal.h"

static volatile bool inline_mode;
static volatile bool gate; // closed by laser_kill until the next M3
static volatile uint8_t modal_s;
static volatile uint8_t cont_power;
static volatile uint8_t output;

static void set_output(uint8_t s)
{
    output = s;
    hal_laser_pwm(s);
}

static void end_continuous(void)
{
    if (cont_power) {
        cont_power = 0;
        set_output(0);
    }
}

void laser_init(void)
{
    inline_mode = false;
    gate = false;
    modal_s = 0;
    cont_power = 0;
    set_output(0);
}

void laser_m3_inline(void)
{
    end_continuous();
    modal_s = 0; // no power left over from before; S comes with the job
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
    set_output(s);
    hal_cs_exit(cs);
}

void laser_set_modal(uint8_t s) { modal_s = s; }

uint8_t laser_block_power(bool rapid)
{
    if (rapid || !inline_mode) return 0;
    return modal_s;
}

void laser_motion_queued(void) { end_continuous(); }

// Going down must not wait for the first step: from standstill that is 7 ms
// away, with the beam on a standing head. Going up waits for that step.
void laser_block_load(uint8_t power)
{
    uint8_t p = gate ? power : 0;
    if (p < output) set_output(p);
}

void laser_first_step(uint8_t power) { set_output(gate ? power : 0); }

void laser_dwell(void)
{
    if (!cont_power) set_output(0);
}

void laser_block_gap(void)
{
    if (!cont_power) set_output(0);
}

void laser_kill(void)
{
    gate = false;
    inline_mode = false;
    modal_s = 0;
    cont_power = 0;
    set_output(0);
}

bool laser_is_inline(void) { return inline_mode; }
uint8_t laser_continuous(void) { return cont_power; }
