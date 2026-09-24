from scumm.archive import Archive
from scumm.palette import parse_clut, parse_cycl, parse_trns, read_palette


def test_parse_clut_synthetic():
    data = b"CLUT" + (776).to_bytes(4, "big") + bytes([0, 0, 0]) + bytes([0, 0, 171]) + bytes(254 * 3)
    colors = parse_clut(data, 0)
    assert len(colors) == 256
    assert colors[0] == (0, 0, 0)
    assert colors[1] == (0, 0, 171)


def test_parse_trns_synthetic():
    data = b"TRNS" + (10).to_bytes(4, "big") + (5).to_bytes(2, "little")
    assert parse_trns(data, 0) == 5


def test_parse_cycl_synthetic():
    payload = bytes([1]) + (0).to_bytes(2, "little") + (100).to_bytes(2, "big") \
        + (0).to_bytes(2, "big") + bytes([2]) + bytes([7]) + bytes([0])
    data = b"CYCL" + (8 + len(payload)).to_bytes(4, "big") + payload
    assert parse_cycl(data, 0, 8 + len(payload)) == ((2, 7, 100),)


def test_read_palette_room1(archive_path):
    a = Archive.load(archive_path)
    off = a.room_index()[1]
    pal = read_palette(a, off)
    assert len(pal.colors) == 256
    assert pal.colors[0] == (0, 0, 0)
    assert pal.colors[1] == (0, 0, 171)
    assert pal.transparent_index == 5
    assert len(pal.cycles) == 1
