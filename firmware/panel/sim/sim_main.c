// PC preview of the panel UI: renders the screens with sample data into raw
// RGB565 files (sim/out/*.raw, converted by sim/topng.py). No hardware, no Pi.
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>

#include "../src/ui.c"     // one translation unit: the preview reaches the static widgets

static lv_color_t fb[800 * 480], draw[800 * 480];
static int64_t now_us = 1000000;

int64_t esp_timer_get_time(void) { return now_us; }
int link_act(const char *op, ...) { printf("act %s\n", op); return 1; }
void link_request(const char *kind) { printf("request %s\n", kind); }
void board_backlight(bool on) { printf("backlight %d\n", on); }

static void flush(lv_disp_drv_t *d, const lv_area_t *a, lv_color_t *c)
{
    for (int y = a->y1; y <= a->y2; y++)
        for (int x = a->x1; x <= a->x2; x++)
            fb[y * 800 + x] = *c++;
    lv_disp_flush_ready(d);
}

static void render(const char *name)
{
    for (int i = 0; i < 5; i++) { lv_tick_inc(5); lv_timer_handler(); }
    lv_obj_invalidate(lv_scr_act());
    lv_obj_invalidate(lv_layer_top());
    lv_refr_now(NULL);
    char path[128];
    snprintf(path, sizeof(path), "out/%s.raw", name);
    FILE *f = fopen(path, "wb");
    fwrite(fb, 2, 800 * 480, f);
    fclose(f);
}

static void feed(const char *json, void (*fn)(const cJSON *))
{
    cJSON *m = cJSON_Parse(json);
    fn(m);
    cJSON_Delete(m);
}

static uint16_t img[640 * 480];

