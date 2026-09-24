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
