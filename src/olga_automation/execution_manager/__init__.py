"""Execution Manager - Run OLGA simulations from Python."""

from olga_automation.execution_manager.batch import (
    build_sweep_matrix,
    run_batch,
)
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
from olga_automation.execution_manager.run_tracker import (
    METADATA_FILENAME,
    get_run_status,
    get_run_status_from_dir,
    list_runs,
    save_run,
)
from olga_automation.execution_manager.runner import (
    cancel_run,
    run_simulation,
    run_simulation_async,
)

__all__ = [
    "BatchResult",
    "LicenseAwareQueue",
    "METADATA_FILENAME",
    "RunConfig",
    "RunState",
    "RunStatus",
    "build_sweep_matrix",
    "cancel_run",
    "get_run_status",
    "get_run_status_from_dir",
    "is_license_failure",
    "list_runs",
    "run_batch",
    "run_simulation",
    "run_simulation_async",
    "save_run",
]
