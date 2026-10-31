"""Create the database (if missing) and apply the Alembic migrations.

    cd server
    python -m scripts.init_db            # uses DATABASE_URL or DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME from .env

Safe to re-run: the database is created with IF NOT EXISTS and `alembic upgrade head` is idempotent.
"""
from __future__ import annotations

import re
import sys

import pymysql
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import make_url

from app.core.config import SERVER_DIR, get_settings
from app.db import init_engine, mysql_connect_args


def create_database() -> str:
    url = make_url(get_settings().resolved_database_url)
    if not url.drivername.startswith("mysql"):
        raise SystemExit(f"init_db only manages MySQL-compatible servers (got '{url.drivername}'). SQLite files are created automatically.")
    name = url.database
    if not name or not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise SystemExit(f"Refusing to create a database with an unsafe name: {name!r}")
    args = mysql_connect_args(15)
    conn = pymysql.connect(host=url.host, port=url.port or 3306, user=url.username, password=url.password, **args)
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
    finally:
        conn.close()
    return name


def main() -> None:
    name = create_database()
    print(f"Database `{name}` is ready.")
    engine = init_engine()
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(cfg, "head")
    tables = sorted(inspect(engine).get_table_names())
    print(f"Migrations applied. {len(tables)} tables in `{name}`:")
    for t in tables:
        print(f"  - {t}")


if __name__ == "__main__":
    sys.exit(main())
