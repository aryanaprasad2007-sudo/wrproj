# -*- coding: utf-8 -*-
import numpy as np
from PIL import Image, ImageFilter

H, W = 1040, 1500

def vnoise(h, w, g, rng):
    arr = (rng.random((max(2, g), max(2, g))) * 255).astype('uint8')
    im = Image.fromarray(arr).resize((w, h), Image.BICUBIC)
    return np.asarray(im, dtype=float) / 255.0

def fbm(h, w, seed, octaves=6, base=3):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w)); amp = 1.0; tot = 0.0
    for o in range(octaves):
        out += amp * vnoise(h, w, base * (2 ** o), rng); tot += amp; amp *= 0.5
    return out / tot

F = fbm(H, W, 7)
T = fbm(H, W, 23)
X = np.linspace(0, 1, W)[None, :].repeat(H, 0)
Y = np.linspace(0, 1, H)[:, None].repeat(W, 1)

# marble veins: diagonal coordinate displaced by turbulence
coord = (X * 1.0 + Y * 1.7)
marble = 0.5 + 0.5 * np.sin((coord * 2.2 + T * 5.0) * np.pi * 2)

# big colour regions
field = np.clip(0.62 * F + 0.30 * marble + 0.16 * (1 - Y), 0, 1)

stops = [(0.00,(9,7,22)),(0.16,(24,16,60)),(0.34,(66,36,132)),(0.50,(150,66,198)),
         (0.62,(70,86,200)),(0.76,(58,128,206)),(0.88,(165,138,224)),(1.0,(220,196,240))]
pos = np.array([s[0] for s in stops])
cols = np.array([s[1] for s in stops], dtype=float)
r = np.interp(field, pos, cols[:, 0])
g = np.interp(field, pos, cols[:, 1])
b = np.interp(field, pos, cols[:, 2])
img = np.stack([r, g, b], -1)

# bright lavender vein highlights where marble peaks
vein = np.clip((marble - 0.82) / 0.18, 0, 1) ** 1.4
img += vein[..., None] * np.array([95, 70, 120])

# darken the deep-black pockets a touch for contrast
dark = np.clip((0.32 - F) / 0.32, 0, 1) ** 2
img *= (1 - 0.45 * dark[..., None])

# stars
sr = np.random.default_rng(5)
n = 1100
ys = sr.integers(0, H, n); xs = sr.integers(0, W, n); br = sr.random(n)
img[ys, xs] = np.clip(img[ys, xs] + (110 + br * 140)[:, None], 0, 255)
# a few bigger glints
for _ in range(28):
    y = sr.integers(3, H - 3); x = sr.integers(3, W - 3)
    img[y-1:y+2, x-1:x+2] = np.clip(img[y-1:y+2, x-1:x+2] + 150, 0, 255)

img = np.clip(img, 0, 255).astype('uint8')
out = Image.fromarray(img).filter(ImageFilter.GaussianBlur(0.7))
out.save('marble.jpg', quality=82)
out.resize((480, int(480 * H / W))).save('marble-preview.jpg', quality=85)
import os
print('marble.jpg size: %.0f KB  dims %dx%d' % (os.path.getsize('marble.jpg')/1024, W, H))
