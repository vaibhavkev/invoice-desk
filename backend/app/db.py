"""SQLite engine and session helpers (SQLModel)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from . import models  # noqa: F401  (register tables)

_engine: Optional[Engine] = None


def make_engine(db_path: Path) -> Engine:
    url = "sqlite://" if str(db_path) == ":memory:" else f"sqlite:///{Path(db_path).as_posix()}"
    kwargs = {"connect_args": {"check_same_thread": False}}
    if str(db_path) == ":memory:":
        from sqlalchemy.pool import StaticPool
        kwargs["poolclass"] = StaticPool
    eng = create_engine(url, **kwargs)

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return eng


def init_engine(db_path: Path) -> Engine:
    global _engine
    if db_path != Path(":memory:") and str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    _engine = make_engine(db_path)
    SQLModel.metadata.create_all(_engine)
    _add_missing_columns(_engine)
    return _engine


def _add_missing_columns(engine: Engine) -> None:
    """create_all never alters an existing table; add nullable columns introduced after a DB was created."""
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            have = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            for col in table.columns:
                if have and col.name not in have and col.nullable:
                    conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '
                                         f'{col.type.compile(engine.dialect)}')


def get_engine() -> Engine:
    if _engine is None:
        from .config import settings
        init_engine(settings.db_path)
    assert _engine is not None
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s
