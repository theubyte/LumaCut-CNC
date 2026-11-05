#!/usr/bin/env python3
"""Checks the flash self-copy routine of a built firmware.elf.

ram_copy erases the running program, so one call or jump into flash would crash
with half an image. The routine must sit in RAM and branch only inside itself.
Usage: check_ramfunc.py <arm-none-eabi-objdump> <firmware.elf>
"""
import re
import subprocess
import sys

HEADER = re.compile(r"^([0-9a-f]{8}) <ram_copy>:$")
TARGET = re.compile(r"(?:^|,\s*)([0-9a-f]{6,})\b")
BRANCHES = re.compile(r"^(b|bl|blx|bx|cbz|cbnz|tbb|tbh)$|^b(eq|ne|cs|hs|cc|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)$")


def check(listing: str) -> list[str]:
    lines = listing.splitlines()
    starts = [i for i, text in enumerate(lines) if HEADER.match(text)]
    if len(starts) != 1:
        return ["ram_copy not found exactly once"]
    start = int(HEADER.match(lines[starts[0]]).group(1), 16)
    if not 0x20000000 <= start < 0x20010000:
        return [f"ram_copy at {start:#x} is not in RAM"]
    instructions = []
    for text in lines[starts[0] + 1:]:
        if not text.strip() or re.match(r"^[0-9a-f]{8} <", text):
            break
        parts = text.split("\t")
        if len(parts) >= 3:
            instructions.append((int(parts[0].strip().rstrip(":"), 16), parts[2].strip(),
                                 parts[3].strip() if len(parts) > 3 else "", text.strip()))
    if not instructions:
        return ["ram_copy is empty"]
    end = instructions[-1][0]
    errors = []
    for _, mnemonic, operand, text in instructions:
        base = mnemonic.split(".")[0]
        if not BRANCHES.match(base):
            continue
        if base in ("bl", "blx"):
            errors.append("call: " + text)
            continue
        target = TARGET.search(operand)
        if not target:
            errors.append("indirect branch: " + text)
        elif not start <= int(target.group(1), 16) <= end:
            errors.append("leaves the routine: " + text)
    return errors


def main() -> int:
    listing = subprocess.run([sys.argv[1], "-d", "-j", ".data", sys.argv[2]], check=True,
                             capture_output=True, text=True).stdout
    errors = check(listing)
    for error in errors:
        print("ram_copy:", error)
    if not errors:
        print("ram_copy: in RAM, no branch leaves it")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
