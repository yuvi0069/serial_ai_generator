"""Semantic long-term memory in Qdrant. One collection, every point tagged with story_id, kind
(summary | beat | fact) and episode, so retrieval is always 'this story, before episode N'.
Retrieval failures degrade gracefully (logged, empty result): Postgres memory layers still work."""
import logging
import uuid
from typing import Any

from ..config import settings
from .embeddings import cosine, embed

logger = logging.getLogger("vectors")


def point_id(story_id: str, kind: str, episode: int, idx: int) -> str:
    """Deterministic id so re-committing an episode overwrites instead of duplicating."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{story_id}:{kind}:{episode}:{idx}"))


class _MemoryBackend:
    """In-process backend for OFFLINE_MODE / tests."""

    def __init__(self):
        self.points: dict[str, dict] = {}

    def ensure(self):
        pass

    def upsert(self, pts):
        for p in pts:
            self.points[p["id"]] = p

    def search(self, vector, story_id, kinds, before, k):
        hits = []
        for p in self.points.values():
            pl = p["payload"]
            if pl["story_id"] != story_id or pl["kind"] not in kinds or (before and pl["episode"] >= before):
                continue
            hits.append({**pl, "score": cosine(vector, p["vector"])})
        return sorted(hits, key=lambda h: -h["score"])[:k]

    def delete(self, story_id, episode):
        for pid in [pid for pid, p in self.points.items() if p["payload"]["story_id"] == story_id
                    and (episode is None or p["payload"]["episode"] == episode)]:
            del self.points[pid]


class _QdrantBackend:
    def __init__(self):
        from qdrant_client import QdrantClient
        self.c = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=30)
        self.col = settings.qdrant_collection

    def ensure(self):
        from qdrant_client import models as m
        if not self.c.collection_exists(self.col):
            self.c.create_collection(self.col, vectors_config=m.VectorParams(
                size=settings.embedding_dim, distance=m.Distance.COSINE))
        # payload indexes are required for filtered search on Qdrant Cloud (strict mode)
        for field, schema in [("story_id", m.PayloadSchemaType.KEYWORD),
                              ("kind", m.PayloadSchemaType.KEYWORD),
                              ("episode", m.PayloadSchemaType.INTEGER)]:
            try:
                self.c.create_payload_index(self.col, field_name=field, field_schema=schema)
            except Exception:
                pass  # already exists

    def _filter(self, story_id, kinds=None, before=None, episode=None):
        from qdrant_client import models as m
        must: list[Any] = [m.FieldCondition(key="story_id", match=m.MatchValue(value=story_id))]
        if kinds:
            must.append(m.FieldCondition(key="kind", match=m.MatchAny(any=kinds)))
        if before:
            must.append(m.FieldCondition(key="episode", range=m.Range(lt=before)))
        if episode is not None:
            must.append(m.FieldCondition(key="episode", match=m.MatchValue(value=episode)))
        return m.Filter(must=must)

    def upsert(self, pts):
        from qdrant_client import models as m
        self.c.upsert(self.col, points=[m.PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
                                        for p in pts])

    def search(self, vector, story_id, kinds, before, k):
        res = self.c.query_points(self.col, query=vector, limit=k, with_payload=True,
                                  query_filter=self._filter(story_id, kinds, before))
        return [{**(p.payload or {}), "score": p.score} for p in res.points]

    def delete(self, story_id, episode):
        from qdrant_client import models as m
        self.c.delete(self.col, points_selector=m.FilterSelector(
            filter=self._filter(story_id, episode=episode)))


_backend = None
TASK_FOR_KIND = {"beat": "text-matching"}


def backend():
    global _backend
    if _backend is None:
        _backend = _MemoryBackend() if settings.offline_mode or not settings.qdrant_url else _QdrantBackend()
    return _backend


def ensure_collection() -> None:
    """Create the collection and payload indexes if missing (called at startup)."""
    backend().ensure()


def upsert_items(story_id: str, episode: int, items: list[dict]) -> None:
    """items: [{kind, text, meta?}] -> embedded and stored. Replaces the episode's old points."""
    if not items:
        return
    # beats are compared symmetrically (repetition check) -> text-matching; the rest are passages
    vectors: list = [None] * len(items)
    for task in {TASK_FOR_KIND.get(i["kind"], "retrieval.passage") for i in items}:
        idxs = [n for n, i in enumerate(items) if TASK_FOR_KIND.get(i["kind"], "retrieval.passage") == task]
        for n, vec in zip(idxs, embed([items[n]["text"] for n in idxs], task=task)):
            vectors[n] = vec
    counters: dict[str, int] = {}
    pts = []
    for item, vec in zip(items, vectors):
        idx = counters.get(item["kind"], 0)
        counters[item["kind"]] = idx + 1
        pts.append({"id": point_id(story_id, item["kind"], episode, idx), "vector": vec,
                    "payload": {"story_id": story_id, "kind": item["kind"], "episode": episode,
                                "text": item["text"], **item.get("meta", {})}})
    backend().upsert(pts)


def search(story_id: str, query: str, kinds: list[str], before_episode: int | None, k: int = 10,
           task: str = "retrieval.query") -> list[dict]:
    """Top-k memories of the given kinds strictly before `before_episode`."""
    try:
        vec = embed([query], task=task)[0]
        return backend().search(vec, story_id, kinds, before_episode, k)
    except Exception as e:
        logger.warning("vector search degraded: %s", e)
        return []


def delete_episode(story_id: str, episode: int | None = None) -> None:
    """Remove one episode's points (retro edit / re-commit) or all of a story's (episode=None)."""
    try:
        backend().delete(story_id, episode)
    except Exception as e:
        logger.warning("vector delete failed: %s", e)
