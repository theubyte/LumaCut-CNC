// Planner and arcs, watched through the simulated step timer.
#include "../src/arc.h"
#include "../src/motion.h"
#include "../src/planner.h"
#include "../src/stepgen.h"
#include "sim.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

// Sends lines the way the Pi does: keeps as many unanswered as B allows.
static void stream(const char *fmt, int count, double a, double b)
{
    int sent = 0, acked = 0;
    char line[96];
    sim_out_clear();
    while (acked < count) {
        while (sent < count && sent - acked < 8) {
            snprintf(line, sizeof line, fmt, a * (sent + 1), b * (sent + 1));
            sim_send(line);
            sim_send("\n");
            sent++;
        }
        sim_run_ms(1);
        acked = sim_ok_count();
        if (acked > 2000) { // keep the capture buffer small
            count -= acked;
            sent -= acked;
            acked = 0;
            sim_out_clear();
        }
    }
    sim_out_clear();
}

static double trace_peak(void)
{
    uint32_t peak = 0;
    for (size_t i = 0; i < sim.trace_n; i++) {
        if (sim.trace_rate[i] > peak) peak = sim.trace_rate[i];
    }
    return peak;
}

static void test_trapezoid(void)
{
    sim_reset();
    sim.trace_on = true;
    sim_cmd("G1 X100 F6000"); // 100 mm/s, 500 mm/s^2
    uint64_t t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(5000));
    double seconds = (double)(sim.now_ticks - t0) / STEP_TICK_HZ;
    CHECK(sim.phys[0] == 8000);
    CHECK(sim.steps[1] == 0 && sim.steps[2] == 0);
    CHECK_NEAR(trace_peak(), 8000.0, 40.0);
    CHECK_NEAR(seconds, 1.2, 0.05); // 1 s cruise equivalent + 2 * v/(2a)

    // Rate never jumps by more than the acceleration allows between steps,
    // apart from the very first step from rest. Rates come from whole timer
    // ticks, so one tick of rounding is allowed on top.
    double a = 500.0 * 80.0;
    for (size_t i = 2; i < sim.trace_n; i++) {
        double dt = (double)(sim.trace_time[i] - sim.trace_time[i - 1]) / STEP_TICK_HZ;
        double dv = (double)sim.trace_rate[i] - (double)sim.trace_rate[i - 1];
        double tick = (double)sim.trace_rate[i] * sim.trace_rate[i] / STEP_TICK_HZ;
        if (fabs(dv) > a * dt * 1.5 + tick + 2.0) {
            CHECK(fabs(dv) <= a * dt * 1.5 + tick + 2.0);
            break;
        }
    }

    // Triangle: too short to reach the feed. v^2 = a*d.
    sim_reset();
    sim.trace_on = true;
    sim_cmd("G1 X5 F9000");
    CHECK(sim_run_until_idle(2000));
    CHECK(sim.phys[0] == 400);
    CHECK_NEAR(trace_peak(), sqrt(500.0 * 5.0) * 80.0, 200.0);

    // Slow move far below the 16-bit timer range still keeps its feed.
    sim_reset();
    sim_cmd("G1 X0.2 F6"); // 0.1 mm/s
    t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(4000));
    CHECK(sim.phys[0] == 16);
    CHECK_NEAR((double)(sim.now_ticks - t0) / STEP_TICK_HZ, 2.0, 0.2);

    // Very slow and very long: no overflow in the planned duration.
    sim_reset();
    sim_cmd("G1 X100 F0.01");
    sim_run_ms(2000);
    CHECK(sg_running());
    CHECK(sim.phys[0] < 5);
    sim_send("M410\n");
    sim_run_ms(2);

    // Diagonal: both axes step exactly, Bresenham shares them out evenly.
    sim_reset();
    sim_cmd("G1 X10 Y3.3 F3000");
    CHECK(sim_run_until_idle(2000));
    CHECK(sim.phys[0] == 800 && sim.phys[1] == 264);
}

