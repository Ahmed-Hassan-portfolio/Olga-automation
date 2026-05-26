"""Model validation: validate_opi (runs opi -exitRC).

Provides a safety gate before simulation execution.  Runs the external
``opi`` command with the ``-exitRC`` flag which performs rule checks
without starting a simulation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from olga_automation.exceptions import OlgaExecutionError


def validate_opi(opi_path: Path) -> dict:
    """Run OLGA validation on an .opi file via ``opi <file> -exitRC``.

    Parameters
    ----------
    opi_path:
        Path to the .opi file to validate.

    Returns
    -------
    dict
        Structured result with keys:

        - **valid** (*bool*) -- ``True`` if return code is 0 and no error
          lines detected.
        - **errors** (*list[str]*) -- Lines from output containing "error"
          (case-insensitive).
        - **warnings** (*list[str]*) -- Lines from output containing
          "warning" (case-insensitive).
        - **return_code** (*int*) -- Process return code.
        - **raw_output** (*str*) -- Full stdout from the opi process.

    Raises
    ------
    FileNotFoundError
        If *opi_path* does not exist on disk.
    OlgaExecutionError
        If the ``opi`` command is not found on ``PATH`` or the
        validation process exceeds the 120-second timeout.
    """
    opi_path = Path(opi_path)
    if not opi_path.exists():
        raise FileNotFoundError(f"OPI file not found: {opi_path}")

    try:
        result = subprocess.run(
            ["opi", str(opi_path), "-exitRC"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except FileNotFoundError:
        raise OlgaExecutionError(
            "opi command not found. Ensure OLGA is installed and 'opi' is on PATH."
        )
    except subprocess.TimeoutExpired:
        raise OlgaExecutionError(
            f"Validation timed out after 120 seconds for {opi_path.name}"
        )

    # Combine stdout and stderr for line-level classification.
    combined = result.stdout + "\n" + result.stderr
    lines = [line for line in combined.splitlines() if line.strip()]

    errors: list[str] = []
    warnings: list[str] = []
    for line in lines:
        lower = line.lower()
        if "error" in lower:
            errors.append(line)
        elif "warning" in lower:
            warnings.append(line)

    return {
        "valid": result.returncode == 0 and len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "return_code": result.returncode,
        "raw_output": result.stdout,
    }
