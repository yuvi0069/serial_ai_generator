"""Jina embeddings (jina-embeddings-v3, 1024-d, task-aware: passage vs query)."""
import hashlib
import math
import re
import time

import httpx

from ..config import settings

JINA_URL = "https://api.jina.ai/v1/embeddings"


def _hash_vec(text: str, dim: int | None = None) -> list[float]:
    """Offline stand-in: hashed bag-of-words vector. Similar texts -> similar vectors."""
    dim = dim or settings.embedding_dim
    v = [0.0] * dim
    for tok in re.findall(r"[a-z0-9']+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dim] += 1.0 if (h >> 8) & 1 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed(texts: list[str], task: str = "retrieval.passage") -> list[list[float]]:
    """Embed a batch of texts. task='retrieval.query' for search queries, 'retrieval.passage'
    for stored memory, 'text-matching' for symmetric similarity (repetition checks)."""
    if not texts:
        return []
    if settings.offline_mode:
        return [_hash_vec(t) for t in texts]
    if not settings.jina_api_key:
        raise RuntimeError("JINA_API_KEY is not set")
    out: list[list[float]] = []
    for i in range(0, len(texts), 64):
        batch = [t[:8000] for t in texts[i:i + 64]]
        out.extend(_post(batch, task))
    return out


def _post(batch: list[str], task: str) -> list[list[float]]:
    last = None
    for attempt in range(3):
        try:
            r = httpx.post(JINA_URL, timeout=30, headers={"Authorization": f"Bearer {settings.jina_api_key}"},
                           json={"model": settings.embedding_model, "task": task,
                                 "dimensions": settings.embedding_dim, "input": batch})
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except (httpx.HTTPError, KeyError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Jina embedding failed: {last}")


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)
