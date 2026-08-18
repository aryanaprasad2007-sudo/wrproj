"""
Generate Passthrough Color LUT textures for Enchanted Night Garden XR.

Pure standard library -- no numpy, no PIL. Writes 8-bit RGB PNGs directly with
zlib, because this machine's Python 3.14 has neither imaging package and the
house rule is to vendor rather than install.

LUT FORMAT (per Meta's "Creating Passthrough Color LUTs"):
    resolution R must be a power of two (16 / 32 / 64)
    the cube is unrolled into R tiles of R x R pixels
    within a tile:  X = red, Y = green
    across tiles:   blue increases
    R=32 has no integer square root, so the tiles form a strip: 1024 x 32

    Meta's own neutral reference LUTs need "Flip Vertically" enabled on the
    OVRPassthroughLayer. Ours are generated top-down to match that convention,
    so use flipY = true. See the self-test below if colours come out wrong.

SELF-TEST:
    lut_identity_32.png applies no colour change at all. Load it FIRST. If
    passthrough looks completely normal, the layout and flipY setting are
    correct and every other LUT here will be right. If it looks scrambled or
    psychedelic, flip the flipY checkbox and try again. Only two possibilities,
    and the identity LUT tells them apart in seconds -- much better than
    guessing while staring at a graded image that is *supposed* to look odd.

Usage:  py -3 make_luts.py [output_dir]
"""

import os
import struct
import sys
import zlib

R = 32  # LUT resolution per axis


# ── PNG writing ─────────────────────────────────────────────────────────────

def write_png(path, width, height, rgb_rows):
    """rgb_rows: list of bytearray, each width*3 bytes."""
    raw = bytearray()
    for row in rgb_rows:
        raw.append(0)  # filter type 0 (None)
        raw.extend(row)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        return out + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", header))
        f.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        f.write(chunk(b"IEND", b""))


# ── Colour helpers ──────────────────────────────────────────────────────────

def clamp01(x):
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def luminance(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def lerp(a, b, t):
    return a + (b - a) * t


# ── The grades ──────────────────────────────────────────────────────────────
#
# Design notes, since these numbers are the whole visual conceit:
#
#   A LUT remaps colours that are already in the camera image. It cannot add
#   light. So the goal is NOT "make it dark" -- passthrough at night is already
#   dark and noisy, and crushing it further just amplifies sensor grain into
#   something ugly. The goal is to make it read as *moonlit*: cool, desaturated,
#   with shadows tinted rather than black, and highlights pulled off warm-white.
#
#   Hence every grade here LIFTS shadows slightly instead of crushing them.
#   Counter-intuitive, but lifted-and-tinted shadows read as moonlight while
#   crushed shadows read as "bad camera".

def grade(r, g, b, *, sat_pull, shadow_tint, highlight_tint, lift, gain, contrast):
    lum = luminance(r, g, b)

    # Desaturate toward luminance -- moonlight has poor colour discrimination
    r = lerp(r, lum, sat_pull)
    g = lerp(g, lum, sat_pull)
    b = lerp(b, lum, sat_pull)

    # Tint shadows and highlights separately, weighted by luminance
    for i, (sh, hi) in enumerate(zip(shadow_tint, highlight_tint)):
        tint = lerp(sh, hi, lum)
        if i == 0:
            r *= tint
        elif i == 1:
            g *= tint
        else:
            b *= tint

    # Lift + gain, then a gentle S-curve for a bit of shape
    r = r * gain[0] + lift[0]
    g = g * gain[1] + lift[1]
    b = b * gain[2] + lift[2]

    if contrast != 0.0:
        def scurve(x):
            x = clamp01(x)
            return lerp(x, x * x * (3.0 - 2.0 * x), contrast)
        r, g, b = scurve(r), scurve(g), scurve(b)

    return clamp01(r), clamp01(g), clamp01(b)


PRESETS = {
    # The self-test. No change whatsoever.
    "identity": None,

    # Midnight Garden -- the Phase 1 default. Cool blue moonlight, restrained.
    "midnight": dict(
        sat_pull=0.45,
        shadow_tint=(0.78, 0.88, 1.18),
        highlight_tint=(0.86, 0.92, 1.10),
        lift=(0.015, 0.020, 0.045),
        gain=(0.92, 0.95, 1.02),
        contrast=0.15,
    ),

    # Same idea, roughly half strength. Use if 'midnight' is too much in-headset,
    # which is more likely than you would think -- LUTs always look weaker on a
    # monitor than they do on your face.
    "midnight_soft": dict(
        sat_pull=0.25,
        shadow_tint=(0.88, 0.94, 1.09),
        highlight_tint=(0.93, 0.96, 1.05),
        lift=(0.008, 0.010, 0.025),
        gain=(0.96, 0.97, 1.01),
        contrast=0.08,
    ),

    # Moonflower Garden -- bioluminescent purple/magenta. Preset work is Phase 7,
    # but it costs nothing to generate now and it is useful for judging how far
    # the LUT mechanism can actually push the room.
    "moonflower": dict(
        sat_pull=0.35,
        shadow_tint=(0.95, 0.72, 1.28),
        highlight_tint=(0.92, 0.84, 1.16),
        lift=(0.030, 0.012, 0.055),
        gain=(0.94, 0.88, 1.04),
        contrast=0.20,
    ),
}


def build_lut(params):
    """Returns (width, height, rows) for the R*R x R horizontal strip."""
    width, height = R * R, R
    rows = []

    for y in range(height):
        row = bytearray()
        # Generated top-down; pair with flipY = true on OVRPassthroughLayer.
        g_val = (height - 1 - y) / (R - 1)

        for tile in range(R):
            b_val = tile / (R - 1)
            for x in range(R):
                r_val = x / (R - 1)

                if params is None:
                    r, g, b = r_val, g_val, b_val
                else:
                    r, g, b = grade(r_val, g_val, b_val, **params)

                row.append(int(round(r * 255)))
                row.append(int(round(g * 255)))
                row.append(int(round(b * 255)))

        rows.append(row)

    return width, height, rows


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    os.makedirs(out_dir, exist_ok=True)

    for name, params in PRESETS.items():
        width, height, rows = build_lut(params)
        path = os.path.join(out_dir, f"lut_{name}_{R}.png")
        write_png(path, width, height, rows)
        print(f"wrote {path}  ({width}x{height})")

    print("\nUnity import settings for each of these -- all four matter:")
    print("  Texture Type      : Default")
    print("  sRGB (Color Tex.) : OFF")
    print("  Non-Power of 2    : None")
    print("  Generate Mip Maps : OFF")
    print("  Wrap Mode         : Clamp")
    print("  Filter Mode       : Bilinear")
    print("  Compression       : None      <- compressed LUTs band badly")
    print("\nOn OVRPassthroughLayer set flipY = true, then load lut_identity_32")
    print("first. Normal-looking passthrough means the setup is correct.")


if __name__ == "__main__":
    main()
