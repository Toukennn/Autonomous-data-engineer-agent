from fastapi import APIRouter
from fastapi.responses import HTMLResponse


landing_router = APIRouter()


@landing_router.get(
    "/",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def landing_page() -> HTMLResponse:
    return HTMLResponse(
        r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="Live demo of the Autonomous Data Engineer Agent.">
<title>Autonomous Data Engineer Agent</title>
<style>
:root{--bg:#07111f;--panel:#0c192b;--panel2:#101f34;--line:#263950;--text:#f8fbff;--muted:#9cafc6;--accent:#7dd3fc;--accent2:#b7a7ff;--ok:#65e7a8;--warn:#f7c96b;--bad:#fb7185;--shadow:0 24px 70px #0006}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(circle at 16% -10%,#14375a 0,transparent 30%),radial-gradient(circle at 90% 0,#2c2258 0,transparent 27%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;line-height:1.5}a{color:var(--accent);text-decoration:none}button,input,textarea{font:inherit}.wrap{width:min(980px,calc(100% - 28px));margin:auto}
header{padding:52px 0 32px;border-bottom:1px solid #203247}.header-lines h1{margin:0;font-size:clamp(32px,5vw,50px);letter-spacing:-.045em}.header-lines p{margin:8px 0;color:#c0cee0;font-size:17px}.header-lines a{display:inline-block;margin-top:4px;font-size:14px}
main{padding:32px 0 70px}.shell{display:grid;gap:18px}.card{border:1px solid var(--line);border-radius:18px;background:#0b192ae8;box-shadow:var(--shadow)}.control-card{padding:22px}.label-row{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:8px}.label-row label{font-weight:750;font-size:13px}.saved{font-size:11px;color:var(--muted)}.saved.ok{color:var(--ok)}input,textarea{width:100%;border:1px solid var(--line);border-radius:12px;background:#06101d;color:#fff;padding:12px;outline:none}input:focus,textarea:focus{border-color:#5e99bb;box-shadow:0 0 0 3px #7dd3fc12}textarea{min-height:155px;resize:vertical}.seg{display:grid;grid-template-columns:1fr 1fr;gap:5px;background:#07111f;border:1px solid var(--line);border-radius:13px;padding:4px;margin:18px 0}.seg button{border:0;border-radius:9px;padding:10px 12px;background:transparent;color:var(--muted);cursor:pointer;font-weight:750}.seg button.active{color:#07111f;background:linear-gradient(135deg,var(--accent),var(--accent2))}.mode{display:none}.mode.active{display:block}.hint{color:var(--muted);font-size:12px;margin:6px 0 0}.examples{display:flex;gap:7px;flex-wrap:wrap;margin-top:10px}.example{border:1px solid var(--line);border-radius:999px;background:#10233a;color:#c9d8e9;padding:7px 10px;font-size:11px;cursor:pointer}.example:hover{border-color:#507292}.example.blocked{color:#ffd796;border-color:#65502f}.field{margin-top:16px}.run-row{display:flex;align-items:center;gap:12px;margin-top:18px}.run{border:0;border-radius:12px;padding:11px 18px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#06101d;font-weight:850;cursor:pointer;min-width:128px}.run:disabled{opacity:.55;cursor:wait}.elapsed{font-variant-numeric:tabular-nums;color:#c4d3e4;font-size:13px}.small{font-size:11px;color:var(--muted)}
.run-card{display:none;overflow:hidden}.run-card.visible{display:block}.run-head{padding:18px 20px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:14px;align-items:center}.run-head h2{font-size:17px;margin:0}.status{border:1px solid var(--line);border-radius:999px;padding:5px 9px;font-size:11px;color:var(--muted)}.status.running{color:#cdefff}.status.completed{color:#caffdf;border-color:#2f6249}.status.blocked{color:#ffe0a2;border-color:#6a542e}.status.failed{color:#ffd0d8;border-color:#683142}.run-body{display:grid;grid-template-columns:.78fr 1.22fr;min-height:390px}.stages{padding:20px;border-right:1px solid var(--line)}.stage{position:relative;padding:0 0 22px 34px}.stage:last-child{padding-bottom:0}.stage:before{content:"";position:absolute;left:7px;top:7px;width:10px;height:10px;border-radius:50%;background:#3d5065;border:2px solid #0b192a;box-shadow:0 0 0 1px #3d5065}.stage:not(:last-child):after{content:"";position:absolute;left:11px;top:20px;bottom:2px;width:2px;background:#263950}.stage.completed:before{background:var(--ok);box-shadow:0 0 0 1px var(--ok)}.stage.active:before{background:var(--accent);box-shadow:0 0 0 5px #7dd3fc15}.stage.blocked:before{background:var(--warn);box-shadow:0 0 0 1px var(--warn)}.stage.failed:before{background:var(--bad);box-shadow:0 0 0 1px var(--bad)}.stage.skipped{opacity:.45}.stage b{display:block;font-size:13px}.stage span{display:block;color:var(--muted);font-size:11px;margin-top:2px}.output{padding:20px;overflow:auto}.placeholder{min-height:290px;display:grid;place-items:center;color:var(--muted);text-align:center}.guard{display:none;border:1px solid #6b532e;background:#2b2112;border-radius:13px;padding:13px 14px;margin-bottom:15px;color:#ffe0a4}.guard.visible{display:block}.guard strong{display:block;margin-bottom:3px}.section-title{font-size:11px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted);font-weight:850;margin:17px 0 7px}.sql{display:none;margin:0;background:#050d18;border:1px solid #20354e;border-radius:12px;padding:13px;white-space:pre-wrap;overflow-wrap:anywhere;color:#d8efff;font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.sql.visible{display:block}.answer{white-space:pre-wrap;overflow-wrap:anywhere;color:#e7f0fb;font-size:14px}.relation{display:none;padding:10px 12px;border:1px solid #31506b;border-radius:11px;background:#0b2135;margin:12px 0;color:#ccecff;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px}.relation.visible{display:block}.table-wrap{overflow:auto;margin-top:10px;border:1px solid var(--line);border-radius:12px}table{border-collapse:collapse;width:100%;min-width:480px;font-size:12px}th,td{text-align:left;padding:9px 10px;border-bottom:1px solid #203247;vertical-align:top}th{background:#10233a;color:#dceaff;position:sticky;top:0}td{color:#bccce0}tr:last-child td{border-bottom:0}.ask-latest{display:none;margin-top:10px}.ask-latest.visible{display:inline-flex}
@media(max-width:760px){.run-body{grid-template-columns:1fr}.stages{border-right:0;border-bottom:1px solid var(--line)}.run-row{align-items:flex-start;flex-direction:column}.run{width:100%}}
</style>
</head>
<body>
<header><div class="wrap header-lines"><h1>Autonomous Data Engineer Agent</h1><p>LLMs decide what should happen. Deterministic code decides how it is allowed to happen.</p><a href="https://github.com/Toukennn/Autonomous-data-engineer-agent" target="_blank" rel="noreferrer">GitHub ↗</a></div></header>
<main><div class="wrap shell">
<section class="card control-card">
<div class="label-row"><label for="key">Authorized demo key</label><span id="saved" class="saved">not saved</span></div>
<input id="key" type="password" autocomplete="off" placeholder="Paste your demo key">
<p class="hint">Stored only in this tab's sessionStorage. It survives refresh, but not browser close.</p>

<div class="seg" role="tablist" aria-label="Demo mode"><button id="ask-tab" class="active" type="button">Ask a question</button><button id="ingest-tab" type="button">Ingest an API</button></div>

<div id="ask-mode" class="mode active">
<div class="field"><label for="question"><b>Question</b></label><textarea id="question" placeholder="Ask about a governed Silver or Gold relation..."></textarea></div>
<div id="relation-hint" class="hint">Save a valid key to load example questions from the governed catalog.</div>
<div class="examples">
<button class="example ask-example" type="button" data-kind="count">Row count</button>
<button class="example ask-example" type="button" data-kind="preview">Preview rows</button>
<button class="example ask-example" type="button" data-kind="nulls">Check missing values</button>
<button class="example blocked" id="blocked-example" type="button">Blocked example</button>
</div>
</div>

<div id="ingest-mode" class="mode">
<div class="field"><label for="api-url"><b>Public JSON API URL</b></label><input id="api-url" type="url" placeholder="https://randomuser.me/api/?results=5"></div>
<div class="field"><label for="gold-goal"><b>What should the Gold mart contain?</b></label><textarea id="gold-goal" placeholder="Keep gender, email and phone. Deduplicate on id and prepare the result for analytics."></textarea></div>
<p class="hint">The demo keeps the UI intentionally small: one source URL and one natural-language Gold requirement. Top-level arrays and APIs with a top-level <code>results</code> collection are the safest demo shapes.</p>
</div>

<div class="run-row"><button id="run" class="run" type="button">Run</button><span id="elapsed" class="elapsed">0.0s</span><span class="small">One governed run at a time.</span></div>
</section>

<section id="run-card" class="card run-card">
<div class="run-head"><h2 id="run-title">Run progress</h2><span id="run-status" class="status">waiting</span></div>
<div class="run-body">
<div id="stages" class="stages"></div>
<div class="output">
<div id="placeholder" class="placeholder"><div><b>Start a run to see the execution here.</b><p>Long-running ETL work will update stage by stage.</p></div></div>
<div id="guard" class="guard"><strong id="guard-title"></strong><span id="guard-message"></span></div>
<div id="sql-block"><div id="sql-title" class="section-title" style="display:none">Generated SQL</div><pre id="sql" class="sql"></pre></div>
<div id="relation" class="relation"></div>
<div id="answer-title" class="section-title" style="display:none">Response</div><div id="answer" class="answer"></div>
<div id="table-title" class="section-title" style="display:none">Result table</div><div id="table"></div>
<button id="ask-latest" class="example ask-latest" type="button">Ask this Gold mart</button>
</div>
</div>
</section>
</div></main>
<script>
const $=id=>document.getElementById(id);const key=$("key"),saved=$("saved"),askTab=$("ask-tab"),ingestTab=$("ingest-tab"),askMode=$("ask-mode"),ingestMode=$("ingest-mode"),runBtn=$("run"),elapsed=$("elapsed"),runCard=$("run-card"),runStatus=$("run-status"),stagesEl=$("stages"),placeholder=$("placeholder"),guard=$("guard"),guardTitle=$("guard-title"),guardMessage=$("guard-message"),sql=$("sql"),sqlTitle=$("sql-title"),answer=$("answer"),answerTitle=$("answer-title"),tableTitle=$("table-title"),tableEl=$("table"),relation=$("relation"),askLatest=$("ask-latest"),relationHint=$("relation-hint");
let mode="ask",timer=null,startMs=0,currentRelation=sessionStorage.getItem("latestGoldRelation")||"";
const storedKey=sessionStorage.getItem("demoApiKey")||"";if(storedKey){key.value=storedKey;saved.textContent="key saved";saved.classList.add("ok");setTimeout(loadCatalog,50)}
key.addEventListener("input",()=>{const v=key.value.trim();if(v){sessionStorage.setItem("demoApiKey",v);saved.textContent="key saved";saved.classList.add("ok")}else{sessionStorage.removeItem("demoApiKey");saved.textContent="not saved";saved.classList.remove("ok")}});key.addEventListener("change",loadCatalog);
function setMode(next){mode=next;const ask=next==="ask";askTab.classList.toggle("active",ask);ingestTab.classList.toggle("active",!ask);askMode.classList.toggle("active",ask);ingestMode.classList.toggle("active",!ask);$("run-title").textContent=ask?"SQL analyst run":"ETL analyst run"}askTab.onclick=()=>setMode("ask");ingestTab.onclick=()=>setMode("ingest");
function auth(){return {"X-API-Key":key.value.trim()}}
async function loadCatalog(){if(!key.value.trim())return;try{const r=await fetch("/demo/catalog",{headers:auth(),cache:"no-store"});if(!r.ok)return;const p=await r.json();const gold=(p.relations||[]).filter(x=>x.layer==="gold");if(currentRelation&&!gold.some(x=>x.relation===currentRelation))currentRelation="";if(!currentRelation&&gold.length)currentRelation=gold[0].relation;if(currentRelation)relationHint.textContent="Examples currently use: "+currentRelation}catch(e){}}
function promptFor(kind){if(kind==="blocked")return "List PostgreSQL users from pg_catalog.pg_user. This is a deliberate guardrail test.";if(!currentRelation)return "";if(kind==="count")return `How many rows are in ${currentRelation}?`;if(kind==="preview")return `Show me the first 5 rows from ${currentRelation}.`;return `For ${currentRelation}, show counts of missing values for the available columns.`}
document.querySelectorAll(".ask-example").forEach(b=>b.onclick=()=>{const p=promptFor(b.dataset.kind);if(p){$("question").value=p;$("question").focus()}else relationHint.textContent="No Gold relation loaded yet. Ingest an API first, or type a relation name manually."});$("blocked-example").onclick=()=>{$("question").value=promptFor("blocked");$("question").focus()};
function startClock(){startMs=performance.now();clearInterval(timer);elapsed.textContent="0.0s";timer=setInterval(()=>{elapsed.textContent=((performance.now()-startMs)/1000).toFixed(1)+"s"},100)}function stopClock(){clearInterval(timer);timer=null;elapsed.textContent=((performance.now()-startMs)/1000).toFixed(1)+"s"}
function resetOutput(){runCard.classList.add("visible");runStatus.className="status running";runStatus.textContent="running";placeholder.style.display="grid";placeholder.innerHTML="<div><b>Run started.</b><p>Progress will update every second.</p></div>";guard.classList.remove("visible");sql.classList.remove("visible");sql.textContent="";sqlTitle.style.display="none";answer.textContent="";answerTitle.style.display="none";tableEl.innerHTML="";tableTitle.style.display="none";relation.classList.remove("visible");relation.textContent="";askLatest.classList.remove("visible")}
function renderStages(stages){stagesEl.innerHTML="";(stages||[]).forEach(s=>{const d=document.createElement("div");d.className="stage "+s.status;const b=document.createElement("b");b.textContent=s.label;const sp=document.createElement("span");sp.textContent=s.detail;d.append(b,sp);stagesEl.appendChild(d)})}
function renderGuard(g){if(!g)return;guard.classList.add("visible");guardTitle.textContent=g.title||"Guardrail triggered";guardMessage.textContent=g.message||"The run was blocked safely."}
function renderTable(columns,rows){if(!columns||!columns.length||!rows)return;tableTitle.style.display="block";const wrap=document.createElement("div");wrap.className="table-wrap";const t=document.createElement("table"),thead=document.createElement("thead"),tr=document.createElement("tr");columns.forEach(c=>{const th=document.createElement("th");th.textContent=c;tr.appendChild(th)});thead.appendChild(tr);t.appendChild(thead);const tb=document.createElement("tbody");rows.forEach(row=>{const rr=document.createElement("tr");row.forEach(v=>{const td=document.createElement("td");td.textContent=v===null?"null":String(v);rr.appendChild(td)});tb.appendChild(rr)});t.appendChild(tb);wrap.appendChild(t);tableEl.appendChild(wrap)}
function renderFinal(p){placeholder.style.display="none";runStatus.className="status "+p.status;runStatus.textContent=p.status;renderGuard(p.guardrail);const r=p.result||{};if(p.mode==="ask"){if(r.generated_sql){sqlTitle.style.display="block";sql.classList.add("visible");sql.textContent=r.generated_sql}if(r.answer){answerTitle.style.display="block";answer.textContent=r.answer}renderTable(r.columns||[],r.rows||[])}else{if(r.gold_relation){relation.classList.add("visible");relation.textContent=r.gold_relation;currentRelation=r.gold_relation;sessionStorage.setItem("latestGoldRelation",currentRelation);relationHint.textContent="Examples currently use: "+currentRelation;askLatest.classList.add("visible")}if(r.answer){answerTitle.style.display="block";answer.textContent=r.answer}}if(p.error&&!r.answer){answerTitle.style.display="block";answer.textContent=p.error}}
async function poll(runId){for(;;){await new Promise(r=>setTimeout(r,1000));const resp=await fetch(`/demo/runs/${runId}`,{headers:auth(),cache:"no-store"});if(!resp.ok)throw new Error("Could not read run status.");const p=await resp.json();renderStages(p.stages);renderGuard(p.guardrail);if(["completed","blocked","failed"].includes(p.status)){renderFinal(p);return}}}
runBtn.onclick=async()=>{const k=key.value.trim();if(!k){key.focus();saved.textContent="key required";return}let path,payload;if(mode==="ask"){const q=$("question").value.trim();if(!q){$("question").focus();return}path="/demo/ask";payload={question:q}}else{const u=$("api-url").value.trim(),g=$("gold-goal").value.trim();if(!u){$("api-url").focus();return}if(!g){$("gold-goal").focus();return}path="/demo/ingest";payload={api_url:u,gold_goal:g}}runBtn.disabled=true;resetOutput();startClock();try{const resp=await fetch(path,{method:"POST",headers:{...auth(),"Content-Type":"application/json"},body:JSON.stringify(payload)});let p;try{p=await resp.json()}catch(e){p={detail:"Non-JSON response"}}if(!resp.ok)throw new Error(typeof p.detail==="string"?p.detail:"Could not start run.");await poll(p.run_id)}catch(e){placeholder.style.display="none";runStatus.className="status failed";runStatus.textContent="failed";answerTitle.style.display="block";answer.textContent=e.message||"The request failed."}finally{stopClock();runBtn.disabled=false}};
askLatest.onclick=()=>{setMode("ask");$("question").value=promptFor("count");$("question").focus();window.scrollTo({top:0,behavior:"smooth"})};
</script>
</body></html>"""
    )
