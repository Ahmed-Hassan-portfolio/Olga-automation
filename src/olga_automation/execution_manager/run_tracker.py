"""Persist run metadata to JSON (run_metadata.json per run)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from olga_automation.execution_manager.models import RunStatus

logger = logging.getLogger(__name__)

METADATA_FILENAME = "run_metadata.json"


def save_run(status: RunStatus) -> None:
    """Write run metadata to run_metadata.json inside the run's output directory.

    Creates ``output_dir`` if it does not exist.  Overwrites any existing
    metadata file (useful for status updates during a run).

    Parameters
    ----------
    status : RunStatus
        The run status to persist.
    """
    status.output_dir.mkdir(parents=True, exist_ok=True)
    data = status.to_dict()
    meta_path = status.output_dir / METADATA_FILENAME
    meta_path.write_text(
        json.dumps(data, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def get_run_status(run_id: str, runs_dir: Path) -> RunStatus | None:
    """Find a run by its ID by scanning all subdirectories of *runs_dir*.

    Parameters
    ----------
    run_id : str
        The unique run identifier to search for.
    runs_dir : Path
        Parent directory containing per-run subdirectories.

    Returns
    -------
    RunStatus | None
        The matching run status, or ``None`` if not found.
    """
    if not runs_dir.is_dir():
        return None
    for subdir in runs_dir.iterdir():
        if not subdir.is_dir():
            continue
        meta_path = subdir / METADATA_FILENAME
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            if data.get("run_id") == run_id:
                return RunStatus.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Skipping corrupt metadata: %s", meta_path)
            continue
    return None


def get_run_status_from_dir(output_dir: Path) -> RunStatus | None:
    """Read run metadata directly from a specific output directory.

    Parameters
    ----------
    output_dir : Path
        Directory that should contain run_metadata.json.

    Returns
    -------
    RunStatus | None
        The run status, or ``None`` if the metadata file is missing or invalid.
    """
    meta_path = output_dir / METADATA_FILENAME
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return RunStatus.from_dict(data)
    except (json.JSONDecodeError, KeyError, TypeError):
        logger.warning("Corrupt metadata: %s", meta_path)
        return None


def list_runs(runs_dir: Path) -> list[RunStatus]:
    """List all tracked runs in *runs_dir*, sorted by start_time (newest first).

    Scans every subdirectory for ``run_metadata.json``.  Directories without
    a valid metadata file are silently skipped.

    Parameters
    ----------
    runs_dir : Path
        Parent directory containing per-run subdirectories.

    Returns
    -------
    list[RunStatus]
        All discovered runs, newest first.
    """
    if not runs_dir.is_dir():
        return []
    results: list[RunStatus] = []
    for subdir in runs_dir.iterdir():
        if not subdir.is_dir():
            continue
        status = get_run_status_from_dir(subdir)
        if status is not None:
            results.append(status)
    results.sort(
        key=lambda s: s.start_time or datetime.min,
        reverse=True,
    )
    return results
