"""Pydantic contracts for every structured LLM output. Lenient by design (defaults, extra keys
ignored, nulls dropped) so small model slips don't crash a run; real violations trigger the
JSON-repair round in llm.chat_json and are logged."""
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator


class Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v is not None}
        return data


# ---------- planning ----------
class Act(Lenient):
    name: str
    start: int
    end: int
    goal: str = ""
    turning_point: str = ""


class CharacterPlan(Lenient):
    name: str
    role: str = ""
    description: str = ""
    arc: str = ""


class ThreadPlan(Lenient):
    name: str
    description: str = ""
    open_by: int | None = None
    resolve_by: int | None = None


class TurningPoint(Lenient):
    episode: int
    event: str


class SegmentPlan(Lenient):
    title: str = ""
    goal: str = ""


class PlanSkeleton(Lenient):
    title: str
    logline: str = ""
    genre: str = ""
    tone: str = ""
    pov: str = ""
    world_rules: list[str] = []
    themes: list[str] = []
    acts: list[Act] = []
    characters: list[CharacterPlan] = []
    threads: list[ThreadPlan] = []
    turning_points: list[TurningPoint] = []
    segments: list[SegmentPlan] = []
    ending: str = ""


class Beat(Lenient):
    episode: int
    beat: str
    hook: str = ""
    characters: list[str] = []
    threads: list[str] = []


class BeatsOut(Lenient):
    beats: list[Beat] = []


# ---------- critic ----------
class CriticIssue(Lenient):
    type: str = "craft"        # continuity | repetition | directive | beat | hook | craft
    severity: str = "medium"   # high | medium | low
    detail: str = ""
    fix: str = ""


class CriticOut(Lenient):
    beat_summary: str = ""
    hook_score: int = 0
    beat_adherence: int = 0
    issues: list[CriticIssue] = []


# ---------- memory extraction ----------
class FactOut(Lenient):
    category: str = "world"
    subject: str = ""
    statement: str
    importance: str = "normal"


class CharOut(Lenient):
    name: str
    is_new: bool = False
    role: str = ""
    description: str = ""
    status: str | None = None
    state_change: str = ""
    relationships: dict[str, str] = {}


class ThreadOut(Lenient):
    name: str
    description: str = ""


class ExtractionOut(Lenient):
    summary: str
    hook: str = ""
    time_marker: str = ""
    facts: list[FactOut] = []
    characters: list[CharOut] = []
    threads_opened: list[ThreadOut] = []
    threads_advanced: list[str] = []
    threads_resolved: list[str] = []


# ---------- feedback ----------
class DirectiveOut(Lenient):
    kind: str = "plot"
    target: str = ""
    instruction: str
    duration_episodes: int | None = None


class FeedbackOut(Lenient):
    scope: str = "forward"  # forward | episode_only
    directive: DirectiveOut | None = None
    beat_updates: list[Beat] = []
    ack: str = ""


class Conflict(Lenient):
    episode: int
    conflict: str
    suggested_fix: str = ""


class RippleOut(Lenient):
    conflicts: list[Conflict] = []
    ack: str = ""
