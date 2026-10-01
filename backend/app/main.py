"""FastAPI entrypoint."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from .config import settings
from .db import session_scope
from .graph.checkpointer import get_graph
from .migrate import upgrade_db
from .models import Story
from .routers import auth, stories
from .services import vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: run migrations, create checkpointer tables, Qdrant collection; recover runs cut off by a restart."""
    upgrade_db()
    get_graph()
    try:
        vector_store.ensure_collection()
    except Exception as e:
        log.warning("Qdrant unavailable at startup (%s); retrieval will degrade gracefully", e)
    with session_scope() as s:
        s.execute(update(Story).where(Story.status == "running").values(
            status="error", last_error="The server restarted during a run. Press Retry to resume from the last checkpoint."))
    yield


app = FastAPI(title="Serial Story Writer", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(stories.router)


@app.get("/health")
def health():
    return {"ok": True, "offline_mode": settings.offline_mode}
