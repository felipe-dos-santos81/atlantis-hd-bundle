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

/* HD room backgrounds for Fate of Atlantis (atlantis-textures-importer).
 *
 * Room data from <game>/hd/: room_NNN.idx (native index map and reference
 * palette) and room_NNN.png (the 4x painting).
 */

#ifndef SCUMM_HD_BACKGROUND_H
#define SCUMM_HD_BACKGROUND_H

#include "common/array.h"
#include "graphics/pixelformat.h"
#include "scumm/hd_compose.h"

namespace Scumm {

class HDBackground {
public:
	explicit HDBackground(const Graphics::PixelFormat &format);

	// Load hd/room_NNN.idx and hd/room_NNN.png for a room of w x h native
	// pixels. On any failure, log one warning and leave the room without HD
	// data (plain 4x upscale).
	void loadRoom(int room, int w, int h);
	int room() const { return _room; }
	const HDCompose::Room *roomData() const { return _valid ? &_data : nullptr; }

	// The effective game palette (after shadow remapping), 768 bytes. Marks
	// the indices whose colour changed in changed[256]; false when none did.
	bool setPalette(const byte *colors, int first, int num, bool *changed);
	const byte *palette() const { return _palette; }

	// Rebuilt after a palette or room change.
	const HDCompose::Tint &tint();
	const HDCompose::Format &format() const { return _format; }

	// Scratch output of at least size pixels.
	uint32 *buffer(uint size);

private:
	Graphics::PixelFormat _pixelFormat;
	HDCompose::Format _format;
	int _room;
	bool _valid;
	HDCompose::Room _data;
	Common::Array<byte> _idx;
	Common::Array<uint32> _pixels;
	byte _ref[768];
	byte _palette[768];
	bool _paletteSet;
	HDCompose::Tint _tint;
	bool _tintDirty;
	Common::Array<uint32> _out;
};

} // End of namespace Scumm

#endif
