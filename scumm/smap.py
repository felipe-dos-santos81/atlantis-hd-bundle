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
