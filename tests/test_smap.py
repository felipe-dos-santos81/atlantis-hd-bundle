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
