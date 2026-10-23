# SCons/PlatformIO pre-build script. Embeds exact *repository* SHA when available.
# This is built into the HMI firmware, so we never guess what version is running.
Import("env")
import os
import subprocess

try:
    root=os.path.abspath(os.path.join(env["PROJECT_DIR"],"..",".."))
    sha=subprocess.check_output(["git","rev-parse","HEAD"],
        cwd=root,text=True,timeout=8).strip()
    if len(sha)!=40 or any(c not in "0123456789abcdef" for c in sha):
        sha="unknown"
except (OSError,subprocess.CalledProcessError,subprocess.TimeoutExpired):
    sha="unknown"
env.Append(CPPDEFINES=[("LUMACUT_SOURCE_SHA",'\\"'+sha+'\\"')])
print("LumaCut firmware source SHA:",sha)
