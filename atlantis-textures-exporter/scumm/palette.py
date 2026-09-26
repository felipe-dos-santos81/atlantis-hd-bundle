from __future__ import annotations

from dataclasses import dataclass

from .archive import Archive, le16


@dataclass(frozen=True)
class Palette:
    colors: tuple[tuple[int, int, int], ...]
    transparent_index: int | None
    cycles: tuple[tuple[int, int, int], ...]


def parse_clut(data: bytes, off: int) -> tuple[tuple[int, int, int], ...]:
    p = off + 8
    return tuple(
        (data[p + 3 * i], data[p + 3 * i + 1], data[p + 3 * i + 2])
        for i in range(256)
    )


def parse_trns(data: bytes, off: int) -> int:
    return le16(data, off + 8)


def parse_cycl(data: bytes, off: int, size: int) -> tuple[tuple[int, int, int], ...]:
    p = off + 8
    end = off + size
    cycles = []
    while p < end and data[p] != 0:
        if p + 9 > end:
            break
        freq = int.from_bytes(data[p + 3:p + 5], "big")
        start = data[p + 7]
        stop = data[p + 8]
        cycles.append((start, stop, freq))
        p += 9
    return tuple(cycles)


def read_palette(archive: Archive, room_off: int) -> Palette:
    clut = archive.find(room_off, "CLUT")
    if clut is None:
        raise ValueError("room has no CLUT")
    colors = parse_clut(archive.data, clut.start)
    trns = archive.find(room_off, "TRNS")
    transparent = parse_trns(archive.data, trns.start) if trns else None
    cycl = archive.find(room_off, "CYCL")
    cycles = parse_cycl(archive.data, cycl.start, cycl.size) if cycl else ()
    return Palette(colors, transparent, cycles)
