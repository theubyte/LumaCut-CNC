// Parser, CRC and TMC frames: plain functions, no simulation needed.
#include "../src/crc32.h"
#include "../src/gcode.h"
#include "../src/tmc.h"
#include "sim.h"
#include <string.h>

static gcode_t g;

void test_parser(void)
{
    CHECK(gcode_parse("G1 X10 Y-2.5 F600 S255", &g) == GC_OK);
    CHECK(g.letter == 'G' && g.code == 1);
    CHECK(gc_fix(&g, 'X') == 1000000);
    CHECK(gc_fix(&g, 'Y') == -250000);
    CHECK(gc_int(&g, 'F') == 600);
    CHECK(gc_int(&g, 'S') == 255);

    CHECK(gcode_parse("g1x.5y+1", &g) == GC_OK); // lower case, no spaces
    CHECK(gc_fix(&g, 'X') == 50000 && gc_fix(&g, 'Y') == 100000);

    CHECK(gcode_parse("G1 X1.234567", &g) == GC_OK);
    CHECK(gc_fix(&g, 'X') == 123457); // rounded at the sixth place

    CHECK(gcode_parse("M3 I", &g) == GC_OK);
    CHECK(gc_has(&g, 'I') && !gc_num(&g, 'I'));

    CHECK(gcode_parse("G28 X Y R0", &g) == GC_OK);
    CHECK(gc_has(&g, 'X') && gc_has(&g, 'Y') && !gc_num(&g, 'X') && gc_num(&g, 'R'));

    CHECK(gcode_parse("G0 X1 ; comment X99", &g) == GC_OK);
    CHECK(gc_fix(&g, 'X') == 100000);
    CHECK(gcode_parse("G0 (move) X2 (more)", &g) == GC_OK);
    CHECK(gc_fix(&g, 'X') == 200000);
    CHECK(gcode_parse("; only comment", &g) == GC_EMPTY);
    CHECK(gcode_parse("(only comment)", &g) == GC_EMPTY);
    CHECK(gcode_parse("   ", &g) == GC_EMPTY);

    CHECK(gcode_parse("M997 U204800 C4294967295", &g) == GC_OK);
    CHECK(gc_int(&g, 'C') == 4294967295LL);

    CHECK(gcode_parse("N10 G1 X1", &g) == GC_BAD);
    CHECK(gcode_parse("G1.5 X1", &g) == GC_BAD);
    CHECK(gcode_parse("G1 G2", &g) == GC_BAD);
    CHECK(gcode_parse("G1 X1 X2", &g) == GC_BAD);
    CHECK(gcode_parse("G1 X-", &g) == GC_BAD);
    CHECK(gcode_parse("G1 #", &g) == GC_BAD);
    CHECK(gcode_parse("hello", &g) == GC_BAD);
    CHECK(gcode_parse("G", &g) == GC_BAD);
    CHECK(gcode_parse("G1 X99999999999999999", &g) == GC_BAD);

    CHECK(gcode_realtime("M112", 4) == 112);
    CHECK(gcode_realtime("m410", 4) == 410);
    CHECK(gcode_realtime("  M112 ; stop", 13) == 112);
    CHECK(gcode_realtime("M112 (x)", 8) == 112);
    CHECK(gcode_realtime("M1120", 5) == 0);
    CHECK(gcode_realtime("M11", 3) == 0);
    CHECK(gcode_realtime("M112 X1", 7) == 0);
    CHECK(gcode_realtime("G112", 4) == 0);
    CHECK(gcode_realtime("M410S", 5) == 0);
}

void test_crc(void)
{
    CHECK(crc32_update(0, (const uint8_t *)"123456789", 9) == 0xCBF43926u);
    CHECK(crc32_update(0, (const uint8_t *)"", 0) == 0);
    // In pieces gives the same result as in one go.
    uint32_t c = crc32_update(0, (const uint8_t *)"1234", 4);
    c = crc32_update(c, (const uint8_t *)"56789", 5);
    CHECK(c == 0xCBF43926u);
}

