"""LangGraph state. Deliberately SMALL: pointers + the in-flight draft. Durable story memory lives
in Postgres/Qdrant, so checkpoints stay cheap and history can be edited outside the graph."""
from typing import Any, TypedDict


class StoryState(TypedDict, total=False):
    story_id: str
    target_episodes: int
    phase: str                      # planning | writing | completed
    plan_feedback: str | None       # human notes for a plan regeneration

    current_episode: int            # episode being written (1-based)
    context: str                    # exact packet the writer/critic saw (kept for traceability)
    context_meta: dict[str, Any]
    draft_title: str
    draft: str
    critic: dict[str, Any]
    revision_count: int
    episode_cost: float             # spend on the current episode (cost cap)

    human_action: str | None        # approve | edit | reject | gate_feedback | continue
    human_feedback: str | None      # free-text note to compile into directives / beat changes
    reject_note: str | None         # note for the rewrite of a rejected episode
    review_reason: str | None       # why a human is being asked (or 'auto')

    batch_remaining: int            # episodes left in the current human-approved batch
    auto_approve_remaining: int     # of those, how many may skip review if the critic passes
