"""Configuration loader for OLGA Automation."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


def _find_project_root() -> Path:
    """Walk up from this file to find the directory containing pyproject.toml."""
    current = Path(__file__).resolve().parent
    for _ in range(10):  # safety limit
        if (current / "pyproject.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # Fallback: two levels up from src/olga_automation/config.py
    return Path(__file__).resolve().parent.parent.parent


@dataclass
class OlgaConfig:
    """Configuration for OLGA Automation."""

    olga_home: Path | None = None
    opi_executable: str = "opi"
    base_models_dir: Path = field(default_factory=lambda: _find_project_root() / "base_models")
    runs_dir: Path = field(default_factory=lambda: _find_project_root() / "runs")
    max_parallel: int = 1
    default_timeout: int | None = None


def load_config(config_path: Path | None = None) -> OlgaConfig:
    """Load configuration from a JSON file or return sensible defaults.

    Parameters
    ----------
    config_path : Path | None
        Path to a JSON config file. If None, defaults are used.

    Returns
    -------
    OlgaConfig
        Populated configuration object.
    """
    project_root = _find_project_root()

    if config_path is not None:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return OlgaConfig(
            olga_home=Path(data["olga_home"]) if data.get("olga_home") else None,
            opi_executable=data.get("opi_executable", "opi"),
            base_models_dir=Path(data["base_models_dir"]) if data.get("base_models_dir") else project_root / "base_models",
            runs_dir=Path(data["runs_dir"]) if data.get("runs_dir") else project_root / "runs",
            max_parallel=data.get("max_parallel", 1),
            default_timeout=data.get("default_timeout"),
        )

    # Defaults
    olga_home_env = os.environ.get("OLGA_HOME")
    return OlgaConfig(
        olga_home=Path(olga_home_env) if olga_home_env else None,
        opi_executable="opi",
        base_models_dir=project_root / "base_models",
        runs_dir=project_root / "runs",
        max_parallel=1,
        default_timeout=None,
    )
