// Fixes from the independent review: lift budget, beam at block end, underrun,
// interrupt races, driver reset. Each case fails without its fix.
#include "../src/laser.h"
#include "../src/motion.h"
#include "../src/planner.h"
#include "../src/stepgen.h"
#include "sim.h"
#include <stdio.h>
#include <string.h>

#define Z_STEPS(mm) ((int32_t)((mm) * 1018.59 + 0.5))

static void z_lift_budget(void)
{
    // After reset the height is unknown: 25 mm up, not to the logical 80.
    sim_reset();
    sim_cmd("G0 Z80");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z25.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z25 F600");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(10000));
    CHECK(sim.phys[2] == Z_STEPS(25));

    // G92 moves the numbers along, it gives no new budget.
    sim_cmd("G92 Z0");
    sim_cmd("G0 Z0.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G92 Z70");
    sim_cmd("G0 Z71");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G91");
    sim_cmd("G0 Z1");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G90");

    // Going down gives it back: the limit is a height, not a distance.
    sim_cmd("G0 Z60 F600");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(10000));
    sim_cmd("G0 Z70 F600");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(10000));
    CHECK(sim.phys[2] == Z_STEPS(25));

    // Quitting an emergency stop while unreferenced gives no new budget either.
    sim_reset();
    sim_cmd("G0 Z25 F600");
    CHECK(sim_run_until_idle(10000));
    sim_send("M112\n");
    sim_run_ms(2);
    sim_cmd("M999");
    sim_cmd("G0 Z25.5");
    CHECK(sim_out_has("Error:Out of bounds"));

    // Referenced: the rail counts, up to 80 and down to -2, with G92 as well.
    sim_reset();
    sim_home_all_at_zero();
    int32_t z0 = sim.phys[2];
    sim_cmd("G0 Z80 F600");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(20000));
    CHECK(sim.phys[2] - z0 == Z_STEPS(80));
    sim_cmd("G0 Z10 F600");
    CHECK(sim_run_until_idle(20000));
    sim_cmd("G92 Z20");
    sim_cmd("G0 Z7.9"); // real height -2.1
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z8"); // real height -2
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(20000));
    sim_cmd("G0 Z20 F600");
    CHECK(sim_run_until_idle(20000));

    // Losing the reference: new budget from where it stands, only once.
    sim_send("M112\n");
    sim_run_ms(2);
    sim_cmd("M999");
    CHECK(!motion_homed(AX_Z));
    sim_cmd("G0 Z45.5");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z45 F600");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(20000));

    // Failed search: stays unreferenced, the budget still holds at its old height.
    sim_reset();
    sim_cmd("G28 Z");
    CHECK(sim_out_has("Error:Homing failed"));
    sim_cmd("G0 Z25.001");
    CHECK(sim_out_has("Error:Out of bounds"));

    // Switch stuck open: every G28 backs off 5 mm. That must end at the budget.
    sim_reset();
    sim.force_open = 4;
    for (int i = 0; i < 10; i++) {
        sim_cmd("G28 Z");
        CHECK(sim_out_has("Error:Homing failed"));
    }
    CHECK(sim.phys[2] >= Z_STEPS(20));
    CHECK(sim.phys[2] <= Z_STEPS(25));

    // A switch that opens only on the way down still gets its normal backoff.
    sim_reset();
    sim.trip_on[2] = true;
    sim.trip[2] = -Z_STEPS(3);
    sim_cmd("G28 Z");
    CHECK(!sim_out_has("Error"));
    CHECK(motion_homed(AX_Z));

    // M92 plausibility, and what it does to the reference.
    sim_reset();
    sim_home_all_at_zero();
    sim_cmd("M92 Z0.5");
    CHECK(sim_out_has("Error:Invalid value"));
    sim_cmd("M92 Z5001");
    CHECK(sim_out_has("Error:Invalid value"));
    sim_cmd("M92 X99999");
    CHECK(sim_out_has("Error:Invalid value"));
    CHECK(motion_homed(AX_X) && motion_homed(AX_Z));
    sim_cmd("M92 Z1018.59"); // the Pi on every connect
    CHECK(!sim_out_has("Error"));
    CHECK(motion_homed(AX_Z));
    sim_cmd("M92 X80 Y80");
    CHECK(motion_homed(AX_X) && motion_homed(AX_Y));
    sim_cmd("M92 Z1000");
    CHECK(!sim_out_has("Error"));
    CHECK(!motion_homed(AX_Z));
    CHECK(motion_homed(AX_X));
    sim_cmd("M92 X81");
    CHECK(!motion_homed(AX_X));
    CHECK(motion_homed(AX_Y));

    sim_cmd("M115");
    CHECK(sim_out_has("Cap:Z_UNHOMED_LIFT:25\n"));
}

