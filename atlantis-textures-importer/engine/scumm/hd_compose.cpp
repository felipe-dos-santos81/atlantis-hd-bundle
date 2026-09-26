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

void buildTint(const byte *cur, const byte *ref, Tint &tint) {
	for (int i = 0; i < 256; i++) {
		const byte *c = cur + 3 * i;
		const byte *r = ref + 3 * i;
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
	for (int y = 0; y < kScale; y++) {
		for (int x = 0; x < kScale; x++) {
			uint32 p = hd[y * hdPitch + x];
			if (!tint.identity[i]) {
				uint8 r, g, b;
				unpack(fmt, p, r, g, b);
				p = pack(fmt,
				         tintChannel(r, tint.mul[i][0], tint.add[i][0]),
				         tintChannel(g, tint.mul[i][1], tint.add[i][1]),
				         tintChannel(b, tint.mul[i][2], tint.add[i][2]));
			}
			block[y * outPitch + x] = p;
		}
	}
}

void composeMain(const byte *src, int srcPitch, int w, int h, int roomX, int roomY,
                 const Room *room, const byte *cur, const Tint &tint, const bool *cycling,
                 const Format &fmt, uint32 *out, int outPitch) {
	for (int y = 0; y < h; y++) {
		const int ry = roomY + y;
		for (int x = 0; x < w; x++) {
			const byte i = src[y * srcPitch + x];
			const int rx = roomX + x;
			uint32 *block = out + y * kScale * outPitch + x * kScale;
			const bool inRoom = room && rx >= 0 && rx < room->w && ry >= 0 && ry < room->h;
			if (inRoom && !cycling[i] && room->idx[ry * room->w + rx] == i) {
				const int hdPitch = room->w * kScale;
				copyBlock(block, outPitch, room->hd + ry * kScale * hdPitch + rx * kScale, hdPitch, fmt, tint, i);
			} else {
				fillBlock(block, outPitch, pack(fmt, cur[3 * i], cur[3 * i + 1], cur[3 * i + 2]));
			}
		}
	}
}

void upscale(const byte *src, int srcPitch, int w, int h, const byte *cur,
             const Format &fmt, uint32 *out, int outPitch) {
	for (int y = 0; y < h; y++) {
		for (int x = 0; x < w; x++) {
			const byte i = src[y * srcPitch + x];
			fillBlock(out + y * kScale * outPitch + x * kScale, outPitch,
			          pack(fmt, cur[3 * i], cur[3 * i + 1], cur[3 * i + 2]));
		}
	}
}

} // End of namespace HDCompose
} // End of namespace Scumm
