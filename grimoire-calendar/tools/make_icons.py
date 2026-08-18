#!/usr/bin/env python3
"""Generate the PWA icon PNGs.

Run once (or after changing the design):  py -3 tools\\make_icons.py

Windows uses the 192px one in the taskbar and Start menu, so it is drawn at 4x
and downsampled — anti-aliasing a crescent at 192px directly leaves visible
stair-stepping on the inner curve.

The maskable variant matters more than it looks: Android and some Windows
surfaces crop icons to a circle/squircle, and anything inside the outer ~10% is
liable to be cut. So the maskable version keeps the same art but shrinks it into
the safe zone and floods the corners with background instead of leaving them
transparent.
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")

PLUM_EDGE = (8, 5, 15)
PLUM_MID = (20, 12, 38)
PLUM_LIT = (43, 26, 77)
FOIL = (224, 178, 90)
MOON = (243, 227, 189)

SS = 4  # supersample factor


def radial_sky(size: int) -> Image.Image:
    """Plum radial gradient, brightest up and to the right like the app's veil.

    Vectorised: at 4x supersampling this is a 2048x2048 grid, and a per-pixel
    Python loop over 4M points takes ~20s per icon for no reason.
    """
    cx, cy = size * 0.70, size * 0.18
    far = size * 0.95

    ys, xs = np.mgrid[0:size, 0:size].astype(np.float32)
    d = np.clip(np.hypot(xs - cx, ys - cy) / far, 0.0, 1.0)

    lit = np.array(PLUM_LIT, np.float32)
    mid = np.array(PLUM_MID, np.float32)
    edge = np.array(PLUM_EDGE, np.float32)

    # Two linear ramps stitched at d=0.6: core glow, then falloff to the edge.
    inner = d < 0.6
    t = np.where(inner, d / 0.6, (d - 0.6) / 0.4)[..., None]
    a = np.where(inner[..., None], lit, mid)
    b = np.where(inner[..., None], mid, edge)

    return Image.fromarray((a + (b - a) * t).round().astype(np.uint8), "RGB")


def draw_icon(size: int, inset: float = 0.0) -> Image.Image:
    """One icon. `inset` shrinks the art for the maskable safe zone."""
    s = size * SS
    sky = radial_sky(s).convert("RGBA")

    art = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(art)

    pad = s * inset
    box = (pad, pad, s - pad, s - pad)
    span = box[2] - box[0]

    # hairline foil frame
    d.rounded_rectangle(box, radius=span * 0.20, outline=FOIL + (120,), width=max(1, int(s * 0.008)))

    # crescent = lit disc MINUS an offset disc, done as a boolean mask so the
    # subtraction is exact. Drawing then erasing with PIL leaves a fringe of
    # half-transparent pixels along the seam where the two anti-aliased edges
    # overlap; a mask has no seam to fringe.
    cx, cy, r = box[0] + span * 0.56, box[1] + span * 0.50, span * 0.30
    ox, orr = cx - r * 0.52, r * 1.02

    ys, xs = np.mgrid[0:s, 0:s].astype(np.float32)
    crescent = (np.hypot(xs - cx, ys - cy) <= r) & (np.hypot(xs - ox, ys - cy) > orr)

    moon = np.zeros((s, s, 4), np.uint8)
    moon[crescent] = (*MOON, 255)
    art = Image.alpha_composite(art, Image.fromarray(moon, "RGBA"))
    d = ImageDraw.Draw(art)

    # Stars sit in the empty left band and the top-right corner. The crescent
    # spans x 0.26-0.86 / y 0.20-0.80 of the box, so anything inside that lands
    # ON the moon and reads as a blemish rather than a star.
    for fx, fy, fr in ((0.15, 0.20, 0.028), (0.89, 0.10, 0.020),
                       (0.13, 0.55, 0.016), (0.21, 0.84, 0.023)):
        x, y = box[0] + span * fx, box[1] + span * fy
        rr = span * fr
        d.ellipse((x - rr, y - rr, x + rr, y + rr), fill=FOIL + (255,))

    out = Image.alpha_composite(sky, art)
    return out.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)

    for size in (192, 512):
        path = os.path.join(OUT, f"icon-{size}.png")
        draw_icon(size).save(path)
        print("wrote", path)

    # 20% inset keeps the art inside the maskable safe zone.
    path = os.path.join(OUT, "icon-maskable-512.png")
    draw_icon(512, inset=0.20).save(path)
    print("wrote", path)


if __name__ == "__main__":
    main()
