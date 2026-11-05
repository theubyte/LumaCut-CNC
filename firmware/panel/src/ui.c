// LumaCut Bedienpanel: the five screens of the light design plus top bar,
// navigation, stop column, release popup and toasts. The panel only shows
// and asks; every action goes to the Pi (link_act), which checks it.
// Before every drive or laser job a popup asks for the go (ask_go). Single jog
// steps are the exception: the operator is at the keys and sees each one.

#include "ui.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

#include "board.h"
#include "esp_timer.h"
#include "link.h"
#include "lvgl.h"
#include "version.h"

LV_FONT_DECLARE(font_ui11)
LV_FONT_DECLARE(font_ui14)
LV_FONT_DECLARE(font_ui16)
LV_FONT_DECLARE(font_ui20)
LV_FONT_DECLARE(font_big56)
LV_FONT_DECLARE(font_mono16)
LV_FONT_DECLARE(font_mono26)
LV_FONT_DECLARE(font_icon20)
LV_FONT_DECLARE(font_icon26)

// FontAwesome 5 (font_icon*)
#define I_HOME     "\xEF\x80\x95"
#define I_PAUSE    "\xEF\x81\x8C"
#define I_PLAY     "\xEF\x81\x8B"
#define I_TIMES    "\xEF\x80\x8D"
#define I_CAMERA   "\xEF\x80\xB0"
#define I_UP       "\xEF\x81\xB7"
#define I_DOWN     "\xEF\x81\xB8"
#define I_LEFT     "\xEF\x81\x93"
#define I_RIGHT    "\xEF\x81\x94"
#define I_SYNC     "\xEF\x80\xA1"
#define I_ZOOM     "\xEF\x80\x8E"
#define I_FILE     "\xEF\x85\x9B"
#define I_GAUGE    "\xEF\x8F\xBD"
#define I_MOVE     "\xEF\x82\xB2"
#define I_LIGHT    "\xEF\x83\xAB"
#define I_WARN     "\xEF\x81\xB1"
#define I_PROBE    "\xEF\x80\x99"
#define I_FRAME    "\xEF\x81\xA5"
#define I_WIND     "\xEF\x9C\xAE"
#define I_PARK     "\xEF\x8F\x85"
#define I_COG      "\xEF\x80\x93"
#define I_LAYERS   "\xEF\x97\xBD"

#define C_BG       lv_color_hex(0xEEF0F3)
#define C_CARD     lv_color_hex(0xFFFFFF)
#define C_LINE     lv_color_hex(0xE3E6EA)
#define C_SOFT     lv_color_hex(0xF5F6F8)
#define C_INK      lv_color_hex(0x16191D)
#define C_MUTE     lv_color_hex(0x8A929B)
#define C_TEXT2    lv_color_hex(0x4C545D)
#define C_ACCENT   lv_color_hex(0xFF6A13)
#define C_ACCENT2  lv_color_hex(0xF35D05)
#define C_ACCSOFT  lv_color_hex(0xFFF1E8)
#define C_OK       lv_color_hex(0x1FBF6A)
#define C_INFO     lv_color_hex(0x1C9BF0)
#define C_STOP     lv_color_hex(0xE5261D)
#define C_OFF      lv_color_hex(0xC8CDD2)

#define NAME_MAX_BYTES 96          // job names; panel.py sends no longer ones

enum { SCR_STATUS, SCR_MOVE, SCR_CAMERA, SCR_JOBS, SCR_SYSTEM, SCR_COUNT };
enum { TAB_MACHINE, TAB_EVENTS, TAB_INFO, TAB_COUNT };

typedef struct {
    bool conn, homed, latched, armed, supply, exhaust, lights, clear, valid;
    char owner[16], act[12], fault[160], placed[NAME_MAX_BYTES], time[8], mat[84];
    char job_file[NAME_MAX_BYTES], job_state[12], job_phase[12], job_error[200], queue[10];
    int line, total, probe_done, probe_total, elapsed, remain, power, feed;
    int bright, dim, qn, ev, evp, soff;   // dim: 1 dims, 0 cannot, -1 not known yet
    float pos[3], mat_mm, fpow;
    bool has_pos;
} state_t;

static state_t st;
static int64_t last_status_us;
static int screen = SCR_STATUS;

static lv_style_t s_card, s_key, s_key_dark, s_key_pr, s_key_on, s_disabled, s_nav, s_nav_on, s_pill;
static lv_obj_t *screens[SCR_COUNT], *navs[SCR_COUNT];

// top bar
static lv_obj_t *pill_pi, *pill_skr, *pill_laser, *pill_air, *pill_light, *lbl_time;
// side column
static lv_obj_t *btn_pause, *btn_resume, *btn_abort;
// status screen
static lv_obj_t *lbl_title, *arc, *lbl_pct, *lbl_rest, *lbl_file, *lbl_info1, *lbl_info2;
static lv_obj_t *lbl_pos[3], *lbl_power, *bar_power, *lbl_feed, *bar_feed;
static lv_obj_t *chip_val[4], *chip_dot[4];
// move screen
static lv_obj_t *lbl_move_pos, *lbl_z, *lbl_move_hint, *step_btn[3], *key_home;
static lv_obj_t *move_keys[16];
static int n_move_keys;
static const char *steps[3] = {"0.1", "1", "10"};
static int step = 2;
// camera
static lv_obj_t *cam_img, *cam_hint, *cam_badge, *key_cam_frame, *key_cam_light, *key_cam_air;
static lv_img_dsc_t cam_dsc;
static bool cam_zoom;
static int64_t cam_last_us;
// jobs
static lv_obj_t *job_list, *lbl_sel, *lbl_sel_info, *btn_frame_job, *btn_start;
static char selected[NAME_MAX_BYTES];
static int selected_kb;
// material
static lv_obj_t *key_mat, *lbl_key_mat, *mat_view, *mat_list;
static char mat_names[40][84], mat_thick[40][16];
// system
static lv_obj_t *tab_btn[TAB_COUNT], *tabs[TAB_COUNT], *nav_dot;
static lv_obj_t *key_light, *key_air, *level_btn[5], *lbl_no_dim, *off_btn[5];
static lv_obj_t *event_list, *info_ip, *info_wifi, *info_host, *info_pi, *info_skr, *lbl_update, *key_panel_update;
static const int light_levels[5] = {10, 30, 60, 80, 100};
static const int off_minutes[5] = {0, 2, 5, 15, 30};      // same list as panel.SCREEN_OFF_CHOICES
static int sys_tab = TAB_MACHINE;
static int seen_problem, shown_events = -1;
// screen off
static lv_obj_t *dark_catch;
static bool dark;
static int64_t jog_wait_us;
// overlays
static lv_obj_t *toast, *toast_lbl, *offline, *latch_box, *lbl_latch;
static lv_timer_t *toast_timer;
static lv_obj_t *popup;
static bool popup_go;              // the question is a go: taken back when the machine stops being free
static bool go_clear;              // the go also said "the head stands clear"

/* ------------------------------------------------------------------ helpers */

static lv_obj_t *box(lv_obj_t *parent, int x, int y, int w, int h)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_style_all(o);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    lv_obj_clear_flag(o, LV_OBJ_FLAG_SCROLLABLE);
    return o;
}

static lv_obj_t *card(lv_obj_t *parent, int x, int y, int w, int h)
{
    lv_obj_t *o = box(parent, x, y, w, h);
    lv_obj_add_style(o, &s_card, 0);
    return o;
}

static lv_obj_t *label(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, int x, int y, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, color, 0);
    lv_obj_set_pos(l, x, y);
    lv_label_set_text(l, text);
    return l;
}

// small grey uppercase caption
static lv_obj_t *caption(lv_obj_t *parent, int x, int y, const char *text)
{
    lv_obj_t *l = label(parent, &font_ui11, C_MUTE, x, y, text);
    lv_obj_set_style_text_letter_space(l, 2, 0);
    return l;
}

static lv_obj_t *key(lv_obj_t *parent, int x, int y, int w, int h, bool dark,
                     const char *icon, const char *text, lv_event_cb_t cb, void *data)
{
    lv_obj_t *b = lv_btn_create(parent);
    lv_obj_remove_style_all(b);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, h);
    lv_obj_add_style(b, dark ? &s_key_dark : &s_key, 0);
    lv_obj_add_style(b, &s_key_on, LV_STATE_CHECKED);
    lv_obj_add_style(b, &s_key_pr, LV_STATE_PRESSED);
    lv_obj_add_style(b, &s_disabled, LV_STATE_DISABLED);
    lv_obj_set_flex_flow(b, h >= 70 && w < 160 ? LV_FLEX_FLOW_COLUMN : LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(b, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_gap(b, 6, 0);
    lv_color_t fg = dark ? lv_color_white() : C_INK;
    if (icon) {
        lv_obj_t *i = lv_label_create(b);
        lv_obj_set_style_text_font(i, &font_icon20, 0);
        lv_obj_set_style_text_color(i, fg, 0);
        lv_label_set_text(i, icon);
    }
    if (text) {
        lv_obj_t *t = lv_label_create(b);
        lv_obj_set_style_text_font(t, &font_ui14, 0);
        lv_obj_set_style_text_color(t, fg, 0);
        lv_label_set_text(t, text);
    }
    if (cb) {
        lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, data);
    }
    return b;
}

static void enable(lv_obj_t *o, bool on)
{
    if (on) {
        lv_obj_clear_state(o, LV_STATE_DISABLED);
    } else {
        lv_obj_add_state(o, LV_STATE_DISABLED);
    }
}

static void mark(lv_obj_t *o, bool on)
{
    if (on) {
        lv_obj_add_state(o, LV_STATE_CHECKED);
    } else {
        lv_obj_clear_state(o, LV_STATE_CHECKED);
    }
}

static void show(lv_obj_t *o, bool on)
{
    if (on) {
        lv_obj_clear_flag(o, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
    }
}

// a row of big buttons of which one is on; the track behind them comes from seg_track
static lv_obj_t *seg_track(lv_obj_t *parent, int x, int y, int w, int h)
{
    lv_obj_t *seg = box(parent, x, y, w, h);
    lv_obj_set_style_radius(seg, 11, 0);
    lv_obj_set_style_bg_color(seg, C_SOFT, 0);
    lv_obj_set_style_bg_opa(seg, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(seg, C_LINE, 0);
    lv_obj_set_style_border_width(seg, 1, 0);
    return seg;
}

static lv_obj_t *seg_btn(lv_obj_t *seg, int x, int y, int w, int h, const char *text, lv_event_cb_t cb, void *data)
{
    lv_obj_t *b = lv_btn_create(seg);
    lv_obj_remove_style_all(b);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, h);
    lv_obj_set_style_radius(b, 8, 0);
    lv_obj_set_style_bg_color(b, C_CARD, LV_STATE_CHECKED);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, LV_STATE_CHECKED);
    lv_obj_set_style_shadow_opa(b, 40, LV_STATE_CHECKED);
    lv_obj_set_style_shadow_width(b, 6, LV_STATE_CHECKED);
    lv_obj_add_style(b, &s_disabled, LV_STATE_DISABLED);
    lv_obj_t *l = label(b, &font_ui14, C_INK, 0, 0, text);
    lv_obj_center(l);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, data);
    return b;
}

