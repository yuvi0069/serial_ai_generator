"""Observability. Every LLM attempt and every graph decision becomes a RunLog row (and a JSON log
line), so any episode can be reconstructed: which node ran, with which model, how many tokens,
what it cost, how long it took, whether it was retried and why."""
import json
import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import update

from ..db import session_scope
from ..models import RunLog, Story

logger = logging.getLogger("trace")


@dataclass
class Trace:
    """Who is calling: attaches story/episode/node to every log row an LLM call produces."""
    story_id: str | None
    node: str
    episode: int | None = None


def _uuid(v):
    if v is None or isinstance(v, uuid.UUID):
        return v
    return uuid.UUID(str(v))


def log_run(trace: Trace, *, model: str | None = None, attempt: int = 1, prompt_tokens: int = 0,
            completion_tokens: int = 0, cost_usd: float = 0.0, latency_ms: int = 0,
            status: str = "ok", decision: str | None = None, error: str | None = None) -> None:
    """Persist one trace row and bump the story's running cost. Never raises: tracing must not
    take the pipeline down."""
    record = dict(story_id=str(trace.story_id) if trace.story_id else None, episode=trace.episode,
                  node=trace.node, model=model, attempt=attempt, prompt_tokens=prompt_tokens,
                  completion_tokens=completion_tokens, cost_usd=round(cost_usd, 6),
                  latency_ms=latency_ms, status=status, decision=decision, error=error)
    logger.info(json.dumps(record))
    try:
        with session_scope() as s:
            s.add(RunLog(**{**record, "story_id": _uuid(trace.story_id)}))
            if cost_usd and trace.story_id:
                s.execute(update(Story).where(Story.id == _uuid(trace.story_id))
                          .values(total_cost_usd=Story.total_cost_usd + cost_usd))
    except Exception:  # pragma: no cover
        logger.exception("failed to persist trace row")


def log_event(story_id, node: str, decision: str, episode: int | None = None,
              status: str = "event", error: str | None = None) -> None:
    """Record a non-LLM decision (routing, gate outcome, budget stop, degraded retrieval...)."""
    log_run(Trace(story_id, node, episode), status=status, decision=decision, error=error)
