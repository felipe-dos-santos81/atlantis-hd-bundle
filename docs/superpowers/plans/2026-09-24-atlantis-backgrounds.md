# Atlantis Backgrounds Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python tool that extracts all 96 room backgrounds from the
*Fate of Atlantis* SCUMM v5 archive as re-import-safe indexed PNGs, plus a
manifest, contact sheet, and report.

**Architecture:** A small package with one unit per format. `archive.py` turns
the XOR-obfuscated file into a nested block tree; `palette.py` reads the CLUT;
`smap.py` decodes one SCUMM strip-compressed bitmap into palette indices;
`room.py` combines them for a background; `export.py` writes PNGs;
`manifest.py` produces the machine index and contact sheet; `extract.py` is the
CLI. Each unit is independently testable.

**Tech Stack:** Python 3.12, Pillow (runtime), pytest (tests).

## Scope

This plan delivers **M0 (foundation) + M1 (backgrounds)** only. It produces a
working CLI that extracts 96 backgrounds.

Deferred to separate plans, each with one format question to spike first:

- **M2 objects** — spike: the 16-byte `IMHD` field layout. Verified so far:
  `OBIM → IMHD → IMxx → SMAP`, object images tagged `IM01+`, names in `OBNA`.
- **M3 costumes** — spike: the classic v5 `COST` cel layout (no `AKOS`/`AKCD`).
- **M4 UI** — spike: provenance audit (`CHAR` ×5 and inventory `OBIM`s in-data
  vs engine-hardcoded cursors).

## Global Constraints

- Python 3.12. Runtime dependency: **Pillow only**. Tests: **pytest**.
- Output PNGs are indexed **`P` mode**, exact 256-entry CLUT, **native
  dimensions, no scaling**.
- Deterministic output: sorted JSON keys, no timestamps; two runs on the same
  input must be byte-identical.
- Recoverable decode problems are recorded as `Anomaly` values, **never
  raised**. Only bad files/XOR are fatal.
- Game files are read **in place** from the `.app`; never copied, never
  committed. The `.app` is code-signed and is never modified.
- Extracted art is LucasArts/Disney copyright: **personal use only, do not
  redistribute.**
- Tool license stays permissive (no ScummVM GPL code is ported in this plan).
- Room numbers are authoritative keys; names are optional and `null` in M1.
- Verified constants: 96 rooms, numbers `1–33, 35–37, 39–98`. Room 1: w=320,
  h=200, `TRNS`=5, `CLUT[0]=(0,0,0)`, `CLUT[1]=(0,0,171)`, 40 strips, codec ids
  `{0x1C: 28, 0x44: 12}`. `LOFF` offset points at the `ROOM` block.
- Pre-flight prototype result: this exact algorithm decodes all 96 rooms with
  **zero anomalies**; codec ids seen across the game are `0x0E,0x10,0x11,0x12,
  0x1A,0x1B,0x1C,0x22,0x42,0x43,0x44`, all inside the dispatch table. So
  `anomalies == 0` is a safe assertion. Rooms 89/90/98 are genuinely tiny
  (16×200, 16×200, 8×200) — real data, not a decode fault.

---

## File Structure

```
atlantis-textures/
  pyproject.toml                 pytest config
  .gitignore                     ignore .venv/, out/, __pycache__/
  README.md                      purpose + legal notice
  scumm/
    __init__.py
    archive.py                   XOR 0x69, Block, Archive, room_index()
    palette.py                   Palette, parse_clut/trns/cycl
    smap.py                      BitReader, Settings, Anomaly, decode_smap
    room.py                      Background, extract_background, room_codec_ids
    export.py                    save_indexed_png, save_palette_swatch
    manifest.py                  build_manifest, contact_sheet, write_report
  extract.py                     CLI
  tests/
    conftest.py                  game-dir discovery, real-archive fixture
    test_archive.py
    test_palette.py
    test_smap.py
    test_room.py
    test_export.py
    test_end_to_end.py
```

---

### Task 0: Project scaffolding

