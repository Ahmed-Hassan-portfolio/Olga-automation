"""Core simulation runner: run_simulation, cancel_run, run_simulation_async.

Launches OLGA's ``opi`` CLI tool as a subprocess, tracks running processes
for cancellation/timeout support, and discovers output files after completion.

All subprocess management uses :mod:`threading` (not asyncio) per project
convention for Windows compatibility.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from olga_automation.execution_manager.environment import detect_olga_install, get_olga_env
from olga_automation.execution_manager.models import RunConfig, RunState, RunStatus

# ---------------------------------------------------------------------------
# Module state: tracks active runs for cancel_run / get_run_result
# ---------------------------------------------------------------------------

_active_runs: dict[str, dict[str, Any]] = {}
"""Map of run_id -> {"process": Popen|None, "thread": Thread|None, "status": RunStatus}."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_opi_command(config: RunConfig, opi_executable: str = "opi") -> list[str]:
    """Build the ``opi`` CLI command list from a :class:`RunConfig`.

    Parameters
    ----------
    config : RunConfig
        Simulation configuration.
    opi_executable : str
        Full path to the opi executable (or just ``"opi"`` if on PATH).

    Returns
    -------
    list[str]
        Command tokens suitable for :class:`subprocess.Popen`.
        Only includes optional flags that differ from defaults.
    """
    cmd: list[str] = [opi_executable, str(config.opi_path.resolve())]
    cmd.extend(["-outDir", str(config.output_dir.resolve())])

    if config.n_threads > 1:
        cmd.extend(["-nthreads", str(config.n_threads)])
    if not config.generate_tpl:
        cmd.append("-notpl")
    if not config.generate_ppl:
        cmd.append("-noppl")
    if not config.generate_out:
        cmd.append("-noout")

    return cmd


def _locate_output_files(
    output_dir: Path,
    opi_dir: Path | None = None,
    opi_stem: str | None = None,
    run_start_time: float | None = None,
) -> dict[str, list[Path]]:
    """Discover output files in *output_dir* by extension, with *opi_dir* fallback.

    OLGA may ignore the ``-outDir`` flag and write outputs next to the ``.opi``
    file.  When *opi_dir* is provided and differs from *output_dir*, this
    function also searches *opi_dir* and copies any found files into
    *output_dir* so that downstream consumers always find outputs there.

    The fallback is guarded by *opi_stem* and *run_start_time* to prevent
    copying stale or unrelated files from a previous simulation run.

    Parameters
    ----------
    output_dir : Path
        Primary directory to scan (the requested output location).
    opi_dir : Path | None
        Directory containing the ``.opi`` file.  Searched as a fallback when
        *output_dir* has no outputs for a given extension.
    opi_stem : str | None
        Stem of the ``.opi`` file (e.g. ``"model"`` for ``model.opi``).
        When provided, the fallback only copies files whose stem matches.
    run_start_time : float | None
        ``time.time()`` captured just before the simulation started.
        When provided, the fallback only copies files modified after this time.

    Returns
    -------
    dict[str, list[Path]]
        ``{"tpl": [...], "ppl": [...], "out": [...]}`` with sorted Path lists
        whose entries always reside inside *output_dir*.
    """
    extensions = ("tpl", "ppl", "out")
    result: dict[str, list[Path]] = {}

    # Determine whether opi_dir is a genuinely different location
    search_opi = (
        opi_dir is not None
        and opi_dir.resolve() != output_dir.resolve()
    )

    for ext in extensions:
        found = sorted(output_dir.glob(f"*.{ext}"))

        if not found and search_opi:
            # Fallback: look in opi_dir and copy into output_dir.
            # Use stem-matched glob when opi_stem is available;
            # otherwise fall back to wildcard (legacy behavior).
            if opi_stem:
                opi_files = sorted(opi_dir.glob(f"{opi_stem}.{ext}"))
            else:
                opi_files = sorted(opi_dir.glob(f"*.{ext}"))

            copied_any = False
            for src in opi_files:
                # Skip files that predate the run (stale outputs)
                if run_start_time is not None:
                    try:
                        mtime = os.path.getmtime(src)
                    except OSError:
                        continue
                    if mtime < run_start_time:
                        logger.debug(
                            "Skipping stale fallback file %s (mtime %.1f < run_start %.1f)",
                            src, mtime, run_start_time,
                        )
                        continue

                dst = output_dir / src.name
                shutil.copy2(src, dst)
                copied_any = True

            if copied_any:
                logger.warning(
                    "Output files not found in %s; copied from opi directory %s (fallback)",
                    output_dir, opi_dir,
                )

            found = sorted(output_dir.glob(f"*.{ext}"))

        result[ext] = found

    return result


