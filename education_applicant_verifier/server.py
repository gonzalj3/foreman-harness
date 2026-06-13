"""FastAPI service: the deployable harness.

Serves a no-sign-in dashboard and a JSON API. A review runs the harness on a
single applicant and returns the full LoopEvent timeline + the decision, so the
dashboard can animate the loop and show *why* an applicant was accepted/rejected.
(SSE streaming + a Next.js/Vercel frontend are the planned upgrade; this single
service deploys fastest.)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from .events import EventBus
from .harness import Harness
from .material import from_dict, render
from .observability import Tracer
from .profiles import teacher_profile
from .verifier import FakeCredentialVerifier
from .worker import FakeWorker, StrictFakeWorker

app = FastAPI(title="EducationApplicantVerifier")

_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "applications.json")

WORKERS = {"fake-worker-v1": FakeWorker, "strict-fake-worker-v1": StrictFakeWorker}


def _samples() -> list[dict]:
    try:
        with open(_DATA) as f:
            return json.load(f)
    except Exception:
        return []


class ReviewRequest(BaseModel):
    applicant: dict
    worker: str = "fake-worker-v1"


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/api/samples")
def samples():
    return {"samples": _samples(), "workers": list(WORKERS)}


@app.post("/api/review")
def review(req: ReviewRequest):
    bus = EventBus()
    events: list = []
    bus.subscribe(lambda e: events.append({"kind": e.kind, "applicant_id": e.applicant_id,
                                           "attempt": e.attempt, "data": e.data}))
    tracer = Tracer(bus)
    worker_cls = WORKERS.get(req.worker, FakeWorker)
    harness = Harness(teacher_profile(FakeCredentialVerifier()), worker_cls(), tracer=tracer)

    app_obj = from_dict(req.applicant)
    result = harness.run([app_obj])
    rendered = render(result)

    # find this applicant's outcome
    outcome = {"decision": "unknown", "record": None}
    for e in rendered["ranking"]:
        if e["applicant_id"] == app_obj.id:
            outcome = {"decision": "accepted" if e["accepted"] else "rejected", "record": e}
    for e in rendered["ineligible"]:
        if e["applicant_id"] == app_obj.id:
            outcome = {"decision": "ineligible", "record": e}
    for e in rendered["escalations"]:
        if e["applicant_id"] == app_obj.id:
            outcome = {"decision": "escalated", "record": e}

    return JSONResponse({"events": events, "outcome": outcome,
                         "spans": [s.name for s in tracer.spans]})


@app.get("/", response_class=HTMLResponse)
def index():
    return HTML


HTML = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>EducationApplicantVerifier</title>
<style>
  :root{--red:#c0392b;--ink:#18202b;--mut:#6b7280;--line:#e2e5ea;--ok:#1f6b4a;--bad:#b5362b;--warn:#9a6a0a}
  *{box-sizing:border-box;margin:0;padding:0}
  body{font:14px/1.5 -apple-system,Helvetica Neue,Arial,sans-serif;color:var(--ink);background:#f6f7f9;padding:22px;max-width:1000px;margin:auto}
  h1{font-size:20px}h1 span{color:var(--red)}
  .sub{color:var(--mut);font-size:13px;margin:2px 0 16px}
  .card{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}
  label{font-size:12px;color:var(--mut);text-transform:uppercase;letter-spacing:.4px}
  select,button,textarea{font:inherit}
  select,textarea{width:100%;padding:8px;border:1px solid var(--line);border-radius:7px;margin-top:4px}
  textarea{height:130px;font-family:Menlo,Consolas,monospace;font-size:12px}
  .row{display:flex;gap:10px;align-items:end;flex-wrap:wrap}
  .row>div{flex:1;min-width:160px}
  button{background:var(--red);color:#fff;border:0;border-radius:7px;padding:9px 18px;cursor:pointer;font-weight:700}
  button:disabled{opacity:.5}
  .pipe{display:flex;gap:6px;flex-wrap:wrap;margin:6px 0}
  .stage{flex:1;min-width:120px;border:1.5px solid var(--line);border-radius:8px;padding:8px;text-align:center;font-size:12px;color:var(--mut);transition:.2s;background:#fafbfc}
  .stage b{display:block;color:var(--ink);font-size:12px}
  .stage.on{border-color:var(--red);background:#fdeecec0;color:var(--ink)}
  .stage.ok{border-color:var(--ok);background:#eaf5ef}
  .stage.bad{border-color:var(--bad);background:#fdeceb}
  .log{font-family:Menlo,Consolas,monospace;font-size:12px;max-height:230px;overflow:auto;background:#0f1622;color:#d6deea;border-radius:8px;padding:10px}
  .log div{white-space:pre-wrap}
  .tag{display:inline-block;font-size:11px;font-weight:700;border-radius:7px;padding:1px 8px}
  .verdict{font-size:18px;font-weight:800}
  .why li{margin:3px 0}
  .alarm{font-size:12px;border-left:3px solid var(--warn);padding:3px 8px;margin:4px 0;background:#fff8e9}
  .alarm.critical{border-color:var(--bad);background:#fdeceb}
  .pill-accepted{background:#eaf5ef;color:var(--ok)}.pill-rejected{background:#fdeceb;color:var(--bad)}
  .pill-ineligible{background:#fbecd9;color:var(--warn)}.pill-escalated{background:#f3eefb;color:#5e3aa0}
  .muted{color:var(--mut);font-size:12px}
</style></head><body>
<h1>Education<span>Applicant</span>Verifier</h1>
<div class=sub>Drop in an applicant, watch the harness move through the loop, and see why it decided.</div>

<div class=card>
  <div class=row>
    <div><label>Sample applicant</label><select id=sample></select></div>
    <div style="flex:0"><label>Worker (swappable)</label><select id=worker></select></div>
    <div style="flex:0"><button id=run>Review applicant</button></div>
  </div>
  <div style="margin-top:10px"><label>Applicant JSON (editable)</label><textarea id=json></textarea></div>
</div>

<div class=card>
  <label>Loop</label>
  <div class=pipe id=pipe></div>
  <div class=log id=log></div>
</div>

<div class=card id=result style="display:none">
  <label>Decision</label>
  <div class=verdict id=verdict></div>
  <div id=why class=why style="margin-top:8px"></div>
</div>

<script>
const STAGES=["material","worker","guardrails","checkpoint","decision"];
const $=s=>document.querySelector(s);
let SAMPLES=[];
function drawPipe(){$("#pipe").innerHTML=STAGES.map(s=>`<div class=stage id=st-${s}><b>${s}</b><span>idle</span></div>`).join("")}
function setStage(id,cls,txt){const el=$("#st-"+id);if(!el)return;el.className="stage "+cls;if(txt)el.querySelector("span").textContent=txt}
function logln(t){const d=document.createElement("div");d.textContent=t;$("#log").appendChild(d);$("#log").scrollTop=1e9}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function load(){
  const r=await fetch("/api/samples");const j=await r.json();SAMPLES=j.samples;
  $("#sample").innerHTML=SAMPLES.map((s,i)=>`<option value=${i}>${s.name} — ${s.role}</option>`).join("");
  $("#worker").innerHTML=j.workers.map(w=>`<option value="${w}">${w}</option>`).join("");
  $("#sample").onchange=()=>{$("#json").value=JSON.stringify(SAMPLES[$("#sample").value],null,2)};
  $("#sample").onchange();
}
load();drawPipe();

$("#run").onclick=async()=>{
  $("#run").disabled=true;$("#log").innerHTML="";$("#result").style.display="none";drawPipe();
  let applicant;try{applicant=JSON.parse($("#json").value)}catch(e){logln("Invalid JSON: "+e);$("#run").disabled=false;return}
  const res=await fetch("/api/review",{method:"POST",headers:{"content-type":"application/json"},
     body:JSON.stringify({applicant,worker:$("#worker").value})});
  const data=await res.json();
  setStage("material","on","received");
  for(const ev of data.events){
    await sleep(260);
    if(ev.kind==="credential"){setStage("material","ok","schema ok");setStage("worker","on","verifying cert: "+ev.data.status);logln("credential → "+ev.data.status)}
    else if(ev.kind==="attempt_started"){setStage("worker","on","attempt "+ev.attempt);logln("— attempt "+ev.attempt)}
    else if(ev.kind==="worker_proposed"){setStage("worker","ok","proposed "+ev.data.overall);logln("worker proposed score "+ev.data.overall+" ("+ev.data.recommendation+")")}
    else if(ev.kind==="guardrail"){const ok=ev.data.passed;setStage("guardrails",ok?"ok":"bad",ok?"passed":ev.data.failures.join(","));logln("guardrails "+(ok?"PASS":"FAIL "+ev.data.failures.join(",")))}
    else if(ev.kind==="checkpoint"){const ok=ev.data.passed;setStage("checkpoint",ok?"ok":"bad",ok?"passed":ev.data.failures.join(","));logln("checkpoint "+(ok?"PASS":"FAIL "+ev.data.failures.join(",")));if(!ok){setStage("worker","on","revising…");logln("↩ returning failure to worker — will revise")}}
    else if(ev.kind==="alarm"){logln("🚨 "+ev.data.type+" ["+ev.data.severity+"]")}
    else if(ev.kind==="escalated"){setStage("decision","bad","escalated");logln("escalated → "+ev.data.reason)}
    else if(ev.kind==="decision"){const s=ev.data.status;setStage("decision",s==="accepted"?"ok":"bad",s);logln("decision → "+s)}
  }
  showOutcome(data.outcome);$("#run").disabled=false;
};

function showOutcome(o){
  $("#result").style.display="block";
  const rec=o.record||{};
  $("#verdict").innerHTML=`<span class="tag pill-${o.decision}">${o.decision.toUpperCase()}</span> &nbsp; ${rec.name||""}`;
  let h="";
  const cr=rec.credential;
  if(cr)h+=`<div class=muted>Credential ${cr.cert_id||""}: <b>${cr.status}</b>${cr.holder_name?(" — holder "+cr.holder_name):""}</div>`;
  if(rec.proposal){
    h+=`<div style="margin-top:6px">Score <b>${rec.proposal.overall_score}</b> (${rec.attempts} attempt${rec.attempts>1?"s":""}) — ${rec.proposal.recommendation}</div><ul>`;
    for(const c of rec.proposal.criteria)h+=`<li><b>${c.name}</b>: ${c.score}/10 — <span class=muted>${c.evidence}</span></li>`;
    h+="</ul>";
  }
  if(rec.reason)h+=`<div style="margin-top:6px"><b>Reason:</b> ${rec.reason}</div>`;
  if(rec.alarms&&rec.alarms.length){h+=`<div style="margin-top:8px">Alarms:</div>`;
    for(const a of rec.alarms)h+=`<div class="alarm ${a.severity}"><b>${a.type}</b> [${a.severity}] — ${a.recommended_action}</div>`;}
  $("#why").innerHTML=h;
}
</script></body></html>"""