static void seg_mark(lv_obj_t **buttons, int count, int on)
{
    for (int i = 0; i < count; i++) {
        mark(buttons[i], i == on);
    }
}

static void toast_hide(lv_timer_t *t)
{
    lv_obj_add_flag(toast, LV_OBJ_FLAG_HIDDEN);
}

static void show_toast(const char *text, bool error)
{
    lv_label_set_text(toast_lbl, text);
    lv_obj_set_style_bg_color(toast, error ? C_STOP : C_INK, 0);
    lv_obj_clear_flag(toast, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(toast);
    lv_timer_reset(toast_timer);
    lv_timer_set_period(toast_timer, error ? 7000 : 3500);
    lv_timer_resume(toast_timer);
}

static void fmt_time(char *out, size_t n, int s)
{
    if (s < 0) {
        snprintf(out, n, "--:--");
    } else if (s >= 3600) {
        snprintf(out, n, "%d:%02d:%02d", s / 3600, s / 60 % 60, s % 60);
    } else {
        snprintf(out, n, "%02d:%02d", s / 60, s % 60);
    }
}

/* ------------------------------------------------------------------ popup */

typedef void (*confirm_fn)(void);
static confirm_fn popup_ok;

static void popup_close(void)
{
    if (popup) {
        lv_obj_del(popup);
        popup = NULL;
    }
    popup_go = false;
}

static void popup_cancel_cb(lv_event_t *e) { popup_close(); }

static void popup_ok_cb(lv_event_t *e)
{
    confirm_fn fn = popup_ok;
    popup_close();
    if (fn) {
        fn();
    }
}

// Modal question with Abbrechen / <ok>; ok runs fn. The stop column stays usable.
static void ask(const char *title, const char *text, const char *ok, lv_color_t ok_color, confirm_fn fn)
{
    popup_close();
    popup_ok = fn;
    popup = box(lv_layer_top(), 0, 0, 692, 480);
    lv_obj_add_flag(popup, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(popup, C_INK, 0);
    lv_obj_set_style_bg_opa(popup, LV_OPA_40, 0);
    lv_obj_t *c = card(popup, 146, 66, 440, 348);
    lv_obj_t *ic = box(c, 24, 24, 44, 44);
    lv_obj_set_style_radius(ic, 12, 0);
    lv_obj_set_style_bg_color(ic, C_ACCSOFT, 0);
    lv_obj_set_style_bg_opa(ic, LV_OPA_COVER, 0);
    lv_obj_t *w = label(ic, &font_icon20, C_ACCENT2, 0, 0, I_WARN);
    lv_obj_center(w);
    label(c, &font_ui20, C_INK, 84, 34, title);
    lv_obj_t *t = label(c, &font_ui16, C_TEXT2, 24, 88, text);
    lv_obj_set_width(t, 392);
    lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
    key(c, 24, 268, 150, 60, false, NULL, "Abbrechen", popup_cancel_cb, NULL);
    lv_obj_t *b = key(c, 190, 268, 226, 60, false, I_PLAY, ok, popup_ok_cb, NULL);
    lv_obj_set_style_bg_color(b, ok_color, 0);
    lv_obj_set_style_border_width(b, 0, 0);
    lv_obj_set_style_shadow_color(b, ok_color, 0);
    lv_obj_set_style_shadow_opa(b, LV_OPA_40, 0);
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(b); i++) {
        lv_obj_set_style_text_color(lv_obj_get_child(b, i), lv_color_white(), 0);
    }
}

// The go before every job that moves the machine or fires the laser.
static void ask_go(const char *title, const char *detail, const char *ok, confirm_fn fn)
{
    static char text[400];
    snprintf(text, sizeof(text), "%s\n\nHände raus · Deckel zu · Schutzbrille auf.", detail);
    go_clear = st.clear;
    ask(title, text, ok, C_ACCENT, fn);
    popup_go = true;
}

/* ------------------------------------------------------------------ actions */

static void act_stop(lv_event_t *e)
{
    link_act("estop", NULL);         // immediately, no question (docs/PI_API_REFERENZ.md §6)
    show_toast("NOT-HALT gesendet", true);
}

static void act_simple(lv_event_t *e)
{
    const char *op = lv_event_get_user_data(e);
    link_act(op, NULL);
}

static void do_home(void)
{
    if (go_clear) {
        link_act("home", "clear", "1", NULL);
    } else {
        link_act("home", NULL);
    }
    show_toast("Referenzfahrt läuft …", false);
}

static void act_home(lv_event_t *e)
{
    if (st.clear) {
        ask_go("Referenzfahrt starten?", "Die Kopfhöhe ist unbekannt. Steht der Kopf frei über allem?\n"
               "Die 30-mm-Streifen an X0 und Y0 müssen leer sein.", "Kopf ist frei", do_home);
    } else {
        ask_go("Referenzfahrt starten?", "Die 30-mm-Streifen an X0 und Y0 müssen leer sein.", "Starten", do_home);
    }
}

static void do_park(void) { link_act("park", NULL); }

static void act_park(lv_event_t *e)
{
    ask_go("Parken?", "Der Kopf fährt in die Park-Ecke X0/Y0.", "Parken", do_park);
}

static void do_resume(void) { link_act("queue_run", NULL); }

static void act_resume(lv_event_t *e)
{
    static char text[80];
    snprintf(text, sizeof(text), "Noch %d Auftrag/Aufträge laufen mit Laser.", st.qn);
    ask_go("Warteschlange fortsetzen?", text, "Freigeben", do_resume);
}

static void act_jog(lv_event_t *e)
{
    int64_t now = esp_timer_get_time();
    if (now < jog_wait_us) {
        return;                      // one step at a time: the next after the Pi's answer
    }
    jog_wait_us = now + 15000000;
    const char *dir = lv_event_get_user_data(e);     // "X+", "Y-", ...
    char axis[2] = {dir[0], 0};
    char dist[8];
    snprintf(dist, sizeof(dist), "%s%s", dir[1] == '-' ? "-" : "", steps[step]);
    link_act("jog", "axis", axis, "distance", dist, NULL);
}

static void act_step(lv_event_t *e)
{
    step = (int)(intptr_t)lv_event_get_user_data(e);
    seg_mark(step_btn, 3, step);
}

static void do_probe(void)
{
    link_act("probe", NULL);
    show_toast("Fokus wird angetastet …", false);
}

static void act_probe(lv_event_t *e)
{
    ask_go("Fokus tasten?", "Der Taster fährt unter dem Kopf auf das Material.", "Tasten", do_probe);
}

static void act_toggle(lv_event_t *e)
{
    const char *op = lv_event_get_user_data(e);
    bool on = !strcmp(op, "light") ? !st.lights : !st.exhaust;
    link_act(op, "on", on ? "1" : "0", NULL);
}

static void do_frame(void) { link_act("frame_job", "name", selected, NULL); }

static void act_frame(lv_event_t *e)
{
    if (!selected[0]) {
        show_toast("Erst unter „Auftrag“ eine Datei wählen", true);
        return;
    }
    static char text[200];
    if (st.fpow > 0) {
        snprintf(text, sizeof(text), "%s\nDer Kopf fährt den Rahmen ab. Der Laser glimmt dabei mit %g %%.",
                 selected, st.fpow);
    } else {
        snprintf(text, sizeof(text), "%s\nDer Kopf fährt den Rahmen ab. Der Laser bleibt aus.", selected);
    }
    ask_go("Rahmen fahren?", text, "Fahren", do_frame);
}

static void do_start(void)
{
    if (go_clear) {
        link_act("autorun", "name", selected, "clear", "1", NULL);
    } else {
        link_act("autorun", "name", selected, NULL);
    }
    show_toast("Freigegeben: Auftrag startet", false);
}

static void act_start(lv_event_t *e)
{
    if (!selected[0]) {
        return;
    }
    static char text[320];
    snprintf(text, sizeof(text), "%s\nMaterial: %s, %g mm%s", selected, st.mat, st.mat_mm,
             st.clear ? "\nKopfhöhe unbekannt: Kopf steht frei über allem." : "");
    ask_go("Laser freigeben?", text, "Freigeben", do_start);
}

static void act_job_select(lv_event_t *e)
{
    lv_obj_t *b = lv_event_get_target(e);
    const char *name = lv_event_get_user_data(e);
    snprintf(selected, sizeof(selected), "%s", name);
    selected_kb = (int)(intptr_t)lv_obj_get_user_data(b);
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(job_list); i++) {
        lv_obj_t *c = lv_obj_get_child(job_list, i);
        mark(c, c == b);
    }
    lv_label_set_text(lbl_sel, selected);
    lv_label_set_text_fmt(lbl_sel_info, "%d KB%s", selected_kb,
                          !strcmp(st.placed, selected) ? " · platziert" : "");
}

static void act_refresh_jobs(lv_event_t *e) { link_request("jobs"); }

static void act_mat_open(lv_event_t *e)
{
    show(mat_view, true);
    link_request("mats");
}

static void act_mat_close(lv_event_t *e) { show(mat_view, false); }

static void act_mat_pick(lv_event_t *e)
{
    int i = (int)(intptr_t)lv_event_get_user_data(e);
    link_act("material", "name", mat_names[i], "thickness", mat_thick[i], NULL);
    show(mat_view, false);
}

static void act_light_level(lv_event_t *e)
{
    char pct[8];
    snprintf(pct, sizeof(pct), "%d", light_levels[(int)(intptr_t)lv_event_get_user_data(e)]);
    link_act("light", "on", "1", "brightness", pct, NULL);
}

static void act_screen_off(lv_event_t *e)
{
    char minutes[8];
    snprintf(minutes, sizeof(minutes), "%d", off_minutes[(int)(intptr_t)lv_event_get_user_data(e)]);
    link_act("screen_off", "minutes", minutes, NULL);
}

