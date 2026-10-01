"""/stories: the chat-like story workspace (list, create, rename, resume, act, inspect, export)."""
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..db import get_db
from ..graph.checkpointer import delete_thread
from ..graph.nodes.memory_nodes import retro_edit
from ..memory import store
from ..models import (CHILD_TABLES, ArcPlan, Character, Directive, Episode, Message, RunLog, Story,
                      Summary, Thread, User)
from ..schemas import ActIn, EpisodeEditIn, MessageOut, StoryCreate, StoryOut, StoryRename
from ..services import runner, vector_store

router = APIRouter(prefix="/stories", tags=["stories"])


def owned_story(story_id: uuid.UUID, user: User, db: Session) -> Story:
    """Load a story and enforce that it belongs to the caller (404 otherwise, no existence leak)."""
    story = db.get(Story, story_id)
    if not story or story.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Story not found.")
    return story


def busy():
    return HTTPException(status.HTTP_409_CONFLICT, "The story is already working. Wait for it to finish.")


@router.get("", response_model=list[StoryOut])
def list_stories(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Sidebar: the user's stories, most recently active first."""
    return list(db.scalars(select(Story).where(Story.user_id == user.id).order_by(Story.updated_at.desc())))


@router.post("", response_model=StoryOut, status_code=201)
def create_story(body: StoryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """New 'chat': store the premise and start planning in the background."""
    premise = body.premise.strip()
    story = Story(user_id=user.id, premise=premise, target_episodes=body.target_episodes,
                  title=(premise[:57] + "...") if len(premise) > 60 else premise)
    db.add(story)
    db.flush()
    store.add_message(db, story.id, "user", "text", premise)
    db.commit()
    runner.start_story(str(story.id), body.target_episodes)
    return story


@router.patch("/{story_id}", response_model=StoryOut)
def rename_story(story_id: uuid.UUID, body: StoryRename, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """Rename the chat heading; locks it so the planner won't overwrite it."""
    story = owned_story(story_id, user, db)
    story.title, story.title_locked = body.title.strip(), True
    db.commit()
    return story


@router.delete("/{story_id}", status_code=204)
def delete_story(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete the story, its memory (Postgres + Qdrant) and its graph checkpoints."""
    story = owned_story(story_id, user, db)
    if runner.is_running(str(story_id)):
        raise busy()
    for model in CHILD_TABLES:
        db.execute(delete(model).where(model.story_id == story_id))
    db.execute(delete(RunLog).where(RunLog.story_id == story_id))
    db.delete(story)
    db.commit()
    vector_store.delete_episode(str(story_id), None)
    delete_thread(str(story_id))


@router.get("/{story_id}/state")
def get_state(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Polled by the UI: story row, whether a run is active, what the graph is waiting for,
    the latest trace line (live activity), and per-episode statuses for the story spine."""
    story = owned_story(story_id, user, db)
    running = runner.is_running(str(story_id))
    pending = None if running else runner.pending_interrupt(str(story_id))
    last = db.scalar(select(RunLog).where(RunLog.story_id == story_id).order_by(RunLog.id.desc()).limit(1))
    eps = db.execute(select(Episode.number, Episode.human_edited, Episode.auto_approved)
                     .where(Episode.story_id == story_id)).all()
    return {"story": StoryOut.model_validate(story).model_dump(mode="json"), "running": running, "pending": pending,
            "activity": f"{last.node}: {last.decision or last.error or ''}" if last else None,
            "episodes": [{"n": e[0], "edited": e[1], "auto": e[2]} for e in eps]}


@router.get("/{story_id}/messages", response_model=list[MessageOut])
def get_messages(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Full chat transcript for resuming a story."""
    owned_story(story_id, user, db)
    return list(db.scalars(select(Message).where(Message.story_id == story_id).order_by(Message.created_at)))


def _describe(body: ActIn, ptype: str) -> str:
    if ptype == "continue" and body.action == "continue":
        return f"Write the next {body.count or 1} episode(s)" + (" with auto-approve" if body.auto_approve else "")
    label = {"approve": "Approved", "edit": "Saved my edits", "reject": "Rejected", "feedback": "Feedback"}[body.action] \
        if body.action in ("approve", "edit", "reject", "feedback") else body.action
    return f"{label}" + (f": {body.feedback}" if body.feedback else "")


@router.post("/{story_id}/act")
def act(story_id: uuid.UUID, body: ActIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Answer the current gate and resume the graph in the background."""
    owned_story(story_id, user, db)
    sid = str(story_id)
    if runner.is_running(sid):
        raise busy()
    pending = runner.pending_interrupt(sid)
    if not pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for your input right now.")
    allowed = {"plan_review": {"approve", "edit", "feedback"}, "episode_review": {"approve", "edit", "reject"},
               "continue": {"continue", "feedback"}}[pending["type"]]
    if body.action not in allowed:
        raise HTTPException(422, f"'{body.action}' isn't available here. Choose one of: {', '.join(sorted(allowed))}.")
    if body.action == "feedback" and not body.feedback:
        raise HTTPException(422, "Write the feedback first.")
    if body.action == "edit" and pending["type"] == "episode_review" and not body.text:
        raise HTTPException(422, "The edited episode text is empty.")
    if body.action == "edit" and pending["type"] == "plan_review" and not body.plan:
        raise HTTPException(422, "The edited plan is empty.")
    kind = "feedback" if body.feedback else "text"
    store.add_message(db, story_id, "user", kind, _describe(body, pending["type"]),
                      {"action": body.action, "gate": pending["type"], "episode": pending.get("episode")})
    db.commit()
    try:
        runner.resume(sid, body.model_dump(exclude_none=True))
    except runner.Busy:
        raise busy()
    return {"ok": True}


@router.post("/{story_id}/retry")
def retry(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Resume after an error from the last good checkpoint."""
    story = owned_story(story_id, user, db)
    if story.status != "error":
        raise HTTPException(409, "There is no failed run to retry.")
    try:
        runner.retry(str(story_id))
    except runner.Busy:
        raise busy()
    return {"ok": True}


@router.get("/{story_id}/plan")
def get_plan(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_story(story_id, user, db)
    row = db.get(ArcPlan, story_id)
    if not row:
        raise HTTPException(404, "The plan hasn't been generated yet.")
    return {"plan": row.plan, "version": row.version, "approved": row.approved}


@router.get("/{story_id}/episodes/{number}")
def get_episode(story_id: uuid.UUID, number: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    owned_story(story_id, user, db)
    ep = db.scalar(select(Episode).where(Episode.story_id == story_id, Episode.number == number))
    if not ep:
        raise HTTPException(404, "Episode not found.")
    return {c.name: getattr(ep, c.name) for c in Episode.__table__.columns if c.name != "story_id"}


@router.put("/{story_id}/episodes/{number}")
def edit_past_episode(story_id: uuid.UUID, number: int, body: EpisodeEditIn, user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    """Retroactive edit of an approved episode: rebuild its memory and ripple-check later episodes."""
    owned_story(story_id, user, db)
    ep = db.scalar(select(Episode).where(Episode.story_id == story_id, Episode.number == number))
    if not ep:
        raise HTTPException(404, "Episode not found.")
    store.add_message(db, story_id, "user", "text", f"Rewrote episode {number}.", {"action": "retro_edit", "episode": number})
    db.commit()
    try:
        runner.run_job(str(story_id), retro_edit, number, body.content, body.title)
    except runner.Busy:
        raise busy()
    return {"ok": True}


@router.get("/{story_id}/memory")
def get_memory(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Inspect the story bible: characters, threads, directives, summaries."""
    owned_story(story_id, user, db)
    q = lambda m, *order: list(db.scalars(select(m).where(m.story_id == story_id).order_by(*order)))
    row = lambda o, cols: {c: getattr(o, c) for c in cols}
    return {
        "characters": [row(c, ["name", "role", "status", "description", "current_state", "relationships",
                               "first_episode", "last_seen_episode", "origin"]) for c in q(Character, Character.id)],
        "threads": [row(t, ["name", "description", "status", "opened_ep", "resolved_ep", "resolve_by",
                            "last_touched_ep", "origin"]) for t in q(Thread, Thread.id)],
        "directives": [row(d, ["id", "instruction", "kind", "target", "active", "created_ep", "expires_ep",
                               "source_feedback"]) for d in q(Directive, Directive.id)],
        "summaries": [row(x, ["level", "start_ep", "end_ep", "content"]) for x in q(Summary, Summary.level, Summary.start_ep)],
    }


@router.patch("/{story_id}/directives/{directive_id}")
def toggle_directive(story_id: uuid.UUID, directive_id: int, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Switch a standing directive on/off (a human can retire old feedback)."""
    owned_story(story_id, user, db)
    d = db.get(Directive, directive_id)
    if not d or d.story_id != story_id:
        raise HTTPException(404, "Directive not found.")
    d.active = not d.active
    db.commit()
    return {"id": d.id, "active": d.active}


@router.get("/{story_id}/logs")
def get_logs(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Trace + cost dashboard: per-node totals, per-episode cost, projection to the full run."""
    story = owned_story(story_id, user, db)
    rows = list(db.scalars(select(RunLog).where(RunLog.story_id == story_id).order_by(RunLog.id.desc()).limit(300)))
    agg = db.execute(select(RunLog.node, func.count(), func.sum(RunLog.prompt_tokens), func.sum(RunLog.completion_tokens),
                            func.sum(RunLog.cost_usd), func.avg(RunLog.latency_ms))
                     .where(RunLog.story_id == story_id, RunLog.status != "event").group_by(RunLog.node)).all()
    errors = db.scalar(select(func.count()).where(RunLog.story_id == story_id, RunLog.status == "error"))
    ep_costs = db.execute(select(Episode.number, Episode.cost_usd, Episode.revisions)
                          .where(Episode.story_id == story_id).order_by(Episode.number)).all()
    per_ep = defaultdict(float)
    for r in db.execute(select(RunLog.episode, func.sum(RunLog.latency_ms)).where(
            RunLog.story_id == story_id, RunLog.episode.is_not(None)).group_by(RunLog.episode)).all():
        per_ep[r[0]] = r[1] or 0
    avg_cost = sum(c[1] for c in ep_costs) / len(ep_costs) if ep_costs else 0.0
    avg_ms = sum(per_ep[c[0]] for c in ep_costs) / len(ep_costs) if ep_costs else 0.0
    remaining = max(0, story.target_episodes - len(ep_costs))
    return {
        "total_cost_usd": round(story.total_cost_usd, 5), "errors": errors,
        "by_node": [{"node": a[0], "calls": a[1], "prompt_tokens": a[2] or 0, "completion_tokens": a[3] or 0,
                     "cost_usd": round(a[4] or 0, 5), "avg_latency_ms": int(a[5] or 0)} for a in agg],
        "episodes": [{"n": c[0], "cost_usd": c[1], "revisions": c[2]} for c in ep_costs],
        "projection": {"avg_cost_per_episode": round(avg_cost, 5), "avg_seconds_per_episode": round(avg_ms / 1000, 1),
                       "remaining_episodes": remaining,
                       "projected_remaining_cost": round(avg_cost * remaining, 3),
                       "projected_remaining_hours": round(avg_ms * remaining / 3_600_000, 2)},
        "recent": [{"id": r.id, "episode": r.episode, "node": r.node, "model": r.model, "attempt": r.attempt,
                    "tokens": r.prompt_tokens + r.completion_tokens, "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
                    "status": r.status, "decision": r.decision, "error": r.error,
                    "at": r.created_at.isoformat()} for r in rows],
    }


@router.get("/{story_id}/export", response_class=PlainTextResponse)
def export_markdown(story_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Deliverable export: full arc plan + every written episode + HITL interventions, as Markdown."""
    story = owned_story(story_id, user, db)
    row = db.get(ArcPlan, story_id)
    p = row.plan if row else {}
    out = [f"# {story.title}", f"_Premise:_ {story.premise}", "", f"**Logline:** {p.get('logline', '')}",
           f"**Tone:** {p.get('tone', '')}  |  **POV:** {p.get('pov', '')}", "", "## Acts"]
    out += [f"- **{a['name']}** (eps {a['start']}-{a['end']}): {a.get('goal', '')} -> {a.get('turning_point', '')}"
            for a in p.get("acts", [])]
    out += ["", "## Characters"] + [f"- **{c['name']}** ({c.get('role', '')}): {c.get('arc', '')}" for c in p.get("characters", [])]
    out += ["", "## Threads"] + [f"- **{t['name']}** (open by {t.get('open_by')}, resolve by {t.get('resolve_by')}): "
                                 f"{t.get('description', '')}" for t in p.get("threads", [])]
    out += ["", "## Turning points"] + [f"- Ep {t['episode']}: {t['event']}" for t in p.get("turning_points", [])]
    out += ["", f"## Episode beats (plan v{row.version if row else 0})"]
    for seg in p.get("segments", []):
        out.append(f"\n### Part {seg['index']}: {seg['title']} (eps {seg['start']}-{seg['end']})\n_{seg.get('goal', '')}_")
        out += [f"{b['episode']}. {b['beat']}" for b in p.get("beats", [])[seg["start"] - 1:seg["end"]]]
    out += ["", "## Human interventions"]
    for m in db.scalars(select(Message).where(Message.story_id == story_id, Message.kind.in_(["feedback"]))
                        .order_by(Message.created_at)):
        out.append(f"- [{m.role}] {m.content}" + (f" (beats changed: {m.meta.get('beats_changed')})"
                                                   if m.meta.get("beats_changed") else ""))
    out += ["", "## Episodes"]
    for e in db.scalars(select(Episode).where(Episode.story_id == story_id).order_by(Episode.number)):
        flags = ", ".join(f for f, on in [("human-edited", e.human_edited), ("auto-approved", e.auto_approved)] if on)
        out += [f"\n### Episode {e.number}: {e.title}" + (f" _({flags})_" if flags else ""),
                f"_{e.word_count} words, {e.revisions} revision(s), ${e.cost_usd:.4f}_", "", e.content]
    return "\n".join(out)
