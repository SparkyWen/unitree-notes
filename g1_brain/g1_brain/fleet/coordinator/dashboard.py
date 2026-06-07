"""Self-contained web dashboard for the coordinator (served at GET /).

Vanilla HTML+JS, no build step, no extra deps. Polls the existing JSON API
(/robots, /dispatch, /anomalies, /events) and issues operator commands via POST
/commands. Renders a *live animated figure per robot* (posture-driven: standing /
patrolling-wave / crouched-sleep) plus a live event ticker, so you can see what
the fleet is doing in real time without any MuJoCo window. (The 3D physics view
is the separate MuJoCo GUI windows; see instructions §7.5.)
"""

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fleet Coordinator — 指挥调度中心</title>
<style>
  :root { color-scheme: dark; }
  body { font: 14px/1.5 system-ui, sans-serif; margin:0; background:#0e1116; color:#e6edf3; }
  header { padding:14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; font-weight:600; }
  .dot { width:9px; height:9px; border-radius:50%; background:#3fb950; display:inline-block; }
  .muted { color:#8b949e; font-size:12px; }
  main { padding:18px 20px; display:grid; gap:18px; max-width:1100px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:#8b949e; margin:0 0 12px; }
  .fleet { display:flex; gap:16px; flex-wrap:wrap; }
  .bot { width:180px; background:#0e1116; border:1px solid #30363d; border-radius:10px;
         padding:12px; text-align:center; }
  .bot .name { font-weight:700; font-size:15px; }
  .bot .act { font-size:12px; min-height:16px; margin:2px 0 6px; }
  .bot .stats { font-size:12px; color:#8b949e; }
  .bot .btns { display:flex; gap:5px; justify-content:center; margin-top:8px; flex-wrap:wrap; }
  .pill { padding:1px 7px; border-radius:999px; font-size:11px; font-weight:600; }
  .online{background:#162e1a;color:#3fb950;} .stale{background:#3a2d12;color:#d29922;}
  .offline,.unknown{background:#30181a;color:#f85149;}
  .hot{color:#f85149;font-weight:700;} .warn{color:#d29922;}
  button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;
         padding:4px 9px;font-size:12px;cursor:pointer;} button:hover{background:#30363d;}
  button.danger{border-color:#71242a;color:#f85149;} button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff;}
  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
  .anom{padding:6px 10px;border-left:3px solid #f85149;background:#1b1417;margin:6px 0;border-radius:4px;font-size:13px;}
  .anom.warning{border-left-color:#d29922;}
  #ticker{font-family:ui-monospace,monospace;font-size:12px;max-height:220px;overflow:auto;}
  #ticker div{padding:2px 0;border-bottom:1px solid #1b2027;}
  .ev-anomaly_detected{color:#f85149;} .ev-task_reassigned{color:#d2a8ff;}
  .ev-robot_sleeping{color:#8b949e;} .ev-robot_resumed,.ev-task_assigned{color:#3fb950;}
  .ev-command_issued{color:#58a6ff;} .ev-command_refused{color:#f0883e;}
  .empty{color:#6e7681;font-style:italic;}
  .wave{animation:wave .6s ease-in-out infinite alternate;transform-origin:40px 36px;}
  @keyframes wave{to{transform:rotate(-28deg);}}
  #log{font-family:ui-monospace,monospace;font-size:12px;color:#8b949e;max-height:90px;overflow:auto;white-space:pre-wrap;}
</style>
</head>
<body>
<header>
  <span class="dot" id="live"></span>
  <h1>Fleet Coordinator · 指挥调度中心</h1>
  <span class="muted" id="meta">connecting…</span>
  <span style="flex:1"></span>
  <button class="primary" onclick="cmd({op:'dispatch',args:{task:'patrol'}})">▶ Dispatch patrol</button>
</header>
<main>
  <div class="card">
    <h2>Fleet — live 机器人(姿态实时)</h2>
    <div class="fleet" id="fleet"></div>
  </div>
  <div class="card">
    <h2>AI 指挥官 — 自然语言调度 (OpenAI)</h2>
    <div class="row">
      <input id="chatin" style="flex:1;background:#0e1116;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:6px 9px"
             placeholder="例: 两机到中间会合，然后 g1_a 把巡逻交给 g1_b" onkeydown="if(event.key==='Enter')chat()">
      <button class="primary" onclick="chat()">发送</button>
    </div>
    <div id="chatlog" style="margin-top:10px;font-size:13px;max-height:240px;overflow:auto"></div>
  </div>
  <div class="card"><h2>Activity — 实时事件流</h2><div id="ticker"></div></div>
  <div class="card"><h2>Dispatch — 任务分配</h2><div id="dispatch" class="row"></div></div>
  <div class="card"><h2>Anomalies — 异常</h2><div id="anomalies"></div></div>
  <div class="card"><h2>Command log</h2><div id="log"></div></div>
</main>
<script>
const $ = id => document.getElementById(id);
function logln(s){ const e=$('log'); e.textContent=`[${new Date().toLocaleTimeString()}] ${s}\n`+e.textContent; }
async function cmd(b){ try{ const r=await fetch('/commands',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(b)});
  logln(JSON.stringify(b)+' -> '+JSON.stringify(await r.json())); refresh(); }catch(e){ logln('ERROR '+e); } }
function tempHtml(t){ if(t==null) return '?'; const c=Math.round(t*10)/10; return c>=70?`<span class="hot">${c}°C</span>`:c>=50?`<span class="warn">${c}°C</span>`:c+'°C'; }

// posture-driven schematic humanoid
function figure(posture, health){
  const col = health==='ok'?'#3fb950':health==='warning'?'#d29922':'#f85149';
  if(posture==='SLEEP'){
    return `<svg viewBox="0 0 80 100" width="64" height="80"><g stroke="${col}" stroke-width="3" fill="none" stroke-linecap="round" opacity="0.55">
      <circle cx="40" cy="58" r="9" fill="${col}"/><line x1="40" y1="67" x2="40" y2="80"/>
      <line x1="40" y1="71" x2="27" y2="79"/><line x1="40" y1="71" x2="53" y2="79"/>
      <line x1="40" y1="80" x2="25" y2="76"/><line x1="40" y1="80" x2="55" y2="76"/></g></svg>`;
  }
  const patrol = posture==='PATROL';
  const larm = patrol ? 'x2="22" y2="22" class="wave"' : 'x2="24" y2="50"';
  return `<svg viewBox="0 0 80 100" width="64" height="80"><g stroke="${col}" stroke-width="3" fill="none" stroke-linecap="round">
    <circle cx="40" cy="18" r="10" fill="${col}"/><line x1="40" y1="28" x2="40" y2="60"/>
    <line x1="40" y1="36" ${larm}/><line x1="40" y1="36" x2="56" y2="50"/>
    <line x1="40" y1="60" x2="30" y2="86"/><line x1="40" y1="60" x2="50" y2="86"/></g></svg>`;
}
function activity(st){
  const p=(st.extensions||{}).g1_sim||{}; const post=p.posture; const fsm=st.fsm_state;
  if(fsm==='DORMANT') return '😴 sleeping (safe)';
  if(post==='PATROL') return '🚶 patrolling';
  if(post==='IDLE'||post==='STOP') return '⏸ idle';
  return '🧍 standing';
}
async function refresh(){
  try{
    const [robots,dispatch,anomalies,events] = await Promise.all([
      fetch('/robots').then(r=>r.json()), fetch('/dispatch').then(r=>r.json()),
      fetch('/anomalies').then(r=>r.json()), fetch('/events?limit=40').then(r=>r.json())]);
    $('live').style.background='#3fb950';
    $('meta').textContent=`${robots.length} robot(s) · ${new Date().toLocaleTimeString()}`;
    $('fleet').innerHTML = robots.length ? robots.map(r=>{
      const st=r.state||{},core=st.core||{},batt=core.battery||{},ext=(st.extensions||{}).g1_sim||{};
      const health=(core.health||{}).level||'ok'; const soc=batt.soc!=null?Math.round(batt.soc*100)+'%':'?';
      return `<div class="bot">
        ${figure(ext.posture, health)}
        <div class="name">${r.robot_id}</div>
        <div class="act">${activity(st)}</div>
        <div><span class="pill ${r.status}">${r.status}</span> <span class="muted">${st.fsm_state||'?'}</span></div>
        <div class="stats">batt ${tempHtml(batt.temperature_c)} · soc ${soc} · ${health}</div>
        <div class="btns">
          <button onclick="cmd({op:'sleep',args:{robot:'${r.robot_id}'}})">sleep</button>
          <button onclick="cmd({op:'wake',args:{robot:'${r.robot_id}'}})">wake</button>
          <button class="danger" onclick="cmd({op:'inject',robot:'${r.robot_id}',battery_temperature_c:75,fault:'battery_hot'})">🔥75°C</button>
        </div></div>`;
    }).join('') : '<span class="empty">no robots connected — run: python -m g1_brain.fleet.sim.verify_dds_fleet --keep-alive</span>';

    const LIFE=new Set(['anomaly_detected','command_issued','command_accepted','command_refused','task_assigned','task_reassigned','robot_sleeping','robot_resumed','lease_expired']);
    const evs=events.filter(e=>LIFE.has(e.type)).slice(-14).reverse();
    $('ticker').innerHTML = evs.length ? evs.map(e=>{
      const t=(e.ts||'').slice(11,19); const p=e.payload||{};
      const extra=p.capability||p.kind||p.reason_code||(p.to?('→ '+p.to):'')||'';
      return `<div class="ev-${e.type}"><span class="muted">${t}</span> <b>${e.robot_id}</b> ${e.type} <span class="muted">${extra}</span></div>`;
    }).join('') : '<div class="empty">no events yet — dispatch a patrol or inject an overheat</div>';

    const a=dispatch.assignments||{},k=Object.keys(a);
    let d=k.length?k.map(x=>`<span class="pill online">${x} → ${a[x]}</span>`).join(' '):'<span class="empty">no active assignments</span>';
    if((dispatch.needs_operator||[]).length) d+=` &nbsp; <span class="pill offline">needs operator: ${dispatch.needs_operator.join(', ')}</span>`;
    $('dispatch').innerHTML=d;
    const an=anomalies.anomalies||[];
    $('anomalies').innerHTML=an.length?an.map(x=>`<div class="anom ${x.severity}"><b>${x.robot_id}</b> ${x.kind} <span class="muted">(${Object.entries(x.evidence||{}).map(([k,v])=>k+'='+v).join(', ')})</span></div>`).join(''):'<div class="empty">none</div>';
  }catch(e){ $('live').style.background='#f85149'; $('meta').textContent='coordinator unreachable'; }
}
function add(html){ const e=$('chatlog'); e.innerHTML='<div style="padding:3px 0;border-bottom:1px solid #1b2027">'+html+'</div>'+e.innerHTML; }
async function chat(){
  const el=$('chatin'); const nl=el.value.trim(); if(!nl) return; el.value='';
  add('<b>你</b> '+nl);
  try{
    const r=await fetch('/chat',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({nl})});
    const b=await r.json();
    if(!b.ok){ add('<span class="warn">指挥官</span> '+(b.needs_clarification||b.reason||'无法执行')); return; }
    let s='<span style="color:#3fb950">指挥官</span> '+b.plan.summary+' <span class="muted">['+b.plan.coordination.type+']</span>';
    for(const rid in b.ops){ s+='<br>&nbsp;&nbsp;<b>'+rid+'</b>: '+b.ops[rid].map(o=>o.op).join(' → '); }
    add(s);
  }catch(e){ add('<span class="warn">指挥官</span> 错误 '+e); }
}
refresh(); setInterval(refresh,1000);
</script>
</body>
</html>
"""
