#include "cmd.h"
#include "../version.h"
#include "arc.h"
#include "config.h"
#include "gcode.h"
#include "hal.h"
#include "homing.h"
#include "laser.h"
#include "motion.h"
#include "out.h"
#include "rxlines.h"
#include "stepgen.h"
#include "tmc.h"
#include "update.h"

typedef enum { DONE, AGAIN } step_t;

// Set in interrupts, handled in the main loop.
static volatile bool latched;         // M112 until M999
static volatile uint8_t rt_m112_acks; // ok lines still owed
static volatile uint8_t rt_m410_acks;
static volatile bool rt_flush;
static volatile uint32_t abort_gen;

static bool have_cmd;
static gcode_t cur;
static char cur_line[RX_LINE_MAX + 1];
static uint32_t cur_gen;
static uint32_t cur_phase; // per-command progress
static uint32_t wait_since, busy_at;

static arc_t arc;
static uint32_t tone_end_ms;
static bool tone_was_on;
static uint8_t tone_axes;

static float feed_g0 = 150.0f, feed_g1 = 25.0f; // mm/s, modal, separate
static float accel_print = 500.0f, accel_travel = 500.0f;
static bool relative;
static volatile bool relay_on, exhaust_on, light_on; // cleared by M112 in the USB interrupt
static uint8_t light_level;
static bool link_was_ok, boot_reported;
static uint32_t continuous_since;

void cmd_init(void)
{
    latched = false;
    rt_m112_acks = rt_m410_acks = 0;
    rt_flush = false;
    abort_gen = 0;
    have_cmd = false;
    feed_g0 = 150.0f;
    feed_g1 = 25.0f;
    accel_print = accel_travel = 500.0f;
    relative = false;
    relay_on = exhaust_on = false;
    light_level = 153; // CASE_LIGHT_DEFAULT_BRIGHTNESS in firmware/marlin/build.py
    light_on = false;
    link_was_ok = false;
    boot_reported = false;
    sg_init();
    motion_init();
    planner_init(motion_limits());
    laser_init();
    rx_init();
}

void cmd_reply_ok(void)
{
    out_str("ok P");
    out_u32(planner_free());
    out_str(" B");
    out_u32(rx_free_lines());
    out_nl();
}

static void reply_error(const char *text)
{
    out_str("Error:");
    out_str(text);
    out_nl();
    cmd_reply_ok();
}

// --- interrupt entry points ------------------------------------------------

void cmd_rt_m112(void)
{
    latched = true;
    hal_all_off();
    sg_abort();
    laser_kill();
    relay_on = exhaust_on = light_on = false;
    rt_m112_acks++;
    rt_flush = true;
    abort_gen = abort_gen + 1;
}

void cmd_rt_m410(void)
{
    sg_abort();
    laser_kill();
    rt_m410_acks++;
    rt_flush = true;
    abort_gen = abort_gen + 1;
    rx_mark_discard();
}

void cmd_rt_link_lost(void) { laser_kill(); }

// --- helpers ---------------------------------------------------------------

static float fix_to_float(int64_t v) { return (float)v / GC_UNIT; }

static float feed_from_word(int64_t fix) { return fix_to_float(fix) / 60.0f; }

static bool wait_stillstand(void)
{
    if (motion_idle()) return true;
    planner_request_flush();
    return false;
}

static bool ensure_motors(void)
{
    uint8_t axis;
    if (motors_ensure(&axis)) return true;
    char text[] = "Driver not responding: X";
    text[sizeof text - 2] = (char)('X' + axis);
    reply_error(text);
    return false;
}

static void unknown(void)
{
    out_str("Error:Unknown command: ");
    out_str(cur_line);
    out_nl();
    cmd_reply_ok();
}

static step_t finish_ok(void)
{
    cmd_reply_ok();
    return DONE;
}

static step_t finish_error(const char *text)
{
    reply_error(text);
    return DONE;
}

static void target_from_words(int32_t t[AXES])
{
    static const char LETTER[AXES] = {'X', 'Y', 'Z'};
    for (int a = 0; a < AXES; a++) {
        t[a] = motion_pos(a);
        if (!gc_num(&cur, LETTER[a])) continue;
        int64_t v = gc_fix(&cur, LETTER[a]);
        if (relative) v += motion_pos(a);
        // Far outside any travel; clamping keeps it out of bounds in 32 bits.
        if (v > 2000000000LL) v = 2000000000LL;
        if (v < -2000000000LL) v = -2000000000LL;
        t[a] = (int32_t)v;
    }
}

