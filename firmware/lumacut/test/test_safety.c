// Laser rules, endstops, emergency stop, homing, probing.
#include "../src/laser.h"
#include "../src/motion.h"
#include "../src/planner.h"
#include "../src/stepgen.h"
#include "sim.h"
#include <string.h>

static bool all_pwm_zero_in_trace(void)
{
    for (size_t i = 0; i < sim.trace_n; i++) {
        if (sim.trace_pwm[i]) return false;
    }
    return true;
}

void test_laser(void)
{
    // Rule 4: inline power only during G1 with S > 0, set when the block starts.
    sim_reset();
    sim_cmd("M3 I");
    CHECK(sim.pwm == 0);
    sim.trace_on = true;
    sim_cmd("G1 X10 F1200 S100");
    CHECK(sim.pwm == 0); // not moving yet
    sim_run_ms(100);
    CHECK(sim.pwm == 100); // running
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.pwm == 0); // no block, no beam
    CHECK(sim.phys[0] == 800);
    // Every step of the block saw the power.
    for (size_t i = 0; i < sim.trace_n; i++) {
        if (sim.trace_pwm[i] != 100) {
            CHECK(sim.trace_pwm[i] == 100);
            break;
        }
    }

    // S stays modal for G1, G0 stays dark and does not reset it.
    sim_cmd("G0 X20 F1200");
    sim_run_ms(100);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(3000));
    sim_cmd("G1 X30 F1200");
    sim_run_ms(100);
    CHECK(sim.pwm == 100);
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.pwm == 0);

    // Dark and bright blocks in one queue change exactly at their boundary.
    sim_reset();
    sim_cmd("M3 I");
    sim.trace_on = true;
    sim_send("G1 X10 F1200 S50\nG0 X20 F1200\nG1 X30 S200\nG1 X40 S0\n");
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 3200);
    for (size_t i = 0; i < sim.trace_n; i++) {
        if (sim.trace_mask[i] & 1u) {
            // trace_pwm[i] is the level while step i goes out.
            uint8_t want = i < 800 ? 50 : i < 1600 ? 0 : i < 2400 ? 200 : 0;
            if (sim.trace_pwm[i] != want) {
                CHECK(sim.trace_pwm[i] == want);
                break;
            }
        }
    }
    CHECK(sim.pwm == 0);

    // Without M3 I a G1 S> 0 stays dark, also when M3 I comes while it runs.
    sim_reset();
    sim.trace_on = true;
    sim_cmd("G1 X10 F1200 S200");
    CHECK(sim_run_until_idle(3000));
    CHECK(all_pwm_zero_in_trace());
    CHECK(sim.pwm_writes == 0 || sim.pwm == 0);

    // S out of range is refused and nothing moves.
    sim_reset();
    sim_cmd("M3 I");
    sim_cmd("G1 X10 S256");
    CHECK(sim_out_has("Error:S out of range"));
    sim_cmd("G1 X10 S-1");
    CHECK(sim_out_has("Error:S out of range"));
    sim_run_ms(50);
    CHECK(sim.steps[0] == 0);

    // M5 I does not wait, new moves are dark, the blocks already queued burn:
    // the tail of a job must not get lost, the power belongs to the block.
    sim_reset();
    sim_cmd("M3 I");
    sim.trace_on = true;
    sim_send("G1 X10 F1200 S100\nM5 I\nG1 X20\n");
    sim_run_ms(100);
    CHECK(!laser_is_inline());
    CHECK(sim.pwm == 100);
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.pwm == 0);
    CHECK(sim.trace_n == 1599 && sim.trace_pwm[100] == 100 && sim.trace_pwm[1200] == 0);
    sim_cmd("G1 X30 S120");
    sim_run_ms(100);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(5000));

    // M5 clears the modal power, the mode stays.
    sim_reset();
    sim_cmd("M3 I");
    sim_cmd("G1 X1 F600 S90");
    CHECK(sim_run_until_idle(3000));
    sim_cmd("M5");
    CHECK(laser_is_inline());
    sim_cmd("G1 X2");
    sim_run_ms(30);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(3000));

    // Rule 5: continuous power at standstill, no time limit while commands come.
    sim_reset();
    sim_cmd("M3 S50");
    CHECK(sim.pwm == 50);
    for (int i = 0; i < 20; i++) { // 60 s with a heartbeat every 3 s
        sim_run_ms(3000);
        sim_cmd("M114");
    }
    CHECK(sim.pwm == 50);
    sim_cmd("M3 S0");
    CHECK(sim.pwm == 0);

    // Continuous power waits for an empty queue.
    sim_reset();
    sim_send("G1 X10 F1200\nM3 S70\n");
    sim_run_ms(50);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(3000));
    sim_run_ms(5);
    CHECK(sim.pwm == 70);

    // A move ends it, at once, and it does not come back.
    sim_cmd("G0 X20 F1200");
    CHECK(sim.pwm == 0);
    CHECK(laser_continuous() == 0);
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.pwm == 0);

    // M5 and M3 I end it too; G4 keeps it, it is no move.
    sim_reset();
    sim_cmd("M3 S60");
    sim_cmd("G4 P100");
    sim_run_ms(50);
    CHECK(sim.pwm == 60);
    sim_run_ms(100);
    CHECK(sim.pwm == 60);
    sim_cmd("M5");
    CHECK(sim.pwm == 0);
    sim_cmd("M3 S60");
    sim_cmd("M3 I");
    CHECK(sim.pwm == 0);

    // G4 in inline mode is dark, between bright moves.
    sim_reset();
    sim_cmd("M3 I");
    sim_send("G1 X5 F1200 S100\nG4 P200\nG1 X10\n");
    sim_run_ms(100);
    CHECK(sim.pwm == 100);
    sim_run_ms(300);
    CHECK(sim.pwm == 0);
    sim_run_ms(150);
    CHECK(sim.pwm == 100);
    CHECK(sim_run_until_idle(3000));

    // Rule 6: 5 s of USB silence ends continuous power...
    sim_reset();
    sim_cmd("M3 S80");
    sim_out_clear();
    sim_run_ms(4900);
    CHECK(sim.pwm == 80);
    sim_run_ms(200);
    CHECK(sim.pwm == 0);
    CHECK(sim_out_has("echo:Laser off: USB silent"));
    // ...M114 counts as traffic...
    sim_reset();
    sim_cmd("M3 S80");
    sim_run_ms(4000);
    sim_cmd("M114");
    sim_run_ms(4000);
    CHECK(sim.pwm == 80);
    sim_run_ms(1100);
    CHECK(sim.pwm == 0);
    // ...and so does M3 itself, even after a long queue wait.
    sim_reset();
    sim_cmd("M3 S80");
    sim.link_ok = false;
    sim_run_ms(1);
    CHECK(sim.pwm == 0); // USB gone
    CHECK(laser_continuous() == 0);
    sim.link_ok = true;
    sim_run_ms(10);
    CHECK(sim.pwm == 0); // does not come back by itself

    // USB gone in the middle of an inline job: dark, also for what is queued.
    sim_reset();
    sim_cmd("M3 I");
    sim_send("G1 X50 F600 S100\nG1 X60\n");
    sim_run_ms(100);
    CHECK(sim.pwm == 100);
    sim.link_ok = false;
    sim_run_ms(1);
    CHECK(sim.pwm == 0);
    CHECK(sim_run_until_idle(20000));
    CHECK(sim.pwm == 0);
    sim.link_ok = true;
    sim_run_ms(2);
    sim_cmd("G1 X70 S100");
    sim_run_ms(100);
    CHECK(sim.pwm == 0); // needs a new M3 I

    // No host, no laser.
    sim_reset();
    sim.link_ok = false;
    sim_cmd("M3 S10");
    CHECK(sim_out_has("Error:No USB host"));
    CHECK(sim.pwm == 0);
    sim_cmd("M3 I");
    CHECK(sim_out_has("Error:No USB host"));
}

