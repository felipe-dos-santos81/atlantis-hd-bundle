#!/usr/bin/env bash
# Build the patched ScummVM bundle at vendor/scummvm/ScummVM.app:
# reset vendor/scummvm to the pinned tag, copy engine/scumm/*, apply
# patches/scumm-hd.patch, build the SCUMM engine only, bundle the dylibs.
set -euo pipefail

TAG=v2026.3.0
HERE=$(cd "$(dirname "$0")/.." && pwd)
SRC="$HERE/vendor/scummvm"
PATCH="$HERE/patches/scumm-hd.patch"
STAMP="$HERE/vendor/.scummvm-applied"  # fingerprint of what the last build applied

# The edits in vendor/scummvm: the diff to the tag plus the copied engine files.
applied() { { git -C "$SRC" diff; cat "$SRC"/engines/scumm/hd_*.h "$SRC"/engines/scumm/hd_*.cpp; } | shasum; }

for tool in git make dylibbundler codesign; do
	command -v "$tool" >/dev/null || { echo "missing $tool (brew install $tool)" >&2; exit 1; }
done

if [ ! -d "$SRC/.git" ]; then
	git clone --depth 1 --branch "$TAG" https://github.com/scummvm/scummvm.git "$SRC"
elif [ -f "$STAMP" ] && [ "$(applied)" != "$(cat "$STAMP")" ]; then
	echo "vendor/scummvm has unsaved edits: run 'make importer-engine-patch' for existing files;" >&2
	echo "edits to hd_* files belong in engine/scumm/" >&2
	exit 1
fi

git -C "$SRC" checkout -q -f "$TAG"
git -C "$SRC" clean -q -fd engines/scumm
cp "$HERE"/engine/scumm/* "$SRC/engines/scumm/"
if [ -s "$PATCH" ]; then
	git -C "$SRC" apply "$PATCH"
fi
applied > "$STAMP"

cd "$SRC"
# Reconfigure when the flags below change (this script is newer than config.mk).
if [ ! -f config.mk ] || [ "$HERE/scripts/build_scummvm.sh" -nt config.mk ]; then
	./configure --disable-all-engines --enable-engine=scumm \
		--disable-mpcdec --disable-sparkle --disable-updates --disable-libcurl --disable-sdlnet \
		--disable-cloud --disable-discord --disable-fluidsynth --disable-fluidlite --disable-mad \
		--disable-vorbis --disable-ogg --disable-tremor --disable-flac --disable-theoradec \
		--disable-faad --disable-mpeg2 --disable-a52 --disable-jpeg --disable-gif --disable-vpx \
		--disable-fribidi --disable-tts --disable-openmpt --disable-mikmod --disable-retrowave \
		--disable-sonivox --disable-osx-dock-plugin --disable-gtk
fi
grep -q '^#define USE_PNG' config.h || { echo "libpng not found by configure (brew install libpng)" >&2; exit 1; }
grep -q '^#define USE_RGB_COLOR' config.h || { echo "configure disabled RGB colour support" >&2; exit 1; }

make -j"$(sysctl -n hw.ncpu)"
cp scummvm scummvm-static
rm -rf ScummVM.app
make bundle-pack
dylibbundler -cd -of -b -x ScummVM.app/Contents/MacOS/scummvm \
	-d ScummVM.app/Contents/libs -p @executable_path/../libs/
# Homebrew's SDL2 is sdl2-compat, which dlopens SDL3 at load time from
# @loader_path/libSDL3.dylib; dylibbundler only follows link-time dependencies.
LIBS=ScummVM.app/Contents/libs
if strings "$LIBS/libSDL2-2.0.0.dylib" | grep -q '@loader_path/libSDL3.dylib'; then
	cp "$(brew --prefix sdl3)/lib/libSDL3.0.dylib" "$LIBS/libSDL3.dylib"
	chmod u+w "$LIBS/libSDL3.dylib"
	install_name_tool -id @loader_path/libSDL3.dylib "$LIBS/libSDL3.dylib" 2>/dev/null
	codesign --force --sign - "$LIBS/libSDL3.dylib"
fi
codesign --force --deep --sign - ScummVM.app
echo "built $SRC/ScummVM.app"
