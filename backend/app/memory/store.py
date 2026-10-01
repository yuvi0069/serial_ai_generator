"""Postgres memory layer: the structured, authoritative story bible. Every write is tagged with
the episode that caused it, so any episode's contribution can be purged and rebuilt."""
import copy
import difflib
import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (ArcPlan, Character, CharacterEvent, Directive, Episode, Fact, Message,
                      Story, Summary, Thread)

STATUSES = {"alive", "dead", "missing", "unknown"}


def U(x) -> uuid.UUID:
    return x if isinstance(x, uuid.UUID) else uuid.UUID(str(x))


# ------------------------------------------------------------------ chat + story
def add_message(s: Session, sid, role: str, kind: str, content: str, meta: dict | None = None) -> None:
    """Append a line to the story's chat transcript (what the sidebar 'chat' shows on resume)."""
    s.add(Message(story_id=U(sid), role=role, kind=kind, content=content, meta=meta or {}))


def get_story(s: Session, sid) -> Story | None:
    return s.get(Story, U(sid))


# ------------------------------------------------------------------ plan
def get_plan(s: Session, sid) -> ArcPlan | None:
    return s.get(ArcPlan, U(sid))


def save_plan(s: Session, sid, plan: dict, approved: bool | None = None) -> ArcPlan:
    """Insert or replace the arc plan, bumping its version (plans are versioned, not mutated)."""
    row = get_plan(s, sid)
    if row is None:
        row = ArcPlan(story_id=U(sid), plan=copy.deepcopy(plan), version=1, approved=bool(approved))
        s.add(row)
    else:
        row.plan = copy.deepcopy(plan)
        row.version += 1
        if approved is not None:
            row.approved = approved
    return row


def beat_for(plan: dict, n: int) -> dict:
    beats = plan.get("beats", [])
    return beats[n - 1] if 1 <= n <= len(beats) else {}


def beats_range(plan: dict, a: int, b: int) -> list[dict]:
    beats = plan.get("beats", [])
    return beats[max(0, a - 1):max(0, b)]


def span_for(items: list[dict], n: int) -> dict:
    """Find the act/segment whose [start, end] contains episode n."""
    for it in items:
        if it.get("start", 0) <= n <= it.get("end", 0):
            return it
    return items[-1] if items else {}


# ------------------------------------------------------------------ names
def match_name(name: str, candidates) -> str | None:
    """Resolve an LLM-written name to a canonical one: exact, first-name/surname token, then fuzzy."""
    cands = list(candidates)
    norm = name.strip().lower()
    for c in cands:
        if c.lower() == norm:
            return c
    token_hits = [c for c in cands if norm in c.lower().split() or c.lower() in norm.split()]
    if len(token_hits) == 1:
        return token_hits[0]
    close = difflib.get_close_matches(norm, [c.lower() for c in cands], n=1, cutoff=0.85)
    if close:
        return next(c for c in cands if c.lower() == close[0])
    return None


# ------------------------------------------------------------------ bible
def characters(s: Session, sid) -> list[Character]:
    return list(s.scalars(select(Character).where(Character.story_id == U(sid)).order_by(Character.id)))


def threads(s: Session, sid) -> list[Thread]:
    return list(s.scalars(select(Thread).where(Thread.story_id == U(sid)).order_by(Thread.id)))


def seed_bible(s: Session, sid, plan: dict) -> None:
    """Create character cards and planned threads from the approved plan (idempotent)."""
    existing = {c.name for c in characters(s, sid)}
    for c in plan.get("characters", []):
        if c["name"] not in existing:
            s.add(Character(story_id=U(sid), name=c["name"], role=c.get("role", ""),
                            description=c.get("description", ""), arc=c.get("arc", ""), origin="plan"))
    existing_t = {t.name for t in threads(s, sid)}
    for t in plan.get("threads", []):
        if t["name"] not in existing_t:
            s.add(Thread(story_id=U(sid), name=t["name"], description=t.get("description", ""),
                         open_by=t.get("open_by"), resolve_by=t.get("resolve_by"), origin="plan"))


def apply_extraction(s: Session, sid, n: int, ext) -> None:
    """Write one episode's extracted facts, character events and thread transitions."""
    chars = {c.name: c for c in characters(s, sid)}
    touched = set()
    for c in ext.characters:
        name = match_name(c.name, chars.keys()) or c.name.strip()[:120]
        row = chars.get(name)
        if row is None:
            row = Character(story_id=U(sid), name=name, role=c.role, description=c.description,
                            origin="episode", first_episode=n)
            s.add(row)
            chars[name] = row
        if not row.description and c.description:
            row.description = c.description
        status = (c.status or "").lower()
        s.add(CharacterEvent(story_id=U(sid), character_name=name, episode=n,
                             status=status if status in STATUSES else None,
                             state_change=c.state_change or "", relationships=c.relationships or {}))
        touched.add(name)
    for f in ext.facts:
        s.add(Fact(story_id=U(sid), episode=n, category=f.category[:32], subject=f.subject[:200],
                   statement=f.statement, importance="high" if f.importance == "high" else "normal"))
    s.flush()
    for name in touched:
        recompute_character(s, sid, name)

    th = {t.name: t for t in threads(s, sid)}
    for t in ext.threads_opened:
        key = match_name(t.name, th.keys())
        row = th.get(key) if key else None
        if row is None:
            row = Thread(story_id=U(sid), name=t.name[:200], description=t.description, status="open",
                         origin="episode", opened_ep=n, last_touched_ep=n)
            s.add(row)
            th[row.name] = row
        elif row.status == "planned":
            row.status, row.opened_ep = "open", n
        row.last_touched_ep = n
    for name in ext.threads_advanced:
        key = match_name(name, th.keys())
        if key:
            row = th[key]
            if row.status == "planned":
                row.status, row.opened_ep = "open", n
            row.last_touched_ep = n
    for name in ext.threads_resolved:
        key = match_name(name, th.keys())
        if key:
            row = th[key]
            row.status, row.resolved_ep, row.last_touched_ep = "resolved", n, n
            row.opened_ep = row.opened_ep or n


