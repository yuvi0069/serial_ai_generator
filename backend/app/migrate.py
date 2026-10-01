"""Schema migrations (Alembic). The app's tables are versioned in backend/alembic/versions;
LangGraph's checkpoint tables are managed separately by PostgresSaver.setup()."""
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from .db import engine

log = logging.getLogger("migrate")
INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def alembic_config() -> Config:
    cfg = Config(str(INI))
    cfg.set_main_option("script_location", str(INI.parent / "alembic"))
    cfg.attributes["configure_logger"] = False  # keep the app's logging config
    return cfg


def upgrade_db() -> None:
    """Bring the database to the latest revision. A database created before Alembic was added
    (tables present, no alembic_version) is stamped at the initial revision first, then upgraded."""
    cfg = alembic_config()
    tables = set(inspect(engine).get_table_names())
    if "alembic_version" not in tables and "stories" in tables:
        log.info("existing schema without alembic_version; stamping initial revision")
        command.stamp(cfg, "f7b36b8a6b84")
    command.upgrade(cfg, "head")