// --- G commands --------------------------------------------------------------

// Reads S and F. Only called once the command is certain to be accepted.
static bool check_power_word(void)
{
    if (!gc_has(&cur, 'S')) return true;
    if (!gc_num(&cur, 'S')) return false;
    int64_t s = gc_int(&cur, 'S');
    return s >= 0 && s <= 255;
}

static void apply_motion_words(bool rapid)
{
    if (gc_num(&cur, 'F')) {
        float f = feed_from_word(gc_fix(&cur, 'F'));
        if (rapid) feed_g0 = f;
        else feed_g1 = f;
    }
    if (!rapid && gc_num(&cur, 'S')) laser_set_modal((uint8_t)gc_int(&cur, 'S'));
}

static step_t g_line(bool rapid)
{
    if (gc_has(&cur, 'F') && (!gc_num(&cur, 'F') || gc_fix(&cur, 'F') <= 0))
        return finish_error("Invalid feedrate");
    if (!rapid && !check_power_word()) return finish_error("S out of range");
    int32_t t[AXES];
    target_from_words(t);
    if (!motion_in_bounds(t)) return finish_error("Out of bounds");
    if (t[0] == motion_pos(0) && t[1] == motion_pos(1) && t[2] == motion_pos(2)) {
        apply_motion_words(rapid);
        return finish_ok();
    }
    if (planner_free() == 0) return AGAIN;
    if (!ensure_motors()) return DONE;
    apply_motion_words(rapid);
    laser_motion_queued();
    float speed = rapid ? feed_g0 : feed_g1;
    float accel = rapid ? accel_travel : accel_print;
    (void)motion_move(t, speed, accel, laser_block_power(rapid));
    return finish_ok();
}

static step_t g_arc(bool clockwise)
{
    if (cur_phase == 0) {
        if (gc_has(&cur, 'Z')) {
            unknown();
            return DONE;
        }
        if (gc_has(&cur, 'F') && (!gc_num(&cur, 'F') || gc_fix(&cur, 'F') <= 0))
            return finish_error("Invalid feedrate");
        if (!check_power_word()) return finish_error("S out of range");
        int32_t t[AXES];
        target_from_words(t);
        int64_t i = gc_num(&cur, 'I') ? gc_fix(&cur, 'I') : 0;
        int64_t j = gc_num(&cur, 'J') ? gc_fix(&cur, 'J') : 0;
        if (i > 100000000 || i < -100000000 || j > 100000000 || j < -100000000 ||
            !arc_plan(&arc, motion_pos(AX_X), motion_pos(AX_Y), t[AX_X], t[AX_Y], (int32_t)i,
                      (int32_t)j, clockwise)) {
            return finish_error("Arc invalid");
        }
        for (uint32_t k = 1; k <= arc.segments; k++) {
            int32_t p[AXES] = {0, 0, motion_pos(AX_Z)};
            arc_point(&arc, k, &p[AX_X], &p[AX_Y]);
            if (!motion_in_bounds(p)) return finish_error("Out of bounds");
        }
        if (!ensure_motors()) return DONE;
        apply_motion_words(false);
        laser_motion_queued();
        cur_phase = 1;
    }
    while (cur_phase <= arc.segments) {
        if (planner_free() == 0) return AGAIN;
        int32_t p[AXES] = {0, 0, motion_pos(AX_Z)};
        arc_point(&arc, cur_phase, &p[AX_X], &p[AX_Y]);
        (void)motion_move(p, feed_g1, accel_print, laser_block_power(false));
        cur_phase++;
    }
    return finish_ok();
}

static step_t g_dwell(void)
{
    int64_t ms = 0;
    if (gc_num(&cur, 'P')) ms = gc_int(&cur, 'P');
    else if (gc_num(&cur, 'S')) ms = gc_int(&cur, 'S') * 1000;
    else return finish_error("Dwell needs P or S");
    if (ms < 0 || ms > 2000000) return finish_error("Dwell out of range");
    if (ms == 0) return finish_ok();
    if (!planner_dwell((uint32_t)ms)) return AGAIN;
    return finish_ok();
}