int main(void)
{
    lv_init();
    static lv_disp_draw_buf_t db;
    lv_disp_draw_buf_init(&db, draw, NULL, 800 * 480);
    static lv_disp_drv_t drv;
    lv_disp_drv_init(&drv);
    drv.hor_res = 800; drv.ver_res = 480; drv.flush_cb = flush; drv.draw_buf = &db;
    lv_disp_drv_register(&drv);
    ui_init();

    feed("{\"t\":\"st\",\"time\":\"14:32\",\"conn\":true,\"owner\":\"job\",\"homed\":true,\"latched\":false,"
         "\"fault\":\"\",\"armed\":true,\"supply\":true,\"exhaust\":true,\"lights\":true,\"pos\":[213.4,148.05,7.0],"
         "\"act\":\"job\",\"clear\":false,\"valid\":true,\"placed\":\"einladung_v3.gcode\",\"job\":{\"file\":"
         "\"einladung_v3.gcode\",\"state\":\"running\",\"phase\":\"running\",\"line\":4812,\"total\":7760,"
         "\"error\":\"\",\"probe\":[10,10]},\"queue\":\"idle\",\"frame\":\"idle\",\"elapsed\":761,\"remain\":468,"
         "\"power\":71,\"feed\":1800,\"mat\":\"Pappelsperrholz\",\"mat_mm\":3,\"bright\":60,\"dim\":true,"
         "\"soff\":15,\"ev\":3,\"evp\":0}", ui_on_status);
    render("1_status");

    feed("{\"t\":\"st\",\"time\":\"14:40\",\"conn\":true,\"owner\":\"Frei\",\"homed\":true,\"latched\":false,"
         "\"armed\":false,\"supply\":false,\"exhaust\":false,\"lights\":true,\"pos\":[213.4,148.05,7.0],"
         "\"act\":\"idle\",\"clear\":false,\"valid\":true,\"placed\":\"\",\"job\":{\"file\":\"einladung_v3.gcode\","
         "\"state\":\"complete\",\"phase\":\"\",\"line\":7760,\"total\":7760,\"error\":\"\",\"probe\":null},"
         "\"queue\":\"idle\",\"frame\":\"idle\",\"elapsed\":null,\"remain\":null,\"power\":null,\"feed\":null,"
         "\"mat\":\"Pappelsperrholz\",\"mat_mm\":3,\"bright\":60,\"dim\":true,\"soff\":15,\"ev\":3,\"evp\":0}", ui_on_status);
    show_screen(SCR_MOVE);
    render("2_bewegen");

    for (int y = 0; y < 480; y++)
        for (int x = 0; x < 640; x++) {
            int wood = x > 170 && x < 470 && y > 110 && y < 360;
            int r = wood ? 220 : 60 + ((x / 14 + y / 24) % 2) * 12, g = wood ? 190 : r, b = wood ? 140 : r + 6;
            img[y * 640 + x] = (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
        }
    show_screen(SCR_CAMERA);
    ui_on_image(img, 640, 480);
    render("3_kamera");

    show_screen(SCR_JOBS);
    feed("{\"t\":\"jobs\",\"files\":[{\"name\":\"einladung_v3.gcode\",\"kb\":412},{\"name\":\"testmuster_pappel.gcode\","
         "\"kb\":96},{\"name\":\"schild_werkstatt.gcode\",\"kb\":1380},{\"name\":\"untersetzer_rund.gcode\",\"kb\":58}]}",
         ui_on_jobs);
    lv_event_send(lv_obj_get_child(job_list, 0), LV_EVENT_CLICKED, NULL);
    const char *idle = "{\"t\":\"st\",\"time\":\"14:41\",\"conn\":true,\"owner\":\"Frei\",\"homed\":true,\"act\":\"idle\",\"valid\":true,"
         "\"lights\":true,\"pos\":[0,0,20],\"job\":{\"state\":\"idle\"},\"queue\":\"idle\",\"mat\":\"Pappelsperrholz\",\"mat_mm\":3,"
         "\"bright\":60,\"dim\":true,\"soff\":15,\"ev\":5,\"evp\":4,\"exhaust\":true}";
    feed(idle, ui_on_status);
    render("4_auftrag");

    lv_event_send(btn_start, LV_EVENT_CLICKED, NULL);
    render("5_freigabe");
    popup_close();

    lv_event_send(key_mat, LV_EVENT_CLICKED, NULL);
    feed("{\"t\":\"mats\",\"items\":[{\"name\":\"Acryl schwarz\",\"mm\":3,\"proc\":\"Schneiden\",\"start\":true},"
         "{\"name\":\"Karton\",\"mm\":1,\"proc\":\"Schneiden\",\"start\":true},{\"name\":\"Leder\",\"mm\":2,\"proc\":\"Gravieren\",\"start\":false},"
         "{\"name\":\"MDF\",\"mm\":3,\"proc\":\"Schneiden\",\"start\":true},{\"name\":\"Pappelsperrholz\",\"mm\":3,\"proc\":\"Schneiden, Gravieren\",\"start\":false},"
         "{\"name\":\"Schiefer\",\"mm\":5,\"proc\":\"Gravieren\",\"start\":true}]}", ui_on_materials);
    render("7_material");
    lv_event_send(lv_obj_get_child(mat_view, 1), LV_EVENT_CLICKED, NULL);

    show_screen(SCR_SYSTEM);
    render("8_system");

    lv_event_send(tab_btn[TAB_EVENTS], LV_EVENT_CLICKED, NULL);
    feed("{\"t\":\"events\",\"items\":["
         "{\"time\":\"14:40\",\"level\":\"ok\",\"text\":\"Fertig: einladung_v3.gcode\"},"
         "{\"time\":\"14:02\",\"level\":\"info\",\"text\":\"Gestartet: einladung_v3.gcode\"},"
         "{\"time\":\"13:58\",\"level\":\"warn\",\"text\":\"Marlin muss zuerst referenziert werden\"},"
         "{\"time\":\"13:40\",\"level\":\"err\",\"text\":\"schild.gcode: Der Taster hat bei X120 Y80 kein Material gefunden – Material unter das Motiv legen oder den Tasterversatz prüfen, dann neu starten.\"},"
         "{\"time\":\"13:12\",\"level\":\"ok\",\"text\":\"Notstopp quittiert\"}]}", ui_on_events);
    render("9_ereignisse");

    lv_event_send(tab_btn[TAB_INFO], LV_EVENT_CLICKED, NULL);
    feed("{\"t\":\"sys\",\"ip\":\"192.168.2.89\",\"http\":\"http://192.168.2.89:8080\",\"host\":\"lumacut\",\"wifi\":\"Werkstatt\",\"signal\":71,"
         "\"pi\":\"978e360 2026-11-05\",\"skr\":\"20261104-1\",\"skr_conn\":true,\"skr_new\":\"\",\"panel_new\":\"1.4\",\"panel_state\":\"idle\","
         "\"panel_msg\":\"\",\"auto\":true,\"serial_err\":0}", ui_on_system);
    render("10_info");

    feed("{\"t\":\"st\",\"time\":\"14:42\",\"conn\":true,\"owner\":\"Frei\",\"latched\":true,\"fault\":"
         "\"Marlin M112 ausgelöst – physischen Not-Aus prüfen\",\"act\":\"idle\",\"job\":{\"state\":\"aborted\"}}",
         ui_on_status);
    render("6_notstopp");

    // walk through the screen-off rule: dark only when idle, a job wakes it, the waking touch does nothing else
    feed(idle, ui_on_status);
    last_status_us = esp_timer_get_time();
    lv_tick_inc(16 * 60000);
    lv_timer_handler();
    printf("dark after 16 min idle: %d (expected 1), camera wanted: %d\n", dark, ui_camera_wanted());
    lv_point_t touch = {746, 118};       // where STOPP is: while dark the touch lands on the catcher
    printf("touch goes to the catcher: %d (expected 1)\n", lv_indev_search_obj(lv_layer_sys(), &touch) == dark_catch);
    lv_event_send(dark_catch, LV_EVENT_PRESSED, NULL);
    printf("dark after the touch: %d (expected 0)\n", dark);
    lv_event_send(dark_catch, LV_EVENT_RELEASED, NULL);
    printf("catcher away after release: %d (expected 1)\n", lv_obj_has_flag(dark_catch, LV_OBJ_FLAG_HIDDEN));
    lv_tick_inc(16 * 60000);
    lv_timer_handler();
    printf("dark again: %d (expected 1)\n", dark);
    feed("{\"t\":\"st\",\"conn\":true,\"owner\":\"job\",\"act\":\"job\",\"job\":{\"state\":\"running\"},\"soff\":15}", ui_on_status);
    printf("dark with a job running: %d (expected 0)\n", dark);

    // a go shown before the machine got busy is taken back
    feed(idle, ui_on_status);
    lv_event_send(btn_start, LV_EVENT_CLICKED, NULL);
    printf("go popup open: %d (expected 1)\n", popup != NULL);
    feed("{\"t\":\"st\",\"conn\":true,\"owner\":\"job\",\"act\":\"job\",\"job\":{\"state\":\"running\"},\"soff\":15}", ui_on_status);
    printf("go popup after another device started a job: %d (expected 0)\n", popup != NULL);
    return 0;
}