static void do_panel_update(void) { link_act("panel_update", NULL); }

static void act_panel_update(lv_event_t *e)
{
    ask("Panel aktualisieren?", "Der Bildschirm ist dabei kurz aus. Die Maschine wird nicht berührt.",
        "Aktualisieren", C_INK, do_panel_update);
}

static void act_zoom(lv_event_t *e)
{
    cam_zoom = !cam_zoom;
    if (cam_dsc.data) {
        ui_on_image((const uint16_t *)cam_dsc.data, cam_dsc.header.w, cam_dsc.header.h);
    }
}

static void act_estop_reset(lv_event_t *e)
{
    link_act("estop_reset", NULL);
    show_toast("Notstopp wird quittiert …", false);
}

/* ------------------------------------------------------------------ navigation */

static void show_tab(int n)
{
    sys_tab = n;
    for (int i = 0; i < TAB_COUNT; i++) {
        show(tabs[i], i == n);
    }
    seg_mark(tab_btn, TAB_COUNT, n);
    if (n == TAB_EVENTS) {
        link_request("events");
        shown_events = st.ev;
        seen_problem = st.evp;
        show(nav_dot, false);
    } else if (n == TAB_INFO) {
        link_request("sys");
    }
}

static void act_tab(lv_event_t *e) { show_tab((int)(intptr_t)lv_event_get_user_data(e)); }

static void show_screen(int n)
{
    screen = n;
    for (int i = 0; i < SCR_COUNT; i++) {
        show(screens[i], i == n);
        mark(navs[i], i == n);
    }
    show(mat_view, false);
    if (n == SCR_JOBS) {
        link_request("jobs");
    } else if (n == SCR_SYSTEM) {
        show_tab(sys_tab);
    }
}

static void nav_cb(lv_event_t *e) { show_screen((int)(intptr_t)lv_event_get_user_data(e)); }

bool ui_camera_wanted(void) { return screen == SCR_CAMERA && !dark; }

/* ------------------------------------------------------------------ screen off */

static bool job_active(void)
{
    return !strcmp(st.job_state, "homing") || !strcmp(st.job_state, "probing") || !strcmp(st.job_state, "running");
}

static bool owner_free(void) { return !strcmp(st.owner, "Frei") || !strcmp(st.owner, "monitor"); }

// Anything going on: the screen stays lit, so STOPP is never behind a first touch that only wakes it.
static bool machine_busy(void)
{
    return strcmp(st.act, "idle") != 0 || job_active() || st.armed || st.latched || !owner_free() ||
           !strcmp(st.queue, "running") || !strcmp(st.queue, "pausing");
}

static void screen_wake(void)
{
    if (dark) {
        dark = false;
        board_backlight(true);
        lv_disp_trig_activity(NULL);
    }
}

// The touch that wakes the screen does nothing else: dark_catch lies above everything until it is released.
static void dark_catch_cb(lv_event_t *e)
{
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_PRESSED) {
        screen_wake();
    } else if (code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST) {
        lv_obj_add_flag(dark_catch, LV_OBJ_FLAG_HIDDEN);
    }
}

static void screen_tick(bool online)
{
    if (!online || machine_busy()) {
        lv_disp_trig_activity(NULL);     // the time counts from the end of the job
        screen_wake();
        if (!lv_obj_has_state(dark_catch, LV_STATE_PRESSED)) {
            lv_obj_add_flag(dark_catch, LV_OBJ_FLAG_HIDDEN);
        }
        return;
    }
    if (!dark && st.soff > 0 && lv_disp_get_inactive_time(NULL) > (uint32_t)st.soff * 60000u) {
        dark = true;
        popup_close();
        lv_obj_clear_flag(dark_catch, LV_OBJ_FLAG_HIDDEN);
        board_backlight(false);
    }
}

/* ------------------------------------------------------------------ build */

static void styles(void)
{
    lv_style_init(&s_card);
    lv_style_set_bg_color(&s_card, C_CARD);
    lv_style_set_bg_opa(&s_card, LV_OPA_COVER);
    lv_style_set_radius(&s_card, 16);
    lv_style_set_border_color(&s_card, lv_color_hex(0xE6E9ED));
    lv_style_set_border_width(&s_card, 1);
    lv_style_set_shadow_color(&s_card, lv_color_hex(0x142028));
    lv_style_set_shadow_opa(&s_card, 18);
    lv_style_set_shadow_width(&s_card, 14);
    lv_style_set_shadow_ofs_y(&s_card, 4);

    lv_style_init(&s_key);
    lv_style_set_bg_color(&s_key, C_CARD);
    lv_style_set_bg_opa(&s_key, LV_OPA_COVER);
    lv_style_set_radius(&s_key, 14);
    lv_style_set_border_color(&s_key, lv_color_hex(0xE1E5E9));
    lv_style_set_border_width(&s_key, 1);
    lv_style_set_shadow_color(&s_key, lv_color_hex(0x142028));
    lv_style_set_shadow_opa(&s_key, 24);
    lv_style_set_shadow_width(&s_key, 8);
    lv_style_set_shadow_ofs_y(&s_key, 3);

    lv_style_init(&s_key_dark);
    lv_style_set_bg_color(&s_key_dark, C_INK);
    lv_style_set_bg_opa(&s_key_dark, LV_OPA_COVER);
    lv_style_set_radius(&s_key_dark, 14);
    lv_style_set_shadow_color(&s_key_dark, C_INK);
    lv_style_set_shadow_opa(&s_key_dark, 60);
    lv_style_set_shadow_width(&s_key_dark, 12);
    lv_style_set_shadow_ofs_y(&s_key_dark, 5);

    lv_style_init(&s_key_on);
    lv_style_set_bg_color(&s_key_on, C_ACCSOFT);
    lv_style_set_border_color(&s_key_on, lv_color_hex(0xFFB98F));
    lv_style_set_border_width(&s_key_on, 2);

    lv_style_init(&s_key_pr);
    lv_style_set_transform_width(&s_key_pr, -2);
    lv_style_set_transform_height(&s_key_pr, -2);
    lv_style_set_bg_color(&s_key_pr, lv_color_hex(0xE9ECEF));

    lv_style_init(&s_disabled);
    lv_style_set_opa(&s_disabled, LV_OPA_40);

    lv_style_init(&s_nav);
    lv_style_set_radius(&s_nav, 12);
    lv_style_set_bg_opa(&s_nav, LV_OPA_TRANSP);
    lv_style_set_text_color(&s_nav, lv_color_hex(0x5D656E));

    lv_style_init(&s_nav_on);
    lv_style_set_bg_color(&s_nav_on, C_INK);
    lv_style_set_bg_opa(&s_nav_on, LV_OPA_COVER);
    lv_style_set_text_color(&s_nav_on, lv_color_white());
    lv_style_set_shadow_color(&s_nav_on, C_INK);
    lv_style_set_shadow_opa(&s_nav_on, 70);
    lv_style_set_shadow_width(&s_nav_on, 14);
    lv_style_set_shadow_ofs_y(&s_nav_on, 6);

    lv_style_init(&s_pill);
    lv_style_set_radius(&s_pill, 15);
    lv_style_set_bg_color(&s_pill, C_SOFT);
    lv_style_set_bg_opa(&s_pill, LV_OPA_COVER);
    lv_style_set_border_color(&s_pill, C_LINE);
    lv_style_set_border_width(&s_pill, 1);
    lv_style_set_pad_hor(&s_pill, 11);
    lv_style_set_pad_gap(&s_pill, 7);
}