static void test_lookahead(void)
{
    // Collinear segments: no slowdown at the joints.
    sim_reset();
    sim.trace_on = true;
    sim_send("G1 X50 F6000\nG1 X100\nG1 X150\n");
    sim_run_ms(5);
    uint64_t t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 12000);
    CHECK_NEAR((double)(sim.now_ticks - t0) / STEP_TICK_HZ, 1.7, 0.1);
    uint32_t low = 100000;
    for (size_t i = 0; i < sim.trace_n; i++) {
        double x = (double)i / 80.0;
        if (x > 30.0 && x < 120.0 && sim.trace_rate[i] < low) low = sim.trace_rate[i];
    }
    CHECK(low > 7800);

    // 90 degree corner: both legs brake to the junction speed, not to zero.
    sim_reset();
    sim.trace_on = true;
    sim_send("G1 X50 F6000\nG1 Y50\n");
    sim_run_ms(5);
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 4000 && sim.phys[1] == 4000);
    double sin_half = sqrt(0.5);
    double vj = sqrt(500.0 * 0.05 * sin_half / (1.0 - sin_half));
    low = 100000;
    size_t low_i = 0;
    for (size_t i = 1000; i < sim.trace_n - 1000; i++) {
        if (sim.trace_rate[i] < low) {
            low = sim.trace_rate[i];
            low_i = i;
        }
    }
    CHECK_NEAR(low / 80.0, vj, vj * 0.35);
    CHECK_NEAR((double)low_i, 4000.0, 30.0);

    // Reversal: full stop in between.
    sim_reset();
    sim.trace_on = true;
    sim_send("G1 X20 F3000\nG1 X0\n");
    sim_run_ms(5);
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 0 && sim.steps[0] == 3200);
    CHECK(!sim.step_with_dir_change);
    low = 100000;
    for (size_t i = 1000; i < 2200; i++) {
        if (sim.trace_rate[i] < low) low = sim.trace_rate[i];
    }
    CHECK(low < 300);

    // Long raster line of short segments, fed as fast as the ok lines allow:
    // it must keep the feed and not stutter (0.2 mm at 100 mm/s = 500 lines/s).
    sim_reset();
    sim.trace_on = true;
    stream("G1 X%.3f F6000", 1000, 0.2, 0.0);
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[0] == 16000);
    low = 100000;
    for (size_t i = 2000; i < sim.trace_n - 2000; i++) {
        if (sim.trace_rate[i] < low) low = sim.trace_rate[i];
    }
    CHECK(low > 7800);

    // A host that pauses: the queue runs dry and the planner brakes normally,
    // no hard stop at full speed.
    sim_reset();
    sim.trace_on = true;
    sim_cmd("G1 X50 F6000");
    CHECK(sim_run_until_idle(3000));
    size_t n = sim.trace_n;
    CHECK(n > 100);
    CHECK(sim.trace_rate[n - 1] < 500);
}

static void test_no_rounding_drift(void)
{
    // 3900 relative moves of 0.1 mm: exactly 390 mm, exactly 31200 steps.
    sim_reset();
    sim_cmd("G91");
    stream("G1 X0.1 F6000 ; %.0f %.0f", 3900, 0.0, 0.0);
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[0] == 31200);
    sim_cmd("M114");
    CHECK(sim_out_has("X:390.000") && sim_out_has("Count X:31200"));

    // Moves below one step add up instead of vanishing: 0.003 mm is 0.24 steps.
    sim_reset();
    sim_cmd("G91");
    stream("G1 X0.003 F600 ; %.0f %.0f", 1000, 0.0, 0.0);
    CHECK(sim_run_until_idle(2000));
    CHECK(sim.phys[0] == 240);
    sim_cmd("M114");
    CHECK(sim_out_has("X:3.000"));

    // Z with its non-integer steps/mm, absolute there and back many times.
    sim_reset();
    for (int i = 0; i < 50; i++) {
        sim_cmd("G1 Z1.234 F300");
        CHECK(sim_run_until_idle(2000));
        sim_cmd("G1 Z0 F300");
        CHECK(sim_run_until_idle(2000));
    }
    CHECK(sim.phys[2] == 0);
    sim_cmd("G1 Z10 F300");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[2] == 10186); // round(10 * 1018.59)
    sim_cmd("M114");
    CHECK(sim_out_has("Z:10.000") && sim_out_has("Z:10186"));
}