**Files:**
- Create: `.gitignore`, `pyproject.toml`, `README.md`, `scumm/__init__.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `tests/conftest.py::GAME_DIR` (str) and pytest fixture `archive_path` (str), used by all later tests.

- [ ] **Step 1: Create the virtualenv and install tools**

```bash
cd ~/code/mine/atlantis-textures
python3 -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet pillow pytest
.venv/bin/python -c "import PIL, pytest; print('ok', PIL.__version__)"
```
Expected: prints `ok <version>`.

- [ ] **Step 2: Write `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
out/
.superpowers/
```

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

- [ ] **Step 4: Write `README.md`**

```markdown
# atlantis-textures

Extracts visual assets from *Indiana Jones and the Fate of Atlantis* (SCUMM v5)
for AI regeneration. Output is re-import-safe indexed PNGs.

## Legal

The extracted and regenerated art is LucasArts/Disney copyright. Personal use
only. Do not redistribute the extracted art or derived work.

## Usage

    .venv/bin/python extract.py --game "<game dir>" --out out

## Status

M1: room backgrounds.
```

- [ ] **Step 5: Write `scumm/__init__.py`**

```python
```

- [ ] **Step 6: Write `tests/conftest.py`**

```python
import os
from pathlib import Path

import pytest

DEFAULT_GAME_DIR = (
    "/Users/felipe.dos.santos/Documents/"
    "Indiana Jones\u00ae and the Fate of Atlantis\u2122.app/"
    "Contents/Resources/game/game"
)

GAME_DIR = os.environ.get("ATLANTIS_GAME_DIR", DEFAULT_GAME_DIR)
ARCHIVE_001 = str(Path(GAME_DIR) / "ATLANTIS.001")


@pytest.fixture(scope="session")
def archive_path():
    if not Path(ARCHIVE_001).is_file():
        pytest.skip(f"game archive not found: {ARCHIVE_001}")
    return ARCHIVE_001
```

- [ ] **Step 7: Commit**

```bash
git add .gitignore pyproject.toml README.md scumm/__init__.py tests/conftest.py
git commit -m "chore: scaffold atlantis-textures project"
```

---

### Task 1: Archive reader (`archive.py`)

**Files:**
- Create: `scumm/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `XOR_KEY: int = 0x69`
  - `class ScummFormatError(Exception)`
  - `@dataclass Block(tag: str, start: int, size: int)` with properties `payload_start`, `payload_size`, `end`
  - `class Archive(data: bytes)` with `load(path) -> Archive`, `block(off) -> Block`, `children(off) -> Iterator[Block]`, `find(off, tag) -> Block | None`, `room_index() -> dict[int, int]`
  - `be32(data, off) -> int`, `le16(data, off) -> int`, `le32(data, off) -> int`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_archive.py
import struct

import pytest

from scumm.archive import Archive, ScummFormatError, be32, le16, le32


def test_int_helpers():
    data = bytes([0x01, 0x02, 0x03, 0x04])
    assert be32(data, 0) == 0x01020304
    assert le16(data, 0) == 0x0201
    assert le32(data, 0) == 0x04030201


def test_load_xors_with_0x69(tmp_path):
    # b"LECF" XOR 0x69
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
    # LOFF offset points at the ROOM block
    assert a.tag(idx[1]) == "ROOM"
    assert a.tag(idx[1] - 8) == "LFLF"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.archive'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/archive.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_archive.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/archive.py tests/test_archive.py
git commit -m "feat: SCUMM archive block reader and room index"
```

---

### Task 2: Palette reader (`palette.py`)

**Files:**
- Create: `scumm/palette.py`
- Test: `tests/test_palette.py`

**Interfaces:**
- Consumes: `scumm.archive.le16`, `Archive`.
- Produces:
  - `@dataclass Palette(colors: tuple[tuple[int,int,int], ...], transparent_index: int | None, cycles: tuple[tuple[int,int,int], ...])`
  - `parse_clut(data, off) -> tuple[tuple[int,int,int], ...]` (256 entries)
  - `parse_trns(data, off) -> int`
  - `parse_cycl(data, off, size) -> tuple[tuple[int,int,int], ...]` (`(start, end, freq)`)
  - `read_palette(archive, room_off) -> Palette`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_palette.py
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
    # idx=1, unk=2 bytes, freq=2 bytes BE, flags=2 bytes BE, start, end, then 0 terminator
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_palette.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.palette'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/palette.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_palette.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/palette.py tests/test_palette.py
git commit -m "feat: SCUMM palette, transparency, and colour-cycle reader"
```

---

