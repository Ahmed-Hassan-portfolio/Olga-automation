"""OLGA Automation CLI - mirrors all 20 MCP tools as CLI commands."""

import json
import sys
from pathlib import Path
from typing import Optional

import typer

from olga_automation.mcp_server.serialization import OlgaEncoder, serialize_result

app = typer.Typer(
    name="olga",
    help="OLGA Automation CLI - mirrors all MCP tools as CLI commands",
    no_args_is_help=True,
)

model_app = typer.Typer(help="Model inspection tools", no_args_is_help=True)
modify_app = typer.Typer(help="Model modification tools", no_args_is_help=True)
execute_app = typer.Typer(help="Execution and results tools", no_args_is_help=True)
batch_app = typer.Typer(help="Batch execution tools", no_args_is_help=True)

app.add_typer(model_app, name="model")
app.add_typer(modify_app, name="modify")
app.add_typer(execute_app, name="execute")
app.add_typer(batch_app, name="batch")


# ---------------------------------------------------------------------------
# Group 1: model
# ---------------------------------------------------------------------------


@model_app.command("read-case-summary")
def read_case_summary(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
) -> None:
    """Parse an OLGA .opi model file and return a structured summary."""
    try:
        from olga_automation.opi_parser.reader import get_model_summary

        summary = get_model_summary(Path(opi_path))
        print(serialize_result(summary))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@model_app.command("get-parameter")
def get_parameter(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    tag: str = typer.Option(..., help="Keyword tag, e.g. 'OPTIONS_0'"),
    key_name: str = typer.Option(..., "--key-name", help="Key name, e.g. 'ENDTIME'"),
) -> None:
    """Read a specific parameter value from a keyword in the .opi file."""
    try:
        from olga_automation.exceptions import KeywordNotFoundError
        from olga_automation.opi_parser.reader import get_parameter as _get_parameter

        result = _get_parameter(Path(opi_path), tag, key_name)

        if result is None:
            print(json.dumps({"error": f"Key '{key_name}' not found on keyword '{tag}'"}))
            sys.exit(1)

        print(serialize_result(result))

    except KeywordNotFoundError as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@model_app.command("list-keywords")
def list_keywords(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    keyword_type: Optional[str] = typer.Option(None, "--keyword-type", help="Filter by keyword type"),
    no_ncs: bool = typer.Option(False, "--no-ncs", help="Exclude network components"),
) -> None:
    """List all keywords in the .opi file, optionally filtered by type."""
    try:
        from olga_automation.opi_parser.reader import list_keywords as _list_keywords

        keywords = _list_keywords(Path(opi_path), keyword_type, include_ncs=not no_ncs)
        print(serialize_result(keywords))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@model_app.command("get-output-config")
def get_output_config(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
) -> None:
    """Get the current output configuration from the .opi file."""
    try:
        from olga_automation.opi_parser.reader import get_output_configuration

        result = get_output_configuration(Path(opi_path))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Group 2: modify
# ---------------------------------------------------------------------------


@modify_app.command("set-parameter")
def set_parameter(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    tag: str = typer.Option(..., help="Keyword tag, e.g. 'OPTIONS_0'"),
    key_name: str = typer.Option(..., "--key-name", help="Key name, e.g. 'ENDTIME'"),
    new_values: str = typer.Option(..., "--new-values", help="JSON array of values, e.g. '[\"100\"]'"),
    unit: Optional[str] = typer.Option(None, help="New unit, e.g. 'kg/s'"),
) -> None:
    """Modify a parameter value in an OLGA .opi model file."""
    try:
        from olga_automation.opi_parser.writer import set_parameter as _set_parameter

        values_list = json.loads(new_values)
        _set_parameter(Path(opi_path), tag, key_name, values_list, unit)

        print(json.dumps({
            "status": "ok",
            "message": f"Set {key_name} on {tag} to {values_list}",
        }))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON for --new-values: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@modify_app.command("set-output-variables")