void test_endstops(void)
{
    // Rule 7: the switch in the driving direction stops everything.
    sim_reset();
    sim.trip_on[2] = true;
    sim.trip[2] = -1000000;
    sim_cmd("G92 Z50");
    sim_cmd("M3 I");
    sim.trip[2] = sim.phys[2] - 5000; // contact about 5 mm further down
    sim_cmd("G1 X100 Z0 F600 S100");
    sim_send("G1 X200\nG1 X300\n");
    sim_run_ms(200);
    CHECK(sim.pwm == 100);
    sim_out_clear();
    bool hit = false;
    for (int i = 0; i < 60000 && !hit; i++) {
        sim_run_ms(1);
        hit = sim_out_has("endstops hit:");
    }
    CHECK(hit);
    CHECK(sim_out_has("endstops hit: Z:"));
    CHECK(!sim_out_has("X:")); // only the axis that hit
    CHECK(sim.pwm == 0);
    CHECK(!sg_running());
    CHECK(planner_used() == 0);
    CHECK(!laser_is_inline()); // a new job needs M3 I
    // Stopped within two samples of the contact.
    CHECK(sim.phys[2] >= sim.trip[2] - 2 && sim.phys[2] <= sim.trip[2]);
    // Lines received before the stop do not start moving again.
    int32_t x_at_stop = sim.phys[0];
    sim_run_ms(100);
    CHECK(sim.phys[0] == x_at_stop);
    // The position follows the real counters.
    sim_cmd("M114");
    int32_t count = sg_count(AX_Z);
    CHECK(planner_position(AX_Z) == count);
    CHECK(sim_out_has("X:") && sim_out_has("Count"));

    // Moving away from a triggered switch is always allowed.
    sim_reset();
    sim.force_open = 4;
    sim_cmd("G1 Z5 F300");
    CHECK(sim_out_has("ok P"));
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[2] == 5093);
    CHECK(!sim_out_has("endstops hit"));

    // Toward a triggered switch: not one step.
    sim.force_open = 4;
    sim_out_clear();
    uint32_t steps_before = sim.steps[2];
    sim_send("G1 Z4 F300\n");
    sim_run_ms(100);
    CHECK(sim_out_has("endstops hit: Z:5.000"));
    CHECK(sim.steps[2] == steps_before);

    // A switch of another axis does not matter for a move without that axis.
    sim_reset();
    sim.force_open = 4; // Z open
    sim_cmd("G0 X10 F3000");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[0] == 800);
    CHECK(!sim_out_has("endstops hit"));

    // Plus move on X and minus on Y: only Y's switch counts.
    sim_reset();
    sim_cmd("G0 Y20 F3000");
    CHECK(sim_run_until_idle(3000));
    sim.force_open = 1; // X open
    sim_out_clear();
    sim_cmd("G0 X10 Y10 F3000");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[0] == 800 && sim.phys[1] == 800);
    CHECK(!sim_out_has("endstops hit"));
    sim.force_open = 2; // Y open, Y moving down
    sim_out_clear();
    sim_cmd("G0 X20 Y5 F3000");
    sim_run_ms(50);
    CHECK(sim_out_has("endstops hit: Y:"));

    // One noisy sample does not stop a job.
    sim_reset();
    sim_cmd("G0 X100 F3000");
    CHECK(sim_run_until_idle(5000));
    sim_out_clear();
    sim_send("G0 X0 F3000\n");
    sim_run_ms(200);
    sim.spike_once = 1;
    CHECK(sim_run_until_idle(5000));
    CHECK(!sim_out_has("endstops hit"));
    CHECK(sim.phys[0] == 0);

    // M119 reports the switches.
    sim_reset();
    sim.force_open = 2;
    sim_cmd("M119");
    CHECK(sim_out_has("Reporting endstop status"));
    CHECK(sim_out_has("x_min: open") && sim_out_has("y_min: TRIGGERED") && sim_out_has("z_min: open"));

    // G28: all axes, Z first, stands at the switch, position 0.
    sim_reset();
    sim.trip_on[0] = sim.trip_on[1] = sim.trip_on[2] = true;
    sim.trip[0] = -8000;  // 100 mm away
    sim.trip[1] = -16000; // 200 mm away
    sim.trip[2] = -2000;
    sim_out_clear();
    sim_send("G28\n");
    sim_run_ms(50);
    CHECK(sim.steps[2] > 0 && sim.steps[0] == 0 && sim.steps[1] == 0); // Z first
    for (int i = 0; i < 20000 && sim_ok_count() == 0; i++) sim_run_ms(1);
    CHECK(sim_ok_count() == 1);
    CHECK(!sim_out_has("Error"));
    CHECK(sim_out_has("echo:busy: processing"));
    CHECK(sim.phys[0] >= sim.trip[0] - 2 && sim.phys[0] <= sim.trip[0]);
    CHECK(sim.phys[1] >= sim.trip[1] - 2 && sim.phys[1] <= sim.trip[1]);
    CHECK(sim.phys[2] >= sim.trip[2] - 2 && sim.phys[2] <= sim.trip[2]);
    sim_cmd("M114");
    CHECK(sim_out_has("X:0.000 Y:0.000 Z:0.000"));
    CHECK(motion_homed(AX_X) && motion_homed(AX_Y) && motion_homed(AX_Z));
    CHECK(sim.max_rate_seen <= 7400u); // X/Y 4000 steps/s, Z 7330 steps/s

    // After homing the axis can move again (it stands on the switch).
    int32_t z0 = sim.phys[2];
    sim_cmd("G0 Z10 F600");
    CHECK(sim_out_has("ok P"));
    CHECK(sim_run_until_idle(3000));
    CHECK(!sim_out_has("endstops hit"));
    CHECK(sim.phys[2] - z0 == 10186);

    // G28 with named axes homes only those.
    sim_reset();
    sim.trip_on[0] = sim.trip_on[1] = sim.trip_on[2] = true;
    sim.trip[0] = -800;
    sim_cmd("G28 X R0");
    CHECK(!sim_out_has("Error"));
    CHECK(sim.steps[1] == 0 && sim.steps[2] == 0);
    CHECK(motion_homed(AX_X) && !motion_homed(AX_Z));

    // Already on the switch: backs off first, then the slow approach.
    sim_reset();
    sim.trip_on[0] = true;
    sim.trip[0] = 0;
    sim_cmd("G28 X");
    CHECK(!sim_out_has("Error"));
    CHECK(sim.phys[0] >= -2 && sim.phys[0] <= 0);
    CHECK(sim.steps[0] >= 400 + 400); // 5 mm out, 5 mm back

    // No switch within the travel.
    sim_reset();
    sim_cmd("G28 Y");
    CHECK(sim_out_has("Error:Homing failed"));
    CHECK(sim_ok_count() == 1);
    CHECK(!motion_homed(AX_Y));
    CHECK(sim.steps[1] == 380u * 80u); // 370 + 10

    // Switch stays open after the backoff.
    sim_reset();
    sim.force_open = 1;
    sim_cmd("G28 X");
    CHECK(sim_out_has("Error:Homing failed"));

    // G30: stays at contact, reports, keeps the Z reference.
    sim_reset();
    sim.trip_on[2] = true;
    sim.trip[2] = 0;
    sim_cmd("G28 Z");
    sim_cmd("G0 X50 Y60 Z20 F3000");
    CHECK(sim_run_until_idle(15000));
    sim.trip[2] = sim.phys[2] - 15000; // surface about 14.7 mm further down
    sim.max_rate_seen = 0;
    sim_cmd("G30");
    CHECK(sim_ok_count() == 1);
    CHECK(sim_out_has("Bed X:50.000 Y:60.000 Z:"));
    CHECK(!sim_out_has("Error"));
    CHECK(sim.phys[2] >= sim.trip[2] - 2 && sim.phys[2] <= sim.trip[2]);
    CHECK(sim.max_rate_seen <= 3700u); // 216 mm/min * 1018.59 steps/mm / 60
    sim_cmd("M114");
    CHECK(motion_homed(AX_Z));
    // A plain G0 up leaves the contact, nothing is reported.
    sim_cmd("G0 Z20 F600");
    CHECK(sim_run_until_idle(15000));
    CHECK(!sim_out_has("endstops hit"));

    // G30 without contact ends at Z=-2 and fails there.
    sim_reset();
    sim_cmd("G0 Z1 F600");
    CHECK(sim_run_until_idle(5000));
    sim_cmd("G30");
    CHECK(sim_out_has("Error:Probing failed"));
    sim_cmd("M114");
    CHECK(sim_out_has("Z:-2.000"));

    // G30 with the switch open before it starts.
    sim_reset();
    sim.force_open = 4;
    sim_cmd("G30");
    CHECK(sim_out_has("Error:Probe already triggered"));
    CHECK(sim.steps[2] == 0);
}

