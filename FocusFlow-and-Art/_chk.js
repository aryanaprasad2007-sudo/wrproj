
(function(){
  "use strict";

  /* ---------- storage ---------- */
  var store = {
    get:function(k,f){ try{ var v=localStorage.getItem(k); return v===null?f:JSON.parse(v);}catch(e){return f;} },
    set:function(k,v){ try{ localStorage.setItem(k,JSON.stringify(v)); }catch(e){} }
  };

  /* ---------- state ---------- */
  var defaults={focus:25,short:5,long:15,interval:4,autoBreak:true,autoFocus:false,notify:false,volume:0.5};
  var settings=Object.assign({},defaults,store.get('ff.settings',{}));
  var tasks=store.get('ff.tasks',[]);
  var stats=store.get('ff.stats',{days:{},totalSeconds:0,totalSessions:0});
  var name=store.get('ff.name','');
  var activeTaskId=store.get('ff.activeTask',null);

  var mode='focus';
  var remaining=settings.focus*60;
  var total=remaining;
  var running=false;
  var endEpoch=null;
  var ticker=null;
  var cycleCount=0; // completed focus sessions toward a long break

  /* ---------- helpers ---------- */
  var $=function(s){return document.querySelector(s);};
  function pad(n){return (n<10?'0':'')+n;}
  function durFor(m){return (m==='focus'?settings.focus:m==='short'?settings.short:settings.long)*60;}
  function dateKey(d){d=d||new Date();return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());}
  function fmtMin(sec){var m=Math.round(sec/60);return m+'m';}

  /* ---------- falling flower petals ---------- */
  (function(){
    var c=$('#petals');
    var glyphs=['🌸','🌸','🌸','🌷','🌼','🌺','💮','🌿','🍃'];
    for(var i=0;i<32;i++){
      var p=document.createElement('div');p.className='petal';
      p.style.left=(Math.random()*100)+'%';
      p.style.setProperty('--dur',(Math.random()*16+13)+'s');
      p.style.animationDelay=(-Math.random()*30)+'s';
      var span=document.createElement('span');
      span.textContent=glyphs[Math.floor(Math.random()*glyphs.length)];
      span.style.setProperty('--size',(Math.random()*16+14)+'px');
      span.style.setProperty('--sway',(Math.random()*4+3)+'s');
      span.style.animationDelay=(-Math.random()*5)+'s';
      span.style.opacity=(Math.random()*0.4+0.5).toFixed(2);
      p.appendChild(span);
      c.appendChild(p);
    }
  })();

  /* ---------- clock + greeting ---------- */
  function tickClock(){
    var n=new Date();
    var h=n.getHours();
    $('#clock').textContent=pad(((h%12)||12))+':'+pad(n.getMinutes())+' '+(h<12?'AM':'PM');
    var part=h<12?'morning':h<18?'afternoon':h<22?'evening':'night';
    var nm=name?'<span class="name" id="nameEdit">'+escapeHtml(name)+'</span>':'<span class="name" id="nameEdit">friend</span>';
    $('#greeting').innerHTML='Good '+part+', '+nm+'.';
    $('#nameEdit').onclick=editName;
  }
  function editName(){
    var v=prompt('What should I call you?',name||'');
    if(v!==null){name=v.trim();store.set('ff.name',name);tickClock();}
  }
  function escapeHtml(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML;}

  /* ---------- timer ---------- */
  var RING_LEN=2*Math.PI*158;
  $('#ring').style.strokeDasharray=RING_LEN;

  function render(){
    $('#time').textContent=pad(Math.floor(remaining/60))+':'+pad(remaining%60);
    var label=mode==='focus'?'Focus':mode==='short'?'Short Break':'Long Break';
    $('#timerLabel').textContent=label;
    var off=RING_LEN*(1-(total>0?remaining/total:0));
    $('#ring').style.strokeDashoffset=off;
    var color=mode==='focus'?getCss('--focus'):getCss('--break');
    $('#ring').style.stroke=color;
    document.documentElement.style.setProperty('--accent', mode==='focus'?'#ffb27a':'#8fd6b4');
    $('#startBtn').textContent=running?'Pause':(remaining<total?'Resume':'Start');
    document.title=(running?pad(Math.floor(remaining/60))+':'+pad(remaining%60)+' · ':'')+label+' — FocusFlow';
    renderDots();
    renderActiveTask();
  }
  function getCss(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim();}

  function renderDots(){
    var box=$('#dots');box.innerHTML='';
    for(var i=0;i<settings.interval;i++){
      var d=document.createElement('div');d.className='dot'+(i<cycleCount?' done':'');
      box.appendChild(d);
    }
    var t=document.createElement('span');t.className='cycle-text';
    t.textContent=cycleCount+' / '+settings.interval+' to long break';
    box.appendChild(t);
  }

  function setMode(m,opts){
    opts=opts||{};
    mode=m;
    document.querySelectorAll('.mode').forEach(function(b){b.classList.toggle('active',b.dataset.mode===m);});
    total=durFor(m);
    remaining=total;
    if(!opts.keepRunning){stopTicker();running=false;}
    render();
    if(opts.autostart){startTimer();}
  }

  function startTimer(){
    if(running)return;
    ensureAudio();
    running=true;
    endEpoch=Date.now()+remaining*1000;
    ticker=setInterval(tick,250);
    render();
  }
  function pauseTimer(){
    if(!running)return;
    running=false;stopTicker();
    remaining=Math.max(0,Math.round((endEpoch-Date.now())/1000));
    render();
  }
  function stopTicker(){if(ticker){clearInterval(ticker);ticker=null;}}
  function toggle(){running?pauseTimer():startTimer();}
  function resetTimer(){stopTicker();running=false;remaining=total;render();}
  function tick(){
    remaining=Math.max(0,Math.round((endEpoch-Date.now())/1000));
    render();
    if(remaining<=0){complete();}
  }

  function complete(){
    stopTicker();running=false;
    playChime();
    if(mode==='focus'){
      recordFocus(total);
      cycleCount++;
      notify('Focus session done! 🎉','Time for a break.');
      var goLong=cycleCount>=settings.interval;
      if(goLong)cycleCount=0;
      setMode(goLong?'long':'short',{autostart:settings.autoBreak});
    }else{
      notify('Break over','Ready to focus again?');
      setMode('focus',{autostart:settings.autoFocus});
    }
  }

  /* ---------- stats ---------- */
  function recordFocus(sec){
    var k=dateKey();
    if(!stats.days[k])stats.days[k]={focus:0,sessions:0};
    stats.days[k].focus+=sec;
    stats.days[k].sessions+=1;
    stats.totalSeconds=(stats.totalSeconds||0)+sec;
    stats.totalSessions=(stats.totalSessions||0)+1;
    store.set('ff.stats',stats);
    renderStats();
  }
  function computeStreak(){
    var s=0,d=new Date();
    for(var i=0;i<400;i++){
      var k=dateKey(d);
      if(stats.days[k]&&stats.days[k].focus>0){s++;}
      else if(i>0){break;}      // today with 0 doesn't break a prior streak
      else if(i===0){/* no focus today yet, keep checking yesterday */}
      d.setDate(d.getDate()-1);
    }
    return s;
  }
  function renderStats(){
    var k=dateKey();
    var today=stats.days[k]||{focus:0,sessions:0};
    $('#stToday').textContent=fmtMin(today.focus);
    $('#stSessions').textContent=today.sessions;
    $('#stStreak').textContent=computeStreak();
    $('#stTotal').textContent=(Math.round((stats.totalSeconds||0)/360)/10)+'h';
    // chart last 7 days
    var chart=$('#chart');chart.innerHTML='';
    var vals=[],keys=[],labels=[];
    var dn=['Su','Mo','Tu','We','Th','Fr','Sa'];
    for(var i=6;i>=0;i--){
      var d=new Date();d.setDate(d.getDate()-i);
      var kk=dateKey(d);keys.push(kk);labels.push(dn[d.getDay()]);
      vals.push(stats.days[kk]?stats.days[kk].focus/60:0);
    }
    var max=Math.max(30,Math.max.apply(null,vals));
    vals.forEach(function(v,i){
      var col=document.createElement('div');col.className='bar-col';
      var bar=document.createElement('div');bar.className='bar'+(i===6?' today':'');
      bar.style.height=Math.max(3,(v/max)*100)+'%';
      bar.title=Math.round(v)+' min';
      var lab=document.createElement('div');lab.className='bar-day';lab.textContent=labels[i];
      col.appendChild(bar);col.appendChild(lab);chart.appendChild(col);
    });
  }

  /* ---------- to-do ---------- */
  function renderTodo(){
    var list=$('#todoList');list.innerHTML='';
    if(!tasks.length){list.innerHTML='<div class="empty">No tasks yet. Add one above ✦</div>';}
    tasks.forEach(function(t){
      var row=document.createElement('div');
      row.className='task'+(t.done?' completed':'')+(t.id===activeTaskId?' active-row':'');
      var chk=document.createElement('div');chk.className='check'+(t.done?' done':'');
      chk.onclick=function(){t.done=!t.done;if(t.done&&t.id===activeTaskId){activeTaskId=null;store.set('ff.activeTask',null);}saveTasks();};
      var txt=document.createElement('div');txt.className='task-text';txt.textContent=t.text;
      txt.title='Click to focus on this task';
      txt.onclick=function(){activeTaskId=(activeTaskId===t.id?null:t.id);store.set('ff.activeTask',activeTaskId);saveTasks();render();};
      var del=document.createElement('button');del.className='task-act';del.innerHTML='🗑';
      del.onclick=function(){tasks=tasks.filter(function(x){return x.id!==t.id;});if(activeTaskId===t.id){activeTaskId=null;store.set('ff.activeTask',null);}saveTasks();render();};
      row.appendChild(chk);row.appendChild(txt);row.appendChild(del);
      list.appendChild(row);
    });
    var open=tasks.filter(function(t){return !t.done;}).length;
    $('#todoCount').textContent=open+' active · '+tasks.length+' total';
  }
  function saveTasks(){store.set('ff.tasks',tasks);renderTodo();}
  function addTask(){
    var inp=$('#todoText');var v=inp.value.trim();if(!v)return;
    tasks.push({id:Date.now()+''+Math.floor(Math.random()*999),text:v,done:false});
    inp.value='';saveTasks();
  }
  function renderActiveTask(){
    var t=tasks.filter(function(x){return x.id===activeTaskId;})[0];
    $('#activeTask').textContent=t?('✦ '+t.text):'';
  }

  /* ---------- audio (ambient + chime) ---------- */
  var ctx=null,master=null,buffers={},active={};
  var soundDefs=[
    {id:'rain',name:'Rain',ico:'🌧'},
    {id:'waves',name:'Ocean waves',ico:'🌊'},
    {id:'brown',name:'Brown noise',ico:'🟤'},
    {id:'white',name:'White noise',ico:'⚪'}
  ];
  function ensureAudio(){
    if(ctx)return;
    try{
      var AC=window.AudioContext||window.webkitAudioContext;
      ctx=new AC();
      master=ctx.createGain();master.gain.value=settings.volume;master.connect(ctx.destination);
      buffers.white=makeNoise('white');
      buffers.brown=makeNoise('brown');
    }catch(e){ctx=null;}
    if(ctx&&ctx.state==='suspended')ctx.resume();
  }
  function makeNoise(type){
    var len=ctx.sampleRate*3;
    var buf=ctx.createBuffer(1,len,ctx.sampleRate);
    var d=buf.getChannelData(0);
    if(type==='white'){for(var i=0;i<len;i++)d[i]=Math.random()*2-1;}
    else{var last=0;for(var j=0;j<len;j++){var w=Math.random()*2-1;last=(last+0.02*w)/1.02;d[j]=last*3.2;}}
    return buf;
  }
  function startSound(id){
    ensureAudio();if(!ctx)return;
    var src=ctx.createBufferSource();src.loop=true;
    var g=ctx.createGain();var lfo=null;
    if(id==='rain'){
      src.buffer=buffers.white;
      var hp=ctx.createBiquadFilter();hp.type='highpass';hp.frequency.value=600;
      var lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=2600;
      src.connect(hp);hp.connect(lp);lp.connect(g);g.gain.value=0.7;
    }else if(id==='waves'){
      src.buffer=buffers.brown;
      var lp2=ctx.createBiquadFilter();lp2.type='lowpass';lp2.frequency.value=650;
      src.connect(lp2);lp2.connect(g);g.gain.value=0.55;
      lfo=ctx.createOscillator();lfo.frequency.value=0.11;
      var lg=ctx.createGain();lg.gain.value=0.45;lfo.connect(lg);lg.connect(g.gain);lfo.start();
    }else if(id==='brown'){
      src.buffer=buffers.brown;src.connect(g);g.gain.value=0.8;
    }else{
      src.buffer=buffers.white;
      var lp3=ctx.createBiquadFilter();lp3.type='lowpass';lp3.frequency.value=8000;
      src.connect(lp3);lp3.connect(g);g.gain.value=0.4;
    }
    g.connect(master);src.start();
    active[id]={src:src,lfo:lfo};
  }
  function stopSound(id){
    var a=active[id];if(!a)return;
    try{a.src.stop();}catch(e){}
    if(a.lfo){try{a.lfo.stop();}catch(e){}}
    delete active[id];
  }
  function toggleSound(id){
    if(active[id]){stopSound(id);}else{startSound(id);}
    renderSounds();
  }
  function renderSounds(){
    var list=$('#soundList');list.innerHTML='';
    soundDefs.forEach(function(s){
      var on=!!active[s.id];
      var row=document.createElement('div');row.className='sound-row'+(on?' on':'');
      row.innerHTML='<div class="sound-ico">'+s.ico+'</div><div class="sound-name">'+s.name+'</div><div class="sound-state">'+(on?'On':'Off')+'</div>';
      row.onclick=function(){toggleSound(s.id);};
      list.appendChild(row);
    });
  }
  function playChime(){
    ensureAudio();if(!ctx)return;
    var now=ctx.currentTime;
    var notes=mode==='focus'?[660,880,1175]:[880,660];
    notes.forEach(function(f,i){
      var o=ctx.createOscillator();var g=ctx.createGain();o.type='sine';o.frequency.value=f;
      var t=now+i*0.16;
      g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(0.25,t+0.02);
      g.gain.exponentialRampToValueAtTime(0.001,t+0.7);
      o.connect(g);g.connect(ctx.destination);o.start(t);o.stop(t+0.75);
    });
  }

  /* ---------- notifications ---------- */
  function notify(title,body){
    if(!settings.notify)return;
    try{ if(window.Notification&&Notification.permission==='granted'){new Notification(title,{body:body});} }catch(e){}
  }

  /* ---------- quotes ---------- */
  var quotes=[
    ["The secret of getting ahead is getting started.","Mark Twain"],
    ["It always seems impossible until it's done.","Nelson Mandela"],
    ["Focus is a matter of deciding what things you're not going to do.","John Carmack"],
    ["Small steps every day add up to big results.",""],
    ["You don't have to be great to start, but you have to start to be great.","Zig Ziglar"],
    ["Concentrate all your thoughts upon the work at hand.","Alexander Graham Bell"],
    ["Discipline is choosing between what you want now and what you want most.",""],
    ["The expert in anything was once a beginner.","Helen Hayes"],
    ["Done is better than perfect.",""],
    ["Your future is created by what you do today, not tomorrow.",""],
    ["Slow progress is still progress. Keep going.",""],
    ["Deep work is the ability to focus without distraction.","Cal Newport"]
  ];
  var qi=Math.floor(Math.random()*quotes.length);
  function showQuote(){
    var el=$('#quote');el.style.opacity=0;
    setTimeout(function(){
      var q=quotes[qi%quotes.length];qi++;
      el.innerHTML='"'+q[0]+'"'+(q[1]?'<span>— '+q[1]+'</span>':'');
      el.style.opacity=1;
    },300);
  }

  /* ---------- drawers ---------- */
  var drawers={todo:'#drawerTodo',stats:'#drawerStats',sounds:'#drawerSounds',settings:'#drawerSettings'};
  function openDrawer(key){
    closeDrawers();
    $(drawers[key]).classList.add('open');
    $('#overlay').classList.add('show');
    if(key==='stats')renderStats();
    if(key==='sounds')renderSounds();
  }
  function closeDrawers(){
    Object.keys(drawers).forEach(function(k){$(drawers[k]).classList.remove('open');});
    $('#overlay').classList.remove('show');
  }

  /* ---------- settings ui ---------- */
  function loadSettingsUI(){
    $('#setFocus').value=settings.focus;
    $('#setShort').value=settings.short;
    $('#setLong').value=settings.long;
    $('#setInterval').value=settings.interval;
    $('#setAutoBreak').checked=settings.autoBreak;
    $('#setAutoFocus').checked=settings.autoFocus;
    $('#setNotify').checked=settings.notify;
    $('#volume').value=settings.volume;
  }
  function saveSettings(){
    settings.focus=clamp($('#setFocus').value,1,180,25);
    settings.short=clamp($('#setShort').value,1,60,5);
    settings.long=clamp($('#setLong').value,1,60,15);
    settings.interval=clamp($('#setInterval').value,2,12,4);
    settings.autoBreak=$('#setAutoBreak').checked;
    settings.autoFocus=$('#setAutoFocus').checked;
    settings.notify=$('#setNotify').checked;
    store.set('ff.settings',settings);
    if(settings.notify&&window.Notification&&Notification.permission==='default'){Notification.requestPermission();}
    if(!running){total=durFor(mode);remaining=total;}
    render();
  }
  function clamp(v,min,max,def){v=parseInt(v,10);if(isNaN(v))return def;return Math.max(min,Math.min(max,v));}

  /* ---------- events ---------- */
  document.querySelectorAll('.mode').forEach(function(b){
    b.onclick=function(){if(running&&!confirm('Switch mode and stop the current timer?'))return;setMode(b.dataset.mode);};
  });
  $('#startBtn').onclick=toggle;
  $('#resetBtn').onclick=resetTimer;
  $('#skipBtn').onclick=function(){if(confirm('Skip to the next session?')){if(mode==='focus'){cycleCount++;if(cycleCount>=settings.interval){cycleCount=0;setMode('long');}else{setMode('short');}}else{setMode('focus');}}};
  $('#btnTodo').onclick=function(){openDrawer('todo');};
  $('#btnStats').onclick=function(){openDrawer('stats');};
  $('#btnSounds').onclick=function(){openDrawer('sounds');};
  $('#btnSettings').onclick=function(){loadSettingsUI();openDrawer('settings');};
  $('#btnFull').onclick=function(){if(!document.fullscreenElement){document.documentElement.requestFullscreen&&document.documentElement.requestFullscreen();}else{document.exitFullscreen&&document.exitFullscreen();}};
  $('#overlay').onclick=closeDrawers;
  document.querySelectorAll('[data-close]').forEach(function(b){b.onclick=closeDrawers;});
  $('#todoAdd').onclick=addTask;
  $('#todoText').addEventListener('keydown',function(e){if(e.key==='Enter')addTask();});
  $('#clearDone').onclick=function(){tasks=tasks.filter(function(t){return !t.done;});saveTasks();render();};
  ['setFocus','setShort','setLong','setInterval','setAutoBreak','setAutoFocus','setNotify'].forEach(function(id){
    $('#'+id).addEventListener('change',saveSettings);
  });
  $('#volume').addEventListener('input',function(){settings.volume=parseFloat(this.value);store.set('ff.settings',settings);if(master)master.gain.value=settings.volume;});
  $('#resetData').onclick=function(){
    if(confirm('This clears all tasks, stats and settings on this device. Continue?')){
      try{localStorage.removeItem('ff.tasks');localStorage.removeItem('ff.stats');localStorage.removeItem('ff.settings');localStorage.removeItem('ff.activeTask');}catch(e){}
      tasks=[];stats={days:{},totalSeconds:0,totalSessions:0};settings=Object.assign({},defaults);activeTaskId=null;cycleCount=0;
      loadSettingsUI();renderTodo();renderStats();setMode('focus');closeDrawers();
    }
  };

  document.addEventListener('keydown',function(e){
    var tag=(e.target.tagName||'').toLowerCase();
    if(tag==='input'||tag==='textarea')return;
    if(e.code==='Space'){e.preventDefault();toggle();}
    else if(e.key==='r'||e.key==='R'){resetTimer();}
    else if(e.key==='Escape'){closeDrawers();}
  });

  /* ---------- init ---------- */
  tickClock();setInterval(tickClock,1000*20);
  showQuote();setInterval(showQuote,30000);
  renderTodo();renderStats();render();

})();
