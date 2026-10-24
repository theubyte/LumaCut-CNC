#!/usr/bin/env python3
"""Pinned grblHAL STM32F1xx build for BTT SKR Mini MZ v1.0.

Experimental image: DO NOT FLASH without validating pinout, PWM, switches,
hardware interlocks and bootloader. This script does not communicate with
the controller or flash anything.
"""
from __future__ import annotations
import argparse, configparser, hashlib, pathlib, re, shutil, subprocess, tempfile

HERE=pathlib.Path(__file__).resolve().parent
CFG=configparser.ConfigParser(interpolation=None)
CFG.read(HERE/"platformio.ini")
SHA=CFG["upstream"]["commit"]
UPSTREAM=CFG["upstream"]["repository"]
ENV=CFG["build"]["environment"]
OUT=HERE/".pio"/"build"/ENV

def run(*args, cwd=None, timeout=600):
    print("+"," ".join(map(str,args)),flush=True)
    subprocess.run(list(args),cwd=cwd,check=True,timeout=timeout)

def change(text,old,new):
    if text.count(old)!=1:
        raise RuntimeError("Upstream grblHAL board map changed unexpectedly: "+old)
    return text.replace(old,new)

def patch(text):
    # The E3 V2 shares SKR MZ X/Y/Z STEP/DIR/ENABLE, limits,
    # PC10/PC11 Trinamic UART and USB PA14 pull-up gate.
    # MZ PC8/PC9 are HEATER FETs: must NOT be mapped as generic outputs.
    text=change(text,
        '#define BOARD_NAME "BTT SKR MINI E3 V2.0"',
        '#define BOARD_NAME "LumaCut SKR Mini MZ v1.0 EXPERIMENTAL"')
    text=change(text,
        '#define BOARD_NAME "BTT SKR MINI E3 V2.0 4-axis"',
        '#define BOARD_NAME "LumaCut SKR Mini MZ v1.0 4-axis EXPERIMENTAL"')
    text=change(text,
        '#define AUXOUTPUT1_PORT         GPIOC // Spindle direction\n#define AUXOUTPUT1_PIN          6',
        '// MZ: do not assign PC6 twice (used as fan/coolant)')
    text=change(text,
        '#define AUXOUTPUT3_PORT         GPIOC // Coolant flood\n#define AUXOUTPUT3_PIN          8',
        '#define AUXOUTPUT3_PORT         GPIOC // MZ FAN0, flood\n#define AUXOUTPUT3_PIN          6')
    text=change(text,
        '#define AUXOUTPUT4_PORT         GPIOC // Coolant mist\n#define AUXOUTPUT4_PIN          9',
        '// PC9 HEATER MOSFET disabled. No AUXOUTPUT4 definition.')
    for expected in ('#define AUXOUTPUT0_PIN          1',
                     '#define AUXOUTPUT2_PIN          7',
                     '#define AUXINPUT2_PIN           14',
                     '#define Z_LIMIT_PIN             2'):
        if expected not in text: raise RuntimeError("Required pin not found: "+expected)
    return text

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--bridge",action="store_true",help="Main grblHAL UART1 to Waveshare, no SKR USB")
    args=parser.parse_args()
    env=("lumacut_skr_mz_hmi_uart" if args.bridge else ENV)
    out=HERE/".pio"/"build"/env
    if UPSTREAM!="https://github.com/grblHAL/STM32F1xx.git":
        raise RuntimeError("Unexpected upstream repository")
    if not re.fullmatch(r"[a-f0-9]{40}",SHA):
        raise RuntimeError("Commit must be full SHA")
    with tempfile.TemporaryDirectory(prefix="lumacut-skr-") as temp:
        root=pathlib.Path(temp)/"upstream"
        run("git","clone","--no-checkout",UPSTREAM,str(root),timeout=360)
        run("git","checkout","--detach",SHA,cwd=root)
        run("git","submodule","update","--init","--recursive",cwd=root,timeout=700)
        actual=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
        if actual!=SHA: raise RuntimeError("Incorrect source revision")
        header=root/"boards/btt_skr_mini_e3_2.0_map.h"
        header.write_text(patch(header.read_text()))
        # LumaCut-specific Z-clearance occurs INSIDE grblHAL's system homing
        # state, between Z and XY cycles, not afterward in the HMI.
        # Armed only after the operator has calibrated Z and explicitly sets
        # the existing GRBL pull-off $27 to the opt-in sentinel 2.5 mm.
        limits=root/"grbl"/"machine_limits.c"
        source=limits.read_text()
        source=change(source,
            'return grbl.home_machine(cycle, auto_square) ? Status_OK : Status_Unhandled;',
            'return grbl.home_machine(cycle, auto_square) ? Status_OK : Status_Unhandled;')
        marker='// Homes the specified cycle axes, sets the machine position'
        if source.count(marker)!=1:
            raise RuntimeError("grblHAL homing function marker has changed")
        routine="""#ifdef LUMACUT_SAFE_Z20
// Runs as a bounded system motion *after* Z homing and BEFORE XY homing.
// Runtime opt-in uses documented GRBL $27 pull-off value 2.5mm; never
// automatically retreat 20mm with uncalibrated steps/mm.
FLASHMEM status_code_t limits_lumacut_z_clearance (void)
{
    const float target = 20.0f;
    const float current_pulloff = homing_pulloff.values[Z_AXIS];
    if(fabsf(settings.homing.pulloff - 2.5f) > 0.001f)
        return Status_OK; // Not yet commissioned for this machine.
    if(!(sys.homed.mask & bit(Z_AXIS)) ||
       settings.axis[Z_AXIS].max_travel > -21.0f ||
       current_pulloff >= target ||
       current_pulloff < 0.5f ||
       settings.axis[Z_AXIS].steps_per_mm <= 0.0f)
        return Status_TravelExceeded; // Refuse XY homing if Z travel unknown.
    coord_data_t distance = {0};
    distance.values[Z_AXIS] = target - current_pulloff;
    return limits_pull_off((axes_signals_t){.z = On}, &distance, 1.0f)
        ? Status_OK : Status_Unhandled;
}
#endif

"""
        source=source.replace(marker,routine+marker)
        # The original generic pull-off feed is based on X rate.
        # For the special Z retreat, constrain it to the real Z max rate.
        rate='plan_data.feed_rate = settings.axis[0].homing_seek_rate * sqrtf(n_axis);'
        if source.count(rate)!=1:
            raise RuntimeError("grblHAL pull-off feed layout has changed")
        source=source.replace(rate,rate+"""
#ifdef LUMACUT_SAFE_Z20
    if(axis.mask == bit(Z_AXIS))
        plan_data.feed_rate = fminf(600.0f, settings.axis[Z_AXIS].max_rate);
#endif
""")
        limits.write_text(source)
        motion=root/"grbl"/"motion_control.c"
        body=motion.read_text()
        location='if((homed_status = limits_go_home(cycle)) != Status_OK)\\n                        break;'
        if body.count(location)!=1:
            raise RuntimeError("grblHAL complete homing loop changed")
        body=body.replace(location,location+"""
#ifdef LUMACUT_SAFE_Z20
                    // Standard grblHAL: cycle[0]=Z, cycle[1]=XY.
                    // Perform extra Z clearance before any XY movement,
                    // but not for standalone $HZ material probing.
                    if(idx == 0 && cycle.mask == bit(Z_AXIS)) {
                        if((homed_status = limits_lumacut_z_clearance()) != Status_OK)
                            break;
                    }
#endif
""")
        prototype='#include "machine_limits.h"'
        if prototype not in body:
            raise RuntimeError("machine_limits include absent")
        body=body.replace(prototype,prototype+"""
#ifdef LUMACUT_SAFE_Z20
extern status_code_t limits_lumacut_z_clearance (void);
#endif
""",1)
        motion.write_text(body)
        # Use upstream's USB CDC environment and verified 28K bootloader
        # linker memory layout, not the unoffset FLASH linker script.
        with (root/"platformio.ini").open("a") as h:
            h.write("\n[env:"+env+"]\n")
            h.write("extends = env:"+("BTT_SKR_MINI_E3_V20" if args.bridge else "BTT_SKR_MINI_E3_V20_USB")+"\n")
            h.write("board_build.ldscript = STM32F103RCTX_BL28K_FLASH.ld\n")
            src_env="BTT_SKR_MINI_E3_V20" if args.bridge else "BTT_SKR_MINI_E3_V20_USB"
            h.write("build_flags = "+chr(36)+"{env:"+src_env+".build_flags}\n")
            if args.bridge:
                h.write("  -D SERIAL_PORT=1\n")
            h.write("  -D COOLANT_ENABLE=1\n")
            h.write("  -D SPINDLE0_ENABLE=SPINDLE_PWM0_NODIR\n")
            # UART0 (PA9 TX, PA10 RX) serves the grblHAL serial keypad.
            # USART3 (PC10/PC11) remains reserved for TMC2209.
            if not args.bridge:
                h.write("  -D KEYPAD_ENABLE=2\n")
            # Actual LumaCut machine: exactly ONE stepper per XYZ axis.
            # No Y_GANGED and no M3/E extruder motor in use.
            # Only ONE mechanical Z switch is installed, wired as Z limit (PC2).
            # It must NOT be assumed to be an independent PC14 probe, and
            # normal XYZ homing cannot run without X and Y switches.
            # Probe operations on the shared switch require a separate,
            # carefully validated control mode before they can be enabled.
            h.write("  -D PROBE_ENABLE=0\n")
            # Default stepper holding after homing. Existing EEPROM/NVS values
            # retain precedence: HMI also sets $1=255 on successful home.
            # Original Atomstack A5 Pro belt mechanics use 80 steps/mm
            # when the Trinamic driver microstepping matches the OEM setup.
            # Factory defaults only: existing SKR EEPROM values take precedence.
            h.write("  -D DEFAULT_X_STEPS_PER_MM=80.0f\\n")
            h.write("  -D DEFAULT_Y_STEPS_PER_MM=80.0f\\n")
            # Z is a different Anet A8 motor + lead screw. Its lead and the
            # running microstep resolution are not yet established; guessing
            # $102 could cause unsafe 20mm retreats or overtravel.
            # Keep the upstream Z steps/mm default pending measured correction.
            h.write("  -D DEFAULT_STEPPER_IDLE_LOCK_TIME=255\n")
            # Three real XYZ switches: enable default homing and optional
            # single-Z homing for workpiece contact using the same head switch.
            # These are factory defaults; SKR nonvolatile $22 takes precedence.
            h.write("  -D DEFAULT_HOMING_ENABLE=1\n")
            h.write("  -D DEFAULT_HOMING_SINGLE_AXIS_COMMANDS=1\n")            h.write("  -D LUMACUT_SAFE_Z20=1\\n")

        run("pio","run","-e",env,cwd=root,timeout=1500)
        generated=root/".pio"/"build"/env
        out.mkdir(parents=True,exist_ok=True)
        for name in ("firmware.bin","firmware.elf"):
            source=generated/name
            if not source.is_file():
                raise RuntimeError("Missing compiled artifact: "+name)
            dest=out/name
            shutil.copyfile(source,dest)
            print(str(dest),"sha256",hashlib.sha256(dest.read_bytes()).hexdigest())
    print("BUILD COMPLETE - EXPERIMENTAL / NOT APPROVED FOR FLASHING")

if __name__=="__main__":
    main()