void test_estop(void)
{
    // M112 while the queue and the line store are full: acts on arrival.
    sim_reset();
    sim_cmd("M106 P0 S255");
    sim_cmd("M8");
    sim_cmd("M355 S1 P100");
    CHECK(sim.relay && sim.exhaust && sim.light == 100);
    sim_cmd("M3 I");
    sim_out_clear();
    for (int i = 0; i < 100; i++) {
        char line[32];
        strcpy(line, i % 2 ? "G1 X300 F600 S200\n" : "G1 X1 F600 S200\n");
        sim_send(line);
        sim_run_ms(i < 79 ? 1 : 0);
    }
    sim_run_ms(100);
    CHECK(planner_free() == 0);
    CHECK(sim.pwm == 200);
    // Bytes go through the receive path, no main loop or step tick in between.
    sim_send("M112\n");
    CHECK(sim.all_off_called);
    CHECK(sim.pwm == 0);
    CHECK(!sim.relay && !sim.exhaust && sim.light == 0);
    CHECK(!sg_running());
    int32_t x = sim.phys[0];
    sim_run_ms(10);
    CHECK(sim.phys[0] == x);
    CHECK(planner_used() == 0);

    // Latched: everything except M115, M119, M999 gets the error, then ok.
    sim_run_ms(50);
    sim_out_clear();
    static const char *const refused[] = {"G0 X1", "M114", "M3 S10", "M3 I", "M106 P0 S255", "M8",
                                          "M355 S1", "M17", "G28", "G30", "M400", "garbage$",
                                          "M997 U100 C1"};
    for (size_t i = 0; i < sizeof refused / sizeof refused[0]; i++) {
        sim_cmd(refused[i]);
        CHECK(sim_out_has("Error:Emergency stop"));
        CHECK(sim_ok_count() == 1);
    }
    CHECK(sim.pwm == 0 && !sim.relay && !sim.exhaust);
    sim_cmd("M410");
    CHECK(sim_out_has("Error:Emergency stop"));
    sim_cmd("M115");
    CHECK(sim_out_has("FIRMWARE_NAME:LumaCut CNC") && sim_out_has("MACHINE_TYPE:LumaCut CNC"));
    CHECK(sim_out_has("Cap:Z_PROBE:1") && sim_out_has("Cap:SELF_UPDATE:1"));
    CHECK(!sim_out_has("Error"));
    sim_cmd("M119");
    CHECK(sim_out_has("x_min:") && !sim_out_has("Error"));

    // M999 clears it. The reference is gone, the outputs stay off.
    sim_cmd("M999");
    CHECK(!sim_out_has("Error"));
    CHECK(sim.armed_again);
    CHECK(sim.pwm == 0 && !sim.relay);
    sim_cmd("M114");
    CHECK(!sim_out_has("Error"));
    sim_cmd("G1 X0 F3000 S100");
    sim_run_ms(50);
    CHECK(sim.pwm == 0); // laser needs a new M3 I
    CHECK(sim_run_until_idle(20000));

    // M112 also stops a command waiting for the queue, and the reference dies.
    sim_reset();
    sim_home_all_at_zero();
    CHECK(motion_homed(AX_X));
    sim_send("G0 X100 F600\nM400\n");
    sim_run_ms(50);
    sim_out_clear();
    sim_send("M112\n");
    sim_run_ms(5);
    CHECK(sim_ok_count() >= 2); // M400 aborted, M112 acknowledged
    CHECK(sim_out_has("Error:Emergency stop"));
    sim_cmd("M999");
    CHECK(!motion_homed(AX_X));

    // M112 during G28.
    sim_reset();
    sim.trip_on[2] = true;
    sim.trip[2] = -50000;
    sim_send("G28\n");
    sim_run_ms(100);
    sim_out_clear();
    sim_send("M112\n");
    sim_run_ms(5);
    CHECK(sim_out_has("Error:Emergency stop"));
    uint32_t z = sim.steps[2];
    sim_run_ms(100);
    CHECK(sim.steps[2] == z);

    // M410: stop, laser off, queue empty, position from the counters, reference stays.
    sim_reset();
    sim_home_all_at_zero();
    int32_t home_x = sim.phys[0]; // up to two steps past the trip point
    sim_cmd("M106 P0 S255");
    sim_cmd("M3 I");
    sim_send("G1 X100 F1200 S150\nG1 X200\nG1 X300\n");
    sim_run_ms(500);
    CHECK(sim.pwm == 150);
    sim_send("G1 X10\nG1 X20\nG1 X30\nM410\n");
    CHECK(sim.pwm == 0);
    CHECK(!sg_running());
    x = sim.phys[0];
    sim_out_clear();
    sim_run_ms(50);
    CHECK(sim.phys[0] == x); // the lines before M410 do not move anything
    CHECK(sim_ok_count() >= 3); // but they are answered, the host keeps counting
    CHECK(!sim_out_has("Error"));
    CHECK(sim.relay); // the relay stays, M410 only stops
    CHECK(motion_homed(AX_X));
    CHECK(planner_position(AX_X) == x - home_x);
    sim_cmd("M114");
    CHECK(sim_out_has("ok P63 B16"));
    // Afterwards it works again.
    sim_cmd("G0 X0 F3000");
    CHECK(!sim_out_has("Error"));
    CHECK(sim_run_until_idle(10000));
    CHECK(sim.phys[0] == home_x);

    // Lines after M410 are normal commands again.
    sim_reset();
    sim_send("M410\nG0 X1 F600\n");
    CHECK(sim_run_until_idle(2000));
    sim_run_ms(50);
    CHECK(sim.phys[0] == 80);
}
