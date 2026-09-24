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
