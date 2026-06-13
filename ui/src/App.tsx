import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const STAGES = ["material", "credential", "worker", "guardrails", "checkpoint", "decision"] as const;
type StageKey = (typeof STAGES)[number];
type StageState = { cls: string; txt: string };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const initStages = (): Record<StageKey, StageState> =>
  Object.fromEntries(STAGES.map((s) => [s, { cls: "", txt: "idle" }])) as Record<StageKey, StageState>;

type Job = any;
type Candidate = any;
type LoopEvent = { kind: string; attempt?: number; data: any };
type Outcome = { decision: string; record: any };

export default function App() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [workers, setWorkers] = useState<string[]>([]);
  const [worker, setWorker] = useState("");
  const [evals, setEvals] = useState<any>(null);

  const [job, setJob] = useState<Job | null>(null);
  const [cand, setCand] = useState<Candidate | null>(null);
  const [running, setRunning] = useState(false);
  const [stages, setStages] = useState<Record<StageKey, StageState>>(initStages());
  const [log, setLog] = useState<string[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [credEvent, setCredEvent] = useState<any>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API}/api/samples`)
      .then((r) => r.json())
      .then((j) => {
        setJobs(j.job_descriptions || []);
        const ws: string[] = j.workers || [];
        setWorkers(ws);
        setWorker(ws[0] || "");
      })
      .catch(() => {});
    fetch(`${API}/api/candidates`)
      .then((r) => r.json())
      .then((j) => setCandidates(j.candidates || []))
      .catch(() => {});
    fetch(`${API}/api/evals`)
      .then((r) => r.json())
      .then(setEvals)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = 1e9;
  }, [log]);

  const addLog = (t: string) => setLog((l) => [...l, t]);
  const setStage = (k: StageKey, cls: string, txt: string) =>
    setStages((s) => ({ ...s, [k]: { cls, txt } }));

  function openJob(j: Job) {
    setJob(j);
    setCand(null);
    setOutcome(null);
    setCredEvent(null);
    setLog([]);
    setStages(initStages());
  }
  function backToJobs() {
    setJob(null);
    setCand(null);
    setOutcome(null);
    setCredEvent(null);
    setLog([]);
    setStages(initStages());
  }

  async function review(candidate: Candidate) {
    setCand(candidate);
    setOutcome(null);
    setCredEvent(null);
    setLog([]);
    setStages(initStages());
    setRunning(true);
    setStage("material", "on", "received");

    let data: { events: LoopEvent[]; outcome: Outcome };
    try {
      const res = await fetch(`${API}/api/review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ applicant: candidate, job, worker, verifier: "tea" }),
      });
      data = await res.json();
    } catch (e) {
      addLog("Request failed: " + e);
      setRunning(false);
      return;
    }

    for (const ev of data.events) {
      await sleep(300);
      if (ev.kind === "credential") {
        setStage("material", "ok", "schema ok");
        const ok = ev.data.status === "valid";
        setStage("credential", ok ? "ok" : "bad", ev.data.status);
        setCredEvent(ev.data);
        addLog(`TEA credential check → ${ev.data.status}${ev.data.holder ? ` (${ev.data.holder})` : ""}`);
        if (ev.data.certifications?.length)
          addLog(
            `   certified subjects: ${ev.data.certifications.join(", ")}` +
              (ev.data.grade_bands?.length ? ` · grades ${ev.data.grade_bands.join(", ")}` : "") +
              (ev.data.expires ? ` · expires ${ev.data.expires}` : "")
          );
      } else if (ev.kind === "attempt_started") {
        setStage("worker", "on", "attempt " + ev.attempt);
        addLog(`— attempt ${ev.attempt}: asking the model to score the candidate against the job`);
      } else if (ev.kind === "worker_proposed") {
        setStage("worker", "ok", "scored " + ev.data.overall);
        addLog(`🤖 model scored ${ev.data.overall}/10 → ${ev.data.recommendation}`);
        for (const c of ev.data.criteria || [])
          addLog(`   • ${c.name}: ${c.score}/10 — ${String(c.evidence).slice(0, 100)}`);
        if (ev.data.rationale) addLog(`   rationale: ${String(ev.data.rationale).slice(0, 140)}`);
      } else if (ev.kind === "worker_error") {
        addLog("⚠ worker error: " + ev.data.error);
      } else if (ev.kind === "guardrail") {
        const ok = ev.data.passed;
        setStage("guardrails", ok ? "ok" : "bad", ok ? "passed" : (ev.data.failures || []).join(","));
        addLog(`guardrails ${ok ? "PASS" : "FAIL"} — ${(ev.data.checks || []).length} checks:`);
        for (const ch of ev.data.checks || [])
          addLog(`   ${ch.passed ? "✓" : "✕"} ${ch.name} — ${ch.detail}`);
      } else if (ev.kind === "checkpoint") {
        const ok = ev.data.passed;
        setStage("checkpoint", ok ? "ok" : "bad", ok ? "passed" : (ev.data.failures || []).join(","));
        addLog(`checkpoint ${ok ? "PASS" : "FAIL"} — ${(ev.data.checks || []).length} checks:`);
        for (const ch of ev.data.checks || [])
          addLog(`   ${ch.passed ? "✓" : "✕"} ${ch.name} — ${ch.detail}`);
        if (!ok) {
          setStage("worker", "on", "revising…");
          addLog("   ↩ returning the failing checks to the model — it will revise");
        }
      } else if (ev.kind === "alarm") {
        addLog(`🚨 ${ev.data.type} [${ev.data.severity}] — ${ev.data.recommended_action}`);
      } else if (ev.kind === "escalated") {
        setStage("decision", "bad", "escalated");
        addLog("escalated → " + ev.data.reason);
      } else if (ev.kind === "decision") {
        const s = ev.data.status;
        setStage("decision", s === "accepted" ? "ok" : "bad", s);
        addLog("decision → " + s);
      }
    }
    setOutcome(data.outcome);
    setRunning(false);
  }

  // ---------- Jobs view ----------
  if (!job) {
    return (
      <div className="wrap">
        <h1>
          Education<span>Applicant</span>Verifier
        </h1>
        <div className="sub">
          You're a school administrator hiring for these roles. Pick a job to review candidates.
        </div>
        <div className="jobs-grid">
          {jobs.map((j) => (
            <button className="job-card" key={j.id} onClick={() => openJob(j)}>
              <div className="job-title">{j.title}</div>
              <div className="job-school">{j.employer}</div>
              <div className="job-meta">{j.location}</div>
              <div className="job-fill">
                Fill by: <b>{j.fill_by}</b>
              </div>
            </button>
          ))}
        </div>

        {evals?.cases?.length > 0 && (
          <div className="evals">
            <h2>Model eval — which model judges best</h2>
            <div className="sub">
              Each model is scored against a gold set whose correct answer comes from the
              candidate's real TEA certification. Last run: {evals.generated_at}
            </div>
            <div className="eval-scores">
              {evals.models.map((m: string) => (
                <span className="eval-score" key={m}>
                  {m} <b>{evals.scores[m].passed}/{evals.scores[m].total}</b>
                </span>
              ))}
            </div>
            <div className="eval-tablewrap">
              <table className="eval-table">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Job</th>
                    <th>Expected</th>
                    {evals.models.map((m: string) => (
                      <th key={m}>{m}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {evals.cases.map((c: any, i: number) => (
                    <tr key={i}>
                      <td>{c.candidate}</td>
                      <td>{c.job}</td>
                      <td>{c.expected}</td>
                      {evals.models.map((m: string) => {
                        const r = c.models?.[m];
                        return (
                          <td key={m} className={r ? (r.pass ? "ev-ok" : "ev-bad") : ""}>
                            {r ? `${r.pass ? "✓" : "✗"} ${r.got}` : "—"}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  }

  // ---------- Job detail view ----------
  const rec = outcome?.record || {};
  const loopVisible = running || !!outcome || log.length > 0;
  return (
    <div className="detail">
      <header className="detailbar">
        <button className="back" onClick={backToJobs}>
          ← Jobs
        </button>
        <div className="dtitle">
          {job.title} <span className="dschool">· {job.employer}</span>
        </div>
        <div className="wsel">
          <label>Worker</label>
          <select value={worker} onChange={(e) => setWorker(e.target.value)}>
            {workers.map((w) => (
              <option key={w} value={w}>
                {w}
              </option>
            ))}
          </select>
        </div>
      </header>

      <div className={"split" + (loopVisible ? " with-loop" : "")}>
        {/* Left: job description */}
        <section className="pane jd">
          <h2>Job Description</h2>
          <div className="jd-head">
            <div className="jd-name">{job.title}</div>
            <div className="muted">
              {job.employer} — {job.location} · Fill by {job.fill_by}
            </div>
          </div>
          {job.summary && <p className="jd-summary">{job.summary}</p>}
          <JdList title="Required education" items={job.required_education} />
          <JdList title="Required credentials" items={job.required_credentials} />
          <JdList title="Preferred experience" items={job.preferred_experience} />
          <JdList title="Responsibilities" items={job.responsibilities} />
          <JdList title="Skills" items={job.skills} />
        </section>

        {/* Right: candidate list -> candidate detail + decision */}
        <section className="pane right">
          {!cand ? (
            <>
              <h2>Candidates</h2>
              {workers.length === 0 && (
                <div className="nomodel">
                  ⚠ No model configured on the backend. Set an API key
                  (ANTHROPIC_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY) to enable reviews — an LLM is required.
                </div>
              )}
              {candidates.map((c) => (
                <button className="cand" key={c.id} onClick={() => review(c)}>
                  <div className="cand-name">{c.name}</div>
                  <div className="muted">{c.role}</div>
                  <div className="cand-go">Review →</div>
                </button>
              ))}
              {candidates.length === 0 && <div className="muted">No candidates yet.</div>}
            </>
          ) : (
            <>
              <button className="link" onClick={() => { setCand(null); setOutcome(null); }}>
                ← candidates
              </button>
              <h2>{cand.name}</h2>
              <div className="muted">{cand.role}</div>
              {cand.narrative && <p className="cand-narr">{cand.narrative}</p>}

              {credEvent && (
                <div
                  className={
                    "credbox " +
                    (credEvent.status === "valid"
                      ? "ok"
                      : credEvent.status === "mismatch" || credEvent.status === "unavailable"
                      ? "warn"
                      : "bad")
                  }
                >
                  <div className="credbadge">
                    {credEvent.status === "valid"
                      ? "✓ CERTIFICATE VERIFIED"
                      : "✕ " + String(credEvent.status).replace(/_/g, " ").toUpperCase()}
                  </div>
                  <div className="credsrc">Checked live against the Texas Education Agency (TEA)</div>
                  <div className="creddetail">
                    {credEvent.holder && (
                      <span>
                        Holder: <b>{credEvent.holder}</b>
                      </span>
                    )}
                    {credEvent.cert_type && <span> · {credEvent.cert_type}</span>}
                    {credEvent.cert_id && <span> · ID {credEvent.cert_id}</span>}
                    {credEvent.expires && <span> · expires {credEvent.expires}</span>}
                  </div>
                </div>
              )}

              {outcome ? (
                <div className="verdict-card">
                  <div className="verdict">
                    <span className={"tag pill-" + outcome.decision}>{outcome.decision.toUpperCase()}</span>
                  </div>
                  {rec.credential && (
                    <div className="muted">
                      Credential {rec.credential.cert_id || ""}: <b>{rec.credential.status}</b>
                      {rec.credential.holder_name ? ` — ${rec.credential.holder_name}` : ""}
                      {rec.credential.expires ? `, exp ${rec.credential.expires}` : ""}
                    </div>
                  )}
                  {rec.proposal && (
                    <>
                      <div style={{ marginTop: 6 }}>
                        Score <b>{rec.proposal.overall_score}</b> ({rec.attempts} attempt
                        {rec.attempts > 1 ? "s" : ""}) — {rec.proposal.recommendation}
                      </div>
                      <ul>
                        {rec.proposal.criteria.map((c: any, i: number) => (
                          <li key={i}>
                            <b>{c.name}</b>: {c.score}/10 — <span className="muted">{c.evidence}</span>
                          </li>
                        ))}
                      </ul>
                      {rec.proposal.rationale && <p className="muted">{rec.proposal.rationale}</p>}
                    </>
                  )}
                  {rec.reason && (
                    <div style={{ marginTop: 6 }}>
                      <b>Reason:</b> {rec.reason}
                    </div>
                  )}
                  {rec.alarms?.length > 0 &&
                    rec.alarms.map((a: any, i: number) => (
                      <div key={i} className={"alarm " + a.severity}>
                        <b>{a.type}</b> [{a.severity}] — {a.recommended_action}
                      </div>
                    ))}
                </div>
              ) : (
                <div className="muted">{running ? "Running the harness…" : ""}</div>
              )}
            </>
          )}
        </section>
      </div>

      {/* Bottom: full-width agent loop */}
      {loopVisible && (
        <div className="loopbar">
          <div className="loopbar-label">Harness loop {running ? "· running" : ""}</div>
          <div className="pipe">
            {STAGES.map((s) => (
              <div key={s} className={"stage " + stages[s].cls}>
                <b>{s}</b>
                <span>{stages[s].txt}</span>
              </div>
            ))}
          </div>
          <div className="log" ref={logRef}>
            {log.map((l, i) => (
              <div key={i}>{l}</div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function JdList({ title, items }: { title: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="jd-sec">
      <div className="jd-sec-title">{title}</div>
      <ul>
        {items.map((it, i) => (
          <li key={i}>{it}</li>
        ))}
      </ul>
    </div>
  );
}
