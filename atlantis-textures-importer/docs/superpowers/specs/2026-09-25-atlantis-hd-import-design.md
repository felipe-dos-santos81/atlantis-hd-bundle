# Atlantis HD Import — Design

Date: 2026-09-25
Status: approved; amended 2026-09-25 while planning (§9)

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
| Install target | The GOG `.app` in place, with a backup of the bundled ScummVM, a one-command uninstall, and no re-signing of the outer app (§5.1). |
| Objects (object images drawn over the room) | Stay native, upscaled 4x nearest. Object pixels identical to the pristine background under them show HD anyway (a property of the compositor, §4.2). HD objects are a later milestone; the per-room data format leaves room for them. |
| Engine base | ScummVM tag `v2026.3.0`, only the SCUMM engine enabled. |
| Approach | An output-stage compositor (§4). Running the engine at 4x internally, or a backend/shader post-process, were rejected: the first touches masks, strips and scrolling engine-wide; the second needs the same engine hooks plus more plumbing. |

## 3. Layout and build

```
atlantis-textures-importer/
  README.md  AGENTS.md  Makefile  .gitignore
  patches/scumm-hd.patch                   # edits to existing ScummVM files, against v2026.3.0
  engine/scumm/hd_compose.{h,cpp}          # pure compositor core, no engine state
  engine/scumm/hd_background.{h,cpp}       # engine glue: loading, blits, palette, cursor
  engine/test_hd_compose.cpp               # standalone clang++ tests of the pure core
  scripts/build_scummvm.sh                 # clone, copy engine/scumm/*, apply, configure, bundle
  importer/                                # Python: validate, stage, install, uninstall, verify
  tests/                                   # unittest
  vendor/  build/                          # gitignored: ScummVM checkout; test binaries
```

Make targets:

| Target | Does |
|---|---|
| `make build` | Shallow-clones ScummVM at the pinned tag into `vendor/scummvm`, resets it to the tag, copies `engine/scumm/*` into `engines/scumm/`, applies `patches/scumm-hd.patch`, configures with `--disable-all-engines --enable-engine=scumm` and libpng, builds an arm64 `ScummVM.app` and bundles its non-system dylibs (`dylibbundler`) so the bundle is self-contained. Refuses to run when `vendor/scummvm` holds edits not saved to the patch. |
| `make patch` | Saves the edits in `vendor/scummvm` to `patches/scumm-hd.patch`. |
| `make install` | §5. Defaults `ai=` and `app=` to the paths in §1. |
| `make uninstall` | §5.3. |
| `make verify` | §5.4. |
| `make test` | Python unittest suite. |
| `make test-engine` | Builds and runs `engine/test_hd_compose.cpp` with `clang++`. |

The importer reuses the exporter's `scumm` package through
`PYTHONPATH=../atlantis-textures-exporter`; it does not duplicate the decoder.
It needs no exporter `out/` folder.

## 4. Engine

### 4.1 Per-room data

The installed game directory gains `hd/`:

| File | Content |
|---|---|
| `hd/room_NNN.png` | The AI background, RGB, 4w x 4h. |
| `hd/room_NNN.idx` | The native room image and its original 256-colour palette: `ATLIDX01`, u16 LE width, u16 LE height, 768 palette bytes, width x height indices. Written by the importer with the exporter's decoder. A raw file, so the engine needs no paletted-PNG handling. |
| `hd/manifest.json` | Written by the importer: source id of the engine sources, per-room native size and SHA-256 of both files. The engine only checks that it exists (it switches HD mode on). |

The engine never decodes the room image a second time: the `.idx` map is the
pristine reference and its palette is the reference palette.

### 4.2 Compositing

`HDBackground` (in `engines/scumm/hd_background.{h,cpp}`) owns the loaded
room data; the pure core lives in `engines/scumm/hd_compose.{h,cpp}`:

