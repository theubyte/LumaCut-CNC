#!/usr/bin/env bash
# Builds and runs the PC preview (needs: pip install ziglang; LVGL and cJSON from a firmware build).
set -euo pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
LV=../managed_components/lvgl__lvgl
CJ=${CJSON:-$HOME/.platformio/packages/framework-espidf/components/json/cJSON}
mkdir -p out
$PY -m ziglang cc -O1 -w -o out/sim.exe -DLV_CONF_SKIP -DLV_LVGL_H_INCLUDE_SIMPLE -DLV_MEM_CUSTOM=1 \
  -Iinclude -I../src -I$LV -I$LV/src -I$CJ \
  sim_main.c ../src/fonts/*.c $CJ/cJSON.c $(find $LV/src -name '*.c')
out/sim.exe
rm -f out/*.png
$PY topng.py out
