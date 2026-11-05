#!/usr/bin/env python3
"""Compile the firmware logic for the PC and run the host tests.

The compiler comes from $CC, else gcc, clang or `python -m ziglang cc`.
Nothing from src/hw is compiled: registers stay out of the tests.
"""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "src"
BUILD = HERE / "build"
FLAGS = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Wshadow", "-Werror", "-Wno-date-time",
         "-D_DEFAULT_SOURCE"]


def compiler() -> list[str]:
    if os.environ.get("CC"):
        return os.environ["CC"].split()
    for name in ("gcc", "clang"):
        if shutil.which(name):
            return [name]
    if importlib.util.find_spec("ziglang"):
        return [sys.executable, "-m", "ziglang", "cc"]
    sys.exit("No C compiler: set CC, install gcc or `pip install ziglang`")


def main() -> int:
    BUILD.mkdir(exist_ok=True)
    exe = BUILD / ("host_tests.exe" if os.name == "nt" else "host_tests")
    sources = sorted(SRC.glob("*.c")) + sorted(HERE.glob("*.c"))
    cmd = compiler() + FLAGS + ["-I", str(SRC)] + [str(s) for s in sources] + ["-lm", "-o", str(exe)]
    subprocess.run(cmd, check=True)
    return subprocess.run([str(exe)], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
