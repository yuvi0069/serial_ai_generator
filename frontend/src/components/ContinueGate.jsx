import { useState } from "react";

// Between batches: the natural stop/resume point.
export default function ContinueGate({ p, onAct }) {
  const [count, setCount] = useState(3);
  const [auto, setAuto] = useState(false);
  if (p.next_episode > p.target) return <div className="gate"><p>All {p.target} episodes are written. Export the story from the header.</p></div>;
  return (
    <div className="gate">
      <p className="gate-lead">Next up: episode {p.next_episode} of {p.target}.</p>
      {p.budget_exceeded && <p className="warn">This story has spent ${p.story_cost} of its ${p.budget} budget. Continuing overrides the cap.</p>}
      <div className="row">
        <label className="inline">Write
          <input type="number" min={1} max={50} value={count} onChange={(e) => setCount(Math.max(1, Math.min(50, Number(e.target.value) || 1)))} />
          episode{count > 1 ? "s" : ""}
        </label>
        <label className="check"><input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
          Skip my review when the critic passes</label>
        <button className="btn primary" onClick={() => onAct({ action: "continue", count, auto_approve: auto })}>
          Write {count === 1 ? "episode" : `${count} episodes`}
        </button>
      </div>
      <p className="hint">Episodes the critic flags always stop for your review. You can close this page and resume later from the sidebar.</p>
    </div>
  );
}