### Task 3: SMAP decoder — bit reader, dispatch, method 1

**Files:**
- Create: `scumm/smap.py`
- Test: `tests/test_smap.py`

**Interfaces:**
- Consumes: `scumm.archive.le32`.
- Produces:
  - `@dataclass(frozen=True) Anomaly(strip: int, codec_id: int, reason: str)`
  - `@dataclass(frozen=True) Settings(method: int, direction: str, transparent: bool, palette_bits: int)`
  - `class BitReader(data, pos=0)` with `read_bit() -> int`, `read_bits(n) -> int`
  - `settings(codec_id) -> Settings | None`
  - `decode_smap(data, smap_off, width, height) -> tuple[bytearray, list[Anomaly]]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smap.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_smap.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.smap'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/smap.py
from __future__ import annotations

import struct
from dataclasses import dataclass

from .archive import le32


@dataclass(frozen=True)
class Anomaly:
    strip: int
    codec_id: int
    reason: str


@dataclass(frozen=True)
class Settings:
    method: int          # 0 = uncompressed, 1 = method 1, 2 = method 2
    direction: str       # "horizontal" | "vertical"
    transparent: bool
    palette_bits: int


# (lo, hi, method, direction, transparent)
_TABLE = (
    (0x01, 0x01, 0, "horizontal", False),
    (0x0E, 0x12, 1, "vertical", False),
    (0x18, 0x1C, 1, "horizontal", False),
    (0x22, 0x26, 1, "vertical", True),
    (0x2C, 0x30, 1, "horizontal", True),
    (0x40, 0x44, 2, "horizontal", False),
    (0x54, 0x58, 2, "horizontal", True),
    (0x68, 0x6C, 2, "horizontal", True),
    (0x7C, 0x80, 2, "horizontal", False),
)
_PAR_SUB = {
    0x0E: 0x0A, 0x18: 0x14, 0x22: 0x1E, 0x2C: 0x28,
    0x40: 0x3C, 0x54: 0x51, 0x68: 0x64, 0x7C: 0x78,
}


def settings(codec_id: int) -> Settings | None:
    for lo, hi, method, direction, transparent in _TABLE:
        if lo <= codec_id <= hi:
            if method == 0:
                return Settings(0, direction, transparent, 8)
            return Settings(method, direction, transparent, codec_id - _PAR_SUB[lo])
    return None


class BitReader:
    __slots__ = ("data", "pos", "cur", "nbits")

    def __init__(self, data: bytes, pos: int = 0):
        self.data = data
        self.pos = pos
        self.cur = 0
        self.nbits = 0

    def read_bit(self) -> int:
        if self.nbits == 0:
            if self.pos >= len(self.data):
                raise EOFError("bitstream exhausted")
            self.cur = self.data[self.pos]
            self.pos += 1
            self.nbits = 8
        bit = self.cur & 1
        self.cur >>= 1
        self.nbits -= 1
        return bit

    def read_bits(self, n: int) -> int:
        value = 0
        for i in range(n):
            value |= self.read_bit() << i
        return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_smap.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/smap.py tests/test_smap.py
git commit -m "feat: SMAP bit reader and codec dispatch table"
```

---

### Task 4: SMAP decoder — methods 1 and 2, uncompressed, anomalies

**Files:**
- Modify: `scumm/smap.py`
- Test: `tests/test_smap.py`

**Interfaces:**
- Consumes: everything from Task 3.
- Produces:
  - `decode_smap(data, smap_off, width, height) -> tuple[bytearray, list[Anomaly]]`
  - `_decode_strip(data, base, height, st, anomalies, strip_index) -> bytearray`
  - `read_codec_ids(data, smap_off, width) -> list[int]` (used by tests and `room.py`)

- [ ] **Step 1: Write the failing test (append to `tests/test_smap.py`)**

