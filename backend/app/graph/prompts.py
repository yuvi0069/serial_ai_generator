"""All prompt templates in one place (versioned with the code, diffable, testable)."""
import json

from ..config import settings

BANNED_PHRASES = [
    "a testament to", "little did", "couldn't help but", "the weight of", "tapestry",
    "sent shivers", "a chill ran down", "in that moment", "time seemed to stop", "unbeknownst",
    "palpable", "a mix of", "only time would tell", "heart pounding in", "let out a breath",
    "the air was thick", "every fiber of", "eyes widened", "a sense of dread",
]

CRAFT_RULES = f"""Craft rules (non-negotiable):
- Open in motion, inside a scene. Never open with a recap of earlier episodes.
- One or two scenes, concrete sensory detail, specific nouns (brand, street, object) over adjectives.
- Dialogue carries subtext; people dodge, lie, interrupt. No speeches explaining feelings.
- Every episode must CHANGE something: a fact revealed, a relationship shifted, a door closed.
- Last paragraph is the hook: a specific new question, danger, reversal or decision. Not vague foreboding.
- {settings.min_words}-{settings.max_words} words. Keep POV and tense consistent with the series bible.
- Never use these phrases: {", ".join(BANNED_PHRASES)}.
- Do not resolve threads or kill characters unless the beat or a directive says so.
- Do not contradict anything in HARD FACTS, CHARACTER STATUS or DIRECTIVES."""


def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=None)


# ------------------------------------------------------------------ planning
def plan_skeleton(premise: str, n_eps: int, n_segments: int, seg_len: int,
                  previous: dict | None = None, feedback: str | None = None) -> list[dict]:
    system = (f"You are the showrunner of a serialized fiction app. You design stories that sustain "
              f"{n_eps} short episodes without sagging: escalating stakes, fair mysteries, reversals, "
              f"and character arcs that genuinely change people. You answer in JSON only.")
    revise = ""
    if previous and feedback:
        prev = {k: v for k, v in previous.items() if k != "beats"}
        revise = (f"\n\nREVISION MODE. Previous plan:\n{_j(prev)}\n\nHuman feedback to address:\n"
                  f"\"{feedback}\"\nKeep what works; change what the feedback asks for.")
    user = f"""Premise: "{premise}"

Design the full {n_eps}-episode arc (each episode is {settings.min_words}-{settings.max_words} words and ends on a hook).
Requirements:
- 4-5 acts covering episodes 1..{n_eps} exactly, contiguous, each with a goal and the turning point that ends it.
- 10-14 turning points with episode numbers spread across the whole run (not front-loaded).
- 6-10 characters incl. antagonistic forces; each with an arc stated as "starts as X -> ends as Y".
- 10-16 story threads (mysteries, relationships, subplots) with open_by and resolve_by episodes; stagger
  them so some resolve every act and new ones open to replace them.
- 4-8 world rules: the logic of the premise that must never be broken.
- Exactly {n_segments} segments (each ~{seg_len} episodes, in order) with a title and a goal.
- tone, pov (e.g. "close third, past tense, follows <name>"), themes, and how it ends.{revise}

Return JSON: {{"title":str,"logline":str,"genre":str,"tone":str,"pov":str,"world_rules":[str],
"themes":[str],"acts":[{{"name":str,"start":int,"end":int,"goal":str,"turning_point":str}}],
"characters":[{{"name":str,"role":str,"description":str,"arc":str}}],
"threads":[{{"name":str,"description":str,"open_by":int,"resolve_by":int}}],
"turning_points":[{{"episode":int,"event":str}}],"segments":[{{"title":str,"goal":str}}],"ending":str}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def plan_beats(skeleton: dict, start: int, end: int, segment: dict, prev_beats: list[dict],
               feedback: str | None = None) -> list[dict]:
    core = {k: skeleton.get(k) for k in ("title", "logline", "tone", "pov", "world_rules", "acts",
                                          "characters", "threads", "turning_points", "ending")}
    tps = [t for t in skeleton.get("turning_points", []) if start <= t.get("episode", 0) <= end]
    fb = f'\nHuman feedback on the plan (honour it): "{feedback}"' if feedback else ""
    user = f"""Series plan:\n{_j(core)}

