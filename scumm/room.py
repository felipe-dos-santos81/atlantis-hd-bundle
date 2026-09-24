from __future__ import annotations

from dataclasses import dataclass

from .archive import Archive, le16
from .palette import Palette, read_palette
from .smap import Anomaly, decode_smap, read_codec_ids


@dataclass
class Background:
    room: int
    width: int
    height: int
    palette: Palette
    pixels: bytearray
    anomalies: list[Anomaly]
    source_offset: int
    codec_ids: tuple[int, ...]


def extract_background(archive: Archive, room_number: int) -> Background:
    room_off = archive.room_index()[room_number]
    rmhd = archive.find(room_off, "RMHD")
    if rmhd is None:
        raise ValueError(f"room {room_number} has no RMHD")
    width = le16(archive.data, rmhd.payload_start)
    height = le16(archive.data, rmhd.payload_start + 2)

    palette = read_palette(archive, room_off)

    rmim = archive.find(room_off, "RMIM")
    if rmim is None:
        raise ValueError(f"room {room_number} has no RMIM")
    im00 = archive.find(rmim.start, "IM00")
    if im00 is None:
        raise ValueError(f"room {room_number} has no IM00")
    smap = archive.find(im00.start, "SMAP")
    if smap is None:
        raise ValueError(f"room {room_number} has no SMAP")

    pixels, anomalies = decode_smap(archive.data, smap.start, width, height)
    codec_ids = tuple(read_codec_ids(archive.data, smap.start, width))
    return Background(room_number, width, height, palette, pixels, anomalies, smap.start, codec_ids)
