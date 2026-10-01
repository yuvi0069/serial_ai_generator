"""Thin, fully-traced wrapper around Groq chat completions.

Why not LangChain chat models? We want total control over retries, JSON repair, cost accounting
and logging per attempt; the graph (LangGraph) doesn't need LangChain models to work."""
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ..config import settings
from .tracing import Trace, log_run

logger = logging.getLogger("llm")
T = TypeVar("T", bound=BaseModel)

# USD per 1M tokens (input, output). Verify against console.groq.com/pricing; unknown models
# fall back to the 70B price so cost is over- rather than under-estimated.
PRICING: dict[str, tuple[float, float]] = {
    "llama-3.3-70b-versatile": (0.59, 0.79),  # retired on Groq; kept for old run_logs
    "llama-3.1-8b-instant": (0.05, 0.08),     # retired on Groq
    "openai/gpt-oss-120b": (0.15, 0.75),
    "openai/gpt-oss-20b": (0.10, 0.50),
    "moonshotai/kimi-k2-instruct": (1.00, 3.00),
}


class LLMError(RuntimeError):
    """Raised when a call fails after all retries (surfaced to the UI with a Retry button)."""


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int


def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Dollar cost of one call from the pricing table."""
    pin, pout = PRICING.get(model, (0.59, 0.79))
    return (prompt_tokens * pin + completion_tokens * pout) / 1_000_000


_client = None


def _groq():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=settings.groq_api_key, timeout=90, max_retries=0)
    return _client


def chat(messages: list[dict], *, model: str, trace: Trace, temperature: float = 0.7,
         max_tokens: int = 2048, json_mode: bool = False) -> LLMResult:
    """One chat completion with bounded retries (rate limits, timeouts, 5xx, empty output,
    Groq json_validate_failed). Each attempt is logged with tokens/cost/latency/error."""
    if settings.offline_mode:
        from .fake_llm import fake_chat
        return fake_chat(messages, model=model, trace=trace, json_mode=json_mode)

    import groq
    retryable = (groq.RateLimitError, groq.APIConnectionError, groq.APITimeoutError,
                 groq.InternalServerError)
    last_err: Exception | None = None
    for attempt in range(1, settings.llm_max_attempts + 1):
        t0 = time.perf_counter()
        try:
            kwargs = dict(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            if model.startswith("openai/gpt-oss"):  # passed raw: the pinned SDK predates this param
                kwargs["extra_body"] = {"reasoning_effort": settings.reasoning_effort}
            resp = _groq().chat.completions.create(**kwargs)
            latency = int((time.perf_counter() - t0) * 1000)
            pt = resp.usage.prompt_tokens if resp.usage else 0
            ct = resp.usage.completion_tokens if resp.usage else 0
            text = (resp.choices[0].message.content or "").strip()
            finish = resp.choices[0].finish_reason
            cost = cost_of(model, pt, ct)
            if not text:
                log_run(trace, model=model, attempt=attempt, prompt_tokens=pt, completion_tokens=ct,
                        cost_usd=cost, latency_ms=latency, status="error", error=f"empty completion (finish={finish})")
                last_err = LLMError("empty completion")
                if finish == "length":  # reasoning used the whole budget; give the answer room
                    max_tokens = int(max_tokens * 1.5)
                continue
            log_run(trace, model=model, attempt=attempt, prompt_tokens=pt, completion_tokens=ct,
                    cost_usd=cost, latency_ms=latency, decision=f"finish={finish}")
            return LLMResult(text, model, pt, ct, cost, latency)
        except retryable as e:
            last_err = e
            latency = int((time.perf_counter() - t0) * 1000)
            log_run(trace, model=model, attempt=attempt, latency_ms=latency, status="error",
                    error=f"{type(e).__name__}: {str(e)[:500]}")
            if isinstance(e, groq.RateLimitError) and "request too large" in str(e).lower():
                raise LLMError(f"{trace.node}: this request is larger than {model}'s per-minute limit on your Groq "
                               f"plan, so waiting won't help. Point this role at another model in .env. ({e})") from e
            wait = _retry_after(e) or min(30, 2 ** attempt + random.random())
            if wait > settings.max_rate_limit_wait_s:
                raise LLMError(f"{trace.node}: Groq rate limit for {model} resets in about {wait / 60:.0f} min "
                               f"(likely the free tier's daily quota). Press Retry after that. ({e})") from e
            # logged as an event so per-node call latency stays clean, but the per-episode time
            # (and so the remaining-time projection) includes time spent waiting on rate limits
            log_run(trace, model=model, attempt=attempt, latency_ms=int(wait * 1000), status="event",
                    decision=f"backoff {wait:.1f}s before attempt {attempt + 1}")
            time.sleep(wait)
        except groq.BadRequestError as e:  # json_validate_failed, context too long, bad model id
            last_err = e
            log_run(trace, model=model, attempt=attempt, status="error",
                    error=f"BadRequest: {str(e)[:500]}")
            if not (json_mode and "json" in str(e).lower()):
                break
            temperature = max(0.2, temperature - 0.3)
    raise LLMError(f"{trace.node}: LLM call failed after retries: {last_err}")


def _retry_after(e: Exception) -> float | None:
    """Seconds to wait: the retry-after header, else Groq's 'Please try again in 1m7.5s' hint."""
    try:
        return float(e.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except Exception:
        pass
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:([\d.]+)s)?(?:([\d.]+)ms)?", str(e))
    if not m or not any(m.groups()):
        return None
    h, mi, s, ms = (float(x) if x else 0.0 for x in m.groups())
    return h * 3600 + mi * 60 + s + ms / 1000 + 0.5


def parse_json(text: str) -> dict:
    """Tolerant JSON extraction: strips ``` fences and takes the outermost {...} block."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in output")
        return json.loads(text[start:end + 1])


def chat_json(messages: list[dict], schema: type[T], *, model: str, trace: Trace,
              temperature: float = 0.3, max_tokens: int = 2048) -> tuple[T, float]:
    """JSON-mode call validated against a Pydantic schema. One self-repair round if the output
    doesn't parse/validate. Returns (validated object, total cost)."""
    res = chat(messages, model=model, trace=trace, temperature=temperature,
               max_tokens=max_tokens, json_mode=True)
    cost = res.cost_usd
    try:
        return schema.model_validate(parse_json(res.text)), cost
    except (ValueError, ValidationError) as e:
        log_run(trace, model=model, status="error", error=f"schema/parse: {str(e)[:500]}",
                decision="attempting JSON repair")
        repair = messages + [
            {"role": "assistant", "content": res.text[:6000]},
            {"role": "user", "content": f"That output was invalid ({str(e)[:300]}). "
                                        "Return ONLY a corrected JSON object matching the schema."},
        ]
        res2 = chat(repair, model=model, trace=trace, temperature=0.1,
                    max_tokens=max_tokens, json_mode=True)
        cost += res2.cost_usd
        try:
            return schema.model_validate(parse_json(res2.text)), cost
        except (ValueError, ValidationError) as e2:
            raise LLMError(f"{trace.node}: invalid JSON after repair: {e2}") from e2
