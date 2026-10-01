"""Relational schema. The story's *durable memory* lives here (not in the prompt, not in the
LangGraph checkpoint): episodes, characters + character events, facts, threads, directives,
layered summaries, chat messages, and the per-call trace log."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, Uuid)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


def story_fk():
    return mapped_column(Uuid, ForeignKey("stories.id", ondelete="CASCADE"), index=True)


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Story(Base):
    """One story == one 'chat' in the sidebar == one LangGraph thread (thread_id = story.id)."""
    __tablename__ = "stories"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    title_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # True once the user renames
    premise: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="planning")
    target_episodes: Mapped[int] = mapped_column(Integer, default=200)
    current_episode: Mapped[int] = mapped_column(Integer, default=1)  # next episode to write
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Message(Base):
    """Chat transcript shown in the UI (premise, decisions, episodes, system events)."""
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    story_id: Mapped[uuid.UUID] = story_fk()
    role: Mapped[str] = mapped_column(String(16))      # user | assistant | system
    kind: Mapped[str] = mapped_column(String(24))      # text | plan | episode | feedback | event | error | ripple
    content: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ArcPlan(Base):
    __tablename__ = "arc_plans"
    story_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True)
    plan: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("story_id", "number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    beat_summary: Mapped[str] = mapped_column(Text, default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="approved")
    revisions: Mapped[int] = mapped_column(Integer, default=0)
    human_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    critic_report: Mapped[dict] = mapped_column(JSON, default=dict)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Character(Base):
    """Static card + cached current state. Current state is DERIVED from CharacterEvent rows."""
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("story_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(120), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    arc: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(16), default="plan")  # plan | episode
    status: Mapped[str] = mapped_column(String(16), default="alive")
    current_state: Mapped[str] = mapped_column(Text, default="")
    relationships: Mapped[dict] = mapped_column(JSON, default=dict)
    first_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_episode: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CharacterEvent(Base):
    """Event-sourced character history: lets us rebuild state after a retroactive edit."""
    __tablename__ = "character_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    character_name: Mapped[str] = mapped_column(String(120), index=True)
    episode: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    state_change: Mapped[str] = mapped_column(Text, default="")
    relationships: Mapped[dict] = mapped_column(JSON, default=dict)


class Fact(Base):
    __tablename__ = "facts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    episode: Mapped[int] = mapped_column(Integer, index=True)
    category: Mapped[str] = mapped_column(String(32), default="world")
    subject: Mapped[str] = mapped_column(String(200), default="")
    statement: Mapped[str] = mapped_column(Text)
    importance: Mapped[str] = mapped_column(String(16), default="normal")


class Thread(Base):
    __tablename__ = "threads"
    __table_args__ = (UniqueConstraint("story_id", "name"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="planned")  # planned | open | resolved
    origin: Mapped[str] = mapped_column(String(16), default="plan")
    open_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolve_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    opened_ep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resolved_ep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_touched_ep: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Directive(Base):
    """Human feedback compiled into a standing instruction that every future episode sees."""
    __tablename__ = "directives"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    instruction: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(24), default="plot")  # pacing | character | plot | style | tone
    target: Mapped[str] = mapped_column(String(200), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_ep: Mapped[int] = mapped_column(Integer, default=1)
    expires_ep: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_feedback: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Summary(Base):
    __tablename__ = "summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID] = story_fk()
    level: Mapped[str] = mapped_column(String(16))  # segment | global
    start_ep: Mapped[int] = mapped_column(Integer)
    end_ep: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RunLog(Base):
    """One row per LLM attempt or graph decision: tokens, cost, latency, retries, errors."""
    __tablename__ = "run_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    story_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | event
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


CHILD_TABLES = [Message, ArcPlan, Episode, Character, CharacterEvent, Fact, Thread, Directive, Summary]
