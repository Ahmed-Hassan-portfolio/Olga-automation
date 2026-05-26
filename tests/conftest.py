"""Shared pytest fixtures: synthetic OLGA output file generators."""

import numpy as np
import pytest
from pathlib import Path


# ---------------------------------------------------------------------------
# Synthetic output file generators (Phase 5+)
# ---------------------------------------------------------------------------


def create_synthetic_tpl(
    output_path: Path,
    n_timesteps: int = 10,
    variables: list[dict] | None = None,
) -> Path:
    """Create a synthetic .tpl (trend plot) file matching OLGA format.

    Parameters
    ----------
    output_path : Path
        File path to write the synthetic .tpl file.
    n_timesteps : int
        Number of timesteps to generate.
    variables : list[dict] | None
        Variable definitions. Each dict has keys: name, position, unit, desc.
        If None, uses default PT@WELLHEAD, TM@WELLHEAD, VOLGBL GLOBAL.

    Returns
    -------
    Path
        The output_path, for convenience.
    """
    if variables is None:
        variables = [
            {"name": "PT", "position": "WELLHEAD", "unit": "PA", "desc": "Pressure"},
            {
                "name": "TM",
                "position": "WELLHEAD",
                "unit": "C",
                "desc": "Fluid temperature",
            },
            {
                "name": "VOLGBL",
                "position": "",
                "unit": "-",
                "desc": "Global max volume error since last write",
                "global": True,
            },
        ]

    lines = []
    # Header
    lines.append("'OLGA 2025.1.2'")
    lines.append("TIME PLOT")
    lines.append("INPUT FILE")
    lines.append("'test_model.inp'")
    lines.append("RESTART FILE")
    lines.append("'restart.rsw'")
    lines.append("DATE")
    lines.append("'2026-02-08 00:00:00'")
    lines.append("PROJECT")
    lines.append("'test_project'")
    lines.append("TITLE")
    lines.append("'test_title'")
    lines.append("AUTHOR")
    lines.append("'test'")

    # Network + geometry.
    # NOTE: OLGA writes n_points + 1 boundary-node coordinates per branch
    # (one per node, not per section). The parser expects n_points + 1
    # floats for positions AND for elevations.
    lines.append("NETWORK")
    lines.append("1")
    lines.append("GEOMETRY ' (M)  '")
    lines.append("BRANCH")
    lines.append("'test_branch'")
    lines.append("3")
    lines.append("       0.000      100.000      200.000      300.000")
    lines.append("       0.000        0.000        0.000        0.000")

    # Catalog
    lines.append("CATALOG")
    lines.append(str(len(variables)))
    for var in variables:
        if var.get("global") or not var["position"]:
            lines.append(
                f"{var['name']} 'GLOBAL' '({var['unit']})' '{var['desc']}'"
            )
        else:
            lines.append(
                f"{var['name']} 'POSITION:' '{var['position']}' "
                f"'({var['unit']})' '{var['desc']}'"
            )

    # Time series data
    lines.append("TIME SERIES  ' (S)  '")
    time_points = np.linspace(0, 3600, n_timesteps)
    for t in time_points:
        row = [f"{t:.6e}"]
        for i, var in enumerate(variables):
            val = 1e7 - t * 100 + i * 1000  # Simple deterministic values
            row.append(f"{val:.6e}")
        lines.append(" ".join(row))

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def create_synthetic_ppl(
    output_path: Path,
    n_timesteps: int = 3,
    n_positions: int = 5,
    variables: list[dict] | None = None,
) -> Path:
    """Create a synthetic .ppl (profile plot) file matching OLGA format.

    Parameters
    ----------
    output_path : Path
        File path to write the synthetic .ppl file.
    n_timesteps : int
        Number of timesteps to generate.
    n_positions : int
        Number of spatial positions per variable.
    variables : list[dict] | None
        Variable definitions. Each dict has keys: name, unit, branch, type, desc.
        If None, uses default PT and TM on test_branch.

    Returns
    -------
    Path
        The output_path, for convenience.
    """
    if variables is None:
        variables = [
            {
                "name": "PT",
                "unit": "PA",
                "branch": "test_branch",
                "type": "SECTION",
                "desc": "Pressure",
            },
            {
                "name": "TM",
                "unit": "C",
                "branch": "test_branch",
                "type": "SECTION",
                "desc": "Fluid temperature",
            },
        ]

    lines = []
    # Header (same as TPL but PROFILE PLOT)
    lines.append("'OLGA 2025.1.2'")
    lines.append("PROFILE PLOT")
    lines.append("INPUT FILE")
    lines.append("'test_model.inp'")
    lines.append("RESTART FILE")
    lines.append("'restart.rsw'")
    lines.append("DATE")
    lines.append("'2026-02-08 00:00:00'")
    lines.append("PROJECT")
    lines.append("'test_project'")
    lines.append("TITLE")
    lines.append("'test_title'")
    lines.append("AUTHOR")
    lines.append("'test'")

    # Network + geometry -- positions for the branch
    positions = np.linspace(0, 1000, n_positions)
    elevations = np.zeros(n_positions)
    lines.append("NETWORK")
    lines.append("1")
    lines.append("GEOMETRY ' (M)  '")
    lines.append("BRANCH")
    lines.append("'test_branch'")
    lines.append(str(n_positions))
    lines.append(" ".join(f"{p:12.3f}" for p in positions))
    lines.append(" ".join(f"{e:12.3f}" for e in elevations))

    # Catalog
    lines.append("CATALOG")
    lines.append(str(len(variables)))
    for var in variables:
        lines.append(
            f"{var['name']} '{var['type']}:' 'BRANCH:' '{var['branch']}' "
            f"'({var['unit']})' '{var['desc']}'"
        )

    # Time series data -- interleaved blocks
    lines.append("TIME SERIES  ' (S)  '")
    time_points = np.linspace(0, 3600, n_timesteps)
    for t_idx, t in enumerate(time_points):
        lines.append(f" {t:.6e}")
        for v_idx, var in enumerate(variables):
            # Deterministic spatial profile: base + position offset + time decay
            vals = []
            for p_idx in range(n_positions):
                val = 1e7 - t * 10 + p_idx * 1000 + v_idx * 5000
                vals.append(f"{val:.6e}")
            lines.append(" ".join(vals))

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def create_synthetic_out(
    output_path: Path,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
    completed: bool = True,
    elapsed_time: float = 3600.0,
    cpu_time: float = 12.5,
) -> Path:
    """Create a synthetic .out simulation log file.

    Parameters
    ----------
    output_path : Path
        File path to write the synthetic .out file.
    errors : list[str] | None
        Error messages to include (format: "Error: {msg}").
    warnings : list[str] | None
        Warning messages to include (format: "Warning: {msg}").
    completed : bool
        Whether to include a completion message.
    elapsed_time : float
        Elapsed simulation time value.
    cpu_time : float
        CPU time value.

    Returns
    -------
    Path
        The output_path, for convenience.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("OLGA Simulation Log")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Initializing OLGA 2025.1.2...")
    lines.append("Reading input file: test_model.inp")
    lines.append("Setting up network...")
    lines.append("")

    # Warnings
    if warnings:
        for w in warnings:
            lines.append(f"Warning: {w}")
        lines.append("")

    # Simulation progress
    lines.append("Starting simulation...")
    lines.append("Timestep 1: t = 100.0 s")
    lines.append("Timestep 2: t = 200.0 s")
    lines.append("")

    # Errors
    if errors:
        for e in errors:
            lines.append(f"Error: {e}")
        lines.append("")

    # Timing
    lines.append(f"Elapsed simulation-time is now {elapsed_time}")
    lines.append(f"CPU time: {cpu_time}")
    lines.append("")

    # Completion
    if completed:
        lines.append("Simulation completed successfully.")
    else:
        lines.append("Simulation stopped.")

    lines.append("")
    lines.append("=" * 60)

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# Pytest fixtures wrapping the generators


@pytest.fixture
def synthetic_tpl(tmp_path):
    """Create a synthetic .tpl file in a temp directory."""
    return create_synthetic_tpl(tmp_path / "test_output.tpl")


@pytest.fixture
def synthetic_ppl(tmp_path):
    """Create a synthetic .ppl file in a temp directory."""
    return create_synthetic_ppl(tmp_path / "test_output.ppl")


@pytest.fixture
def synthetic_out(tmp_path):
    """Create a synthetic .out file in a temp directory."""
    return create_synthetic_out(tmp_path / "test_output.out")
