"""Tests for olga_automation.opi_parser.validator -- all subprocess calls mocked."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from olga_automation.exceptions import OlgaExecutionError
from olga_automation.opi_parser.validator import validate_opi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_completed_process(returncode: int = 0, stdout: str = "", stderr: str = ""):
    """Build a subprocess.CompletedProcess for mocking."""
    return subprocess.CompletedProcess(
        args=["opi", "dummy.opi", "-exitRC"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateOpiSuccess:
    """validate_opi returns valid=True on clean validation run."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_success(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        mock_run.return_value = _make_completed_process(
            returncode=0,
            stdout="Validation complete\n",
            stderr="",
        )

        result = validate_opi(opi_file)

        assert result["valid"] is True
        assert result["errors"] == []
        assert result["warnings"] == []
        assert result["return_code"] == 0
        mock_run.assert_called_once()


class TestValidateOpiErrors:
    """validate_opi returns valid=False when errors are present."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_with_errors(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        mock_run.return_value = _make_completed_process(
            returncode=1,
            stdout="Error: Missing PVT file\nWarning: Deprecated keyword\n",
            stderr="",
        )

        result = validate_opi(opi_file)

        assert result["valid"] is False
        assert len(result["errors"]) == 1
        assert "Error: Missing PVT file" in result["errors"]
        assert len(result["warnings"]) == 1
        assert "Warning: Deprecated keyword" in result["warnings"]
        assert result["return_code"] == 1


class TestValidateOpiWarningsOnly:
    """Warnings alone do not make the result invalid (returncode 0)."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_with_warnings_only(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        mock_run.return_value = _make_completed_process(
            returncode=0,
            stdout="Warning: Large time step\n",
            stderr="",
        )

        result = validate_opi(opi_file)

        assert result["valid"] is True
        assert result["errors"] == []
        assert len(result["warnings"]) == 1
        assert "Warning: Large time step" in result["warnings"]


class TestValidateOpiFileNotFound:
    """FileNotFoundError raised when .opi path does not exist on disk."""

    def test_validate_opi_file_not_found(self, tmp_path):
        missing = tmp_path / "nonexistent.opi"

        with pytest.raises(FileNotFoundError, match="OPI file not found"):
            validate_opi(missing)


class TestValidateOpiCommandNotFound:
    """OlgaExecutionError raised when opi executable is not on PATH."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_command_not_found(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        mock_run.side_effect = FileNotFoundError("No such file or directory: 'opi'")

        with pytest.raises(OlgaExecutionError, match="opi command not found"):
            validate_opi(opi_file)


class TestValidateOpiTimeout:
    """OlgaExecutionError raised when validation exceeds timeout."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_timeout(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd=["opi", str(opi_file), "-exitRC"],
            timeout=120,
        )

        with pytest.raises(OlgaExecutionError, match="timed out"):
            validate_opi(opi_file)


class TestValidateOpiRawOutput:
    """raw_output field contains the full stdout."""

    @patch("olga_automation.opi_parser.validator.subprocess.run")
    def test_validate_opi_raw_output_included(self, mock_run, tmp_path):
        opi_file = tmp_path / "model.opi"
        opi_file.write_text("<OPGCase/>")

        stdout_text = "Line 1\nLine 2\nValidation complete\n"
        mock_run.return_value = _make_completed_process(
            returncode=0,
            stdout=stdout_text,
            stderr="",
        )

        result = validate_opi(opi_file)

        assert result["raw_output"] == stdout_text
        assert result["valid"] is True