// F2: the beam must not wait for the next block's first step when it gets weaker.
static void beam_at_block_end(void)
{
    // Burn, then a reversal: the rapid back starts from rest, its first step is
    // milliseconds away, and the head stands still in that time.
    sim_reset();
    sim_cmd("M3 I");
    sim.trace_on = true;
    sim_send("G1 X10 F1200 S100\nG0 X0 F1200\n");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.trace_pwm[799] == 100);       // last step of the burn
    CHECK(sim.trace_pwm_after[799] == 0);   // dark within that same tick
    CHECK(sim.trace_pwm[800] == 0);

    // Weaker block: down at once. Stronger block: only with its first step.
    sim_reset();
    sim_cmd("M3 I");
    sim.trace_on = true;
    sim_send("G1 X10 F1200 S200\nG1 X20 S50\nG1 X30 S120\n");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.trace_pwm[799] == 200 && sim.trace_pwm_after[799] == 50);
    CHECK(sim.trace_pwm[1599] == 50 && sim.trace_pwm_after[1599] == 50);
    CHECK(sim.trace_pwm[1600] == 120);
}

// F4: main loop blocked, stepper runs out of planned blocks at speed.
static void feed_lines(int from, int count)
{
    char line[48];
    for (int i = 0; i < count; i++) {
        snprintf(line, sizeof line, "G1 X%d F6000 S10\n", from + i);
        sim_send(line);
        sim_run_ms(1);
    }
}

static void underrun(void)
{
    // Normal job with a main loop that hangs up to 40 ms: nothing happens.
    sim_reset();
    sim_home_all_at_zero();
    int32_t x0 = sim.phys[0];
    sim_cmd("M3 I");
    feed_lines(1, 10);
    for (int i = 0; i < 6; i++) {
        sim_stall_ms(40);
        sim_run_ms(40);
    }
    CHECK(sim_run_until_idle(3000));
    CHECK(!sim_out_has("Error"));
    CHECK(sim.phys[0] - x0 == 800);
    CHECK(motion_homed(AX_X));

    // Blocked far beyond the horizon, more blocks waiting: stop, not silent.
    sim_reset();
    sim_home_all_at_zero();
    sim_cmd("M3 I");
    sim_out_clear();
    feed_lines(1, 30);
    CHECK(sg_running());
    sim_stall_ms(300);
    CHECK(!sg_running());
    CHECK(sim.pwm == 0);
    sim_run_ms(5);
    CHECK(sim_out_has("Error:Planner underrun"));
    CHECK(planner_used() == 0);
    CHECK(!motion_homed(AX_X) && !motion_homed(AX_Y) && !motion_homed(AX_Z));
    CHECK(!laser_is_inline());
    sim_run_ms(100);
    CHECK(!sg_running());

    // Standing still between blocks is no underrun, however late the next one is.
    sim_reset();
    sim_cmd("G0 X5 F3000");
    CHECK(sim_run_until_idle(2000));
    sim_stall_ms(300);
    sim_cmd("G0 X10 F3000");
    CHECK(sim_run_until_idle(2000));
    CHECK(!sim_out_has("underrun"));
    CHECK(sim.phys[0] == 800);

    // Big arc: the travel check runs in slices. The chord that leaves the travel
    // is far along, so one pass cannot know yet.
    sim_reset();
    sim_cmd("G0 X200 Y40 F60000");
    CHECK(sim_run_until_idle(10000));
    sim_out_clear();
    sim_send("G2 X200 Y40 I0 J-150 F3000\n"); // leaves the travel after about 23 chords
    sim_step_one_pass();
    CHECK(!sim_out_has("Error"));
    sim_run_ms(20);
    CHECK(sim_out_has("Error:Out of bounds"));
    CHECK(sim.phys[1] == 3200);
}