static lv_obj_t *pill(lv_obj_t *parent, const char *text)
{
    lv_obj_t *p = lv_obj_create(parent);
    lv_obj_remove_style_all(p);
    lv_obj_add_style(p, &s_pill, 0);
    lv_obj_set_size(p, LV_SIZE_CONTENT, 30);
    lv_obj_set_flex_flow(p, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(p, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_t *dot = lv_obj_create(p);
    lv_obj_remove_style_all(dot);
    lv_obj_set_size(dot, 8, 8);
    lv_obj_set_style_radius(dot, 4, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(dot, C_OFF, 0);
    lv_obj_t *t = label(p, &font_ui14, C_TEXT2, 0, 0, text);
    (void)t;
    return p;
}

static void pill_set(lv_obj_t *p, bool on, lv_color_t color, bool hot)
{
    lv_obj_set_style_bg_color(lv_obj_get_child(p, 0), on ? color : C_OFF, 0);
    lv_obj_set_style_bg_color(p, hot && on ? C_ACCSOFT : C_SOFT, 0);
    lv_obj_set_style_border_color(p, hot && on ? lv_color_hex(0xFFD2B6) : C_LINE, 0);
}

static void build_frame(lv_obj_t *scr)
{
    // top bar with the one metal detail: a fine aluminium edge
    lv_obj_t *top = card(scr, 12, 10, 776, 48);
    lv_obj_set_style_radius(top, 14, 0);
    lv_obj_set_style_bg_color(top, lv_color_hex(0xFAFBFC), 0);
    lv_obj_set_style_bg_grad_color(top, lv_color_hex(0xE7EAEE), 0);
    lv_obj_set_style_bg_grad_dir(top, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_border_color(top, lv_color_hex(0xD4D9DE), 0);
    static const int sx[4] = {6, 6, 763, 763}, sy[4] = {6, 35, 6, 35};
    for (int i = 0; i < 4; i++) {
        lv_obj_t *s = box(top, sx[i], sy[i], 7, 7);
        lv_obj_set_style_radius(s, 4, 0);
        lv_obj_set_style_bg_opa(s, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(s, lv_color_hex(0xC3C9CF), 0);
        lv_obj_set_style_border_color(s, lv_color_hex(0x9AA2AA), 0);
        lv_obj_set_style_border_width(s, 1, 0);
    }
    lv_obj_t *logo = label(top, &font_ui20, C_INK, 22, 11, "/Luma#FF6A13 Cut#/");
    lv_label_set_recolor(logo, true);
    lv_obj_t *sub = caption(top, 138, 18, "CNC · LT-80W");
    (void)sub;

    lv_obj_t *pills = box(top, 300, 9, 470, 30);
    lv_obj_set_flex_flow(pills, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(pills, LV_FLEX_ALIGN_END, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_gap(pills, 6, 0);
    pill_pi = pill(pills, "Pi");
    pill_skr = pill(pills, "SKR");
    pill_laser = pill(pills, "Laser");
    pill_air = pill(pills, "Abluft");
    pill_light = pill(pills, "Licht");
    lbl_time = label(pills, &font_mono16, C_INK, 0, 0, "--:--");
    lv_obj_set_style_pad_left(lbl_time, 8, 0);

    // navigation
    lv_obj_t *rail = card(scr, 12, 68, 84, 400);
    static const char *icons[SCR_COUNT] = {I_GAUGE, I_MOVE, I_CAMERA, I_FILE, I_COG};
    static const char *names[SCR_COUNT] = {"Status", "Bewegen", "Kamera", "Auftrag", "System"};
    for (int i = 0; i < SCR_COUNT; i++) {
        lv_obj_t *b = lv_btn_create(rail);
        lv_obj_remove_style_all(b);
        lv_obj_set_pos(b, 10, 8 + i * 77);
        lv_obj_set_size(b, 64, 73);
        lv_obj_add_style(b, &s_nav, 0);
        lv_obj_add_style(b, &s_nav_on, LV_STATE_CHECKED);
        lv_obj_set_flex_flow(b, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(b, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_set_style_pad_gap(b, 7, 0);
        lv_obj_t *ic = lv_label_create(b);
        lv_obj_set_style_text_font(ic, &font_icon20, 0);
        lv_label_set_text(ic, icons[i]);
        lv_obj_t *t = lv_label_create(b);
        lv_obj_set_style_text_font(t, &font_ui11, 0);
        lv_label_set_text(t, names[i]);
        lv_obj_add_event_cb(b, nav_cb, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        navs[i] = b;
    }
    // a warning or error not looked at yet
    nav_dot = box(navs[SCR_SYSTEM], 48, 8, 10, 10);
    lv_obj_add_flag(nav_dot, LV_OBJ_FLAG_IGNORE_LAYOUT);
    lv_obj_set_style_radius(nav_dot, 5, 0);
    lv_obj_set_style_bg_color(nav_dot, C_STOP, 0);
    lv_obj_set_style_bg_opa(nav_dot, LV_OPA_COVER, 0);
    lv_obj_add_flag(nav_dot, LV_OBJ_FLAG_HIDDEN);

    // stop column: always reachable, also during popups (popup leaves x >= 692 free)
    lv_obj_t *side = card(lv_layer_top(), 704, 68, 84, 400);
    lv_obj_t *stop = lv_btn_create(side);
    lv_obj_remove_style_all(stop);
    lv_obj_set_pos(stop, 5, 12);
    lv_obj_set_size(stop, 72, 72);
    lv_obj_set_style_radius(stop, 36, 0);
    lv_obj_set_style_bg_opa(stop, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(stop, lv_color_hex(0xFF5A4F), 0);
    lv_obj_set_style_bg_grad_color(stop, lv_color_hex(0xC8180F), 0);
    lv_obj_set_style_bg_grad_dir(stop, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_border_color(stop, lv_color_white(), 0);
    lv_obj_set_style_border_width(stop, 4, 0);
    lv_obj_set_style_outline_color(stop, C_LINE, 0);
    lv_obj_set_style_outline_width(stop, 1, 0);
    lv_obj_set_style_shadow_color(stop, C_STOP, 0);
    lv_obj_set_style_shadow_opa(stop, 110, 0);
    lv_obj_set_style_shadow_width(stop, 20, 0);
    lv_obj_set_style_shadow_ofs_y(stop, 8, 0);
    lv_obj_add_style(stop, &s_key_pr, LV_STATE_PRESSED);
    lv_obj_t *sl = label(stop, &font_ui14, lv_color_white(), 0, 0, "STOPP");
    lv_obj_center(sl);
    lv_obj_add_event_cb(stop, act_stop, LV_EVENT_PRESSED, NULL);   // on touch, not on release
    lv_obj_t *nh = caption(side, 0, 92, "NOT-HALT");
    lv_obj_set_width(nh, 84);
    lv_obj_set_style_text_align(nh, LV_TEXT_ALIGN_CENTER, 0);
    btn_pause = key(side, 10, 120, 64, 80, false, I_PAUSE, "Pause", act_simple, "queue_pause");
    btn_resume = key(side, 10, 210, 64, 80, false, I_PLAY, "Weiter", act_resume, NULL);
    btn_abort = key(side, 10, 300, 64, 86, false, I_TIMES, "Abbruch", act_simple, "abort");
}

static void build_status(lv_obj_t *s)
{
    lv_obj_t *c = card(s, 0, 0, 250, 400);
    lbl_title = label(c, &font_ui20, C_INK, 20, 16, "Bereit");
    arc = lv_arc_create(c);
    lv_obj_set_pos(arc, 25, 54);
    lv_obj_set_size(arc, 200, 200);
    lv_arc_set_rotation(arc, 270);
    lv_arc_set_bg_angles(arc, 0, 360);
    lv_arc_set_range(arc, 0, 100);
    lv_arc_set_value(arc, 0);
    lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
    lv_obj_clear_flag(arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(arc, 13, LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc, 13, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc, lv_color_hex(0xECEEF1), LV_PART_MAIN);
    lv_obj_set_style_arc_color(arc, C_ACCENT, LV_PART_INDICATOR);
    lbl_pct = label(c, &font_big56, C_INK, 0, 0, "0%");
    lv_obj_align(lbl_pct, LV_ALIGN_TOP_MID, 0, 116);
    lbl_rest = label(c, &font_ui14, C_MUTE, 0, 0, "");
    lv_obj_align(lbl_rest, LV_ALIGN_TOP_MID, 0, 182);
    lv_obj_t *sep = box(c, 20, 276, 210, 1);
    lv_obj_set_style_bg_color(sep, C_LINE, 0);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lbl_file = label(c, &font_ui16, C_INK, 20, 290, "Kein Auftrag");
    lv_obj_set_width(lbl_file, 210);
    lv_label_set_long_mode(lbl_file, LV_LABEL_LONG_DOT);
    lbl_info1 = label(c, &font_ui14, C_MUTE, 20, 316, "");
    lbl_info2 = label(c, &font_ui14, C_MUTE, 20, 338, "");
    lv_obj_set_width(lbl_info2, 214);
    lv_label_set_long_mode(lbl_info2, LV_LABEL_LONG_WRAP);

    lv_obj_t *p = card(s, 262, 0, 326, 150);
    caption(p, 20, 18, "POSITION · MM");
    static const char *ax[3] = {"X", "Y", "Z"};
    static const int px[3] = {20, 128, 236};
    for (int i = 0; i < 3; i++) {
        label(p, &font_ui14, C_INK, px[i], 58, ax[i]);
        lbl_pos[i] = label(p, &font_mono26, C_INK, px[i], 82, "---");
    }

    lv_obj_t *w = card(s, 262, 162, 326, 120);
    caption(w, 20, 18, "LASERLEISTUNG");
    lbl_power = label(w, &font_mono16, C_ACCENT, 0, 0, "--");
    lv_obj_align(lbl_power, LV_ALIGN_TOP_RIGHT, -20, 14);
    bar_power = lv_bar_create(w);
    lv_obj_set_pos(bar_power, 20, 42);
    lv_obj_set_size(bar_power, 286, 6);
    lv_obj_set_style_bg_color(bar_power, lv_color_hex(0xECEEF1), LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar_power, C_ACCENT, LV_PART_INDICATOR);
    caption(w, 20, 74, "VORSCHUB");
    lbl_feed = label(w, &font_mono16, C_INK, 0, 0, "--");
    lv_obj_align(lbl_feed, LV_ALIGN_TOP_RIGHT, -20, 70);
    bar_feed = lv_bar_create(w);
    lv_obj_set_pos(bar_feed, 20, 98);
    lv_obj_set_size(bar_feed, 286, 6);
    lv_bar_set_range(bar_feed, 0, 6000);
    lv_obj_set_style_bg_color(bar_feed, lv_color_hex(0xECEEF1), LV_PART_MAIN);
    lv_obj_set_style_bg_color(bar_feed, C_INK, LV_PART_INDICATOR);

    lv_obj_t *k = card(s, 262, 294, 326, 106);
    static const char *chips[4] = {"LASER", "24 V", "ABLUFT", "REFERENZ"};
    for (int i = 0; i < 4; i++) {
        lv_obj_t *ch = box(k, 14 + i * 76, 24, 70, 58);
        lv_obj_set_style_radius(ch, 12, 0);
        lv_obj_set_style_bg_color(ch, C_SOFT, 0);
        lv_obj_set_style_bg_opa(ch, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(ch, C_LINE, 0);
        lv_obj_set_style_border_width(ch, 1, 0);
        lv_obj_t *cap = caption(ch, 9, 10, chips[i]);
        lv_obj_set_style_text_letter_space(cap, 0, 0);
        chip_dot[i] = box(ch, 10, 36, 8, 8);
        lv_obj_set_style_radius(chip_dot[i], 4, 0);
        lv_obj_set_style_bg_opa(chip_dot[i], LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(chip_dot[i], C_OFF, 0);
        chip_val[i] = label(ch, &font_ui14, C_INK, 24, 30, "–");
    }
}

static lv_obj_t *move_key(lv_obj_t *parent, int x, int y, int w, int h, bool dark, const char *icon,
                          const char *text, lv_event_cb_t cb, void *data)
{
    lv_obj_t *b = key(parent, x, y, w, h, dark, icon, text, cb, data);
    if (n_move_keys < 16) {
        move_keys[n_move_keys++] = b;
    }
    return b;
}

static void build_move(lv_obj_t *s)
{
    lv_obj_t *c = card(s, 0, 0, 300, 400);
    label(c, &font_ui20, C_INK, 20, 16, "Bewegen");
    lv_obj_t *pad = box(c, 30, 62, 240, 240);
    lv_obj_set_style_radius(pad, 120, 0);
    lv_obj_set_style_bg_color(pad, C_SOFT, 0);
    lv_obj_set_style_bg_opa(pad, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(pad, lv_color_hex(0xDFE3E7), 0);
    lv_obj_set_style_border_width(pad, 1, 0);
    // as seen from the front: X0/Y0 is top right, X grows to the left, Y to the front
    move_key(c, 118, 74, 64, 62, false, I_UP, "Y−", act_jog, "Y-");
    move_key(c, 118, 228, 64, 62, false, I_DOWN, "Y+", act_jog, "Y+");
    move_key(c, 42, 151, 64, 62, false, I_LEFT, "X+", act_jog, "X+");
    move_key(c, 194, 151, 64, 62, false, I_RIGHT, "X−", act_jog, "X-");
    key_home = key(c, 124, 156, 52, 52, true, I_HOME, NULL, act_home, NULL);
    lv_obj_set_style_radius(key_home, 26, 0);
    lbl_move_hint = label(c, &font_ui14, C_MUTE, 0, 314, "Mitte = Referenzfahrt");
    lv_obj_set_width(lbl_move_hint, 300);
    lv_obj_set_style_text_align(lbl_move_hint, LV_TEXT_ALIGN_CENTER, 0);
    lbl_move_pos = label(c, &font_mono16, C_TEXT2, 0, 344, "X ---  Y ---");
    lv_obj_set_width(lbl_move_pos, 300);
    lv_obj_set_style_text_align(lbl_move_pos, LV_TEXT_ALIGN_CENTER, 0);

    lv_obj_t *z = card(s, 312, 0, 100, 400);
    lv_obj_t *zt = label(z, &font_ui20, C_INK, 0, 16, "Z");
    lv_obj_set_width(zt, 100);
    lv_obj_set_style_text_align(zt, LV_TEXT_ALIGN_CENTER, 0);
    move_key(z, 18, 60, 64, 90, false, I_UP, "Z+", act_jog, "Z+");
    lbl_z = label(z, &font_mono26, C_INK, 0, 170, "--");
    lv_obj_set_width(lbl_z, 100);
    lv_obj_set_style_text_align(lbl_z, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_t *mm = caption(z, 0, 204, "MM");
    lv_obj_set_width(mm, 100);
    lv_obj_set_style_text_align(mm, LV_TEXT_ALIGN_CENTER, 0);
    move_key(z, 18, 240, 64, 90, false, I_DOWN, "Z−", act_jog, "Z-");

    lv_obj_t *r = card(s, 424, 0, 164, 400);
    caption(r, 16, 18, "SCHRITTWEITE");
    lv_obj_t *seg = seg_track(r, 14, 40, 136, 150);
    static const char *names[3] = {"0,1 mm", "1 mm", "10 mm"};
    for (int i = 0; i < 3; i++) {
        step_btn[i] = seg_btn(seg, 5, 5 + i * 47, 126, 42, names[i], act_step, (void *)(intptr_t)i);
    }
    seg_mark(step_btn, 3, step);
    move_key(r, 14, 222, 136, 64, false, I_PARK, "Parken", act_park, NULL);
    move_key(r, 14, 304, 136, 72, true, I_PROBE, "Fokus tasten", act_probe, NULL);
}

static void build_camera(lv_obj_t *s)
{
    lv_obj_t *c = card(s, 0, 0, 470, 400);
    lv_obj_t *view = box(c, 14, 14, 442, 372);
    lv_obj_set_style_radius(view, 10, 0);
    lv_obj_set_style_clip_corner(view, true, 0);
    lv_obj_set_style_bg_color(view, lv_color_hex(0xE9ECEF), 0);
    lv_obj_set_style_bg_opa(view, LV_OPA_COVER, 0);
    cam_img = lv_img_create(view);
    lv_obj_center(cam_img);
    lv_obj_add_flag(cam_img, LV_OBJ_FLAG_HIDDEN);
    cam_hint = label(view, &font_ui16, C_MUTE, 0, 0, "Kamerabild wird geladen …");
    lv_obj_center(cam_hint);
    cam_badge = box(view, 12, 12, 64, 26);
    lv_obj_set_style_radius(cam_badge, 13, 0);
    lv_obj_set_style_bg_color(cam_badge, lv_color_white(), 0);
    lv_obj_set_style_bg_opa(cam_badge, 225, 0);
    lv_obj_t *dot = box(cam_badge, 10, 9, 8, 8);
    lv_obj_set_style_radius(dot, 4, 0);
    lv_obj_set_style_bg_color(dot, C_STOP, 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    label(cam_badge, &font_ui11, C_INK, 24, 6, "Live");
    lv_obj_add_flag(cam_badge, LV_OBJ_FLAG_HIDDEN);

    key_cam_frame = key(s, 482, 0, 106, 92, false, I_FRAME, "Rahmen", act_frame, NULL);
    key(s, 482, 102, 106, 92, false, I_ZOOM, "Zoom", act_zoom, NULL);
    key_cam_light = key(s, 482, 204, 106, 92, false, I_LIGHT, "Licht", act_toggle, "light");
    key_cam_air = key(s, 482, 306, 106, 94, false, I_WIND, "Abluft", act_toggle, "exhaust");
}

static void build_jobs(lv_obj_t *s)
{
    lv_obj_t *c = card(s, 0, 0, 300, 400);
    label(c, &font_ui20, C_INK, 20, 16, "Aufträge");
    lv_obj_t *r = key(c, 236, 10, 48, 40, false, I_SYNC, NULL, act_refresh_jobs, NULL);
    (void)r;
    job_list = lv_obj_create(c);
    lv_obj_remove_style_all(job_list);
    lv_obj_set_pos(job_list, 12, 60);
    lv_obj_set_size(job_list, 276, 328);
    lv_obj_set_flex_flow(job_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_gap(job_list, 6, 0);
    lv_obj_set_scroll_dir(job_list, LV_DIR_VER);
    label(job_list, &font_ui14, C_MUTE, 0, 0, "Liste wird geladen …");

    lv_obj_t *d = card(s, 312, 0, 276, 400);
    caption(d, 22, 20, "AUSGEWÄHLT");
    lbl_sel = label(d, &font_ui16, C_INK, 22, 42, "–");
    lv_obj_set_width(lbl_sel, 232);
    lv_label_set_long_mode(lbl_sel, LV_LABEL_LONG_WRAP);
    lbl_sel_info = label(d, &font_ui14, C_MUTE, 22, 88, "Datei links antippen");
    key_mat = key(d, 22, 116, 232, 80, false, I_LAYERS, "Material wählen", act_mat_open, NULL);
    lbl_key_mat = lv_obj_get_child(key_mat, 1);
    lv_obj_set_width(lbl_key_mat, 180);
    lv_label_set_long_mode(lbl_key_mat, LV_LABEL_LONG_WRAP);
    btn_frame_job = key(d, 22, 208, 232, 64, false, I_FRAME, "Rahmen fahren", act_frame, NULL);
    btn_start = key(d, 22, 284, 232, 96, false, I_PLAY, "LASER STARTEN", act_start, NULL);
    lv_obj_set_style_bg_color(btn_start, C_ACCENT, 0);
    lv_obj_set_style_bg_grad_color(btn_start, C_ACCENT2, 0);
    lv_obj_set_style_bg_grad_dir(btn_start, LV_GRAD_DIR_VER, 0);
    lv_obj_set_style_border_width(btn_start, 0, 0);
    lv_obj_set_style_shadow_color(btn_start, C_ACCENT2, 0);
    lv_obj_set_style_shadow_opa(btn_start, 90, 0);
    lv_obj_set_style_shadow_width(btn_start, 22, 0);
    for (uint32_t i = 0; i < lv_obj_get_child_cnt(btn_start); i++) {
        lv_obj_set_style_text_color(lv_obj_get_child(btn_start, i), lv_color_white(), 0);
    }
    lv_obj_set_style_text_font(lv_obj_get_child(btn_start, 1), &font_ui20, 0);
    enable(btn_frame_job, false);
    enable(btn_start, false);

    // material list, over the whole screen
    mat_view = card(s, 0, 0, 588, 400);
    label(mat_view, &font_ui20, C_INK, 20, 16, "Material wählen");
    key(mat_view, 448, 8, 124, 48, false, I_LEFT, "Zurück", act_mat_close, NULL);
    label(mat_view, &font_ui14, C_MUTE, 20, 46, "Die Stärke setzt die Fahrhöhe. Leistung steht im Auftrag.");
    mat_list = lv_obj_create(mat_view);
    lv_obj_remove_style_all(mat_list);
    lv_obj_set_pos(mat_list, 12, 72);
    lv_obj_set_size(mat_list, 564, 316);
    lv_obj_set_flex_flow(mat_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_gap(mat_list, 6, 0);
    lv_obj_set_scroll_dir(mat_list, LV_DIR_VER);
    label(mat_list, &font_ui14, C_MUTE, 0, 0, "Liste wird geladen …");
    lv_obj_add_flag(mat_view, LV_OBJ_FLAG_HIDDEN);
}

static lv_obj_t *info_field(lv_obj_t *parent, int x, int y, const char *name, const char *value)
{
    caption(parent, x, y, name);
    lv_obj_t *v = label(parent, &font_ui16, C_INK, x, y + 18, value);
    lv_obj_set_width(v, 262);
    lv_label_set_long_mode(v, LV_LABEL_LONG_DOT);
    return v;
}

static void build_system(lv_obj_t *s)
{
    lv_obj_t *seg = seg_track(s, 0, 0, 588, 56);
    static const char *names[TAB_COUNT] = {"Licht & Abluft", "Ereignisse", "Info"};
    for (int i = 0; i < TAB_COUNT; i++) {
        tab_btn[i] = seg_btn(seg, 5 + i * 193, 5, 190, 44, names[i], act_tab, (void *)(intptr_t)i);
        tabs[i] = box(s, 0, 66, 588, 334);
    }

    // light, exhaust, screen
    lv_obj_t *t = tabs[TAB_MACHINE];
    lv_obj_t *c = card(t, 0, 0, 588, 156);
    label(c, &font_ui20, C_INK, 20, 14, "Licht");
    key_light = key(c, 20, 54, 130, 84, false, I_LIGHT, "Aus", act_toggle, "light");
    lbl_no_dim = label(c, &font_ui14, C_MUTE, 172, 86, "Diese Firmware kann das Licht nicht dimmen.");
    lv_obj_add_flag(lbl_no_dim, LV_OBJ_FLAG_HIDDEN);
    lv_obj_t *levels = seg_track(c, 166, 54, 402, 84);
    static const char *level_names[5] = {"10 %", "30 %", "60 %", "80 %", "100 %"};
    for (int i = 0; i < 5; i++) {
        level_btn[i] = seg_btn(levels, 5 + i * 79, 5, 76, 72, level_names[i], act_light_level, (void *)(intptr_t)i);
    }
    c = card(t, 0, 168, 170, 166);
    label(c, &font_ui20, C_INK, 20, 14, "Abluft");
    key_air = key(c, 20, 54, 130, 92, false, I_WIND, "Aus", act_toggle, "exhaust");
    c = card(t, 182, 168, 406, 166);
    label(c, &font_ui20, C_INK, 20, 14, "Bildschirm aus nach");
    lv_obj_t *offs = seg_track(c, 14, 54, 378, 72);
    static const char *off_names[5] = {"Nie", "2 min", "5 min", "15 min", "30 min"};
    for (int i = 0; i < 5; i++) {
        off_btn[i] = seg_btn(offs, 5 + i * 74, 5, 71, 60, off_names[i], act_screen_off, (void *)(intptr_t)i);
    }
    label(c, &font_ui14, C_MUTE, 20, 134, "Bleibt an, solange die Maschine arbeitet.");

    // events
    c = card(tabs[TAB_EVENTS], 0, 0, 588, 334);
    event_list = lv_obj_create(c);
    lv_obj_remove_style_all(event_list);
    lv_obj_set_pos(event_list, 12, 10);
    lv_obj_set_size(event_list, 564, 314);
    lv_obj_set_flex_flow(event_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_scroll_dir(event_list, LV_DIR_VER);
    label(event_list, &font_ui14, C_MUTE, 0, 0, "Noch keine Ereignisse");

    // network and versions
    c = card(tabs[TAB_INFO], 0, 0, 588, 334);
    info_ip = info_field(c, 20, 16, "ADRESSE", "–");
    info_wifi = info_field(c, 20, 76, "WLAN", "–");
    info_host = info_field(c, 20, 136, "NAME", "–");
    info_field(c, 306, 16, "PANEL", PANEL_VERSION);
    info_pi = info_field(c, 306, 76, "PI-SOFTWARE", "–");
    info_skr = info_field(c, 306, 136, "STEUERUNG", "–");
    lv_obj_t *sep = box(c, 20, 194, 548, 1);
    lv_obj_set_style_bg_color(sep, C_LINE, 0);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lbl_update = label(c, &font_ui14, C_TEXT2, 20, 208, "");
    lv_obj_set_width(lbl_update, 340);
    lv_label_set_long_mode(lbl_update, LV_LABEL_LONG_WRAP);
    key_panel_update = key(c, 380, 212, 188, 100, true, I_SYNC, "Panel aktualisieren", act_panel_update, NULL);
    lv_obj_add_flag(key_panel_update, LV_OBJ_FLAG_HIDDEN);
    show_tab(TAB_MACHINE);
}

static void build_overlays(lv_obj_t *scr)
{
    toast = box(lv_layer_top(), 0, 0, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_style_radius(toast, 14, 0);
    lv_obj_set_style_bg_opa(toast, 240, 0);
    lv_obj_set_style_pad_hor(toast, 18, 0);
    lv_obj_set_style_pad_ver(toast, 12, 0);
    lv_obj_set_style_max_width(toast, 560, 0);
    toast_lbl = label(toast, &font_ui14, lv_color_white(), 0, 0, "");
    lv_obj_set_style_max_width(toast_lbl, 524, 0);
    lv_label_set_long_mode(toast_lbl, LV_LABEL_LONG_WRAP);
    lv_obj_align(toast, LV_ALIGN_BOTTOM_MID, -46, -20);
    lv_obj_add_flag(toast, LV_OBJ_FLAG_HIDDEN);
    toast_timer = lv_timer_create(toast_hide, 3500, NULL);
    lv_timer_pause(toast_timer);
    lv_timer_set_repeat_count(toast_timer, -1);

    // emergency latch: everything but the stop column and the reset
    latch_box = card(scr, 106, 68, 588, 400);
    lv_obj_add_flag(latch_box, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_color(latch_box, lv_color_hex(0xFFF3F2), 0);
    lv_obj_set_style_border_color(latch_box, lv_color_hex(0xF5B5B0), 0);
    label(latch_box, &font_icon26, C_STOP, 32, 34, I_WARN);
    label(latch_box, &font_ui20, C_STOP, 76, 36, "Notstopp aktiv");
    lbl_latch = label(latch_box, &font_ui16, C_TEXT2, 32, 90,
                      "1. SKR zurücksetzen (Reset-Taste oder 24 V kurz aus).\n"
                      "2. Hier quittieren.\n3. Danach neu referenzieren.");
    lv_obj_set_width(lbl_latch, 520);
    lv_label_set_long_mode(lbl_latch, LV_LABEL_LONG_WRAP);
    lv_obj_t *q = key(latch_box, 32, 300, 260, 64, true, I_SYNC, "Notstopp quittieren", act_estop_reset, NULL);
    (void)q;
    lv_obj_add_flag(latch_box, LV_OBJ_FLAG_HIDDEN);

    offline = card(scr, 106, 68, 588, 400);
    lv_obj_add_flag(offline, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_t *o1 = label(offline, &font_ui20, C_INK, 0, 150, "Keine Verbindung zum Pi");
    lv_obj_set_width(o1, 588);
    lv_obj_set_style_text_align(o1, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_t *o2 = label(offline, &font_ui14, C_MUTE, 0, 186,
                         "USB-C-Buchse „USB“ des Panels mit dem Pi verbinden.\n"
                         "STOPP sendet trotzdem – der echte Not-Aus bleibt der rote Pilz.");
    lv_obj_set_width(o2, 588);
    lv_obj_set_style_text_align(o2, LV_TEXT_ALIGN_CENTER, 0);

    // above everything while the screen is dark
    dark_catch = box(lv_layer_sys(), 0, 0, 800, 480);
    lv_obj_add_flag(dark_catch, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_add_flag(dark_catch, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_event_cb(dark_catch, dark_catch_cb, LV_EVENT_ALL, NULL);
}

static void watchdog(lv_timer_t *t)
{
    bool online = last_status_us && esp_timer_get_time() - last_status_us < 3500000;
    if (online) {
        lv_obj_add_flag(offline, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_clear_flag(offline, LV_OBJ_FLAG_HIDDEN);
    }
    pill_set(pill_pi, online, C_OK, false);
    if (cam_last_us && esp_timer_get_time() - cam_last_us > 8000000) {
        lv_obj_add_flag(cam_badge, LV_OBJ_FLAG_HIDDEN);
    }
    if (popup && popup_go && !online) {
        popup_close();
    }
    screen_tick(online);
    static int ticks;
    if (++ticks >= 10) {
        ticks = 0;
        if (screen == SCR_SYSTEM && sys_tab == TAB_INFO && !dark) {
            link_request("sys");
        }
    }
}

void ui_init(void)
{
    styles();
    lv_obj_t *scr = lv_scr_act();
    lv_obj_set_style_bg_color(scr, C_BG, 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    build_frame(scr);
    for (int i = 0; i < SCR_COUNT; i++) {
        screens[i] = box(scr, 106, 68, 588, 400);
        lv_obj_set_style_clip_corner(screens[i], false, 0);
    }
    build_status(screens[SCR_STATUS]);
    build_move(screens[SCR_MOVE]);
    build_camera(screens[SCR_CAMERA]);
    build_jobs(screens[SCR_JOBS]);
    build_system(screens[SCR_SYSTEM]);
    build_overlays(scr);
    show_screen(SCR_STATUS);
    lv_timer_create(watchdog, 500, NULL);
}

/* ------------------------------------------------------------------ data from the Pi */

static void copy_str(char *dst, size_t n, const cJSON *obj, const char *key)
{
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(obj, key));
    snprintf(dst, n, "%s", v ? v : "");
}

static int get_int(const cJSON *obj, const char *key, int fallback)
{
    const cJSON *v = cJSON_GetObjectItem(obj, key);
    return cJSON_IsNumber(v) ? (int)v->valuedouble : fallback;
}

static bool get_bool(const cJSON *obj, const char *key)
{
    return cJSON_IsTrue(cJSON_GetObjectItem(obj, key));
}

static float get_float(const cJSON *obj, const char *key)
{
    const cJSON *v = cJSON_GetObjectItem(obj, key);
    return cJSON_IsNumber(v) ? (float)v->valuedouble : 0.0f;
}

static const char *phase_title(void)
{
    const char *s = st.job_state, *p = st.job_phase;
    if (st.armed && !strcmp(st.act, "idle")) return "Laser scharf ohne Auftrag!";
    if (!strcmp(s, "homing")) return "Referenzfahrt …";
    if (!strcmp(s, "probing")) return "Abtasten …";
    if (!strcmp(s, "running")) {
        if (!strcmp(p, "focusing")) return "Fokus rechnen …";
        if (!strcmp(p, "finishing")) return "Letzte Bahnen …";
        if (!strcmp(p, "parking")) return "Parken …";
        return "Auftrag läuft";
    }
    if (!strcmp(s, "complete")) return "Fertig";
    if (!strcmp(s, "aborted")) return "Abgebrochen";
    if (!strcmp(s, "error")) return "Fehler";
    if (!strcmp(st.act, "framing")) return "Rahmenfahrt";
    return "Bereit";
}

static void chip(int i, bool on, lv_color_t color, const char *on_text, const char *off_text)
{
    lv_obj_set_style_bg_color(chip_dot[i], on ? color : C_OFF, 0);
    lv_label_set_text(chip_val[i], on ? on_text : off_text);
}

void ui_on_status(const cJSON *m)
{
    last_status_us = esp_timer_get_time();
    lv_obj_add_flag(offline, LV_OBJ_FLAG_HIDDEN);
    pill_set(pill_pi, true, C_OK, false);
    st.conn = get_bool(m, "conn");
    st.homed = get_bool(m, "homed");
    st.latched = get_bool(m, "latched");
    st.armed = get_bool(m, "armed");
    st.supply = get_bool(m, "supply");
    st.exhaust = get_bool(m, "exhaust");
    st.lights = get_bool(m, "lights");
    st.clear = get_bool(m, "clear");
    st.valid = get_bool(m, "valid");
    copy_str(st.owner, sizeof(st.owner), m, "owner");
    copy_str(st.act, sizeof(st.act), m, "act");
    copy_str(st.fault, sizeof(st.fault), m, "fault");
    copy_str(st.placed, sizeof(st.placed), m, "placed");
    copy_str(st.time, sizeof(st.time), m, "time");
    copy_str(st.queue, sizeof(st.queue), m, "queue");
    st.elapsed = get_int(m, "elapsed", -1);
    st.remain = get_int(m, "remain", -1);
    st.power = get_int(m, "power", -1);
    st.feed = get_int(m, "feed", -1);
    st.bright = get_int(m, "bright", -1);
    const cJSON *dim = cJSON_GetObjectItem(m, "dim");
    st.dim = cJSON_IsTrue(dim) ? 1 : cJSON_IsFalse(dim) ? 0 : -1;
    st.fpow = get_float(m, "fpow");
    st.qn = get_int(m, "qn", 0);
    st.ev = get_int(m, "ev", 0);
    st.evp = get_int(m, "evp", 0);
    st.soff = get_int(m, "soff", -1);
    copy_str(st.mat, sizeof(st.mat), m, "mat");
    st.mat_mm = get_float(m, "mat_mm");
    const cJSON *pos = cJSON_GetObjectItem(m, "pos");
    st.has_pos = cJSON_IsArray(pos) && cJSON_GetArraySize(pos) == 3;
    for (int i = 0; st.has_pos && i < 3; i++) {
        st.pos[i] = (float)cJSON_GetArrayItem(pos, i)->valuedouble;
    }
    const cJSON *job = cJSON_GetObjectItem(m, "job");
    copy_str(st.job_file, sizeof(st.job_file), job, "file");
    copy_str(st.job_state, sizeof(st.job_state), job, "state");
    copy_str(st.job_phase, sizeof(st.job_phase), job, "phase");
    copy_str(st.job_error, sizeof(st.job_error), job, "error");
    st.line = get_int(job, "line", 0);
    st.total = get_int(job, "total", 0);
    const cJSON *probe = cJSON_GetObjectItem(job, "probe");
    st.probe_done = cJSON_IsArray(probe) ? (int)cJSON_GetArrayItem(probe, 0)->valuedouble : 0;
    st.probe_total = cJSON_IsArray(probe) ? (int)cJSON_GetArrayItem(probe, 1)->valuedouble : 0;

    // top bar
    lv_label_set_text(lbl_time, st.time[0] ? st.time : "--:--");
    pill_set(pill_skr, st.conn, C_OK, false);
    pill_set(pill_laser, st.armed, C_ACCENT, true);
    pill_set(pill_air, st.exhaust, C_INFO, false);
    pill_set(pill_light, st.lights, C_OK, false);

    // status screen
    bool active = job_active();
    lv_label_set_text(lbl_title, phase_title());
    lv_obj_set_style_text_color(lbl_title, (st.armed && !strcmp(st.act, "idle")) || !strcmp(st.job_state, "error")
                                ? C_STOP : C_INK, 0);
    int pct = 0;
    if (!strcmp(st.job_state, "complete")) {
        pct = 100;
    } else if (!strcmp(st.job_state, "probing") && st.probe_total) {
        pct = 0;
    } else if (st.total) {
        pct = st.line * 100 / st.total;
    }
    lv_arc_set_value(arc, pct);
    lv_label_set_text_fmt(lbl_pct, "%d%%", pct);
    char t1[16], t2[16];
    if (!strcmp(st.job_state, "probing") && st.probe_total) {
        lv_label_set_text_fmt(lbl_rest, "Punkt %d von %d", st.probe_done, st.probe_total);
    } else if (active && st.remain >= 0) {
        fmt_time(t1, sizeof(t1), st.remain);
        lv_label_set_text_fmt(lbl_rest, "noch %s", t1);
    } else {
        lv_label_set_text(lbl_rest, active ? "Restzeit wird geschätzt" : "");
    }
    lv_label_set_text(lbl_file, st.job_file[0] ? st.job_file : "Kein Auftrag");
    if (st.elapsed >= 0) {
        fmt_time(t2, sizeof(t2), st.elapsed);
        lv_label_set_text_fmt(lbl_info1, "Laufzeit %s · Zeile %d/%d", t2, st.line, st.total);
    } else {
        lv_label_set_text(lbl_info1, st.total ? "" : "Unter „Auftrag“ eine Datei wählen");
    }
    if (!st.job_error[0] && st.qn > 0) {
        lv_label_set_text_fmt(lbl_info2, "Warteschlange: noch %d", st.qn);
    } else {
        lv_label_set_text(lbl_info2, st.job_error);
    }
    lv_obj_set_style_text_color(lbl_info2, !strcmp(st.job_state, "error") ? C_STOP : C_MUTE, 0);

    for (int i = 0; i < 3; i++) {
        if (st.has_pos) {
            char v[16];
            snprintf(v, sizeof(v), "%.2f", st.pos[i]);   // lv_snprintf has no floats
            lv_label_set_text(lbl_pos[i], v);
        } else {
            lv_label_set_text(lbl_pos[i], "---");
        }
    }
    if (st.power >= 0) {
        lv_label_set_text_fmt(lbl_power, "%d %%", st.power);
        lv_bar_set_value(bar_power, st.power, LV_ANIM_ON);
    } else {
        lv_label_set_text(lbl_power, "--");
        lv_bar_set_value(bar_power, 0, LV_ANIM_OFF);
    }
    if (st.feed >= 0) {
        lv_label_set_text_fmt(lbl_feed, "%d mm/min", st.feed);
        lv_bar_set_value(bar_feed, st.feed, LV_ANIM_ON);
    } else {
        lv_label_set_text(lbl_feed, "--");
        lv_bar_set_value(bar_feed, 0, LV_ANIM_OFF);
    }
    chip(0, st.armed, C_ACCENT, "An", "Aus");
    chip(1, st.supply, C_OK, "An", "Aus");
    chip(2, st.exhaust, C_INFO, "An", "Aus");
    chip(3, st.homed, C_OK, "OK", "Fehlt");

    // move screen
    if (st.has_pos) {
        char v[40];
        snprintf(v, sizeof(v), "X %.2f · Y %.2f", st.pos[0], st.pos[1]);
        lv_label_set_text(lbl_move_pos, v);
        snprintf(v, sizeof(v), "%.2f", st.pos[2]);
        lv_label_set_text(lbl_z, v);
    }
    bool can_move = st.conn && !st.latched && !strcmp(st.act, "idle") && owner_free();
    for (int i = 0; i < n_move_keys; i++) {
        enable(move_keys[i], can_move && st.valid && st.homed);
    }
    enable(key_home, can_move && st.valid);
    if (!st.conn) {
        lv_label_set_text(lbl_move_hint, "Steuerung nicht verbunden");
    } else if (!st.valid) {
        lv_label_set_text(lbl_move_hint, "Mechanik nicht freigegeben");
    } else if (strcmp(st.act, "idle") != 0) {
        lv_label_set_text(lbl_move_hint, "Maschine arbeitet");
    } else if (!owner_free()) {
        lv_label_set_text_fmt(lbl_move_hint, "Belegt durch %s", st.owner);
    } else if (!st.homed) {
        lv_label_set_text(lbl_move_hint, "Erst Referenzfahrt: Mitte antippen");
    } else {
        lv_label_set_text(lbl_move_hint, "Mitte = Referenzfahrt");
    }
    lv_obj_set_style_text_color(lbl_move_hint, can_move && st.valid && st.homed ? C_MUTE : C_ACCENT2, 0);

    // light and exhaust: the Pi refuses them while somebody else holds the machine
    lv_obj_t *accessories[4] = {key_light, key_air, key_cam_light, key_cam_air};
    for (int i = 0; i < 4; i++) {
        enable(accessories[i], can_move);
        mark(accessories[i], i % 2 ? st.exhaust : st.lights);
    }
    lv_label_set_text(lv_obj_get_child(key_light, 1), st.lights ? "An" : "Aus");
    lv_label_set_text(lv_obj_get_child(key_air, 1), st.exhaust ? "An" : "Aus");
    int level = -1;
    for (int i = 0; i < 5; i++) {
        enable(level_btn[i], can_move);
        if (st.lights && st.bright == light_levels[i]) {
            level = i;
        }
    }
    seg_mark(level_btn, 5, level);
    show(lv_obj_get_parent(level_btn[0]), st.dim != 0);
    show(lbl_no_dim, st.dim == 0);
    int off = -1;
    for (int i = 0; i < 5; i++) {
        if (st.soff == off_minutes[i]) {
            off = i;
        }
    }
    seg_mark(off_btn, 5, off);

    // material
    if (st.mat[0]) {
        char v[110];
        snprintf(v, sizeof(v), "%s · %g mm", st.mat, st.mat_mm);
        lv_label_set_text(lbl_key_mat, v);
    } else {
        lv_label_set_text(lbl_key_mat, "Material wählen");
    }
    mark(key_mat, !st.mat[0]);
    enable(key_mat, can_move);

    // events: new ones show in an open list, a new problem as a dot on the rail
    if (screen == SCR_SYSTEM && sys_tab == TAB_EVENTS) {
        if (st.ev != shown_events) {
            shown_events = st.ev;
            link_request("events");
        }
        seen_problem = st.evp;
    }
    show(nav_dot, st.evp != seen_problem);

    // side column and jobs
    enable(btn_pause, !strcmp(st.queue, "running"));
    enable(btn_resume, can_move && st.valid && (!strcmp(st.queue, "paused") || !strcmp(st.queue, "stopped")));
    enable(btn_abort, strcmp(st.act, "idle") != 0);
    enable(btn_frame_job, can_move && selected[0] && st.homed && st.valid);
    enable(key_cam_frame, can_move && st.homed && st.valid);
    enable(btn_start, can_move && selected[0] && st.valid && st.mat[0]);
    enable(key_panel_update, can_move);

    // a go that was asked for another situation does not count any more
    if (popup && popup_go && !can_move) {
        popup_close();
    }
    if (dark && machine_busy()) {
        screen_tick(true);
    }

    if (st.latched) {
        lv_obj_clear_flag(latch_box, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(latch_box);
        if (st.fault[0]) {
            lv_label_set_text_fmt(lbl_latch, "%s\n\n1. SKR zurücksetzen (Reset-Taste oder 24 V kurz aus).\n"
                                  "2. Hier quittieren.\n3. Danach neu referenzieren.", st.fault);
        }
    } else {
        lv_obj_add_flag(latch_box, LV_OBJ_FLAG_HIDDEN);
    }
}

void ui_on_result(const cJSON *m)
{
    const char *msg = cJSON_GetStringValue(cJSON_GetObjectItem(m, "msg"));
    const char *op = cJSON_GetStringValue(cJSON_GetObjectItem(m, "op"));
    bool ok = get_bool(m, "ok");
    if (op && !strcmp(op, "camera")) {
        if (screen == SCR_CAMERA && !cam_dsc.data) {
            lv_label_set_text(cam_hint, msg ? msg : "Kein Kamerabild");
        }
        return;
    }
    if (op && !strcmp(op, "jog")) {
        jog_wait_us = 0;
        if (ok) {
            return;                   // the position shows it; no toast for every step
        }
    }
    if (msg && msg[0]) {
        show_toast(msg, !ok);
    }
}

void ui_on_jobs(const cJSON *m)
{
    lv_obj_clean(job_list);
    const cJSON *files = cJSON_GetObjectItem(m, "files");
    int n = cJSON_GetArraySize(files);
    if (n == 0) {
        label(job_list, &font_ui14, C_MUTE, 0, 0, "Keine Aufträge auf dem Pi");
        return;
    }
    // names live as long as the buttons: one buffer per list
    static char names[60][NAME_MAX_BYTES];
    bool still_there = false;
    for (int i = 0; i < n && i < 60; i++) {
        const cJSON *f = cJSON_GetArrayItem(files, i);
        snprintf(names[i], sizeof(names[i]), "%s", cJSON_GetStringValue(cJSON_GetObjectItem(f, "name")));
        lv_obj_t *b = lv_btn_create(job_list);
        lv_obj_remove_style_all(b);
        lv_obj_set_size(b, 268, 52);
        lv_obj_set_style_radius(b, 12, 0);
        lv_obj_set_style_bg_color(b, C_SOFT, 0);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(b, C_LINE, 0);
        lv_obj_set_style_border_width(b, 1, 0);
        lv_obj_set_style_bg_color(b, C_INK, LV_STATE_CHECKED);
        lv_obj_set_style_text_color(b, lv_color_white(), LV_STATE_CHECKED);
        lv_obj_set_style_text_color(b, C_INK, 0);
        lv_obj_t *ic = lv_label_create(b);
        lv_obj_set_style_text_font(ic, &font_icon20, 0);
        lv_label_set_text(ic, I_FILE);
        lv_obj_set_pos(ic, 14, 15);
        lv_obj_t *t = lv_label_create(b);
        lv_obj_set_style_text_font(t, &font_ui14, 0);
        lv_obj_set_size(t, 160, 18);
        lv_label_set_long_mode(t, LV_LABEL_LONG_DOT);
        lv_label_set_text(t, names[i]);
        lv_obj_set_pos(t, 44, 17);
        lv_obj_t *kb = lv_label_create(b);
        lv_obj_set_style_text_font(kb, &font_ui11, 0);
        lv_label_set_text_fmt(kb, "%d KB", get_int(f, "kb", 0));
        lv_obj_align(kb, LV_ALIGN_RIGHT_MID, -12, 0);
        lv_obj_set_user_data(b, (void *)(intptr_t)get_int(f, "kb", 0));
        lv_obj_add_event_cb(b, act_job_select, LV_EVENT_CLICKED, names[i]);
        if (!strcmp(names[i], selected)) {
            lv_obj_add_state(b, LV_STATE_CHECKED);
            still_there = true;
        }
    }
    if (selected[0] && !still_there) {    // deleted on another device: nothing left to start
        selected[0] = 0;
        lv_label_set_text(lbl_sel, "–");
        lv_label_set_text(lbl_sel_info, "Datei links antippen");
    }
}

void ui_on_materials(const cJSON *m)
{
    lv_obj_clean(mat_list);
    const cJSON *items = cJSON_GetObjectItem(m, "items");
    int n = cJSON_GetArraySize(items);
    if (n == 0) {
        label(mat_list, &font_ui14, C_MUTE, 0, 0, "Keine Materialien auf dem Pi");
    }
    for (int i = 0; i < n && i < 40; i++) {
        const cJSON *f = cJSON_GetArrayItem(items, i);
        copy_str(mat_names[i], sizeof(mat_names[i]), f, "name");
        float mm = get_float(f, "mm");
        snprintf(mat_thick[i], sizeof(mat_thick[i]), "%g", mm);
        lv_obj_t *b = lv_btn_create(mat_list);
        lv_obj_remove_style_all(b);
        lv_obj_set_size(b, 552, 62);
        lv_obj_set_style_radius(b, 12, 0);
        lv_obj_set_style_bg_color(b, C_SOFT, 0);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(b, C_LINE, 0);
        lv_obj_set_style_border_width(b, 1, 0);
        lv_obj_add_style(b, &s_key_on, LV_STATE_CHECKED);
        lv_obj_t *name = label(b, &font_ui16, C_INK, 16, 10, mat_names[i]);
        lv_obj_set_width(name, 410);
        lv_label_set_long_mode(name, LV_LABEL_LONG_DOT);
        char line[80];
        const char *proc = cJSON_GetStringValue(cJSON_GetObjectItem(f, "proc"));
        snprintf(line, sizeof(line), "%s%s", proc ? proc : "", get_bool(f, "start") ? " · Startwert, erst testen" : "");
        label(b, &font_ui14, C_MUTE, 16, 34, line);
        char v[16];
        snprintf(v, sizeof(v), "%g mm", mm);
        lv_obj_t *thick = label(b, &font_mono16, C_INK, 0, 0, v);
        lv_obj_align(thick, LV_ALIGN_RIGHT_MID, -16, 0);
        lv_obj_add_event_cb(b, act_mat_pick, LV_EVENT_CLICKED, (void *)(intptr_t)i);
        mark(b, !strcmp(mat_names[i], st.mat) && mm == st.mat_mm);
    }
}

void ui_on_events(const cJSON *m)
{
    lv_obj_clean(event_list);
    const cJSON *items = cJSON_GetObjectItem(m, "items");
    int n = cJSON_GetArraySize(items);
    if (n == 0) {
        label(event_list, &font_ui14, C_MUTE, 0, 0, "Noch keine Ereignisse");
    }
    for (int i = 0; i < n; i++) {
        const cJSON *f = cJSON_GetArrayItem(items, i);
        const char *level = cJSON_GetStringValue(cJSON_GetObjectItem(f, "level"));
        const char *when = cJSON_GetStringValue(cJSON_GetObjectItem(f, "time"));
        const char *text = cJSON_GetStringValue(cJSON_GetObjectItem(f, "text"));
        lv_color_t color = !level ? C_OFF : !strcmp(level, "err") ? C_STOP : !strcmp(level, "warn") ? C_ACCENT
                         : !strcmp(level, "ok") ? C_OK : C_INFO;
        lv_obj_t *row = box(event_list, 0, 0, 552, LV_SIZE_CONTENT);
        lv_obj_set_style_pad_ver(row, 9, 0);
        lv_obj_set_style_border_side(row, LV_BORDER_SIDE_BOTTOM, 0);
        lv_obj_set_style_border_color(row, C_LINE, 0);
        lv_obj_set_style_border_width(row, 1, 0);
        lv_obj_t *dot = box(row, 4, 5, 10, 10);
        lv_obj_set_style_radius(dot, 5, 0);
        lv_obj_set_style_bg_color(dot, color, 0);
        lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
        label(row, &font_mono16, C_TEXT2, 24, 0, when ? when : "");
        lv_obj_t *t = label(row, &font_ui14, C_INK, 90, 1, text ? text : "");
        lv_obj_set_width(t, 456);
        lv_label_set_long_mode(t, LV_LABEL_LONG_WRAP);
    }
}

static void set_text_from(lv_obj_t *l, const cJSON *m, const char *key)
{
    const char *v = cJSON_GetStringValue(cJSON_GetObjectItem(m, key));
    lv_label_set_text(l, v && v[0] ? v : "–");
}

void ui_on_system(const cJSON *m)
{
    set_text_from(info_ip, m, "http");
    set_text_from(info_host, m, "host");
    set_text_from(info_pi, m, "pi");
    const char *wifi = cJSON_GetStringValue(cJSON_GetObjectItem(m, "wifi"));
    int signal = get_int(m, "signal", -1);
    if (wifi && wifi[0] && signal >= 0) {
        lv_label_set_text_fmt(info_wifi, "%s · %d %%", wifi, signal);
    } else if (wifi && wifi[0]) {
        lv_label_set_text(info_wifi, wifi);
    } else {
        lv_label_set_text(info_wifi, "Nicht im WLAN");
    }
    const char *skr = cJSON_GetStringValue(cJSON_GetObjectItem(m, "skr"));
    lv_label_set_text_fmt(info_skr, "%s%s%s", get_bool(m, "skr_conn") ? "Verbunden" : "Nicht verbunden",
                          skr && skr[0] ? " · " : "", skr ? skr : "");
    const char *panel_new = cJSON_GetStringValue(cJSON_GetObjectItem(m, "panel_new"));
    const char *panel_state = cJSON_GetStringValue(cJSON_GetObjectItem(m, "panel_state"));
    const char *panel_msg = cJSON_GetStringValue(cJSON_GetObjectItem(m, "panel_msg"));
    const char *skr_new = cJSON_GetStringValue(cJSON_GetObjectItem(m, "skr_new"));
    int errors = get_int(m, "serial_err", 0);
    char text[320] = "";
    size_t used = 0;
    if (panel_state && !strcmp(panel_state, "error") && panel_msg) {
        used += snprintf(text + used, sizeof(text) - used, "%s\n", panel_msg);
    }
    if (panel_new && panel_new[0]) {
        used += snprintf(text + used, sizeof(text) - used, "Panel-Update auf %s liegt bereit%s\n", panel_new,
                         get_bool(m, "auto") ? " und kommt im Leerlauf von selbst." : ".");
    }
    if (skr_new && skr_new[0] && used < sizeof(text)) {
        used += snprintf(text + used, sizeof(text) - used, "Neue Steuerungs-Firmware %s: in der Web-Oberfläche "
                         "installieren.\n", skr_new);
    }
    if (errors > 0 && used < sizeof(text)) {
        used += snprintf(text + used, sizeof(text) - used, "%d serielle Fehler seit dem Start des Pi.\n", errors);
    }
    lv_label_set_text(lbl_update, used ? text : "Keine Updates offen, keine Fehler.");
    show(key_panel_update, panel_new && panel_new[0]);
}

void ui_on_image(const uint16_t *rgb565, int w, int h)
{
    cam_dsc.header.always_zero = 0;
    cam_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
    cam_dsc.header.w = w;
    cam_dsc.header.h = h;
    cam_dsc.data_size = w * h * 2;
    cam_dsc.data = (const uint8_t *)rgb565;
    lv_img_set_src(cam_img, &cam_dsc);
    lv_img_cache_invalidate_src(&cam_dsc);
    // fit 640x480 into 442x372 (zoom 256 = 1:1); "Zoom" shows the middle at 1:1
    int fit = 442 * 256 / w;
    if (372 * 256 / h < fit) {
        fit = 372 * 256 / h;
    }
    lv_img_set_zoom(cam_img, cam_zoom ? 256 : fit);
    lv_obj_center(cam_img);
    lv_obj_clear_flag(cam_img, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(cam_hint, LV_OBJ_FLAG_HIDDEN);
    lv_obj_clear_flag(cam_badge, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(cam_badge);
    cam_last_us = esp_timer_get_time();
}