def _validate_pvt_path(opi_path: Path) -> None:
    """Validate that the PVT file referenced in the .opi can be found.

    Reads the ``<Key Name="PVTFILE">`` value from the FILES keyword in the
    .opi file, resolves it relative to the .opi's parent directory, and
    raises a clear error if the file does not exist.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to validate.

    Raises
    ------
    FileNotFoundError
        If the PVT file cannot be found at the resolved path.
    """
    from olga_automation.opi_parser.xml_navigator import (
        _element_text,
        get_key_values,
        iter_keywords,
        load_opi,
    )

    try:
        tree = load_opi(opi_path)
    except Exception:
        logger.debug("Could not load %s for PVT validation; skipping", opi_path)
        return

    # Find the FILES keyword and extract PVTFILE
    pvt_rel_path: str | None = None
    for _scope, kw_el in iter_keywords(tree):
        kw_type = _element_text(kw_el, "Type")
        if kw_type == "FILES":
            kv = get_key_values(kw_el, "PVTFILE")
            if kv and kv.values:
                pvt_rel_path = kv.values[0]
            break

    if not pvt_rel_path:
        logger.debug("No PVTFILE key found in %s; skipping validation", opi_path)
        return

    # Resolve relative to the .opi's parent directory
    opi_dir = opi_path.parent
    resolved = (opi_dir / pvt_rel_path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(
            f"PVT file not found. The .opi references relative path "
            f"'{pvt_rel_path}' which resolves to '{resolved}' (does not "
            f"exist). Either move the PVT file to that location, fix "
            f"the PVTFILE path in the .opi file, or provide the "
            f"pvt_file parameter with the correct PVT file path."
        )

    logger.debug("PVT file validated: %s -> %s", pvt_rel_path, resolved)


def _check_batch_summary(working_dir: Path) -> tuple[bool, str | None]:
    """Check ``BatchExecutionSummary.txt`` for the true simulation outcome.

    OLGA's ``opi.exe`` wrapper always returns exit code 0, even when the
    inner simulation fails.  The real success/failure status is written to
    ``BatchExecutionSummary.txt`` in the working directory.

    Parameters
    ----------
    working_dir : Path
        Directory where ``opi.exe`` was run (``config.output_dir``).

    Returns
    -------
    tuple[bool, str | None]
        ``(success, error_detail)`` — *success* is True when all cases
        finished successfully (or when the summary file is missing, to
        preserve backward compatibility).  *error_detail* contains the
        content of ``BatchExecutionSummary.txt.simOut`` when available.
    """
    summary_path = working_dir / "BatchExecutionSummary.txt"
    if not summary_path.exists():
        return True, None

    try:
        summary_text = summary_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True, None

    # Look for "N of M case(s) finished successfully"
    match = re.search(
        r"(\d+)\s+of\s+(\d+)\s+case\(s\)\s+finished\s+successfully",
        summary_text,
    )
    if match is None:
        # Unrecognized format — don't break existing behavior
        return True, None

    n_success = int(match.group(1))
    n_total = int(match.group(2))

    if n_success >= n_total:
        return True, None

    # Simulation failed — try to get detailed error from .simOut
    error_detail = f"{n_success} of {n_total} case(s) finished successfully"
    sim_out_path = working_dir / "BatchExecutionSummary.txt.simOut"
    if sim_out_path.exists():
        try:
            sim_out_text = sim_out_path.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
            if sim_out_text:
                # Truncate very long error logs to a reasonable size
                if len(sim_out_text) > 2000:
                    sim_out_text = sim_out_text[:2000] + "\n... (truncated)"
                error_detail = f"{error_detail}\n{sim_out_text}"
        except OSError:
            pass

    return False, error_detail


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _fix_pvt_for_simulation(opi_path: Path, pvt_file: Path) -> None:
    """Copy a PVT file next to the .opi and update the PVTFILE key.

    Creates a ``Multiflash/`` subdirectory next to *opi_path*, copies
    *pvt_file* into it, and rewrites the ``PVTFILE`` key in the .opi
    XML to ``./Multiflash/{filename}``.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    pvt_file : Path
        Path to the PVT file to copy.  Must exist.

    Raises
    ------
    ValueError
        If *pvt_file* does not exist.
    """
    from olga_automation.opi_parser.xml_navigator import (
        _element_text,
        get_key_values,
        iter_keywords,
        load_opi,
        save_opi,
        set_key_values,
    )

    pvt_file = Path(pvt_file)
    if not pvt_file.exists():
        raise ValueError(f"Provided pvt_file does not exist: '{pvt_file}'")

    opi_dir = opi_path.parent

    # Copy PVT file into Multiflash/ subdirectory next to the .opi
    mf_dir = opi_dir / "Multiflash"
    mf_dir.mkdir(parents=True, exist_ok=True)
    dst_pvt = mf_dir / pvt_file.name
    shutil.copy2(pvt_file, dst_pvt)

    # Update the PVTFILE key in the .opi XML
    tree = load_opi(opi_path)
    files_kw = None
    for _scope, kw_el in iter_keywords(tree):
        kw_type = _element_text(kw_el, "Type")
        if kw_type == "FILES":
            files_kw = kw_el
            break

    if files_kw is not None:
        new_rel_path = f"./Multiflash/{pvt_file.name}"
        set_key_values(files_kw, "PVTFILE", [new_rel_path])
        save_opi(tree, opi_path)
        logger.info(
            "Copied PVT file '%s' -> '%s' and updated PVTFILE to '%s'",
            pvt_file,
            dst_pvt,
            new_rel_path,
        )
    else:
        logger.warning(
            "Copied PVT file '%s' -> '%s' but no FILES keyword found to update",
            pvt_file,
            dst_pvt,
        )


def run_simulation(
    config: RunConfig,
    env: dict[str, str] | None = None,
    pvt_file: str | Path | None = None,
) -> RunStatus:
    """Run a single OLGA simulation synchronously.

    Blocks until the simulation completes, times out, or an error occurs.

    Parameters
    ----------
    config : RunConfig
        Simulation configuration (opi path, output dir, flags, timeout).
    env : dict[str, str] | None
        Environment dict for the subprocess.  When *None*, calls
        :func:`get_olga_env` which may also return *None* (meaning use
        the default inherited environment).
    pvt_file : str, Path, or None
        Optional path to a PVT fluid property file (``.tab``). When the
        .opi model's PVT path cannot be resolved, this file is copied
        into a ``Multiflash/`` subdirectory next to the .opi and the
        PVTFILE key is updated accordingly.

    Returns
    -------
    RunStatus
        Final status including timing, return code, output files (on success),
        and error message (on failure).
    """
    run_id = str(uuid.uuid4())

    # Ensure output directory exists
    config.output_dir.mkdir(parents=True, exist_ok=True)

    # Detect OLGA installation for full executable path
    detection = detect_olga_install()
    opi_exe = str(detection["opi_executable"]) if detection["opi_executable"] else "opi"

    # Build command
    cmd = _build_opi_command(config, opi_executable=opi_exe)

    # Resolve environment
    if env is None:
        env = get_olga_env()

    # Pre-flight: validate PVT file is accessible from the .opi location.
    # If validation fails and pvt_file is provided, copy it into place.
    try:
        _validate_pvt_path(config.opi_path)
    except FileNotFoundError:
        if pvt_file is not None:
            _fix_pvt_for_simulation(config.opi_path, Path(pvt_file))
        else:
            raise

    start_time = datetime.now()
    run_start_clock = time.time()  # monotonic wall-clock for stale-file filtering
    process = None
    return_code = None
    error_message = None
    state = RunState.FAILED  # default; overwritten on success

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=str(config.output_dir),
        )

        # Register for cancel support
        _active_runs[run_id] = {
            "process": process,
            "thread": None,
            "status": None,
        }

        # Use communicate() instead of wait() to avoid pipe-buffer deadlock.
        # Python docs warn: wait() with PIPE can deadlock if the child fills
        # the OS pipe buffer (~4KB on Windows).  communicate() drains pipes
        # and waits in the correct order.
        stdout_bytes, stderr_bytes = process.communicate(
            timeout=config.timeout_seconds
        )

        return_code = process.returncode

        if return_code == 0:
            # opi.exe returns 0 even when the inner simulation fails.
            # Check BatchExecutionSummary.txt for the real outcome.
            batch_ok, batch_error = _check_batch_summary(config.output_dir)
            if batch_ok:
                state = RunState.COMPLETED
                error_message = None
            else:
                state = RunState.FAILED
                error_message = batch_error
        else:
            state = RunState.FAILED
            stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
            error_message = stderr_text or f"Exit code {return_code}"

    except subprocess.TimeoutExpired:
        if process is not None:
            process.kill()
            process.communicate()  # drain pipes to avoid zombie
        state = RunState.FAILED
        error_message = (
            f"Simulation timed out after {config.timeout_seconds} seconds"
        )

    except Exception as exc:
        # Kill and drain the process to avoid orphaned subprocesses and
        # locked file handles on the output directory.
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                pass
        state = RunState.FAILED
        error_message = str(exc)

    finally:
        _active_runs.pop(run_id, None)

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    # Discover output files only on success
    output_files = (
        _locate_output_files(
            config.output_dir,
            opi_dir=config.opi_path.parent,
            opi_stem=config.opi_path.stem,
            run_start_time=run_start_clock,
        )
        if state == RunState.COMPLETED
        else None
    )

    return RunStatus(
        run_id=run_id,
        state=state,
        opi_path=config.opi_path,
        output_dir=config.output_dir,
        start_time=start_time,
        end_time=end_time,
        elapsed_seconds=elapsed,
        return_code=return_code,
        error_message=error_message,
        output_files=output_files,
    )