static void test_limits(void)
{
    sim_reset();
    sim_cmd("G0 X390.001");
    CHECK(sim_out_has("Error:Out of bounds") && sim_ok_count() == 1);
    sim_cmd("G0 Y370.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 X-0.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z-2.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z80.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G1 X99999999999");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_run_ms(50);
    CHECK(sim.steps[0] == 0 && sim.steps[1] == 0 && sim.steps[2] == 0);
    CHECK(!sim.motors); // rule 8: refused moves do not energise anything

    // Within travel it moves to the very edge, but Z never above 80.
    sim_cmd("G0 X390 Y370 Z80 F60000");
    CHECK(sim_out_has("ok P"));
    CHECK(sim_run_until_idle(30000));
    CHECK(sim.phys[0] == 31200 && sim.phys[1] == 29600 && sim.phys[2] == 81487);

    sim_cmd("G91");
    sim_cmd("G0 Z0.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G90");

    // G92 cannot be used to get around the hard Z limit once Z is referenced.
    sim_reset();
    sim_home_all_at_zero();
    sim_cmd("G0 Z70 F600");
    CHECK(sim_run_until_idle(20000));
    sim_cmd("G92 Z0");
    CHECK(sim_out_has("ok P"));
    sim_cmd("G0 Z10.001");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_cmd("G0 Z10");
    CHECK(sim_out_has("ok P"));
    CHECK(sim_run_until_idle(20000));
    sim_cmd("M114");
    CHECK(sim_out_has("Z:10.000"));
    sim_cmd("G92 Z80.5");
    CHECK(sim_out_has("Error:Out of bounds"));

    // M203 Z is capped at 9 mm/s and no F beats it.
    sim_reset();
    sim_cmd("M203 Z100");
    CHECK(motion_limits()->max_feed[AX_Z] == 9.0f);
    sim_cmd("G0 Z30 F60000");
    CHECK(sim_run_until_idle(20000));
    CHECK(sim.max_rate_seen <= (uint32_t)(9.0 * 1018.59) + 2u);

    // 15 kHz limit holds whatever M203, M92 and F say.
    sim_reset();
    sim_cmd("M203 X100000 Y100000");
    sim_cmd("M201 X100000 Y100000");
    sim_cmd("M204 P100000 T100000");
    sim_cmd("G0 X300 F6000000");
    CHECK(sim_run_until_idle(20000));
    CHECK(sim.max_rate_seen <= MAX_STEP_RATE + 2u);
    CHECK(sim.max_rate_seen > 14000u);
    CHECK(sim.min_interval_ticks >= STEP_TICK_HZ / (MAX_STEP_RATE + 2u));

    // Runtime values: M92 keeps the mm position and changes the steps.
    sim_reset();
    sim_cmd("G0 X10 F6000");
    CHECK(sim_run_until_idle(5000));
    sim_cmd("M92 X160");
    sim_cmd("M114");
    CHECK(sim_out_has("X:10.000") && sim_out_has("Count X:1600"));
    sim_cmd("G0 X11");
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.steps[0] == 800 + 160);
    sim_cmd("M92 X0");
    CHECK(sim_out_has("Error:Invalid value"));
}

static void test_queue_sizes(void)
{
    sim_reset();
    sim_cmd("M114");
    CHECK(sim_out_has("ok P63 B16"));

    // The contract: at least 32 blocks and 16 lines of 96 characters.
    sim_out_clear();
    for (int i = 0; i < 16; i++) {
        char line[97];
        memset(line, ' ', sizeof line);
        int n = snprintf(line, sizeof line, "G0 X%d", 300 - i * 10);
        line[n] = ' ';
        line[95] = 0;
        sim_send(line);
        sim_send("\n");
    }
    sim_run_ms(3);
    CHECK(sim_ok_count() == 16);

    // A full queue answers late, never loses a line.
    sim_reset();
    sim_out_clear();
    int acked = 0, sent = 0;
    while (sent < 200) {
        char line[40];
        snprintf(line, sizeof line, "G1 X%d F600\n", (sent % 2) ? 300 : 0);
        sim_send(line);
        sent++;
        for (int i = 0; i < 4; i++) sim_run_ms(1);
        if (sent - sim_ok_count() >= 15) break;
    }
    acked = sim_ok_count();
    CHECK(acked < sent);
    CHECK(sent - acked <= 16);
    CHECK(sim_out_has("ok P0"));
    sim_send("M410\n");
    sim_run_ms(5);
    CHECK(!sg_running() && planner_used() == 0);
}

void test_planner(void)
{
    test_trapezoid();
    test_lookahead();
    test_no_rounding_drift();
    test_limits();
    test_queue_sizes();
}

