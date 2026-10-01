// The whole run at a glance: one tick per episode, act boundaries marked, current position lit.
export default function StorySpine({ total, episodes, current, acts, pendingEp }) {
  const byN = new Map(episodes.map((e) => [e.n, e]));
  const actStarts = new Map(acts.map((a) => [a.start, a.name]));
  const ticks = [];
  for (let n = 1; n <= total; n++) {
    const e = byN.get(n);
    const cls = e ? (e.edited ? "edited" : e.auto ? "auto" : "done") : n === pendingEp ? "review" : n === current ? "next" : "";
    ticks.push(
      <span key={n} className={`tick ${cls} ${actStarts.has(n) && n > 1 ? "act-start" : ""}`}
        title={`Episode ${n}${e ? (e.edited ? ": edited by you" : e.auto ? ": auto-approved" : ": approved") : n === pendingEp ? ": waiting for review" : ""}${actStarts.has(n) ? ` (${actStarts.get(n)})` : ""}`} />
    );
  }
  return (
    <div className="spine" role="img" aria-label={`${episodes.length} of ${total} episodes written`}>
      <div className="ticks" style={{ gridTemplateColumns: `repeat(${total}, 1fr)` }}>{ticks}</div>
      <div className="spine-legend">
        <span><i className="tick done" />approved</span>
        <span><i className="tick auto" />auto-approved</span>
        <span><i className="tick edited" />edited by you</span>
        <span className="count">{episodes.length} of {total}</span>
      </div>
    </div>
  );
}
