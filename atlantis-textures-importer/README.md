# atlantis-textures-importer

Plays *Indiana Jones and the Fate of Atlantis* from the GOG app with the AI
room backgrounds from `atlantis-texture-enhancement` in true HD (1280x800).

It builds a patched ScummVM (v2026.3.0, SCUMM engine only, arm64) whose
output step paints each native pixel as a 4x4 block: the AI painting where
the pixel still shows the room's own background, the palette colour
elsewhere (actors, changed objects, text, the verb bar). Palette fades tint
the painting; colour-cycling pixels stay native. It then swaps that ScummVM
into the GOG app, with a backup and a one-command uninstall.

**Personal use only.** The art is LucasArts/Disney copyright. Nothing here
commits game data, art or builds.

## Requirements

- macOS on Apple silicon, Xcode command line tools
- Homebrew: `sdl2-compat` (or `sdl2`), `sdl3`, `libpng`, `freetype`, `dylibbundler`
- Python 3.12 (Pillow is installed by `make env`)
- `../atlantis-textures-exporter` (its decoder reads the native rooms)
- The GOG app and the AI folder (`room_NNN.png`, RGB, exactly 4x each room)

## Usage

    make build        # clone ScummVM v2026.3.0 into vendor/, patch, build, bundle
    make validate     # check the 96 AI backgrounds against the game's rooms
    make install      # swap the patched ScummVM and hd/ into the app (quit the game first)
    make verify       # check the installed engine and HD files
    make uninstall    # restore the app's original ScummVM and configfile

Paths default to `~/Documents`; override with
`make install ai="/path/to/ai" app="/path/to/Indiana Jones® and the Fate of Atlantis™.app"`.

`make install` changes nothing unless every room validates. It keeps the
original ScummVM as `Contents/Resources/game/scummvm.orig` and the original
`configfile` as `configfile.orig`, and adds `engineid=scumm` to the
`[atlantis]` target (ScummVM 2026 cannot start GOG's 1.7-era target without
it). It does not re-sign the app: GOG's own seal already fails verification
and the game runs regardless, and signing inside iCloud-synced `~/Documents`
always fails. Rerun `make install` after rebuilding.

## Launching

On this Mac, GOG's launcher (double-clicking the app) does not start the
game, with the stock engine as with this one. Start it with the game's own
script:

    cd "$HOME/Documents/Indiana Jones® and the Fate of Atlantis™.app/Contents/Resources/game" && ./launch_game.sh

## Development

    make test         # Python suite (never touches the real app)
    make test-engine  # standalone tests of the compositor core

New engine files live in `engine/scumm/`; edits to existing ScummVM files
live in `patches/scumm-hd.patch`. Edit existing files in `vendor/scummvm/`,
then `make patch` before `make build`. See `AGENTS.md`.
