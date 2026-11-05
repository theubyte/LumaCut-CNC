// Self-update protocol and the remaining commands.
#include "../src/crc32.h"
#include "../src/motion.h"
#include "../src/planner.h"
#include "../src/stepgen.h"
#include "../src/update.h"
#include "../version.h"
#include "sim.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint8_t image[64 * 1024];

static void make_image(uint32_t size)
{
    for (uint32_t i = 0; i < size; i++) image[i] = (uint8_t)(i * 31u + (i >> 8));
    uint32_t sp = 0x20010000u, reset = APP_ADDR + 0x401u;
    memcpy(image, &sp, 4);
    memcpy(image + 4, &reset, 4);
    memcpy(image + size / 2, LUMACUT_ID, strlen(LUMACUT_ID));
}

// Host side of M997. Returns false on an unexpected reply.
static bool send_image(uint32_t size, uint32_t crc_flip)
{
    char line[64];
    snprintf(line, sizeof line, "M997 U%lu C%lu", (unsigned long)size,
             (unsigned long)(crc32_update(0, image, size) ^ crc_flip));
    sim_out_clear();
    sim_send(line);
    sim_send("\n");
    sim_run_ms(2);
    if (!sim_out_has("ok READY 1024\n")) return false;
    uint32_t off = 0;
    while (off < size) {
        uint32_t n = size - off < 1024u ? size - off : 1024u;
        sim_out_clear();
        for (uint32_t i = 0; i < n; i += 64u) {
            sim_send_bytes(image + off + i, n - i < 64u ? n - i : 64u);
        }
        sim_run_ms(2);
        off += n;
        snprintf(line, sizeof line, "ok %lu\n", (unsigned long)off);
        if (!sim_out_has(line)) return false;
    }
    return true;
}

void test_update(void)
{
    // Image checks.
    make_image(4096);
    CHECK(update_image_valid(image, 4096));
    uint8_t saved = image[2048];
    image[2048] ^= 0xFF;
    CHECK(!update_image_valid(image, 4096)); // no LumaCut CNC text
    image[2048] = saved;
    image[3] = 0x10; // stack pointer not in RAM
    CHECK(!update_image_valid(image, 4096));
    make_image(4096);
    image[4] = 0x00; // even reset vector
    CHECK(!update_image_valid(image, 4096));
    make_image(4096);
    uint32_t bad = APP_ADDR + 8192u + 1u;
    memcpy(image + 4, &bad, 4); // reset vector behind the image
    CHECK(!update_image_valid(image, 4096));

    // Whole transfer with several pages and a short last chunk.
    sim_reset();
    make_image(5000);
    CHECK(send_image(5000, 0));
    sim_run_ms(10);
    CHECK(sim_out_has("ok DONE"));
    CHECK(sim.selfcopy_bytes == 0); // not before the reply left
    sim_run_ms(100);
    CHECK(sim.selfcopy_bytes == 5000);
    CHECK(memcmp(sim.stage, image, 5000) == 0);

    // Wrong CRC: refused, back to normal lines, nothing copied.
    sim_reset();
    make_image(5000);
    CHECK(send_image(5000, 1));
    sim_run_ms(20);
    CHECK(sim_out_has("Error:Update CRC") && sim_ok_count() >= 1);
    sim_run_ms(100);
    CHECK(sim.selfcopy_bytes == 0);
    sim_cmd("M114");
    CHECK(sim_out_has("X:0.000"));

    // Image without the LumaCut mark (right CRC).
    sim_reset();
    make_image(5000);
    memset(image + 2500, 0, strlen(LUMACUT_ID));
    CHECK(send_image(5000, 0));
    sim_run_ms(20);
    CHECK(sim_out_has("Error:Update image"));
    CHECK(sim.selfcopy_bytes == 0);

    // Size limits.
    sim_reset();
    sim_cmd("M997 U200705 C1");
    CHECK(sim_out_has("Error:Update size"));
    sim_cmd("M997 U0 C1");
    CHECK(sim_out_has("Error:Update size"));
    sim_cmd("M997 U100");
    CHECK(sim_out_has("Error:Update arguments"));

    // Chip too small for the stage (register 0x1FFFF7E0).
    sim.flash_kb = 256;
    sim_cmd("M997 U1000 C1");
    CHECK(sim_out_has("Error:Update flash size"));
    sim.flash_kb = 512;

    // Only at standstill, laser and relay off.
    sim_reset();
    sim_send("G0 X100 F600\n");
    sim_run_ms(50);
    sim_cmd("M997 U1000 C1");
    CHECK(sim_out_has("Error:Update refused: machine moving"));
    sim_send("M410\n");
    sim_run_ms(5);
    sim_cmd("M3 I");
    sim_cmd("M997 U1000 C1");
    CHECK(sim_out_has("Error:Update refused"));
    sim_cmd("M5 I");
    sim_cmd("M106 P0 S255");
    sim_cmd("M997 U1000 C1");
    CHECK(sim_out_has("Error:Update refused"));
    sim_cmd("M107 P0");
    sim_cmd("M3 S10");
    sim_cmd("M997 U1000 C1");
    CHECK(sim_out_has("Error:Update refused"));
    sim_cmd("M5");

    // Host goes silent: gives up and takes lines again.
    sim_reset();
    sim_cmd("M997 U4000 C1");
    CHECK(sim_out_has("ok READY"));
    sim_out_clear();
    sim_send_bytes(image, 100);
    sim_run_ms(UPDATE_TIMEOUT_MS + 100);
    CHECK(sim_out_has("Error:Update timeout"));
    sim_cmd("M114");
    CHECK(sim_out_has("X:0.000"));

    // Flash write failure.
    sim_reset();
    sim.stage_fail_write = true;
    sim_cmd("M997 U1024 C1");
    sim_out_clear();
    sim_send_bytes(image, 1024);
    sim_run_ms(5);
    CHECK(sim_out_has("Error:Update flash write"));

    // USB lost during the transfer.
    sim_reset();
    sim_cmd("M997 U4000 C1");
    sim.link_ok = false;
    sim_run_ms(2);
    CHECK(!update_active());
    sim.link_ok = true;
}

