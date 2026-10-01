import { useState } from "react";

const EXAMPLE = "A delivery rider realizes every address on today's route belongs to someone who died in the same building.";

export default function NewStory({ onCreate }) {
  const [premise, setPremise] = useState("");
  const [target, setTarget] = useState(200);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError("");
    try { await onCreate(premise.trim(), Number(target)); } catch (err) { setError(err.message); setBusy(false); }
  };

  return (
    <form className="new-story" onSubmit={submit}>
      <h1 className="hero">Start with one line.</h1>
      <p className="lede">The planner turns it into acts, characters, threads and a beat for every episode. You approve the plan before a word is written.</p>
      <textarea value={premise} onChange={(e) => setPremise(e.target.value)} rows={3} minLength={10} maxLength={1500} required
        placeholder="Your premise" aria-label="Premise" />
      <button type="button" className="example" onClick={() => setPremise(EXAMPLE)}>Use the delivery-rider premise</button>
      <div className="row">
        <label className="inline">Episodes
          <select value={target} onChange={(e) => setTarget(e.target.value)}>
            {[20, 50, 100, 200].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <button className="btn primary" disabled={busy || premise.trim().length < 10}>{busy ? "Starting" : "Plan the story"}</button>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}
