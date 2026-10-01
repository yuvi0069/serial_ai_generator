"""Commit an approved episode into long-term memory; roll summaries; handle retroactive edits."""
from sqlalchemy import select

from ...config import settings
from ...db import session_scope
from ...memory import store
from ...memory.checks import word_count
from ...models import Episode
from ...services import vector_store
from ...services.llm import chat, chat_json
from ...services.tracing import Trace, log_event
from .. import prompts
from ..llm_schemas import ExtractionOut, RippleOut
from ..state import StoryState


def extract_and_store(sid: str, n: int, text: str, beat_text: str | None = None) -> tuple[ExtractionOut, float]:
    """Extract facts/characters/threads from episode text into Postgres + Qdrant. Idempotent: the
    episode's previous contribution is purged first, so retries and retro-edits never duplicate."""
    with session_scope() as s:
        known_c = [c.name for c in store.characters(s, sid)]
        known_t = [t.name for t in store.threads(s, sid) if t.status != "resolved"]
    ext, cost = chat_json(prompts.extractor(n, text, known_c, known_t), ExtractionOut,
                          model=settings.extractor_model, trace=Trace(sid, "extract_memory", n),
                          temperature=0.1, max_tokens=2500)
    with session_scope() as s:
        store.purge_episode_memory(s, sid, n)
        store.apply_extraction(s, sid, n, ext)
        ep = s.scalar(select(Episode).where(Episode.story_id == store.U(sid), Episode.number == n))
        ep.summary, ep.hook = ext.summary, ext.hook
        ep.beat_summary = beat_text or ext.summary
    items = [{"kind": "summary", "text": f"Ep {n}: {ext.summary}"},
             {"kind": "beat", "text": beat_text or ext.summary}]
    items += [{"kind": "fact", "text": f.statement, "meta": {"importance": f.importance, "subject": f.subject}}
              for f in ext.facts]
    vector_store.delete_episode(sid, n)
    try:
        vector_store.upsert_items(sid, n, items)
    except Exception as e:  # semantic layer is an accelerator, not the source of truth
        log_event(sid, "extract_memory", "vector upsert failed; Postgres memory intact", episode=n,
                  status="error", error=str(e)[:500])
    return ext, cost


def summarize_segment(sid: str, start: int, end: int, update_global: bool = True) -> None:
    """Compress episodes [start, end] into a chapter summary and fold it into the story-so-far."""
    with session_scope() as s:
        eps = list(s.scalars(select(Episode).where(Episode.story_id == store.U(sid), Episode.number >= start,
                                                   Episode.number <= end).order_by(Episode.number)))
        prev_global = (store.summaries(s, sid, "global") or [None])[-1]
    seg = chat(prompts.segment_summary(start, end, [e.summary for e in eps]), model=settings.utility_model,
               trace=Trace(sid, "summarize_segment", end), temperature=0.2, max_tokens=500).text
    with session_scope() as s:
        store.upsert_summary(s, sid, "segment", start, end, seg)
    if update_global:
        glob = chat(prompts.global_summary(prev_global.content if prev_global else "", seg, start, end),
                    model=settings.extractor_model, trace=Trace(sid, "summarize_global", end),
                    temperature=0.2, max_tokens=900).text
        with session_scope() as s:
            store.upsert_summary(s, sid, "global", 1, end, glob)
    log_event(sid, "summarize", f"chapter summary eps {start}-{end}" + (" + story-so-far" if update_global else ""), episode=end)


