"""Data extractors: extract_variable, extract_time_window, compare_runs.

These functions provide querying and analysis capabilities on top of parsed
OLGA output data. They operate on TrendData objects (from .tpl parsing) and
enable extracting specific variables, slicing time windows, and comparing
results across multiple simulation runs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from olga_automation.output_parser.models import TrendData, VariableSeries


def extract_variable(
    trend_data: TrendData,
    variable: str,
    position: str | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract a specific variable's time series from TrendData.

    Supports three lookup modes:
    1. Exact key: ``variable="PT@WELLHEAD"`` (no position param)
    2. Composed key: ``variable="PT", position="WELLHEAD"`` -> ``"PT@WELLHEAD"``
    3. Auto-resolve: ``variable="PT"`` with no position -- if exactly one
       key starts with ``"PT@"``, it is used; if multiple match, raises
       KeyError listing all matches.

    Parameters
    ----------
    trend_data : TrendData
        Parsed trend data containing variables dict.
    variable : str
        Variable name (e.g. "PT") or exact key (e.g. "PT@WELLHEAD").
    position : str | None
        Optional position qualifier. If provided, the lookup key becomes
        ``f"{variable}@{position}"``.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(time, values)`` -- both 1D numpy arrays of the same length.

    Raises
    ------
    KeyError
        If the variable is not found, or if multiple matches exist when
        no position is specified.
    """
    # Build lookup key
    if position is not None:
        key = f"{variable}@{position}"
    else:
        key = variable

    # Try exact match first
    if key in trend_data.variables:
        vs = trend_data.variables[key]
        return (trend_data.time, vs.values)

    # If position was explicitly given and not found, fail immediately
    if position is not None:
        raise KeyError(
            f"Variable '{key}' not found in TrendData. "
            f"Available: {list(trend_data.variables.keys())}"
        )

    # Auto-resolve: search for keys starting with "variable@"
    prefix = f"{variable}@"
    matches = [k for k in trend_data.variables if k.startswith(prefix)]

    if len(matches) == 1:
        vs = trend_data.variables[matches[0]]
        return (trend_data.time, vs.values)

    if len(matches) > 1:
        raise KeyError(
            f"Ambiguous variable '{variable}' matches multiple keys: {matches}. "
            f"Specify a position to disambiguate."
        )

    # No matches at all
    raise KeyError(
        f"Variable '{variable}' not found in TrendData. "
        f"Available: {list(trend_data.variables.keys())}"
    )


def extract_time_window(
    trend_data: TrendData,
    t_start: float,
    t_end: float,
) -> TrendData:
    """Extract a time-windowed subset of TrendData.

    Creates a new TrendData containing only timesteps where
    ``t_start <= time <= t_end``. All variables are sliced to match.

    Parameters
    ----------
    trend_data : TrendData
        Source trend data.
    t_start : float
        Start of the time window (inclusive).
    t_end : float
        End of the time window (inclusive).

    Returns
    -------
    TrendData
        New TrendData with sliced time and variable arrays. If no timesteps
        fall within the range, arrays have length 0.

    Raises
    ------
    ValueError
        If ``t_start > t_end``.
    """
    if t_start > t_end:
        raise ValueError(
            f"t_start ({t_start}) must be <= t_end ({t_end})"
        )

    # Boolean mask for the time window
    mask = (trend_data.time >= t_start) & (trend_data.time <= t_end)

    # Slice all variables
    sliced_variables: dict[str, VariableSeries] = {}
    for key, vs in trend_data.variables.items():
        sliced_variables[key] = VariableSeries(
            name=vs.name,
            position=vs.position,
            unit=vs.unit,
            values=vs.values[mask],
        )

    return TrendData(
        olga_version=trend_data.olga_version,
        time_unit=trend_data.time_unit,
        time=trend_data.time[mask],
        variables=sliced_variables,
        metadata=dict(trend_data.metadata),
    )


def compare_runs(
    run_dirs: list[Path],
    variable: str,
    position: str,
) -> dict:
    """Compare a variable across multiple simulation run directories.

    For each directory, finds the first ``.tpl`` file, parses it, extracts
    the specified variable, and collects results for comparison.

    Parameters
    ----------
    run_dirs : list[Path]
        List of directories, each containing OLGA output files.
    variable : str
        Variable name to extract (e.g. "PT").
    position : str
        Position qualifier (e.g. "WELLHEAD").

    Returns
    -------
    dict
        Comparison result with keys:
        - ``variable`` (str): The variable name.
        - ``position`` (str): The position.
        - ``runs`` (list[dict]): One entry per run directory, each with
          ``dir``, ``time`` (list), ``values`` (list), or ``error`` (str).

    Raises
    ------
    ValueError
        If ``run_dirs`` is empty.
    """
    if not run_dirs:
        raise ValueError("run_dirs must not be empty")

    # Import parse_tpl at function level to avoid circular imports
    # and to handle the case where tpl_parser isn't implemented yet
    from olga_automation.output_parser.tpl_parser import parse_tpl

    runs = []
    for run_dir in run_dirs:
        run_dir = Path(run_dir)
        tpl_files = list(run_dir.glob("*.tpl"))

        if not tpl_files:
            runs.append({"dir": str(run_dir), "error": "No .tpl file found"})
            continue

        try:
            trend_data = parse_tpl(tpl_files[0])
            time_arr, values_arr = extract_variable(
                trend_data, variable, position
            )
            runs.append({
                "dir": str(run_dir),
                "time": time_arr.tolist(),
                "values": values_arr.tolist(),
            })
        except Exception as exc:
            runs.append({"dir": str(run_dir), "error": str(exc)})

    return {
        "variable": variable,
        "position": position,
        "runs": runs,
    }
