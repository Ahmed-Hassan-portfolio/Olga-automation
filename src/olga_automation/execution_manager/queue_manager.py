"""License-aware semaphore for parallel run management.

Provides LicenseAwareQueue for limiting concurrent OLGA simulations
based on available FlexLM licenses, and is_license_failure for detecting
license-related errors in subprocess stderr output.
"""

from __future__ import annotations

import logging
import re
import threading

logger = logging.getLogger(__name__)

# Compiled regex patterns for detecting FlexLM license failures.
# Each pattern uses re.IGNORECASE for case-insensitive matching.
LICENSE_FAILURE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"license", re.IGNORECASE),
    re.compile(r"FLEXlm", re.IGNORECASE),
    re.compile(r"FLEXnet", re.IGNORECASE),
    re.compile(r"Licensed number of users already reached", re.IGNORECASE),
    re.compile(r"Cannot connect to license server", re.IGNORECASE),
    re.compile(r"No such feature exists", re.IGNORECASE),
    re.compile(r"License server.*down", re.IGNORECASE),
]


class LicenseAwareQueue:
    """Semaphore-based queue that limits concurrent OLGA simulation slots.

    Wraps threading.Semaphore to limit how many simulations can run
    simultaneously, matching the number of available FlexLM licenses.

    Usage::

        queue = LicenseAwareQueue(max_parallel=4)

        # As context manager (preferred):
        with queue:
            run_simulation(...)

        # Manual acquire/release:
        queue.acquire()
        try:
            run_simulation(...)
        finally:
            queue.release()
    """

    def __init__(self, max_parallel: int = 1) -> None:
        """Initialize with a maximum number of concurrent slots.

        Args:
            max_parallel: Maximum number of concurrent simulations.
                Must be >= 1.

        Raises:
            ValueError: If max_parallel < 1.
        """
        if max_parallel < 1:
            raise ValueError(
                f"max_parallel must be >= 1, got {max_parallel}"
            )
        self._max_parallel = max_parallel
        self._semaphore = threading.Semaphore(max_parallel)
        self._lock = threading.Lock()
        self._active_count = 0

    @property
    def max_parallel(self) -> int:
        """Return the configured maximum number of concurrent slots."""
        return self._max_parallel

    @property
    def active_count(self) -> int:
        """Return the number of currently acquired slots (thread-safe)."""
        with self._lock:
            return self._active_count

    def acquire(self) -> None:
        """Acquire a slot, blocking until one is available."""
        self._semaphore.acquire()
        with self._lock:
            self._active_count += 1
        logger.debug(
            "Slot acquired (%d/%d active)", self._active_count, self._max_parallel
        )

    def release(self) -> None:
        """Release a slot, allowing another caller to proceed."""
        with self._lock:
            self._active_count -= 1
        self._semaphore.release()
        logger.debug(
            "Slot released (%d/%d active)", self._active_count, self._max_parallel
        )

    def __enter__(self) -> LicenseAwareQueue:
        """Acquire a slot on context entry."""
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release the slot on context exit."""
        self.release()


def is_license_failure(error_message: str | None) -> bool:
    """Check if an error message indicates a FlexLM license failure.

    Scans the error message against known FlexLM/license error patterns.
    Used by the batch runner to distinguish license failures (re-queue)
    from permanent failures (mark as failed).

    Args:
        error_message: The stderr output from an OLGA subprocess,
            or None if no stderr was captured.

    Returns:
        True if the message matches any known license failure pattern,
        False otherwise (including for None and empty strings).
    """
    if not error_message:
        return False

    for pattern in LICENSE_FAILURE_PATTERNS:
        if pattern.search(error_message):
            return True

    return False
