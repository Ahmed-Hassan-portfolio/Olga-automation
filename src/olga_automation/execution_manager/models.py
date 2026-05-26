"""Data models: RunConfig, RunStatus, RunState, BatchResult."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


class RunState:
    """Constants for simulation run states."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class RunConfig:
    """Configuration for a single OLGA simulation run.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to execute.
    output_dir : Path
        Directory for simulation output files.
    n_threads : int
        Number of threads for OLGA's internal parallelism.
    generate_tpl : bool
        Whether to generate .tpl (trend) output.
    generate_ppl : bool
        Whether to generate .ppl (profile) output.
    generate_out : bool
        Whether to generate .out (summary) output.
    timeout_seconds : int | None
        Maximum wall-clock time in seconds, or None for no limit.
    """

    opi_path: Path
    output_dir: Path
    n_threads: int = 1
    generate_tpl: bool = True
    generate_ppl: bool = True
    generate_out: bool = True
    timeout_seconds: int | None = None


@dataclass
class RunStatus:
    """Status and result of a simulation run.

    Parameters
    ----------
    run_id : str
        Unique identifier for this run.
    state : str
        Current state (use RunState constants).
    opi_path : Path
        Path to the .opi file that was executed.
    output_dir : Path
        Directory containing output files.
    start_time : datetime | None
        When the simulation started.
    end_time : datetime | None
        When the simulation finished.
    elapsed_seconds : float | None
        Wall-clock duration in seconds.
    return_code : int | None
        Process exit code (0 = success).
    error_message : str | None
        Error description if the run failed.
    output_files : dict | None
        Map of output type to file path (e.g. {"tpl": "path/to/file.tpl"}).
    """

    run_id: str
    state: str
    opi_path: Path
    output_dir: Path
    start_time: datetime | None = None
    end_time: datetime | None = None
    elapsed_seconds: float | None = None
    return_code: int | None = None
    error_message: str | None = None
    output_files: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:

        """Serialize to a JSON-compatible dictionary.

        Path objects are converted to strings.
        datetime objects are converted to ISO 8601 format strings.
        None values are preserved as None.

        Returns
        -------
        dict[str, Any]
            JSON-serializable dictionary.
        """
        return {
            "run_id": self.run_id,
            "state": self.state,
            "opi_path": str(self.opi_path),
            "output_dir": str(self.output_dir),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "elapsed_seconds": self.elapsed_seconds,
            "return_code": self.return_code,
            "error_message": self.error_message,
            "output_files": (
                {k: [str(p) for p in v] if isinstance(v, list) else str(v) for k, v in self.output_files.items()}
                if self.output_files else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RunStatus:
        """Deserialize from a dictionary (inverse of to_dict).

        String paths are converted back to Path objects.
        ISO 8601 datetime strings are converted back to datetime objects.

        Parameters
        ----------
        data : dict[str, Any]
            Dictionary as produced by to_dict().

        Returns
        -------
        RunStatus
            Reconstructed RunStatus instance.
        """
        return cls(
            run_id=data["run_id"],
            state=data["state"],
            opi_path=Path(data["opi_path"]),
            output_dir=Path(data["output_dir"]),
            start_time=(
                datetime.fromisoformat(data["start_time"])
                if data.get("start_time")
                else None
            ),
            end_time=(
                datetime.fromisoformat(data["end_time"])
                if data.get("end_time")
                else None
            ),
            elapsed_seconds=data.get("elapsed_seconds"),
            return_code=data.get("return_code"),
            error_message=data.get("error_message"),
            output_files=data.get("output_files"),
        )


@dataclass
class BatchResult:
    """Result of a batch execution run.

    Bundles the input configs with their corresponding statuses,
    along with optional sweep metadata and timing information.

    Parameters
    ----------
    configs : list[RunConfig]
        The RunConfigs that were executed.
    statuses : list[RunStatus]
        Final status for each config, in the same order as configs.
    sweep_params : dict | None
        Sweep parameters if this batch was generated by build_sweep_matrix.
    total_elapsed_seconds : float | None
        Wall-clock time for the entire batch in seconds.
    """

    configs: list[RunConfig]
    statuses: list[RunStatus]
    sweep_params: dict | None = None
    total_elapsed_seconds: float | None = None
