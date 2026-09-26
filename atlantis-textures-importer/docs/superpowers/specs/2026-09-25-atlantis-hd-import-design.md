# Atlantis HD Import — Design

Date: 2026-09-25
Status: draft, awaiting user review

## 1. Problem

Play *Indiana Jones and the Fate of Atlantis* from the GOG app with the 96
AI-regenerated room backgrounds shown in true HD (4x, 1280x800).

Inputs:

| Input | Default path | Content |
|---|---|---|
| AI backgrounds | `~/Documents/Indiana Jones and the Fate of Atlantis-ai/` | `room_NNN.png`, 96 files, RGB, exactly 4x each room's native size (126 MB). The `.quality/` history beside them is ignored. |
| Game app | `~/Documents/Indiana Jones® and the Fate of Atlantis™.app` | GOG wrapper around a bundled ScummVM 2.0.0 (x86_64) and `ATLANTIS.000/.001` (SCUMM v5, DOS CD English). |

`NNN` is the SCUMM room number from the `LOFF` table (the exporter's
`Archive.room_index()`), the same number the engine holds in `_currentRoom`.
Native sizes: 320x144 main screen for most rooms (HD 1280x576), 320x200 for
full-screen rooms (HD 1280x800), wider for scrolling rooms, and three narrow
rooms (8 and 16 native pixels wide).

No ScummVM version can show HD backgrounds: the SCUMM engine draws 8-bit
indexed rooms at 320x200. Importing therefore means a patched engine, not a
data patch.

## 2. Decisions

| Question | Decision |
|---|---|
| Outcome | True HD play: a patched, arm64-native ScummVM that shows the 4x RGB backgrounds. No native-resolution data patch. |
| Install target | The GOG `.app` in place, with a backup of the bundled ScummVM, a one-command uninstall, and an ad-hoc re-sign. |
| Objects (object images drawn over the room) | Stay native, upscaled 4x nearest. Object pixels identical to the pristine background under them show HD anyway (a property of the compositor, §4.2). HD objects are a later milestone; the per-room data format leaves room for them. |
| Engine base | ScummVM tag `v2026.3.0`, only the SCUMM engine enabled. |
| Approach | An output-stage compositor (§4). Running the engine at 4x internally, or a backend/shader post-process, were rejected: the first touches masks, strips and scrolling engine-wide; the second needs the same engine hooks plus more plumbing. |

## 3. Layout and build

```
atlantis-textures-importer/
  README.md  AGENTS.md  Makefile  pyproject.toml  .gitignore
  patches/0001-scumm-hd-backgrounds.patch   # against ScummVM v2026.3.0
  engine/hd_background.h, hd_background.cpp # copied into engines/scumm/ at build time
  engine/test_hd_background.cpp            # standalone clang++ tests of the pure core
  importer/                                # Python: validate, stage, install, uninstall, verify
  tests/                                   # unittest
  vendor/                                  # gitignored: ScummVM checkout and build
```

Make targets:

| Target | Does |
|---|---|
| `make build` | Shallow-clones ScummVM at the pinned tag into `vendor/scummvm`, copies `engine/*` into `engines/scumm/`, applies `patches/`, configures with `--disable-all-engines --enable-engine=scumm` and libpng, builds an arm64 `ScummVM.app` and bundles its non-system dylibs so the bundle is self-contained. Idempotent. |
| `make install` | §5. Defaults `ai=` and `app=` to the paths in §1. |
| `make uninstall` | §5.3. |
| `make verify` | §5.4. |
| `make test` | Python unittest suite. |
| `make test-engine` | Builds and runs `engine/test_hd_background.cpp` with `clang++`. |

The importer reuses the exporter's `scumm` package through
`PYTHONPATH=../atlantis-textures-exporter`; it does not duplicate the decoder.
It needs no exporter `out/` folder.

## 4. Engine

### 4.1 Per-room data

The installed game directory gains `hd/`:

| File | Content |
|---|---|
| `hd/room_NNN.png` | The AI background, RGB, 4w x 4h. |
| `hd/room_NNN.idx.png` | The native room image, indexed (P mode), w x h, carrying the room's original 256-colour palette. Written by the importer with the exporter's decoder. |
| `hd/manifest.json` | Written by the importer: patch version, per-room native size and SHA-256 of both files. Not read by the engine. |

The engine never decodes the room image a second time: the `.idx.png` is the
pristine reference and its palette is the reference palette.

### 4.2 Compositing

`HDBackground` (in `engines/scumm/hd_background.{h,cpp}`) owns the loaded
room data and the pure core:

```
composeStrip(native, idx, hd, curPal, refPal, cycling, cameraX, out)
```

For each native pixel (x, y) of a main-screen strip, with room column
`rx = x + cameraX` and native index `i` taken from the composited 8-bit strip
(game graphics with the text overlay already applied, as stock ScummVM
builds `_compositeBuf`):

- If `i == idx[rx, y]` and `cycling[i]` is false: copy the 4x4 HD block at
  (4·rx, 4·y), each channel scaled by `curPal[i] / refPal[i]` and clamped to
  255. When `refPal[i]` channel is 0, that channel is `curPal[i]` instead. An
  unchanged palette gives a ratio of 1: exact HD pixels. Fades, darkening and
  lightning flashes follow the palette through this ratio.
- Otherwise fill the 4x4 block with `curPal[i]`. This is how actors, changed
  object pixels, text, dark rooms and the flashlight appear.

