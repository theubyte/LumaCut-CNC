"""sim/out/*.raw (800x480 RGB565) -> PNG, standard library only."""
import struct, sys, zlib
from pathlib import Path

for raw in sorted(Path(sys.argv[1] if len(sys.argv) > 1 else "out").glob("*.raw")):
    data = raw.read_bytes()
    rows = bytearray()
    for y in range(480):
        rows.append(0)
        for x in range(800):
            v = data[(y * 800 + x) * 2] | data[(y * 800 + x) * 2 + 1] << 8
            r, g, b = v >> 11, (v >> 5) & 63, v & 31
            rows += bytes(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 800, 480, 8, 2, 0, 0, 0)) \
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b"")
    raw.with_suffix(".png").write_bytes(png)
    print(raw.with_suffix(".png"))