Write beats for EPISODES {start}-{end}. Segment: "{segment.get('title', '')}" - goal: {segment.get('goal', '')}.
Turning points inside this range (must land on these exact episodes): {_j(tps)}
Last beats before this range: {_j(prev_beats)}{fb}

Rules: one beat per episode, 1-2 sentences, a concrete event and what it changes, plus the hook it ends on.
No two beats may be the same kind of scene. Open/resolve threads on schedule. Escalate across the range.
Return JSON: {{"beats":[{{"episode":int,"beat":str,"hook":str,"characters":[str],"threads":[str]}}]}}"""
    return [{"role": "system", "content": "You are a story editor breaking a season into episode beats. JSON only."},
            {"role": "user", "content": user}]


# ------------------------------------------------------------------ writing
def writer(context: str, n: int, total: int, reject_note: str | None = None) -> list[dict]:
    note = (f"\n\nThe human rejected the previous draft of this episode. Their note: \"{reject_note}\"\n"
            f"Write a fresh version that addresses it.") if reject_note else ""
    system = f"You are the lead novelist of a {total}-episode serial. You write tight, specific, propulsive prose.\n\n{CRAFT_RULES}"
    user = f"""{context}{note}

Write EPISODE {n} now, delivering THIS EPISODE'S BEAT.
Output format exactly:
TITLE: <short evocative title>

<episode prose>"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def reviser(context: str, n: int, total: int, title: str, draft: str, issues: list[dict],
            findings: list[str]) -> list[dict]:
    notes = "\n".join(f"- [{i.get('severity')}/{i.get('type')}] {i.get('detail')} -> fix: {i.get('fix')}"
                      for i in issues) or "- (none from editor)"
    auto = "\n".join(f"- {f}" for f in findings) or "- (none)"
    system = f"You are the lead novelist of a {total}-episode serial, revising after editorial notes.\n\n{CRAFT_RULES}"
    user = f"""{context}

YOUR DRAFT OF EPISODE {n} ("{title}"):
{draft}

EDITOR NOTES:
{notes}
AUTOMATED CHECKS:
{auto}

Rewrite the whole episode fixing every note while keeping what works. Same output format:
TITLE: <title>

<episode prose>"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def critic(context: str, n: int, draft: str, findings: list[str]) -> list[dict]:
    auto = "\n".join(f"- {f}" for f in findings) or "- (none)"
    system = ("You are the continuity editor and story critic for a long serial. You catch contradictions, "
              "repeated beats, ignored directives and weak hooks. You only report problems you can point "
              "to in the text. JSON only.")
    user = f"""{context}

DRAFT OF EPISODE {n}:
<<<
{draft}
>>>

AUTOMATED CHECK FINDINGS (verify them; a dead character in a flashback/memory is fine):
{auto}

Evaluate:
1. continuity: contradictions with HARD FACTS, CHARACTER STATUS, RECENT EPISODES, timeline or world rules.
2. repetition: does it replay a scene/beat type already used in RECENT EPISODES or RELATED MEMORY?
3. directive: does it violate any ACTIVE DIRECTIVE?
4. beat: does it deliver THIS EPISODE'S BEAT? (beat_adherence 1-10)
5. hook: does the final paragraph end on a specific question/danger/reversal? (hook_score 1-10)
6. craft: generic prose, recap openings, telling instead of showing.
severity=high only for real contradictions, directive violations, missing beat, or no hook.

