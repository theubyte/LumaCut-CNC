#include "tmc.h"
#include "config.h"
#include "hal.h"
#include "out.h"

// Addresses: Marlin 2.1.2.9 pins_BTT_SKR_MINI_E3_V2_0.h (included by
// pins_BTT_SKR_MINI_MZ_V1_0.h): X=0, Y=2, Z=1.
static const uint8_t ADDR[AXES] = {0, 2, 1};
static const char AXIS_NAME[AXES] = {'X', 'Y', 'Z'};

// Registers from the TMC2209 datasheet.
enum {
    REG_GCONF = 0x00,
    REG_GSTAT = 0x01,
    REG_IFCNT = 0x02,
    REG_NODECONF = 0x03,
    REG_IHOLD_IRUN = 0x10,
    REG_TPOWERDOWN = 0x11,
    REG_CHOPCONF = 0x6C,
    REG_DRV_STATUS = 0x6F,
    REG_PWMCONF = 0x70
};

// Current: X/Y/Z_CURRENT 800 mA, X/Y/Z_RSENSE 0.11 ohm (Configurations
// release-2.1.2.9, AnyCubic/Mega Zero/BigTreeTech SKR Mini MZ V1.0,
// Configuration_adv.h). Datasheet: CS = 32*sqrt2*I*(Rs+0.02)/Vfs - 1. With
// Vfs 0.325 V CS is 13, below the useful range 16..31, so VSENSE=1 (0.180 V): 25.
#define CS_RUN 25u
#define VSENSE 1u
// HOLD_MULTIPLIER 0.5 (same file), rounded down like the old firmware.
#define CS_HOLD 12u
// Same file: X/Y/Z_MICROSTEPS 16 (MRES=4), INTERPOLATE true.
#define MRES_16 4u
#define INTPOL 1u
// Same file: CHOPPER_TIMING CHOPPER_DEFAULT_12V; Marlin 2.1.2.9 core/drivers.h
// gives { toff 3, hend -1, hstrt 1 }. Marlin module/stepper/trinamic.cpp maps
// this to HEND = hend+3, HSTRT = hstrt-1, TBL = 1. The old firmware ran these.
#define TOFF 3u
#define HEND 2u
#define HSTRT 0u
#define TBL 1u
// Marlin 2.1.2.9 module/stepper/trinamic.cpp: tmc_init for TMC2209.
#define IHOLDDELAY 10u
#define TPOWERDOWN 128u
#define PWM_OFS 36u
#define PWM_GRAD 14u
#define PWM_FREQ 1u
#define PWM_REG 8u
#define PWM_LIM 12u
// Three drivers share the bus. SENDDELAY 0/1 (8 bit times) is not for multi-node
// use; 2 means 3*8 bit times (TMC2209 datasheet, NODECONF; Klipper uses 2 as well).
#define SENDDELAY 2u
#define WRITES_IN_SETUP 7u

uint8_t tmc_crc8(const uint8_t *data, size_t len)
{
    uint8_t crc = 0;
    for (size_t i = 0; i < len; i++) {
        uint8_t byte = data[i];
        for (int bit = 0; bit < 8; bit++) {
            bool mix = ((crc >> 7) ^ (byte & 1u)) != 0;
            crc = (uint8_t)(crc << 1);
            if (mix) crc ^= 0x07;
            byte >>= 1;
        }
    }
    return crc;
}

size_t tmc_frame_write(uint8_t *buf, uint8_t addr, uint8_t reg, uint32_t value)
{
    buf[0] = 0x05;
    buf[1] = addr;
    buf[2] = (uint8_t)(reg | 0x80u);
    buf[3] = (uint8_t)(value >> 24);
    buf[4] = (uint8_t)(value >> 16);
    buf[5] = (uint8_t)(value >> 8);
    buf[6] = (uint8_t)value;
    buf[7] = tmc_crc8(buf, 7);
    return 8;
}

size_t tmc_frame_read(uint8_t *buf, uint8_t addr, uint8_t reg)
{
    buf[0] = 0x05;
    buf[1] = addr;
    buf[2] = reg;
    buf[3] = tmc_crc8(buf, 3);
    return 4;
}

bool tmc_find_reply(const uint8_t *rx, size_t n, uint8_t reg, uint32_t *value)
{
    for (size_t i = 0; i + 8 <= n; i++) {
        const uint8_t *f = &rx[i];
        if (f[0] == 0x05 && f[1] == 0xFF && f[2] == reg && tmc_crc8(f, 7) == f[7]) {
            *value = ((uint32_t)f[3] << 24) | ((uint32_t)f[4] << 16) | ((uint32_t)f[5] << 8) | f[6];
            return true;
        }
    }
    return false;
}

uint32_t tmc_gconf(bool spreadcycle)
{
    // pdn_disable and mstep_reg_select: UART owns the pins' functions.
    return (1u << 6) | (1u << 7) | (spreadcycle ? (1u << 2) : 0u);
}

uint32_t tmc_chopconf(void)
{
    return TOFF | (HSTRT << 4) | (HEND << 7) | (TBL << 15) | (VSENSE << 17) | (MRES_16 << 24) |
           (INTPOL << 28);
}

