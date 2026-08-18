# -*- coding: utf-8 -*-
import sys
FILES = [
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html",
    "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html",
]

old = '''  function startAlarm(label){
    stopAlarm();
    playChime();
    alarmTimer=setInterval(playChime,2600);
    $('#alarmText').textContent=label||"Time's up!";
    $('#alarmBanner').classList.add('show');
  }'''

new = '''  function startAlarm(label){
    stopAlarm();
    playBeeps();
    alarmTimer=setInterval(playBeeps,760);
    $('#alarmText').textContent=label||"Time's up!";
    $('#alarmBanner').classList.add('show');
  }
  function playBeeps(){
    ensureAudio();if(!ctx)return;
    var now=ctx.currentTime;
    for(var i=0;i<3;i++){
      var o=ctx.createOscillator();var g=ctx.createGain();
      o.type='square';o.frequency.value=1245;
      var t=now+i*0.125;
      g.gain.setValueAtTime(0,t);
      g.gain.linearRampToValueAtTime(0.2,t+0.004);
      g.gain.setValueAtTime(0.2,t+0.07);
      g.gain.exponentialRampToValueAtTime(0.0008,t+0.108);
      o.connect(g);g.connect(ctx.destination);
      o.start(t);o.stop(t+0.12);
    }
  }'''

allok = True
for path in FILES:
    with open(path, "r", encoding="utf-8") as fh:
        html = fh.read()
    c = html.count(old)
    if c != 1:
        print("!! [%s] startAlarm matched %d" % (path.split('/')[-1], c)); allok = False
        continue
    html = html.replace(old, new)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    print("ok:", path.split('/')[-1])

sys.exit(0 if allok else 1)