```python
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
    table = (12).to_bytes(4, "little")  # single strip offset = 8 header + 4 table
    payload = table + body
    return b"SMAP" + (8 + len(payload)).to_bytes(4, "big") + payload


def test_method1_constant_colour():
    # codec 0x1C = method 1, horizontal, opaque, 8-bit palette
    # height 2 -> 16 pixels; pixel 0 = 10; 15 zero bits keep colour 10
    data = _strip(0x1C, 10, [0] * 15, height=2)
    pixels, anomalies = decode_smap(data, 0, width=8, height=2)
    assert list(pixels) == [10] * 16
    assert anomalies == []


def test_method1_new_colour():
    # pixel0=10; then bit 1, bit 0 -> read 8-bit colour 20 for pixel1; rest 0 bits
    bits = [1, 0] + [0, 0, 1, 0, 1, 0, 0, 0] + [0] * 14  # 20 == 0b00010100
    data = _strip(0x1C, 10, bits, height=2)
    pixels, anomalies = decode_smap(data, 0, width=8, height=2)
    assert pixels[0] == 10
    assert pixels[1] == 20
    assert anomalies == []


def test_method2_rle_run():
    # codec 0x44 = method 2, horizontal, opaque, 8-bit palette; height 1 -> 8 px
    # pixel0=7; then bit1,bit1, v=4 (3 bits LSB: 0,0,1), run=7 (8 bits)
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
    # codec 0x0E = method 1, vertical; height 2, width 8 -> 16 px
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_smap.py -v`
Expected: FAIL with `ImportError: cannot import name 'decode_smap'`

- [ ] **Step 3: Write minimal implementation (append to `scumm/smap.py`)**

```python
def read_codec_ids(data: bytes, smap_off: int, width: int) -> list[int]:
    n = (width + 7) // 8
    offsets = struct.unpack_from("<" + "I" * n, data, smap_off + 8)
    return [data[smap_off + o] for o in offsets]


def _clamp_index(color: int, anomalies, strip_index, codec_id) -> int:
    if color < 0:
        anomalies.append(Anomaly(strip_index, codec_id, "index-underflow"))
        return 0
    if color > 255:
        anomalies.append(Anomaly(strip_index, codec_id, "index-overflow"))
        return 255
    return color


def _decode_strip(data, base, height, st, anomalies, strip_index) -> bytearray:
    n = 8 * height
    out = bytearray(n)
    first = data[base + 1]
    out[0] = first
    color = first
    reader = BitReader(data, base + 2)
    i = 1

    if st.method == 0:
        while i < n:
            try:
                out[i] = reader.read_bits(8)
            except EOFError:
                anomalies.append(Anomaly(strip_index, 0x01, "eof"))
                out[i:] = bytes([out[i - 1]]) * (n - i)
                break
            i += 1
        return out

    if st.method == 1:
        inc = -1
        while i < n:
            try:
                if reader.read_bit():
                    if not reader.read_bit():
                        color = reader.read_bits(st.palette_bits)
                        inc = -1
                    else:
                        if reader.read_bit():
                            inc = -inc
                        color = _clamp_index(color + inc, anomalies, strip_index, 0)
            except EOFError:
                anomalies.append(Anomaly(strip_index, 0, "eof"))
                out[i:] = bytes([out[i - 1]]) * (n - i)
                break
            out[i] = color
            i += 1
        return out

    # method 2
    while i < n:
        run = 1
        try:
            if reader.read_bit():
                if not reader.read_bit():
                    color = reader.read_bits(st.palette_bits)
                else:
                    value = reader.read_bits(3)
                    inc = value - 4
                    if inc:
                        color = _clamp_index(color + inc, anomalies, strip_index, 0)
                    else:
                        run = reader.read_bits(8)
        except EOFError:
            anomalies.append(Anomaly(strip_index, 0, "eof"))
            out[i:] = bytes([out[i - 1]]) * (n - i)
            break
        if run < 1:
            anomalies.append(Anomaly(strip_index, 0, "zero-run"))
            run = 1
        if i + run > n:
            anomalies.append(Anomaly(strip_index, 0, "run-overshoot"))
            run = n - i
        out[i:i + run] = bytes([color]) * run
        i += run
    return out


def decode_smap(data: bytes, smap_off: int, width: int, height: int):
    n_strips = (width + 7) // 8
    offsets = struct.unpack_from("<" + "I" * n_strips, data, smap_off + 8)
    pixels = bytearray(width * height)
    anomalies: list[Anomaly] = []
    for s in range(n_strips):
        base = smap_off + offsets[s]
        codec_id = data[base]
        st = settings(codec_id)
        if st is None:
            anomalies.append(Anomaly(s, codec_id, "unknown-codec"))
            continue
        strip = _decode_strip(data, base, height, st, anomalies, s)
        x0 = s * 8
        if st.direction == "horizontal":
            for i in range(8 * height):
                x = x0 + (i % 8)
                if x < width:
                    pixels[(i // 8) * width + x] = strip[i]
        else:
            for i in range(8 * height):
                x = x0 + (i // height)
                if x < width:
                    pixels[(i % height) * width + x] = strip[i]
    return pixels, anomalies
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_smap.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/smap.py tests/test_smap.py
git commit -m "feat: SMAP strip decoder (methods 1 and 2, uncompressed, anomalies)"
```

