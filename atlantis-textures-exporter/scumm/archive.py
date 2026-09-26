from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

XOR_KEY = 0x69


class ScummFormatError(Exception):
    pass


def be32(data: bytes, off: int) -> int:
    return struct.unpack_from(">I", data, off)[0]


def le16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def le32(data: bytes, off: int) -> int:
    return struct.unpack_from("<I", data, off)[0]


@dataclass(frozen=True)
class Block:
    tag: str
    start: int
    size: int

    @property
    def payload_start(self) -> int:
        return self.start + 8

    @property
    def payload_size(self) -> int:
        return self.size - 8

    @property
    def end(self) -> int:
        return self.start + self.size


class Archive:
    def __init__(self, data: bytes):
        self.data = data

    @classmethod
    def load(cls, path) -> "Archive":
        raw = Path(path).read_bytes()
        return cls(bytes(b ^ XOR_KEY for b in raw))

    def tag(self, off: int) -> str:
        return self.data[off:off + 4].decode("latin1")

    def block(self, off: int) -> Block:
        if off + 8 > len(self.data):
            raise ScummFormatError(f"block header past EOF at {off}")
        tag = self.tag(off)
        size = be32(self.data, off + 4)
        if size < 8 or off + size > len(self.data):
            raise ScummFormatError(f"bad block {tag!r} at {off} size={size}")
        return Block(tag, off, size)

    def children(self, off: int) -> Iterator[Block]:
        parent = self.block(off)
        cur = parent.payload_start
        while cur < parent.end:
            child = self.block(cur)
            yield child
            cur = child.end

    def find(self, off: int, tag: str) -> Block | None:
        for child in self.children(off):
            if child.tag == tag:
                return child
        return None

    def room_index(self) -> dict[int, int]:
        lecf = self.block(0)
        if lecf.tag != "LECF":
            raise ScummFormatError(f"expected LECF, got {lecf.tag!r}")
        loff = self.find(0, "LOFF")
        if loff is None:
            raise ScummFormatError("no LOFF block")
        n = self.data[loff.payload_start]
        out: dict[int, int] = {}
        p = loff.payload_start + 1
        for _ in range(n):
            room = self.data[p]
            out[room] = le32(self.data, p + 1)
            p += 5
        return out
