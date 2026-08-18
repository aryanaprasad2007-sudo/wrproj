# -*- coding: utf-8 -*-
import sys

F = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html"

# ---------- CSS ----------
css = """  /* info boxes: weather / message / calendar around the clock */
  header{justify-content:flex-end;align-items:center}
  .top-row{display:grid;grid-template-columns:1fr auto 1fr;gap:22px;align-items:start;padding:2px 6px 0;margin-top:4px}
  .side-col{display:flex;flex-direction:column;gap:14px;width:100%;max-width:300px}
  .side-col.left{margin-left:auto}
  .side-col.right{margin-right:auto}
  .clock-wrap.center{text-align:center;padding-top:4px}
  .clock-wrap.center .clock{font-size:42px}
  .clock-wrap.center .greeting{font-size:14px}
  .info-box{background:var(--panel);border:1px solid var(--border);border-radius:16px;padding:14px 16px;
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);box-shadow:var(--shadow)}
  .info-box h3{font-size:11px;text-transform:uppercase;letter-spacing:1.4px;color:var(--muted);
    margin-bottom:10px;display:flex;align-items:center;gap:7px;font-weight:600}
  .info-box h3 .cal-date{margin-left:auto;text-transform:none;letter-spacing:0;color:var(--accent);font-size:12px}
  .wx-row{display:flex;align-items:center;gap:10px}
  .wx-icon{font-size:30px;line-height:1}
  .wx-temp{font-size:32px;font-weight:600;font-variant-numeric:tabular-nums}
  .wx-cond{font-size:14px;margin-top:2px}
  .wx-meta{font-size:11px;color:var(--muted);margin-top:5px}
  .msg-text{font-size:14px;line-height:1.55;color:var(--text)}
  .cal-list{display:flex;flex-direction:column;gap:9px;max-height:210px;overflow-y:auto}
  .cal-list::-webkit-scrollbar{width:6px}
  .cal-list::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:4px}
  .cal-item{display:flex;gap:10px;align-items:flex-start}
  .cal-dot{width:9px;height:9px;border-radius:50%;margin-top:5px;flex-shrink:0}
  .cal-time{font-size:11px;color:var(--muted)}
  .cal-title{font-size:13px;font-weight:500;line-height:1.3;word-break:break-word}
  .cal-loc{font-size:11px;color:var(--muted);margin-top:1px}
  .cal-empty{font-size:13px;color:var(--muted);padding:6px 0}
  @media(max-width:880px){
    .top-row{grid-template-columns:1fr;justify-items:center}
    .side-col{max-width:440px;margin:0 auto}
    .clock-wrap.center{order:-1}
  }
  /* now playing (Spotify via Cowork) */"""

# ---------- HTML: header trim + top-row ----------
header_old = """  <header>
    <div class="clock-wrap">
      <div class="clock" id="clock">--:--</div>
      <div class="greeting" id="greeting"></div>
    </div>
    <div class="tools">"""
header_new = """  <header>
    <div class="tools">"""

row_old = """  </header>

  <main>"""
row_new = """  </header>

  <section class="top-row">
    <div class="side-col left">
      <div class="info-box weather-box" id="weatherBox">
        <h3><span>☀️</span> Weather</h3>
        <div class="wx-row"><span class="wx-icon" id="wxIcon">⛅</span><span class="wx-temp" id="wxTemp">--°</span></div>
        <div class="wx-cond" id="wxCond">—</div>
        <div class="wx-meta" id="wxMeta"></div>
      </div>
      <div class="info-box message-box" id="messageBox">
        <div class="msg-text" id="msgText">Putting together your day…</div>
      </div>
    </div>
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

  <main>"""

