"""Parse .tpl trend data files.

Reads OLGA .tpl (trend plot) output files into structured TrendData objects.
Handles header metadata, NETWORK geometry, CATALOG variable definitions,
and columnar TIME SERIES data.

Key format details:
- Header: OLGA version (quoted), then key/value pairs on alternating lines
- CATALOG entries: GLOBAL, POSITION:, SECTION:/BRANCH:, BOUNDARY:/BRANCH: formats
- TIME SERIES: column 0 = time, columns 1..N = catalog variables 0..N-1
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from olga_automation.exceptions import OutputParseError
from olga_automation.output_parser.models import TrendData, VariableSeries


def parse_tpl(tpl_path: Path) -> TrendData:
    """Parse an OLGA .tpl trend plot file into a TrendData object.

    Parameters
    ----------
    tpl_path : Path
        Path to the .tpl file.

    Returns
    -------
    TrendData
        Parsed trend data with time array and named VariableSeries.

    Raises
    ------
    OutputParseError
        If file is missing, unreadable, or has invalid format.
    """
    tpl_path = Path(tpl_path)
    if not tpl_path.exists():
        raise OutputParseError(f"TPL file not found: {tpl_path}")

    try:
        text = tpl_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OutputParseError(f"Cannot read TPL file: {exc}") from exc

    lines = text.splitlines()
    if len(lines) < 2:
        raise OutputParseError("TPL file too short")

    # Parse sections in sequence
    olga_version, metadata, header_end = _parse_header(lines)
    geometry, geo_end = _parse_geometry(lines, header_end)
    catalog, catalog_end = _parse_catalog(lines, geo_end)
    time_unit, time_array, var_data = _load_time_series(
        lines, catalog_end, len(catalog)
    )

    # Build VariableSeries for each catalog entry
    variables: dict[str, VariableSeries] = {}
    for i, entry in enumerate(catalog):
        name = entry["name"]
        position = entry["position"]
        unit = entry["unit"]

        # Key convention: "Name@Position" if position else "Name"
        key = f"{name}@{position}" if position else name

        variables[key] = VariableSeries(
            name=name,
            position=position,
            unit=unit,
            values=var_data[i],
        )

    return TrendData(
        olga_version=olga_version,
        time_unit=time_unit,
        time=time_array,
        variables=variables,
        metadata=metadata,
    )


def _parse_header(
    lines: list[str],
) -> tuple[str, dict[str, str], int]:
    """Parse header lines: OLGA version, plot type, and key-value metadata.

    Returns
    -------
    tuple
        (olga_version, metadata_dict, line_index_after_header)
    """
    # Line 0: OLGA version (quoted)
    olga_version = _unquote(lines[0])

    # Line 1: plot type (TIME PLOT / PROFILE PLOT) -- skip, just verify
    # We don't enforce here; the caller (parse_tpl) expects TIME PLOT

    # Lines 2+: key-value pairs until NETWORK marker
    metadata: dict[str, str] = {}
    header_keys = {
        "INPUT FILE": "input_file",
        "RESTART FILE": "restart_file",
        "DATE": "date",
        "PROJECT": "project",
        "TITLE": "title",
        "AUTHOR": "author",
    }

    idx = 2
    while idx < len(lines):
        line = lines[idx].strip()
        if line == "NETWORK":
            break
        if line in header_keys:
            # Next line is the value
            if idx + 1 < len(lines):
                metadata[header_keys[line]] = _unquote(lines[idx + 1])
                idx += 2
                continue
        idx += 1

    return olga_version, metadata, idx


def _parse_geometry(
    lines: list[str], start: int
) -> tuple[dict[str, np.ndarray], int]:
    """Parse NETWORK / GEOMETRY / BRANCH sections.

    Returns
    -------
    tuple
        (dict mapping branch_name -> geometry_array, line_index_after_geometry)
    """
    idx = start
    geometry: dict[str, np.ndarray] = {}

    # Expect NETWORK at current line
    if idx >= len(lines) or lines[idx].strip() != "NETWORK":
        raise OutputParseError(
            f"Expected NETWORK at line {idx}, got: "
            f"{lines[idx].strip() if idx < len(lines) else 'EOF'}"
        )
    idx += 1

    # Number of branches
    n_branches = int(lines[idx].strip())
    idx += 1

    # GEOMETRY line with unit
    geo_line = lines[idx].strip()
    if not geo_line.startswith("GEOMETRY"):
        raise OutputParseError(f"Expected GEOMETRY at line {idx}, got: {geo_line}")
    idx += 1

    # Parse each branch (BRANCH or ANNULUS keywords use identical format)
    valid_geo_keywords = {"BRANCH", "ANNULUS"}
    for _ in range(n_branches):
        # BRANCH or ANNULUS marker
        marker = lines[idx].strip()
        if marker not in valid_geo_keywords:
            raise OutputParseError(
                f"Expected BRANCH or ANNULUS at line {idx}, got: {marker}"
            )
        idx += 1

        # Branch name (quoted)
        branch_name = _unquote(lines[idx])
        idx += 1

        # Number of points
        n_points = int(lines[idx].strip())
        idx += 1

        # OLGA writes n_sections+1 boundary-node coordinates (one per node,
        # not per section). Read n_points+1 values for both positions and
        # elevations to avoid leaving a stray value on the last line.
        n_nodes = n_points + 1
        coords, idx = _read_n_floats(lines, idx, n_nodes)

        # Read elevation values (same node count, skip).
        _, idx = _read_n_floats(lines, idx, n_nodes)

        geometry[branch_name] = np.array(coords)

    return geometry, idx


def _read_n_floats(
    lines: list[str], start: int, n: int
) -> tuple[list[float], int]:
    """Read exactly *n* floats from consecutive lines, advancing *idx* only as far
    as needed.

    When the last consumed line has more values than required, idx is still
    incremented past that line (values already on that line are lost, but they
    are only elevation or geometry data we don't need). This mirrors the original
    behaviour while preventing the overshoot case where the parser would leave
    a stray numeric line and then fail to find the next BRANCH/ANNULUS keyword.

    Parameters
    ----------
    lines : list[str]
        All file lines.
    start : int
        Line index to start reading from.
    n : int
        Exact number of float values to collect.

    Returns
    -------
    tuple
        (list_of_n_floats, line_index_after_last_consumed_line)
    """
    values: list[float] = []
    idx = start
    while len(values) < n and idx < len(lines):
        vals = lines[idx].split()
        values.extend(float(v) for v in vals)
        idx += 1
    return values[:n], idx


def _parse_catalog(
    lines: list[str], start: int
) -> tuple[list[dict], int]:
    """Parse CATALOG section with variable definitions.

    Handles 4 format variations:
    - GLOBAL: ``VOLGBL 'GLOBAL' '(-)' 'Description'``
    - POSITION: ``PT 'POSITION:' 'WELLHEAD' '(PA)' 'Description'``
    - SECTION/BRANCH: ``PT 'SECTION:' 'BRANCH:' 'riser' '(PA)' 'Description'``
    - BOUNDARY/BRANCH: ``GG 'BOUNDARY:' 'BRANCH:' 'old_offshore' '(KG/S)' 'Desc'``

    Returns
    -------
    tuple
        (list of catalog dicts, line_index_of_TIME_SERIES_marker)
    """
    idx = start

    # Find CATALOG marker
    while idx < len(lines):
        if lines[idx].strip() == "CATALOG":
            break
        idx += 1
    else:
        raise OutputParseError("CATALOG marker not found in TPL file")

    idx += 1  # Move past CATALOG

    # Number of variables
    n_vars = int(lines[idx].strip())
    idx += 1

    catalog: list[dict] = []
    for _ in range(n_vars):
        line = lines[idx].strip()
        idx += 1

        # Extract variable name (first token before quotes)
        first_space = line.index(" ") if " " in line else len(line)
        var_name = line[:first_space]

        # Extract all quoted strings
        quoted = re.findall(r"'([^']*)'", line)

        entry = _classify_catalog_entry(var_name, quoted)
        catalog.append(entry)

    # Find TIME SERIES marker
    while idx < len(lines):
        if lines[idx].strip().startswith("TIME SERIES"):
            break
        idx += 1
    else:
        raise OutputParseError("TIME SERIES marker not found in TPL file")

    return catalog, idx


def _classify_catalog_entry(var_name: str, quoted: list[str]) -> dict:
    """Classify a CATALOG entry based on its quoted string markers.

    Parameters
    ----------
    var_name : str
        Variable name (first token, e.g. "PT", "VOLGBL").
    quoted : list[str]
        All quoted strings extracted from the catalog line.

    Returns
    -------
    dict
        Keys: name, position, unit, description.
    """
    # Find unit string -- the one matching (SOMETHING)
    unit = ""
    unit_idx = -1
    for i, q in enumerate(quoted):
        m = re.match(r"^\((.+)\)$", q)
        if m:
            unit = m.group(1)
            unit_idx = i
            break

    # Description is the last quoted string (after unit)
    description = quoted[-1] if quoted else ""
    if unit_idx >= 0 and unit_idx < len(quoted) - 1:
        description = quoted[-1]

    # Classify by markers
    if not quoted:
        return {
            "name": var_name,
            "position": "",
            "unit": "",
            "description": "",
        }

    marker = quoted[0] if quoted else ""

    if marker == "GLOBAL":
        # GLOBAL: name 'GLOBAL' '(unit)' 'desc'
        return {
            "name": var_name,
            "position": "",
            "unit": unit,
            "description": description,
        }
    elif marker == "POSITION:":
        # POSITION: name 'POSITION:' 'position_name' '(unit)' 'desc'
        position = quoted[1] if len(quoted) > 1 else ""
        return {
            "name": var_name,
            "position": position,
            "unit": unit,
            "description": description,
        }
    elif marker in ("SECTION:", "BOUNDARY:"):
        # SECTION/BOUNDARY + BRANCH: name 'TYPE:' 'BRANCH:' 'branch_name' '(unit)' 'desc'
        # Position is derived from branch name
        branch_name = ""
        for i, q in enumerate(quoted):
            if q == "BRANCH:" and i + 1 < len(quoted):
                branch_name = quoted[i + 1]
                break
        return {
            "name": var_name,
            "position": branch_name,
            "unit": unit,
            "description": description,
        }
    else:
        # Unknown format -- use first quoted string as position
        return {
            "name": var_name,
            "position": marker,
            "unit": unit,
            "description": description,
        }


def _load_time_series(
    lines: list[str], start: int, n_vars: int
) -> tuple[str, np.ndarray, dict[int, np.ndarray]]:
    """Load columnar TIME SERIES data.

    Parameters
    ----------
    lines : list[str]
        All file lines.
    start : int
        Line index of the TIME SERIES marker.
    n_vars : int
        Number of CATALOG variables (columns after time).

    Returns
    -------
    tuple
        (time_unit, time_array, dict mapping catalog_index -> value_array)
    """
    ts_line = lines[start].strip()

    # Extract time unit from marker line: TIME SERIES  ' (S)  '
    time_unit = "S"  # default
    unit_match = re.search(r"'\s*\((\w+)\)\s*'", ts_line)
    if unit_match:
        time_unit = unit_match.group(1)

    # Parse data lines starting after marker
    data_start = start + 1
    data_lines = lines[data_start:]

    # Filter out empty lines and collect all data rows
    rows: list[list[float]] = []
    for line in data_lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            vals = [float(x) for x in stripped.split()]
            rows.append(vals)
        except ValueError:
            # Non-numeric line, stop reading
            break

    if not rows:
        raise OutputParseError("No data found in TIME SERIES section")

    # Convert to numpy array
    data = np.array(rows)

    # Column 0 = time, columns 1..N = variables
    time_array = data[:, 0]
    var_data: dict[int, np.ndarray] = {}
    for i in range(n_vars):
        col_idx = i + 1  # catalog[0] -> column 1
        if col_idx < data.shape[1]:
            var_data[i] = data[:, col_idx]
        else:
            raise OutputParseError(
                f"Expected {n_vars + 1} columns but got {data.shape[1]}"
            )

    return time_unit, time_array, var_data


def _unquote(s: str) -> str:
    """Remove surrounding single quotes from a string.

    Parameters
    ----------
    s : str
        Input string, potentially quoted with single quotes.

    Returns
    -------
    str
        Unquoted string. If not quoted, returns stripped input.
    """
    s = s.strip()
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1]
    return s
