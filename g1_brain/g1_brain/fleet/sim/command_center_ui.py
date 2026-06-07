"""Operator-facing control-center page for command_center (served at GET /).

Vanilla HTML+JS, no build step. Polls /world (~8 Hz) to draw a live top-down 2D
map of the shared world (robot dots + heading + the rendezvous point + live
separation), POSTs /command to send a natural-language request to the codex
commander, and polls /events for the commander's decisions + execution log. The
3D physics view is the separate MuJoCo window (launched with --viewer)."""

INDEX_HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 指挥调度中心 · Command Center</title>
<style>
  :root { color-scheme: dark; }
  body { font:14px/1.5 system-ui,sans-serif; margin:0; background:#0e1116; color:#e6edf3; }
  header { padding:14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; font-weight:600; }
  .dot { width:9px; height:9px; border-radius:50%; background:#3fb950; display:inline-block; }
  .muted { color:#8b949e; font-size:12px; }
  main { padding:18px 20px; display:grid; gap:18px; max-width:1040px;
         grid-template-columns:minmax(0,1fr); }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:#8b949e; margin:0 0 12px; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  input { flex:1; background:#0e1116; color:#e6edf3; border:1px solid #30363d;
          border-radius:6px; padding:7px 10px; font-size:14px; }
  button { background:#1f6feb; color:#fff; border:1px solid #1f6feb; border-radius:6px;
           padding:6px 14px; font-size:13px; cursor:pointer; } button:hover{ filter:brightness(1.1); }
  .chip { display:inline-block; padding:1px 8px; border-radius:999px; font-size:11px; font-weight:600;
          background:#1b2a17; color:#3fb950; }
  #chatlog div, #ticker div { padding:3px 0; border-bottom:1px solid #1b2027; }
  #chatlog { margin-top:10px; font-size:13px; max-height:240px; overflow:auto; }
  #ticker { font-family:ui-monospace,monospace; font-size:12px; max-height:200px; overflow:auto; }
  .thinking { color:#d29922; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  td,th { text-align:left; padding:3px 8px; border-bottom:1px solid #1b2027; }
  .empty { color:#6e7681; font-style:italic; }
  svg text { fill:#8b949e; font-size:11px; }
</style>
</head>
<body>
<header>
  <span class="dot" id="live"></span>
  <h1>AI 指挥调度中心 · Command Center</h1>
  <span class="muted" id="meta">connecting…</span>
</header>
<main>
  <div class="card">
    <h2>实时俯视图 — live top-down</h2>
    <svg id="map" viewBox="-280 -210 560 420" style="width:100%;max-height:430px;background:#0b0e13;border-radius:8px"></svg>
    <div class="muted" id="status" style="margin-top:8px"></div>
  </div>
  <div class="card">
    <h2>AI 指挥官 — 说出你的想法 (codex)</h2>
    <div class="row">
      <input id="chatin" placeholder="例: 两机到中间会合，然后 g1_a 把巡逻交给 g1_b"
             onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()">发送</button>
    </div>
    <div id="chatlog"></div>
  </div>
  <div class="card"><h2>事件流 — 调度 / 执行</h2><div id="ticker"></div></div>
  <div class="card"><h2>遥测 — telemetry</h2><div id="tele"></div></div>
</main>
<script>
const $ = id => document.getElementById(id);
const SC = 72;                                   // px per metre
const COLORS = ['#58a6ff','#3fb950','#d2a8ff','#f0883e'];
const fx = x => x*SC, fy = y => -y*SC;           // world -> svg (y up)
let order = [];                                  // stable colour assignment

function drawMap(robots, mission){
  let s = '';
  // grid crosshair + 1 m rings
  s += `<line x1="-280" y1="0" x2="280" y2="0" stroke="#1b2027"/>`;
  s += `<line x1="0" y1="-210" x2="0" y2="210" stroke="#1b2027"/>`;
  for(const r of [1,2]) s += `<circle cx="0" cy="0" r="${r*SC}" fill="none" stroke="#161b22"/>`;
  // rendezvous point
  if(mission && mission.point){
    const px=fx(mission.point[0]), py=fy(mission.point[1]);
    s += `<g><circle cx="${px}" cy="${py}" r="9" fill="none" stroke="#d29922" stroke-dasharray="3 3"/>`+
         `<text x="${px+11}" y="${py+4}" style="fill:#d29922">集合点</text></g>`;
  }
  // separation line between first two robots
  if(robots.length>=2){
    const a=robots[0], b=robots[1];
    const d=Math.hypot(a.x-b.x,a.y-b.y).toFixed(2);
    s += `<line x1="${fx(a.x)}" y1="${fy(a.y)}" x2="${fx(b.x)}" y2="${fy(b.y)}" `+
         `stroke="#30363d" stroke-dasharray="4 4"/>`+
         `<text x="${(fx(a.x)+fx(b.x))/2}" y="${(fy(a.y)+fy(b.y))/2-6}">${d} m</text>`;
  }
  for(const rb of robots){
    if(!order.includes(rb.robot_id)) order.push(rb.robot_id);
    const col = COLORS[order.indexOf(rb.robot_id)%COLORS.length];
    const x=fx(rb.x), y=fy(rb.y);
    const hx=x+Math.cos(rb.yaw)*20, hy=y-Math.sin(rb.yaw)*20;
    const cur = mission && mission.cur ? (mission.cur[rb.robot_id]||'') : '';
    s += `<g><line x1="${x}" y1="${y}" x2="${hx}" y2="${hy}" stroke="${col}" stroke-width="3"/>`+
         `<circle cx="${x}" cy="${y}" r="11" fill="${col}"/>`+
         `<text x="${x+14}" y="${y-10}" style="fill:${col};font-weight:700">${rb.robot_id}</text>`+
         `<text x="${x+14}" y="${y+5}">${rb.posture||''} ${cur}</text></g>`;
  }
  $('map').innerHTML = s;
}

async function world(){
  try{
    const b = await (await fetch('/world')).json();
    $('live').style.background='#3fb950';
    let mtxt = `${b.robots.length} robot(s) · ${new Date().toLocaleTimeString()}`;
    if(b.mission){
      mtxt += ` · <span class="chip">${b.mission.type}</span> ${b.mission.summary}`
            + (b.mission.complete?' ✓':' …');
    }
    $('meta').innerHTML = mtxt;
    drawMap(b.robots, b.mission);
    $('status').innerHTML = b.mission
      ? `任务: <b>${b.mission.summary}</b> [${b.mission.type}]`
        + (b.mission.min_sep!=null?` · 最近间距 ${b.mission.min_sep} m`:'')
        + (b.mission.complete?' · <span style="color:#3fb950">已完成</span>':' · 执行中')
      : '<span class="empty">等待指令…</span>';
    $('tele').innerHTML = '<table><tr><th>机器人</th><th>x</th><th>y</th><th>朝向</th><th>姿态</th></tr>'
      + b.robots.map(r=>`<tr><td><b>${r.robot_id}</b></td><td>${r.x.toFixed(2)}</td>`
        + `<td>${r.y.toFixed(2)}</td><td>${(r.yaw*57.3).toFixed(0)}°</td><td>${r.posture||''}</td></tr>`).join('')
      + '</table>';
  }catch(e){ $('live').style.background='#f85149'; $('meta').textContent='command center unreachable'; }
}
async function events(){
  try{
    const b = await (await fetch('/events')).json();
    const evs = b.events.slice(-16).reverse();
    $('ticker').innerHTML = evs.length
      ? evs.map(e=>`<div><span class="muted">${e.ts}</span> ${e.msg}</div>`).join('')
      : '<div class="empty">尚无事件</div>';
  }catch(e){}
}
function add(html){ const e=$('chatlog'); e.innerHTML='<div>'+html+'</div>'+e.innerHTML; }
async function send(){
  const el=$('chatin'); const nl=el.value.trim(); if(!nl) return; el.value='';
  add('<b>你</b> '+nl);
  const id='t'+Math.random().toString(36).slice(2);
  add(`<span class="thinking" id="${id}">指挥官思考中…</span>`);
  try{
    const b = await (await fetch('/command',{method:'POST',
      headers:{'content-type':'application/json'},body:JSON.stringify({nl})})).json();
    const t=document.getElementById(id); if(t) t.parentElement.remove();
    if(!b.ok){ add('<span class="thinking">指挥官</span> '+(b.needs_clarification||b.reason||'无法执行')); return; }
    let s='<span style="color:#3fb950">指挥官</span> '+b.plan.summary+' <span class="muted">['+b.plan.coordination.type+']</span>';
    for(const rid in b.ops){ s+='<br>&nbsp;&nbsp;<b>'+rid+'</b>: '+b.ops[rid].map(o=>o.op).join(' → '); }
    add(s); world();
  }catch(e){ const t=document.getElementById(id); if(t) t.parentElement.remove(); add('<span class="thinking">指挥官</span> 错误 '+e); }
}
world(); events(); setInterval(world,125); setInterval(events,1000);
</script>
</body>
</html>
"""