static step_t g_set_position(void)
{
    static const char LETTER[AXES] = {'X', 'Y', 'Z'};
    if (!wait_stillstand()) return AGAIN;
    for (int a = 0; a < AXES; a++) {
        if (gc_num(&cur, LETTER[a])) {
            int64_t v = gc_fix(&cur, LETTER[a]);
            if (v > 100000000 || v < -100000000 || !motion_set_position(a, (int32_t)v))
                return finish_error("Out of bounds");
        }
    }
    return finish_ok();
}

static step_t g_home(void)
{
    if (cur_phase == 0) {
        if (!wait_stillstand()) return AGAIN;
        if (!ensure_motors()) return DONE;
        uint8_t axes = 0;
        if (gc_has(&cur, 'X')) axes |= 1u << AX_X;
        if (gc_has(&cur, 'Y')) axes |= 1u << AX_Y;
        if (gc_has(&cur, 'Z')) axes |= 1u << AX_Z;
        if (!axes) axes = 7;
        laser_motion_queued();
        homing_start(axes);
        cur_phase = 1;
    }
    switch (homing_poll()) {
    case SEEK_BUSY:
        return AGAIN;
    case SEEK_DONE:
        return finish_ok();
    case SEEK_FAILED:
        break;
    }
    return finish_error("Homing failed");
}

static step_t g_probe(void)
{
    if (cur_phase == 0) {
        if (!wait_stillstand()) return AGAIN;
        if (!probe_start()) return finish_error("Probe already triggered");
        if (!ensure_motors()) return DONE;
        laser_motion_queued();
        cur_phase = 1;
    }
    switch (probe_poll()) {
    case SEEK_BUSY:
        return AGAIN;
    case SEEK_DONE:
        out_str("Bed X:");
        out_fix3(motion_pos(AX_X));
        out_str(" Y:");
        out_fix3(motion_pos(AX_Y));
        out_str(" Z:");
        out_fix3(motion_pos(AX_Z));
        out_nl();
        return finish_ok();
    case SEEK_FAILED:
        break;
    }
    return finish_error("Probing failed");
}

// --- M commands --------------------------------------------------------------

static step_t m_laser_on(void)
{
    if (gc_has(&cur, 'I')) {
        if (!check_power_word()) return finish_error("S out of range");
        if (!hal_usb_link_ok()) return finish_error("No USB host");
        laser_m3_inline();
        if (gc_num(&cur, 'S')) laser_set_modal((uint8_t)gc_int(&cur, 'S'));
        return finish_ok();
    }
    if (!check_power_word()) return finish_error("S out of range");
    if (!wait_stillstand()) return AGAIN;
    uint8_t s = gc_num(&cur, 'S') ? (uint8_t)gc_int(&cur, 'S') : 0;
    if (s && !hal_usb_link_ok()) return finish_error("No USB host");
    laser_m3_continuous(s);
    continuous_since = hal_ms();
    return finish_ok();
}

static step_t m_relay(bool on)
{
    if (gc_num(&cur, 'P') && gc_fix(&cur, 'P') != 0) {
        unknown();
        return DONE;
    }
    if (!wait_stillstand()) return AGAIN;
    if (on && gc_num(&cur, 'S')) on = gc_fix(&cur, 'S') > 0;
    relay_on = on;
    hal_relay(on);
    return finish_ok();
}

static step_t m_light(void)
{
    if (gc_num(&cur, 'P')) {
        int64_t p = gc_int(&cur, 'P');
        if (p < 0 || p > 255) return finish_error("P out of range");
        light_level = (uint8_t)p;
    }
    if (gc_num(&cur, 'S')) light_on = gc_fix(&cur, 'S') != 0;
    hal_light(light_on ? light_level : 0);
    return finish_ok();
}

