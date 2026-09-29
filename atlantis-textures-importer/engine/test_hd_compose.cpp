// Standalone tests of the HD compositor core. Build and run: make importer-test-engine
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
		buildTint(cur, ref, kFmt, tint);
		const int w = (int)src.size();
		std::vector<uint32> out(w * kScale * kScale);
		composeMain(src.data(), w, w, 1, roomX, 0, r, tint, cycling, kFmt, out.data(), w * kScale);
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

static void testCameraOffset() {
	Fixture f(3);
	std::vector<uint32> out = f.compose({11}, 1, &f.room);
	CHECK(f.blockIsHD(out, 1, 0, 1), "screen column 0 at camera 1 is room column 1");
}

// Every case where a native pixel keeps its palette colour instead of the HD block.
static void testNativeFallbacks() {
	struct Case {
		const char *what;
		int roomW;       // the fixture's room width
		byte src;        // the native index shown
		int roomX;       // the camera
		int cycling;     // an index to mark colour-cycling, or -1
		bool withRoom;   // false: no HD data at all
	};
	static const Case cases[] = {
		{"an actor pixel (index differs from the room's)", 2, 12, 0, -1, true},
		{"a colour-cycling index", 1, 10, 0, 10, true},
		{"a column past the room's width", 2, 11, 5, -1, true},
		{"no room data: the verb and text screens, or a room without HD files", 1, 10, 0, -1, false},
	};
	for (const Case &c : cases) {
		Fixture f(c.roomW);
		if (c.cycling >= 0)
			f.cycling[c.cycling] = true;
		std::vector<uint32> out = f.compose({c.src}, c.roomX, c.withRoom ? &f.room : nullptr);
		CHECK(blockIs(out, 1, 0, rgb(c.src, c.src, c.src)), c.what);
	}
}

int main() {
	testUnchangedPaletteGivesExactHD();
	testPaletteChangeTintsHD();
	testCameraOffset();
	testNativeFallbacks();
	if (failures) {
		std::printf("%d failure(s)\n", failures);
		return 1;
	}
	std::printf("all passed\n");
	return 0;
}