uint32_t tmc_ihold_irun(void) { return CS_HOLD | (CS_RUN << 8) | (IHOLDDELAY << 16); }

uint32_t tmc_pwmconf(void)
{
    // pwm_autoscale and pwm_autograd on.
    return PWM_OFS | (PWM_GRAD << 8) | (PWM_FREQ << 16) | (1u << 18) | (1u << 19) |
           (PWM_REG << 24) | ((uint32_t)PWM_LIM << 28);
}

static void reg_write(uint8_t axis, uint8_t reg, uint32_t value)
{
    uint8_t f[8];
    size_t n = tmc_frame_write(f, ADDR[axis], reg, value);
    hal_tmc_send(f, n);
}

static bool reg_read(uint8_t axis, uint8_t reg, uint32_t *value)
{
    uint8_t f[4], rx[8]; // hal_tmc_send already took our echo off the wire
    size_t n = tmc_frame_read(f, ADDR[axis], reg);
    for (int attempt = 0; attempt < 4; attempt++) {
        hal_tmc_bus_lock(true);
        hal_tmc_send(f, n);
        size_t got = hal_tmc_recv(rx, sizeof rx, 4000);
        hal_tmc_bus_lock(false);
        if (tmc_find_reply(rx, got, reg, value)) return true;
    }
    return false;
}

// Three nodes share the wire, and SENDDELAY 0 from reset is not allowed then:
// reads fail at random until every node has it. Writes need no answer.
static void bus_setup(void)
{
    for (uint8_t a = 0; a < AXES; a++) reg_write(a, REG_NODECONF, SENDDELAY << 8);
}

bool tmc_configure_all(uint8_t *failed_axis)
{
    bus_setup();
    for (uint8_t a = 0; a < AXES; a++) {
        uint32_t before, after, chop;
        *failed_axis = a;
        if (!reg_read(a, REG_IFCNT, &before)) return false;
        // Stealth on all axes: STEALTHCHOP_XY and STEALTHCHOP_Z in the same
        // example, HYBRID_THRESHOLD off.
        reg_write(a, REG_NODECONF, SENDDELAY << 8);
        reg_write(a, REG_GCONF, tmc_gconf(false));
        reg_write(a, REG_CHOPCONF, tmc_chopconf());
        reg_write(a, REG_IHOLD_IRUN, tmc_ihold_irun());
        reg_write(a, REG_TPOWERDOWN, TPOWERDOWN);
        reg_write(a, REG_PWMCONF, tmc_pwmconf());
        reg_write(a, REG_GSTAT, 0x7u);
        if (!reg_read(a, REG_IFCNT, &after)) return false;
        if (((after - before) & 0xFFu) != WRITES_IN_SETUP) return false;
        if (!reg_read(a, REG_CHOPCONF, &chop) || chop != tmc_chopconf()) return false;
    }
    return true;
}

tmc_health_t tmc_check_reset(uint8_t *axis)
{
    for (uint8_t a = 0; a < AXES; a++) {
        uint32_t gstat;
        *axis = a;
        // This verdict drops the reference: one lost read is not enough for it.
        if (!reg_read(a, REG_GSTAT, &gstat) && !reg_read(a, REG_GSTAT, &gstat) &&
            !reg_read(a, REG_GSTAT, &gstat)) {
            return TMC_NO_ANSWER;
        }
        if (gstat & 1u) return TMC_WAS_RESET;
    }
    return TMC_OK;
}

void tmc_spreadcycle(uint8_t axes, bool on)
{
    for (uint8_t a = 0; a < AXES; a++) {
        if (axes & (1u << a)) reg_write(a, REG_GCONF, tmc_gconf(on));
    }
}

void tmc_report(void)
{
    bus_setup();
    for (uint8_t a = 0; a < AXES; a++) {
        char head[3] = {AXIS_NAME[a], ':', 0};
        uint32_t gconf, gstat, chop, drv;
        out_str(head);
        if (!reg_read(a, REG_GCONF, &gconf) || !reg_read(a, REG_GSTAT, &gstat) ||
            !reg_read(a, REG_CHOPCONF, &chop) || !reg_read(a, REG_DRV_STATUS, &drv)) {
            out_str(" no response\n");
            continue;
        }
        out_str(" addr=");
        out_u32(ADDR[a]);
        out_str(" irun=");
        out_u32(CS_RUN);
        out_str(" ihold=");
        out_u32(CS_HOLD);
        out_str(" cs_actual=");
        out_u32((drv >> 16) & 31u);
        out_str(" vsense=");
        out_u32((chop >> 17) & 1u);
        out_str(" microsteps=");
        out_u32(256u >> ((chop >> 24) & 15u));
        out_str(" stealth=");
        out_u32(((gconf >> 2) & 1u) ? 0u : 1u);
        out_str(" gstat=");
        out_hex(gstat);
        out_str(" drv_status=");
        out_hex(drv);
        out_str(" ot=");
        out_u32((drv >> 1) & 1u);
        out_str(" otpw=");
        out_u32(drv & 1u);
        out_str(" short=");
        out_u32((drv >> 2) & 15u);
        out_str(" open=");
        out_u32((drv >> 6) & 3u);
        out_nl();
    }
}