# ---------- JS ----------
js_anchor = "  /* ---------- Spotify now playing (via Cowork connector) ---------- */"
js_new = '''  /* ---------- weather / calendar / daily message ---------- */
  var WEATHER={"updated":"2026-06-17","city":"Union City, CA","tempF":86,"hi":87,"lo":58,"cond":"Sunny","icon":"☀️"};
  function renderWeather(){
    var w=WEATHER;
    if(!w){$('#wxTemp').textContent='--°';$('#wxCond').textContent='Unavailable';return;}
    $('#wxIcon').textContent=w.icon||'⛅';
    $('#wxTemp').textContent=(w.tempF!=null?Math.round(w.tempF)+'°':'--°');
    $('#wxCond').textContent=w.cond||'';
    var meta=w.city||'';
    if(w.hi!=null&&w.lo!=null)meta+=' · H '+Math.round(w.hi)+'° L '+Math.round(w.lo)+'°';
    if(w.updated)meta+=' · as of '+w.updated;
    $('#wxMeta').textContent=meta;
  }
  var CAL_TOOL='mcp__f8f8675f-d173-480c-a4aa-70563862fbc4__list_events';
  var CAL_COLORS={'1':'#7986cb','2':'#33b679','3':'#8e24aa','4':'#e67c73','5':'#f6bf26','6':'#f4511e','7':'#039be5','8':'#616161','9':'#3f51b5','10':'#0b8043','11':'#d50000'};
  function pad2(n){return (n<10?'0':'')+n;}
  function fmtEvTime(iso){try{var d=new Date(iso);var h=d.getHours();var m=d.getMinutes();return pad2(((h%12)||12))+':'+pad2(m)+' '+(h<12?'AM':'PM');}catch(e){return '';}}
  function todayBounds(){
    var n=new Date();var y=n.getFullYear(),mo=n.getMonth(),da=n.getDate();
    var s=y+'-'+pad2(mo+1)+'-'+pad2(da)+'T00:00:00';
    var e2=new Date(y,mo,da+1);
    var e=e2.getFullYear()+'-'+pad2(e2.getMonth()+1)+'-'+pad2(e2.getDate())+'T00:00:00';
    return {start:s,end:e};
  }
  function renderCalendar(data){
    var evs=(data&&data.events)||[];
    $('#calDate').textContent=new Date().toLocaleDateString(undefined,{month:'short',day:'numeric'});
    if(!evs.length){$('#calList').innerHTML='<div class="cal-empty">Nothing scheduled today ✨</div>';return [];}
    var html='';
    evs.forEach(function(e){
      var title=e.summary||'(untitled)';
      var t=(e.start&&e.start.dateTime)?fmtEvTime(e.start.dateTime):'All day';
      var c=CAL_COLORS[e.colorId]||'var(--accent)';
      var loc=e.location?('<div class="cal-loc">'+escapeHtml(e.location)+'</div>'):'';
      html+='<div class="cal-item"><span class="cal-dot" style="background:'+c+'"></span><div class="cal-meta"><div class="cal-time">'+t+'</div><div class="cal-title">'+escapeHtml(title)+'</div>'+loc+'</div></div>';
    });
    $('#calList').innerHTML=html;
    return evs;
  }
  function buildMessage(openTasks,eventTitles){
    var nm=(store.get('ff.name','')||'Aryan');
    var hr=new Date().getHours();
    var part=hr<12?'morning':hr<18?'afternoon':'evening';
    function fallback(){
      var s="Good "+part+", "+nm+"! ";
      if(eventTitles&&eventTitles.length){s+="On your calendar today: "+eventTitles.slice(0,2).join(", ")+". ";}
      if(openTasks&&openTasks.length){s+="Top of your list: "+openTasks.slice(0,3).join(", ")+". You've got this.";}
      else if(!(eventTitles&&eventTitles.length)){s+="Your slate is clear — pick one focus and dive in.";}
      else{s+="Add a task or two and start a focus session when you're ready.";}
      $('#msgText').textContent=s;
    }
    if(window.cowork&&window.cowork.askClaude){
      var prompt="You are a warm, upbeat study companion inside a focus app. Write a short message (2-3 sentences, under ~45 words) addressed to "+nm+" for this "+part+". Greet them by name, sound encouraging and human, and naturally reference their open tasks and today's calendar events from the data provided. Do not invent tasks or events that are not in the data. Use at most one emoji. Return only the message text.";
      var data=[{label:"open_tasks",tasks:(openTasks||[])},{label:"todays_calendar_events",events:(eventTitles||[])}];
      try{
        window.cowork.askClaude(prompt,data).then(function(res){
          var txt=(typeof res==='string')?res:(res&&(res.text||res.message||res.content||res.output));
          if(txt&&typeof txt==='string'){$('#msgText').textContent=txt.trim();}else{fallback();}
        }).catch(fallback);
      }catch(e){fallback();}
    }else{fallback();}
  }
  function loadDay(){
    renderWeather();
    var openT=tasks.filter(function(t){return !t.done;}).map(function(t){return t.text;});
    if(!(window.cowork&&window.cowork.callMcpTool)){
      $('#calList').innerHTML='<div class="cal-empty">Open this in Cowork to see your calendar</div>';
      buildMessage(openT,[]);
      return;
    }
    var b=todayBounds();
    window.cowork.callMcpTool(CAL_TOOL,{startTime:b.start,endTime:b.end,orderBy:'startTime',pageSize:25}).then(function(r){
      if(r&&r.isError){$('#calList').innerHTML='<div class="cal-empty">Calendar not connected — reconnect in Cowork</div>';buildMessage(openT,[]);return;}
      var data=r?r.structuredContent:null;
      if((data==null||typeof data!=='object')&&r&&r.content&&r.content[0]&&r.content[0].text){try{data=JSON.parse(r.content[0].text);}catch(e){data={};}}
      var evs=renderCalendar(data||{});
      var titles=evs.map(function(e){return e.summary||'';}).filter(Boolean);
      buildMessage(openT,titles);
    }).catch(function(){
      $('#calList').innerHTML='<div class="cal-empty">Couldn\\u0027t load calendar</div>';
      buildMessage(openT,[]);
    });
  }
  loadDay();
  setInterval(loadDay,10*60*1000);

  /* ---------- Spotify now playing (via Cowork connector) ---------- */'''

with open(F, "r", encoding="utf-8") as fh:
    html = fh.read()

steps = [
    ("css", "  /* now playing (Spotify via Cowork) */", css),
    ("header", header_old, header_new),
    ("toprow", row_old, row_new),
    ("js", js_anchor, js_new),
]
ok = True
for name, old, new in steps:
    if html.count(old) != 1:
        print("!! anchor '%s' matched %d" % (name, html.count(old))); ok = False
    else:
        html = html.replace(old, new); print("ok:", name)

if not ok:
    print("ABORT"); sys.exit(1)

with open(F, "w", encoding="utf-8") as fh:
    fh.write(html)
print("updated focusflow-live.html (%.1f KB)" % (len(html.encode('utf-8'))/1024.0))
