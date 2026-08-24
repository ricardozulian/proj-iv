"""Read-only access to the frozen local SQLite dataset.

Notebooks must not depend on Gas Flare Postgres, secrets, or pipelines.
Single file: ``data/gas_flare.sqlite``.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

DEFAULT_DB_NAME = "gas_flare.sqlite"


def find_project_root() -> Path:
    """Locate proj_IV root from notebook cwd (repo root or notebooks/)."""
    cwd = Path.cwd().resolve()
    for root in (cwd, cwd.parent):
        if (root / "data").is_dir() and (root / "src").is_dir():
            return root
        if (root / "data" / DEFAULT_DB_NAME).exists():
            return root
    raise FileNotFoundError(
        "Could not locate proj_IV root (expected data/ and src/). "
        "Run notebooks from proj_IV/ or proj_IV/notebooks/."
    )


def sqlite_path(project_root: Path | None = None) -> Path:
    """Absolute path to the frozen SQLite file under data/."""
    root = project_root or find_project_root()
    path = root / "data" / DEFAULT_DB_NAME
    if not path.exists():
        raise FileNotFoundError(f"Frozen SQLite not found: {path}")
    return path.resolve()


def resolve_database_url(project_root: Path | None = None) -> str:
    """SQLAlchemy URL for the frozen SQLite dataset (no env / secrets)."""
    return f"sqlite:///{sqlite_path(project_root)}"


def read_engine(project_root: Path | None = None) -> Engine:
    """SQLAlchemy engine for read-only notebook queries against frozen SQLite."""
    return create_engine(
        resolve_database_url(project_root),
        connect_args={"check_same_thread": False},
    )


def table_exists(engine: Engine, table_name: str) -> bool:
    from sqlalchemy import inspect

    return table_name in inspect(engine).get_table_names()
