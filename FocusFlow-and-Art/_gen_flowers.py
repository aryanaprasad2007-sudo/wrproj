# -*- coding: utf-8 -*-
import math, colorsys, base64, io, sys
from PIL import Image, ImageDraw, ImageFilter

HTML = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html"

def petal(Wf, Hf, hue, sat=0.62):
    """An elongated petal with a vertical gradient (lighter tip, deeper base)."""
    mask = Image.new('L', (Wf, Hf), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, Wf - 1, Hf - 1], fill=255)
    col = Image.new('RGB', (1, Hf))
    for y in range(Hf):
        f = y / (Hf - 1)                      # 0 tip -> 1 base
        l = max(0.0, min(1.0, 0.84 - 0.30 * f))
        s = max(0.0, min(1.0, sat * (0.80 + 0.35 * f)))
        r, g, b = colorsys.hls_to_rgb(hue, l, s)
        col.putpixel((0, y), (int(r * 255), int(g * 255), int(b * 255)))
    grad = col.resize((Wf, Hf)).convert('RGBA')
    grad.putalpha(mask)
    return grad

def flower(hue, n, sat=0.62):
    S = 520
    base = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    PW, PH = int(S * 0.30), int(S * 0.50)
    pet = petal(PW, PH, hue, sat)
    cx = cy = S // 2
    for i in range(n):
        layer = Image.new('RGBA', (S, S), (0, 0, 0, 0))
        layer.paste(pet, (cx - PW // 2, cy - PH + int(S * 0.05)), pet)
        layer = layer.rotate(360.0 * i / n, resample=Image.BICUBIC, center=(cx, cy))
        base = Image.alpha_composite(base, layer)
    # warm center (complements the cool petals)
    cd = ImageDraw.Draw(base)
    R = int(S * 0.135)
    ir, ig, ib = 255, 249, 210
    orr, og, ob = 232, 196, 110
    for t in range(R, 0, -1):
        f = t / R
        r = int(ir * (1 - f) + orr * f)
        g = int(ig * (1 - f) + og * f)
        b = int(ib * (1 - f) + ob * f)
        cd.ellipse([cx - t, cy - t, cx + t, cy + t], fill=(r, g, b, 255))
    base = base.filter(ImageFilter.GaussianBlur(0.6))
    return base.resize((130, 130), Image.LANCZOS)

def single(hue, sat=0.6):
    p = petal(150, 300, hue, sat)
    p = p.filter(ImageFilter.GaussianBlur(0.6))
    return p.resize((92, 184), Image.LANCZOS)

def uri(img):
    b = io.BytesIO()
    img.save(b, 'PNG', optimize=True)
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

# light-blue -> purple sweep
whole = [(0.575, 6), (0.60, 5), (0.645, 6), (0.70, 5), (0.745, 6), (0.795, 5)]
petals_single = [0.59, 0.69, 0.785]

imgs = [flower(h, n) for (h, n) in whole] + [single(h) for h in petals_single]
uris = [uri(im) for im in imgs]
total_kb = sum(len(u) for u in uris) / 1024.0
print("generated %d images, ~%.1f KB base64 total" % (len(uris), total_kb))

# ---- build new JS / CSS / HTML fragments ----
arr = "var FLOWER_IMGS=[\n" + ",\n".join('    "%s"' % u for u in uris) + "\n  ];"

new_petals_js = (
    "  /* ---------- flowers (light-blue -> purple, transparent PNGs) ---------- */\n"
    "  " + arr + "\n"
    "  (function(){\n"
    "    var c=$('#petals');\n"
    "    for(var i=0;i<30;i++){\n"
    "      var p=document.createElement('div');p.className='petal';\n"
    "      p.style.left=(Math.random()*100)+'%';\n"
    "      p.style.setProperty('--dur',(Math.random()*16+14)+'s');\n"
    "      p.style.animationDelay=(-Math.random()*30)+'s';\n"
    "      var img=document.createElement('img');\n"
    "      img.src=FLOWER_IMGS[Math.floor(Math.random()*FLOWER_IMGS.length)];img.alt='';\n"
    "      img.style.setProperty('--size',(Math.random()*28+22)+'px');\n"
    "      img.style.setProperty('--sway',(Math.random()*4+3)+'s');\n"
    "      img.style.animationDelay=(-Math.random()*5)+'s';\n"
    "      img.style.opacity=(Math.random()*0.35+0.55).toFixed(2);\n"
    "      p.appendChild(img);c.appendChild(p);\n"
    "    }\n"
    "    document.querySelectorAll('.bouquet').forEach(function(b){\n"
    "      var k=3+Math.floor(Math.random()*2);\n"
    "      for(var j=0;j<k;j++){\n"
    "        var im=document.createElement('img');\n"
    "        im.src=FLOWER_IMGS[Math.floor(Math.random()*FLOWER_IMGS.length)];im.alt='';\n"
    "        im.style.width=(46+Math.random()*30)+'px';\n"
    "        b.appendChild(im);\n"
    "      }\n"
    "    });\n"
    "  })();"
)

old_petals_js = (
    "  /* ---------- falling flower petals ---------- */\n"
    "  (function(){\n"
    "    var c=$('#petals');\n"
    "    var glyphs=['\U0001F338','\U0001F338','\U0001F338','\U0001F337','\U0001F33C','\U0001F33A','\U0001F4AE','\U0001F33F','\U0001F343'];\n"
    "    for(var i=0;i<32;i++){\n"
    "      var p=document.createElement('div');p.className='petal';\n"
    "      p.style.left=(Math.random()*100)+'%';\n"
    "      p.style.setProperty('--dur',(Math.random()*16+13)+'s');\n"
    "      p.style.animationDelay=(-Math.random()*30)+'s';\n"
    "      var span=document.createElement('span');\n"
    "      span.textContent=glyphs[Math.floor(Math.random()*glyphs.length)];\n"
    "      span.style.setProperty('--size',(Math.random()*16+14)+'px');\n"
    "      span.style.setProperty('--sway',(Math.random()*4+3)+'s');\n"
    "      span.style.animationDelay=(-Math.random()*5)+'s';\n"
    "      span.style.opacity=(Math.random()*0.4+0.5).toFixed(2);\n"
    "      p.appendChild(span);\n"
    "      c.appendChild(p);\n"
    "    }\n"
    "  })();"
)

old_css_span = (
    "  .petal span{display:inline-block;line-height:1;font-size:var(--size,18px);\n"
    "    animation:sway var(--sway,4s) ease-in-out infinite alternate;\n"
    "    filter:drop-shadow(0 2px 5px rgba(0,0,0,.3))}"
)
new_css_span = (
    "  .petal span,.petal img{display:inline-block;line-height:1;font-size:var(--size,18px);\n"
    "    animation:sway var(--sway,4s) ease-in-out infinite alternate;\n"
    "    filter:drop-shadow(0 3px 6px rgba(70,50,130,.40))}\n"
    "  .petal img{width:var(--size,28px);height:auto;object-fit:contain}"
)

old_css_bouquet = (
    "  .bouquet{position:fixed;bottom:-12px;font-size:52px;z-index:-2;opacity:.22;\n"
    "    pointer-events:none;user-select:none;filter:blur(.4px)}\n"
    "  .bouquet.left{left:-4px;transform:rotate(-8deg)}\n"
    "  .bouquet.right{right:-4px;transform:rotate(8deg)}\n"
    "  .bouquet.top-left{top:-14px;bottom:auto;left:-6px;transform:rotate(150deg);font-size:44px;opacity:.16}"
)
new_css_bouquet = (
    "  .bouquet{position:fixed;bottom:-20px;z-index:-2;opacity:.34;display:flex;align-items:flex-end;\n"
    "    pointer-events:none;user-select:none;filter:blur(.3px) drop-shadow(0 5px 12px rgba(45,30,95,.45))}\n"
    "  .bouquet img{height:auto;margin:0 -9px}\n"
    "  .bouquet.left{left:-12px;transform:rotate(-6deg)}\n"
    "  .bouquet.right{right:-12px;transform:rotate(6deg)}\n"
    "  .bouquet.top-left{top:-24px;bottom:auto;left:-16px;transform:rotate(162deg);opacity:.20}"
)

old_html_bouquet = (
    '<div class="bouquet left">\U0001F33F\U0001F337\U0001F338\U0001F33C</div>\n'
    '<div class="bouquet right">\U0001F33C\U0001F338\U0001F337\U0001F33F</div>\n'
    '<div class="bouquet top-left">\U0001F338\U0001F33F\U0001F337</div>'
)
new_html_bouquet = (
    '<div class="bouquet left"></div>\n'
    '<div class="bouquet right"></div>\n'
    '<div class="bouquet top-left"></div>'
)

with open(HTML, 'r', encoding='utf-8') as f:
    html = f.read()

repls = [
    ("petals-js", old_petals_js, new_petals_js),
    ("css-span", old_css_span, new_css_span),
    ("css-bouquet", old_css_bouquet, new_css_bouquet),
    ("html-bouquet", old_html_bouquet, new_html_bouquet),
]
ok = True
for name, old, new in repls:
    n = html.count(old)
    if n != 1:
        print("!! FAILED to match '%s' (found %d)" % (name, n))
        ok = False
    else:
        html = html.replace(old, new)
        print("ok: replaced %s" % name)

if not ok:
    print("ABORTED - no file written")
    sys.exit(1)

with open(HTML, 'w', encoding='utf-8') as f:
    f.write(html)
print("WROTE focusflow.html  (%.1f KB)" % (len(html.encode('utf-8')) / 1024.0))
