"""Deterministic fake LLM for OFFLINE_MODE: exercises the whole graph (routing, HITL, memory,
tracing) with no API keys. Used by tests/test_offline_flow.py and CI."""
import json
import random
import re

from .llm import LLMResult
from .tracing import Trace, log_run

WORDS = ("rain lantern stairwell ledger courier parcel radiator siren concrete neon doorbell elevator "
         "receipt helmet basement landlord whisper static ashtray window corridor mailbox ticket scooter "
         "fuse archive photograph key hinge smoke kettle ribbon").split()


def _prose(seed: int, n: int = 520) -> str:
    rnd = random.Random(seed)
    sents = []
    while sum(len(s.split()) for s in sents) < n:
        sents.append(" ".join(rnd.choice(WORDS) for _ in range(rnd.randint(8, 16))).capitalize() + ".")
    return " ".join(sents) + " Then the door behind her clicked shut, and someone inside said her name."


def fake_chat(messages, *, model: str, trace: Trace, json_mode: bool) -> LLMResult:
    text = messages[-1]["content"]
    ep = trace.episode or 0
    node = trace.node
    if node == "plan_arc":
        total = int(re.search(r"full (\d+)-episode", text).group(1))
        out = {"title": "The Last Route", "logline": "A rider delivers to the dead.", "tone": "eerie", "pov": "close third, past",
               "world_rules": ["Addresses only appear after midnight"],
               "acts": [{"name": f"Act {i + 1}", "start": i * total // 4 + 1, "end": (i + 1) * total // 4, "goal": "g"} for i in range(4)],
               "characters": [{"name": "Maya Chen", "role": "protagonist", "arc": "a->b"},
                              {"name": "Theo Park", "role": "love interest", "arc": "a->b"},
                              {"name": "Mr. Hale", "role": "antagonist", "arc": "a->b"}],
               "threads": [{"name": "The building", "open_by": 1, "resolve_by": total}],
               "turning_points": [{"episode": total // 2, "event": "midpoint"}],
               "segments": [{"title": f"Part {i}", "goal": "escalate"} for i in range(20)]}
    elif node == "expand_beats":
        a, b = map(int, re.search(r"EPISODES (\d+)-(\d+)", text).groups())
        out = {"beats": [{"episode": e, "beat": f"Beat {e}: Maya follows delivery #{e}.", "hook": "a knock",
                          "characters": ["Maya Chen"], "threads": ["The building"]} for e in range(a, b + 1)]}
    elif node in ("write_episode", "revise_episode"):
        body = _prose(ep * 7 + (node == "revise_episode"))
        return _res(f"TITLE: Delivery {ep}\n\n{body}", model, trace)
    elif node == "critique":
        out = {"beat_summary": f"Episode {ep}: Maya delivers parcel {ep} and finds {random.Random(ep).choice(WORDS)}.",
               "hook_score": 8, "beat_adherence": 8, "issues": []}
    elif node == "extract_memory":
        out = {"summary": f"In episode {ep} Maya delivered parcel {ep}.", "hook": "a voice",
               "facts": [{"category": "timeline", "subject": "Maya Chen", "statement": f"Maya made delivery {ep}", "importance": "normal"}],
               "characters": [{"name": "Maya", "status": "alive", "state_change": f"shaken after ep {ep}"}],
               "threads_advanced": ["The building"]}
    elif node == "apply_feedback":
        out = {"scope": "forward", "directive": {"kind": "pacing", "target": "romance", "instruction": "Keep the romance slow."},
               "beat_updates": [{"episode": ep + 1, "beat": "Rewritten beat honouring feedback", "hook": "h"}],
               "ack": "From the next episode the romance slows down."}
    elif node == "ripple_check":
        out = {"conflicts": [], "ack": "No downstream conflicts."}
    else:
        return _res(f"Summary of events up to episode {ep}.", model, trace)
    return _res(json.dumps(out), model, trace)


def _res(text: str, model: str, trace: Trace) -> LLMResult:
    pt, ct = 1000, len(text) // 4
    from .llm import cost_of
    cost = cost_of(model, pt, ct)
    log_run(trace, model=model, prompt_tokens=pt, completion_tokens=ct, cost_usd=cost, latency_ms=5, decision="offline")
    return LLMResult(text, model, pt, ct, cost, 5)