static step_t m_axis_values(float *values, bool z_cap)
{
    static const char LETTER[AXES] = {'X', 'Y', 'Z'};
    for (int a = 0; a < AXES; a++) {
        if (gc_has(&cur, LETTER[a]) && (!gc_num(&cur, LETTER[a]) || gc_fix(&cur, LETTER[a]) <= 0))
            return finish_error("Invalid value");
    }
    for (int a = 0; a < AXES; a++) {
        if (!gc_num(&cur, LETTER[a])) continue;
        float v = fix_to_float(gc_fix(&cur, LETTER[a]));
        if (z_cap && a == AX_Z && v > Z_HARD_MAX_FEED) v = Z_HARD_MAX_FEED;
        values[a] = v;
    }
    return finish_ok();
}

static step_t m_steps_per_mm(void)
{
    static const char LETTER[AXES] = {'X', 'Y', 'Z'};
    if (!wait_stillstand()) return AGAIN;
    for (int a = 0; a < AXES; a++) {
        if (gc_has(&cur, LETTER[a]) && (!gc_num(&cur, LETTER[a]) || gc_fix(&cur, LETTER[a]) <= 0))
            return finish_error("Invalid value");
    }
    for (int a = 0; a < AXES; a++) {
        if (gc_num(&cur, LETTER[a])) motion_set_steps_mm(a, fix_to_float(gc_fix(&cur, LETTER[a])));
    }
    return finish_ok();
}

static step_t m_accel(void)
{
    if ((gc_has(&cur, 'P') && (!gc_num(&cur, 'P') || gc_fix(&cur, 'P') <= 0)) ||
        (gc_has(&cur, 'T') && (!gc_num(&cur, 'T') || gc_fix(&cur, 'T') <= 0))) {
        return finish_error("Invalid value");
    }
    if (gc_num(&cur, 'P')) accel_print = fix_to_float(gc_fix(&cur, 'P'));
    if (gc_num(&cur, 'T')) accel_travel = fix_to_float(gc_fix(&cur, 'T'));
    return finish_ok();
}

static step_t m_position(void)
{
    out_str("X:");
    out_fix3(motion_pos(AX_X));
    out_str(" Y:");
    out_fix3(motion_pos(AX_Y));
    out_str(" Z:");
    out_fix3(motion_pos(AX_Z));
    out_str(" Count X:");
    out_i32(planner_position(AX_X));
    out_str(" Y:");
    out_i32(planner_position(AX_Y));
    out_str(" Z:");
    out_i32(planner_position(AX_Z));
    out_nl();
    return finish_ok();
}

static step_t m_identify(void)
{
    out_str("FIRMWARE_NAME:" LUMACUT_ID " " LUMACUT_VERSION " (" __DATE__ " " __TIME__
            ") MACHINE_TYPE:" LUMACUT_ID "\nCap:Z_PROBE:1\nCap:SELF_UPDATE:1\n");
    return finish_ok();
}

static step_t m_endstops(void)
{
    uint8_t e = hal_endstops();
    out_str("Reporting endstop status\n");
    out_str((e & 1u) ? "x_min: TRIGGERED\n" : "x_min: open\n");
    out_str((e & 2u) ? "y_min: TRIGGERED\n" : "y_min: open\n");
    out_str((e & 4u) ? "z_min: TRIGGERED\n" : "z_min: open\n");
    return finish_ok();
}

static void tone_restore(void)
{
    tmc_spreadcycle(tone_axes, false);
    if (!tone_was_on) motors_off();
}

// Stepper coils sing: alternating microsteps forward and back, net travel zero.
static step_t m_tone(void)
{
    if (cur_phase == 0) {
        if (!wait_stillstand()) return AGAIN;
        if (laser_continuous() || laser_is_inline()) {
            out_str("echo:M300 refused: laser on\n");
            return finish_ok();
        }
        int64_t ms = gc_num(&cur, 'P') ? gc_int(&cur, 'P') : 200;
        int64_t hz = gc_num(&cur, 'S') ? gc_int(&cur, 'S') : 440;
        if (ms < 0) ms = 0;
        if (ms > TONE_MAX_MS) ms = TONE_MAX_MS;
        if (hz != 0 && (hz < TONE_MIN_HZ || hz > TONE_MAX_HZ)) {
            out_str("echo:M300 S must be 40..5000 Hz\n");
            return finish_ok();
        }
        tone_end_ms = hal_ms() + (uint32_t)ms;
        if (hz == 0 || ms == 0) {
            cur_phase = 3; // rest
            return AGAIN;
        }
        bool x = gc_has(&cur, 'X'), y = gc_has(&cur, 'Y');
        tone_axes = (uint8_t)((x || !y) ? 1u : 0u) | (uint8_t)((y || !x) ? 2u : 0u);
        tone_was_on = motors_are_on();
        if (!ensure_motors()) return DONE;
        tmc_spreadcycle(tone_axes, true);
        uint32_t half_ticks = (STEP_TICK_HZ / 2u) / (uint32_t)hz;
        uint32_t steps = (uint32_t)((uint32_t)ms * (uint32_t)hz / 500u);
        steps &= ~1u; // even count: always back where it started
        if (steps == 0) steps = 2;
        sg_tone_start(tone_axes, half_ticks, steps);
        cur_phase = 1;
        return AGAIN;
    }
    if (cur_phase == 1) {
        if (sg_running()) return AGAIN;
        tone_restore();
        return finish_ok();
    }
    if ((int32_t)(hal_ms() - tone_end_ms) < 0) return AGAIN;
    return finish_ok();
}

