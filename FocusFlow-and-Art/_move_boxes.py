# -*- coding: utf-8 -*-
import sys
F = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html"

with open(F, "r", encoding="utf-8") as fh:
    html = fh.read()

# R1: put the small clock + greeting back into the header (left of tools)
r1_old = '''  <header>
    <div class="tools">'''
r1_new = '''  <header>
    <div class="clock-wrap">
      <div class="clock" id="clock">--:--</div>
      <div class="greeting" id="greeting"></div>
    </div>
    <div class="tools">'''

# R2a: turn the top-row section into the main stage (keep left side-col)
r2a_old = '''  <section class="top-row">
    <div class="side-col left">'''
r2a_new = '''  <main class="stage">
    <div class="side-col left">'''

# R2b: drop the centre clock + the (old) right calendar col + old <main>, open the timer stack
r2b_old = '''    </div>
    <div class="clock-wrap center">
      <div class="clock" id="clock">--:--</div>
      <div class="greeting" id="greeting"></div>
    </div>
    <div class="side-col right">
      <div class="info-box cal-box" id="calBox">
        <h3><span>\U0001F4C5</span> Today <span class="cal-date" id="calDate"></span></h3>
        <div class="cal-list" id="calList">Loading…</div>
      </div>
    </div>
  </section>

  <main>
    <div class="modes">'''
r2b_new = '''    </div>
    <div class="timer-stack">
      <div class="modes">'''

# R2c: close the timer stack and add the calendar to the RIGHT of the timer
r2c_old = '''    <div class="quote" id="quote"></div>
  </main>'''
r2c_new = '''    <div class="quote" id="quote"></div>
    </div>
    <div class="side-col right">
      <div class="info-box cal-box" id="calBox">
        <h3><span>\U0001F4C5</span> Today <span class="cal-date" id="calDate"></span></h3>
        <div class="cal-list" id="calList">Loading…</div>
      </div>
    </div>
  </main>'''

# CSS: stage is a 3-column row centred on the timer
css_old = "</style>"
css_new = '''  /* timer flanked by side boxes */
  header{justify-content:space-between;align-items:flex-start}
  main.stage{flex:1;display:flex;flex-direction:row;align-items:center;justify-content:center;gap:24px;padding:0 22px;min-height:0}
  .timer-stack{display:flex;flex-direction:column;align-items:center;gap:18px;flex:0 0 auto}
  main.stage .side-col{width:212px;max-width:212px;min-width:0;flex-shrink:1;align-self:center;margin:0}
  main.stage .cal-list{max-height:240px}
  @media(max-width:720px){
    main.stage{flex-direction:column;gap:14px;justify-content:flex-start;overflow-y:auto;padding:10px 16px}
    main.stage .timer-stack{order:-1}
    main.stage .side-col{width:100%;max-width:440px}
  }
</style>'''

steps = [("r1", r1_old, r1_new), ("r2a", r2a_old, r2a_new),
         ("r2b", r2b_old, r2b_new), ("r2c", r2c_old, r2c_new),
         ("css", css_old, css_new)]
ok = True
for name, old, new in steps:
    c = html.count(old)
    if c != 1:
        print("!! %s matched %d" % (name, c)); ok = False
    else:
        html = html.replace(old, new); print("ok:", name)

if not ok:
    print("ABORT"); sys.exit(1)

with open(F, "w", encoding="utf-8") as fh:
    fh.write(html)
print("restructured (%.1f KB)" % (len(html.encode('utf-8'))/1024.0))
