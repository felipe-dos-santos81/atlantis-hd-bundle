"""Read and write rooms.yaml and reviews.yaml.

rooms.yaml is hand-owned: one entry per manifest room, keyed room_NNN, with a
`kind` (scene, insert or skip) and a `caption` that `make caption` fills and
the user edits. reviews.yaml is machine-written: one verdict per room on its
latest judged attempt, from the VLM review (`source: review`) or from batch's
geometry gate (`source: geometry`).

Multi-line strings are written in folded (`>`) style. PyYAML writes a blank
line for every embedded line break so the text reloads byte-for-byte; the file
looks airier than a hand-written folded block, which is accepted. Every save
goes to <file>.tmp and is renamed into place.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

KINDS = ("scene", "insert", "skip")
REVIEW_SOURCES = ("review", "geometry")
_KEY = re.compile(r"^room_\d{3}$")


class RoomsFileError(ValueError):
    """A YAML file does not have the shape this kit expects."""


@dataclass(frozen=True)
class RoomEntry:
    kind: str
    caption: str = ""


@dataclass(frozen=True)
class Review:
    attempt: int
    accepted: bool
    issues: tuple
    source: str = "review"


def normalize_text(text):
    """Strip trailing whitespace on each line and trailing blank lines.

    PyYAML refuses block style for text with a space before a line break and
    falls back to a double-quoted scalar; VLM output often has such spaces.
    """
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper, data):
    style = ">" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _dump(mapping, path):
    path = Path(path)
    text = yaml.dump(mapping, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=1_000_000)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_mapping(path, optional):
    """The file's top-level mapping of room keys; {} for a missing file when optional."""
    path = Path(path)
    if not path.exists():
        if optional:
            return {}
        raise RoomsFileError(f"{path}: file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise RoomsFileError(f"{path}: invalid YAML: {error}") from error
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise RoomsFileError(f"{path}: expected a mapping of room_NNN entries")
    for key in data:
        if not isinstance(key, str) or not _KEY.match(key):
            raise RoomsFileError(f"{path}: {key!r} is not a room key (room_NNN)")
    return data


def load_rooms(path):
    """{room_NNN: RoomEntry}. A missing or blank caption loads as ""."""
    result = {}
    for key, entry in _read_mapping(path, optional=False).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise RoomsFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"kind", "caption"})
        if unknown:
            raise RoomsFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        kind = entry.get("kind")
        if kind not in KINDS:
            raise RoomsFileError(f'{where}: "kind" must be one of {", ".join(KINDS)}, '
                                 f"got {kind!r}")
        caption = entry.get("caption")
        if caption is None:
            caption = ""
        if not isinstance(caption, str):
            raise RoomsFileError(f'{where}: "caption" must be a string')
        result[key] = RoomEntry(kind, caption)
    return result


def save_rooms(path, rooms):
    _dump({key: {"kind": rooms[key].kind, "caption": normalize_text(rooms[key].caption)}
           for key in sorted(rooms)}, path)


def check_coverage(rooms, keys, path="rooms.yaml"):
    """Raise unless `rooms` has exactly one entry per key in `keys`."""
    missing = sorted(set(keys) - set(rooms))
    extra = sorted(set(rooms) - set(keys))
    problems = []
    if missing:
        problems.append("no entry for " + ", ".join(missing))
    if extra:
        problems.append("entries for rooms not in the manifest: " + ", ".join(extra))
    if problems:
        raise RoomsFileError(f"{path}: " + "; ".join(problems))


def load_reviews(path, optional=False):
    """{room_NNN: Review}. A missing file is {} when optional, else an error."""
    result = {}
    for key, entry in _read_mapping(path, optional).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise RoomsFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"attempt", "accepted", "issues", "source"})
        if unknown:
            raise RoomsFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        attempt, accepted = entry.get("attempt"), entry.get("accepted")
        issues, source = entry.get("issues"), entry.get("source", "review")
        if type(attempt) is not int or attempt < 0:
            raise RoomsFileError(f'{where}: "attempt" must be a non-negative integer')
        if type(accepted) is not bool:
            raise RoomsFileError(f'{where}: "accepted" must be true or false')
        if (not isinstance(issues, list)
                or any(not isinstance(x, str) or not x.strip() for x in issues)):
            raise RoomsFileError(f'{where}: "issues" must be a list of non-empty strings')
        if accepted != (not issues):
            raise RoomsFileError(f'{where}: "accepted" contradicts "issues"')
        if source not in REVIEW_SOURCES:
            raise RoomsFileError(f'{where}: "source" must be one of {", ".join(REVIEW_SOURCES)}')
        result[key] = Review(attempt, accepted, tuple(issues), source)
    return result


def save_reviews(path, reviews):
    _dump({key: {"attempt": r.attempt, "accepted": r.accepted,
                 "issues": [normalize_text(x) for x in r.issues], "source": r.source}
           for key, r in sorted(reviews.items())}, path)
