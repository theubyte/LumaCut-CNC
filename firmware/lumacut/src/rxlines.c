#include "rxlines.h"
#include "gcode.h"
#include "hal.h"

typedef struct {
    char text[RX_LINE_MAX + 1];
    bool too_long;
} slot_t;

static slot_t slots[RX_SLOTS];
static volatile uint32_t wr_seq, rd_seq, discard_seq;
static char cur[RX_LINE_MAX + 1];
static uint16_t cur_len;
static bool cur_long;
static volatile uint32_t last_line_ms;

static volatile bool raw_mode;
static uint8_t raw[RX_RAW_SIZE];
static volatile uint32_t raw_wr, raw_rd;

void rx_init(void)
{
    wr_seq = rd_seq = discard_seq = 0;
    cur_len = 0;
    cur_long = false;
    raw_mode = false;
    raw_wr = raw_rd = 0;
    last_line_ms = hal_ms();
}

static void end_of_line(void)
{
    uint16_t len = cur_len;
    bool too_long = cur_long;
    cur_len = 0;
    cur_long = false;
    if (len == 0) return; // blank lines and the LF of CRLF get no reply
    cur[len] = 0;
    last_line_ms = hal_ms();
    if (!too_long) {
        int rt = gcode_realtime(cur, len);
        if (rt == 112) {
            cmd_rt_m112();
            return;
        }
        if (rt == 410) {
            cmd_rt_m410();
            return;
        }
    }
    slot_t *s = &slots[wr_seq % RX_SLOTS];
    for (uint16_t i = 0; i <= len; i++) s->text[i] = cur[i];
    s->too_long = too_long;
    wr_seq = wr_seq + 1;
}

void rx_feed(const uint8_t *data, size_t len)
{
    if (raw_mode) {
        for (size_t i = 0; i < len; i++) {
            raw[raw_wr % RX_RAW_SIZE] = data[i];
            raw_wr = raw_wr + 1;
        }
        return;
    }
    for (size_t i = 0; i < len; i++) {
        char c = (char)data[i];
        if (c == '\n' || c == '\r') {
            end_of_line();
        } else if (cur_len < RX_LINE_MAX) {
            cur[cur_len++] = c;
        } else {
            cur_long = true;
        }
    }
}

bool rx_can_take_packet(void)
{
    if (raw_mode) return RX_RAW_SIZE - (raw_wr - raw_rd) >= 64;
    return RX_SLOTS - (wr_seq - rd_seq) > RX_RESERVE_LINES;
}

const char *rx_peek(bool *too_long, bool *discard)
{
    if (rd_seq == wr_seq) return 0;
    const slot_t *s = &slots[rd_seq % RX_SLOTS];
    *too_long = s->too_long;
    *discard = (int32_t)(rd_seq - discard_seq) < 0;
    return s->text;
}

void rx_pop(void)
{
    rd_seq = rd_seq + 1;
    hal_usb_rx_resume();
}

uint8_t rx_free_lines(void)
{
    uint32_t used = wr_seq - rd_seq;
    if (used >= RX_REPORTED_LINES) return 0;
    return (uint8_t)(RX_REPORTED_LINES - used);
}

uint32_t rx_last_line_ms(void) { return last_line_ms; }

void rx_mark_discard(void) { discard_seq = wr_seq; }

void rx_set_raw(bool on)
{
    raw_wr = raw_rd = 0;
    cur_len = 0;
    cur_long = false;
    raw_mode = on;
    hal_usb_rx_resume();
}

size_t rx_raw_read(uint8_t *dst, size_t max)
{
    size_t n = 0;
    while (n < max && raw_rd != raw_wr) {
        dst[n++] = raw[raw_rd % RX_RAW_SIZE];
        raw_rd = raw_rd + 1;
    }
    if (n) hal_usb_rx_resume();
    return n;
}
