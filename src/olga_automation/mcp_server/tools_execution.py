"""Execution & results tools: run_simulation, get_run_status, cancel_run, parse_trend_data, etc.

Parsing tools use async timeout wrappers (30s) and auto-summarization when
responses exceed safe stdio pipe buffer sizes. See docs/MCP_STDIO_STALLING_FIX.md.
"""

import json
import logging
from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger("olga-automation.tools.execution")

# Maximum response size in bytes before auto-summarization.
# Trend/profile data can be enormous; use a higher threshold than model tools.
_MAX_DATA_RESPONSE_BYTES = 8192


def register_execution_tools(mcp):
    """Register 7 execution and results tools.

    Execution control:
    - run_simulation: Run synchronously
    - run_simulation_async: Launch in background
    - get_run_status: Poll for completion
    - cancel_run: Kill running simulation

    Results parsing:
    - parse_trend_data: Parse .tpl files
    - parse_profile_data: Parse .ppl files
    - get_simulation_log: Parse .out files
    """

    @mcp.tool()
    async def run_simulation(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to execute")
        ],
        output_dir: Annotated[
            str, Field(description="Directory for simulation output files")
        ],
        n_threads: Annotated[int, Field(description="Number of OLGA threads (default 1)")] = 1,
        generate_tpl: Annotated[
            bool, Field(description="Generate .tpl trend output (default true)")
        ] = True,
        generate_ppl: Annotated[
            bool, Field(description="Generate .ppl profile output (default true)")
        ] = True,
        generate_out: Annotated[
            bool, Field(description="Generate .out summary output (default true)")
        ] = True,
        timeout_seconds: Annotated[
            int | None,
            Field(description="Max simulation time in seconds, or null for no limit"),
        ] = None,
        pvt_file: Annotated[
            str | None,
            Field(
                description=(
                    "Path to PVT fluid property file (.tab). Required when "
                    "the .opi model's PVT path cannot be resolved. The file "
                    "will be copied next to the .opi file."
                )
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Run a single OLGA simulation synchronously.

        Blocks until completion. For long simulations, use run_simulation_async instead.
        Requires OLGA to be installed.

        Examples
        --------
        Run with all default settings:
        >>> run_simulation("model.opi", "runs/run_001")

        Run with custom threads and timeout:
        >>> run_simulation("model.opi", "runs/run_002", n_threads=4, timeout_seconds=3600)

        Run with explicit PVT file:
        >>> run_simulation("model.opi", "runs/run_003", pvt_file="C:/pvt/fluid.tab")
        """
        try:
            from olga_automation.execution_manager.runner import (
                run_simulation as _run_simulation,
            )
            from olga_automation.execution_manager.models import RunConfig
            from olga_automation.execution_manager.run_tracker import save_run

            config = RunConfig(
                opi_path=Path(opi_path),
                output_dir=Path(output_dir),
                n_threads=n_threads,
                generate_tpl=generate_tpl,
                generate_ppl=generate_ppl,
                generate_out=generate_out,
                timeout_seconds=timeout_seconds,
            )

            # Run in a worker thread to avoid blocking the MCP event loop.
            # FastMCP calls sync tools on the event loop directly; a blocked
            # event loop prevents ALL other MCP requests from being processed.
            status = await anyio.to_thread.run_sync(
                partial(_run_simulation, config, pvt_file=pvt_file)
            )

            # Save run metadata to disk
            save_run(status)

            return json.dumps(status.to_dict(), indent=2)

        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"PVT/file error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception(f"Error in run_simulation: {e}")
            return json.dumps({"error": f"Failed to run simulation: {e}"})

    @mcp.tool()
    async def run_simulation_async(
        opi_path: Annotated[
            str, Field(description="Absolute path to the .opi file to execute")
        ],
        output_dir: Annotated[
            str, Field(description="Directory for simulation output files")
        ],
        n_threads: Annotated[int, Field(description="Number of OLGA threads (default 1)")] = 1,
        generate_tpl: Annotated[
            bool, Field(description="Generate .tpl trend output (default true)")
        ] = True,
        generate_ppl: Annotated[
            bool, Field(description="Generate .ppl profile output (default true)")
        ] = True,
        generate_out: Annotated[
            bool, Field(description="Generate .out summary output (default true)")
        ] = True,
        timeout_seconds: Annotated[
            int | None,
            Field(description="Max simulation time in seconds, or null for no limit"),
        ] = None,
        pvt_file: Annotated[
            str | None,
            Field(
                description=(
                    "Path to PVT fluid property file (.tab). Required when "
                    "the .opi model's PVT path cannot be resolved. The file "
                    "will be copied next to the .opi file."
                )
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Launch an OLGA simulation in the background and return immediately with a run_id.

        Use get_run_status to poll for completion.

        Examples
        --------
        >>> result = run_simulation_async("model.opi", "runs/run_003")
        >>> run_id = json.loads(result)["run_id"]
        >>> # ... later ...
        >>> status = get_run_status(run_id)
        """
        try:
            from olga_automation.execution_manager.runner import (
                run_simulation_async as _run_simulation_async,
            )
            from olga_automation.execution_manager.models import RunConfig

            config = RunConfig(
                opi_path=Path(opi_path),
                output_dir=Path(output_dir),
                n_threads=n_threads,
                generate_tpl=generate_tpl,
                generate_ppl=generate_ppl,
                generate_out=generate_out,
                timeout_seconds=timeout_seconds,
            )

            # Offload to worker thread — _run_simulation_async spawns its own
            # background thread internally, but constructing RunConfig and
            # calling detect_olga_install() can still do blocking I/O.
            status = await anyio.to_thread.run_sync(
                partial(_run_simulation_async, config, pvt_file=pvt_file)
            )

            return json.dumps(status.to_dict(), indent=2)

        except (FileNotFoundError, ValueError) as e:
            logger.warning(f"PVT/file error: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception(f"Error in run_simulation_async: {e}")
            return json.dumps({"error": f"Failed to launch async simulation: {e}"})

    @mcp.tool()
    def get_run_status(
        run_id: Annotated[
            str,
            Field(
                description="The run ID returned by run_simulation or run_simulation_async"
            ),
        ],
        ctx: Context = None,
    ) -> str:
        """Check the current status of a simulation run.

        Returns state (queued/running/completed/failed/cancelled), timing, and output files.

        Examples
        --------
        >>> get_run_status("20260208_120000_abc123")
        """
        try:
            from olga_automation.execution_manager.runner import get_run_result
            from olga_automation.execution_manager.run_tracker import (
                get_run_status as _get_run_status,
            )

            # First check in-memory for active async runs
            status = get_run_result(run_id)

            # If not in memory, check persisted metadata
            if status is None and ctx and hasattr(ctx, "request_context"):
                runs_dir = ctx.request_context.lifespan_context.runs_dir
                if runs_dir:
                    status = _get_run_status(run_id, Path(runs_dir))

            if status is None:
                return json.dumps({"error": f"Run '{run_id}' not found"})

            return json.dumps(status.to_dict(), indent=2)

        except Exception as e:
            logger.exception(f"Error in get_run_status: {e}")
            return json.dumps({"error": f"Failed to get run status: {e}"})

    @mcp.tool()
    def cancel_run(
        run_id: Annotated[str, Field(description="The run ID to cancel")],
        ctx: Context = None,
    ) -> str:
        """Cancel a running simulation by killing its subprocess.

        Examples
        --------
        >>> cancel_run("20260208_120000_abc123")
        """
        try:
            from olga_automation.execution_manager.runner import (
                cancel_run as _cancel_run,
            )

            cancelled = _cancel_run(run_id)

            return json.dumps({"cancelled": cancelled, "run_id": run_id})

        except Exception as e:
            logger.exception(f"Error in cancel_run: {e}")
            return json.dumps({"error": f"Failed to cancel run: {e}"})

    @mcp.tool()
    async def parse_trend_data(
        tpl_path: Annotated[
            str, Field(description="Absolute path to the .tpl trend data file")
        ],
        variables: Annotated[
            list[str] | None,
            Field(description="Filter to specific variables (e.g. ['PT', 'TM']). None = all variables."),
        ] = None,
        t_start: Annotated[
            float | None,
            Field(description="Start of time window filter (seconds). None = from beginning."),
        ] = None,
        t_end: Annotated[
            float | None,
            Field(description="End of time window filter (seconds). None = to end."),
        ] = None,
        summary_only: Annotated[
            bool,
            Field(description="If true, return metadata and variable list only, no data arrays"),
        ] = False,
        ctx: Context = None,
    ) -> str:
        """Parse a .tpl trend data file from an OLGA simulation into structured JSON.

        Returns time series data with variable names, positions, and values.

        Examples
        --------
        >>> parse_trend_data("runs/run_001/output.tpl")
        """
        def _build_trend_summary(trend_data, auto_summarized=False):
            """Build a summary dict from trend data."""
            from olga_automation.mcp_server.serialization import OlgaEncoder

            var_summaries = []
            for key, vs in trend_data.variables.items():
                var_summaries.append({
                    "key": key,
                    "name": vs.name,
                    "position": vs.position,
                    "unit": vs.unit,
                    "min": float(vs.values.min()) if len(vs.values) > 0 else None,
                    "max": float(vs.values.max()) if len(vs.values) > 0 else None,
                    "mean": float(vs.values.mean()) if len(vs.values) > 0 else None,
                })
            summary = {
                "olga_version": trend_data.olga_version,
                "time_unit": trend_data.time_unit,
                "metadata": trend_data.metadata,
                "time_range": (
                    [float(trend_data.time[0]), float(trend_data.time[-1])]
                    if len(trend_data.time) > 0
                    else []
                ),
                "n_timesteps": len(trend_data.time),
                "variables": var_summaries,
            }
            if auto_summarized:
                summary["auto_summarized"] = True
                summary["hint"] = (
                    "Full data exceeded safe response size. "
                    "Use summary_only=True explicitly, or filter with variables/time window."
                )
            return json.dumps(summary, cls=OlgaEncoder, indent=2)

        def _sync():
            from olga_automation.output_parser.tpl_parser import parse_tpl
            from olga_automation.output_parser.exporters import export_to_json
            from olga_automation.output_parser.models import TrendData
            from olga_automation.mcp_server.serialization import OlgaEncoder

            trend_data = parse_tpl(Path(tpl_path))

            # Apply time window filter
            if t_start is not None or t_end is not None:
                from olga_automation.output_parser.extractors import extract_time_window

                trend_data = extract_time_window(
                    trend_data,
                    t_start if t_start is not None else 0.0,
                    t_end if t_end is not None else float("inf"),
                )

            # Apply variable name filter
            if variables is not None:
                filtered_vars = {}
                for key, vs in trend_data.variables.items():
                    if vs.name in variables:
                        filtered_vars[key] = vs
                trend_data = TrendData(
                    olga_version=trend_data.olga_version,
                    time_unit=trend_data.time_unit,
                    time=trend_data.time,
                    variables=filtered_vars,
                    metadata=trend_data.metadata,
                )

            # Summary mode: return metadata + variable stats only
            if summary_only:
                return _build_trend_summary(trend_data)

            result = export_to_json(trend_data)
            serialized = json.dumps(result, cls=OlgaEncoder, indent=2)

            # Auto-summarize if response exceeds safe size
            if len(serialized) > _MAX_DATA_RESPONSE_BYTES:
                logger.info(
                    f"parse_trend_data: auto-summarizing ({len(serialized)} bytes > {_MAX_DATA_RESPONSE_BYTES})"
                )
                return _build_trend_summary(trend_data, auto_summarized=True)

            return serialized

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
                "hint": "Use summary_only=True or filter with variables/time window.",
            })
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in parse_trend_data: {e}")
            return json.dumps({"error": f"Failed to parse trend data: {e}"})

    @mcp.tool()
    async def parse_profile_data(
        ppl_path: Annotated[
            str, Field(description="Absolute path to the .ppl profile data file")
        ],
        variables: Annotated[
            list[str] | None,
            Field(description="Filter to specific variables (e.g. ['PT', 'TM']). None = all variables."),
        ] = None,
        timestep_indices: Annotated[
            list[int] | None,
            Field(description="Only include specific timestep indices. None = all timesteps."),
        ] = None,
        summary_only: Annotated[
            bool,
            Field(description="If true, return metadata and variable list only, no data arrays"),
        ] = False,
        ctx: Context = None,
    ) -> str:
        """Parse a .ppl profile data file from an OLGA simulation into structured JSON.

        Returns spatial profile data with variable names, branches, and position arrays.

        Examples
        --------
        >>> parse_profile_data("runs/run_001/output.ppl")
        """
        def _build_profile_summary(profile_data, auto_summarized=False):
            """Build a summary dict from profile data."""
            from olga_automation.mcp_server.serialization import OlgaEncoder

            var_summaries = []
            for key, pv in profile_data.variables.items():
                var_summaries.append({
                    "key": key,
                    "name": pv.name,
                    "unit": pv.unit,
                    "branch": pv.branch,
                    "n_positions": len(pv.positions),
                    "n_timesteps": pv.data.shape[0] if len(pv.data.shape) == 2 else 0,
                })
            summary = {
                "olga_version": profile_data.olga_version,
                "time_unit": profile_data.time_unit,
                "metadata": profile_data.metadata,
                "timestamps": profile_data.timestamps.tolist() if len(profile_data.timestamps) > 0 else [],
                "n_timesteps": len(profile_data.timestamps),
                "variables": var_summaries,
            }
            if auto_summarized:
                summary["auto_summarized"] = True
                summary["hint"] = (
                    "Full data exceeded safe response size. "
                    "Use summary_only=True explicitly, or filter with variables/timestep_indices."
                )
            return json.dumps(summary, cls=OlgaEncoder, indent=2)

        def _sync():
            from olga_automation.output_parser.ppl_parser import parse_ppl
            from olga_automation.output_parser.exporters import export_to_json
            from olga_automation.output_parser.models import ProfileData, ProfileVariable
            from olga_automation.mcp_server.serialization import OlgaEncoder

            import numpy as np

            profile_data = parse_ppl(Path(ppl_path))

            # Apply variable name filter
            if variables is not None:
                filtered_vars = {}
                for key, pv in profile_data.variables.items():
                    if pv.name in variables:
                        filtered_vars[key] = pv
                profile_data = ProfileData(
                    olga_version=profile_data.olga_version,
                    time_unit=profile_data.time_unit,
                    timestamps=profile_data.timestamps,
                    variables=filtered_vars,
                    metadata=profile_data.metadata,
                )

            # Apply timestep index filter
            if timestep_indices is not None:
                idx = np.array(timestep_indices)
                filtered_vars = {}
                for key, pv in profile_data.variables.items():
                    filtered_vars[key] = ProfileVariable(
                        name=pv.name,
                        unit=pv.unit,
                        branch=pv.branch,
                        positions=pv.positions,
                        data=pv.data[idx] if len(pv.data) > 0 else pv.data,
                    )
                profile_data = ProfileData(
                    olga_version=profile_data.olga_version,
                    time_unit=profile_data.time_unit,
                    timestamps=profile_data.timestamps[idx] if len(profile_data.timestamps) > 0 else profile_data.timestamps,
                    variables=filtered_vars,
                    metadata=profile_data.metadata,
                )

            # Summary mode
            if summary_only:
                return _build_profile_summary(profile_data)

            result = export_to_json(profile_data)
            serialized = json.dumps(result, cls=OlgaEncoder, indent=2)

            # Auto-summarize if response exceeds safe size
            if len(serialized) > _MAX_DATA_RESPONSE_BYTES:
                logger.info(
                    f"parse_profile_data: auto-summarizing ({len(serialized)} bytes > {_MAX_DATA_RESPONSE_BYTES})"
                )
                return _build_profile_summary(profile_data, auto_summarized=True)

            return serialized

        try:
            with anyio.fail_after(30):
                return await anyio.to_thread.run_sync(_sync)
        except TimeoutError:
            return json.dumps({
                "error": "Tool timed out after 30s",
                "hint": "Use summary_only=True or filter with variables/timestep_indices.",
            })
        except FileNotFoundError as e:
            logger.warning(f"File not found: {e}")
            return json.dumps({"error": f"File not found: {e}"})
        except Exception as e:
            logger.exception(f"Error in parse_profile_data: {e}")
            return json.dumps({"error": f"Failed to parse profile data: {e}"})

    @mcp.tool()
    async def get_simulation_log(
        out_path: Annotated[
            str, Field(description="Absolute path to the .out simulation log file")
        ],
        ctx: Context = None,
    ) -> str:
        """Parse a .out simulation log file.

        Returns summary information including timing, warnings, and errors.

        Examples
        --------
        >>> get_simulation_log("runs/run_001/output.out")
        """
        def _sync():
            from olga_automation.output_parser.out_parser import parse_out

            result = parse_out(Path(out_path))
            return json.dumps(result, indent=2)

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
            logger.exception(f"Error in get_simulation_log: {e}")
            return json.dumps({"error": f"Failed to parse simulation log: {e}"})
