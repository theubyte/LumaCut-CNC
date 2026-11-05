// PC stand-in for the hardware: virtual time, a step-timer simulation, switches
// on a virtual machine, a fake TMC bus, fake flash and captured USB output.
#pragma once
#include "../src/config.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
    uint64_t now_ticks;
    bool timer_armed;
    uint64_t next_tick;

    int32_t phys[AXES];   // steps the motors really made, starting at 0
    uint32_t steps[AXES]; // pulses
    uint8_t sim_dir;
    uint32_t min_interval_ticks;
    uint32_t max_rate_seen;
    bool step_with_dir_change;

    // Switch model: triggered when phys[axis] <= trip[axis] and trip_on[axis].
    bool trip_on[AXES];
    int32_t trip[AXES];
    uint8_t force_open;   // bits forced triggered
    uint8_t spike_once;   // bits triggered for one sample only
    uint8_t spike_mask;   // bits triggered for spike_samples samples in a row
    uint32_t spike_samples;

    uint8_t pwm;
    uint32_t pwm_writes;
    bool all_off_called;
    bool armed_again;
    bool relay, exhaust, motors;
    uint8_t light;
    bool link_ok;

    // Rate trace of the fastest axis, per tick.
    bool trace_on;
    uint32_t trace_rate[200000];
    uint8_t trace_pwm[200000];       // while this step goes out
    uint8_t trace_pwm_after[200000]; // at the end of the same tick
    uint8_t trace_mask[200000];
    uint64_t trace_time[200000];
    size_t trace_n;

    // Test hooks: bytes that "arrive" at a chosen moment inside the main loop.
    const char *inject_after_pop;     // after a line was taken, before it runs
    bool inject_armed;
    const char *inject_at_link_check; // between reading the clock and comparing it

    bool tmc_dead;
    uint32_t tmc_gstat_reads;
    bool tmc_spread[4];
    uint32_t tmc_reg[4][128];
    uint32_t tmc_ifcnt[4];

    uint32_t flash_kb;
    uint8_t stage[256 * 1024];
    uint32_t selfcopy_bytes;
    bool stage_fail_write;
} sim_t;

extern sim_t sim;

void sim_reset(void); // fresh hardware and fresh firmware state
void sim_send(const char *text);       // bytes from the host, as the USB interrupt gets them
void sim_send_bytes(const uint8_t *data, size_t len);
void sim_run_ms(uint32_t ms);          // advance virtual time, main loop every 100 us
bool sim_run_until_idle(uint32_t max_ms);
void sim_stall_ms(uint32_t ms);        // like sim_run_ms, but the main loop hangs
void sim_step_one_pass(void);          // exactly one main-loop pass
const char *sim_out(void);             // text the firmware wrote since the last clear
void sim_out_clear(void);
int sim_ok_count(void);
bool sim_out_has(const char *needle);
// Sends a line and runs until its ok came. Returns the output of that line.
const char *sim_cmd(const char *line);
void sim_home_all_at_zero(void); // pretend G28 done: Z guard active etc.

// Tiny test framework.
extern int t_checks, t_failed;
void t_fail(const char *file, int line, const char *msg);
#define CHECK(c) do { t_checks++; if (!(c)) t_fail(__FILE__, __LINE__, #c); } while (0)
#define CHECK_NEAR(a, b, tol) do { t_checks++; double a_ = (double)(a), b_ = (double)(b); \
    if (a_ - b_ > (tol) || b_ - a_ > (tol)) { t_fail(__FILE__, __LINE__, #a " ~ " #b); \
    t_print_near(a_, b_); } } while (0)
void t_print_near(double a, double b);
