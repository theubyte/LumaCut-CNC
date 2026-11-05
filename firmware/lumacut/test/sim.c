#include "sim.h"
#include "../src/cmd.h"
#include "../src/hal.h"
#include "../src/planner.h"
#include "../src/rxlines.h"
#include "../src/stepgen.h"
#include "../src/tmc.h"
#include <stdio.h>
#include <string.h>

sim_t sim;
static char out_buf[1 << 20];
static size_t out_len;
int t_checks, t_failed;

void t_fail(const char *file, int line, const char *msg)
{
    t_failed++;
    printf("FAIL %s:%d: %s\n", file, line, msg);
}

void t_print_near(double a, double b) { printf("     got %.6f, want %.6f\n", a, b); }

// --- hal.h ------------------------------------------------------------------

uint32_t hal_ms(void)
{
    if (sim.inject_armed && sim.inject_after_pop) {
        const char *text = sim.inject_after_pop;
        sim.inject_after_pop = 0;
        sim.inject_armed = false;
        sim_send(text);
    }
    return (uint32_t)(sim.now_ticks / (STEP_TICK_HZ / 1000u));
}
const char *hal_reset_cause(void) { return "test"; }
uint32_t hal_cs_enter(void) { return 0; }
void hal_cs_exit(uint32_t state) { (void)state; }

void hal_all_off(void)
{
    sim.all_off_called = true;
    sim.pwm = 0;
    sim.relay = false;
    sim.exhaust = false;
    sim.light = 0;
    sim.timer_armed = false;
}

void hal_outputs_arm(void)
{
    sim.armed_again = true;
    sim.pwm = 0;
}

void hal_laser_pwm(uint8_t s)
{
    sim.pwm = s;
    sim.pwm_writes++;
}

void hal_relay(bool on) { sim.relay = on; }
void hal_exhaust(bool on) { sim.exhaust = on; }
void hal_light(uint8_t level) { sim.light = level; }
void hal_motors(bool on) { sim.motors = on; }

uint8_t hal_endstops(void)
{
    uint8_t e = sim.force_open;
    for (int a = 0; a < AXES; a++) {
        if (sim.trip_on[a] && sim.phys[a] <= sim.trip[a]) e |= (uint8_t)(1u << a);
    }
    return e;
}

void hal_step_start(uint32_t ticks)
{
    if (sg_dir_changed()) sim.sim_dir = sg_dir();
    sim.timer_armed = true;
    sim.next_tick = sim.now_ticks + ticks;
}

void hal_step_stop(void) { sim.timer_armed = false; }

void hal_usb_write(const char *data, size_t len)
{
    if (out_len + len < sizeof out_buf) {
        memcpy(out_buf + out_len, data, len);
        out_len += len;
        out_buf[out_len] = 0;
    }
}

bool hal_usb_tx_idle(void) { return true; }
bool hal_usb_link_ok(void)
{
    if (sim.inject_at_link_check) {
        const char *text = sim.inject_at_link_check;
        sim.inject_at_link_check = 0;
        sim.now_ticks += STEP_TICK_HZ / 1000u;
        sim_send(text);
    }
    return sim.link_ok;
}

void hal_usb_rx_resume(void) { sim.inject_armed = sim.inject_after_pop != 0; }

// Fake TMC bus: frames arrive through hal_tmc_send, replies wait for hal_tmc_recv.
static uint8_t tmc_reply[8];
static size_t tmc_reply_len;

void hal_tmc_send(const uint8_t *data, size_t len)
{
    tmc_reply_len = 0;
    if (sim.tmc_dead) return;
    uint8_t addr = data[1];
    if (addr > 3) return;
    if (len == 8 && tmc_crc8(data, 7) == data[7] && (data[2] & 0x80u)) {
        uint8_t reg = data[2] & 0x7Fu;
        uint32_t v = ((uint32_t)data[3] << 24) | ((uint32_t)data[4] << 16) |
                     ((uint32_t)data[5] << 8) | data[6];
        if (reg == 0x01) sim.tmc_reg[addr][reg] &= ~v; // GSTAT: write 1 to clear
        else sim.tmc_reg[addr][reg] = v;
        sim.tmc_ifcnt[addr]++;
    } else if (len == 4 && tmc_crc8(data, 3) == data[3]) {
        uint8_t reg = data[2];
        if (reg == 0x01) sim.tmc_gstat_reads++;
        uint32_t v = reg == 0x02 ? sim.tmc_ifcnt[addr] : sim.tmc_reg[addr][reg & 0x7Fu];
        tmc_reply[0] = 0x05;
        tmc_reply[1] = 0xFF;
        tmc_reply[2] = reg;
        tmc_reply[3] = (uint8_t)(v >> 24);
        tmc_reply[4] = (uint8_t)(v >> 16);
        tmc_reply[5] = (uint8_t)(v >> 8);
        tmc_reply[6] = (uint8_t)v;
        tmc_reply[7] = tmc_crc8(tmc_reply, 7);
        tmc_reply_len = 8;
    }
}

size_t hal_tmc_recv(uint8_t *data, size_t max, uint32_t timeout_us)
{
    (void)timeout_us;
    size_t n = tmc_reply_len < max ? tmc_reply_len : max;
    memcpy(data, tmc_reply, n);
    tmc_reply_len = 0;
    return n;
}

