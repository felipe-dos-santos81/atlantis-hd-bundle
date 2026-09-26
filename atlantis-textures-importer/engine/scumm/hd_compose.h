/* HD room backgrounds for Fate of Atlantis (atlantis-textures-importer).
 *
 * The pure compositor core: no engine state, so it builds standalone for its
 * tests (-DHD_COMPOSE_STANDALONE) as well as inside ScummVM.
 */

#ifndef SCUMM_HD_COMPOSE_H
#define SCUMM_HD_COMPOSE_H

#ifdef HD_COMPOSE_STANDALONE
#include <stdint.h>
typedef uint8_t byte;
typedef uint8_t uint8;
typedef uint32_t uint32;
#else
#include "common/scummsys.h"
#endif

namespace Scumm {
namespace HDCompose {

enum { kScale = 4 };

// A 32-bit output format with 8 bits per channel.
struct Format {
	uint8 rShift, gShift, bShift, aShift;
	bool hasAlpha;
};

uint32 pack(const Format &fmt, uint8 r, uint8 g, uint8 b);
void unpack(const Format &fmt, uint32 c, uint8 &r, uint8 &g, uint8 &b);

// Per palette index: identity when the current colour equals the reference
// colour; otherwise channel c maps an HD value v to
// min(255, (v * mul[c] >> 16) + add[c]). A reference channel of 0 cannot be
// scaled, so that channel takes the current colour (mul 0, add current).
struct Tint {
	bool identity[256];
	uint32 mul[256][3];
	uint8 add[256][3];
};

void buildTint(const byte *cur, const byte *ref, Tint &tint);

// One room's HD data: its native index map (w * h) and its HD painting
// ((w * kScale) x (h * kScale) pixels, already in the output Format).
struct Room {
	int w, h;
	const byte *idx;
	const uint32 *hd;
};

// Compose a w x h block of the main screen. src holds the native indices
// (game graphics with text already composited); (roomX, roomY) is the room
// position of src's first pixel. Each native pixel becomes a kScale x kScale
// block of out: the tinted HD block when the index equals the room's index at
// that position and is not colour-cycling, the current palette colour
// otherwise (and everywhere when room is null). cur is the current palette
// (768 bytes), cycling has 256 entries.
void composeMain(const byte *src, int srcPitch, int w, int h, int roomX, int roomY,
                 const Room *room, const byte *cur, const Tint &tint, const bool *cycling,
                 const Format &fmt, uint32 *out, int outPitch);

// Nearest-neighbour kScale x upscale through the current palette.
void upscale(const byte *src, int srcPitch, int w, int h, const byte *cur,
             const Format &fmt, uint32 *out, int outPitch);

} // End of namespace HDCompose
} // End of namespace Scumm

#endif
