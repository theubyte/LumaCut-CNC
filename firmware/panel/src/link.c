// Link to the Pi: JSON lines over the ESP32-S3's own USB (USB-Serial/JTAG).
// Pi -> panel: {"t":"st"|"res"|"jobs"|"mats"|"events"|"sys"} lines, and {"t":"img","len":n} followed by n bytes JPEG.

#include "link.h"

#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "jpeg_decoder.h"
#include "lvgl_port.h"
#include "ui.h"
#include "version.h"

static const char *TAG = "link";

#define LINK_LINE_MAX    8192    // panel.LINE_LIMIT stays below this
#define IMG_MAX     (512 * 1024)
#define CAM_W       640
#define CAM_H       480

static SemaphoreHandle_t tx_lock;
static int next_id = 1;
static uint8_t *jpeg;                  // incoming JPEG (PSRAM)
static uint16_t *frames[2];            // decoded frames, used alternately (PSRAM)
static int frame_index;

static void send_text(const char *text)
{
    xSemaphoreTake(tx_lock, portMAX_DELAY);
    size_t len = strlen(text);
    // short timeout: without the Pi on the other end nothing is read
    usb_serial_jtag_write_bytes(text, len, pdMS_TO_TICKS(50));
    usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(50));
    xSemaphoreGive(tx_lock);
}

static void send_json(cJSON *msg)
{
    char *text = cJSON_PrintUnformatted(msg);
    if (text) {
        send_text(text);
        cJSON_free(text);
    }
    cJSON_Delete(msg);
}

int link_act(const char *op, ...)
{
    cJSON *msg = cJSON_CreateObject();
    int id = next_id++;
    cJSON_AddStringToObject(msg, "t", "act");
    cJSON_AddNumberToObject(msg, "id", id);
    cJSON_AddStringToObject(msg, "op", op);
    va_list ap;
    va_start(ap, op);
    for (const char *key = va_arg(ap, const char *); key; key = va_arg(ap, const char *)) {
        const char *value = va_arg(ap, const char *);
        cJSON_AddStringToObject(msg, key, value ? value : "");
    }
    va_end(ap);
    send_json(msg);
    return id;
}

void link_request(const char *kind)
{
    char text[32];
    snprintf(text, sizeof(text), "{\"t\":\"%s\"}", kind);
    send_text(text);
}

static void show_image(int len)
{
    uint16_t *out = frames[frame_index];
    esp_jpeg_image_cfg_t cfg = {
        .indata = jpeg,
        .indata_size = len,
        .outbuf = (uint8_t *)out,
        .outbuf_size = CAM_W * CAM_H * 2,
        .out_format = JPEG_IMAGE_FORMAT_RGB565,
        .out_scale = JPEG_IMAGE_SCALE_0,
        .flags = {.swap_color_bytes = 0},
    };
    esp_jpeg_image_output_t info;
    if (esp_jpeg_decode(&cfg, &info) != ESP_OK || info.width > CAM_W || info.height > CAM_H) {
        ESP_LOGW(TAG, "JPEG not decoded (%d bytes)", len);
        return;
    }
    if (lvgl_port_lock(-1)) {
        ui_on_image(out, info.width, info.height);
        lvgl_port_unlock();
    }
    frame_index ^= 1;   // the screen keeps showing this frame while the next one is decoded
}

static void handle_line(char *line)
{
    cJSON *msg = cJSON_Parse(line);
    if (!msg) {
        return;
    }
    const char *t = cJSON_GetStringValue(cJSON_GetObjectItem(msg, "t"));
    if (t && lvgl_port_lock(-1)) {
        if (!strcmp(t, "st")) {
            ui_on_status(msg);
        } else if (!strcmp(t, "res")) {
            ui_on_result(msg);
        } else if (!strcmp(t, "jobs")) {
            ui_on_jobs(msg);
        } else if (!strcmp(t, "mats")) {
            ui_on_materials(msg);
        } else if (!strcmp(t, "events")) {
            ui_on_events(msg);
        } else if (!strcmp(t, "sys")) {
            ui_on_system(msg);
        }
        lvgl_port_unlock();
    }
    cJSON_Delete(msg);
}

static void rx_task(void *arg)
{
    static char line[LINK_LINE_MAX];
    static uint8_t buf[1024];
    size_t used = 0;
    int img_len = 0, img_got = 0;
    for (;;) {
        int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) {
            if (img_len) {                          // binary JPEG after an "img" header
                int take = n - i;
                if (take > img_len - img_got) {
                    take = img_len - img_got;
                }
                memcpy(jpeg + img_got, buf + i, take);
                img_got += take;
                i += take - 1;
                if (img_got == img_len) {
                    show_image(img_len);
                    img_len = 0;
                }
                continue;
            }
            char c = buf[i];
            if (c != '\n') {
                if (used < LINK_LINE_MAX - 1) {
                    line[used++] = c;
                } else {
                    used = 0;                       // overlong line: drop it
                }
                continue;
            }
            line[used] = 0;
            used = 0;
            if (strncmp(line, "{\"t\":\"img\"", 10) == 0) {
                cJSON *hdr = cJSON_Parse(line);
                int len = hdr ? (int)cJSON_GetNumberValue(cJSON_GetObjectItem(hdr, "len")) : 0;
                cJSON_Delete(hdr);
                if (len > 0 && len <= IMG_MAX) {
                    img_len = len;
                    img_got = 0;
                }
                continue;
            }
            handle_line(line);
        }
    }
}

static void ping_task(void *arg)
{
    send_text("{\"t\":\"hello\",\"v\":\"" PANEL_VERSION "\"}");
    for (;;) {
        bool cam = false;
        if (lvgl_port_lock(-1)) {
            cam = ui_camera_wanted();
            lvgl_port_unlock();
        }
        // the version in every ping: the Pi may start after the hello
        send_text(cam ? "{\"t\":\"ping\",\"cam\":1,\"v\":\"" PANEL_VERSION "\"}"
                      : "{\"t\":\"ping\",\"cam\":0,\"v\":\"" PANEL_VERSION "\"}");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

void link_start(void)
{
    tx_lock = xSemaphoreCreateMutex();
    jpeg = heap_caps_malloc(IMG_MAX, MALLOC_CAP_SPIRAM);
    frames[0] = heap_caps_malloc(CAM_W * CAM_H * 2, MALLOC_CAP_SPIRAM);
    frames[1] = heap_caps_malloc(CAM_W * CAM_H * 2, MALLOC_CAP_SPIRAM);
    usb_serial_jtag_driver_config_t conf = {.rx_buffer_size = 16384, .tx_buffer_size = 4096};
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&conf));
    xTaskCreatePinnedToCore(rx_task, "link_rx", 8192, NULL, 4, NULL, 0);
    xTaskCreatePinnedToCore(ping_task, "link_ping", 4096, NULL, 3, NULL, 0);
}