void test_commands(void)
{
    // Every command gets its ok; unknown ones the fixed error first.
    sim_reset();
    static const char *const unknown[] = {"G20", "G17", "G54", "M2", "M105", "M120", "M503",
                                          "M851 Z0", "M7", "M28", "M593 Y F10", "G1 G1", "T0"};
    for (size_t i = 0; i < sizeof unknown / sizeof unknown[0]; i++) {
        sim_cmd(unknown[i]);
        char want[96];
        snprintf(want, sizeof want, "Error:Unknown command: %s\nok P", unknown[i]);
        CHECK(sim_out_has(want));
        CHECK(sim_ok_count() == 1);
    }
    sim_cmd("M410 extra");
    CHECK(sim_out_has("Error:Unknown command"));

    static const char *const fine[] = {"G21", "G90", "M5", "M5 I", "M84", "M9", "M107 P0", "M400",
                                       "; just a comment", "(comment)", "M204 P500 T500", "M201 X500",
                                       "M203 X150"};
    for (size_t i = 0; i < sizeof fine / sizeof fine[0]; i++) {
        sim_cmd(fine[i]);
        CHECK(sim_ok_count() == 1);
        CHECK(!sim_out_has("Error"));
    }

    // Too long line.
    char line[200];
    memset(line, 'X', sizeof line);
    line[150] = 0;
    sim_cmd(line);
    CHECK(sim_out_has("Error:Line too long") && sim_ok_count() == 1);

    // Blank lines and CRLF: one ok per command.
    sim_out_clear();
    sim_send("M114\r\n\r\n\n");
    sim_run_ms(2);
    CHECK(sim_ok_count() == 1);

    // Reply format of M114.
    sim_reset();
    sim_cmd("G0 X1.5 Y2.25 Z0.5 F6000");
    sim_cmd("M114");
    CHECK(sim_out_has("X:1.500 Y:2.250 Z:0.500 Count X:120 Y:180 Z:509\n"));
    CHECK(sim_out_has("\nok P"));
    CHECK(sim_run_until_idle(3000));

    // M114 while moving: planned end, and it does not touch the PWM.
    sim_reset();
    sim_cmd("M3 I");
    sim_send("G1 X100 F1200 S120\n");
    sim_run_ms(300);
    uint32_t writes = sim.pwm_writes;
    for (int i = 0; i < 200; i++) sim_cmd("M114");
    CHECK(sim.pwm_writes == writes);
    CHECK(sim.pwm == 120);
    CHECK(sim_out_has("X:100.000"));
    sim_send("M410\n");
    sim_run_ms(5);

    // Rule 8: current on only with the first move or M17, off with M84.
    sim_reset();
    CHECK(!sim.motors);
    sim_cmd("M114");
    sim_cmd("G21");
    CHECK(!sim.motors);
    sim_cmd("M17");
    CHECK(sim.motors);
    sim_cmd("M84");
    CHECK(!sim.motors);
    sim_cmd("G0 X1 F600");
    CHECK(sim.motors);
    // M84 waits for standstill.
    sim_send("M84\n");
    sim_run_ms(5);
    CHECK(sim.motors);
    CHECK(sim_run_until_idle(2000));
    sim_run_ms(2);
    CHECK(!sim.motors);
    // No self-shutdown after long idle.
    sim_cmd("M17");
    sim_run_ms(30000);
    CHECK(sim.motors);

    // Relay waits for the queue, exhaust and light act at once.
    sim_reset();
    sim_send("G0 X10 F600\nM106 P0 S255\n");
    sim_run_ms(50);
    CHECK(!sim.relay);
    CHECK(sim_run_until_idle(3000));
    sim_run_ms(2);
    CHECK(sim.relay);
    sim_cmd("M107 P0");
    CHECK(!sim.relay);
    sim_cmd("M106 P0 S0");
    CHECK(!sim.relay);
    sim_cmd("M106 P1 S255");
    CHECK(sim_out_has("Error:Unknown command") && !sim.relay);
    sim_cmd("M8");
    CHECK(sim.exhaust);
    sim_cmd("M9");
    CHECK(!sim.exhaust);
    sim_cmd("M355 S1 P200");
    CHECK(sim.light == 200);
    sim_cmd("M355 P50");
    CHECK(sim.light == 50);
    sim_cmd("M355 S0");
    CHECK(sim.light == 0);
    sim_cmd("M355 S1");
    CHECK(sim.light == 50);
    sim_cmd("M355 P300");
    CHECK(sim_out_has("Error:P out of range"));

    // F is modal, separate for G0 and G1.
    sim_reset();
    sim_cmd("G0 X10 F600");
    sim_cmd("G1 X20 F1200");
    uint64_t t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(5000));
    sim_cmd("G0 X30");
    t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(5000));
    double t_g0 = (double)(sim.now_ticks - t0) / STEP_TICK_HZ;
    sim_cmd("G1 X40");
    t0 = sim.now_ticks;
    CHECK(sim_run_until_idle(5000));
    double t_g1 = (double)(sim.now_ticks - t0) / STEP_TICK_HZ;
    CHECK(t_g0 > 0.95 && t_g0 < 1.2);  // 10 mm at 10 mm/s
    CHECK(t_g1 > 0.48 && t_g1 < 0.62); // 10 mm at 20 mm/s
    sim_cmd("G1 X50 F0");
    CHECK(sim_out_has("Error:Invalid feedrate"));

    // G4 takes its place in the queue.
    sim_reset();
    sim_send("G0 X1 F600\nG4 P300\nM400\n");
    t0 = sim.now_ticks;
    for (int i = 0; i < 5000 && sim_ok_count() < 3; i++) sim_run_ms(1);
    double t = (double)(sim.now_ticks - t0) / STEP_TICK_HZ;
    CHECK(t > 0.3 + 0.08 && t < 0.3 + 0.2);
    sim_out_clear();
    sim_send("G4 S1\nM400\n");
    t0 = sim.now_ticks;
    for (int i = 0; i < 5000 && sim_ok_count() < 2; i++) sim_run_ms(1);
    CHECK(sim.now_ticks - t0 > STEP_TICK_HZ && sim.now_ticks - t0 < STEP_TICK_HZ + STEP_TICK_HZ / 10);
    sim_cmd("G4");
    CHECK(sim_out_has("Error:Dwell needs P or S"));

    // M400 answers only at standstill.
    sim_reset();
    sim_out_clear();
    sim_send("G0 X50 F3000\nM400\n");
    sim_run_ms(100);
    CHECK(sim_ok_count() == 1);
    for (int i = 0; i < 5000 && sim_ok_count() < 2; i++) sim_run_ms(1);
    CHECK(sim_ok_count() == 2);
    CHECK(!sg_running() && sim.phys[0] == 4000);

    // G92 waits for standstill and changes no motor position.
    sim_reset();
    sim_send("G0 X10 F600\nG92 X100 Y7\n");
    CHECK(sim_run_until_idle(3000));
    sim_run_ms(5);
    CHECK(sim.phys[0] == 800);
    sim_cmd("M114");
    CHECK(sim_out_has("X:100.000 Y:7.000") && sim_out_has("Count X:8000 Y:560"));
    sim_cmd("G0 X110 F600");
    CHECK(sim_run_until_idle(3000));
    CHECK(sim.phys[0] == 1600);

    // M300: sings without moving, restores everything.
    sim_reset();
    sim_out_clear();
    sim_send("M300 S1000 P100\n");
    sim_run_ms(2);
    CHECK(sim.motors);
    CHECK(sim.tmc_reg[0][0] & 4u); // SpreadCycle during the tone
    CHECK(sim.tmc_reg[2][0] & 4u);
    CHECK(sim_ok_count() == 0);
    sim_run_ms(150);
    CHECK(sim_ok_count() == 1);
    CHECK(sim.steps[0] == 200 && sim.steps[1] == 200 && sim.steps[2] == 0);
    CHECK(sim.phys[0] == 0 && sim.phys[1] == 0); // net travel zero
    CHECK(!(sim.tmc_reg[0][0] & 4u));
    CHECK(!sim.motors); // was off before
    sim_cmd("M114");
    CHECK(sim_out_has("X:0.000 Y:0.000"));

    // Then a normal move in plus direction is still a plus move.
    sim_cmd("G0 X1 F600");
    CHECK(sim_run_until_idle(2000));
    CHECK(sim.phys[0] == 80);
    CHECK(sim.motors);

    // X only, motors stay on when they were on; S0 is a rest, at most 2 s.
    sim_out_clear();
    sim_send("M300 S500 P100 X\n");
    CHECK(sim_run_until_idle(500));
    sim_run_ms(200);
    CHECK(sim_ok_count() == 1);
    CHECK(sim.steps[0] == 200 + 80 + 100 && sim.steps[1] == 200);
    CHECK(sim.motors);
    sim_out_clear();
    t0 = sim.now_ticks;
    sim_send("M300 S0 P99999\n");
    for (int i = 0; i < 5000 && sim_ok_count() < 1; i++) sim_run_ms(1);
    CHECK(sim.now_ticks - t0 >= 2 * STEP_TICK_HZ && sim.now_ticks - t0 < 2 * STEP_TICK_HZ + STEP_TICK_HZ / 100);
    sim_cmd("M300 S20 P100");
    CHECK(sim_out_has("S must be"));

    // Refused while the laser can burn.
    sim_reset();
    sim_cmd("M3 I");
    sim_cmd("M300 S1000 P100");
    CHECK(sim_out_has("M300 refused"));
    CHECK(sim.steps[0] == 0);
    sim_cmd("M5 I");
    sim_cmd("M3 S20");
    sim_cmd("M300 S1000 P100");
    CHECK(sim_out_has("M300 refused"));
    sim_cmd("M5");

    // M410 during a tone leaves the driver in StealthChop again.
    sim_reset();
    sim_send("M300 S1000 P1000\n");
    sim_run_ms(50);
    CHECK(sim.tmc_reg[0][0] & 4u);
    sim_send("M410\n");
    sim_run_ms(5);
    CHECK(!(sim.tmc_reg[0][0] & 4u));
    CHECK(!sg_running());

    // First contact reports why the board restarted.
    sim_reset();
    sim_run_ms(2);
    CHECK(sim_out_has("echo:LumaCut reset=test"));
}
