#include "update.h"
#include "../version.h"
#include "config.h"
#include "crc32.h"
#include "hal.h"
#include "out.h"
#include "rxlines.h"
#include <string.h>

typedef enum { UP_IDLE, UP_RX, UP_VERIFY, UP_FLUSH } up_state_t;

#define VERIFY_SLICE 8192u
#define FLUSH_MIN_MS 50u
#define FLUSH_MAX_MS 500u

static up_state_t state;
static uint32_t total, expected_crc, offset, fill, verified, crc_now, last_ms, flush_start;
static uint8_t chunk[UPDATE_CHUNK];

void cmd_reply_ok(void); // provided by the command layer

bool update_active(void) { return state != UP_IDLE; }

bool update_begin(uint32_t bytes, uint32_t crc, const char **error)
{
    if (bytes == 0 || bytes > UPDATE_MAX_BYTES) {
        *error = "Error:Update size";
        return false;
    }
    if (hal_flash_kb() < UPDATE_MIN_FLASH_KB) {
        *error = "Error:Update flash size";
        return false;
    }
    total = bytes;
    expected_crc = crc;
    offset = fill = verified = crc_now = 0;
    last_ms = hal_ms();
    state = UP_RX;
    rx_set_raw(true);
    out_str("ok READY ");
    out_u32(UPDATE_CHUNK);
    out_nl();
    return true;
}

static void fail(const char *text)
{
    state = UP_IDLE;
    rx_set_raw(false);
    out_str(text);
    out_nl();
    cmd_reply_ok();
}

void update_cancel(void)
{
    if (state == UP_IDLE) return;
    state = UP_IDLE;
    rx_set_raw(false);
}

bool update_image_valid(const uint8_t *image, uint32_t bytes)
{
    if (bytes < 8u) return false;
    uint32_t sp, reset;
    memcpy(&sp, image, 4);
    memcpy(&reset, image + 4, 4);
    if (sp < 0x20000000u || sp > 0x20010000u) return false;
    if (!(reset & 1u) || reset < APP_ADDR || reset >= APP_ADDR + bytes) return false;
    size_t id_len = strlen(LUMACUT_ID);
    for (uint32_t i = 0; i + id_len <= bytes; i++) {
        if (image[i] == LUMACUT_ID[0] && memcmp(image + i, LUMACUT_ID, id_len) == 0) return true;
    }
    return false;
}

static void receive(uint32_t now_ms)
{
    uint32_t want = total - offset;
    if (want > UPDATE_CHUNK) want = UPDATE_CHUNK;
    uint32_t n = (uint32_t)rx_raw_read(chunk + fill, want - fill);
    if (n) {
        fill += n;
        last_ms = now_ms;
    } else if (now_ms - last_ms > UPDATE_TIMEOUT_MS) {
        fail("Error:Update timeout");
        return;
    }
    if (fill < want) return;

    for (uint32_t page = offset / FLASH_PAGE; page <= (offset + want - 1u) / FLASH_PAGE; page++) {
        uint32_t page_addr = page * FLASH_PAGE;
        if (page_addr >= offset && !hal_stage_erase_page(page_addr)) {
            fail("Error:Update flash erase");
            return;
        }
    }
    if (!hal_stage_write(offset, chunk, want)) {
        fail("Error:Update flash write");
        return;
    }
    offset += want;
    fill = 0;
    last_ms = now_ms;
    out_str("ok ");
    out_u32(offset);
    out_nl();
    if (offset == total) state = UP_VERIFY;
}

void update_poll(uint32_t now_ms)
{
    switch (state) {
    case UP_IDLE:
        break;
    case UP_RX:
        receive(now_ms);
        break;
    case UP_VERIFY: {
        uint32_t n = total - verified;
        if (n > VERIFY_SLICE) n = VERIFY_SLICE;
        crc_now = crc32_update(crc_now, hal_stage_data() + verified, n);
        verified += n;
        if (verified < total) break;
        if (crc_now != expected_crc) {
            fail("Error:Update CRC");
        } else if (!update_image_valid(hal_stage_data(), total)) {
            fail("Error:Update image");
        } else {
            out_str("ok DONE\n");
            flush_start = now_ms;
            state = UP_FLUSH;
        }
        break;
    }
    case UP_FLUSH: {
        uint32_t waited = now_ms - flush_start;
        if ((hal_usb_tx_idle() && waited >= FLUSH_MIN_MS) || waited >= FLUSH_MAX_MS) {
            state = UP_IDLE;
            hal_selfcopy_and_reset(total);
        }
        break;
    }
    }
}