// Distance of the chord midpoint from the true arc: the contract's chord error.
static double max_chord_error(const arc_t *a, double r)
{
    double worst = 0.0;
    int32_t px, py;
    arc_point(a, 1, &px, &py);
    for (uint32_t k = 2; k <= a->segments; k++) {
        int32_t x, y;
        arc_point(a, k, &x, &y);
        double mx = 0.5 * ((double)px + x) / FIX_PER_MM - (double)a->cx / FIX_PER_MM;
        double my = 0.5 * ((double)py + y) / FIX_PER_MM - (double)a->cy / FIX_PER_MM;
        double e = r - sqrt(mx * mx + my * my);
        if (e > worst) worst = e;
        px = x;
        py = y;
    }
    return worst;
}

void test_arc(void)
{
    arc_t a;
    static const double radii[] = {0.5, 2.0, 10.0, 50.0, 180.0};
    for (size_t i = 0; i < sizeof radii / sizeof radii[0]; i++) {
        double r = radii[i];
        int32_t rf = (int32_t)(r * FIX_PER_MM);
        // Quarter circle from (r,0) around the origin of the arc.
        CHECK(arc_plan(&a, rf, 0, 0, rf, -rf, 0, false));
        CHECK(a.sweep > 0.0f);
        CHECK(max_chord_error(&a, r) <= 0.1);
        CHECK(max_chord_error(&a, r) <= ARC_TOLERANCE_MM * 1.2);
        int32_t x, y;
        arc_point(&a, a.segments, &x, &y);
        CHECK(x == 0 && y == rf); // exact end
        // First point really lies on the circle.
        arc_point(&a, 1, &x, &y);
        CHECK_NEAR(sqrt((double)x * x + (double)y * y) / FIX_PER_MM, r, 0.001);
    }

    // Direction: G2 clockwise, G3 counter clockwise, the long way round.
    CHECK(arc_plan(&a, 1000000, 0, 0, 1000000, -1000000, 0, true));
    CHECK(a.sweep < 0.0f);
    CHECK_NEAR(a.sweep, -1.5 * 3.14159265, 0.001);

    // Same start and end is a full circle.
    CHECK(arc_plan(&a, 1000000, 0, 1000000, 0, -1000000, 0, false));
    CHECK_NEAR(a.sweep, 2.0 * 3.14159265, 0.001);
    CHECK(arc_plan(&a, 1000000, 0, 1000000, 0, -1000000, 0, true));
    CHECK_NEAR(a.sweep, -2.0 * 3.14159265, 0.001);

    // End point off the circle or no radius is refused.
    CHECK(!arc_plan(&a, 1000000, 0, 0, 2000000, -1000000, 0, false));
    CHECK(!arc_plan(&a, 0, 0, 100000, 0, 0, 0, false));

    // Through the command layer.
    sim_reset();
    sim_cmd("G0 X100 Y100 F6000");
    CHECK(sim_run_until_idle(5000));
    sim_cmd("G2 X120 Y120 I20 J0 F3000 S0");
    CHECK(sim_out_has("ok P"));
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 9600 && sim.phys[1] == 9600);
    sim_cmd("M114");
    CHECK(sim_out_has("X:120.000 Y:120.000"));

    sim_cmd("G3 X100 Y100 I-20 J0 F3000");
    CHECK(sim_run_until_idle(5000));
    CHECK(sim.phys[0] == 8000 && sim.phys[1] == 8000);

    // A circle that leaves the travel is refused as a whole, nothing moves.
    uint32_t before = sim.steps[0];
    sim_cmd("G2 X100 Y100 I-150 J0");
    CHECK(sim_out_has("Error:Out of bounds"));
    sim_run_ms(50);
    CHECK(sim.steps[0] == before);

    sim_cmd("G2 X110 Y100 I1 J0");
    CHECK(sim_out_has("Error:Arc invalid"));
    sim_cmd("G2 X110 Y100 I5 J0 Z3");
    CHECK(sim_out_has("Error:Unknown command"));

    // Long arc with many chords larger than the queue: still every step.
    sim_reset();
    sim_cmd("G0 X200 Y200 F6000");
    CHECK(sim_run_until_idle(5000));
    uint32_t chords;
    CHECK(arc_plan(&a, MM_FIX(200), MM_FIX(200), MM_FIX(200), MM_FIX(200), MM_FIX(-1), 0, false));
    chords = a.segments;
    CHECK(chords > 0);
    sim_cmd("G3 X200 Y200 I-150 J0 F6000");
    CHECK(sim_run_until_idle(20000));
    CHECK(sim.phys[0] == 16000 && sim.phys[1] == 16000);
}
