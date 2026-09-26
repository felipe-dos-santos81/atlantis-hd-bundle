# atlantis-textures-importer — agent notes

## 1. Invariants

- **The engine runs at 320x200.** Only the output step changes: scripts,
  boxes, masks, text and costumes are untouched. Anything that writes to the
  backend screen goes through `hdBlit` (via `drawStripToScreen`) or
  `effectBlit`.
- **HD mode is opt-in by data.** It is on only for Fate of Atlantis DOS with
  `hd/manifest.json` in the game directory; otherwise the build is stock.
- **Missing data never errors.** A room without valid `hd/` files logs one
  warning and gets a plain 4x upscale.
- **Room data loads lazily** in `hdBlit`, keyed on `_currentRoom`: loading a
  save sets `_currentRoom` without `startScene`.
- **Palette changes recompose the screen** (`hdSetPalette`): the backend's
  `setPalette` asserts on a 32-bit screen, and fades loop without a screen
  update in between. Only the 8-px strips that show a changed colour (in the
  game graphics or the text over them) are redrawn, so colour cycling stays
  cheap; an unchanged palette redraws nothing.
- **The engine draws 8-bit.** In HD mode `_outputPixelFormat` is CLUT8 (what
  the engine produces); only `hdBlit` writes the 32-bit screen.
- **Install never loses the original.** `scummvm.orig` and `configfile.orig`
  are written once and restored by uninstall or by a failed install.
- **Install edits configfile once:** `engineid=scumm` in `[atlantis]`.
  ScummVM 2026.3.0 cannot upgrade GOG's 1.7-era target without it and quits
  with `Unknown key "path"!`.
- **The outer app is never re-signed.** In iCloud-synced `~/Documents`, File
  Provider re-adds `com.apple.FinderInfo` to bundle folders within a second,
  so `codesign` always refuses; GOG's 2014 seal already fails verification
  and the game runs regardless. The engine keeps the ad-hoc signature from
  `make engine-build`.

## 2. Modules

| File | Owns | Must not |
|---|---|---|
| `engine/scumm/hd_compose.*` | the pixel rule, tint, packed colours | know engine state or files |
| `engine/scumm/hd_background.*` | loading `hd/`, the ScummEngine HD methods | decide the pixel rule |
| `patches/scumm-hd.patch` | the hooks in existing ScummVM files | hold logic beyond a call |
| `scripts/build_scummvm.sh` | clone, reset, patch, configure, bundle | edit `vendor/` by hand |
| `importer/rooms.py` | native rooms, validation | write files |
| `importer/stage.py` | the `hd/` format and manifest, staging and checking it | touch the app |
| `importer/app.py` | install, uninstall, verify, rollback, the configfile edit | decode rooms |
| `importer/cli.py` | argument parsing, the install sequence | hold rules |

Engine work: edit new files in `engine/scumm/`; edit existing ScummVM files
in `vendor/scummvm/`, then `make engine-patch` before `make engine-build`.
The build resets `vendor/scummvm` to the tag. It records a fingerprint of
what it applied (the diff plus the copied `hd_*` sources) in
`vendor/.scummvm-applied` and refuses to run when `vendor/scummvm` differs
from it, so no edit is lost.

The bundle: Homebrew's `libSDL2` is `sdl2-compat`, which dlopens
`@loader_path/libSDL3.dylib`; `dylibbundler` only follows link-time
dependencies, so the build script copies and signs SDL3 itself. Dylibs in
`Contents/libs` are signed one by one (`codesign --deep` does not reach
them). The build passes `--disable-gtk`, else GTK and X11 get bundled.

## 3. Engine touch points

`patches/scumm-hd.patch` against v2026.3.0. Every hook is a call or a
scale factor; the logic lives in `engine/scumm/`.

| File | Function | Change in HD mode |
|---|---|---|
| `module.mk` | | builds `hd_background.o`, `hd_compose.o` |
| `scumm.h` | `ScummEngine` | `_hd`, `hdScale()`, the `hd*`/`effectBlit` declarations |
| `scumm.cpp` | `init` | `hdInit()` sets up the 4x, 32-bit screen; `_outputPixelFormat` stays CLUT8 |
| `scumm.cpp` | `~ScummEngine` | deletes `_hd` |
| `gfx.cpp` | `drawStripToScreen` | after the text composite, `hdBlit` and return |
| `gfx.cpp` | `dissolveEffect`, `scrollEffect` | direct blits go through `effectBlit`, with their room position |
| `gfx.cpp` | `moveScreen`, `updateScreenShakeEffect` | offsets and shake times `hdScale()` |
| `palette.cpp` | `updatePalette` | `hdSetPalette` instead of the backend palette |
| `input.cpp` | mouse events | coordinates divided by `hdScale()` |
| `saveload.cpp` | post-load `warpMouse` | coordinates times `hdScale()` |
| `cursor.cpp` | `updateCursor` | `hdUpdateCursor`: 4x, CLUT8, cursor palette |

## 4. Testing

    make test         # unittest discover: every tests/test_*.py
    make test-engine  # engine/test_hd_compose.cpp

Tests never touch the real app. `tests/testkit.py` is the one shared
test-support module: `make_rooms`, `write_ai`, `make_app` (named like the
real app, with `®` and `™`), `make_build`, `Runner`, `snapshot`. Never
re-implement these in a test module. The rules of
`../atlantis-texture-enhancement/AGENTS.md` §5 apply.
`test_rooms.RealCorpusTests` runs when the game and the AI folder exist: all
96 rooms validate.

Screenshots of the running game: capture the game window alone by its
window id (`screencapture -l <id>`, the id from `CGWindowListCopyWindowInfo`
for the scummvm pid), never the screen or a screen region.

## 5. Live check (2026-09-26)

- Build: stock-behaving bundle boots GOG's data with `engineid=scumm` added
  (LucasArts logo); without it ScummVM 2026.3.0 quits (`Unknown key "path"!`).
- Install on the real app: the first attempt failed at `codesign` and rolled
  back to stock (engine, configfile, no `hd/`); without re-signing, install
  and `make hd-verify` pass.
- GOG launcher: does not start the game on this Mac, stock or HD (the
  process idles, no window). `launch_game.sh` starts both.
- Room 4 (title): HD painting at 1280x800 (window 1280x832 with title bar);
  logo and credits as 4x pixel art. A dotted line at native row ~150 spans the
  credits' width: a credits text line mid-redraw, not a compositor defect.
  Blocky patches at the upper right are in the AI painting itself.
