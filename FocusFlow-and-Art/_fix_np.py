# -*- coding: utf-8 -*-
import sys
F = "/sessions/jolly-amazing-archimedes/mnt/outputs/focusflow-live.html"

old = '''  function renderNP(d){
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
  }'''

new = '''  function renderNP(d){
    if(!d||(typeof d==='object'&&Object.keys(d).length===0)){ setNP('Nothing playing','Press play on Spotify',false,'Spotify'); return; }
    var e=d.currently_playing_entity||d.item||d.track||d.currently_playing_item||d;
    var name=(e&&(e.title||e.name))||deepFind(d,'title')||deepFind(d,'name');
    var artists='';
    if(e&&typeof e.subtitle==='string'){artists=e.subtitle;}
    else{
      var ar=(e&&e.artists)?e.artists:deepFind(d,'artists');
      if(Array.isArray(ar)){artists=ar.map(function(a){return (a&&a.name)?a.name:a;}).join(', ');}
      else if(typeof ar==='string'){artists=ar;}
      if(!artists){var ai=deepFind(d,'artist'); if(typeof ai==='string'){artists=ai;}}
    }
    if(!name){ setNP('Nothing playing','Press play on Spotify',false,'Spotify'); return; }
    var typ=(e&&typeof e.type==='string')?e.type:'';
    var src=(typ&&typ.toLowerCase()!=='song'&&typ.toLowerCase()!=='track')?('Playing '+typ+' on Spotify'):'Playing on Spotify';
    setNP(name,artists,true,src);
  }'''

with open(F, "r", encoding="utf-8") as fh:
    html = fh.read()

if html.count(old) != 1:
    print("!! renderNP anchor matched %d times" % html.count(old)); sys.exit(1)
html = html.replace(old, new)
with open(F, "w", encoding="utf-8") as fh:
    fh.write(html)
print("renderNP updated")
