"""Central configuration. Every tunable (models, budgets, thresholds) lives here so behaviour
can be changed through environment variables without touching code."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # infrastructure
    database_url: str = "sqlite:///./local.db"
    groq_api_key: str = ""
    jina_api_key: str = ""
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "story_memory"
    # Postgres connections per process. Supabase's session pooler caps ALL clients (on the free
    # plan: 15), and a deploy briefly runs old + new instances, so keep one process well under half.
    db_pool_size: int = 3
    db_max_overflow: int = 2
    checkpoint_pool_size: int = 2

    # auth
    jwt_secret: str = "change-me"
    jwt_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:5173"

    # models (role -> Groq model id). Tuned for Groq's free tier, where every model has its own
    # 8k tokens/min and 1k requests/day: writing runs on 120b, checking/extraction on 20b, so the
    # two halves of an episode draw on separate quotas. (qwen/qwen3.8-27b is rejected on the free
    # tier for long outputs: a 1k output-tokens/min cap. Groq retired the llama-3.x defaults.)
    planner_model: str = "openai/gpt-oss-120b"
    writer_model: str = "openai/gpt-oss-120b"
    critic_model: str = "openai/gpt-oss-20b"
    extractor_model: str = "openai/gpt-oss-20b"
    utility_model: str = "openai/gpt-oss-20b"
    # gpt-oss models reason before answering and those tokens count against max_tokens;
    # "low" keeps them from exhausting the budget and returning empty output.
    reasoning_effort: str = "low"
    embedding_model: str = "jina-embeddings-v3"
    embedding_dim: int = 1024

    # story shape
    min_words: int = 400
    max_words: int = 700
    segment_size: int = 10          # episodes per rolling "chapter" summary
    beats_per_plan_chunk: int = 20  # episodes expanded per planner call

    # bounds / stopping rules
    max_revisions: int = 2
    max_episode_cost_usd: float = 0.05
    max_story_cost_usd: float = 5.0
    max_batch: int = 50
    llm_max_attempts: int = 6
    max_rate_limit_wait_s: int = 90   # longer waits (daily quota) fail fast instead of blocking

    # quality gates
    hook_threshold: int = 7
    beat_threshold: int = 6
    repetition_threshold: float = 0.90   # cosine sim of beat summaries
    ngram_overlap_threshold: float = 0.06

    offline_mode: bool = False

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
