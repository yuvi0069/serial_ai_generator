"""Context -> draft -> (revision) nodes."""
from ...config import settings
from ...memory.checks import parse_episode
from ...memory.context import build_context
from ...services.llm import chat
from ...services.tracing import Trace
from .. import prompts
from ..state import StoryState


def build_context_node(state: StoryState) -> dict:
    """Assemble the layered memory packet for the next episode; resets per-episode counters."""
    ctx, meta = build_context(state["story_id"], state["current_episode"])
    return {"context": ctx, "context_meta": meta, "revision_count": 0, "episode_cost": 0.0, "critic": {}}


def write_episode(state: StoryState) -> dict:
    """First draft of the episode from the context packet (plus a rejection note if any)."""
    sid, n = state["story_id"], state["current_episode"]
    res = chat(prompts.writer(state["context"], n, state["target_episodes"], state.get("reject_note")),
               model=settings.writer_model, trace=Trace(sid, "write_episode", n), temperature=0.9, max_tokens=1600)
    title, body = parse_episode(res.text)
    return {"draft": body, "draft_title": title, "reject_note": None,
            "episode_cost": state.get("episode_cost", 0.0) + res.cost_usd}


def revise_episode(state: StoryState) -> dict:
    """Rewrite the draft against the critic's issues and the deterministic findings."""
    sid, n = state["story_id"], state["current_episode"]
    c = state.get("critic", {})
    res = chat(prompts.reviser(state["context"], n, state["target_episodes"], state.get("draft_title", ""),
                               state["draft"], c.get("issues", []), c.get("checks", {}).get("findings", [])),
               model=settings.writer_model, trace=Trace(sid, "revise_episode", n), temperature=0.7, max_tokens=1600)
    title, body = parse_episode(res.text)
    return {"draft": body, "draft_title": title or state.get("draft_title", ""),
            "revision_count": state.get("revision_count", 0) + 1,
            "episode_cost": state.get("episode_cost", 0.0) + res.cost_usd}