static step_t m_update(void)
{
    if (!gc_num(&cur, 'U') || !gc_num(&cur, 'C')) return finish_error("Update arguments");
    if (!motion_idle()) return finish_error("Update refused: machine moving");
    if (laser_continuous() || laser_is_inline() || relay_on)
        return finish_error("Update refused: laser or relay on");
    int64_t u = gc_int(&cur, 'U'), c = gc_int(&cur, 'C');
    if (u < 0 || u > 0xFFFFFFFFLL || c < 0 || c > 0xFFFFFFFFLL) return finish_error("Update size");
    const char *error = 0;
    if (!update_begin((uint32_t)u, (uint32_t)c, &error)) {
        out_str(error);
        out_nl();
        cmd_reply_ok();
    }
    return DONE;
}

static step_t m_clear_estop(void)
{
    if (latched) {
        latched = false;
        hal_outputs_arm();
        laser_init();
        motion_set_unhomed(7);
    }
    return finish_ok();
}

static step_t dispatch(void)
{
    if (cur.letter == 'G') {
        switch (cur.code) {
        case 0: return g_line(true);
        case 1: return g_line(false);
        case 2: return g_arc(true);
        case 3: return g_arc(false);
        case 4: return g_dwell();
        case 21: return finish_ok();
        case 28: return g_home();
        case 30: return g_probe();
        case 90: relative = false; return finish_ok();
        case 91: relative = true; return finish_ok();
        case 92: return g_set_position();
        default: break;
        }
    } else {
        switch (cur.code) {
        case 3: return m_laser_on();
        case 5:
            if (gc_has(&cur, 'I')) laser_m5_inline();
            else laser_m5();
            return finish_ok();
        case 8:
            exhaust_on = true;
            hal_exhaust(true);
            return finish_ok();
        case 9:
            exhaust_on = false;
            hal_exhaust(false);
            return finish_ok();
        case 17: {
            if (!wait_stillstand()) return AGAIN;
            if (!ensure_motors()) return DONE;
            return finish_ok();
        }
        case 84:
            if (!wait_stillstand()) return AGAIN;
            motors_off();
            return finish_ok();
        case 92: return m_steps_per_mm();
        case 106: return m_relay(true);
        case 107: return m_relay(false);
        case 114: return m_position();
        case 115: return m_identify();
        case 119: return m_endstops();
        case 122:
            tmc_report();
            return finish_ok();
        case 201: return m_axis_values(motion_limits()->max_accel, false);
        case 203: return m_axis_values(motion_limits()->max_feed, true);
        case 204: return m_accel();
        case 300: return m_tone();
        case 355: return m_light();
        case 400:
            if (!wait_stillstand()) return AGAIN;
            return finish_ok();
        case 997: return m_update();
        case 999: return m_clear_estop();
        default: break;
        }
    }
    unknown();
    return DONE;
}

// --- main loop pass ----------------------------------------------------------

static bool allowed_while_latched(void)
{
    return cur.letter == 'M' && (cur.code == 115 || cur.code == 119 || cur.code == 999);
}

static void copy_line(const char *line)
{
    size_t i = 0;
    while (line[i] && i < RX_LINE_MAX) {
        cur_line[i] = line[i];
        i++;
    }
    cur_line[i] = 0;
}

