#!/usr/bin/env bash
# Erzeugt src/fonts/*.c mit lv_font_conv 1.5.2 (npm) aus Inter 4.0, JetBrains Mono 2.304
# und LVGLs FontAwesome 5 (managed_components/lvgl__lvgl/scripts/built_in_font).
# Aufruf: tools/gen_fonts.sh <Ordner mit Inter-*.ttf und JetBrainsMono-SemiBold.ttf>
set -euo pipefail
TTF=${1:?Ordner mit den TTF-Dateien}
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT=$HERE/src/fonts
FA=$HERE/managed_components/lvgl__lvgl/scripts/built_in_font/FontAwesome5-Solid+Brands+Regular.woff
TEXT="0x20-0x7E,0xA0-0xFF,0x2013,0x2022,0x2026,0x2212,0x201C,0x201E,0x2192"
ICONS="0xF015,0xF04C,0xF04B,0xF00D,0xF030,0xF077,0xF078,0xF053,0xF054,0xF021,0xF00E,0xF15B,0xF3FD,0xF0B2,0xF0EB,0xF071,0xF019,0xF065,0xF72E,0xF3C5"
mkdir -p "$OUT"
conv(){ lv_font_conv --no-compress --format lvgl --bpp 4 --lv-include lvgl.h "$@"; }
conv --size 11 --font "$TTF/Inter-SemiBold.ttf" -r "$TEXT" -o "$OUT/font_ui11.c"
conv --size 14 --font "$TTF/Inter-SemiBold.ttf" -r "$TEXT" -o "$OUT/font_ui14.c"
conv --size 16 --font "$TTF/Inter-SemiBold.ttf" -r "$TEXT" -o "$OUT/font_ui16.c"
conv --size 20 --font "$TTF/Inter-Bold.ttf" -r "$TEXT" -o "$OUT/font_ui20.c"
conv --size 56 --font "$TTF/Inter-ExtraBold.ttf" -r "0x20,0x25,0x30-0x39" -o "$OUT/font_big56.c"
conv --size 16 --font "$TTF/JetBrainsMono-SemiBold.ttf" -r "0x20-0x7E,0xB7" -o "$OUT/font_mono16.c"
conv --size 26 --font "$TTF/JetBrainsMono-SemiBold.ttf" -r "0x20-0x7E" -o "$OUT/font_mono26.c"
conv --size 20 --font "$FA" -r "$ICONS" -o "$OUT/font_icon20.c"
conv --size 26 --font "$FA" -r "$ICONS" -o "$OUT/font_icon26.c"
