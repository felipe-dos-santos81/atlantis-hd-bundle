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