---

### Task 5: Room background extraction (`room.py`)

**Files:**
- Create: `scumm/room.py`
- Test: `tests/test_room.py`

**Interfaces:**
- Consumes: `Archive`, `Palette`/`read_palette`, `decode_smap`.
- Produces:
  - `@dataclass Background(room: int, width: int, height: int, palette: Palette, pixels: bytearray, anomalies: list, source_offset: int)`
  - `extract_background(archive, room_number) -> Background`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_room.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_room.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.room'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/room.py
from __future__ import annotations

from dataclasses import dataclass

from .archive import Archive, le16
from .palette import Palette, read_palette
from .smap import Anomaly, decode_smap


@dataclass
class Background:
    room: int
    width: int
    height: int
    palette: Palette
    pixels: bytearray
    anomalies: list[Anomaly]
    source_offset: int


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
    return Background(room_number, width, height, palette, pixels, anomalies, smap.start)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_room.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/room.py tests/test_room.py
git commit -m "feat: room background extraction"
```

---

### Task 6: PNG export (`export.py`)

**Files:**
- Create: `scumm/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Palette`, Pillow.
- Produces:
  - `save_indexed_png(path, pixels, width, height, palette) -> None`
  - `save_palette_swatch(path, palette, scale=16) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_export.py
from PIL import Image

from scumm.archive import Archive
from scumm.export import save_indexed_png, save_palette_swatch
from scumm.room import extract_background


def test_save_indexed_png_roundtrip(tmp_path):
    colors = tuple((i, i, i) for i in range(256))
    from scumm.palette import Palette
    pal = Palette(colors, 5, ())
    pixels = bytearray([0, 1, 2, 3])
    out = tmp_path / "r.png"
    save_indexed_png(out, pixels, 2, 2, pal)
    img = Image.open(out)
    assert img.mode == "P"
    assert img.size == (2, 2)
    assert list(img.getdata()) == [0, 1, 2, 3]
    assert img.getpalette()[:3] == [0, 0, 0]


def test_save_background_is_indexed(archive_path, tmp_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    out = tmp_path / "room1.png"
    save_indexed_png(out, bg.pixels, bg.width, bg.height, bg.palette)
    img = Image.open(out)
    assert img.mode == "P"
    assert img.size == (320, 200)
    assert img.getpalette()[3:6] == [0, 0, 171]


def test_save_palette_swatch(archive_path, tmp_path):
    a = Archive.load(archive_path)
    bg = extract_background(a, 1)
    out = tmp_path / "pal.png"
    save_palette_swatch(out, bg.palette, scale=4)
    img = Image.open(out)
    assert img.mode == "RGB"
    assert img.size == (64, 64)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.export'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/export.py
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .palette import Palette


def save_indexed_png(path, pixels, width: int, height: int, palette: Palette) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img = Image.frombytes("P", (width, height), bytes(pixels))
    flat = [c for rgb in palette.colors for c in rgb]
    img.putpalette(flat)
    img.save(path, format="PNG")


def save_palette_swatch(path, palette: Palette, scale: int = 16) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (16, 16))
    img.putdata(list(palette.colors))
    img = img.resize((16 * scale, 16 * scale), Image.NEAREST)
    img.save(path, format="PNG")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_export.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/export.py tests/test_export.py
git commit -m "feat: indexed PNG and palette swatch export"
```

---

### Task 7: Manifest, contact sheet, report (`manifest.py`)

**Files:**
- Create: `scumm/manifest.py`
- Test: `tests/test_manifest.py`

**Interfaces:**
- Consumes: `Background`, Pillow.
- Produces:
  - `sha256_file(path) -> str`
  - `build_manifest(game_dir, records: list[dict], anomalies: int) -> dict`
  - `write_manifest(path, manifest) -> None` (sorted keys, no timestamps)
  - `contact_sheet(paths: list[tuple[int, str]], out_path, cell=(320, 200), cols=8) -> None`
  - `write_report(path, manifest) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_manifest.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scumm.manifest'`

