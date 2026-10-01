"""Cheap deterministic checks that run before (and are fed to) the LLM critic."""
import re

from ..config import settings
from ..graph.prompts import BANNED_PHRASES

WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-]*")


def word_count(text: str) -> int:
    return len(WORD.findall(text))


def ngrams(text: str, n: int = 6) -> set[tuple[str, ...]]:
    toks = [t.lower() for t in WORD.findall(text)]
    return {tuple(toks[i:i + n]) for i in range(len(toks) - n + 1)}


def ngram_overlap(draft: str, previous: list[str], n: int = 6) -> float:
    """Share of the draft's 6-grams already used in recent episodes (copy-paste / stock phrasing)."""
    d = ngrams(draft, n)
    if not d or not previous:
        return 0.0
    prev = set().union(*(ngrams(p, n) for p in previous))
    return len(d & prev) / len(d)


def banned_found(text: str) -> list[str]:
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]


def dead_mentions(text: str, dead: list[str]) -> list[str]:
    hits = []
    for name in dead:
        for tok in {name, name.split()[0]}:
            if len(tok) > 2 and re.search(rf"\b{re.escape(tok)}\b", text):
                hits.append(name)
                break
    return hits


def parse_episode(raw: str) -> tuple[str, str]:
    """Split 'TITLE: x\\n\\nbody' model output into (title, body); tolerant of markdown."""
    raw = raw.strip()
    m = re.match(r"^\**\s*TITLE\s*:\s*\**\s*(.+?)\**\s*\n", raw, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().strip('"*#'), raw[m.end():].strip()
    first, _, rest = raw.partition("\n")
    if len(first) < 80 and rest:
        return first.strip("#* \""), rest.strip()
    return "Untitled", raw


def run_checks(draft: str, previous_texts: list[str], dead_names: list[str]) -> dict:
    """Aggregate deterministic findings. `hard_fail` means the draft must be revised."""
    wc = word_count(draft)
    overlap = ngram_overlap(draft, previous_texts)
    banned = banned_found(draft)
    dead = dead_mentions(draft, dead_names)
    findings = []
    lo, hi = settings.min_words, settings.max_words
    if wc < lo - 20 or wc > hi + 20:
        findings.append(f"word count {wc} is outside {lo}-{hi}")
    if overlap > settings.ngram_overlap_threshold:
        findings.append(f"{overlap:.0%} of 6-word phrases repeat recent episodes; rephrase")
    if banned:
        findings.append(f"banned stock phrases used: {', '.join(banned)}")
    if dead:
        findings.append(f"dead characters mentioned: {', '.join(dead)} (only OK as memory/flashback/body)")
    hard = (wc < lo - 20 or wc > hi + 20) or overlap > settings.ngram_overlap_threshold
    return {"word_count": wc, "ngram_overlap": round(overlap, 3), "banned": banned,
            "dead_mentions": dead, "findings": findings, "hard_fail": hard}
