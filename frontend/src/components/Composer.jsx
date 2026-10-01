import { useState } from "react";

// Free-text channel. At a gate, what you type becomes feedback that carries into future episodes.
export default function Composer({ pending, running, onAct }) {
  const [text, setText] = useState("");
  const type = pending?.type;
  const enabled = !running && (type === "continue" || type === "plan_review");
  const placeholder = running ? "Writing. You can steer once it pauses."
    : type === "plan_review" ? "Ask for changes to the plan, e.g. 'make the landlord the villain from the start'"
    : type === "continue" ? "Steer future episodes, e.g. 'slow down the romance' or 'kill off Theo within three episodes'"
    : type === "episode_review" ? "Use the review above: approve, edit, or reject with a note."
    : "Nothing is waiting for input.";
  const send = (e) => {
    e.preventDefault();
    if (!text.trim() || !enabled) return;
    onAct({ action: "feedback", feedback: text.trim() });
    setText("");
  };
  return (
    <form className="composer" onSubmit={send}>
      <textarea rows={2} value={text} disabled={!enabled} placeholder={placeholder} aria-label="Feedback"
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) send(e); }} />
      <button className="btn primary" disabled={!enabled || !text.trim()}>
        {type === "plan_review" ? "Revise plan" : "Send feedback"}
      </button>
    </form>
  );
}
