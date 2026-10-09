"""Typed project directories.

Frozen SQLite stays in data/. Static assets (logo, drawio) stay in images/.
Generated EDA charts go to figures/eda/. Forecast overlays go to
figures/forecasts/. Metrics and forecast JSON go to results/. Run stdout
goes to logs/.
"""

from __future__ import annotations

from pathlib import Path

from db_access import find_project_root


def data_dir(root: Path | None = None) -> Path:
    return (root or find_project_root()) / "data"


def images_dir(root: Path | None = None) -> Path:
    """Static assets. Do not write generated charts or JSON here."""
    return (root or find_project_root()) / "images"


def figures_eda_dir(root: Path | None = None) -> Path:
    return (root or find_project_root()) / "figures" / "eda"


def figures_forecasts_dir(root: Path | None = None) -> Path:
    return (root or find_project_root()) / "figures" / "forecasts"


def results_dir(root: Path | None = None) -> Path:
    return (root or find_project_root()) / "results"


def logs_dir(root: Path | None = None) -> Path:
    return (root or find_project_root()) / "logs"


def metrics_path(root: Path | None = None) -> Path:
    return results_dir(root) / "etapa3_metrics.json"


def forecasts_path(root: Path | None = None) -> Path:
    return results_dir(root) / "etapa3_forecasts.json"


def ensure_output_dirs(root: Path | None = None) -> Path:
    r = root or find_project_root()
    for d in (
        images_dir(r),
        figures_eda_dir(r),
        figures_forecasts_dir(r),
        results_dir(r),
        logs_dir(r),
    ):
        d.mkdir(parents=True, exist_ok=True)
    return r
