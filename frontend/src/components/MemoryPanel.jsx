import { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const TABS = ["Characters", "Threads", "Directives", "Summaries", "Trace"];

// The story bible (what the writer is fed) and the trace/cost dashboard, side by side with the story.
export default function MemoryPanel({ storyId, onClose, version }) {
  const [tab, setTab] = useState("Characters");
  const [mem, setMem] = useState(null);
  const [logs, setLogs] = useState(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [m, l] = await Promise.all([api.memory(storyId), api.logs(storyId)]);
      setMem(m); setLogs(l); setError("");
    } catch (e) { setError(e.message); }
  }, [storyId]);
  useEffect(() => { load(); }, [load, version]);

  const toggle = async (id) => {
    try { await api.toggleDirective(storyId, id); load(); } catch (e) { setError(e.message); }
  };

  return (
    <aside className="panel" aria-label="Story bible">
      <header className="panel-head">
        <h2>Story bible</h2>
        <button className="mini" onClick={load}>Refresh</button>
        <button className="mini" onClick={onClose} aria-label="Close panel">Close</button>
      </header>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {!mem ? <p className="loading">Loading</p> : (
        <div className="panel-body">
          {tab === "Characters" && <Characters list={mem.characters} />}
          {tab === "Threads" && <Threads list={mem.threads} />}
          {tab === "Directives" && <Directives list={mem.directives} onToggle={toggle} />}
          {tab === "Summaries" && <Summaries list={mem.summaries} />}
          {tab === "Trace" && logs && <Trace logs={logs} />}
        </div>
      )}
    </aside>
  );
}

function Characters({ list }) {
  if (!list.length) return <p className="empty">Characters appear once the plan is approved.</p>;
  return list.map((c) => (
    <div key={c.name} className={`card char s-${c.status}`}>
      <p className="card-title"><strong>{c.name}</strong> <span className={`tag ${c.status === "alive" ? "" : "flag"}`}>{c.status}</span></p>
      {c.role && <p className="hint">{c.role}{c.origin === "episode" ? ", introduced in the story" : ""}</p>}
      {c.current_state && <p>{c.current_state}</p>}
      {c.relationships && Object.keys(c.relationships).length > 0 && (
        <p className="hint">{Object.entries(c.relationships).map(([k, v]) => `${k}: ${v}`).join("; ")}</p>
      )}
      <p className="hint">{c.first_episode ? `First seen ep ${c.first_episode}` : "Not yet on the page"}{c.last_seen_episode ? `, last seen ep ${c.last_seen_episode}` : ""}</p>
    </div>
  ));
}

function Threads({ list }) {
  if (!list.length) return <p className="empty">No threads yet.</p>;
  const order = { open: 0, planned: 1, resolved: 2 };
  return [...list].sort((a, b) => (order[a.status] ?? 3) - (order[b.status] ?? 3)).map((t) => (
    <div key={t.name} className="card">
      <p className="card-title"><strong>{t.name}</strong> <span className={`tag ${t.status === "open" ? "flag" : t.status === "resolved" ? "teal" : ""}`}>{t.status}</span></p>
      <p>{t.description}</p>
      <p className="hint">
        {t.opened_ep ? `Opened ep ${t.opened_ep}` : "Not opened yet"}
        {t.last_touched_ep ? `, last touched ep ${t.last_touched_ep}` : ""}
        {t.resolve_by ? `, due by ep ${t.resolve_by}` : ""}
        {t.resolved_ep ? `, resolved ep ${t.resolved_ep}` : ""}
      </p>
    </div>
  ));
}

function Directives({ list, onToggle }) {
  if (!list.length) return <p className="empty">Feedback you give becomes standing rules here. Every future draft and critique sees the active ones.</p>;
  return list.map((d) => (
    <div key={d.id} className={`card ${d.active ? "" : "inactive"}`}>
      <p className="card-title"><span className="tag">{d.kind}</span>{d.target ? <strong> {d.target}</strong> : null}</p>
      <p>{d.instruction}</p>
      <p className="hint">From ep {d.created_ep}{d.expires_ep ? `, expires after ep ${d.expires_ep}` : ""}. You said: "{d.source_feedback}"</p>
      <button className="mini" onClick={() => onToggle(d.id)}>{d.active ? "Retire" : "Re-activate"}</button>
    </div>
  ));
}

function Summaries({ list }) {
  if (!list.length) return <p className="empty">Rolling summaries are written as segments complete.</p>;
  return list.map((s) => (
    <div key={`${s.level}-${s.start_ep}`} className="card">
      <p className="card-title"><span className="tag">{s.level}</span> eps {s.start_ep}-{s.end_ep}</p>
      <p>{s.content}</p>
    </div>
  ));
}

function Trace({ logs }) {
  const p = logs.projection;
  return (
    <>
      <div className="stat-grid">
        <Stat label="Spent" value={`$${logs.total_cost_usd.toFixed(4)}`} />
        <Stat label="Per episode" value={`$${p.avg_cost_per_episode.toFixed(4)}`} />
        <Stat label="Sec / episode" value={p.avg_seconds_per_episode} />
        <Stat label="Errors" value={logs.errors} />
        <Stat label={`Remaining ${p.remaining_episodes} eps`} value={`~$${p.projected_remaining_cost}`} />
        <Stat label="Remaining time" value={`~${p.projected_remaining_hours} h`} />
      </div>
      <h3>By step</h3>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Node</th><th>Calls</th><th>Tokens in/out</th><th>Cost</th><th>Avg ms</th></tr></thead>
          <tbody>
            {logs.by_node.map((r) => (
              <tr key={r.node}><td>{r.node}</td><td>{r.calls}</td><td>{r.prompt_tokens}/{r.completion_tokens}</td>
                <td>${r.cost_usd.toFixed(4)}</td><td>{r.avg_latency_ms}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
      <h3>Recent steps</h3>
      <ol className="trace">
        {logs.recent.slice(0, 80).map((r) => (
          <li key={r.id} className={`trace-row t-${r.status}`}>
            <span className="t-node">{r.episode != null ? `ep ${r.episode} ` : ""}{r.node}{r.attempt > 1 ? ` (try ${r.attempt})` : ""}</span>
            {r.status !== "event" && <span className="hint">{r.model} {r.tokens} tok ${r.cost_usd.toFixed(4)} {r.latency_ms}ms</span>}
            {(r.decision || r.error) && <span className={r.error ? "error" : ""}>{r.error || r.decision}</span>}
          </li>
        ))}
      </ol>
    </>
  );
}

const Stat = ({ label, value }) => <div className="stat"><b>{value}</b><span>{label}</span></div>;
