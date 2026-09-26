// Standalone tests of the HD compositor core. Build and run: make test-engine
#include <cstdio>
#include <cstring>
#include <vector>

#include "scumm/hd_compose.h"

using namespace Scumm::HDCompose;

static int failures = 0;

#define CHECK(cond, what) \
	do { \
		if (!(cond)) { \
			std::printf("FAIL %s: %s\n", what, #cond); \
			failures++; \
		} \
	} while (0)

static const Format kFmt = {16, 8, 0, 24, true}; // ARGB8888

static uint32 rgb(uint8 r, uint8 g, uint8 b) { return pack(kFmt, r, g, b); }

// A w x 1 room: index 10 + x at column x; reference and current palettes are
// grey ramps (index i = (i, i, i)); HD pixel (x, y) = rgb(100 + x, 100 + y, 50),
// so a test can tell which HD pixel landed where.
struct Fixture {
	byte ref[768];
	byte cur[768];
	bool cycling[256];
	std::vector<byte> idx;
	std::vector<uint32> hd;
	Room room;

	explicit Fixture(int w) : idx(w), hd(w * kScale * kScale) {
		for (int i = 0; i < 256; i++)
			ref[3 * i] = ref[3 * i + 1] = ref[3 * i + 2] = (byte)i;
		memcpy(cur, ref, sizeof(cur));
		memset(cycling, 0, sizeof(cycling));
		for (int x = 0; x < w; x++)
			idx[x] = (byte)(10 + x);
		for (int y = 0; y < kScale; y++)
			for (int x = 0; x < w * kScale; x++)
				hd[y * w * kScale + x] = rgb((uint8)(100 + x), (uint8)(100 + y), 50);
		room.w = w;
		room.h = 1;
		room.idx = idx.data();
		room.hd = hd.data();
	}

	std::vector<uint32> compose(const std::vector<byte> &src, int roomX, const Room *r) {
		Tint tint;
		buildTint(cur, ref, tint);
		const int w = (int)src.size();
		std::vector<uint32> out(w * kScale * kScale);
		composeMain(src.data(), w, w, 1, roomX, 0, r, cur, tint, cycling, kFmt, out.data(), w * kScale);
		return out;
	}

	// Is output block x (of an output w blocks wide) the HD block of room column rx?
	bool blockIsHD(const std::vector<uint32> &out, int w, int x, int rx) const {
		for (int by = 0; by < kScale; by++)
			for (int bx = 0; bx < kScale; bx++)
				if (out[by * w * kScale + x * kScale + bx] != hd[by * room.w * kScale + rx * kScale + bx])
					return false;
		return true;
	}
};

static bool blockIs(const std::vector<uint32> &out, int w, int x, uint32 c) {
	for (int by = 0; by < kScale; by++)
		for (int bx = 0; bx < kScale; bx++)
			if (out[by * w * kScale + x * kScale + bx] != c)
				return false;
	return true;
}

static void testUnchangedPaletteGivesExactHD() {
	Fixture f(2);
	std::vector<uint32> out = f.compose({10, 11}, 0, &f.room);
	CHECK(f.blockIsHD(out, 2, 0, 0), "unchanged palette, column 0");
	CHECK(f.blockIsHD(out, 2, 1, 1), "unchanged palette, column 1");
}

static void testChangedPixelIsNative() {
	Fixture f(2);
	std::vector<uint32> out = f.compose({12, 11}, 0, &f.room);
	CHECK(blockIs(out, 2, 0, rgb(12, 12, 12)), "an actor pixel is its palette colour");
	CHECK(f.blockIsHD(out, 2, 1, 1), "the background next to it stays HD");
}

static void testPaletteChangeTintsHD() {
	Fixture f(1);
	// Index 10: red halves, green has a zero reference (takes the current 40),
	// blue grows 25.5x and clamps at 255.
	f.ref[30] = 10; f.ref[31] = 0; f.ref[32] = 10;
	f.cur[30] = 5; f.cur[31] = 40; f.cur[32] = 255;
	std::vector<uint32> out = f.compose({10}, 0, &f.room);
	// HD pixel (0, 0) is rgb(100, 100, 50).
	CHECK(out[0] == rgb(50, 40, 255), "fade ratio, zero-channel guard and clamp");
}

static void testCyclingIndexIsNative() {
	Fixture f(1);
	f.cycling[10] = true;
	std::vector<uint32> out = f.compose({10}, 0, &f.room);
	CHECK(blockIs(out, 1, 0, rgb(10, 10, 10)), "a colour-cycling index stays native");
}

static void testCameraOffset() {
	Fixture f(3);
	std::vector<uint32> out = f.compose({11}, 1, &f.room);
	CHECK(f.blockIsHD(out, 1, 0, 1), "screen column 0 at camera 1 is room column 1");
}

static void testOutsideTheRoomIsNative() {
	Fixture f(2);
	std::vector<uint32> out = f.compose({11}, 5, &f.room);
	CHECK(blockIs(out, 1, 0, rgb(11, 11, 11)), "a column past the room's width stays native");
}

static void testNoRoomDataIsNative() {
	Fixture f(1);
	std::vector<uint32> out = f.compose({10}, 0, nullptr);
	CHECK(blockIs(out, 1, 0, rgb(10, 10, 10)), "a room without HD data is a plain 4x upscale");
}

static void testUpscale() {
	Fixture f(1);
	const std::vector<byte> src = {3, 4};
	std::vector<uint32> out(2 * kScale * kScale);
	upscale(src.data(), 2, 2, 1, f.cur, kFmt, out.data(), 2 * kScale);
	CHECK(blockIs(out, 2, 0, rgb(3, 3, 3)) && blockIs(out, 2, 1, rgb(4, 4, 4)), "4x nearest upscale");
}

int main() {
	testUnchangedPaletteGivesExactHD();
	testChangedPixelIsNative();
	testPaletteChangeTintsHD();
	testCyclingIndexIsNative();
	testCameraOffset();
	testOutsideTheRoomIsNative();
	testNoRoomDataIsNative();
	testUpscale();
	if (failures) {
		std::printf("%d failure(s)\n", failures);
		return 1;
	}
	std::printf("all passed\n");
	return 0;
}
