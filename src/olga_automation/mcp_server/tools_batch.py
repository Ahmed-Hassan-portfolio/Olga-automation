"""Batch tools: build_sweep, run_batch, compare_runs.

build_sweep and compare_runs use async timeout wrappers (30s).
run_batch is intentionally long-running and has no timeout.
See docs/MCP_STDIO_STALLING_FIX.md.
"""

import json
import logging
from pathlib import Path
from typing import Annotated

import anyio
from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger("olga-automation.tools.batch")


def register_batch_tools(mcp):
    """Register 3 batch execution tools.

    - build_sweep: Generate parameter sweep matrix
    - run_batch: Execute batch of simulations in parallel
    - compare_runs: Compare results across multiple runs
    """

    @mcp.tool()
    async def build_sweep(
        base_opi: Annotated[str, Field(description="Absolute path to the base .opi file")],
        sweep_params: Annotated[
            dict,
            Field(
                description="Parameter sweep definition: {'tag.key': ['val1', 'val2'], ...}"
            ),
        ],
        output_base_dir: Annotated[
            str, Field(description="Base directory for sweep output subdirectories")
        ],
        ctx: Context = None,
    ) -> str:
        """Build a parameter sweep matrix from parameter ranges.

        Creates variant .opi files for each combination and returns a list of RunConfig objects.

        Examples
        --------
        Two-parameter sweep:
        >>> build_sweep(
        ...     "base.opi",
        ...     {
        ...         "OPTIONS_0.ENDTIME": ["3600", "7200"],
        ...         "FLOWPATH_7.SOURCE_18.MASSFLOW": ["100", "150", "200"]
        ...     },
        ...     "runs/sweep_001"
        ... )
        """
        def _sync():
            from olga_automation.execution_manager.batch import build_sweep_matrix
            from olga_automation.mcp_server.serialization import OlgaEncoder

            configs = build_sweep_matrix(
                Path(base_opi), sweep_params, Path(output_base_dir)
            )

            # Serialize configs using OlgaEncoder (handles Path fields)
            configs_data = [
                {
                    "opi_path": str(cfg.opi_path),
                    "output_dir": str(cfg.output_dir),
                    "n_threads": cfg.n_threads,
                    "generate_tpl": cfg.generate_tpl,
                    "generate_ppl": cfg.generate_ppl,
                    "generate_out": cfg.generate_out,
                    "timeout_seconds": cfg.timeout_seconds,
                }
                for cfg in configs
            ]

            return json.dumps(
                {
                    "status": "ok",
                    "configs": configs_data,
                    "sweep_size": len(configs),
                },
                cls=OlgaEncoder,
                indent=2,
            )

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
            })
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in build_sweep: {e}")
            return json.dumps({"error": f"Failed to build sweep: {e}"})

    @mcp.tool()
    def run_batch(
        configs_json: Annotated[
            str,
            Field(description="JSON string of RunConfig list from build_sweep output"),
        ],
        max_parallel: Annotated[
            int, Field(description="Maximum concurrent simulations (default 2)")
        ] = 2,
        ctx: Context = None,
    ) -> str:
        """Execute a batch of simulations in parallel.

        Respects license limits and manages parallel execution. Returns results for all runs.

        Examples
        --------
        >>> sweep_result = build_sweep(...)
        >>> configs_json = json.loads(sweep_result)["configs"]
        >>> batch_result = run_batch(json.dumps(configs_json), max_parallel=2)
        """
        try:
            from olga_automation.execution_manager.batch import run_batch as _run_batch
            from olga_automation.execution_manager.models import RunConfig
            from olga_automation.mcp_server.serialization import OlgaEncoder

            # Parse configs from JSON
            configs_data = json.loads(configs_json)

            # Handle both formats: {"configs": [...]} or [...]
            if isinstance(configs_data, dict) and "configs" in configs_data:
                configs_list = configs_data["configs"]
            else:
                configs_list = configs_data

            # Reconstruct RunConfig objects
            configs = [
                RunConfig(
                    opi_path=Path(cfg["opi_path"]),
                    output_dir=Path(cfg["output_dir"]),
                    n_threads=cfg.get("n_threads", 1),
                    generate_tpl=cfg.get("generate_tpl", True),
                    generate_ppl=cfg.get("generate_ppl", True),
                    generate_out=cfg.get("generate_out", True),
                    timeout_seconds=cfg.get("timeout_seconds"),
                )
                for cfg in configs_list
            ]

            # Run batch
            batch_result = _run_batch(configs, max_parallel=max_parallel)

            # Serialize result
            result_data = {
                "status": "ok",
                "total_runs": len(batch_result.statuses),
                "completed": sum(
                    1 for s in batch_result.statuses if s.state == "completed"
                ),
                "failed": sum(1 for s in batch_result.statuses if s.state == "failed"),
                "total_elapsed_seconds": batch_result.total_elapsed_seconds,
                "statuses": [s.to_dict() for s in batch_result.statuses],
            }

            return json.dumps(result_data, cls=OlgaEncoder, indent=2)

        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON: {e}")
            return json.dumps({"error": f"Invalid configs JSON: {e}"})
        except Exception as e:
            logger.exception(f"Error in run_batch: {e}")
            return json.dumps({"error": f"Failed to run batch: {e}"})

    @mcp.tool()
    async def compare_runs(
        run_dirs: Annotated[
            list[str], Field(description="List of run output directory paths to compare")
        ],
        variable: Annotated[str, Field(description="Variable name to compare, e.g. 'PT'")],
        position: Annotated[
            str, Field(description="Position label to compare at, e.g. 'WH'")
        ],
        ctx: Context = None,
    ) -> str:
        """Compare results across multiple simulation runs.

        Extracts a specific variable at a position from each run and returns comparison data.

        Examples
        --------
        Compare pressure at wellhead across three runs:
        >>> compare_runs(
        ...     ["runs/run_001", "runs/run_002", "runs/run_003"],
        ...     "PT",
        ...     "WH"
        ... )
        """
        def _sync():
            from olga_automation.output_parser.extractors import (
                compare_runs as _compare_runs,
            )
            from olga_automation.mcp_server.serialization import OlgaEncoder

            result = _compare_runs(
                [Path(d) for d in run_dirs], variable, position
            )

            return json.dumps(result, cls=OlgaEncoder, indent=2)

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
            })
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except KeyError as e:
            logger.warning(f"Variable not found: {e}")
            return json.dumps({"error": f"Variable not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in compare_runs: {e}")
            return json.dumps({"error": f"Failed to compare runs: {e}"})