def commit_memory(state: StoryState) -> dict:
    """Persist the approved episode, extract its memory, roll summaries at segment boundaries."""
    sid, n = state["story_id"], state["current_episode"]
    critic = state.get("critic", {})
    edited = state.get("human_action") == "edit"
    auto = state.get("review_reason") == "auto"
    draft = state["draft"]
    with session_scope() as s:
        ep = s.scalar(select(Episode).where(Episode.story_id == store.U(sid), Episode.number == n))
        if ep is None:
            ep = Episode(story_id=store.U(sid), number=n)
            s.add(ep)
        ep.title, ep.content, ep.word_count = state.get("draft_title", ""), draft, word_count(draft)
        ep.status, ep.revisions, ep.human_edited, ep.auto_approved = "approved", state.get("revision_count", 0), edited, auto
        ep.critic_report = critic
    beat_text = None if edited else critic.get("beat_summary")
    ext, cost = extract_and_store(sid, n, draft, beat_text)
    seg = settings.segment_size
    if n % seg == 0:
        summarize_segment(sid, n - seg + 1, n)
    total_cost = state.get("episode_cost", 0.0) + cost
    with session_scope() as s:
        ep = s.scalar(select(Episode).where(Episode.story_id == store.U(sid), Episode.number == n))
        ep.cost_usd = round(total_cost, 6)
        story = store.get_story(s, sid)
        story.current_episode = n + 1
        store.add_message(s, sid, "assistant", "episode", draft, {
            "episode": n, "title": ep.title, "summary": ext.summary, "hook": ext.hook,
            "word_count": ep.word_count, "auto_approved": auto, "human_edited": edited,
            "revisions": ep.revisions, "hook_score": critic.get("hook_score"),
            "cost_usd": round(total_cost, 5)})
    log_event(sid, "commit_memory", f"ep {n} committed: {len(ext.facts)} facts, {len(ext.characters)} character "
              f"updates, +{len(ext.threads_opened)}/-{len(ext.threads_resolved)} threads, ${total_cost:.4f}", episode=n)
    return {"current_episode": n + 1, "batch_remaining": max(0, state.get("batch_remaining", 1) - 1),
            "auto_approve_remaining": max(0, state.get("auto_approve_remaining", 0) - 1),
            "draft": "", "draft_title": "", "critic": {}, "human_action": None, "human_feedback": None,
            "review_reason": None, "revision_count": 0, "episode_cost": 0.0}


def route_after_commit(state: StoryState) -> str:
    """Continue the batch unless the story is finished, out of budget, or the batch is done."""
    sid, n = state["story_id"], state["current_episode"]
    if n > state["target_episodes"]:
        return "next_gate"
    with session_scope() as s:
        cost = store.get_story(s, sid).total_cost_usd
    if cost >= settings.max_story_cost_usd:
        log_event(sid, "route", f"story budget ${settings.max_story_cost_usd} reached -> pause for human", episode=n)
        return "next_gate"
    return "build_context" if state.get("batch_remaining", 0) > 0 else "next_gate"


def retro_edit(sid: str, n: int, content: str, title: str | None) -> None:
    """A human rewrote an already-approved episode n (the 'edit episode 40' case):
    1) replace text, 2) purge + re-extract ep n's memory (character state is rebuilt from events),
    3) rebuild affected summaries, 4) ripple-check later episodes and report conflicts."""
    with session_scope() as s:
        ep = s.scalar(select(Episode).where(Episode.story_id == store.U(sid), Episode.number == n))
        old_summary = ep.summary
        ep.content, ep.word_count, ep.human_edited = content, word_count(content), True
        if title:
            ep.title = title
        current = store.get_story(s, sid).current_episode
    ext, _ = extract_and_store(sid, n, content)
    seg = settings.segment_size
    start = ((n - 1) // seg) * seg + 1
    if start + seg - 1 < current:
        summarize_segment(sid, start, start + seg - 1, update_global=False)
        with session_scope() as s:
            segs = store.summaries(s, sid, "segment")
        joined = "\n".join(f"Eps {x.start_ep}-{x.end_ep}: {x.content}" for x in segs)
        glob = chat(prompts.global_summary("", joined, 1, segs[-1].end_ep), model=settings.extractor_model,
                    trace=Trace(sid, "summarize_global", n), temperature=0.2, max_tokens=900).text
        with session_scope() as s:
            store.upsert_summary(s, sid, "global", 1, segs[-1].end_ep, glob)
    with session_scope() as s:
        later = [(e.number, e.summary) for e in s.scalars(select(Episode).where(
            Episode.story_id == store.U(sid), Episode.number > n).order_by(Episode.number).limit(30))]
    conflicts, ack = [], f"Episode {n} updated and its memory rebuilt."
    if later:
        out, _ = chat_json(prompts.ripple(n, old_summary, ext.summary, later), RippleOut,
                           model=settings.critic_model, trace=Trace(sid, "ripple_check", n), temperature=0.1)
        conflicts = [c.model_dump() for c in out.conflicts]
        ack = out.ack or (f"{len(conflicts)} later episode(s) may now conflict." if conflicts else ack)
    with session_scope() as s:
        store.add_message(s, sid, "assistant", "ripple", ack, {"episode": n, "conflicts": conflicts})
    log_event(sid, "retro_edit", f"ep {n} rewritten by human; {len(conflicts)} downstream conflicts", episode=n)
