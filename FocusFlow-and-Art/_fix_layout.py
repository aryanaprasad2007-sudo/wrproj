# -*- coding: utf-8 -*-
import sys
F = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html"

repls = [
    # let the 3 columns shrink instead of wrapping; tighter gap
    ("  .top-row{display:grid;grid-template-columns:1fr auto 1fr;gap:22px;align-items:start;padding:2px 6px 0;margin-top:4px}",
     "  .top-row{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:16px;align-items:start;padding:2px 4px 0;margin-top:4px}"),
    # side columns may shrink (min-width:0) and are a bit narrower
    ("  .side-col{display:flex;flex-direction:column;gap:14px;width:100%;max-width:300px}",
     "  .side-col{display:flex;flex-direction:column;gap:12px;width:100%;max-width:248px;min-width:0}"),
    # slightly smaller centre clock so the trio fits sooner
    ("  .clock-wrap.center .clock{font-size:42px}",
     "  .clock-wrap.center .clock{font-size:38px}"),
    # only stack on genuinely tiny widths (was 880)
    ("  @media(max-width:880px){\n    .top-row{grid-template-columns:1fr;justify-items:center}\n    .side-col{max-width:440px;margin:0 auto}\n    .clock-wrap.center{order:-1}\n  }",
     "  @media(max-width:540px){\n    .top-row{grid-template-columns:1fr;justify-items:center}\n    .side-col{max-width:440px;margin:0 auto}\n    .clock-wrap.center{order:-1}\n  }"),
]

with open(F, "r", encoding="utf-8") as fh:
    html = fh.read()

ok = True
for old, new in repls:
    if html.count(old) != 1:
        print("!! no unique match for:\n", old[:70], "...(", html.count(old), ")"); ok = False
    else:
        html = html.replace(old, new); print("ok:", old[:48])

if not ok:
    print("ABORT"); sys.exit(1)

with open(F, "w", encoding="utf-8") as fh:
    fh.write(html)
print("layout updated")
