# -*- coding: utf-8 -*-
import sys, random

FILES = [
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html",
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html",
]

W, BASE = 1440, 340

def pine_line(seed, peak_lo, peak_hi, step_lo, step_hi, valley_hi=30):
    random.seed(seed)
    xs, ys = [0], [BASE]
    x, i = 0, 0
    while x < W:
        x = min(W, x + random.randint(step_lo, step_hi))
        if i % 2 == 0:
            y = BASE - random.randint(peak_lo, peak_hi)
        else:
            y = BASE - random.randint(6, valley_hi)
        xs.append(x); ys.append(y); i += 1
    xs.append(W); ys.append(BASE)
    d = "M%d,%d " % (xs[0], ys[0]) + " ".join("L%d,%d" % (xs[k], ys[k]) for k in range(1, len(xs))) + " Z"
    return d

FAR = pine_line(4, 70, 140, 60, 95, valley_hi=55)     # distant, shorter, softer
NEAR = pine_line(11, 150, 250, 26, 46, valley_hi=26)   # foreground pines

# ---- replacements ----
root_old = """    --bg-0:#15101c;
    --bg-1:#241a2b;
    --bg-2:#3a2a33;
    --glow:#5a3b3f;"""
root_new = """    --bg-0:#081710;
    --bg-1:#0f2c1d;
    --bg-2:#1b4329;
    --glow:#2f6b40;"""

bg_old = """  .bg{
    position:fixed;inset:0;z-index:-3;
    background:
      radial-gradient(120% 90% at 75% 10%, rgba(255,150,110,.18), transparent 55%),
      radial-gradient(100% 80% at 15% 90%, rgba(120,90,170,.20), transparent 55%),
      linear-gradient(160deg, var(--bg-0), var(--bg-1) 45%, var(--bg-2));
    background-size:200% 200%, 200% 200%, 100% 100%;
    animation:drift 26s ease-in-out infinite;
  }"""
bg_new = """  .bg{
    position:fixed;inset:0;z-index:-3;
    background:
      radial-gradient(130% 85% at 72% 6%, rgba(255,226,150,.22), transparent 54%),
      radial-gradient(110% 80% at 20% 96%, rgba(70,160,95,.22), transparent 55%),
      linear-gradient(165deg, var(--bg-0), var(--bg-1) 50%, var(--bg-2));
    background-size:200% 200%, 200% 200%, 100% 100%;
    animation:drift 26s ease-in-out infinite;
  }"""

css_anchor = "  /* falling flower petals */"
css_new = """  /* Hyrule-style forest scenery */
  .godrays{position:fixed;inset:0;z-index:-3;pointer-events:none;opacity:.55;
    background:repeating-linear-gradient(101deg, rgba(255,232,165,.06) 0 22px, transparent 22px 78px);
    mix-blend-mode:screen}
  .forest{position:fixed;left:0;right:0;bottom:0;z-index:-2;height:44vh;pointer-events:none;overflow:hidden}
  .forest svg{position:absolute;bottom:0;left:0;width:100%;height:100%;display:block}
  .forest .far{opacity:.62;filter:blur(2.5px)}
  .forest .mist{position:absolute;left:0;right:0;bottom:20vh;height:16vh;
    background:linear-gradient(to top, rgba(150,205,165,.12), transparent);filter:blur(7px)}
  /* falling flower petals */"""

html_anchor = '<div class="bg"></div>'
html_new = ('<div class="bg"></div>\n'
            '<div class="godrays"></div>\n'
            '<div class="forest">\n'
            '  <div class="mist"></div>\n'
            '  <svg viewBox="0 0 1440 340" preserveAspectRatio="xMidYMax slice" xmlns="http://www.w3.org/2000/svg">\n'
            '    <path class="far" d="' + FAR + '" fill="#163c22"/>\n'
            '    <path class="near" d="' + NEAR + '" fill="#0a2413"/>\n'
            '  </svg>\n'
            '</div>')

steps = [("root", root_old, root_new),
         ("bg", bg_old, bg_new),
         ("css", css_anchor, css_new),
         ("html", html_anchor, html_new)]

allok = True
for path in FILES:
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    fileok = True
    for name, old, new in steps:
        c = html.count(old)
        if c != 1:
            print("!! [%s] %s matched %d" % (path.split('/')[-1], name, c)); fileok = False; allok = False
        else:
            html = html.replace(old, new)
    if fileok:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("ok:", path.split('/')[-1], "(%.1f KB)" % (len(html.encode('utf-8'))/1024.0))

if not allok:
    sys.exit(1)
print("FAR pts/NEAR pts:", FAR.count('L'), NEAR.count('L'))