def set_output_variables(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    trend_vars: Optional[str] = typer.Option(None, "--trend-vars", help="JSON list of trend variable dicts"),
    profile_vars: Optional[str] = typer.Option(None, "--profile-vars", help="JSON list of profile variable dicts"),
    flowpath_tag: Optional[str] = typer.Option(None, "--flowpath-tag", help="Target flowpath tag"),
) -> None:
    """Configure what variables OLGA records during simulation."""
    try:
        from olga_automation.opi_parser.output_config import (
            set_output_variables as _set_output_variables,
        )

        parsed_trend = json.loads(trend_vars) if trend_vars is not None else None
        parsed_profile = json.loads(profile_vars) if profile_vars is not None else None

        _set_output_variables(
            Path(opi_path),
            trend_vars=parsed_trend,
            profile_vars=parsed_profile,
            flowpath_tag=flowpath_tag,
        )

        trend_count = len(parsed_trend) if parsed_trend else 0
        profile_count = len(parsed_profile) if parsed_profile else 0

        print(json.dumps({
            "status": "ok",
            "message": f"Configured {trend_count} trend variable(s) and {profile_count} profile variable(s)",
        }))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@modify_app.command("create-variant")
def create_variant(
    base_opi: str = typer.Argument(..., help="Absolute path to the base .opi file"),
    output_opi: str = typer.Argument(..., help="Absolute path for the new variant file"),
    modifications: str = typer.Option(..., help="JSON list of modification dicts"),
    pvt_file: Optional[str] = typer.Option(None, "--pvt-file", help="Path to PVT fluid property file"),
) -> None:
    """Create a variant .opi file from a base model with parameter modifications."""
    try:
        from olga_automation.opi_parser.writer import create_variant as _create_variant

        mods = json.loads(modifications)
        variant_path = _create_variant(
            Path(base_opi), Path(output_opi), mods, pvt_file=pvt_file,
        )

        print(json.dumps({"status": "ok", "variant_path": str(variant_path)}))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON for --modifications: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@modify_app.command("validate-model")
def validate_model(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
) -> None:
    """Validate an OLGA .opi model file using OLGA's validation."""
    try:
        from olga_automation.opi_parser.validator import validate_opi

        result = validate_opi(Path(opi_path))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@modify_app.command("add-keyword")
def add_keyword(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    keyword_type: str = typer.Argument(..., help="Keyword type, e.g. 'SOURCE', 'VALVE'"),
    keys: Optional[str] = typer.Option(None, help="JSON dict of key-value data"),
    parent_tag: Optional[str] = typer.Option(None, "--parent-tag", help="Parent scope tag"),
    output_vars: Optional[str] = typer.Option(None, "--output-vars", help="JSON list for TRENDDATA/PROFILEDATA"),
    nc_type: Optional[str] = typer.Option(None, "--nc-type", help="NC type: FLOWPATH, NODE, ANNULUS"),
    nc_label: Optional[str] = typer.Option(None, "--nc-label", help="Label for new NC"),
) -> None:
    """Add a new keyword or network component to an OLGA .opi model file."""
    try:
        from olga_automation.opi_parser.writer import (
            add_keyword as _add_keyword,
            add_network_component as _add_network_component,
        )

        parsed_keys = json.loads(keys) if keys is not None else None
        parsed_output_vars = json.loads(output_vars) if output_vars is not None else None

        if nc_type is not None:
            initial_keywords = None
            if keyword_type:
                initial_keywords = [{
                    "keyword_type": keyword_type,
                    "keys": parsed_keys,
                    "output_vars": parsed_output_vars,
                }]
            tag = _add_network_component(
                Path(opi_path),
                nc_type,
                nc_label or nc_type,
                initial_keywords=initial_keywords,
            )
            print(json.dumps({
                "status": "ok",
                "tag": tag,
                "message": f"Added {nc_type} with tag {tag}",
            }))
        else:
            if not keyword_type or not keyword_type.strip():
                print(json.dumps({
                    "status": "error",
                    "message": "keyword_type must be a non-empty string",
                }))
                sys.exit(1)

            tag = _add_keyword(
                Path(opi_path), keyword_type, parsed_keys, parent_tag, parsed_output_vars,
            )
            print(json.dumps({
                "status": "ok",
                "tag": tag,
                "message": f"Added {keyword_type} with tag {tag}",
            }))

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@modify_app.command("remove-keyword")
def remove_keyword(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    tag: str = typer.Option(..., help="Tag of the keyword or NC to remove"),
    is_nc: bool = typer.Option(False, "--is-nc", help="Remove a network component instead of a keyword"),
) -> None:
    """Remove a keyword or network component from an OLGA .opi model file."""
    try:
        from olga_automation.opi_parser.writer import (
            remove_keyword as _remove_keyword,
            remove_network_component as _remove_network_component,
        )

        if is_nc:
            success = _remove_network_component(Path(opi_path), tag)
        else:
            success = _remove_keyword(Path(opi_path), tag)

        if success:
            print(json.dumps({
                "status": "ok",
                "message": f"Removed {'NC' if is_nc else 'keyword'} {tag}",
            }))
        else:
            print(json.dumps({
                "status": "not_found",
                "message": f"{'NC' if is_nc else 'Keyword'} '{tag}' not found",
            }))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Group 3: execute