void test_tmc(void)
{
    // Read frames widely printed in TMC2209 examples.
    uint8_t f[8];
    CHECK(tmc_frame_read(f, 0, 0x00) == 4 && f[3] == 0x48);
    CHECK(tmc_frame_read(f, 0, 0x06) == 4 && f[3] == 0x6F);
    CHECK(tmc_frame_write(f, 2, 0x10, 0x000A190Cu) == 8);
    CHECK(f[0] == 0x05 && f[1] == 2 && f[2] == 0x90 && f[3] == 0x00 && f[4] == 0x0A && f[5] == 0x19 &&
          f[6] == 0x0C && f[7] == tmc_crc8(f, 7));

    // Reply inside a stream with our own echo in front.
    uint8_t rx[12] = {0x05, 0x00, 0x02, 0x00, 0x05, 0xFF, 0x02, 0, 0, 0, 7, 0};
    rx[11] = tmc_crc8(&rx[4], 7);
    uint32_t v = 0;
    CHECK(tmc_find_reply(rx, sizeof rx, 0x02, &v) && v == 7);
    rx[11] ^= 1;
    CHECK(!tmc_find_reply(rx, sizeof rx, 0x02, &v));

    // Current formula from the datasheet gives the constants in tmc.c.
    double irms = 0.8, rs = 0.11, vfs = 0.18;
    double cs = 32.0 * 1.41421356 * irms * (rs + 0.02) / vfs - 1.0;
    CHECK((tmc_ihold_irun() >> 8 & 31u) == (uint32_t)cs);
    CHECK((tmc_ihold_irun() & 31u) == ((uint32_t)cs) / 2u);
    CHECK((tmc_ihold_irun() >> 16 & 15u) == 10u);
    CHECK((32.0 * 1.41421356 * irms * (rs + 0.02) / 0.325 - 1.0) < 16.0); // why VSENSE=1

    uint32_t chop = tmc_chopconf();
    CHECK((chop & 15u) == 3u);        // toff
    CHECK((chop >> 4 & 7u) == 0u);    // hstrt
    CHECK((chop >> 7 & 15u) == 2u);   // hend
    CHECK((chop >> 15 & 3u) == 1u);   // tbl
    CHECK((chop >> 17 & 1u) == 1u);   // vsense
    CHECK((chop >> 24 & 15u) == 4u);  // 1/16
    CHECK((chop >> 28 & 1u) == 1u);   // interpolate
    CHECK((tmc_gconf(false) & 4u) == 0u); // StealthChop
    CHECK((tmc_gconf(true) & 4u) == 4u);  // SpreadCycle
    CHECK((tmc_gconf(false) & 0xC0u) == 0xC0u); // UART has the say

    uint8_t axis = 9;
    sim_reset();
    CHECK(tmc_configure_all(&axis));
    CHECK(sim.tmc_reg[0][0x6C] == chop && sim.tmc_reg[2][0x6C] == chop && sim.tmc_reg[1][0x6C] == chop);
    CHECK(sim.tmc_reg[3][0x6C] == 0); // address 3 belongs to no axis here

    sim.tmc_dead = true;
    CHECK(!tmc_configure_all(&axis) && axis == 0);
    sim_cmd("G0 X1");
    CHECK(sim_out_has("Error:Driver not responding: X"));
    CHECK(!sim.motors);
    CHECK(sim_ok_count() == 1);
    sim_cmd("M122");
    CHECK(sim_out_has("X: no response"));
    sim.tmc_dead = false;
    sim_cmd("M122");
    CHECK(sim_out_has("X: addr=0") && sim_out_has("Y: addr=2") && sim_out_has("Z: addr=1"));
    sim_cmd("G0 X1");
    CHECK(sim_out_has("ok P") && sim.motors);
}
