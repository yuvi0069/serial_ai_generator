"""Runs graph work off the request thread. One run per story at a time (per-process lock); the
UI polls /state. Errors never lose work: the last checkpoint survives and /retry resumes it."""
import logging
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from langgraph.types import Command

from ..db import session_scope
from ..graph.checkpointer import get_graph
from ..memory import store
from .tracing import log_event

logger = logging.getLogger("runner")
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="story")
_running: set[str] = set()
_lock = threading.Lock()

STATUS_FOR = {"plan_review": "awaiting_plan", "episode_review": "awaiting_review", "continue": "awaiting_continue"}


class Busy(Exception):
    pass


def config_for(sid: str) -> dict:
    return {"configurable": {"thread_id": str(sid)}, "recursion_limit": 2000}


def is_running(sid: str) -> bool:
    return str(sid) in _running


def pending_interrupt(sid: str) -> dict | None:
    """The payload the graph is paused on (what the UI should render controls for), or None."""
    snap = get_graph().get_state(config_for(sid))
    for task in snap.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def graph_finished(sid: str) -> bool:
    snap = get_graph().get_state(config_for(sid))
    return bool(snap.values) and not snap.next


def submit(sid: str, fn: Callable, *args: Any) -> None:
    """Queue a job for a story; raises Busy if one is already running for it."""
    sid = str(sid)
    with _lock:
        if sid in _running:
            raise Busy(sid)
        _running.add(sid)
    _executor.submit(_guard, sid, fn, *args)


def _guard(sid: str, fn: Callable, *args: Any) -> None:
    try:
        with session_scope() as s:
            story = store.get_story(s, sid)
            story.status, story.last_error = "running", None
        fn(sid, *args)
        _sync_status(sid)
    except Exception as e:
        logger.exception("run failed for %s", sid)
        msg = f"{type(e).__name__}: {e}"
        log_event(sid, "runner", "run failed; checkpoint kept, use Retry", status="error",
                  error=traceback.format_exc()[-2000:])
        with session_scope() as s:
            story = store.get_story(s, sid)
            if story:
                story.status, story.last_error = "error", msg[:2000]
                store.add_message(s, sid, "system", "error", msg[:2000])
    finally:
        with _lock:
            _running.discard(sid)


def _invoke(sid: str, inp: Any) -> None:
    get_graph().invoke(inp, config_for(sid))


def _sync_status(sid: str) -> None:
    """Mirror the graph's position into stories.status for the sidebar."""
    p = pending_interrupt(sid)
    with session_scope() as s:
        story = store.get_story(s, sid)
        if p:
            story.status = STATUS_FOR.get(p.get("type"), "paused")
        elif graph_finished(sid):
            story.status = "completed"
            store.add_message(s, sid, "assistant", "event", f"All {story.target_episodes} episodes are written.")
        else:
            story.status = "paused"


def start_story(sid: str, target: int) -> None:
    submit(sid, _invoke, {"story_id": str(sid), "target_episodes": target, "current_episode": 1})


def resume(sid: str, payload: dict) -> None:
    submit(sid, _invoke, Command(resume=payload))


def retry(sid: str) -> None:
    """Re-run from the last checkpoint (the failed node executes again)."""
    submit(sid, _invoke, None)


def run_job(sid: str, fn: Callable, *args: Any) -> None:
    """Non-graph job (e.g. retroactive edit) under the same per-story lock."""
    submit(sid, lambda _sid, *a: fn(_sid, *a), *args)
