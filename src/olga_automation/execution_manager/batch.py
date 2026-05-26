"""Batch execution: sweep matrix generation and parallel batch runner.

Provides :func:`build_sweep_matrix` for generating Cartesian-product
parameter studies, and :func:`run_batch` for executing multiple OLGA
simulations in parallel with license-aware queuing and retry logic.

Key design choices:
- ``ThreadPoolExecutor`` with ``max_workers = max_parallel`` to avoid deadlock.
- ``LicenseAwareQueue`` gates actual simulation starts (semaphore-based).
- License failures are retried with exponential backoff; other failures are not.
- Environment is resolved once at batch start for efficiency.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

from olga_automation.execution_manager.environment import get_olga_env
from olga_automation.execution_manager.models import (
    BatchResult,
    RunConfig,
    RunState,
    RunStatus,
)
from olga_automation.execution_manager.queue_manager import (
    LicenseAwareQueue,
    is_license_failure,
)
from olga_automation.execution_manager.run_tracker import save_run
from olga_automation.execution_manager.runner import run_simulation
from olga_automation.opi_parser.writer import create_variant

logger = logging.getLogger(__name__)

# Regex to extract optional [N] index from a param spec tail.
_INDEX_RE = re.compile(r"\[(\d+)\]$")


def parse_param_spec(spec: str) -> tuple[str, str, int | None]:
    """Decompose a parameter specification into (tag, key_name, index).

    Supported formats::

        "FLOWPATH_7.SOURCE_18.MASSFLOW"      -> ("FLOWPATH_7.SOURCE_18", "MASSFLOW", None)
        "FLOWPATH_7.SOURCE_18.MASSFLOW[3]"   -> ("FLOWPATH_7.SOURCE_18", "MASSFLOW", 3)
        "HMININNERWALL"                       -> ("", "HMININNERWALL", None)
        "HMININNERWALL[0]"                    -> ("", "HMININNERWALL", 0)
        "A.B.C.KEY"                           -> ("A.B.C", "KEY", None)

    Parameters
    ----------
    spec : str
        Parameter specification string in ``TAG.KEY`` or ``TAG.KEY[N]`` format.

    Returns
    -------
    tuple[str, str, int | None]
        ``(tag, key_name, index)`` where *tag* may be ``""`` if no dot is
        present, and *index* is ``None`` if no ``[N]`` suffix.
    """
    # Extract optional [N] index
    index: int | None = None
    m = _INDEX_RE.search(spec)
    if m:
        index = int(m.group(1))
        spec = spec[: m.start()]

    # Split on last dot: everything before is tag, last part is key
    if "." in spec:
        last_dot = spec.rfind(".")
        tag = spec[:last_dot]
        key_name = spec[last_dot + 1 :]
    else:
        tag = ""
        key_name = spec

    return tag, key_name, index


def save_sweep_summary(
    output_base_dir: Path,
    sweep_params: dict[str, list],
    configs: list[RunConfig],
) -> Path:
    """Write a sweep_summary.json to *output_base_dir*.

    The summary records the sweep parameters, total case count, and a
    per-case mapping of index to opi_path and output_dir.

    Parameters
    ----------
    output_base_dir : Path
        Directory where sweep_summary.json will be written.
    sweep_params : dict[str, list]
        The sweep parameter definitions.
    configs : list[RunConfig]
        Generated RunConfigs (one per combination).

    Returns
    -------
    Path
        Path to the created sweep_summary.json file.
    """
    cases = []
    for i, cfg in enumerate(configs):
        cases.append(
            {
                "case_index": i,
                "opi_path": str(cfg.opi_path),
                "output_dir": str(cfg.output_dir),
            }
        )

    summary = {
        "sweep_params": {k: [str(v) for v in vals] for k, vals in sweep_params.items()},
        "total_cases": len(configs),
        "cases": cases,
    }

    output_base_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_base_dir / "sweep_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return summary_path


def build_sweep_matrix(
    base_opi: Path,
    sweep_params: dict[str, list],
    output_base_dir: Path,
    **run_config_kwargs,
) -> list[RunConfig]:
    """Generate RunConfigs for every combination in a parameter sweep.

    Uses :func:`itertools.product` to compute the Cartesian product of all
    parameter values, then calls :func:`create_variant` for each combination.

    Parameters
    ----------
    base_opi : Path
        Path to the base .opi model file.
    sweep_params : dict[str, list]
        Mapping of parameter specs (``"TAG.KEY"`` or ``"TAG.KEY[N]"``) to
        lists of values.  All combinations are generated.
    output_base_dir : Path
        Root directory for sweep outputs.  Each case gets a ``case_NNN/``
        subdirectory.
    **run_config_kwargs
        Extra keyword arguments passed through to each :class:`RunConfig`
        (e.g. ``n_threads=4``, ``timeout_seconds=600``).

    Returns
    -------
    list[RunConfig]
        One RunConfig per parameter combination, with unique opi_path
        and output_dir.
    """
    base_opi = Path(base_opi)
    output_base_dir = Path(output_base_dir)
    output_base_dir.mkdir(parents=True, exist_ok=True)

    # Parse all param specs upfront
    param_keys = list(sweep_params.keys())
    param_values = [sweep_params[k] for k in param_keys]
    parsed_specs = [parse_param_spec(k) for k in param_keys]

    # Generate Cartesian product
    combinations = list(itertools.product(*param_values))

    configs: list[RunConfig] = []

    for case_idx, combo in enumerate(combinations):
        case_dir = output_base_dir / f"case_{case_idx:03d}"
        case_dir.mkdir(parents=True, exist_ok=True)

        variant_opi = case_dir / f"variant_{case_idx:03d}.opi"

        # Build modifications list for create_variant
        modifications: list[dict] = []
        for param_idx, value in enumerate(combo):
            tag, key_name, _index = parsed_specs[param_idx]
            # Note: index mode (TAG.KEY[N]) currently sets single value.
            # Full indexed-value replacement (read existing, replace at N)
            # requires an .opi reader call and is deferred to a future
            # enhancement if needed.
            modifications.append(
                {
                    "tag": tag,
                    "key": key_name,
                    "values": [str(value)],
                }
            )

        # Create the variant .opi file
        create_variant(base_opi, variant_opi, modifications)

        # Build RunConfig
        config = RunConfig(
            opi_path=variant_opi,
            output_dir=case_dir,
            **run_config_kwargs,
        )
        configs.append(config)

    # Write summary
    save_sweep_summary(output_base_dir, sweep_params, configs)

    logger.info(
        "Built sweep matrix: %d cases from %d parameters",
        len(configs),
        len(param_keys),
    )

    return configs


def run_batch(
    configs: list[RunConfig],
    max_parallel: int = 2,
    max_retries: int = 3,
    env: dict[str, str] | None = None,
) -> BatchResult:
    """Execute multiple OLGA simulations in parallel with retry logic.

    Uses :class:`ThreadPoolExecutor` with :class:`LicenseAwareQueue` to
    limit concurrency.  License failures are retried with exponential
    backoff; other failures are not retried.

    Parameters
    ----------
    configs : list[RunConfig]
        Simulation configurations to execute.
    max_parallel : int
        Maximum number of concurrent simulations.
    max_retries : int
        Maximum number of retry attempts for license failures.
    env : dict[str, str] | None
        Environment dict for subprocesses.  When *None*, resolved once
        via :func:`get_olga_env`.

    Returns
    -------
    BatchResult
        Contains configs, statuses (in input order), and elapsed time.
    """
    if not configs:
        return BatchResult(
            configs=[],
            statuses=[],
            sweep_params=None,
            total_elapsed_seconds=0.0,
        )

    # Resolve environment once
    if env is None:
        env = get_olga_env()

    logger.info(
        "Starting batch: %d configs, max_parallel=%d, max_retries=%d",
        len(configs),
        max_parallel,
        max_retries,
    )

    start_time = time.monotonic()

    queue = LicenseAwareQueue(max_parallel)

    # Track results by config index to preserve order
    results: dict[int, RunStatus] = {}
    # Track retry counts per config index
    retry_counts: dict[int, int] = {i: 0 for i in range(len(configs))}

    def _worker(config_index: int, config: RunConfig) -> tuple[int, RunStatus]:
        """Execute a single simulation with queue gating."""
        queue.acquire()
        try:
            status = run_simulation(config, env=env)
            save_run(status)
            return config_index, status
        finally:
            queue.release()

    # Initial submission
    with ThreadPoolExecutor(max_workers=max_parallel) as executor:
        # Map of future -> config_index
        future_to_index: dict[Future, int] = {}
        for i, config in enumerate(configs):
            future = executor.submit(_worker, i, config)
            future_to_index[future] = i

        # Process completions + retry logic
        while future_to_index:
            done_futures = []
            retries_to_submit: list[tuple[int, RunConfig]] = []

            for future in as_completed(future_to_index):
                config_index = future_to_index[future]
                try:
                    idx, status = future.result()
                except Exception as exc:
                    # Unexpected error in worker
                    logger.error(
                        "Worker exception for config %d: %s", config_index, exc
                    )
                    status = RunStatus(
                        run_id=f"error-{config_index}",
                        state=RunState.FAILED,
                        opi_path=configs[config_index].opi_path,
                        output_dir=configs[config_index].output_dir,
                        error_message=str(exc),
                    )
                    idx = config_index

                done_futures.append(future)

                if (
                    status.state == RunState.FAILED
                    and is_license_failure(status.error_message)
                    and retry_counts[idx] < max_retries
                ):
                    # Schedule retry
                    retry_counts[idx] += 1
                    attempt = retry_counts[idx]
                    backoff = 5 * (2 ** (attempt - 1))
                    logger.warning(
                        "License failure for config %d, retry %d/%d after %ds backoff",
                        idx,
                        attempt,
                        max_retries,
                        backoff,
                    )
                    time.sleep(backoff)
                    retries_to_submit.append((idx, configs[idx]))
                else:
                    # Final result (success or non-retriable failure or max retries)
                    results[idx] = status
                    if status.state == RunState.COMPLETED:
                        logger.info("Config %d completed successfully", idx)
                    else:
                        logger.warning(
                            "Config %d failed: %s", idx, status.error_message
                        )

            # Clear done futures from the map
            for f in done_futures:
                del future_to_index[f]

            # Submit retries (after clearing done futures to prevent deadlock)
            for idx, config in retries_to_submit:
                future = executor.submit(_worker, idx, config)
                future_to_index[future] = idx

    elapsed = time.monotonic() - start_time

    # Build ordered results list
    statuses = [results[i] for i in range(len(configs))]

    logger.info("Batch complete: %d configs in %.1fs", len(configs), elapsed)

    return BatchResult(
        configs=list(configs),
        statuses=statuses,
        sweep_params=None,
        total_elapsed_seconds=elapsed,
    )
