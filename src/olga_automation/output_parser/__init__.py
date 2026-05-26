"""Output Parser - Parse OLGA simulation results (.tpl, .ppl, .out).

This module provides functions to parse OLGA output files into structured
data objects, extract specific variables and time windows, compare results
across runs, and export data to CSV and JSON formats.

Public API:
    Data models: TrendData, VariableSeries, ProfileData, ProfileVariable
    Parsers: parse_out, parse_tpl, parse_ppl
    Extractors: extract_variable, extract_time_window, compare_runs
    Exporters: export_to_csv, export_to_json
"""

from olga_automation.output_parser.models import (
    ProfileData,
    ProfileVariable,
    TrendData,
    VariableSeries,
)
from olga_automation.output_parser.out_parser import parse_out
from olga_automation.output_parser.extractors import (
    compare_runs,
    extract_time_window,
    extract_variable,
)
from olga_automation.output_parser.exporters import export_to_csv, export_to_json

# tpl_parser and ppl_parser may not be implemented yet (plan 05-02 parallel).
# Import them if available; they will be added to __all__ regardless so that
# downstream code can rely on the public API once all plans complete.
try:
    from olga_automation.output_parser.tpl_parser import parse_tpl
except (ImportError, AttributeError):
    parse_tpl = None  # type: ignore[assignment]

try:
    from olga_automation.output_parser.ppl_parser import parse_ppl
except (ImportError, AttributeError):
    parse_ppl = None  # type: ignore[assignment]

__all__ = [
    "TrendData",
    "VariableSeries",
    "ProfileData",
    "ProfileVariable",
    "parse_out",
    "parse_tpl",
    "parse_ppl",
    "extract_variable",
    "extract_time_window",
    "compare_runs",
    "export_to_csv",
    "export_to_json",
]
