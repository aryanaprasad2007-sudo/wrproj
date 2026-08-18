# -*- coding: utf-8 -*-
import base64, sys

FILES = [
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html",
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html",
]

with open("/sessions/jolly-amazing-archimedes/mnt/outputs/marble.jpg", "rb") as f:
    b64 = base64.b64encode(f.read()).decode()
uri = "data:image/jpeg;base64," + b64

root_old = """    --bg-0:#081710;
    --bg-1:#0f2c1d;
    --bg-2:#1b4329;
    --glow:#2f6b40;"""
root_new = """    --bg-0:#0a0a1a;
    --bg-1:#141026;
    --bg-2:#1e1733;
    --glow:#3a2b6b;"""

bg_old = """  .bg{
    position:fixed;inset:0;z-index:-3;
    background:
      radial-gradient(130% 85% at 72% 6%, rgba(255,226,150,.22), transparent 54%),
      radial-gradient(110% 80% at 20% 96%, rgba(70,160,95,.22), transparent 55%),
      linear-gradient(165deg, var(--bg-0), var(--bg-1) 50%, var(--bg-2));
    background-size:200% 200%, 200% 200%, 100% 100%;
    animation:drift 26s ease-in-out infinite;
  }"""
bg_new = ("""  .bg{
    position:fixed;inset:0;z-index:-3;background-color:#0a0a1a;
    background:linear-gradient(rgba(10,8,24,.32),rgba(12,8,26,.46)), url(\"""" + uri + """\") center center / cover no-repeat;
  }""")

hide_old = "</style>"
hide_new = "  .forest,.godrays{display:none}\n</style>"

greet_old = 'id="nameEdit">friend</span>'
greet_new = 'id="nameEdit">Aryan</span>'

steps = [("root", root_old, root_new), ("bg", bg_old, bg_new),
         ("hide", hide_old, hide_new), ("greet", greet_old, greet_new)]

allok = True
for path in FILES:
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    fok = True
    for name, old, new in steps:
        c = html.count(old)
        if c != 1:
            print("!! [%s] %s matched %d" % (path.split('/')[-1], name, c)); fok = False; allok = False
        else:
            html = html.replace(old, new)
    if fok:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("ok:", path.split('/')[-1], "(%.0f KB)" % (len(html.encode('utf-8'))/1024))

sys.exit(0 if allok else 1)
