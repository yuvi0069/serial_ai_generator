"""Turn free-text human feedback into (a) a standing directive and (b) concrete plan changes, so it
changes FUTURE episodes, not just the current one."""
from ...config import settings
from ...db import session_scope
from ...memory import store
from ...models import Directive
from ...services.llm import chat_json
from ...services.tracing import Trace, log_event
from .. import prompts
from ..llm_schemas import FeedbackOut
from ..state import StoryState


def apply_feedback(state: StoryState) -> dict:
    """Compile feedback -> directive (persisted, injected into every later writer/critic prompt)
    + rewritten upcoming beats (plan version bump). Scope 'episode_only' is honoured only on reject."""
    sid, n = state["story_id"], state["current_episode"]
    fb, action = state["human_feedback"], state.get("human_action")
    first = n + 1 if action in ("approve", "edit") else n
    with session_scope() as s:
        plan = store.get_plan(s, sid).plan
        upcoming = store.beats_range(plan, first, first + 14)
        names = [f"{c.name} ({c.status})" for c in store.characters(s, sid)]
        dirs = [d.instruction for d in store.active_directives(s, sid, n)]
    out, _ = chat_json(prompts.feedback(fb, n, upcoming, names, dirs, action in ("approve", "edit", "reject")),
                       FeedbackOut, model=settings.planner_model, trace=Trace(sid, "apply_feedback", n),
                       temperature=0.3, max_tokens=3500)
    forward = out.scope != "episode_only" or action != "reject"
    changed = []
    with session_scope() as s:
        existing = {x.instruction.strip().lower() for x in store.active_directives(s, sid, first)}
        if forward and out.directive and out.directive.instruction.strip().lower() not in existing:
            d = out.directive
            s.add(Directive(story_id=store.U(sid), instruction=d.instruction, kind=d.kind[:24], target=d.target[:200],
                            created_ep=first, source_feedback=fb,
                            expires_ep=first + d.duration_episodes - 1 if d.duration_episodes else None))
        row = store.get_plan(s, sid)
        new_plan = {**row.plan, "beats": list(row.plan.get("beats", []))}
        last = first + 14
        for b in out.beat_updates:
            if first <= b.episode <= min(last, len(new_plan["beats"])) and forward:
                new_plan["beats"][b.episode - 1] = b.model_dump()
                changed.append(b.episode)
        if changed:
            store.save_plan(s, sid, new_plan)
        ack = out.ack or ("Noted for this rewrite." if not forward else "Feedback saved for future episodes.")
        store.add_message(s, sid, "assistant", "feedback", ack, {
            "scope": "forward" if forward else "episode_only",
            "directive": out.directive.model_dump() if (forward and out.directive) else None,
            "beats_changed": sorted(changed), "from_episode": first})
    log_event(sid, "apply_feedback", f"scope={'forward' if forward else 'episode'} directive={bool(out.directive)} "
              f"beats_changed={sorted(changed)}", episode=n)
    return {"human_feedback": None, "reject_note": fb if action == "reject" else None}


def route_after_feedback(state: StoryState) -> str:
    action = state.get("human_action")
    if action in ("approve", "edit"):
        return "commit_memory"
    if action == "reject":
        return "build_context"
    return "next_gate"
