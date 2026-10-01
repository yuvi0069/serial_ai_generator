"""HTTP request/response models."""
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt hard limit


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class StoryCreate(BaseModel):
    premise: str = Field(min_length=10, max_length=1500)
    target_episodes: int = Field(default=200, ge=5, le=500)


class StoryRename(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class StoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    premise: str
    status: str
    current_episode: int
    target_episodes: int
    total_cost_usd: float
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    kind: str
    content: str
    meta: dict[str, Any] = {}
    created_at: datetime


class ActIn(BaseModel):
    """Answer to whatever the graph is currently paused on (plan_review | episode_review | continue)."""
    action: Literal["approve", "edit", "feedback", "reject", "continue"]
    feedback: str | None = Field(default=None, max_length=2000)
    text: str | None = None          # edited episode text
    title: str | None = None         # edited episode title
    plan: dict[str, Any] | None = None  # edited plan
    count: int | None = Field(default=None, ge=1, le=50)
    auto_approve: bool = False


class EpisodeEditIn(BaseModel):
    content: str = Field(min_length=50)
    title: str | None = None
