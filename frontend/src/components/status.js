// Human-readable story states, shared by the sidebar and the header.
export function statusLabel(s) {
  const n = s.current_episode;
  return {
    planning: "Planning the arc",
    awaiting_plan: "Arc plan ready for your review",
    writing: "Ready to write",
    running: "Writing",
    awaiting_review: `Episode ${n} is waiting for your review`,
    awaiting_continue: n > s.target_episodes ? "Finished" : `Paused before episode ${n}`,
    completed: "Finished",
    paused: "Paused",
    error: "Stopped by an error",
  }[s.status] || s.status;
}

export const written = (s) => Math.max(0, Math.min(s.target_episodes, s.current_episode - 1));