// Takes the next line. Returns true when a command is ready to run.
static bool next_line(void)
{
    bool too_long = false, discard = false;
    const char *line = rx_peek(&too_long, &discard);
    if (!line) return false;
    copy_line(line);
    gcode_status_t st = too_long ? GC_BAD : gcode_parse(cur_line, &cur);
    rx_pop();
    if (discard) {
        cmd_reply_ok();
        return false;
    }
    if (latched && !(st == GC_OK && allowed_while_latched())) {
        reply_error("Emergency stop");
        return false;
    }
    if (too_long) {
        reply_error("Line too long");
        return false;
    }
    if (st == GC_EMPTY) {
        cmd_reply_ok();
        return false;
    }
    if (st == GC_BAD) {
        unknown();
        return false;
    }
    have_cmd = true;
    cur_gen = abort_gen;
    cur_phase = 0;
    wait_since = hal_ms();
    busy_at = wait_since + BUSY_PERIOD_MS;
    return true;
}

// The stepper stopped by itself or by M112/M410: forget the queue and take the
// position from the step counters.
static void handle_stops(void)
{
    sg_stop_t reason = sg_stop_reason();
    if (reason == SG_STOP_ENDSTOP) {
        static const char *const NAME[AXES] = {" X:", " Y:", " Z:"};
        uint8_t axes = sg_stop_axes();
        out_str("endstops hit:");
        for (int a = 0; a < AXES; a++) {
            if (axes & (1u << a)) {
                out_str(NAME[a]);
                out_fix3(motion_fix_from_steps(a, sg_count(a)));
            }
        }
        out_nl();
        rx_mark_discard();
        abort_gen = abort_gen + 1;
    }
    if (reason == SG_STOP_SEEK) homing_note_switch_hit();
    if (reason != SG_STOP_NONE || rt_flush) {
        uint32_t cs = hal_cs_enter();
        rt_flush = false;
        hal_cs_exit(cs);
        motion_resync();
        sg_stop_clear();
    }
    while (rt_m112_acks) {
        cmd_reply_ok();
        uint32_t cs = hal_cs_enter();
        rt_m112_acks--;
        hal_cs_exit(cs);
    }
    while (rt_m410_acks) {
        if (latched) reply_error("Emergency stop");
        else cmd_reply_ok();
        uint32_t cs = hal_cs_enter();
        rt_m410_acks--;
        hal_cs_exit(cs);
    }
}

static void drop_aborted_command(void)
{
    if (!have_cmd || cur_gen == abort_gen) return;
    have_cmd = false;
    if (cur.letter == 'M' && cur.code == 300 && cur_phase == 1) tone_restore();
    if (latched) {
        reply_error("Emergency stop");
    } else if (cur.letter == 'G' && cur.code == 28 && cur_phase) {
        reply_error("Homing failed");
    } else if (cur.letter == 'G' && cur.code == 30 && cur_phase) {
        reply_error("Probing failed");
    } else {
        cmd_reply_ok();
    }
}

static void check_link(uint32_t now)
{
    bool ok = hal_usb_link_ok();
    if (link_was_ok && !ok) {
        laser_kill(); // rule 6
        update_cancel();
    }
    link_was_ok = ok;
    if (ok && !boot_reported) {
        boot_reported = true;
        out_str("echo:LumaCut reset=");
        out_str(hal_reset_cause());
        out_nl();
    }
    if (laser_continuous() && now - rx_last_line_ms() > USB_SILENCE_MS &&
        now - continuous_since > USB_SILENCE_MS) {
        laser_kill(); // rule 6
        out_str("echo:Laser off: USB silent\n");
    }
}

void cmd_poll(void)
{
    uint32_t now = hal_ms();
    check_link(now);
    handle_stops();
    drop_aborted_command();
    planner_poll(now);

    if (update_active()) {
        update_poll(now);
        return;
    }

    if (!have_cmd && !next_line()) return;

    step_t r = dispatch();
    if (r == DONE) {
        have_cmd = false;
    } else if ((int32_t)(now - busy_at) >= 0) {
        busy_at = now + BUSY_PERIOD_MS;
        out_str("echo:busy: processing\n");
    }
    planner_poll(hal_ms());
}
