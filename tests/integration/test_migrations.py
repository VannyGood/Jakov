"""Alembic migrations build exactly the schema the models describe."""

from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine

from jakov.__main__ import upgrade_database
from jakov.config import PROJECT_ROOT
from jakov.db.base import Base


def test_upgrade_head_matches_models(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    upgrade_database(f"sqlite+aiosqlite:///{db}")
    engine = create_engine(f"sqlite:///{db}")
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}),
                                Base.metadata)
    engine.dispose()
    assert diff == []


def test_downgrade_to_base_and_back(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'd.db'}"
    upgrade_database(url)
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_every_table_has_owner_id() -> None:
    missing = [t.name for t in Base.metadata.sorted_tables if "owner_id" not in t.c]
    assert missing == []
