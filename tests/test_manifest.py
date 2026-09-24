import json

from PIL import Image

from scumm.manifest import build_manifest, contact_sheet, sha256_file, write_manifest, write_report


def test_sha256_and_manifest_roundtrip(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    assert sha256_file(f) == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"

    man = build_manifest("/game", [{"room": 1, "file": "indexed/rooms/room_001.png"}], anomalies=0)
    out = tmp_path / "manifest.json"
    write_manifest(out, man)
    text = out.read_text()
    assert "2026" not in text and "timestamp" not in text
    loaded = json.loads(text)
    assert loaded["summary"]["rooms"] == 1


def test_manifest_is_byte_identical_and_order_independent(tmp_path):
    records = [
        {"room": 2, "file": "indexed/rooms/room_002.png"},
        {"room": 1, "file": "indexed/rooms/room_001.png"},
    ]
    man = build_manifest("/game", records, anomalies=0)
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    write_manifest(a, man)
    write_manifest(b, man)
    assert a.read_bytes() == b.read_bytes()

    reordered = build_manifest("/game", list(reversed(records)), anomalies=0)
    c = tmp_path / "c.json"
    write_manifest(c, reordered)
    assert c.read_bytes() == a.read_bytes()


def test_manifest_expected_is_not_shared(tmp_path):
    man = build_manifest("/game", [], anomalies=0)
    man["summary"]["expected"]["rooms"] = -1
    fresh = build_manifest("/game", [], anomalies=0)
    assert fresh["summary"]["expected"]["rooms"] == 96


def test_contact_sheet(tmp_path):
    a = tmp_path / "a.png"
    Image.new("RGB", (320, 200), (255, 0, 0)).save(a)
    out = tmp_path / "sheet.png"
    contact_sheet([(1, str(a))], out, cols=1)
    img = Image.open(out)
    assert img.size[0] >= 320


def test_write_report(tmp_path):
    man = build_manifest("/game", [], anomalies=2)
    out = tmp_path / "report.md"
    write_report(out, man)
    assert "anomal" in out.read_text().lower()
