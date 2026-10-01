"""Planning nodes: skeleton (acts, characters, threads, turning points) -> beats per segment."""
import math

from ...config import settings
from ...db import session_scope
from ...memory import store
from ...services.llm import chat_json
from ...services.tracing import Trace, log_event
from .. import prompts
from ..llm_schemas import BeatsOut, PlanSkeleton
from ..state import StoryState


def normalize_skeleton(sk: dict, total: int, seg_len: int) -> dict:
    """Force the LLM's skeleton into a valid shape: contiguous acts covering 1..total, exactly
    ceil(total/seg_len) segments with computed ranges, clamped episode numbers."""
    clamp = lambda x: max(1, min(total, int(x)))
    acts = sorted(sk.get("acts") or [], key=lambda a: a.get("start", 0))
    if not acts:
        q = math.ceil(total / 4)
        acts = [{"name": f"Act {i + 1}", "start": i * q + 1, "end": min(total, (i + 1) * q), "goal": ""} for i in range(4)]
    for i, a in enumerate(acts):
        a["start"] = 1 if i == 0 else acts[i - 1]["end"] + 1
        a["end"] = total if i == len(acts) - 1 else max(a["start"], clamp(a.get("end", a["start"])))
    acts = [a for a in acts if a["start"] <= total]
    acts[-1]["end"] = total
    n_seg = math.ceil(total / seg_len)
    raw = sk.get("segments") or []
    segs = []
    for i in range(n_seg):
        src = raw[i] if i < len(raw) else {}
        segs.append({"index": i + 1, "start": i * seg_len + 1, "end": min(total, (i + 1) * seg_len),
                     "title": src.get("title") or f"Part {i + 1}", "goal": src.get("goal", "")})
    for t in sk.get("turning_points", []):
        t["episode"] = clamp(t.get("episode", 1))
    for t in sk.get("threads", []):
        t["open_by"] = clamp(t["open_by"]) if t.get("open_by") else None
        t["resolve_by"] = clamp(t["resolve_by"]) if t.get("resolve_by") else None
    return {**sk, "acts": acts, "segments": segs, "total_episodes": total, "beats": []}


def normalize_beats(beats: list, start: int, end: int, seg: dict) -> list[dict]:
    """Exactly one beat per episode in [start, end]; gaps are filled with a segment-goal beat."""
    by_ep = {b.episode: b.model_dump() for b in beats if start <= b.episode <= end}
    return [by_ep.get(e) or {"episode": e, "beat": f"Advance the segment goal: {seg.get('goal', '')}",
                             "hook": "", "characters": [], "threads": []} for e in range(start, end + 1)]


def plan_arc(state: StoryState) -> dict:
    """Generate (or revise, if the human left plan feedback) the series skeleton."""
    sid = state["story_id"]
    with session_scope() as s:
        story = store.get_story(s, sid)
        premise, total = story.premise, story.target_episodes
        prev = store.get_plan(s, sid)
        prev_plan = prev.plan if prev else None
    fb = state.get("plan_feedback")
    seg_len = settings.beats_per_plan_chunk
    n_seg = math.ceil(total / seg_len)
    sk, _ = chat_json(prompts.plan_skeleton(premise, total, n_seg, seg_len, prev_plan, fb), PlanSkeleton,
                      model=settings.planner_model, trace=Trace(sid, "plan_arc"), temperature=0.8, max_tokens=6000)
    plan = normalize_skeleton(sk.model_dump(), total, seg_len)
    with session_scope() as s:
        store.save_plan(s, sid, plan, approved=False)
        story = store.get_story(s, sid)
        story.status = "planning"
        if not story.title_locked and plan.get("title"):
            story.title = plan["title"][:200]
    log_event(sid, "plan_arc", f"skeleton: {len(plan['acts'])} acts, {len(plan.get('characters', []))} characters, "
              f"{len(plan.get('threads', []))} threads, {len(plan['segments'])} segments" + (" (revision)" if fb else ""))
    return {"phase": "planning", "target_episodes": total}


def expand_beats(state: StoryState) -> dict:
    """Expand every segment into per-episode beats, one LLM call per segment. Progress is saved after
    each segment, so a crash/retry resumes from the first unexpanded segment."""
    sid = state["story_id"]
    fb = state.get("plan_feedback")
    with session_scope() as s:
        plan = store.get_plan(s, sid).plan
    beats: list[dict] = list(plan.get("beats") or [])
    for seg in plan["segments"]:
        if len(beats) >= seg["end"]:
            continue
        out, _ = chat_json(prompts.plan_beats(plan, seg["start"], seg["end"], seg, beats[-3:], fb), BeatsOut,
                           model=settings.planner_model, trace=Trace(sid, "expand_beats"),
                           temperature=0.8, max_tokens=5000)
        beats = beats[:seg["start"] - 1] + normalize_beats(out.beats, seg["start"], seg["end"], seg)
        plan["beats"] = beats
        with session_scope() as s:
            row = store.get_plan(s, sid)
            row.plan = {**plan}
        log_event(sid, "expand_beats", f"segment {seg['index']}/{len(plan['segments'])} expanded "
                                       f"(eps {seg['start']}-{seg['end']})")
    with session_scope() as s:
        row = store.get_plan(s, sid)
        store.add_message(s, sid, "assistant", "plan",
                          f"The {plan['total_episodes']}-episode arc plan is ready for review: "
                          f"{len(plan['acts'])} acts, {len(plan.get('characters', []))} characters, "
                          f"{len(plan.get('threads', []))} threads.",
                          {"version": row.version, "title": plan.get("title"), "logline": plan.get("logline")})
    return {"plan_feedback": None}


def init_bible(state: StoryState) -> dict:
    """Plan approved: mark it canon and seed character cards + planned threads."""
    sid = state["story_id"]
    with session_scope() as s:
        row = store.get_plan(s, sid)
        row.approved = True
        store.seed_bible(s, sid, row.plan)
        story = store.get_story(s, sid)
        story.status = "writing"
        store.add_message(s, sid, "assistant", "event",
                          f"Plan v{row.version} approved. Story bible seeded with "
                          f"{len(row.plan.get('characters', []))} characters and {len(row.plan.get('threads', []))} threads.")
    log_event(sid, "init_bible", "plan approved, bible seeded")
    return {"phase": "writing", "current_episode": state.get("current_episode") or 1,
            "batch_remaining": 0, "auto_approve_remaining": 0}
