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

	// Load hd/room_NNN.idx and hd/room_NNN.png. On any failure, log one
	// warning and leave the room without HD data (plain 4x upscale).
	void loadRoom(int room);
	int room() const { return _room; }
	const HDCompose::Room *roomData() const { return _valid ? &_data : nullptr; }

	// The effective game palette (after shadow remapping), 768 bytes.
	void setPalette(const byte *colors, int first, int num);
	const byte *palette() const { return _palette; }

	// Rebuilt after a palette or room change.
	const HDCompose::Tint &tint();
	const HDCompose::Format &format() const { return _format; }

	// Scratch output of at least size pixels.
	uint32 *buffer(uint size);

private:
	HDCompose::Format _format;
	int _room;
	bool _valid;
	HDCompose::Room _data;
	Common::Array<byte> _idx;
	Common::Array<uint32> _hd;
	byte _ref[768];
	byte _palette[768];
	HDCompose::Tint _tint;
	bool _tintDirty;
	Common::Array<uint32> _out;
};

} // End of namespace Scumm

#endif