```
composeMain(src, srcPitch, w, h, roomX, roomY, room, cur, tint, cycling, fmt, out, outPitch)
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
| `ScummEngine::init` graphics setup (`scumm.cpp`) | `hdInit()`: only for Fate of Atlantis DOS with `hd/manifest.json` present; 4 x `_screenWidth` by 4 x `_screenHeight` in a 32-bit format the backend offers, else a warning and stock 8-bit. |
| Room data (`hdBlit`) | Loaded lazily when a main-screen strip is drawn and `_currentRoom` differs from the loaded room. This covers `startScene`, loading a save (which sets `_currentRoom` directly) and the debugger's `room` command. A missing or wrong-sized file logs one warning and the room gets the plain 4x upscale. Never an error. |
| `ScummEngine::drawStripToScreen` (`gfx.cpp`) | After the text composite into `_compositeBuf`, `hdBlit` (main screen: `composeMain`; other screens: 4x upscale) and blit the 32-bit result at 4x coordinates. |
| `ScummEngine::updatePalette` (`palette.cpp`) | The backend's `setPalette` asserts on a 32-bit screen, so HD mode skips it: `hdSetPalette` keeps the effective palette, feeds it to the cursor palette, and recomposes the main, text and verb screens at once (fades loop without a screen update in between). |
| Effects (`gfx.cpp` `dissolveEffect`, `scrollEffect`, `moveScreen`) | Their direct 8-bit blits go through `effectBlit`, which composes in HD mode; `moveScreen` scales its offsets by 4. |
| Mouse (`input.cpp` event handling; the post-load `warpMouse` in `saveload.cpp`) | Divide event coordinates by 4; multiply warp coordinates by 4. |
| Cursor (`cursor.cpp`) | `updateCursor` scales the 8-bit cursor by 4 and hands it over as CLUT8; `setBuiltinCursor` keeps a 1-byte stride although the screen is 32-bit. |
| Shake (`gfx.cpp`, `updateScreenShakeEffect` multiplier) | Multiply by 4. |

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
   original; it replaces the current build instead). Copy
   `game/game/configfile` to `configfile.orig` the same way. Copy the new
   `ScummVM.app` to `game/scummvm`, move the staged `hd/` to `game/game/hd`,
   remove `com.apple.quarantine`. The outer app is not re-signed: GOG's
   2014 seal already fails modern verification and the app still launches;
   the engine keeps the ad-hoc signature `make build` gives it; and in
   iCloud-synced `~/Documents`, File Provider re-adds `com.apple.FinderInfo`
   to bundle folders within a second, so `codesign` always refuses
   ("resource fork, Finder information, or similar detritus not allowed").
   Not signing also lets uninstall leave GOG's signature untouched.
5. **Launcher.** `launch_game.sh` is not edited. It runs
   `../scummvm/Contents/MacOS/scummvm`, so the new bundle keeps that
   executable path (`make build` renames the binary if needed).

If step 4 fails, restore `scummvm.orig` and `configfile.orig`, delete any
partial `hd/`, and exit non-zero.

### 5.2 Config and saves

ScummVM 2026.x cannot start GOG's `configfile` as is: its 1.7-era
`[atlantis]` target has no `engineid`, and upgrading it fails (`Unknown key
"path"!`). Install adds `engineid=scumm` to `[atlantis]` (once; user decision
2026-09-26) and changes nothing else (`aspect_ratio=false` suits 1280x800).
ScummVM 2026.x also rewrites the file on exit; hence the `configfile.orig`
backup, which uninstall restores. Saves use ScummVM's default folder; none exist on
this Mac today, and ScummVM 2026.x loads 2.0 saves.

### 5.3 `make uninstall`

Refuse while the game is running. Restore `scummvm.orig` and
`configfile.orig`, delete `game/game/hd`. On a stock app it changes
nothing. Prints what it did.

### 5.4 `make verify`

Re-hash `hd/` against `hd/manifest.json`; check the installed binary is an
arm64 Mach-O that contains `ATLIDX01` (only the patched engine does), and that
`scummvm.orig` exists.

## 6. Testing

The rules in `atlantis-texture-enhancement/AGENTS.md` §5 apply: one test
module per production module, data-only variations as one `subTest` table, a
rule tested once at the layer that owns it, a regression test names what it
guards.

### 6.1 Engine core

`engine/test_hd_compose.cpp` links only `hd_compose.cpp`. Tests of
`composeMain` and `upscale`: exact HD with an unchanged palette; native fill where
`i != idx`; fade ratio, including the zero-channel guard; cycled index falls
back to native; camera offset in a scrolling room; 4x upscale of a non-main
screen; the missing-room fallback (no room data).

### 6.2 Importer

Tests build a miniature fake game and AI folder, and a fake `.app` tree in a
temporary directory; `xattr` and `pgrep` go through an injected
runner that records calls. They never touch the real app.

- `validate`: one `subTest` table: missing, wrong size, not RGB, decode
  anomaly.
- `install` and `uninstall`: a round trip restores the tree byte for byte,
  even after ScummVM rewrote `configfile`; a reinstall never overwrites
  `scummvm.orig`; a failure in the swap rolls back; uninstall refuses while
  the game runs.
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

## 9. Amendments made while planning

Reading the v2026.3.0 sources changed these details; the design is unchanged.

- Index maps are raw `.idx` files, not `.idx.png` (§4.1).
- Room data loads lazily at draw time, not in `startScene`: loading a save
  sets `_currentRoom` without `startScene` (§4.3).
- Palette changes recompose the screen, because the backend's `setPalette`
  asserts on a 32-bit screen; the cursor gets its own palette (§4.3).
- Dissolve and scroll transitions, `moveScreen` and the built-in cursor's
  stride needed HD handling (§4.3).
- `configfile` is backed up and restored, because ScummVM rewrites it, and
  install adds `engineid=scumm` to `[atlantis]`, without which ScummVM
  2026.x cannot start the GOG target (§5.2; found in Task 6, user decision).
- `make verify` checks the binary's header and engine marker instead of
  running `--version` (§5.4); no `pyproject.toml` (the importer needs only
  Pillow, installed by `make env`).
- The outer app is not re-signed (§5.1): signing fails in iCloud-synced
  `~/Documents`, and GOG's own seal was already invalid (found in Task 7).
- GOG's `GOGLauncher` does not start the game on this Mac even with the stock
  engine (found in Task 7); `launch_game.sh` run from `Contents/Resources/game`
  does. Out of scope here; reported to the user.
- Make targets are named by stage (`engine-build`, `engine-patch`,
  `hd-validate`, `hd-install`, `hd-verify`, `hd-uninstall`; `install` sets up
  `.venv`), following the house Makefile style (review, 2026-09-26).
- Review fixes (2026-09-26): the engine checks each `.idx` against the room's
  real size; palette changes redraw only the strips showing a changed colour;
  `_outputPixelFormat` stays CLUT8 in HD mode; effects pass their room
  position; the build's unsaved-edit check fingerprints what it applied.