- [ ] **Step 3: Write minimal implementation**

```python
# scumm/manifest.py
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

EXPECTED = {"rooms": 96, "backgrounds": 96, "objects": 1372, "costumes": 240, "fonts": 5}


def sha256_file(path) -> str:
    h = hashlib.sha256()
    h.update(Path(path).read_bytes())
    return h.hexdigest()


def build_manifest(game_dir: str, records: list[dict], anomalies: int) -> dict:
    return {
        "game": {"dir": str(game_dir)},
        "assets": records,
        "summary": {
            "rooms": len(records),
            "backgrounds": len(records),
            "objects": 0,
            "costumes": 0,
            "fonts": 0,
            "anomalies": anomalies,
            "expected": EXPECTED,
        },
    }


def write_manifest(path, manifest: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def contact_sheet(items: list[tuple[int, str]], out_path, cell=(320, 200), cols: int = 8) -> None:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    rows = (len(items) + cols - 1) // cols if items else 1
    sheet = Image.new("RGB", (cell[0] * cols, cell[1] * rows), (0, 0, 0))
    for i, (_room, file) in enumerate(items):
        img = Image.open(file).convert("RGB").resize(cell, Image.NEAREST)
        sheet.paste(img, ((i % cols) * cell[0], (i // cols) * cell[1]))
    sheet.save(out_path, format="PNG")


def write_report(path, manifest: dict) -> None:
    s = manifest["summary"]
    lines = [
        "# Atlantis texture extraction report",
        "",
        f"Rooms/backgrounds: {s['rooms']}",
        f"Anomalies: {s['anomalies']}",
        "",
        "## Expected vs found",
        "",
    ]
    for key in ("rooms", "backgrounds", "objects", "costumes", "fonts"):
        lines.append(f"- {key}: found {s.get(key, 0)} / expected {s['expected'][key]}")
    lines.append("")
    if s["anomalies"]:
        lines.append("Unexplained anomalies present; triage before considering complete.")
    else:
        lines.append("No anomalies.")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_manifest.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scumm/manifest.py tests/test_manifest.py
git commit -m "feat: manifest, contact sheet, and report writers"
```

---

### Task 8: CLI and end-to-end verification (`extract.py`)

**Files:**
- Create: `extract.py`
- Test: `tests/test_end_to_end.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv=None) -> int`; CLI `--game DIR --out DIR`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_end_to_end.py
import hashlib
import json
from pathlib import Path

from PIL import Image

import extract


def _run(tmp_path):
    out = tmp_path / "out"
    rc = extract.main(["--game", str(Path(extract.__file__).parent / "tests" / "__none__"), "--out", str(out)])
    return rc, out


def test_cli_end_to_end(archive_path, tmp_path):
    game_dir = str(Path(archive_path).parent)
    out = tmp_path / "out"
    rc = extract.main(["--game", game_dir, "--out", str(out)])
    assert rc == 0

    pngs = sorted((out / "indexed" / "rooms").glob("*.png"))
    assert len(pngs) == 96

    img = Image.open(pngs[0])
    assert img.mode == "P" and img.size == (320, 200)

    man = json.loads((out / "manifest.json").read_text())
    assert man["summary"]["backgrounds"] == 96
    assert man["summary"]["anomalies"] == 0
    assert (out / "contact_sheet_backgrounds.png").is_file()
    assert (out / "report.md").is_file()


def test_cli_is_deterministic(archive_path, tmp_path):
    game_dir = str(Path(archive_path).parent)

    def run(tag):
        out = tmp_path / tag
        assert extract.main(["--game", game_dir, "--out", str(out)]) == 0
        h = hashlib.sha256()
        for p in sorted(out.rglob("*")):
            if p.is_file():
                h.update(p.relative_to(out).as_posix().encode())
                h.update(p.read_bytes())
        return h.hexdigest()

    assert run("a") == run("b")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_end_to_end.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'extract'`

- [ ] **Step 3: Write minimal implementation**

```python
# extract.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scumm.archive import Archive
from scumm.export import save_indexed_png, save_palette_swatch
from scumm.manifest import (build_manifest, contact_sheet, sha256_file,
                            write_manifest, write_report)
