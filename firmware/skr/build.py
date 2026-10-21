#!/usr/bin/env python3
"""Pinned grblHAL STM32F1xx build for BTT SKR Mini MZ v1.0.

Experimental image: DO NOT FLASH without validating pinout, PWM, switches,
hardware interlocks and bootloader. This script does not communicate with
the controller or flash anything.
"""
from __future__ import annotations
import configparser, hashlib, pathlib, re, shutil, subprocess, tempfile

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
        # Use upstream's USB CDC environment and verified 28K bootloader
        # linker memory layout, not the unoffset FLASH linker script.
        with (root/"platformio.ini").open("a") as h:
            h.write("\n[env:"+ENV+"]\n")
            h.write("extends = env:BTT_SKR_MINI_E3_V20_USB\n")
            h.write("board_build.ldscript = STM32F103RCTX_BL28K_FLASH.ld\n")
            h.write("build_flags = "+chr(36)+"{env:BTT_SKR_MINI_E3_V20_USB.build_flags}\n")
            h.write("  -D COOLANT_ENABLE=1\n")
            h.write("  -D SPINDLE0_ENABLE=SPINDLE_PWM0_NODIR\n")
            # UART0 (PA9 TX, PA10 RX) serves the grblHAL serial keypad.
            # USART3 (PC10/PC11) remains reserved for TMC2209.
            h.write("  -D KEYPAD_ENABLE=2\n")
        run("pio","run","-e",ENV,cwd=root,timeout=1500)
        generated=root/".pio"/"build"/ENV
        OUT.mkdir(parents=True,exist_ok=True)
        for name in ("firmware.bin","firmware.elf"):
            source=generated/name
            if not source.is_file():
                raise RuntimeError("Missing compiled artifact: "+name)
            dest=OUT/name
            shutil.copyfile(source,dest)
            print(str(dest),"sha256",hashlib.sha256(dest.read_bytes()).hexdigest())
    print("BUILD COMPLETE - EXPERIMENTAL / NOT APPROVED FOR FLASHING")

if __name__=="__main__":
    main()