uint32_t hal_flash_kb(void) { return sim.flash_kb; }

bool hal_stage_erase_page(uint32_t offset)
{
    if (offset + FLASH_PAGE > sizeof sim.stage) return false;
    memset(sim.stage + offset, 0xFF, FLASH_PAGE);
    return true;
}

bool hal_stage_write(uint32_t offset, const uint8_t *data, size_t len)
{
    if (sim.stage_fail_write || offset + len > sizeof sim.stage) return false;
    memcpy(sim.stage + offset, data, len);
    return true;
}

const uint8_t *hal_stage_data(void) { return sim.stage; }
void hal_selfcopy_and_reset(uint32_t bytes) { sim.selfcopy_bytes = bytes; }

// --- simulation -------------------------------------------------------------

void sim_reset(void)
{
    memset(&sim, 0, sizeof sim);
    sim.link_ok = true;
    sim.flash_kb = 512;
    sim.min_interval_ticks = 0xFFFFFFFFu;
    out_len = 0;
    out_buf[0] = 0;
    cmd_init();
}

void sim_send_bytes(const uint8_t *data, size_t len) { rx_feed(data, len); }
void sim_send(const char *text) { rx_feed((const uint8_t *)text, strlen(text)); }

static void step_tick(void)
{
    uint8_t mask = sg_pre(hal_endstops() | sim.spike_once);
    sim.spike_once = 0;
    uint8_t pwm_while_stepping = sim.pwm;
    for (int a = 0; a < AXES; a++) {
        if (mask & (1u << a)) {
            sim.phys[a] += (sim.sim_dir & (1u << a)) ? -1 : 1;
            sim.steps[a]++;
        }
    }
    uint32_t next = sg_post();
    if (sg_dir_changed()) {
        sim.sim_dir = sg_dir();
        // The next tick is the next possible step: DIR must lead it clearly.
        if (next && next < 8u) sim.step_with_dir_change = true;
    }
    if (next) {
        if (mask && next < sim.min_interval_ticks) sim.min_interval_ticks = next;
        sim.next_tick += next;
        uint32_t rate = STEP_TICK_HZ / next;
        if (mask && rate > sim.max_rate_seen) sim.max_rate_seen = rate;
        if (sim.trace_on && sim.trace_n < 200000 && mask) {
            sim.trace_rate[sim.trace_n] = rate;
            sim.trace_pwm[sim.trace_n] = pwm_while_stepping;
            sim.trace_pwm_after[sim.trace_n] = sim.pwm;
            sim.trace_mask[sim.trace_n] = mask;
            sim.trace_time[sim.trace_n] = sim.now_ticks;
            sim.trace_n++;
        }
    } else {
        sim.timer_armed = false;
    }
}

void sim_run_ms(uint32_t ms)
{
    uint64_t end = sim.now_ticks + (uint64_t)ms * (STEP_TICK_HZ / 1000u);
    uint64_t next_poll = sim.now_ticks;
    while (sim.now_ticks < end) {
        if (sim.now_ticks >= next_poll) {
            cmd_poll();
            next_poll = sim.now_ticks + 200; // 100 us
        }
        uint64_t t = next_poll;
        if (sim.timer_armed && sim.next_tick < t) t = sim.next_tick;
        if (t > end) t = end;
        sim.now_ticks = t;
        while (sim.timer_armed && sim.next_tick <= sim.now_ticks) step_tick();
    }
}

void sim_stall_ms(uint32_t ms)
{
    uint64_t end = sim.now_ticks + (uint64_t)ms * (STEP_TICK_HZ / 1000u);
    while (sim.now_ticks < end) {
        uint64_t t = end;
        if (sim.timer_armed && sim.next_tick < t) t = sim.next_tick;
        sim.now_ticks = t;
        while (sim.timer_armed && sim.next_tick <= sim.now_ticks) step_tick();
    }
}

void sim_step_one_pass(void) { cmd_poll(); }

bool sim_run_until_idle(uint32_t max_ms)
{
    for (uint32_t i = 0; i < max_ms; i++) {
        sim_run_ms(1);
        if (planner_used() == 0 && !sg_running()) {
            sim_run_ms(1);
            return true;
        }
    }
    return false;
}

const char *sim_out(void) { return out_buf; }

void sim_out_clear(void)
{
    out_len = 0;
    out_buf[0] = 0;
}

int sim_ok_count(void)
{
    int n = 0;
    const char *p = out_buf;
    while (p && *p) {
        if (p[0] == 'o' && p[1] == 'k' && (p == out_buf || p[-1] == '\n')) n++;
        p = strchr(p, '\n');
        if (p) p++;
    }
    return n;
}

bool sim_out_has(const char *needle) { return strstr(out_buf, needle) != 0; }

const char *sim_cmd(const char *line)
{
    sim_out_clear();
    sim_send(line);
    sim_send("\n");
    for (int i = 0; i < 300000 && sim_ok_count() == 0; i++) sim_run_ms(1);
    return out_buf;
}

void sim_home_all_at_zero(void)
{
    sim.trip_on[0] = sim.trip_on[1] = sim.trip_on[2] = true;
    sim.trip[0] = sim.trip[1] = sim.trip[2] = 0;
    sim_cmd("G28");
    sim_run_until_idle(1000);
    sim_out_clear();
}
