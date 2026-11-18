"""Etapa 4 data helpers.

Reuse the Etapa 3 loader without changing etapa3_models.py or db_access.py.
Call ``load_frames_at`` with an explicit SQLite path.
"""

from __future__ import annotations

import sys
import hashlib
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

import etapa3_models as e3
from db_access import find_project_root
from paths import data_dir

CURRENT_FREEZE = "gas_flare.sqlite"
SEP_EXPORT = "gas_flare_export_20260927.sqlite"
CURRENT_SHA256 = "b314283c8e711becd802d5162be38b1c47052e9603d8bbf81345916fc2bf35ba"
SEP_SHA256 = "155f53607aae0e92e66a588288ce309a8bce05678b77b67a0b56603713db3a6d"


def sqlite_file(name: str, root: Path | None = None) -> Path:
    path = data_dir(root) / name
    if not path.exists():
        raise FileNotFoundError(path)
    expected = {CURRENT_FREEZE: CURRENT_SHA256, SEP_EXPORT: SEP_SHA256}.get(name)
    if expected:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"SQLite SHA-256 mismatch: {name}: {actual}")
    return path.resolve()


def engine_for(sqlite_path: Path) -> Engine:
    return create_engine(
        f"sqlite:///file:{Path(sqlite_path).resolve().as_posix()}?mode=ro&uri=true",
        connect_args={"check_same_thread": False},
    )


def load_frames_at(sqlite_path: Path | str, root: Path | None = None) -> dict:
    """Load the Etapa 3 panels from a named SQLite file."""
    root = root or find_project_root()
    path = Path(sqlite_path).resolve()
    engine = engine_for(path)
    orig = e3.read_engine
    e3.read_engine = lambda project_root=None: engine  # noqa: ARG005
    try:
        frames = e3.load_frames(root)
    finally:
        e3.read_engine = orig
    frames["sqlite_path"] = str(path)
    return frames
