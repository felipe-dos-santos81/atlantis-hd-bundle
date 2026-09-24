from scumm.smap import BitReader, Settings, settings


def test_bit_reader_is_lsb_first():
    r = BitReader(bytes([0b10110010]), 0)
    assert [r.read_bit() for _ in range(8)] == [0, 1, 0, 0, 1, 1, 0, 1]


def test_bit_reader_read_bits():
    r = BitReader(bytes([0b00000101]), 0)
    assert r.read_bits(3) == 0b101


def test_settings_ranges():
    assert settings(0x01) == Settings(0, "horizontal", False, 8)
    assert settings(0x18) == Settings(1, "horizontal", False, 4)
    assert settings(0x1C) == Settings(1, "horizontal", False, 8)
    assert settings(0x22) == Settings(1, "vertical", True, 4)
    assert settings(0x44) == Settings(2, "horizontal", False, 8)
    assert settings(0x54) == Settings(2, "horizontal", True, 3)
    assert settings(0x05) is None


from scumm.smap import Anomaly, decode_smap, read_codec_ids


def _pack_bits(bits):
    out = bytearray()
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        byte = 0
        for j, b in enumerate(chunk):
            byte |= (b & 1) << j
        out.append(byte)
    return bytes(out)


def _strip(codec_id, first_color, bits, height):
    body = bytes([codec_id, first_color]) + _pack_bits(bits)
    table = (12).to_bytes(4, "little")
    payload = table + body
    return b"SMAP" + (8 + len(payload)).to_bytes(4, "big") + payload


def test_method1_constant_colour():
    data = _strip(0x1C, 10, [0] * 15, height=2)
    pixels, anomalies = decode_smap(data, 0, width=8, height=2)
    assert list(pixels) == [10] * 16
    assert anomalies == []


def test_method1_new_colour():
    bits = [1, 0] + [0, 0, 1, 0, 1, 0, 0, 0] + [0] * 14
    data = _strip(0x1C, 10, bits, height=2)
    pixels, anomalies = decode_smap(data, 0, width=8, height=2)
    assert pixels[0] == 10
    assert pixels[1] == 20
    assert anomalies == []


def test_method2_rle_run():
    bits = [1, 1, 0, 0, 1] + [1, 1, 1, 0, 0, 0, 0, 0]
    data = _strip(0x44, 7, bits, height=1)
    pixels, anomalies = decode_smap(data, 0, width=8, height=1)
    assert list(pixels) == [7] * 8
    assert anomalies == []


def test_unknown_codec_records_anomaly():
    data = _strip(0x05, 3, [0] * 16, height=2)
    pixels, anomalies = decode_smap(data, 0, width=8, height=2)
    assert anomalies == [Anomaly(0, 0x05, "unknown-codec")]


def test_vertical_direction_places_columns():
    data = _strip(0x0E, 9, [0] * 15, height=2)
    pixels, _ = decode_smap(data, 0, width=8, height=2)
    assert list(pixels) == [9] * 16


def test_read_codec_ids_room1(archive_path):
    from scumm.archive import Archive
    a = Archive.load(archive_path)
    room = a.room_index()[1]
    rmim = a.find(room, "RMIM")
    im00 = a.find(rmim.start, "IM00")
    smap = a.find(im00.start, "SMAP")
    ids = read_codec_ids(a.data, smap.start, width=320)
    from collections import Counter
    assert Counter(ids) == Counter({0x1C: 28, 0x44: 12})
