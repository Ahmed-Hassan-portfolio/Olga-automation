"""Parse .out simulation log files.

The .out file is a plain text log containing simulation progress messages,
warnings, errors, timing information, and convergence data. This module
extracts structured information using regex pattern matching.

Confidence on .out format is LOW -- patterns are educated guesses based on
OLGA documentation references and may need updating against real .out files.
"""

from __future__ import annotations

import re
from pathlib import Path

from olga_automation.exceptions import OutputParseError

# ---------------------------------------------------------------------------
# Compiled regex patterns (module-level for performance)
# ---------------------------------------------------------------------------

# Error patterns: match lines containing error indicators
ERROR_PATTERNS = [
    re.compile(r"(?i)\berror\s*:"),
    re.compile(r"(?i)\bfatal\s*:"),
    re.compile(r"(?i)license\s+(?:not\s+available|error|failure)"),
]

# Warning patterns: match lines containing warning indicators
WARNING_PATTERNS = [
    re.compile(r"(?i)\bwarning\s*:"),
]

# Timing patterns: extract numeric values from timing messages.
# Multiple patterns per key for backward compatibility across OLGA versions.
# OLGA 2025 format:
#   TOTAL SIMULATED TIME: 64800.4577 s
#   SIMULATION TIME:        2804.8126 s
#   TOTAL EXECUTION TIME:   2840.0218 s
# Legacy/generic format:
#   Elapsed simulation-time is now 3600.0
#   CPU time: 120.5
TIMING_PATTERNS_MULTI: dict[str, list[re.Pattern]] = {
    "elapsed_simulation_time": [
        re.compile(r"(?i)TOTAL\s+SIMULATED\s+TIME:\s*([\d.eE+\-]+)"),
        re.compile(r"(?i)Elapsed\s+simulation-time\s+is\s+now\s+([\d.eE+\-]+)"),
    ],
    "cpu_time": [
        re.compile(r"(?i)^\s*SIMULATION\s+TIME:\s*([\d.eE+\-]+)"),
        re.compile(r"(?i)CPU\s+time[:\s]+([\d.eE+\-]+)"),
    ],
    "total_execution_time": [
        re.compile(r"(?i)TOTAL\s+EXECUTION\s+TIME:\s*([\d.eE+\-]+)"),
    ],
    "initialization_time": [
        re.compile(r"(?i)INITIALIZATION\s+TIME:\s*([\d.eE+\-]+)"),
    ],
}

# Convergence patterns: extract volume error information
CONVERGENCE_PATTERNS = {
    "max_volume_error": re.compile(
        r"(?i)(?:max(?:imum)?\s+)?volume\s+error[:\s]+([\d.eE+\-]+)"
    ),
}

# Time step info patterns (OLGA 2025 .out format)
TIMESTEP_PATTERNS = {
    "number_of_timesteps": re.compile(
        r"(?i)NUMBER\s+OF\s+TIME\s+STEPS:\s*([\d]+)"
    ),
    "average_timestep": re.compile(
        r"(?i)AVERAGE\s+TIME\s+STEP:\s*([\d.eE+\-]+)"
    ),
}

# OLGA version pattern
VERSION_PATTERN = re.compile(r"(?i)VERSION\s*:\s*OLGA\s+([\d.]+)")

# Completion patterns: detect successful simulation completion
# OLGA 2025 uses: "NORMAL STOP IN EXECUTION"
COMPLETION_PATTERNS = [
    re.compile(r"(?i)NORMAL\s+STOP\s+IN\s+EXECUTION"),
    re.compile(r"(?i)simulation\s+completed"),
    re.compile(r"(?i)simulation\s+finished"),
    re.compile(r"(?i)end\s+of\s+simulation"),
]


def parse_out(out_path: Path) -> dict:
    """Parse an OLGA .out simulation log file.

    Scans the log text for errors, warnings, timing information, convergence
    data, and completion status using regex pattern matching.

    Parameters
    ----------
    out_path : Path
        Path to the .out file.

    Returns
    -------
    dict
        Parsed log information with keys:
        - ``errors`` (list[str]): Lines matching error patterns.
        - ``warnings`` (list[str]): Lines matching warning patterns.
        - ``convergence`` (dict): Convergence info, e.g.
          ``{"max_volume_error": float | None}``.
        - ``timing`` (dict): Timing info, e.g.
          ``{"elapsed_simulation_time": float | None, "cpu_time": float | None}``.
        - ``completed`` (bool): True if a completion pattern was found.

    Raises
    ------
    OutputParseError
        If the file does not exist or cannot be read.
    """
    out_path = Path(out_path)

    if not out_path.exists():
        raise OutputParseError(f"Output file not found: {out_path}")

    try:
        text = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise OutputParseError(f"Cannot read output file {out_path}: {exc}") from exc

    errors: list[str] = []
    warnings: list[str] = []
    timing: dict[str, float | None] = {
        "elapsed_simulation_time": None,
        "cpu_time": None,
        "total_execution_time": None,
        "initialization_time": None,
    }
    convergence: dict[str, float | None] = {
        "max_volume_error": None,
    }
    timestep_info: dict[str, float | None] = {
        "number_of_timesteps": None,
        "average_timestep": None,
    }
    completed = False
    olga_version: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Check error patterns
        for pattern in ERROR_PATTERNS:
            if pattern.search(stripped):
                errors.append(stripped)
                break  # one match per line is enough

        # Check warning patterns (separate from errors -- a line could match both)
        for pattern in WARNING_PATTERNS:
            if pattern.search(stripped):
                warnings.append(stripped)
                break

        # Check timing patterns (take the LAST match in the file)
        for key, patterns in TIMING_PATTERNS_MULTI.items():
            for pattern in patterns:
                match = pattern.search(stripped)
                if match:
                    try:
                        timing[key] = float(match.group(1))
                    except (ValueError, IndexError):
                        pass
                    break  # first matching pattern wins for this key

        # Check convergence patterns
        for key, pattern in CONVERGENCE_PATTERNS.items():
            match = pattern.search(stripped)
            if match:
                try:
                    convergence[key] = float(match.group(1))
                except (ValueError, IndexError):
                    pass

        # Check time step info patterns
        for key, pattern in TIMESTEP_PATTERNS.items():
            match = pattern.search(stripped)
            if match:
                try:
                    timestep_info[key] = float(match.group(1))
                except (ValueError, IndexError):
                    pass

        # Check OLGA version
        if olga_version is None:
            match = VERSION_PATTERN.search(stripped)
            if match:
                olga_version = match.group(1)

        # Check completion patterns
        if not completed:
            for pattern in COMPLETION_PATTERNS:
                if pattern.search(stripped):
                    completed = True
                    break

    return {
        "olga_version": olga_version,
        "errors": errors,
        "warnings": warnings,
        "convergence": convergence,
        "timing": timing,
        "timestep_info": timestep_info,
        "completed": completed,
    }
