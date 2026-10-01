"""Graph singleton with a durable checkpointer. In Postgres mode every superstep is saved to
Supabase (thread_id = story id), which is what makes 'stop at 12, resume next week' work."""
import threading

from ..config import settings
from ..db import IS_SQLITE, raw_pg_url
from .builder import build_graph

_graph = None
_pool = None
_lock = threading.Lock()


def get_graph():
    """Build once: PostgresSaver on a psycopg pool (autocommit, no prepared statements for the
    Supabase pooler) or an in-memory saver for SQLite/offline tests."""
    global _graph, _pool
    with _lock:
        if _graph is not None:
            return _graph
        if IS_SQLITE:
            from langgraph.checkpoint.memory import MemorySaver
            cp = MemorySaver()
        else:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(conninfo=raw_pg_url(settings.database_url), max_size=5, open=True,
                                   kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row})
            cp = PostgresSaver(_pool)
            cp.setup()
        _graph = build_graph(cp)
        return _graph


def delete_thread(thread_id: str) -> None:
    """Drop a story's checkpoints when the story is deleted."""
    g = get_graph()
    try:
        g.checkpointer.delete_thread(thread_id)
    except Exception:
        pass
