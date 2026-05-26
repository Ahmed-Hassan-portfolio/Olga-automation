"""Detect OLGA install, capture env vars from Olga Command Prompt."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

# Registry paths where OLGA installation may be recorded
OLGA_REGISTRY_PATHS: list[tuple[str, str]] = [
    (r"SOFTWARE\Schlumberger\OLGA", "InstallDir"),
    (r"SOFTWARE\Schlumberger\OLGA", "Home"),
    (r"SOFTWARE\SPT Group\OLGA", "InstallDir"),
    (r"SOFTWARE\SPT Group\OLGA", "Home"),
]

# Environment variable keys relevant to OLGA operation
OLGA_ENV_KEYS: set[str] = {"OLGA_HOME", "LM_LICENSE_FILE", "PATH"}


def _is_olga_env_key(key: str) -> bool:
    """Return True if *key* is an OLGA-relevant environment variable name."""
    return key in OLGA_ENV_KEYS or key.startswith("OLGA_")


def _find_opi_in_dir(olga_home: Path) -> Path | None:
    """Look for opi.exe (or opi) under *olga_home* root and /bin."""
    for name in ("opi.exe", "opi"):
        # Check root directory first (OLGA 2025+ installs opi.exe at root)
        candidate = olga_home / name
        if candidate.exists():
            return candidate
        # Fall back to bin/ subdirectory
        candidate = olga_home / "bin" / name
        if candidate.exists():
            return candidate
    return None


def _check_registry() -> Path | None:
    """Try to find OLGA install directory from Windows registry.

    Returns the install directory Path if found, else None.
    """
    if winreg is None:
        return None

    for subkey_path, value_name in OLGA_REGISTRY_PATHS:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as key:
                install_dir, _ = winreg.QueryValueEx(key, value_name)
                if install_dir:
                    return Path(install_dir)
        except (OSError, FileNotFoundError):
            continue

    return None


# -------------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------------


def detect_olga_install() -> dict[str, Any]:
    """Detect OLGA installation by checking env vars, PATH, and registry.

    Returns a dict with keys:
        olga_home:      Path | None  -- installation root directory
        opi_executable: Path | None  -- full path to opi executable
        version:        str  | None  -- version string (populated by validate)
        source:         str          -- "environment", "path", "registry", or "not_found"

    The function does **not** raise on failure; instead it returns
    ``source="not_found"`` with None values so the caller can decide
    how to handle a missing installation.
    """
    result: dict[str, Any] = {
        "olga_home": None,
        "opi_executable": None,
        "version": None,
        "source": "not_found",
    }

    # 1. Check OLGA_HOME environment variable
    olga_home_env = os.environ.get("OLGA_HOME")
    if olga_home_env:
        olga_home = Path(olga_home_env)
        result["olga_home"] = olga_home
        result["source"] = "environment"
        opi = _find_opi_in_dir(olga_home)
        if opi is not None:
            result["opi_executable"] = opi
        return result

    # 2. Check PATH via shutil.which
    opi_on_path = shutil.which("opi")
    if opi_on_path is not None:
        opi_path = Path(opi_on_path)
        result["opi_executable"] = opi_path
        result["source"] = "path"
        # Derive olga_home: opi is typically at <olga_home>/bin/opi.exe
        if opi_path.parent.name.lower() == "bin":
            result["olga_home"] = opi_path.parent.parent
        return result

    # 3. Check Windows registry
    registry_home = _check_registry()
    if registry_home is not None:
        result["olga_home"] = registry_home
        result["source"] = "registry"
        opi = _find_opi_in_dir(registry_home)
        if opi is not None:
            result["opi_executable"] = opi
        return result

    return result


def capture_env_vars(dump_file: Path | None = None) -> dict[str, str | None]:
    """Capture OLGA-related environment variables.

    Parameters
    ----------
    dump_file : Path | None
        Path to a text file produced by ``set > dump.txt`` in the Olga Command
        Prompt.  Each line is expected to be ``KEY=VALUE``.  If *None*, reads
        from the current process environment (``os.environ``).

    Returns
    -------
    dict[str, str | None]
        Mapping of relevant env-var names to their values.  Keys that were
        not found have value ``None``.
    """
    raw: dict[str, str] = {}

    if dump_file is not None:
        text = dump_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if key and _is_olga_env_key(key):
                raw[key] = value
    else:
        for key, value in os.environ.items():
            if _is_olga_env_key(key):
                raw[key] = value

    # Build result: guarantee well-known keys appear (as None if not found)
    result: dict[str, str | None] = {
        "OLGA_HOME": raw.get("OLGA_HOME"),
        "LM_LICENSE_FILE": raw.get("LM_LICENSE_FILE"),
    }

    # Include PATH if found
    if "PATH" in raw:
        result["PATH"] = raw["PATH"]

    # Include any extra OLGA_* variables
    for key, value in raw.items():
        if key not in result:
            result[key] = value

    return result


def validate_environment(
    opi_path: str | Path | None = None,
) -> dict[str, Any]:
    """Validate that the OLGA opi executable can run.

    Parameters
    ----------
    opi_path : str | Path | None
        Explicit path to the opi executable.  When *None*, the function
        calls :func:`detect_olga_install` to try finding it automatically.

    Returns
    -------
    dict
        ``{"valid": bool, "version": str|None, "error": str|None}``
    """
    if opi_path is None:
        detection = detect_olga_install()
        opi_path = detection.get("opi_executable")

    if opi_path is None:
        return {
            "valid": False,
            "version": None,
            "error": "opi executable not found",
        }

    opi_path = Path(opi_path)

    try:
        proc = subprocess.run(
            [str(opi_path), "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        return {
            "valid": False,
            "version": None,
            "error": "Timeout: opi did not respond within 10 seconds",
        }
    except FileNotFoundError as exc:
        return {
            "valid": False,
            "version": None,
            "error": f"opi executable not found: {exc}",
        }
    except OSError as exc:
        return {
            "valid": False,
            "version": None,
            "error": f"Failed to run opi: {exc}",
        }

    if proc.returncode != 0:
        error_output = (proc.stderr or proc.stdout or "").strip()
        return {
            "valid": False,
            "version": None,
            "error": f"opi returned exit code {proc.returncode}: {error_output}",
        }

    # Parse version from stdout
    version = _parse_version(proc.stdout)
    return {
        "valid": True,
        "version": version,
        "error": None,
    }


def _parse_version(output: str) -> str | None:
    """Extract an OLGA version string from opi output."""
    # Try patterns like "OLGA version 2024.1.0" or "Version: 2024.1"
    match = re.search(r"(?:version|Version)[:\s]+(\S+)", output)
    if match:
        return match.group(1)
    # Fallback: return first line if non-empty
    first_line = output.strip().split("\n")[0].strip() if output.strip() else None
    return first_line or None


def get_olga_env(dump_file: Path | None = None) -> dict[str, str] | None:
    """Build a complete environment dict suitable for ``Popen(env=...)``.

    Combines the current process environment with OLGA-specific overrides
    captured via :func:`capture_env_vars`.

    Parameters
    ----------
    dump_file : Path | None
        Optional env-dump file (see :func:`capture_env_vars`).

    Returns
    -------
    dict[str, str] | None
        Merged environment, or *None* if no OLGA-specific variables were
        found (indicating the caller should just use the default env).
    """
    captured = capture_env_vars(dump_file)

    # Check if any OLGA-specific variables were actually found
    has_olga_vars = any(
        v is not None
        for k, v in captured.items()
        if k not in ("PATH",)  # PATH alone doesn't indicate OLGA env
    )

    if not has_olga_vars:
        return None

    # Merge: current env + captured overrides
    merged: dict[str, str] = dict(os.environ)
    for key, value in captured.items():
        if value is not None:
            merged[key] = value

    return merged
