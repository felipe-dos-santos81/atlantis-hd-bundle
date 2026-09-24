from scumm.archive import Archive
from scumm.room import extract_background


def test_room1_metadata(archive_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    assert (bg.width, bg.height) == (320, 200)
    assert bg.palette.transparent_index == 5
    assert bg.palette.colors[0] == (0, 0, 0)
    assert bg.palette.colors[1] == (0, 0, 171)
    assert bg.anomalies == []
    assert bg.source_offset > 0


def test_room1_pixels_vary(archive_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    assert len(bg.pixels) == 320 * 200
    assert len(set(bg.pixels)) > 1


def test_all_96_backgrounds_decode(archive_path):
    a = Archive.load(archive_path)
    idx = a.room_index()
    assert len(idx) == 96
    for room in idx:
        bg = extract_background(a, room)
        assert bg.width >= 8 and bg.height > 0
        assert len(bg.pixels) == bg.width * bg.height
        assert bg.anomalies == [], f"room {room} anomalies: {bg.anomalies}"
