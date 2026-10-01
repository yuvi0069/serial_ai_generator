import { useState } from "react";
import { api } from "../api.js";

// The story transcript, rendered by message kind. Episodes are manuscript cards that can be
// rewritten after the fact (retroactive edit -> memory rebuild + ripple check on later episodes).
export default function MessageList({ messages, storyId, plan, onChanged, canEdit }) {
  return (
    <ol className="messages">
      {messages.map((m) => (
        <li key={m.id} className={`msg msg-${m.role} kind-${m.kind}`}>
          <Message m={m} storyId={storyId} plan={plan} onChanged={onChanged} canEdit={canEdit} />
        </li>
      ))}
    </ol>
  );
}

function Message({ m, storyId, plan, onChanged, canEdit }) {
  switch (m.kind) {
    case "episode": return <EpisodeCard m={m} storyId={storyId} onChanged={onChanged} canEdit={canEdit} />;
    case "plan": return <PlanNote m={m} plan={plan} />;
    case "feedback": return m.role === "user" ? <UserLine m={m} feedback /> : <FeedbackAck m={m} />;
    case "ripple": return <Ripple m={m} />;
    case "error": return <p className="bubble error-bubble">{m.content}</p>;
    case "event": return <p className="event-line">{m.content}</p>;
    default: return m.role === "user" ? <UserLine m={m} /> : <p className="bubble">{m.content}</p>;
  }
}

function UserLine({ m, feedback }) {
  return (
    <div className="user-line">
      {feedback && <span className="tag flag">Feedback</span>}
      <p>{m.content}</p>
    </div>
  );
}

function PlanNote({ m, plan }) {
  return (
    <div className="bubble plan-note">
      <p className="eyebrow">Arc plan v{m.meta.version}</p>
      {m.meta.title && <h3>{m.meta.title}</h3>}
      {m.meta.logline && <p className="logline">{m.meta.logline}</p>}
      <p className="hint">{m.content}{plan?.approved ? " Approved." : ""}</p>
    </div>
  );
}

function FeedbackAck({ m }) {
  const d = m.meta.directive;
  const beats = m.meta.beats_changed || [];
  return (
    <div className="bubble feedback-ack">
      <p>{m.content}</p>
      {d && (
        <p className="directive-line">
          <span className="tag teal">Standing rule</span> {d.instruction}
          {d.duration_episodes ? <span className="hint"> (for the next {d.duration_episodes} episodes)</span> : null}
        </p>
      )}
      {beats.length > 0 && <p className="hint">Rewrote the planned beats for episode{beats.length > 1 ? "s" : ""} {compact(beats)}.</p>}
      {m.meta.scope === "episode_only" && <p className="hint">Applied to this rewrite only.</p>}
    </div>
  );
}

function Ripple({ m }) {
  const conflicts = m.meta.conflicts || [];
  return (
    <div className={`bubble ripple ${conflicts.length ? "has-conflicts" : ""}`}>
      <p className="eyebrow">Continuity check after editing episode {m.meta.episode}</p>
      <p>{m.content}</p>
      {conflicts.length > 0 && (
        <ul className="conflicts">
          {conflicts.map((c, i) => (
            <li key={i}><strong>Episode {c.episode}:</strong> {c.conflict}{c.suggested_fix ? <span className="hint"> Suggested fix: {c.suggested_fix}</span> : null}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function EpisodeCard({ m, storyId, onChanged, canEdit }) {
  const meta = m.meta || {};
  const [open, setOpen] = useState(true);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.content);
  const [title, setTitle] = useState(meta.title || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const save = async () => {
    setBusy(true); setError("");
    try {
      await api.editEpisode(storyId, meta.episode, text, title);
      setEditing(false);
      onChanged?.();
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  };

  return (
    <article className="manuscript">
      <header className="ms-head">
        <button className="ms-toggle" onClick={() => setOpen(!open)} aria-expanded={open}>
          <span className="ms-number">Episode {meta.episode}</span>
          <span className="ms-title">{meta.title}</span>
        </button>
        <div className="ms-meta">
          {meta.human_edited && <span className="tag flag">Edited by you</span>}
          {meta.auto_approved && <span className="tag teal">Auto-approved</span>}
          <span>{meta.word_count} words</span>
          {meta.hook_score != null && <span>hook {meta.hook_score}/10</span>}
          {meta.revisions > 0 && <span>{meta.revisions} revision{meta.revisions > 1 ? "s" : ""}</span>}
          {meta.cost_usd != null && <span>${Number(meta.cost_usd).toFixed(4)}</span>}
        </div>
      </header>
      {open && !editing && (
        <>
          <div className="prose">{m.content.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>)}</div>
          <footer className="ms-foot">
            {meta.hook && <p className="hint"><em>Hook:</em> {meta.hook}</p>}
            {canEdit && <button className="btn link" onClick={() => setEditing(true)}>Rewrite this episode</button>}
          </footer>
        </>
      )}
      {editing && (
        <div className="ms-edit">
          <p className="warn">Saving rewrites this episode's memory (facts, character states, threads) and checks the episodes after it for contradictions.</p>
          <input className="title-field" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Episode title" />
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={18} aria-label="Episode text" />
          {error && <p className="error" role="alert">{error}</p>}
          <div className="row">
            <button className="btn primary" disabled={busy || text.trim().length < 50} onClick={save}>{busy ? "Saving" : "Save and re-check"}</button>
            <button className="btn ghost" onClick={() => { setEditing(false); setText(m.content); setTitle(meta.title || ""); }}>Cancel</button>
          </div>
        </div>
      )}
    </article>
  );
}

// [3,4,5,9] -> "3-5, 9"
function compact(nums) {
  const out = [];
  let start = nums[0], prev = nums[0];
  for (const n of nums.slice(1).concat([null])) {
    if (n === prev + 1) { prev = n; continue; }
    out.push(start === prev ? `${start}` : `${start}-${prev}`);
    start = prev = n;
  }
  return out.join(", ");
}
