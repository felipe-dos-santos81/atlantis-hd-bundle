# atlantis-textures-importer

Plays *Indiana Jones and the Fate of Atlantis* from the GOG app with the AI
backgrounds from `atlantis-texture-enhancement`, in true HD (1280x800).

It builds a patched ScummVM (v2026.3.0, SCUMM engine only, arm64). The game
still runs at 320x200; only the final output changes: each native pixel that
shows the room's own background becomes the matching 4x4 block of the AI
painting, and everything else (actors, changed objects, text, the verb bar)
becomes a 4x4 block of its palette colour. Fades tint the painting;
colour-cycling pixels stay native. It then swaps that ScummVM into the GOG
app, with a backup and a one-command uninstall.

**Personal use only.** The art is LucasArts/Disney copyright. Nothing here
commits game data, art or builds.

## Requirements

- macOS on Apple silicon with the Xcode command line tools
- Homebrew: `sdl2-compat`, `sdl3`, `libpng`, `freetype`, `dylibbundler`
- Python 3.12 (Pillow is installed by `make importer-install`)
- `../atlantis-textures-exporter`, whose decoder reads the native rooms
- The GOG app and the AI folder (`room_NNN.png`, RGB, exactly 4x each room)

## Usage

Run these from the repository root:

    make importer-engine-build   # 1. clone ScummVM into vendor/, patch, build, bundle
    make importer-hd-validate    # 2. check the 96 AI backgrounds against the game's rooms
    make importer-hd-install     # 3. install the engine and hd/ into the app (quit the game first)
    make importer-hd-verify      # 4. check the installed engine and files
    make importer-hd-uninstall   #    restore the original engine and configfile

Paths default to `~/Documents`; override with `ai="..."` and `app="..."`.

`importer-hd-install` changes nothing unless every room validates. It keeps the
original engine as `scummvm.orig` and the original `configfile` as
`configfile.orig`, and adds `engineid=scumm` to `[atlantis]` (ScummVM 2026
cannot start GOG's older target without it). It does not re-sign the app:
GOG's own signature already fails verification and the game runs anyway, and
signing inside iCloud-synced `~/Documents` always fails.

## Launching

GOG's launcher (double-clicking the app) does not start the game on this Mac,
with the stock engine or this one. Use the game's own script:

    cd "$HOME/Documents/Indiana Jones® and the Fate of Atlantis™.app/Contents/Resources/game" && ./launch_game.sh

## Development

    make importer-test         # Python suite; never touches the real app
    make importer-test-engine  # standalone tests of the compositor core

New engine files live in `engine/scumm/`. Edits to existing ScummVM files
live in `patches/scumm-hd.patch`: make them in `vendor/scummvm/`, then run
`make importer-engine-patch` before `make importer-engine-build`. See `AGENTS.md`.