# ---------------------------------------------------------------------------


@execute_app.command("run-simulation")
def run_simulation_cmd(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for simulation output files"),
    n_threads: int = typer.Option(1, "--n-threads", help="Number of OLGA threads"),
    no_tpl: bool = typer.Option(False, "--no-tpl", help="Skip .tpl generation"),
    no_ppl: bool = typer.Option(False, "--no-ppl", help="Skip .ppl generation"),
    no_out: bool = typer.Option(False, "--no-out", help="Skip .out generation"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Max simulation time in seconds"),
    pvt_file: Optional[str] = typer.Option(None, "--pvt-file", help="Path to PVT file"),
) -> None:
    """Run a single OLGA simulation synchronously (blocks until done)."""
    try:
        from olga_automation.execution_manager.models import RunConfig
        from olga_automation.execution_manager.run_tracker import save_run
        from olga_automation.execution_manager.runner import (
            run_simulation as _run_simulation,
        )

        config = RunConfig(
            opi_path=Path(opi_path),
            output_dir=Path(output_dir),
            n_threads=n_threads,
            generate_tpl=not no_tpl,
            generate_ppl=not no_ppl,
            generate_out=not no_out,
            timeout_seconds=timeout,
        )

        status = _run_simulation(config, pvt_file=pvt_file)
        save_run(status)
        print(json.dumps(status.to_dict(), indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("run-simulation-async")
def run_simulation_async_cmd(
    opi_path: str = typer.Argument(..., help="Absolute path to the .opi file"),
    output_dir: str = typer.Option(..., "--output-dir", help="Directory for simulation output files"),
    n_threads: int = typer.Option(1, "--n-threads", help="Number of OLGA threads"),
    no_tpl: bool = typer.Option(False, "--no-tpl", help="Skip .tpl generation"),
    no_ppl: bool = typer.Option(False, "--no-ppl", help="Skip .ppl generation"),
    no_out: bool = typer.Option(False, "--no-out", help="Skip .out generation"),
    timeout: Optional[int] = typer.Option(None, "--timeout", help="Max simulation time in seconds"),
    pvt_file: Optional[str] = typer.Option(None, "--pvt-file", help="Path to PVT file"),
) -> None:
    """Launch an OLGA simulation in the background and return immediately with a run_id."""
    try:
        from olga_automation.execution_manager.models import RunConfig
        from olga_automation.execution_manager.runner import (
            run_simulation_async as _run_simulation_async,
        )

        config = RunConfig(
            opi_path=Path(opi_path),
            output_dir=Path(output_dir),
            n_threads=n_threads,
            generate_tpl=not no_tpl,
            generate_ppl=not no_ppl,
            generate_out=not no_out,
            timeout_seconds=timeout,
        )

        status = _run_simulation_async(config, pvt_file=pvt_file)
        print(json.dumps(status.to_dict(), indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("get-run-status")
def get_run_status_cmd(
    run_id: str = typer.Argument(..., help="The run ID to check"),
) -> None:
    """Check the current status of a simulation run."""
    try:
        from olga_automation.execution_manager.run_tracker import (
            get_run_status as _get_run_status_persisted,
        )
        from olga_automation.execution_manager.runner import get_run_result

        # Check in-memory first (active async runs)
        status = get_run_result(run_id)

        # Fall back to persisted metadata in runs/ directory
        if status is None:
            runs_dir = Path("runs")
            if runs_dir.is_dir():
                status = _get_run_status_persisted(run_id, runs_dir)

        if status is None:
            print(json.dumps({"error": f"Run '{run_id}' not found"}))
            sys.exit(1)

        print(json.dumps(status.to_dict(), indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("cancel-run")
def cancel_run_cmd(
    run_id: str = typer.Argument(..., help="The run ID to cancel"),
) -> None:
    """Cancel a running simulation by killing its subprocess."""
    try:
        from olga_automation.execution_manager.runner import cancel_run as _cancel_run

        cancelled = _cancel_run(run_id)
        print(json.dumps({"cancelled": cancelled, "run_id": run_id}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("parse-trend-data")
def parse_trend_data_cmd(
    tpl_path: str = typer.Argument(..., help="Absolute path to the .tpl file"),
    variables: Optional[str] = typer.Option(None, "--variables", help="Comma-separated variable names, e.g. PT,TM"),
    t_start: Optional[float] = typer.Option(None, "--t-start", help="Start of time window (seconds)"),
    t_end: Optional[float] = typer.Option(None, "--t-end", help="End of time window (seconds)"),
    summary_only: bool = typer.Option(False, "--summary-only", help="Return metadata and stats only"),
) -> None:
    """Parse a .tpl trend data file into structured JSON."""
    try:
        from olga_automation.output_parser.exporters import export_to_json
        from olga_automation.output_parser.models import TrendData
        from olga_automation.output_parser.tpl_parser import parse_tpl

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
            var_list = [v.strip() for v in variables.split(",")]
            filtered_vars = {}
            for key, vs in trend_data.variables.items():
                if vs.name in var_list:
                    filtered_vars[key] = vs
            trend_data = TrendData(
                olga_version=trend_data.olga_version,
                time_unit=trend_data.time_unit,
                time=trend_data.time,
                variables=filtered_vars,
                metadata=trend_data.metadata,
            )

        # Summary mode
        if summary_only:
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
            print(json.dumps(summary, cls=OlgaEncoder, indent=2))
            return

        result = export_to_json(trend_data)
        print(json.dumps(result, cls=OlgaEncoder, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("parse-profile-data")
def parse_profile_data_cmd(
    ppl_path: str = typer.Argument(..., help="Absolute path to the .ppl file"),
    variables: Optional[str] = typer.Option(None, "--variables", help="Comma-separated variable names, e.g. PT,TM"),
    timestep_indices: Optional[str] = typer.Option(None, "--timestep-indices", help="Comma-separated timestep indices, e.g. 0,1,2"),
    summary_only: bool = typer.Option(False, "--summary-only", help="Return metadata and stats only"),
) -> None:
    """Parse a .ppl profile data file into structured JSON."""
    try:
        import numpy as np

        from olga_automation.output_parser.exporters import export_to_json
        from olga_automation.output_parser.models import ProfileData, ProfileVariable
        from olga_automation.output_parser.ppl_parser import parse_ppl

        profile_data = parse_ppl(Path(ppl_path))

        # Apply variable name filter
        if variables is not None:
            var_list = [v.strip() for v in variables.split(",")]
            filtered_vars = {}
            for key, pv in profile_data.variables.items():
                if pv.name in var_list:
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
            idx = np.array([int(i.strip()) for i in timestep_indices.split(",")])
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
            print(json.dumps(summary, cls=OlgaEncoder, indent=2))
            return

        result = export_to_json(profile_data)
        print(json.dumps(result, cls=OlgaEncoder, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@execute_app.command("get-simulation-log")
def get_simulation_log_cmd(
    out_path: str = typer.Argument(..., help="Absolute path to the .out file"),
) -> None:
    """Parse a .out simulation log file."""
    try:
        from olga_automation.output_parser.out_parser import parse_out

        result = parse_out(Path(out_path))
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


# ---------------------------------------------------------------------------
# Group 4: batch
# ---------------------------------------------------------------------------


@batch_app.command("build-sweep")
def build_sweep_cmd(
    base_opi: str = typer.Argument(..., help="Absolute path to the base .opi file"),
    sweep_params: str = typer.Option(..., "--sweep-params", help="JSON dict of sweep parameters"),
    output_base_dir: str = typer.Option(..., "--output-base-dir", help="Base directory for sweep outputs"),
) -> None:
    """Build a parameter sweep matrix from parameter ranges."""
    try:
        from olga_automation.execution_manager.batch import build_sweep_matrix

        params = json.loads(sweep_params)
        configs = build_sweep_matrix(Path(base_opi), params, Path(output_base_dir))

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

        print(json.dumps(
            {
                "status": "ok",
                "configs": configs_data,
                "sweep_size": len(configs),
            },
            cls=OlgaEncoder,
            indent=2,
        ))
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON for --sweep-params: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@batch_app.command("run-batch")
def run_batch_cmd(
    configs_json: str = typer.Argument(..., help="JSON string of RunConfig list"),
    max_parallel: int = typer.Option(2, "--max-parallel", help="Maximum concurrent simulations"),
) -> None:
    """Execute a batch of simulations."""
    try:
        from olga_automation.execution_manager.batch import run_batch as _run_batch
        from olga_automation.execution_manager.models import RunConfig

        configs_data = json.loads(configs_json)

        # Handle both formats: {"configs": [...]} or [...]
        if isinstance(configs_data, dict) and "configs" in configs_data:
            configs_list = configs_data["configs"]
        else:
            configs_list = configs_data

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

        batch_result = _run_batch(configs, max_parallel=max_parallel)

        result_data = {
            "status": "ok",
            "total_runs": len(batch_result.statuses),
            "completed": sum(1 for s in batch_result.statuses if s.state == "completed"),
            "failed": sum(1 for s in batch_result.statuses if s.state == "failed"),
            "total_elapsed_seconds": batch_result.total_elapsed_seconds,
            "statuses": [s.to_dict() for s in batch_result.statuses],
        }

        print(json.dumps(result_data, cls=OlgaEncoder, indent=2))

    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid configs JSON: {e}"}))
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


@batch_app.command("compare-runs")
def compare_runs_cmd(
    run_dirs: str = typer.Option(..., "--run-dirs", help="Comma-separated list of run directory paths"),
    variable: str = typer.Option(..., help="Variable name to compare, e.g. 'PT'"),
    position: str = typer.Option(..., help="Position label, e.g. 'WH'"),
) -> None:
    """Compare results across multiple simulation runs."""
    try:
        from olga_automation.output_parser.extractors import (
            compare_runs as _compare_runs,
        )

        dirs = [Path(d.strip()) for d in run_dirs.split(",")]
        result = _compare_runs(dirs, variable, position)
        print(json.dumps(result, cls=OlgaEncoder, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
