# -*- coding: utf-8 -*-
import sys

SRC = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow.html"
OUT = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html"
TOOL = "mcp__255a1d9a-f031-401d-85f2-4bed88fff239__get_currently_playing"

np_css = """  /* now playing (Spotify via Cowork) */
  .nowplaying{position:fixed;left:22px;bottom:42px;z-index:20;display:flex;align-items:center;gap:12px;
    max-width:300px;background:var(--panel);border:1px solid var(--border);
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
    padding:10px 14px;border-radius:14px;box-shadow:var(--shadow);transition:border-color .3s}
  .nowplaying.playing{border-color:rgba(120,210,160,.55)}
  .np-eq{display:flex;align-items:flex-end;gap:2px;height:20px;width:20px;flex-shrink:0}
  .np-eq span{flex:1;background:var(--accent);border-radius:2px;height:30%}
  .nowplaying.playing .np-eq span{animation:eq .9s ease-in-out infinite}
  .nowplaying.playing .np-eq span:nth-child(2){animation-delay:.2s}
  .nowplaying.playing .np-eq span:nth-child(3){animation-delay:.45s}
  .nowplaying.playing .np-eq span:nth-child(4){animation-delay:.65s}
  @keyframes eq{0%,100%{height:22%}50%{height:96%}}
  .np-info{min-width:0;flex:1}
  .np-title{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .np-artist{font-size:11px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .np-src{font-size:9px;color:var(--muted);opacity:.7;letter-spacing:.6px;text-transform:uppercase;margin-top:2px}
  .np-refresh{background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;flex-shrink:0;padding:4px;border-radius:8px}
  .np-refresh:hover{color:var(--accent)}
  @media(max-width:560px){.nowplaying{left:12px;bottom:12px;max-width:64vw}}
  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:25;opacity:0;pointer-events:none;transition:.3s}"""

np_html = """<div class="nowplaying" id="nowPlaying" title="Spotify - now playing">
  <div class="np-eq"><span></span><span></span><span></span><span></span></div>
  <div class="np-info">
    <div class="np-title" id="npTitle">Now Playing</div>
    <div class="np-artist" id="npArtist">Loading...</div>
    <div class="np-src" id="npSrc"></div>
  </div>
  <button class="np-refresh" id="npRefresh" title="Refresh">&#8635;</button>
</div>

<div class="overlay" id="overlay"></div>"""

np_js = """  renderTodo();renderStats();render();

  /* ---------- Spotify now playing (via Cowork connector) ---------- */
  var npTimer=null;
  function setNP(title,artist,playing,src){
    $('#npTitle').textContent=title||'\\u2014';
    $('#npArtist').textContent=artist||'';
    $('#npSrc').textContent=src||'';
    $('#nowPlaying').classList.toggle('playing',!!playing);
  }
  function deepFind(o,key,depth){
    depth=depth||0; if(o==null||typeof o!=='object'||depth>6)return null;
    if(key==='artists'&&Array.isArray(o.artists))return o.artists;
    if(o[key]!=null&&typeof o[key]!=='object')return o[key];
    for(var k in o){ if(!Object.prototype.hasOwnProperty.call(o,k))continue; var v=deepFind(o[k],key,depth+1); if(v!=null)return v; }
    return null;
  }
  function renderNP(d){
    if(!d||(typeof d==='object'&&Object.keys(d).length===0)){ setNP('Nothing playing','Press play on Spotify',false,'Spotify'); return; }
    var item=d.item||d.track||d.currently_playing_item||d;
    var name=(item&&typeof item.name==='string')?item.name:deepFind(d,'name');
    var artists='';
    var ar=(item&&item.artists)?item.artists:deepFind(d,'artists');
    if(Array.isArray(ar))artists=ar.map(function(a){return (a&&a.name)?a.name:a;}).join(', ');
    else if(typeof ar==='string')artists=ar;
    if(!artists){var ai=deepFind(d,'artist'); if(typeof ai==='string')artists=ai;}
    if(!name){ setNP('Nothing playing','Press play on Spotify',false,'Spotify'); return; }
    var playing=(d.is_playing!==undefined)?!!d.is_playing:true;
    setNP(name,artists,playing,playing?'Playing on Spotify':'Paused on Spotify');
  }
  function fetchNP(){
    if(!(window.cowork&&window.cowork.callMcpTool)){ setNP('Now Playing','Open this in Cowork to see your Spotify track',false,''); return; }
    window.cowork.callMcpTool('__TOOL__',{}).then(function(r){
      if(!r){ renderNP({}); return; }
      if(r.isError){ setNP('Spotify not connected','Connect Spotify in Cowork, then tap the refresh icon',false,''); return; }
      var d=r.structuredContent;
      if((d==null||typeof d!=='object')&&r.content&&r.content[0]&&r.content[0].text){ try{d=JSON.parse(r.content[0].text);}catch(e){d=null;} }
      renderNP(d||{});
    }).catch(function(){ setNP('Spotify unavailable','Tap the refresh icon to retry',false,''); });
  }
  $('#npRefresh').onclick=fetchNP;
  fetchNP();
  npTimer=setInterval(fetchNP,12000);"""

np_js = np_js.replace("__TOOL__", TOOL)

with open(SRC, "r", encoding="utf-8") as f:
    html = f.read()

repls = [
    ("css", "  .overlay{position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:25;opacity:0;pointer-events:none;transition:.3s}", np_css),
    ("html", '<div class="overlay" id="overlay"></div>', np_html),
    ("js", "  renderTodo();renderStats();render();", np_js),
]
ok = True
for name, old, new in repls:
    c = html.count(old)
    if c != 1:
        print("!! anchor '%s' matched %d times" % (name, c)); ok = False
    else:
        html = html.replace(old, new); print("ok:", name)

if not ok:
    print("ABORT"); sys.exit(1)

# tweak title
html = html.replace("<title>FocusFlow</title>", "<title>FocusFlow Live</title>", 1)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote focusflow-live.html (%.1f KB)" % (len(html.encode('utf-8'))/1024.0))