`cycling[i]` is true for every index inside an active `_colorCycle[]` range.

The verb, text and other virtual screens are upscaled 4x nearest.

Known artifact: an actor pixel whose index equals the background index under
it shows the HD pixel. Judged in the live check (§6.3); if visible, an actor
coverage mask from the costume renderer is the fix, out of scope until then.

### 4.3 Engine touch points (the patch)

HD mode is on only when the game directory contains `hd/`. Without it the
patched build behaves exactly like stock ScummVM.

| Where | Change in HD mode |
|---|---|
| `ScummEngine::init` graphics setup (`scumm.cpp`, `initGraphics`) | 4 x `_screenWidth` by 4 x `_screenHeight`, 32-bit output format. |
| `ScummEngine::startScene` (`room.cpp`) | Load the new room's `hd/` files; on a missing or wrong-sized file, log a warning and use the plain 4x upscale for that room. Never an error. |
| `ScummEngine::drawStripToScreen` (`gfx.cpp`) | After the text composite into `_compositeBuf`, dispatch to `HDBackground` (main screen: `composeStrip`; other screens: 4x upscale) and blit the 32-bit result at 4x coordinates. |
| Mouse (`input.cpp` event handling, and every `warpMouse` call) | Divide event coordinates by 4; multiply warp coordinates by 4. |
| Cursor (`cursor.cpp`, the `sclW`/`sclH` scaling) | Scale by 4. |
| Shake (`gfx.cpp`, `setShakePos` multiplier) | Multiply by 4. |

Performance: only dirty strips are composed; a full frame is 1280x800x4 bytes.

## 5. Importer

### 5.1 `make install`

1. **Preflight.** The app and `ATLANTIS.001` exist; `vendor/` holds a built
   `ScummVM.app`; the game is not running (`pgrep`).
2. **Validate.** Decode every room from `ATLANTIS.001`. For each room,
   `ai/room_NNN.png` must exist, be RGB, and measure exactly 4w x 4h; a room
   whose decode reports anomalies fails, since its index map would be wrong.
   All problems are collected and reported together; any problem stops the
   install before the app is touched.
3. **Stage.** Write `hd/` (§4.1) into a temporary folder beside the app.
4. **Swap.** Rename `Contents/Resources/game/scummvm` to `scummvm.orig`, only
   if no `scummvm.orig` exists (a reinstall never overwrites the real
   original; it replaces the current build instead). Copy the new
   `ScummVM.app` to `game/scummvm`, move the staged `hd/` to `game/game/hd`,
   remove `com.apple.quarantine`, run `codesign --force --deep -s -` on the
   app.
5. **Launcher.** `launch_game.sh` is not edited. It runs
   `../scummvm/Contents/MacOS/scummvm`, so the new bundle keeps that
   executable path (`make build` renames the binary if needed).

If step 4 fails, restore `scummvm.orig` to `scummvm`, delete any partial
`hd/`, and exit non-zero.

### 5.2 Config and saves

`configfile` is not edited (it has `aspect_ratio=false`, which suits
1280x800). Saves use ScummVM's default folder; none exist on this Mac today,
and ScummVM 2026.x loads 2.0 saves.

### 5.3 `make uninstall`

Restore `scummvm.orig` to `scummvm`, delete `game/game/hd`, re-sign.
Idempotent; prints what it did.

### 5.4 `make verify`

Re-hash `hd/` against `hd/manifest.json`; run the installed binary with
`--version` and check it is the patched arm64 build.

## 6. Testing

The rules in `atlantis-texture-enhancement/AGENTS.md` §5 apply: one test
module per production module, data-only variations as one `subTest` table, a
rule tested once at the layer that owns it, a regression test names what it
guards.

### 6.1 Engine core

`engine/test_hd_background.cpp` links only `hd_background.cpp`. One table
test of `composeStrip`: exact HD with an unchanged palette; native fill where
`i != idx`; fade ratio, including the zero-channel guard; cycled index falls
back to native; camera offset in a scrolling room; 4x upscale of a non-main
screen. One test of the missing-room fallback.

### 6.2 Importer

Tests build a miniature fake game and AI folder, and a fake `.app` tree in a
temporary directory; `codesign`, `xattr` and `pgrep` go through an injected
runner that records calls. They never touch the real app.

- `validate`: one `subTest` table: missing, wrong size, not RGB, decode
  anomaly.
- `install` and `uninstall`: a round trip restores the tree byte for byte; a
  reinstall never overwrites `scummvm.orig`; a failure in the swap rolls back.
- Real corpus, when the game and AI folder exist: all 96 rooms pass
  `validate`.

### 6.3 Live check (manual, recorded in `AGENTS.md`)

Build, install, launch from the GOG app. With the SCUMM debugger's `room`
command, visit rooms 1, 29, 47, 52, 58, 85 and 95 and screenshot each. Check:
scrolling; an actor behind a foreground mask; the fade on a room change; one
colour-cycling room; one dark or flashlight scene; save and load; the actor
speckle artifact of §4.2. Then `make uninstall` and confirm stock 2.0.0
launches.

## 7. Out of scope

- HD object images, costumes and UI art (a later milestone across all three
  projects).
- A native-resolution data patch for stock ScummVM.
- Distributing the build or the art. The art is LucasArts/Disney copyright;
  personal use only. `vendor/` and any staged art are gitignored.
