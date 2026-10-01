"""Quality gate: deterministic checks + LLM critic + embedding-based repetition detection."""
from ...config import settings
from ...db import session_scope
from ...memory import store
from ...memory.checks import run_checks
from ...services import vector_store
from ...services.llm import chat_json
from ...services.tracing import Trace, log_event
from .. import prompts
from ..llm_schemas import CriticOut
from ..state import StoryState


def critique(state: StoryState) -> dict:
    """Score the draft. Pass = no high-severity issue, length/overlap OK, hook and beat above thresholds."""
    sid, n, draft = state["story_id"], state["current_episode"], state["draft"]
    with session_scope() as s:
        prev_texts = [e.content for e in store.recent_episodes(s, sid, n, 3)]
        dead = [c.name for c in store.characters(s, sid) if c.status == "dead"]
    checks = run_checks(draft, prev_texts, dead)
    out, cost = chat_json(prompts.critic(state["context"], n, draft, checks["findings"]), CriticOut,
                          model=settings.critic_model, trace=Trace(sid, "critique", n), temperature=0.1, max_tokens=1500)
    issues = [i.model_dump() for i in out.issues]

    repetition = None
    if out.beat_summary:
        hits = vector_store.search(sid, out.beat_summary, ["beat"], before_episode=n, k=1, task="text-matching")
        if hits and hits[0]["score"] >= settings.repetition_threshold:
            repetition = {"episode": hits[0].get("episode"), "score": round(hits[0]["score"], 3), "text": hits[0].get("text")}
            issues.append({"type": "repetition", "severity": "high",
                           "detail": f"Plays like episode {repetition['episode']} again (similarity {repetition['score']}): "
                                     f"{repetition['text']}",
                           "fix": "Change the kind of scene, setting or outcome so this episode moves somewhere new."})
    for f in checks["findings"]:
        if "word count" in f or "repeat" in f:
            issues.append({"type": "craft", "severity": "medium", "detail": f, "fix": "fix before approval"})

    high = [i for i in issues if i.get("severity") == "high"]
    passed = (not high and not checks["hard_fail"] and out.hook_score >= settings.hook_threshold
              and out.beat_adherence >= settings.beat_threshold)
    report = {"passed": passed, "hook_score": out.hook_score, "beat_adherence": out.beat_adherence,
              "beat_summary": out.beat_summary, "issues": issues, "checks": checks,
              "repetition": repetition, "attempt": state.get("revision_count", 0) + 1}
    log_event(sid, "critique", f"attempt {report['attempt']}: {'PASS' if passed else 'FAIL'} hook={out.hook_score} "
              f"beat={out.beat_adherence} high={len(high)} words={checks['word_count']}", episode=n)
    return {"critic": report, "episode_cost": state.get("episode_cost", 0.0) + cost}


def route_after_critique(state: StoryState) -> str:
    """Stopping rules: pass -> review; else revise until max_revisions or the per-episode cost cap."""
    sid, n = state["story_id"], state["current_episode"]
    if state["critic"].get("passed"):
        return "human_review"
    if state.get("revision_count", 0) >= settings.max_revisions:
        log_event(sid, "route", f"max revisions ({settings.max_revisions}) reached -> escalate to human", episode=n)
        return "human_review"
    if state.get("episode_cost", 0.0) >= settings.max_episode_cost_usd:
        log_event(sid, "route", f"episode cost cap ${settings.max_episode_cost_usd} reached -> escalate", episode=n)
        return "human_review"
    return "revise_episode"