def recompute_character(s: Session, sid, name: str) -> None:
    """Rebuild a character's current status/state/relationships by replaying its events in order."""
    row = s.scalar(select(Character).where(Character.story_id == U(sid), Character.name == name))
    if row is None:
        return
    events = list(s.scalars(select(CharacterEvent).where(
        CharacterEvent.story_id == U(sid), CharacterEvent.character_name == name).order_by(
        CharacterEvent.episode, CharacterEvent.id)))
    status, state, rel = "alive", "", {}
    for e in events:
        status = e.status or status
        state = e.state_change or state
        rel.update(e.relationships or {})
    row.status, row.current_state, row.relationships = status, state, rel
    row.last_seen_episode = events[-1].episode if events else None
    if row.origin == "episode":
        row.first_episode = events[0].episode if events else row.first_episode


def purge_episode_memory(s: Session, sid, n: int) -> None:
    """Undo everything episode n contributed (used by retroactive edits before re-extraction)."""
    names = {e.character_name for e in s.scalars(select(CharacterEvent).where(
        CharacterEvent.story_id == U(sid), CharacterEvent.episode == n))}
    s.execute(delete(Fact).where(Fact.story_id == U(sid), Fact.episode == n))
    s.execute(delete(CharacterEvent).where(CharacterEvent.story_id == U(sid), CharacterEvent.episode == n))
    s.flush()
    for name in names:
        recompute_character(s, sid, name)
        row = s.scalar(select(Character).where(Character.story_id == U(sid), Character.name == name))
        if row and row.origin == "episode" and row.last_seen_episode is None:
            s.delete(row)
    for t in threads(s, sid):
        if t.opened_ep == n:
            if t.origin == "episode":
                s.delete(t)
                continue
            t.status, t.opened_ep = "planned", None
        if t.resolved_ep == n:
            t.status, t.resolved_ep = "open", None


# ------------------------------------------------------------------ retrieval helpers
def open_threads(s: Session, sid, n: int, limit: int = 8) -> list[dict]:
    """Threads the writer must keep alive: overdue first, then longest-untouched, then due soon."""
    out = []
    for t in threads(s, sid):
        if t.status == "resolved":
            continue
        if t.status == "planned" and not (t.open_by and t.open_by <= n + 2):
            continue
        overdue = bool(t.resolve_by and t.resolve_by < n)
        idle = n - (t.last_touched_ep or t.opened_ep or n)
        out.append({"name": t.name, "description": t.description, "status": t.status,
                    "opened_ep": t.opened_ep, "resolve_by": t.resolve_by, "overdue": overdue, "idle": idle})
    out.sort(key=lambda d: (not d["overdue"], -d["idle"], d["resolve_by"] or 10_000))
    return out[:limit]


def active_directives(s: Session, sid, n: int) -> list[Directive]:
    rows = s.scalars(select(Directive).where(Directive.story_id == U(sid), Directive.active.is_(True))
                     .order_by(Directive.id))
    return [d for d in rows if d.created_ep <= n and (d.expires_ep is None or d.expires_ep >= n)]


def recent_episodes(s: Session, sid, before: int, k: int = 5) -> list[Episode]:
    rows = list(s.scalars(select(Episode).where(Episode.story_id == U(sid), Episode.number < before,
                                                Episode.status == "approved")
                          .order_by(Episode.number.desc()).limit(k)))
    return list(reversed(rows))


def high_facts(s: Session, sid, before: int, subjects: list[str], limit: int = 12) -> list[Fact]:
    rows = list(s.scalars(select(Fact).where(Fact.story_id == U(sid), Fact.episode < before,
                                             Fact.importance == "high").order_by(Fact.episode.desc())))
    subj = [x.lower() for x in subjects]
    picked = [f for f in rows if f.category == "world" or any(x in (f.subject or "").lower() for x in subj)]
    return picked[:limit]


def summaries(s: Session, sid, level: str) -> list[Summary]:
    return list(s.scalars(select(Summary).where(Summary.story_id == U(sid), Summary.level == level)
                          .order_by(Summary.start_ep)))


def upsert_summary(s: Session, sid, level: str, start: int, end: int, content: str) -> None:
    q = select(Summary).where(Summary.story_id == U(sid), Summary.level == level)
    if level == "segment":
        q = q.where(Summary.start_ep == start)
    row = s.scalar(q)
    if row is None:
        s.add(Summary(story_id=U(sid), level=level, start_ep=start, end_ep=end, content=content))
    else:
        row.start_ep, row.end_ep, row.content = start, end, content
