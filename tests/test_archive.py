import struct

import pytest

from scumm.archive import Archive, ScummFormatError, be32, le16, le32


def test_int_helpers():
    data = bytes([0x01, 0x02, 0x03, 0x04])
    assert be32(data, 0) == 0x01020304
    assert le16(data, 0) == 0x0201
    assert le32(data, 0) == 0x04030201


def test_load_xors_with_0x69(tmp_path):
    raw = bytes([b ^ 0x69 for b in b"LECF" + b"\x00\x00\x00\x08"])
    p = tmp_path / "ATLANTIS.001"
    p.write_bytes(raw)
    a = Archive.load(p)
    assert a.data[:4] == b"LECF"


def test_block_rejects_bad_size(tmp_path):
    a = Archive(b"LECF\x00\x00\x00\x04")
    with pytest.raises(ScummFormatError):
        a.block(0)


def test_room_index_real(archive_path):
    a = Archive.load(archive_path)
    idx = a.room_index()
    assert len(idx) == 96
    assert sorted(idx) == list(range(1, 34)) + list(range(35, 38)) + list(range(39, 99))
    assert a.tag(idx[1]) == "ROOM"
    assert a.tag(idx[1] - 8) == "LFLF"
