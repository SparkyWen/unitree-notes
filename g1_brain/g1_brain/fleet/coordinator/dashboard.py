"""Self-contained web dashboard for the coordinator (served at GET /).

Vanilla HTML+JS, no build step, no extra deps. Polls the existing JSON API
(/robots, /dispatch, /anomalies) and issues operator commands via POST
/commands. Same-origin, so no CORS. This is the browser "see the fleet" view;
the 3D robots live in the MuJoCo windows (instructions §7.5).
"""

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fleet Coordinator — 指挥调度中心</title>
<style>
  :root { color-scheme: dark; }
  body { font: 14px/1.5 system-ui, sans-serif; margin: 0; background:#0e1116; color:#e6edf3; }
  header { padding: 14px 20px; background:#161b22; border-bottom:1px solid #30363d;
           display:flex; align-items:center; gap:16px; flex-wrap:wrap; }
  header h1 { font-size:17px; margin:0; font-weight:600; }
  header .dot { width:9px; height:9px; border-radius:50%; background:#3fb950; display:inline-block; }
  header .muted { color:#8b949e; font-size:12px; }
  main { padding: 18px 20px; display:grid; gap:18px; max-width:1100px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:#8b949e;
             margin:0 0 10px; }
  table { width:100%; border-collapse:collapse; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #21262d; white-space:nowrap; }
  th { color:#8b949e; font-weight:600; font-size:12px; }
  .pill { padding:2px 8px; border-radius:999px; font-size:12px; font-weight:600; }
  .online { background:#162e1a; color:#3fb950; } .stale { background:#3a2d12; color:#d29922; }
  .offline,.unknown { background:#30181a; color:#f85149; }
  .fsm-STANDING{color:#3fb950;} .fsm-DORMANT{color:#8b949e;} .fsm-ACTING{color:#58a6ff;}
  .fsm-EMERGENCY_STOP,.fsm-FAULT{color:#f85149;}
  .hot { color:#f85149; font-weight:700; } .warn { color:#d29922; }
  button { background:#21262d; color:#e6edf3; border:1px solid #30363d; border-radius:6px;
           padding:5px 10px; font-size:12px; cursor:pointer; }
  button:hover { background:#30363d; } button.danger { border-color:#71242a; color:#f85149; }
  button.primary { background:#1f6feb; border-color:#1f6feb; color:#fff; }
  .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
  .anom { padding:6px 10px; border-left:3px solid #f85149; background:#1b1417; margin:6px 0;
          border-radius:4px; font-size:13px; }
  .anom.warning { border-left-color:#d29922; }
  #log { font-family:ui-monospace,monospace; font-size:12px; color:#8b949e; max-height:140px;
         overflow:auto; white-space:pre-wrap; }
  .empty { color:#6e7681; font-style:italic; }
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
    <h2>Fleet · 机器人</h2>
    <table><thead><tr>
      <th>robot</th><th>status</th><th>fsm</th><th>posture</th><th>battery °C</th>
      <th>soc</th><th>health</th><th>actions</th>
    </tr></thead><tbody id="robots"></tbody></table>
  </div>
  <div class="card">
    <h2>Dispatch · 任务分配</h2>
    <div id="dispatch" class="row"></div>
  </div>
  <div class="card">
    <h2>Anomalies · 异常</h2>
    <div id="anomalies"></div>
  </div>
  <div class="card">
    <h2>Command log</h2>
    <div id="log"></div>
  </div>
</main>
<script>
const $ = id => document.getElementById(id);
function logln(s){ const el=$('log'); el.textContent = `[${new Date().toLocaleTimeString()}] ${s}\n` + el.textContent; }
async function cmd(body){
  try{ const r = await fetch('/commands',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)});
       logln(JSON.stringify(body)+' -> '+JSON.stringify(await r.json())); refresh(); }
  catch(e){ logln('ERROR '+e); }
}
function fmtTemp(t){ if(t==null) return '?'; const c=Math.round(t*10)/10; return c>=70?`<span class="hot">${c}</span>`:c>=50?`<span class="warn">${c}</span>`:c; }
async function refresh(){
  try{
    const [robots, dispatch, anomalies] = await Promise.all([
      fetch('/robots').then(r=>r.json()),
      fetch('/dispatch').then(r=>r.json()),
      fetch('/anomalies').then(r=>r.json()),
    ]);
    $('live').style.background='#3fb950';
    $('meta').textContent = `${robots.length} robot(s) · ${new Date().toLocaleTimeString()}`;
    // robots
    $('robots').innerHTML = robots.length ? robots.map(r=>{
      const st=r.state||{}, core=st.core||{}, batt=core.battery||{}, ext=(st.extensions||{}).g1_sim||{};
      const health=(core.health||{}).level||'?';
      const soc=batt.soc!=null?Math.round(batt.soc*100)+'%':'?';
      const hc = health==='ok'?'':health==='warning'?'warn':'hot';
      return `<tr>
        <td><b>${r.robot_id}</b></td>
        <td><span class="pill ${r.status}">${r.status}</span></td>
        <td class="fsm-${st.fsm_state}">${st.fsm_state||'?'}</td>
        <td>${ext.posture||'-'}</td>
        <td>${fmtTemp(batt.temperature_c)}</td>
        <td>${soc}</td>
        <td class="${hc}">${health}</td>
        <td class="row">
          <button onclick="cmd({op:'sleep',args:{robot:'${r.robot_id}'}})">sleep</button>
          <button onclick="cmd({op:'wake',args:{robot:'${r.robot_id}'}})">wake</button>
          <button class="danger" onclick="cmd({op:'inject',robot:'${r.robot_id}',battery_temperature_c:75,fault:'battery_hot'})">inject 75°C</button>
        </td></tr>`;
    }).join('') : '<tr><td colspan="8" class="empty">no robots connected — start robot nodes (instructions §7.5)</td></tr>';
    // dispatch
    const a=dispatch.assignments||{}; const keys=Object.keys(a);
    let d = keys.length ? keys.map(k=>`<span class="pill online">${k} → ${a[k]}</span>`).join(' ') : '<span class="empty">no active assignments</span>';
    if((dispatch.needs_operator||[]).length) d += ` &nbsp; <span class="pill offline">needs operator: ${dispatch.needs_operator.join(', ')}</span>`;
    $('dispatch').innerHTML = d;
    // anomalies
    const an=anomalies.anomalies||[];
    $('anomalies').innerHTML = an.length ? an.map(x=>`<div class="anom ${x.severity}"><b>${x.robot_id}</b> ${x.kind} <span class="muted">(${Object.entries(x.evidence||{}).map(([k,v])=>k+'='+v).join(', ')})</span></div>`).join('') : '<div class="empty">none</div>';
  }catch(e){ $('live').style.background='#f85149'; $('meta').textContent='coordinator unreachable'; }
}
refresh(); setInterval(refresh, 1000);
</script>
</body>
</html>
"""
