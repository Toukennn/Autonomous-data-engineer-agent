from fastapi import APIRouter
from fastapi.responses import HTMLResponse

landing_router = APIRouter()

@landing_router.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing_page() -> HTMLResponse:
    return HTMLResponse(r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Live demo of the Autonomous Data Engineer Agent.">
<title>Autonomous Data Engineer Agent · Live Demo</title>
<style>
:root{--bg:#07111f;--panel:#0f1f35;--line:#263b55;--text:#f7fbff;--muted:#9fb1c8;--a:#7dd3fc;--b:#b6a1ff;--ok:#67e8a8;--bad:#fb7185}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;background:radial-gradient(circle at 10% 0,#123354 0,transparent 27%),radial-gradient(circle at 90% 0,#2a1f55 0,transparent 25%),var(--bg);line-height:1.55}a{color:inherit;text-decoration:none}.wrap{width:min(1120px,calc(100% - 30px));margin:auto}
nav{position:sticky;top:0;z-index:20;border-bottom:1px solid var(--line);background:#07111fd9;backdrop-filter:blur(16px)}.nav{min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;align-items:center;gap:11px}.logo{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;font-weight:900;color:#06101d;background:linear-gradient(135deg,var(--a),var(--b))}.brand small{display:block;color:var(--muted)}.links{display:flex;gap:9px;flex-wrap:wrap}
.btn{border:1px solid var(--line);border-radius:12px;padding:9px 14px;background:#10233a;color:#e8f3ff;cursor:pointer;display:inline-flex;align-items:center;justify-content:center}.btn:hover{border-color:#54718f}.primary{border:0;color:#06101d;font-weight:800;background:linear-gradient(135deg,var(--a),var(--b))}
.hero{padding:76px 0 42px}.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:34px;align-items:center}.badge{display:inline-flex;gap:8px;align-items:center;border:1px solid #31526f;border-radius:999px;padding:6px 10px;color:#cdeeff;font-size:12px}.dot{width:7px;height:7px;border-radius:50%;background:var(--ok)}h1{font-size:clamp(42px,6vw,74px);line-height:.98;letter-spacing:-.055em;margin:20px 0 18px}.grad{background:linear-gradient(90deg,#fff,#8fe0ff,#c5b7ff);background-clip:text;color:transparent}.lead{font-size:18px;color:#b7c7db;max-width:760px}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:26px 0}.principle{border-left:2px solid #4ea3c8;padding-left:14px;color:#bfcee0;font-size:14px}
.panel{border:1px solid var(--line);border-radius:20px;background:#0d1d31e6;box-shadow:0 28px 80px #0005}.status{padding:22px}.status h2{font-size:17px;margin:0 0 14px}.row{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:13px 0;border-top:1px solid var(--line)}.row small{display:block;color:var(--muted)}.chip{border:1px solid var(--line);border-radius:999px;padding:5px 9px;color:var(--muted);font-size:12px}.chip.ok{color:#c9ffe4;border-color:#285941;background:#0c2a1d}.chip.bad{color:#ffd1da;border-color:#693242;background:#351321}
section{padding:42px 0}.head{max-width:760px;margin-bottom:22px}.head h2{font-size:clamp(28px,4vw,40px);letter-spacing:-.035em;margin:0 0 8px}.head p{color:var(--muted);margin:0}.flow{display:grid;grid-template-columns:repeat(7,1fr);gap:10px}.step{padding:14px;border:1px solid var(--line);border-radius:15px;background:#0c1a2c}.step b{display:block;margin:7px 0;font-size:14px}.step span{color:var(--muted);font-size:12px}.n{font-size:11px;color:var(--a);font-weight:900}.cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.card{padding:20px;border:1px solid var(--line);border-radius:17px;background:#0c1a2ccf}.card em{font-style:normal;color:var(--a);font-size:11px;font-weight:900;text-transform:uppercase;letter-spacing:.08em}.card h3{margin:7px 0}.card p{margin:0;color:var(--muted);font-size:14px}
.demo{display:grid;grid-template-columns:.9fr 1.1fr;gap:16px}.form{padding:22px}.form h3,.result h3{margin:0 0 5px}.help{color:var(--muted);font-size:13px;margin:0 0 16px}label{display:block;font-size:13px;font-weight:750;margin:14px 0 7px}input,textarea{width:100%;border:1px solid var(--line);border-radius:12px;background:#06111f;color:#fff;outline:none;padding:12px}input:focus,textarea:focus{border-color:#5ca2c5}textarea{min-height:140px;resize:vertical}.samples{display:flex;gap:7px;flex-wrap:wrap;margin-top:9px}.sample{border:1px solid var(--line);border-radius:999px;background:#122740;color:#bed0e4;padding:6px 9px;font-size:11px;cursor:pointer}.submit{margin-top:16px}.note{color:var(--muted);font-size:11px;margin-top:8px}.result{overflow:hidden;min-height:420px}.result-top{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:10px}.meta{display:flex;gap:7px;flex-wrap:wrap;padding:12px 20px;border-bottom:1px solid var(--line)}.pill{font-size:11px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:4px 7px}.body{padding:20px}.placeholder{min-height:250px;display:grid;place-items:center;text-align:center;color:var(--muted)}pre{white-space:pre-wrap;overflow-wrap:anywhere;color:#e9f3ff;font-family:inherit;line-height:1.7}.error{color:#ffd1da}
footer{padding:48px 0 60px;color:var(--muted);font-size:13px}.foot{border-top:1px solid var(--line);padding-top:22px;display:flex;justify-content:space-between;gap:14px}
@media(max-width:900px){.hero-grid,.demo{grid-template-columns:1fr}.flow{grid-template-columns:repeat(2,1fr)}.cards{grid-template-columns:repeat(2,1fr)}}@media(max-width:600px){.brand small,.docs{display:none}.hero{padding-top:50px}.flow,.cards{grid-template-columns:1fr}.actions,.foot{flex-direction:column}.btn{width:100%}}
</style>
</head>
<body>
<nav><div class="wrap nav"><a class="brand" href="/"><div class="logo">DE</div><div><b>Autonomous Data Engineer Agent</b><small>Governed agentic data engineering · v1.0.0</small></div></a><div class="links"><a class="btn docs" href="/docs">API Docs</a><a class="btn" href="https://github.com/Toukennn/Autonomous-data-engineer-agent" target="_blank" rel="noreferrer">GitHub ↗</a></div></div></nav>

<main>
<div class="wrap hero"><div class="hero-grid"><div>
<div class="badge"><span class="dot"></span>Live cloud deployment</div>
<h1>Data engineering,<br><span class="grad">agentic by design.</span></h1>
<p class="lead">A governed platform that turns natural-language intent into bounded ETL workflows and safe warehouse analytics across APIs, PostgreSQL, dbt, and SQLGlot.</p>
<div class="actions"><a class="btn primary" href="#demo">Try the live API</a><a class="btn" href="#how">See how it works</a><a class="btn" href="/docs">Open Swagger</a></div>
<div class="principle"><b>Design principle:</b> LLMs decide what should happen. Deterministic code decides how it is allowed to happen.</div>
</div>
<aside class="panel status"><h2>Deployment status</h2>
<div class="row"><div><b>API process</b><small>FastAPI liveness</small></div><span id="health" class="chip">Checking</span></div>
<div class="row"><div><b>Dependencies</b><small>Storage + PostgreSQL</small></div><span id="ready" class="chip">Checking</span></div>
<div class="row"><div><b>Query boundary</b><small>Protected execution</small></div><span class="chip ok">API-key protected</span></div>
<div class="row"><div><b>Warehouse</b><small>Managed PostgreSQL</small></div><span class="chip ok">Private</span></div>
</aside></div></div>

<section id="how"><div class="wrap"><div class="head"><h2>From prompt to governed data product</h2><p>The model plans and routes. Deterministic code owns persistence, transformations, validation, and database execution.</p></div>
<div class="flow">
<div class="step"><span class="n">01</span><b>Natural language</b><span>ETL or analytics intent</span></div>
<div class="step"><span class="n">02</span><b>LangGraph</b><span>Routes to specialist agent</span></div>
<div class="step"><span class="n">03</span><b>Bronze</b><span>Durable validated ingestion</span></div>
<div class="step"><span class="n">04</span><b>PostgreSQL</b><span>Controlled warehouse loading</span></div>
<div class="step"><span class="n">05</span><b>dbt</b><span>Silver + Gold models</span></div>
<div class="step"><span class="n">06</span><b>SQLGlot</b><span>AST + allowlist validation</span></div>
<div class="step"><span class="n">07</span><b>Answer</b><span>Read-only governed analytics</span></div>
</div></div></section>

<section><div class="wrap"><div class="head"><h2>What is actually engineered here?</h2><p>The demo is backed by a real data platform, not a chat-only mockup.</p></div>
<div class="cards">
<div class="card"><em>Ingestion</em><h3>Resilient API pipelines</h3><p>Retries, pagination bounds, response limits, SSRF checks, incremental state, and schema evolution.</p></div>
<div class="card"><em>Warehouse</em><h3>PostgreSQL + dbt</h3><p>Business-key-aware Bronze loading, generated Silver/Gold models, quality tests, and incremental processing.</p></div>
<div class="card"><em>Governance</em><h3>SQL cannot approve itself</h3><p>LLM-generated SQL is parsed and checked against a governed catalog before read-only execution.</p></div>
<div class="card"><em>Reliability</em><h3>Explicit runtime boundaries</h3><p>Liveness/readiness, bounded concurrency, request timeouts, failure-stop behavior, and CI.</p></div>
<div class="card"><em>Observability</em><h3>Traceable executions</h3><p>Request IDs, run IDs, structured safe logs, durable execution records, lineage, and dbt artifacts.</p></div>
<div class="card"><em>Deployment</em><h3>Real cloud environment</h3><p>Dockerized FastAPI on Railway, private PostgreSQL, persistent storage, and HTTPS.</p></div>
</div></div></section>

<section id="demo"><div class="wrap"><div class="head"><h2>Live governed query</h2><p>Authorized reviewers can call the deployed agent directly. The key is not embedded in this page.</p></div>
<div class="demo">
<form id="form" class="panel form"><h3>Ask the data platform</h3><p class="help">Use a real deployed Silver/Gold dataset name.</p>
<label for="key">API key</label><input id="key" type="password" autocomplete="off" placeholder="Paste an authorized demo key" required>
<label for="message">Request</label><textarea id="message" placeholder="How many rows are in the Gold dataset ...?" required></textarea>
<div class="samples">
<button class="sample" type="button" data-prompt="How many rows are in the Gold dataset dbt_dev_gold.mart_YOUR_DATASET? Use the governed warehouse analytics path.">Row count</button>
<button class="sample" type="button" data-prompt="Return email and phone from the Gold dataset dbt_dev_gold.mart_YOUR_DATASET. Use the governed warehouse analytics path.">Inspect Gold</button>
</div>
<button id="go" class="btn primary submit" type="submit">Run query</button>
<div class="note">This page does not persist your API key.</div>
</form>

<div class="panel result"><div class="result-top"><div><h3>Agent response</h3><p class="help" style="margin:0">HTTP result + correlation metadata</p></div><span id="result-status" class="chip">Waiting</span></div>
<div class="meta"><span id="http" class="pill">HTTP —</span><span id="time" class="pill">Duration —</span><span id="request" class="pill">Request ID —</span><span id="run" class="pill">Run ID —</span></div>
<div class="body"><div id="placeholder" class="placeholder"><div><b>Your result will appear here.</b><p>The backend still enforces authentication, concurrency, SQL safety, and warehouse governance.</p></div></div><pre id="answer" hidden></pre></div>
</div>
</div></div></section>
</main>

<footer><div class="wrap foot"><span>Autonomous Data Engineer Agent · Portfolio v1</span><span><a href="/docs">Swagger</a> · <a href="https://github.com/Toukennn/Autonomous-data-engineer-agent" target="_blank" rel="noreferrer">Source on GitHub</a></span></div></footer>

<script>
function chip(el,ok,good,bad){el.className="chip "+(ok?"ok":"bad");el.textContent=ok?good:bad}
async function status(path,id,text){const el=document.getElementById(id);try{const r=await fetch(path,{cache:"no-store"});chip(el,r.ok,text,"Unavailable")}catch(e){chip(el,false,text,"Unavailable")}}
status("/health","health","Online");status("/ready","ready","Ready");
document.querySelectorAll(".sample").forEach(b=>b.onclick=()=>{message.value=b.dataset.prompt;message.focus()});
const form=document.getElementById("form"),go=document.getElementById("go"),answer=document.getElementById("answer"),placeholder=document.getElementById("placeholder"),rs=document.getElementById("result-status");
form.onsubmit=async(e)=>{e.preventDefault();const key=document.getElementById("key").value.trim(),msg=document.getElementById("message").value.trim();if(!key||!msg)return;go.disabled=true;go.textContent="Running…";rs.className="chip";rs.textContent="Running";answer.hidden=true;placeholder.hidden=false;const start=performance.now();
try{const r=await fetch("/query",{method:"POST",headers:{"Content-Type":"application/json","X-API-Key":key},body:JSON.stringify({message:msg})});let p;try{p=await r.json()}catch(e){p={detail:"Non-JSON response"}}document.getElementById("http").textContent="HTTP "+r.status;document.getElementById("time").textContent="Duration "+Math.round(performance.now()-start)+" ms";document.getElementById("request").textContent="Request ID "+(r.headers.get("X-Request-ID")||"—");document.getElementById("run").textContent="Run ID "+(r.headers.get("X-Run-ID")||"—");placeholder.hidden=true;answer.hidden=false;answer.className=r.ok?"":"error";answer.textContent=r.ok?(p.response||JSON.stringify(p,null,2)):(typeof p.detail==="string"?p.detail:JSON.stringify(p,null,2));chip(rs,r.ok,"Completed","Rejected / failed")}catch(e){placeholder.hidden=true;answer.hidden=false;answer.className="error";answer.textContent="The request could not reach the API.";chip(rs,false,"Completed","Network error")}finally{go.disabled=false;go.textContent="Run query"}};
</script>
</body></html>""")