def run_simulation_async(
    config: RunConfig,
    env: dict[str, str] | None = None,
    pvt_file: str | Path | None = None,
) -> RunStatus:
    """Launch a simulation in a background thread and return immediately.

    The caller receives an initial :class:`RunStatus` with ``state="running"``.
    Use :func:`get_run_result` to poll for the final result.

    Parameters
    ----------
    config : RunConfig
        Simulation configuration.
    env : dict[str, str] | None
        Environment dict for the subprocess.
    pvt_file : str, Path, or None
        Optional path to a PVT fluid property file (``.tab``). Passed
        through to :func:`run_simulation`.

    Returns
    -------
    RunStatus
        Initial status with ``state=RunState.RUNNING``.
    """
    run_id = str(uuid.uuid4())
    initial_status = RunStatus(
        run_id=run_id,
        state=RunState.RUNNING,
        opi_path=config.opi_path,
        output_dir=config.output_dir,
        start_time=datetime.now(),
    )

    _active_runs[run_id] = {
        "process": None,
        "thread": None,
        "status": initial_status,
    }

    def _run() -> None:
        result = run_simulation(config, env, pvt_file=pvt_file)
        # Preserve the original run_id so the caller can look it up
        result.run_id = run_id
        _active_runs[run_id]["status"] = result

    thread = threading.Thread(target=_run, daemon=True)
    _active_runs[run_id]["thread"] = thread
    thread.start()

    return initial_status


def cancel_run(run_id: str) -> bool:
    """Cancel a running simulation.

    Parameters
    ----------
    run_id : str
        The run identifier returned by :func:`run_simulation_async`.

    Returns
    -------
    bool
        *True* if the run was found and killed, *False* if *run_id* is unknown.
    """
    entry = _active_runs.get(run_id)
    if entry is None:
        return False

    process = entry.get("process")
    if process is not None and process.poll() is None:
        process.kill()

    # Update stored status to cancelled
    if entry.get("status") is not None:
        entry["status"].state = RunState.CANCELLED

    return True


def get_run_result(run_id: str) -> RunStatus | None:
    """Look up the current status of a run.

    Parameters
    ----------
    run_id : str
        The run identifier.

    Returns
    -------
    RunStatus | None
        Current status, or *None* if *run_id* is not tracked.
    """
    entry = _active_runs.get(run_id)
    if entry is None:
        return None
    return entry.get("status")