// F8: M112 or M410 lands after a command's checks, before its output.
static void races(void)
{
    static const struct {
        const char *line;
    } cases[] = {{"M106 P0 S255"}, {"M8"}, {"M355 S1 P100"}, {"M3 S200"}, {"M3 I"}};
    for (size_t i = 0; i < sizeof cases / sizeof cases[0]; i++) {
        sim_reset();
        sim.inject_after_pop = "M112\n";
        sim_cmd(cases[i].line);
        CHECK(sim_out_has("Error:Emergency stop"));
        CHECK(!sim.relay && !sim.exhaust && sim.light == 0 && sim.pwm == 0);
        CHECK(!laser_is_inline() && laser_continuous() == 0);

        sim_reset();
        sim.inject_after_pop = "M410\n";
        sim_cmd(cases[i].line);
        sim_run_ms(5);
        CHECK(!sim.relay && !sim.exhaust && sim.light == 0 && sim.pwm == 0);
        CHECK(!laser_is_inline() && laser_continuous() == 0);
    }

    // F7: a line arrives between reading the clock and comparing. Unsigned, the
    // difference of -1 ms looked like 49 days of silence.
    sim_reset();
    sim_cmd("M3 S80");
    for (int i = 0; i < 7; i++) {
        sim_run_ms(1000);
        sim_cmd("M114");
    }
    CHECK(sim.pwm == 80);
    sim_out_clear();
    sim.inject_at_link_check = "M114\n";
    sim_run_ms(1);
    CHECK(!sim_out_has("echo:Laser off"));
    CHECK(sim.pwm == 80);
    sim_cmd("M5");
}

// F9: 24 V gone and back. The driver runs on defaults, so the position is void.
static void driver_reset(void)
{
    sim_reset();
    sim_home_all_at_zero();
    sim_cmd("G0 X1 F3000");
    CHECK(sim_run_until_idle(2000));
    sim_run_ms(1100);
    int32_t x = sim.phys[0];

    sim.tmc_reg[1][0x01] |= 1u; // GSTAT.reset of Z (address 1)
    sim.tmc_reg[1][0x6C] = 0;   // CHOPCONF back at some default
    sim_cmd("G0 X2 F3000");
    CHECK(sim_out_has("Error:Driver reset"));
    CHECK(sim_ok_count() == 1);
    sim_run_ms(50);
    CHECK(sim.phys[0] == x);
    CHECK(!motion_homed(AX_X) && !motion_homed(AX_Y) && !motion_homed(AX_Z));
    CHECK(sim.tmc_reg[1][0x6C] != 0); // set up again
    CHECK(!(sim.tmc_reg[1][0x01] & 1u));
    CHECK(sim.motors);

    sim_cmd("G0 X2 F3000");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(2000));

    // Not more than once a second, and not in the middle of moving.
    sim_run_ms(1100);
    uint32_t reads = sim.tmc_gstat_reads;
    for (int i = 0; i < 5; i++) {
        sim_cmd("G0 X3 F3000");
        CHECK(sim_run_until_idle(1000));
        sim_cmd("G0 X2 F3000");
        CHECK(sim_run_until_idle(1000));
    }
    CHECK(sim.tmc_gstat_reads - reads <= 3u * 4u);

    // Driver gone altogether.
    sim_run_ms(1100);
    sim.tmc_dead = true;
    sim_cmd("G0 X3 F3000");
    CHECK(sim_out_has("Error:Driver not responding"));
    CHECK(!sim.motors);
    sim.tmc_dead = false;
}

static void small_ones(void)
{
    // M3 I starts without power from earlier S words.
    sim_reset();
    sim_cmd("G1 X1 F600 S90"); // not armed: S is only remembered
    CHECK(sim_run_until_idle(2000));
    sim_cmd("M3 I");
    sim_cmd("G1 X2 F600");
    sim_run_ms(40);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(2000));

    // Reply delay for a bus with three drivers.
    sim_reset();
    sim_cmd("M17");
    CHECK((sim.tmc_reg[0][0x03] >> 8 & 15u) >= 2u);
    CHECK((sim.tmc_reg[1][0x03] >> 8 & 15u) >= 2u);
    CHECK((sim.tmc_reg[2][0x03] >> 8 & 15u) >= 2u);
}

void test_review(void)
{
    z_lift_budget();
    beam_at_block_end();
    underrun();
    races();
    driver_reset();
    small_ones();
}
