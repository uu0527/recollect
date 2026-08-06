"""生成插件占位图标（纯色 PNG）"""
import struct
import zlib
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent / "icons"


def make_png(path, size, rgb):
    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        c += struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)
        return c

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = b""
    row = bytes(rgb) * size
    for _ in range(size):
        raw += b"\x00" + row
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


if __name__ == "__main__":
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    for s in (16, 48, 128):
        make_png(ICON_DIR / f"icon{s}.png", s, (55, 138, 221))
        print(f"created icon{s}.png")
