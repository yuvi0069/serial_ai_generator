import { useState } from "react";

const SEVERITY_ORDER = { high: 0, medium: 1, low: 2 };

// Gate 2: the draft plus the critic's verdict. Approve, edit, or reject, with optional
// feedback that becomes a standing directive for future episodes.
export default function EpisodeReview({ p, onAct }) {
  const [mode, setMode] = useState("read");
  const [text, setText] = useState(p.draft);
  const [title, setTitle] = useState(p.title);
  const [feedback, setFeedback] = useState("");
  const c = p.critic || {};
  const issues = [...(c.issues || [])].sort((a, b) => (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3));
  const checks = c.checks || {};
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const fb = feedback.trim() || undefined;

  return (
    <section className="gate episode-review" aria-label={`Review episode ${p.episode}`}>
      <div className="review-head">
        <p className="eyebrow">Episode {p.episode}, waiting for your review</p>
        <p className={`verdict ${c.passed ? "pass" : "flag"}`}>
          {c.passed ? "The critic passed this draft." : `Flagged: ${p.reason}.`}
        </p>
      </div>

      <div className="scores">
        <Score label="Hook" value={c.hook_score} min={7} />
        <Score label="Beat adherence" value={c.beat_adherence} min={6} />
        <span className="score"><b>{p.revisions}</b> revision{p.revisions === 1 ? "" : "s"}</span>
        <span className="score"><b>${Number(p.episode_cost || 0).toFixed(4)}</b> this episode</span>
        {checks.word_count != null && <span className="score"><b>{checks.word_count}</b> words</span>}
      </div>

      {issues.length > 0 && (
        <ul className="issues">
          {issues.map((i, k) => (
            <li key={k} className={`issue sev-${i.severity}`}>
              <span className="tag">{i.type}</span> {i.detail}
              {i.fix && <span className="hint"> Fix: {i.fix}</span>}
            </li>
          ))}
        </ul>
      )}

      {mode === "read" ? (
        <article className="manuscript draft">
          <h3 className="ms-title">{title}</h3>
          <div className="prose">{p.draft.split(/\n{2,}/).map((para, i) => <p key={i}>{para}</p>)}</div>
        </article>
      ) : (
        <div className="ms-edit">
          <input className="title-field" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="Episode title" />
          <textarea rows={20} value={text} onChange={(e) => setText(e.target.value)} aria-label="Episode text" />
          <p className={`hint ${words < 400 || words > 700 ? "warn-text" : ""}`}>{words} words (target 400-700)</p>
        </div>
      )}

      <div className="feedback-box">
        <label htmlFor="ep-fb">Feedback for future episodes (optional)</label>
        <textarea id="ep-fb" rows={2} value={feedback} onChange={(e) => setFeedback(e.target.value)}
          placeholder="e.g. 'slow down the romance' or 'kill off the landlord within three episodes'. With Reject, this is the note for the rewrite." />
      </div>

      <div className="gate-actions">
        {mode === "read" ? (
          <>
            <button className="btn primary approve" onClick={() => onAct({ action: "approve", feedback: fb })}>Approve</button>
            <button className="btn ghost" onClick={() => setMode("edit")}>Edit</button>
            <button className="btn ghost reject" onClick={() => onAct({ action: "reject", feedback: fb })}>Reject and rewrite</button>
          </>
        ) : (
          <>
            <button className="btn primary approve" disabled={words < 50}
              onClick={() => onAct({ action: "edit", text, title, feedback: fb })}>Save my version</button>
            <button className="btn ghost" onClick={() => { setMode("read"); setText(p.draft); setTitle(p.title); }}>Cancel</button>
          </>
        )}
      </div>
      <p className="hint">Approving makes the episode canon: its facts, character changes and threads go into the story bible.</p>
    </section>
  );
}

function Score({ label, value, min }) {
  if (value == null) return null;
  return <span className={`score ${value >= min ? "ok" : "low"}`}><b>{value}</b>/10 {label.toLowerCase()}</span>;
}
