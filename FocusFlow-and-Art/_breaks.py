# -*- coding: utf-8 -*-
import sys
FILES = [
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html",
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html",
]

old = """  var defaults={focus:25,short:5,long:15,interval:4,autoBreak:true,autoFocus:false,notify:false,volume:0.5,repeatAlarm:true};
  var settings=Object.assign({},defaults,store.get('ff.settings',{}));"""

new = """  var defaults={focus:25,short:10,long:30,interval:4,autoBreak:true,autoFocus:false,notify:false,volume:0.5,repeatAlarm:true,ver:2};
  var _stored=store.get('ff.settings',null);
  var settings=Object.assign({},defaults,_stored||{});
  if(!_stored||(_stored.ver||0)<2){settings.short=10;settings.long=30;settings.ver=2;store.set('ff.settings',settings);}"""

allok = True
for path in FILES:
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    c = html.count(old)
    if c != 1:
        print("!! [%s] matched %d" % (path.split('/')[-1], c)); allok = False; continue
    html = html.replace(old, new)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("ok:", path.split('/')[-1])

sys.exit(0 if allok else 1)
