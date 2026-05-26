"""Tests for the .tpl trend file parser."""

from pathlib import Path

import numpy as np
import pytest

from olga_automation.exceptions import OutputParseError
from olga_automation.output_parser.models import TrendData, VariableSeries
from olga_automation.output_parser.tpl_parser import parse_tpl
from tests.conftest import create_synthetic_tpl


class TestParseTpl:
    """Tests for parse_tpl() on synthetic .tpl files."""

    def test_parse_basic(self, synthetic_tpl):
        """Parse synthetic tpl and verify TrendData structure."""
        result = parse_tpl(synthetic_tpl)
        assert isinstance(result, TrendData)
        assert len(result.time) == 10  # default n_timesteps
        assert len(result.variables) == 3  # PT@WELLHEAD, TM@WELLHEAD, VOLGBL

    def test_variable_keys(self, synthetic_tpl):
        """Verify variables dict has expected keys."""
        result = parse_tpl(synthetic_tpl)
        assert "PT@WELLHEAD" in result.variables
        assert "TM@WELLHEAD" in result.variables
        assert "VOLGBL" in result.variables

    def test_variable_series_fields(self, synthetic_tpl):
        """Verify each VariableSeries has correct name, position, unit, values."""
        result = parse_tpl(synthetic_tpl)

        pt = result.variables["PT@WELLHEAD"]
        assert isinstance(pt, VariableSeries)
        assert pt.name == "PT"
        assert pt.position == "WELLHEAD"
        assert pt.unit == "PA"
        assert pt.values.shape == (10,)

        tm = result.variables["TM@WELLHEAD"]
        assert tm.name == "TM"
        assert tm.position == "WELLHEAD"
        assert tm.unit == "C"
        assert tm.values.shape == (10,)

        vol = result.variables["VOLGBL"]
        assert vol.name == "VOLGBL"
        assert vol.position == ""
        assert vol.unit == "-"
        assert vol.values.shape == (10,)

    def test_time_array_values(self, synthetic_tpl):
        """Verify time array starts at 0, ends at 3600, correct length."""
        result = parse_tpl(synthetic_tpl)
        assert result.time[0] == pytest.approx(0.0)
        assert result.time[-1] == pytest.approx(3600.0)
        assert len(result.time) == 10

    def test_data_values_deterministic(self, synthetic_tpl):
        """Verify data values match the deterministic formula: 1e7 - t*100 + i*1000."""
        result = parse_tpl(synthetic_tpl)
        time_points = np.linspace(0, 3600, 10)

        # PT@WELLHEAD is catalog index 0 -> val = 1e7 - t*100 + 0*1000
        pt = result.variables["PT@WELLHEAD"]
        for j, t in enumerate(time_points):
            expected = 1e7 - t * 100 + 0 * 1000
            assert pt.values[j] == pytest.approx(expected, rel=1e-5)

        # TM@WELLHEAD is catalog index 1 -> val = 1e7 - t*100 + 1*1000
        tm = result.variables["TM@WELLHEAD"]
        for j, t in enumerate(time_points):
            expected = 1e7 - t * 100 + 1 * 1000
            assert tm.values[j] == pytest.approx(expected, rel=1e-5)

        # VOLGBL is catalog index 2 -> val = 1e7 - t*100 + 2*1000
        vol = result.variables["VOLGBL"]
        for j, t in enumerate(time_points):
            expected = 1e7 - t * 100 + 2 * 1000
            assert vol.values[j] == pytest.approx(expected, rel=1e-5)

    def test_metadata(self, synthetic_tpl):
        """Verify olga_version, time_unit, and metadata dict."""
        result = parse_tpl(synthetic_tpl)
        assert result.olga_version == "OLGA 2025.1.2"
        assert result.time_unit == "S"
        assert result.metadata["input_file"] == "test_model.inp"
        assert result.metadata["restart_file"] == "restart.rsw"
        assert result.metadata["date"] == "2026-02-08 00:00:00"
        assert result.metadata["project"] == "test_project"
        assert result.metadata["title"] == "test_title"
        assert result.metadata["author"] == "test"

    def test_global_variable_key(self, synthetic_tpl):
        """Verify GLOBAL variable keyed by name alone, no '@'."""
        result = parse_tpl(synthetic_tpl)
        # VOLGBL is GLOBAL -> keyed as "VOLGBL" not "VOLGBL@"
        assert "VOLGBL" in result.variables
        assert "VOLGBL@" not in result.variables
        vol = result.variables["VOLGBL"]
        assert vol.position == ""

    def test_missing_file(self, tmp_path):
        """Raises OutputParseError for non-existent file."""
        with pytest.raises(OutputParseError, match="not found"):
            parse_tpl(tmp_path / "nonexistent.tpl")

    def test_custom_variables(self, tmp_path):
        """Create synthetic tpl with custom variable list and verify parsing."""
        custom_vars = [
            {"name": "GG", "position": "INLET", "unit": "KG/S", "desc": "Gas flow"},
            {
                "name": "ACCLIQ",
                "position": "",
                "unit": "M3",
                "desc": "Accumulated liquid",
                "global": True,
            },
        ]
        tpl_path = create_synthetic_tpl(
            tmp_path / "custom.tpl", n_timesteps=5, variables=custom_vars
        )
        result = parse_tpl(tpl_path)
        assert len(result.variables) == 2
        assert "GG@INLET" in result.variables
        assert "ACCLIQ" in result.variables
        assert result.variables["GG@INLET"].unit == "KG/S"
        assert result.variables["ACCLIQ"].unit == "M3"
        assert len(result.time) == 5

    def test_single_timestep(self, tmp_path):
        """Edge case: single timestep file parses correctly."""
        tpl_path = create_synthetic_tpl(tmp_path / "single.tpl", n_timesteps=1)
        result = parse_tpl(tpl_path)
        assert len(result.time) == 1
        assert result.time[0] == pytest.approx(0.0)
        for var in result.variables.values():
            assert var.values.shape == (1,)

    def test_many_timesteps(self, tmp_path):
        """Verify parsing with a larger number of timesteps."""
        tpl_path = create_synthetic_tpl(tmp_path / "many.tpl", n_timesteps=100)
        result = parse_tpl(tpl_path)
        assert len(result.time) == 100
        assert result.time[0] == pytest.approx(0.0)
        assert result.time[-1] == pytest.approx(3600.0)
        for var in result.variables.values():
            assert var.values.shape == (100,)
