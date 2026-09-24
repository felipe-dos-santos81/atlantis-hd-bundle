from __future__ import annotations

import struct
from dataclasses import dataclass

from .archive import le32


@dataclass(frozen=True)
class Anomaly:
    strip: int
    codec_id: int
    reason: str


@dataclass(frozen=True)
class Settings:
    method: int
    direction: str
    transparent: bool
    palette_bits: int


_TABLE = (
    (0x01, 0x01, 0, "horizontal", False),
    (0x0E, 0x12, 1, "vertical", False),
    (0x18, 0x1C, 1, "horizontal", False),
    (0x22, 0x26, 1, "vertical", True),
    (0x2C, 0x30, 1, "horizontal", True),
    (0x40, 0x44, 2, "horizontal", False),
    (0x54, 0x58, 2, "horizontal", True),
    (0x68, 0x6C, 2, "horizontal", True),
    (0x7C, 0x80, 2, "horizontal", False),
)
_PAR_SUB = {
    0x0E: 0x0A, 0x18: 0x14, 0x22: 0x1E, 0x2C: 0x28,
    0x40: 0x3C, 0x54: 0x51, 0x68: 0x64, 0x7C: 0x78,
}


def settings(codec_id: int) -> Settings | None:
    for lo, hi, method, direction, transparent in _TABLE:
        if lo <= codec_id <= hi:
            if method == 0:
                return Settings(0, direction, transparent, 8)
            return Settings(method, direction, transparent, codec_id - _PAR_SUB[lo])
    return None


class BitReader:
    __slots__ = ("data", "pos", "cur", "nbits")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.cur = 0
        self.nbits = 0

    def read_bit(self) -> int:
        if self.nbits == 0:
            if self.pos >= len(self.data):
                raise EOFError("bitstream exhausted")
            self.cur = self.data[self.pos]
            self.pos += 1
            self.nbits = 8
        bit = self.cur & 1
        self.cur >>= 1
        self.nbits -= 1
        return bit

    def read_bits(self, n: int) -> int:
        value = 0
        for i in range(n):
            value |= self.read_bit() << i
        return value


def read_codec_ids(data: bytes, smap_off: int, width: int) -> list[int]:
    n = (width + 7) // 8
    offsets = struct.unpack_from("<" + "I" * n, data, smap_off + 8)
    return [data[smap_off + o] for o in offsets]


def _clamp_index(color: int, anomalies, strip_index, codec_id) -> int:
    if color < 0:
        anomalies.append(Anomaly(strip_index, codec_id, "index-underflow"))
        return 0
    if color > 255:
        anomalies.append(Anomaly(strip_index, codec_id, "index-overflow"))
        return 255
    return color


def _decode_strip(data, base, height, st, anomalies, strip_index) -> bytearray:
    n = 8 * height
    out = bytearray(n)
    first = data[base + 1]
    out[0] = first
    color = first
    reader = BitReader(data, base + 2)
    i = 1

    if st.method == 0:
        while i < n:
            try:
                out[i] = reader.read_bits(8)
            except EOFError:
                anomalies.append(Anomaly(strip_index, 0x01, "eof"))
                out[i:] = bytes([out[i - 1]]) * (n - i)
                break
            i += 1
        return out

    if st.method == 1:
        inc = -1
        while i < n:
            try:
                if reader.read_bit():
                    if not reader.read_bit():
                        color = reader.read_bits(st.palette_bits)
                        inc = -1
                    else:
                        if reader.read_bit():
                            inc = -inc
                        color = _clamp_index(color + inc, anomalies, strip_index, 0)
            except EOFError:
                anomalies.append(Anomaly(strip_index, 0, "eof"))
                out[i:] = bytes([out[i - 1]]) * (n - i)
                break
            out[i] = color
            i += 1
        return out

    while i < n:
        run = 1
        try:
            if reader.read_bit():
                if not reader.read_bit():
                    color = reader.read_bits(st.palette_bits)
                else:
                    value = reader.read_bits(3)
                    inc = value - 4
                    if inc:
                        color = _clamp_index(color + inc, anomalies, strip_index, 0)
                    else:
                        run = reader.read_bits(8)
        except EOFError:
            anomalies.append(Anomaly(strip_index, 0, "eof"))
            out[i:] = bytes([out[i - 1]]) * (n - i)
            break
        if run < 1:
            anomalies.append(Anomaly(strip_index, 0, "zero-run"))
            run = 1
        if i + run > n:
            anomalies.append(Anomaly(strip_index, 0, "run-overshoot"))
            run = n - i
        out[i:i + run] = bytes([color]) * run
        i += run
    return out


def decode_smap(data: bytes, smap_off: int, width: int, height: int):
    n_strips = (width + 7) // 8
    offsets = struct.unpack_from("<" + "I" * n_strips, data, smap_off + 8)
    pixels = bytearray(width * height)
    anomalies: list[Anomaly] = []
    for s in range(n_strips):
        base = smap_off + offsets[s]
        codec_id = data[base]
        st = settings(codec_id)
        if st is None:
            anomalies.append(Anomaly(s, codec_id, "unknown-codec"))
            continue
        strip = _decode_strip(data, base, height, st, anomalies, s)
        x0 = s * 8
        if st.direction == "horizontal":
            for i in range(8 * height):
                x = x0 + (i % 8)
                if x < width:
                    pixels[(i // 8) * width + x] = strip[i]
        else:
            for i in range(8 * height):
                x = x0 + (i // height)
                if x < width:
                    pixels[(i % height) * width + x] = strip[i]
    return pixels, anomalies
