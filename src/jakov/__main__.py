"""Entry point: `python -m jakov` (applies DB migrations first)."""

from __future__ import annotations

import asyncio
import sys

from pydantic import ValidationError

from jakov.config import PROJECT_ROOT, get_settings
from jakov.logging_setup import get_logger, setup_logging


def upgrade_database(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def main() -> None:
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"Configuration error (check your .env):\n{exc}", file=sys.stderr)
        raise SystemExit(2) from None
    setup_logging(settings.var_dir / "logs", settings.log_level, settings.secret_values(),
                  settings.log_json)
    log = get_logger("jakov")
    upgrade_database(settings.database_url)
    log.info("database_ready")

    from jakov.app import run

    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        log.info("interrupted")


if __name__ == "__main__":
    main()
