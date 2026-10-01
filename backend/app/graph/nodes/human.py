"""Human-in-the-loop gates, implemented with LangGraph interrupt(). The graph pauses here, the
checkpoint is persisted in Postgres, and the run resumes whenever (minutes or weeks later) the
human answers via POST /stories/{id}/act.
NOTE: a node containing interrupt() re-runs from the top on resume, so nothing before the
interrupt() call may have side effects."""
from langgraph.graph import END
from langgraph.types import interrupt

from ...config import settings
from ...db import session_scope
from ...memory import store
from ...services.tracing import log_event
from ..state import StoryState


def plan_review(state: StoryState) -> dict:
    """Gate 1: approve / edit / request changes to the arc plan before any episode is written."""
    sid = state["story_id"]
    decision = interrupt({"type": "plan_review"})
    action = decision.get("action", "approve")
    if action == "edit" and decision.get("plan"):
        from .planning import normalize_skeleton
        with session_scope() as s:
            edited = decision["plan"]
            beats = edited.get("beats") or store.get_plan(s, sid).plan.get("beats", [])
            plan = normalize_skeleton(edited, edited.get("total_episodes") or state["target_episodes"],
                                      settings.beats_per_plan_chunk)
            plan["beats"] = beats
            store.save_plan(s, sid, plan)
    log_event(sid, "plan_review", f"human: {action}")
    return {"human_action": action, "plan_feedback": decision.get("feedback") if action == "feedback" else None}


def route_after_plan_review(state: StoryState) -> str:
    return "plan_arc" if state.get("human_action") == "feedback" else "init_bible"


def _review_reason(state: StoryState) -> str:
    c = state.get("critic", {})
    if c.get("passed"):
        return "critic passed"
    if state.get("episode_cost", 0) >= settings.max_episode_cost_usd:
        return "cost cap reached before the critic passed"
    return f"critic still flags issues after {state.get('revision_count', 0)} revision(s)"


def human_review(state: StoryState) -> dict:
    """Gate 2: approve / edit / reject the episode, optionally with feedback that carries forward.
    Auto-approve batches skip this gate only when the critic passed (failures always escalate)."""
    sid, n = state["story_id"], state["current_episode"]
    critic = state.get("critic", {})
    if state.get("auto_approve_remaining", 0) > 0 and critic.get("passed"):
        log_event(sid, "human_review", "auto-approved (critic passed)", episode=n)
        return {"human_action": "approve", "human_feedback": None, "review_reason": "auto"}
    reason = _review_reason(state)
    decision = interrupt({"type": "episode_review", "episode": n, "title": state.get("draft_title", ""),
                          "draft": state.get("draft", ""), "critic": critic, "reason": reason,
                          "revisions": state.get("revision_count", 0),
                          "episode_cost": round(state.get("episode_cost", 0.0), 5)})
    action = decision.get("action", "approve")
    update: dict = {"human_action": action, "human_feedback": (decision.get("feedback") or "").strip() or None,
                    "review_reason": reason}
    if action == "edit":
        update["draft"] = decision.get("text") or state.get("draft", "")
        update["draft_title"] = decision.get("title") or state.get("draft_title", "")
    if action == "reject" and not update["human_feedback"]:
        update["reject_note"] = "The editor rejected the draft without comment; write a clearly different take on the beat."
    log_event(sid, "human_review", f"human: {action}" + (" + feedback" if update["human_feedback"] else ""), episode=n)
    return update


def route_after_review(state: StoryState) -> str:
    if state.get("human_feedback"):
        return "apply_feedback"
    return "build_context" if state.get("human_action") == "reject" else "commit_memory"


def next_gate(state: StoryState) -> dict:
    """Gate 3 (between batches): 'write N more episodes (auto-approve?)' or leave standing feedback.
    This is the natural stop/resume point: close the tab at episode 12, come back next week."""
    sid, n, total = state["story_id"], state.get("current_episode", 1), state["target_episodes"]
    if n > total:
        return {"phase": "completed"}
    with session_scope() as s:
        cost = store.get_story(s, sid).total_cost_usd
    decision = interrupt({"type": "continue", "next_episode": n, "target": total,
                          "story_cost": round(cost, 4), "budget": settings.max_story_cost_usd,
                          "budget_exceeded": cost >= settings.max_story_cost_usd})
    if decision.get("action") == "feedback" and decision.get("feedback"):
        return {"human_action": "gate_feedback", "human_feedback": decision["feedback"]}
    count = max(1, min(settings.max_batch, int(decision.get("count") or 1)))
    auto = count if decision.get("auto_approve") else 0
    log_event(sid, "next_gate", f"human: write {count} (auto-approve {auto})", episode=n)
    return {"human_action": "continue", "batch_remaining": count, "auto_approve_remaining": auto}


def route_after_gate(state: StoryState) -> str:
    if state.get("phase") == "completed":
        return END
    return "apply_feedback" if state.get("human_action") == "gate_feedback" else "build_context"
