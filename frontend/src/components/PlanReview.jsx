import { useMemo, useState } from "react";

// Gate 1: read the full arc, edit beats or the raw plan, then approve, save edits, or ask for changes.
export default function PlanReview({ data, onAct }) {
  const [plan, setPlan] = useState(() => structuredClone(data.plan));
  const [dirty, setDirty] = useState(false);
  const [raw, setRaw] = useState(false);
  const [rawText, setRawText] = useState("");
  const [rawError, setRawError] = useState("");
  const [openSeg, setOpenSeg] = useState(1);
  const [feedback, setFeedback] = useState("");

  const beatsBySeg = useMemo(() => {
    const beats = plan.beats || [];
    return (plan.segments || []).map((s) => ({ ...s, beats: beats.slice(s.start - 1, s.end) }));
  }, [plan]);

  const setBeat = (episode, field, value) => {
    setPlan((p) => ({ ...p, beats: p.beats.map((b) => (b.episode === episode ? { ...b, [field]: value } : b)) }));
    setDirty(true);
  };

  const openRaw = () => { setRawText(JSON.stringify(plan, null, 2)); setRawError(""); setRaw(true); };
  const applyRaw = () => {
    try { setPlan(JSON.parse(rawText)); setDirty(true); setRaw(false); }
    catch (e) { setRawError(`Not valid JSON: ${e.message}`); }
  };

  return (
    <section className="gate plan-review" aria-label="Arc plan review">
      <p className="eyebrow">Arc plan v{data.version}, waiting for your approval</p>
      <h2>{plan.title}</h2>
      {plan.logline && <p className="logline">{plan.logline}</p>}
      <dl className="facts-grid">
        {plan.genre && <><dt>Genre</dt><dd>{plan.genre}</dd></>}
        {plan.tone && <><dt>Tone</dt><dd>{plan.tone}</dd></>}
        {plan.pov && <><dt>POV</dt><dd>{plan.pov}</dd></>}
        {plan.ending && <><dt>Ending</dt><dd>{plan.ending}</dd></>}
      </dl>

      <h3>Acts</h3>
      <ol className="acts">
        {(plan.acts || []).map((a) => (
          <li key={a.name + a.start}>
            <strong>{a.name}</strong> <span className="hint">eps {a.start}-{a.end}</span>
            <p>{a.goal}</p>
            {a.turning_point && <p className="hint">Turns on: {a.turning_point}</p>}
          </li>
        ))}
      </ol>

      <div className="two-col">
        <div>
          <h3>Characters</h3>
          <ul className="plain">
            {(plan.characters || []).map((c) => (
              <li key={c.name}><strong>{c.name}</strong>{c.role ? `, ${c.role}` : ""}<p className="hint">{c.arc || c.description}</p></li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Threads</h3>
          <ul className="plain">
            {(plan.threads || []).map((t) => (
              <li key={t.name}><strong>{t.name}</strong> <span className="hint">opens by {t.open_by ?? "?"}, resolves by {t.resolve_by ?? "?"}</span>
                <p className="hint">{t.description}</p></li>
            ))}
          </ul>
        </div>
      </div>

      <h3>Turning points</h3>
      <ul className="plain turning">
        {(plan.turning_points || []).map((t, i) => <li key={i}><span className="ep-num">{t.episode}</span>{t.event}</li>)}
      </ul>

      <h3>Episode beats <span className="hint">(click a part to open it; beats are editable)</span></h3>
      <div className="segments">
        {beatsBySeg.map((s) => (
          <div key={s.index} className={`segment ${openSeg === s.index ? "open" : ""}`}>
            <button className="segment-head" onClick={() => setOpenSeg(openSeg === s.index ? null : s.index)} aria-expanded={openSeg === s.index}>
              <span>Part {s.index}: {s.title}</span><span className="hint">eps {s.start}-{s.end}</span>
            </button>
            {openSeg === s.index && (
              <ol className="beats">
                {s.goal && <p className="hint seg-goal">{s.goal}</p>}
                {s.beats.map((b) => (
                  <li key={b.episode}>
                    <span className="ep-num">{b.episode}</span>
                    <div className="beat-fields">
                      <textarea rows={2} value={b.beat} onChange={(e) => setBeat(b.episode, "beat", e.target.value)} aria-label={`Beat for episode ${b.episode}`} />
                      <input value={b.hook || ""} placeholder="Hook" onChange={(e) => setBeat(b.episode, "hook", e.target.value)} aria-label={`Hook for episode ${b.episode}`} />
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>

      <div className="row">
        <button className="btn link" onClick={raw ? () => setRaw(false) : openRaw}>{raw ? "Close raw JSON" : "Edit raw JSON"}</button>
      </div>
      {raw && (
        <div className="raw">
          <textarea rows={16} value={rawText} onChange={(e) => setRawText(e.target.value)} aria-label="Plan JSON" spellCheck={false} />
          {rawError && <p className="error">{rawError}</p>}
          <button className="btn ghost" onClick={applyRaw}>Apply JSON</button>
        </div>
      )}

      <div className="gate-actions">
        {dirty ? (
          <button className="btn primary" onClick={() => onAct({ action: "edit", plan })}>Save my edits and start writing</button>
        ) : (
          <button className="btn primary" onClick={() => onAct({ action: "approve" })}>Approve the plan</button>
        )}
        {dirty && <button className="btn ghost" onClick={() => { setPlan(structuredClone(data.plan)); setDirty(false); }}>Discard edits</button>}
      </div>
      <div className="feedback-box">
        <label htmlFor="plan-fb">Or ask for a revised plan</label>
        <textarea id="plan-fb" rows={2} value={feedback} onChange={(e) => setFeedback(e.target.value)}
          placeholder="e.g. 'the sister should be alive and the antagonist until act 3'" />
        <button className="btn ghost" disabled={!feedback.trim()} onClick={() => onAct({ action: "feedback", feedback: feedback.trim() })}>Revise the plan</button>
      </div>
    </section>
  );
}