Return JSON: {{"beat_summary":"2 sentences: what happens in this draft","hook_score":int,
"beat_adherence":int,"issues":[{{"type":str,"severity":"high|medium|low","detail":"quote the text","fix":str}}]}}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ------------------------------------------------------------------ memory
def extractor(n: int, text: str, known_characters: list[str], known_threads: list[str]) -> list[dict]:
    system = ("You maintain the story bible for a long serial. Extract ONLY what this episode establishes. "
              "Reuse existing names exactly. JSON only.")
    user = f"""Known characters: {_j(known_characters)}
Known threads (open or planned): {_j(known_threads)}

EPISODE {n}:
<<<
{text}
>>>

Return JSON:
{{"summary":"80-120 words: events, revelations, relationship shifts, where it leaves off",
"hook":"the cliffhanger in one sentence",
"time_marker":"in-story time at the end (e.g. 'Day 3, 11pm')",
"facts":[{{"category":"world|timeline|character|location|object","subject":str,"statement":str,"importance":"high|normal"}}],
"characters":[{{"name":str,"is_new":bool,"role":str,"description":str,"status":"alive|dead|missing|unknown or null if unchanged","state_change":"what changed for them, or empty","relationships":{{"OtherName":"relationship now"}}}}],
"threads_opened":[{{"name":str,"description":str}}],
"threads_advanced":[str],"threads_resolved":[str]}}
Mark importance=high for facts later episodes must never contradict (deaths, identities, rules, injuries, dates).
Only list characters who appear or are materially affected."""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def segment_summary(start: int, end: int, summaries: list[str]) -> list[dict]:
    body = "\n".join(f"Ep {start + i}: {s}" for i, s in enumerate(summaries))
    return [{"role": "system", "content": "You compress serial fiction into load-bearing summaries."},
            {"role": "user", "content": f"Summarize episodes {start}-{end} in at most 180 words. Keep: plot "
             f"changes, revelations, deaths/injuries, relationship shifts, open questions. Drop scene detail.\n\n{body}"}]


def global_summary(previous: str, new_segment: str, start: int, end: int) -> list[dict]:
    return [{"role": "system", "content": "You maintain the 'story so far' for a long serial."},
            {"role": "user", "content": f"STORY SO FAR:\n{previous or '(beginning)'}\n\nNEW (episodes {start}-{end}):\n"
             f"{new_segment}\n\nRewrite the story-so-far in at most 450 words. Prioritise what future episodes "
             f"must remember: who is dead/alive, secrets revealed, promises made, unresolved mysteries."}]


# ------------------------------------------------------------------ feedback
def feedback(fb: str, n: int, upcoming: list[dict], characters: list[str], directives: list[str],
             from_review: bool) -> list[dict]:
    where = (f"while reviewing episode {n}" if from_review else f"between episodes (next to write: {n})")
    user = f"""A human editor gave this feedback {where}:
"{fb}"

Characters: {_j(characters)}
Active directives: {_j(directives)}
Upcoming planned beats: {_j(upcoming)}

Decide:
- scope: "episode_only" if it is purely about this single episode's prose (e.g. "the ending is flat"),
  otherwise "forward" (pacing, characters, plot, tone: anything future episodes must honour).
- directive (for forward scope): one standing instruction every future episode will see. Be concrete
  (e.g. "Maya and Theo may not kiss or confess feelings before episode 40; keep romance to glances").
  duration_episodes: null for permanent, or a number.
- beat_updates: rewrite ONLY the upcoming beats that must change so the plan obeys the feedback
  (e.g. schedule a character's death in the next 1-3 episodes and remove them from later beats).
- ack: one sentence to the human saying exactly what will change and from which episode.

Return JSON: {{"scope":str,"directive":{{"kind":"pacing|character|plot|style|tone","target":str,
"instruction":str,"duration_episodes":int|null}}|null,"beat_updates":[{{"episode":int,"beat":str,"hook":str,
"characters":[str],"threads":[str]}}],"ack":str}}"""
    return [{"role": "system", "content": "You are a showrunner turning editor notes into plan changes. JSON only."},
            {"role": "user", "content": user}]


def ripple(n: int, old_summary: str, new_summary: str, later: list[tuple[int, str]]) -> list[dict]:
    body = "\n".join(f"Ep {e}: {s}" for e, s in later)
    return [{"role": "system", "content": "You are a continuity editor. JSON only."},
            {"role": "user", "content": f"Episode {n} was rewritten by a human.\nOLD: {old_summary}\nNEW: {new_summary}\n\n"
             f"Later episodes:\n{body}\n\nList later episodes that now contradict the new episode {n}. "
             f'Return JSON: {{"conflicts":[{{"episode":int,"conflict":str,"suggested_fix":str}}],"ack":str}}'}]
