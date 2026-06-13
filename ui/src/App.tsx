import { useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const STAGES = ["material", "worker", "guardrails", "checkpoint", "decision"] as const;
type StageKey = (typeof STAGES)[number];
type StageState = { cls: string; txt: string };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const initStages = (): Record<StageKey, StageState> =>
  Object.fromEntries(STAGES.map((s) => [s, { cls: "", txt: "idle" }])) as Record<StageKey, StageState>;

type LoopEvent = { kind: string; applicant_id?: string; attempt?: number; data: any };
type Outcome = { decision: string; record: any };

export default function App() {
  const [samples, setSamples] = useState<any[]>([]);
  const [workers, setWorkers] = useState<string[]>([]);
  const [idx, setIdx] = useState(0);
  const [worker, setWorker] = useState("fake-worker-v1");
  const [jsonText, setJsonText] = useState("");
  const [running, setRunning] = useState(false);
  const [stages, setStages] = useState<Record<StageKey, StageState>>(initStages());
  const [log, setLog] = useState<string[]>([]);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API}/api/samples`)
      .then((r) => r.json())
      .then((j) => {
        setSamples(j.samples || []);
        setWorkers(j.workers || []);
        if (j.samples?.length) setJsonText(JSON.stringify(j.samples[0], null, 2));
      })
      .catch(() => addLog("Could not reach backend at " + API));
  }, []);

  useEffect(() => {
    if (samples[idx]) setJsonText(JSON.stringify(samples[idx], null, 2));
  }, [idx]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = 1e9;
  }, [log]);

  const addLog = (t: string) => setLog((l) => [...l, t]);
  const setStage = (k: StageKey, cls: string, txt: string) =>
    setStages((s) => ({ ...s, [k]: { cls, txt } }));

  async function run() {
    let applicant: any;
    try {
      applicant = JSON.parse(jsonText);
    } catch (e) {
      addLog("Invalid JSON: " + e);
      return;
    }
    setRunning(true);
    setLog([]);
    setOutcome(null);
    setStages(initStages());

    let data: { events: LoopEvent[]; outcome: Outcome };
    try {
      const res = await fetch(`${API}/api/review`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ applicant, worker }),
      });
      data = await res.json();
    } catch (e) {
      addLog("Request failed: " + e);
      setRunning(false);
      return;
    }

    setStage("material", "on", "received");
    for (const ev of data.events) {
      await sleep(280);
      if (ev.kind === "credential") {
        setStage("material", "ok", "schema ok");
        setStage("worker", "on", "verify cert: " + ev.data.status);
        addLog("credential → " + ev.data.status);
      } else if (ev.kind === "attempt_started") {
        setStage("worker", "on", "attempt " + ev.attempt);
        addLog("— attempt " + ev.attempt);
      } else if (ev.kind === "worker_proposed") {
        setStage("worker", "ok", "proposed " + ev.data.overall);
        addLog(`worker proposed score ${ev.data.overall} (${ev.data.recommendation})`);
      } else if (ev.kind === "guardrail") {
        const ok = ev.data.passed;
        setStage("guardrails", ok ? "ok" : "bad", ok ? "passed" : ev.data.failures.join(","));
        addLog("guardrails " + (ok ? "PASS" : "FAIL " + ev.data.failures.join(",")));
      } else if (ev.kind === "checkpoint") {
        const ok = ev.data.passed;
        setStage("checkpoint", ok ? "ok" : "bad", ok ? "passed" : ev.data.failures.join(","));
        addLog("checkpoint " + (ok ? "PASS" : "FAIL " + ev.data.failures.join(",")));
        if (!ok) {
          setStage("worker", "on", "revising…");
          addLog("↩ returning failure to worker — will revise");
        }
      } else if (ev.kind === "alarm") {
        addLog(`🚨 ${ev.data.type} [${ev.data.severity}]`);
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

  const rec = outcome?.record || {};
  return (
    <div className="wrap">
      <h1>
        Education<span>Applicant</span>Verifier
      </h1>
      <div className="sub">
        Drop in an applicant, watch the harness move through the loop, and see why it decided.
      </div>

      <div className="card">
        <div className="row">
          <div>
            <label>Sample applicant</label>
            <select value={idx} onChange={(e) => setIdx(+e.target.value)}>
              {samples.map((s, i) => (
                <option key={i} value={i}>
                  {s.name} — {s.role}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: 0 }}>
            <label>Worker (swappable)</label>
            <select value={worker} onChange={(e) => setWorker(e.target.value)}>
              {workers.map((w) => (
                <option key={w} value={w}>
                  {w}
                </option>
              ))}
            </select>
          </div>
          <div style={{ flex: 0 }}>
            <button disabled={running} onClick={run}>
              {running ? "Reviewing…" : "Review applicant"}
            </button>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <label>Applicant JSON (editable)</label>
          <textarea value={jsonText} onChange={(e) => setJsonText(e.target.value)} />
        </div>
      </div>

      <div className="card">
        <label>Loop</label>
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

      {outcome && (
        <div className="card">
          <label>Decision</label>
          <div className="verdict">
            <span className={"tag pill-" + outcome.decision}>{outcome.decision.toUpperCase()}</span>{" "}
            &nbsp; {rec.name}
          </div>
          <div className="why" style={{ marginTop: 8 }}>
            {rec.credential && (
              <div className="muted">
                Credential {rec.credential.cert_id || ""}: <b>{rec.credential.status}</b>
                {rec.credential.holder_name ? ` — holder ${rec.credential.holder_name}` : ""}
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
              </>
            )}
            {rec.reason && (
              <div style={{ marginTop: 6 }}>
                <b>Reason:</b> {rec.reason}
              </div>
            )}
            {rec.alarms?.length > 0 && (
              <>
                <div style={{ marginTop: 8 }}>Alarms:</div>
                {rec.alarms.map((a: any, i: number) => (
                  <div key={i} className={"alarm " + a.severity}>
                    <b>{a.type}</b> [{a.severity}] — {a.recommended_action}
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}

      <div className="foot">
        backend: <code>{API}</code>
      </div>
    </div>
  );
}
