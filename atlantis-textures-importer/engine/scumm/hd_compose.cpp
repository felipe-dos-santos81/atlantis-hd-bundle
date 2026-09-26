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

#include "scumm/hd_compose.h"

namespace Scumm {
namespace HDCompose {

uint32 pack(const Format &fmt, uint8 r, uint8 g, uint8 b) {
	uint32 c = ((uint32)r << fmt.rShift) | ((uint32)g << fmt.gShift) | ((uint32)b << fmt.bShift);
	if (fmt.hasAlpha)
		c |= (uint32)0xFF << fmt.aShift;
	return c;
}

void unpack(const Format &fmt, uint32 c, uint8 &r, uint8 &g, uint8 &b) {
	r = (c >> fmt.rShift) & 0xFF;
	g = (c >> fmt.gShift) & 0xFF;
	b = (c >> fmt.bShift) & 0xFF;
}

void buildTint(const byte *cur, const byte *ref, const Format &fmt, Tint &tint) {
	for (int i = 0; i < 256; i++) {
		const byte *c = cur + 3 * i;
		const byte *r = ref + 3 * i;
		tint.color[i] = pack(fmt, c[0], c[1], c[2]);
		tint.identity[i] = c[0] == r[0] && c[1] == r[1] && c[2] == r[2];
		for (int ch = 0; ch < 3; ch++) {
			if (r[ch]) {
				tint.mul[i][ch] = ((uint32)c[ch] << 16) / r[ch];
				tint.add[i][ch] = 0;
			} else {
				tint.mul[i][ch] = 0;
				tint.add[i][ch] = c[ch];
			}
		}
	}
}

static inline uint8 tintChannel(uint8 v, uint32 mul, uint8 add) {
	const uint32 t = (((uint32)v * mul) >> 16) + add;
	return t > 255 ? 255 : (uint8)t;
}

static void fillBlock(uint32 *block, int outPitch, uint32 color) {
	for (int y = 0; y < kScale; y++)
		for (int x = 0; x < kScale; x++)
			block[y * outPitch + x] = color;
}

static void copyBlock(uint32 *block, int outPitch, const uint32 *hd, int hdPitch,
                      const Format &fmt, const Tint &tint, byte i) {
	if (tint.identity[i]) {
		for (int y = 0; y < kScale; y++)
			for (int x = 0; x < kScale; x++)
				block[y * outPitch + x] = hd[y * hdPitch + x];
		return;
	}
	const uint32 *mul = tint.mul[i];
	const uint8 *add = tint.add[i];
	for (int y = 0; y < kScale; y++) {
		for (int x = 0; x < kScale; x++) {
			uint8 r, g, b;
			unpack(fmt, hd[y * hdPitch + x], r, g, b);
			block[y * outPitch + x] = pack(fmt, tintChannel(r, mul[0], add[0]),
			                               tintChannel(g, mul[1], add[1]), tintChannel(b, mul[2], add[2]));
		}
	}
}

void composeMain(const byte *src, int srcPitch, int w, int h, int roomX, int roomY,
                 const Room *room, const Tint &tint, const bool *cycling,
                 const Format &fmt, uint32 *out, int outPitch) {
	const int hdPitch = room ? room->w * kScale : 0;
	for (int y = 0; y < h; y++) {
		const int ry = roomY + y;
		for (int x = 0; x < w; x++) {
			const byte i = src[y * srcPitch + x];
			const int rx = roomX + x;
			uint32 *block = out + y * kScale * outPitch + x * kScale;
			const bool inRoom = room && rx >= 0 && rx < room->w && ry >= 0 && ry < room->h;
			if (inRoom && !cycling[i] && room->idx[ry * room->w + rx] == i) {
				copyBlock(block, outPitch, room->hd + ry * kScale * hdPitch + rx * kScale, hdPitch, fmt, tint, i);
			} else {
				fillBlock(block, outPitch, tint.color[i]);
			}
		}
	}
}

} // End of namespace HDCompose
} // End of namespace Scumm
