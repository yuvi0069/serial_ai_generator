"""Context assembly: the heart of 'works at episode 150 as well as episode 5'.

The writer never sees the whole story. It sees a FIXED-SIZE packet assembled from layers:
  1. series bible (plan core)            - constant
  2. arc position + beat window          - constant
  3. active human directives             - small, bounded
  4. story-so-far (recompressed)         - capped ~450 words
  5. last 2 chapter summaries            - capped
  6. last 5 episode summaries            - capped
  7. last scene verbatim (~250 words)    - voice + cliffhanger continuity
  8. character cards in play + status    - capped at 8 cards, all deaths always listed
  9. open threads, overdue first         - capped at 8
 10. hard facts (importance=high)        - capped at 12
 11. semantic retrieval (Qdrant)         - top 8 older memories relevant to this beat
Packet size is ~O(1) in episode number, so cost and quality don't drift as the story grows."""
from ..config import settings
from ..db import session_scope
from ..services import vector_store
from ..services.tracing import log_event
from . import store


def _tail(text: str, words: int = 250) -> str:
    toks = text.split()
    return ("... " if len(toks) > words else "") + " ".join(toks[-words:])


def build_context(sid: str, n: int) -> tuple[str, dict]:
    """Assemble the prompt context for episode n. Returns (rendered text, metadata for tracing)."""
    with session_scope() as s:
        story = store.get_story(s, sid)
        plan = store.get_plan(s, sid).plan
        total = story.target_episodes
        beat = store.beat_for(plan, n)
        prev_beats = store.beats_range(plan, n - 2, n - 1)
        next_beats = store.beats_range(plan, n + 1, n + 3)
        act = store.span_for(plan.get("acts", []), n)
        seg = store.span_for(plan.get("segments", []), n)
        tp = [t for t in plan.get("turning_points", []) if n <= t.get("episode", 0) <= n + 10]
        directives = [f"{d.instruction} (since ep {d.created_ep}"
                      + (f", until ep {d.expires_ep})" if d.expires_ep else ")")
                      for d in store.active_directives(s, sid, n)]
        glob = store.summaries(s, sid, "global")
        segs = store.summaries(s, sid, "segment")[-2:]
        recent = store.recent_episodes(s, sid, n, 5)
        recent_nums = {e.number for e in recent}
        last_scene = _tail(recent[-1].content) if recent else ""

        all_chars = store.characters(s, sid)
        focus_text = " ".join([beat.get("beat", "")] + [b.get("beat", "") for b in next_beats]).lower()
        named = set(beat.get("characters", []))
        in_play = []
        for c in all_chars:
            first = c.name.split()[0].lower()
            score = (3 if c.name in named else 0) + (2 if first in focus_text else 0) \
                + (2 if c.last_seen_episode and n - c.last_seen_episode <= 3 else 0) \
                + (1 if "protagonist" in (c.role or "").lower() else 0)
            if score and c.status != "dead":
                in_play.append((score, c))
        in_play = [c for _, c in sorted(in_play, key=lambda x: -x[0])[:8]]
        dead = [c.name for c in all_chars if c.status == "dead"]
        missing = [c.name for c in all_chars if c.status == "missing"]
        char_lines = [
            f"- {c.name} ({c.role or 'character'}) [{c.status}]: {c.description[:220]}"
            + (f" NOW: {c.current_state[:200]}" if c.current_state else "")
            + (f" RELATIONSHIPS: " + "; ".join(f"{k}: {v}" for k, v in list(c.relationships.items())[:5])
               if c.relationships else "")
            for c in in_play]
        thread_lines = [
            f"- {t['name']} [{t['status']}{', OVERDUE (resolve by ep ' + str(t['resolve_by']) + ')' if t['overdue'] else ''}"
            f"{', untouched ' + str(t['idle']) + ' eps' if t['idle'] >= 10 else ''}]: {t['description'][:200]}"
            for t in store.open_threads(s, sid, n)]
        facts = store.high_facts(s, sid, n, [c.name for c in in_play])
        fact_lines = [f"- (ep {f.episode}) {f.statement}" for f in facts]
        fact_set = {f.statement for f in facts}

    query = " ".join([beat.get("beat", "")] + [b.get("beat", "") for b in next_beats])
    hits = vector_store.search(sid, query, ["summary", "fact"], before_episode=n, k=12) if query else []
    retrieved = [h for h in hits if not (h.get("kind") == "summary" and h.get("episode") in recent_nums)
                 and h.get("text") not in fact_set][:8]

    parts = [
        "=== SERIES BIBLE ===",
        f"Title: {plan.get('title')}\nLogline: {plan.get('logline')}\nTone: {plan.get('tone')}\nPOV: {plan.get('pov')}",
        "World rules:\n" + "\n".join(f"- {r}" for r in plan.get("world_rules", [])),
        "=== WHERE WE ARE ===",
        f"Episode {n} of {total}. Act: {act.get('name', '')} (goal: {act.get('goal', '')}). "
        f"Segment: {seg.get('title', '')} (goal: {seg.get('goal', '')}).",
    ]
    if tp:
        parts.append("Upcoming turning points: " + "; ".join(f"ep {t['episode']}: {t['event']}" for t in tp))
    parts += [
        "=== THIS EPISODE'S BEAT ===",
        f"{beat.get('beat', '(free episode: advance the open threads)')}\nIntended hook: {beat.get('hook', '')}",
        "Previous beats: " + " | ".join(b.get("beat", "") for b in prev_beats),
        "Next beats (set up, do NOT pay off yet): " + " | ".join(b.get("beat", "") for b in next_beats),
        "=== ACTIVE DIRECTIVES (from the human editor - obey) ===",
        "\n".join(f"- {d}" for d in directives) or "- none",
    ]
    if glob:
        parts += ["=== STORY SO FAR ===", glob[-1].content]
    if segs:
        parts += ["=== RECENT CHAPTERS ==="] + [f"Eps {x.start_ep}-{x.end_ep}: {x.content}" for x in segs]
    if recent:
        parts += ["=== RECENT EPISODES ==="] + [f"Ep {e.number} \"{e.title}\": {e.summary} (Hook: {e.hook})"
                                               for e in recent]
        parts += [f"=== LAST SCENE (end of ep {recent[-1].number}, verbatim - continue from here) ===", last_scene]
    parts += ["=== CHARACTERS IN PLAY ===", "\n".join(char_lines) or "- (introduce the cast per the plan)",
              f"CHARACTER STATUS: dead: {', '.join(dead) or 'none'}; missing: {', '.join(missing) or 'none'}",
              "=== OPEN THREADS ===", "\n".join(thread_lines) or "- none yet",
              "=== HARD FACTS (never contradict) ===", "\n".join(fact_lines) or "- none yet"]
    if retrieved:
        parts += ["=== RELATED MEMORY (retrieved from earlier episodes) ==="] + [
            f"- (ep {h.get('episode')}, {h.get('kind')}) {h.get('text')}" for h in retrieved]
    text = "\n".join(parts)
    meta = {"approx_tokens": len(text) // 4, "characters": [c.name for c in in_play], "dead": dead,
            "retrieved": len(retrieved), "directives": len(directives), "recent": sorted(recent_nums)}
    log_event(sid, "build_context", f"context ~{meta['approx_tokens']} tokens, {len(in_play)} chars, "
              f"{len(thread_lines)} threads, {len(fact_lines)} facts, {len(retrieved)} retrieved", episode=n)
    return text, meta