from scumm.room import extract_background


def _room_file(room: int) -> str:
    return f"room_{room:03d}.png"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extract Fate of Atlantis backgrounds.")
    parser.add_argument("--game", required=True, help="directory containing ATLANTIS.001")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)

    archive = Archive.load(Path(args.game) / "ATLANTIS.001")
    rooms = sorted(archive.room_index())

    out = Path(args.out)
    rooms_dir = out / "indexed" / "rooms"
    pal_dir = out / "indexed" / "palettes"
    records = []
    anomalies_total = 0
    sheet_items = []

    for room in rooms:
        bg = extract_background(archive, room)
        anomalies_total += len(bg.anomalies)
        img_rel = f"indexed/rooms/{_room_file(room)}"
        pal_rel = f"indexed/palettes/{_room_file(room)}"
        save_indexed_png(out / img_rel, bg.pixels, bg.width, bg.height, bg.palette)
        save_palette_swatch(out / pal_rel, bg.palette)
        records.append({
            "room": room,
            "name": None,
            "width": bg.width,
            "height": bg.height,
            "transparent_index": bg.palette.transparent_index,
            "source_offset": bg.source_offset,
            "file": img_rel,
            "palette_file": pal_rel,
            "sha256": sha256_file(out / img_rel),
            "anomalies": [
                {"strip": a.strip, "codec_id": a.codec_id, "reason": a.reason}
                for a in bg.anomalies
            ],
        })
        sheet_items.append((room, str(out / img_rel)))

    manifest = build_manifest(args.game, records, anomalies_total)
    write_manifest(out / "manifest.json", manifest)
    contact_sheet(sheet_items, out / "contact_sheet_backgrounds.png")
    write_report(out / "report.md", manifest)

    print(f"rooms: {len(records)}/{len(rooms)}  anomalies: {anomalies_total}")
    return 0 if len(records) == len(rooms) else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_end_to_end.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: PASS (all tests across all files)

- [ ] **Step 6: Inspect the contact sheet**

Run: `.venv/bin/python extract.py --game "$(python3 -c 'import tests.conftest as c; print(c.GAME_DIR)')" --out out`
Then open `out/contact_sheet_backgrounds.png` and confirm 96 labeled-free tiles look
like coherent scenes, not noise. Any tile that looks like static is a decode bug.

- [ ] **Step 7: Commit**

```bash
git add extract.py tests/test_end_to_end.py
git commit -m "feat: backgrounds extraction CLI with end-to-end and determinism tests"
```

---

## Self-Review

**1. Spec coverage (M0+M1 scope):**

- XOR 0x69 decode — Task 1. ✓
- Block tree, LOFF room index — Task 1. ✓
- CLUT/TRNS/EPAL/CYCL — Task 2 (`EPAL` is not needed for the base palette and is
  intentionally not parsed in M1; it is recorded as out-of-scope for M1). ✓
- SMAP both methods, all nine ID ranges, direction, anomalies — Tasks 3–4. ✓
- RMHD dimensions, RMIM→RMIH→IM00→SMAP — Task 5. ✓
- Indexed `P` PNG, exact CLUT, native size — Task 6. ✓
- Manifest with counts, sha256, offsets, anomalies — Task 7. ✓
- Contact sheet + report — Task 7. ✓
- Determinism — Task 8 test. ✓
- Completeness (96/96) — Tasks 5 and 8. ✓
- ZP0n masks — deferred; not required for backgrounds (recorded as M1-optional,
  not implemented). Gap accepted: spec lists z-planes as metadata, not as a
  required M1 deliverable.
- `--rgb` previews — deferred; not required for the M1 source-of-truth output.

**2. Placeholder scan:** No TBD/TODO. Every code step contains complete code.

**3. Type consistency:** `decode_smap(data, smap_off, width, height)` is defined
in Task 4 and called with that exact signature in Task 5. `Palette` fields
(`colors`, `transparent_index`, `cycles`) are consistent across Tasks 2, 6, 7.
`Anomaly` has `strip`, `codec_id`, `reason` everywhere, and `extract.py`
serializes those three fields explicitly.
