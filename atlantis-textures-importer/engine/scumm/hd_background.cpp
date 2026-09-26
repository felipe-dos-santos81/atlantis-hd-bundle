/* ScummVM - Graphic Adventure Engine
 *
 * ScummVM is the legal property of its developers, whose names
 * are too numerous to list here. Please refer to the COPYRIGHT
 * file distributed with this source distribution.
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 *
 */

/* HD room backgrounds for Fate of Atlantis (atlantis-textures-importer). */

#include "common/file.h"
#include "common/str.h"
#include "common/system.h"
#include "common/textconsole.h"
#include "engines/util.h"
#include "graphics/blit.h"
#include "graphics/cursorman.h"
#include "graphics/surface.h"
#include "image/png.h"

#include "scumm/hd_background.h"
#include "scumm/scumm.h"

namespace Scumm {

static const char kIdxMagic[] = "ATLIDX01"; // written by atlantis-textures-importer (importer/stage.py)

HDBackground::HDBackground(const Graphics::PixelFormat &format) : _pixelFormat(format), _room(-1), _valid(false), _paletteSet(false), _tintDirty(true) {
	_format.rShift = format.rShift;
	_format.gShift = format.gShift;
	_format.bShift = format.bShift;
	_format.aShift = format.aShift;
	_format.hasAlpha = format.aBits() > 0;
	_data.w = _data.h = 0;
	_data.idx = nullptr;
	_data.hd = nullptr;
	memset(_ref, 0, sizeof(_ref));
	memset(_palette, 0, sizeof(_palette));
}

void HDBackground::loadRoom(int room, int roomW, int roomH) {
	_room = room;
	_valid = false;
	_tintDirty = true;
	_idx.clear();
	_pixels.clear();
	if (room <= 0)
		return;

	const Common::String idxName = Common::String::format("hd/room_%03d.idx", room);
	const Common::String pngName = Common::String::format("hd/room_%03d.png", room);

	Common::File idx;
	if (!idx.open(Common::Path(idxName))) {
		warning("HD backgrounds: %s is missing; room %d gets a plain 4x upscale", idxName.c_str(), room);
		return;
	}
	char magic[8];
	if (idx.read(magic, 8) != 8 || memcmp(magic, kIdxMagic, 8) != 0) {
		warning("HD backgrounds: %s is not an index map", idxName.c_str());
		return;
	}
	const int w = idx.readUint16LE();
	const int h = idx.readUint16LE();
	if (w != roomW || h != roomH) {
		warning("HD backgrounds: %s is %dx%d but room %d is %dx%d; it gets a plain 4x upscale", idxName.c_str(), w, h, room, roomW, roomH);
		return;
	}
	_idx.resize(w * h);
	if (w <= 0 || h <= 0 || idx.read(_ref, 768) != 768 || idx.read(_idx.data(), w * h) != (uint32)(w * h)) {
		warning("HD backgrounds: %s is truncated", idxName.c_str());
		return;
	}

#ifdef USE_PNG
	Common::File png;
	Image::PNGDecoder decoder;
	if (!png.open(Common::Path(pngName)) || !decoder.loadStream(png)) {
		warning("HD backgrounds: %s is missing or unreadable; room %d gets a plain 4x upscale", pngName.c_str(), room);
		return;
	}
	const Graphics::Surface *s = decoder.getSurface();
	if (!s || s->format.bytesPerPixel < 2 || s->w != w * HDCompose::kScale || s->h != h * HDCompose::kScale) {
		warning("HD backgrounds: %s is not an RGB image of %dx%d", pngName.c_str(), w * HDCompose::kScale, h * HDCompose::kScale);
		return;
	}
	_pixels.resize(s->w * s->h);
	Graphics::crossBlit((byte *)_pixels.data(), (const byte *)s->getPixels(), s->w * sizeof(uint32), s->pitch,
	                    s->w, s->h, _pixelFormat, s->format);
	_data.w = w;
	_data.h = h;
	_data.idx = _idx.data();
	_data.hd = _pixels.data();
	_valid = true;
#else
	warning("HD backgrounds: this build has no PNG support");
#endif
}

bool HDBackground::setPalette(const byte *colors, int first, int num, bool *changed) {
	bool any = false;
	for (int i = 0; i < num; i++) {
		byte *entry = _palette + (first + i) * 3;
		if (!_paletteSet || memcmp(entry, colors + i * 3, 3) != 0) {
			memcpy(entry, colors + i * 3, 3);
			changed[first + i] = any = true;
		}
	}
	_paletteSet = true;
	_tintDirty |= any;
	return any;
}

const HDCompose::Tint &HDBackground::tint() {
	if (_tintDirty) {
		HDCompose::buildTint(_palette, _valid ? _ref : _palette, _format, _tint);
		_tintDirty = false;
	}
	return _tint;
}

uint32 *HDBackground::buffer(uint size) {
	if (_out.size() < size)
		_out.resize(size);
	return _out.data();
}

bool ScummEngine::hdInit() {
#ifdef USE_RGB_COLOR
	if (_game.id != GID_INDY4 || _game.platform != Common::kPlatformDOS || _macScreen || _textSurfaceMultiplier != 1 ||
	    (_renderMode != Common::kRenderDefault && _renderMode != Common::kRenderVGA) ||
	    !Common::File::exists(Common::Path("hd/manifest.json")))
		return false;

	Graphics::PixelFormat format;
	bool found = false;
	Common::List<Graphics::PixelFormat> formats = _system->getSupportedFormats();
	for (Common::List<Graphics::PixelFormat>::const_iterator f = formats.begin(); f != formats.end(); ++f) {
		if (f->bytesPerPixel == 4 && f->rBits() == 8 && f->gBits() == 8 && f->bBits() == 8) {
			format = *f;
			found = true;
			break;
		}
	}
	if (!found) {
		warning("HD backgrounds: the backend offers no 32-bit screen; running at native resolution");
		return false;
	}

	initGraphics(_screenWidth * HDCompose::kScale, _screenHeight * HDCompose::kScale, &format);
	if (_system->getScreenFormat() != format) {
		warning("HD backgrounds: could not set a 32-bit screen; running at native resolution");
		initGraphics(_screenWidth, _screenHeight);
		return false;
	}
	_hd = new HDBackground(format);
	return true;
#else
	return false;
#endif
}

void ScummEngine::hdBlit(VirtScreen *vs, const byte *src, int srcPitch, int roomX, int roomY, int dstX, int dstY, int w, int h) {
	if (w <= 0 || h <= 0)
		return;
	const int s = HDCompose::kScale;
	const int outPitch = w * s;
	uint32 *out = _hd->buffer(outPitch * h * s);

	// Only the main screen shows the room; the verb and text screens are a plain upscale.
	const HDCompose::Room *room = nullptr;
	bool cycling[256] = {};
	if (vs->number == kMainVirtScreen) {
		// Lazily, so startScene, loading a save and the debugger's room command are all covered.
		if (_hd->room() != _currentRoom)
			_hd->loadRoom(_currentRoom, _roomWidth, _roomHeight);
		room = _hd->roomData();
		for (int i = 0; i < ARRAYSIZE(_colorCycle); i++) {
			const ColorCycle &c = _colorCycle[i];
			if (c.delay)
				for (int j = c.start; j <= c.end; j++)
					cycling[j] = true;
		}
	}
	HDCompose::composeMain(src, srcPitch, w, h, roomX, roomY, room, _hd->tint(), cycling, _hd->format(), out, outPitch);
	_system->copyRectToScreen(out, outPitch * sizeof(uint32), dstX * s, dstY * s, w * s, h * s);
}

void ScummEngine::effectBlit(VirtScreen *vs, const byte *src, int pitch, int roomX, int roomY, int x, int y, int w, int h) {
	if (_hd)
		hdBlit(vs, src, pitch, roomX, roomY, x, y, w, h);
	else
		_system->copyRectToScreen(src, pitch, x, y, w, h);
}

void ScummEngine::hdSetPalette(const byte *colors, int first, int num) {
	bool changed[256] = {};
	if (!_hd->setPalette(colors, first, num, changed))
		return;
	CursorMan.replaceCursorPalette(_hd->palette(), 0, 256);
	CursorMan.disableCursorPalette(false);
	if (!_textSurface.getPixels())
		return;
	// A 32-bit screen does not follow palette changes, and fades loop without
	// a screen update in between: recompose now every strip showing a changed
	// colour, in the game graphics or in the text over them.
	static const VirtScreenNumber screens[] = { kMainVirtScreen, kTextVirtScreen, kVerbVirtScreen };
	for (int i = 0; i < ARRAYSIZE(screens); i++) {
		VirtScreen *vs = &_virtscr[screens[i]];
		if (vs->h <= 0 || !vs->getBasePtr(0, 0))
			continue;
		for (int x = 0; x < vs->w; x += 8) {
			bool shows = false;
			for (int y = 0; y < vs->h && !shows; y++) {
				const byte *game = vs->getPixels(x, y);
				const byte *text = (const byte *)_textSurface.getBasePtr(x, vs->topline + y);
				for (int k = 0; k < 8 && !shows; k++)
					shows = changed[game[k]] || (text[k] != CHARSET_MASK_TRANSPARENCY && changed[text[k]]);
			}
			if (shows)
				drawStripToScreen(vs, x, 8, 0, vs->h);
		}
	}
}

void ScummEngine::hdUpdateCursor(const byte *cursor, int w, int h, int hotspotX, int hotspotY, uint32 transColor) {
	const int s = HDCompose::kScale;
	Common::Array<byte> big(w * s * h * s);
	Graphics::scaleBlit(big.data(), cursor, w * s, w, w * s, h * s, w, h, Graphics::PixelFormat::createFormatCLUT8());
	CursorMan.replaceCursor(big.data(), w * s, h * s, hotspotX * s, hotspotY * s, transColor);
}

} // End of namespace Scumm
