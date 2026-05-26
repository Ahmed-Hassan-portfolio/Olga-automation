"""Parse .ppl profile data files.

Reads OLGA .ppl (profile plot) output files into structured ProfileData objects.
Handles header metadata, NETWORK geometry, CATALOG variable definitions with
SECTION/BOUNDARY branch markers, and interleaved TIME SERIES profile blocks.

Key format details:
- Header: OLGA version (quoted), PROFILE PLOT marker, key/value pairs
- CATALOG entries: SECTION:/BRANCH: and BOUNDARY:/BRANCH: formats
- TIME SERIES: interleaved blocks with stride = n_vars + 1 per timestep
  (1 timestamp line + n_vars spatial value lines)
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from olga_automation.exceptions import OutputParseError
from olga_automation.output_parser.models import ProfileData, ProfileVariable


def parse_ppl(ppl_path: Path) -> ProfileData:
    """Parse an OLGA .ppl profile plot file into a ProfileData object.

    Parameters
    ----------
    ppl_path : Path
        Path to the .ppl file.

    Returns
    -------
    ProfileData
        Parsed profile data with timestamps and named ProfileVariable objects.

    Raises
    ------
    OutputParseError
        If file is missing, unreadable, or has invalid format.
    """
    ppl_path = Path(ppl_path)
    if not ppl_path.exists():
        raise OutputParseError(f"PPL file not found: {ppl_path}")

    try:
        text = ppl_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise OutputParseError(f"Cannot read PPL file: {exc}") from exc

    lines = text.splitlines()
    if len(lines) < 2:
        raise OutputParseError("PPL file too short")

    # Parse sections in sequence
    olga_version, metadata, header_end = _parse_header(lines)
    geometry, geo_end = _parse_geometry(lines, header_end)
    catalog, catalog_end = _parse_catalog(lines, geo_end)
    time_unit, timestamps, var_data = _load_profile_data(
        lines, catalog_end, catalog, geometry
    )

    # Build ProfileVariable for each catalog entry
    variables: dict[str, ProfileVariable] = {}
    for i, entry in enumerate(catalog):
        name = entry["name"]
        unit = entry["unit"]
        branch = entry["branch"]

        # Key convention: "Name@Branch"
        key = f"{name}@{branch}" if branch else name

        # Get positions from geometry for this variable's branch
        positions = geometry.get(branch, np.array([]))

        variables[key] = ProfileVariable(
            name=name,
            unit=unit,
            branch=branch,
            positions=positions,
            data=var_data[i],
        )

    return ProfileData(
        olga_version=olga_version,
        time_unit=time_unit,
        timestamps=timestamps,
        variables=variables,
        metadata=metadata,
    )


def _parse_header(
    lines: list[str],
) -> tuple[str, dict[str, str], int]:
    """Parse header lines: OLGA version, PROFILE PLOT type, and key-value metadata.

    Returns
    -------
    tuple
        (olga_version, metadata_dict, line_index_after_header)

    Raises
    ------
    OutputParseError
        If line 2 is not PROFILE PLOT.
    """
    # Line 0: OLGA version (quoted)
    olga_version = _unquote(lines[0])

    # Line 1: must be PROFILE PLOT
    if lines[1].strip() != "PROFILE PLOT":
        raise OutputParseError(
            f"Expected 'PROFILE PLOT' on line 2, got: '{lines[1].strip()}'"
        )

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
        (dict mapping branch_name -> geometry_positions_array, line_index_after)
    """
    idx = start
    geometry: dict[str, np.ndarray] = {}

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
        marker = lines[idx].strip()
        if marker not in valid_geo_keywords:
            raise OutputParseError(
                f"Expected BRANCH or ANNULUS at line {idx}, got: {marker}"
            )
        idx += 1

        # Branch name (quoted)
        branch_name = _unquote(lines[idx])
        idx += 1

        # Number of points (number of pipe sections for this branch).
        n_points = int(lines[idx].strip())
        idx += 1

        # Each branch writes TWO equal-length coordinate arrays back to back:
        # positions then elevations. The per-array length is one value per
        # node -- which is n_points in synthetic fixtures and n_points + 1 in
        # real OLGA output (a boundary node per section). OLGA packs values a
        # fixed number per line, and the boundary between the two arrays does
        # NOT always fall on a line break: a single physical line can carry
        # the tail of the positions array and the head of the elevations
        # array. Whole-line consumption therefore over-reads and desyncs the
        # cursor from the array boundaries on irregular-grid cases.
        #
        # Robust approach: consume every numeric token of this branch's block
        # -- the run stops at the next non-numeric token, which is the next
        # BRANCH/ANNULUS marker or the CATALOG marker. The block is exactly
        # the two arrays (no marker sits between positions and elevations),
        # so splitting the token run in half yields the positions array
        # regardless of whether nodes-per-array is n_points or n_points + 1.
        tokens, idx = _read_geometry_block(lines, idx)
        if len(tokens) % 2 != 0:
            raise OutputParseError(
                f"PPL geometry block for branch {branch_name!r} has an odd "
                f"token count ({len(tokens)}); expected equal-length "
                f"position and elevation arrays"
            )
        half = len(tokens) // 2
        if half < n_points:
            raise OutputParseError(
                f"PPL geometry block for branch {branch_name!r} has {half} "
                f"position values, fewer than the declared {n_points}"
            )
        coords = tokens[:half]

        geometry[branch_name] = np.array(coords[:n_points])

    return geometry, idx


def _read_geometry_block(
    lines: list[str], line_idx: int
) -> tuple[list[float], int]:
    """Consume one branch's contiguous run of numeric geometry tokens.

    Reads whitespace-separated float tokens starting at ``lines[line_idx]``
    and walks forward across line boundaries, stopping at the first line
    whose leading token is non-numeric -- i.e. the next BRANCH/ANNULUS marker
    or the CATALOG marker. The returned token list is the branch's positions
    array followed immediately by its elevations array.

    Parameters
    ----------
    lines : list[str]
        All file lines.
    line_idx : int
        Index of the first line of coordinate values for the branch.

    Returns
    -------
    tuple
        ``(values, new_line_idx)`` -- every numeric token of the branch's
        geometry block, and the index of the line where the next section
        marker begins.

    Raises
    ------
    OutputParseError
        If a line that begins numerically contains a non-numeric token, or
        the file ends before any marker is found.
    """
    values: list[float] = []
    while line_idx < len(lines):
        row = lines[line_idx].split()
        if not row:
            # Blank line inside the block -- skip it.
            line_idx += 1
            continue
        # A marker line (BRANCH / ANNULUS / CATALOG) terminates the block.
        if not _is_float_token(row[0]):
            break
        for tok in row:
            try:
                values.append(float(tok))
            except ValueError as exc:
                raise OutputParseError(
                    f"Invalid coordinate value in PPL geometry at line "
                    f"{line_idx}: {tok!r}"
                ) from exc
        line_idx += 1
    else:
        raise OutputParseError(
            "Unexpected end of PPL file while reading branch geometry"
        )

    if not values:
        raise OutputParseError(
            f"No coordinate values found in PPL geometry at line {line_idx}"
        )

    return values, line_idx


def _is_float_token(token: str) -> bool:
    """Return True if ``token`` parses as a float."""
    try:
        float(token)
    except ValueError:
        return False
    return True


def _parse_catalog(
    lines: list[str], start: int
) -> tuple[list[dict], int]:
    """Parse CATALOG section with PPL-specific variable definitions.

    PPL CATALOG entries use SECTION:/BOUNDARY: with BRANCH: markers:
    - ``PT 'SECTION:' 'BRANCH:' 'riser' '(PA)' 'Pressure'``
    - ``GG 'BOUNDARY:' 'BRANCH:' 'old_offshore' '(KG/S)' 'Gas mass flow'``

    Returns
    -------
    tuple
        (list of catalog dicts with name/unit/branch/section_type/description,
         line_index_of_TIME_SERIES_marker)
    """
    idx = start

    # Find CATALOG marker
    while idx < len(lines):
        if lines[idx].strip() == "CATALOG":
            break
        idx += 1
    else:
        raise OutputParseError("CATALOG marker not found in PPL file")

    idx += 1  # Move past CATALOG

    # Number of variables
    n_vars = int(lines[idx].strip())
    idx += 1

    catalog: list[dict] = []
    for _ in range(n_vars):
        line = lines[idx].strip()
        idx += 1

        # Extract variable name (first token)
        first_space = line.index(" ") if " " in line else len(line)
        var_name = line[:first_space]

        # Extract all quoted strings
        quoted = re.findall(r"'([^']*)'", line)

        entry = _classify_ppl_catalog_entry(var_name, quoted)
        catalog.append(entry)

    # Find TIME SERIES marker
    while idx < len(lines):
        if lines[idx].strip().startswith("TIME SERIES"):
            break
        idx += 1
    else:
        raise OutputParseError("TIME SERIES marker not found in PPL file")

    return catalog, idx


def _classify_ppl_catalog_entry(var_name: str, quoted: list[str]) -> dict:
    """Classify a PPL CATALOG entry based on its quoted string markers.

    Parameters
    ----------
    var_name : str
        Variable name (first token, e.g. "PT", "GG").
    quoted : list[str]
        All quoted strings extracted from the catalog line.

    Returns
    -------
    dict
        Keys: name, unit, branch, section_type, description.
    """
    # Find unit string -- the one matching (SOMETHING)
    unit = ""
    for q in quoted:
        m = re.match(r"^\((.+)\)$", q)
        if m:
            unit = m.group(1)
            break

    # Description is the last quoted string
    description = quoted[-1] if quoted else ""

    # Determine section type and branch
    section_type = ""
    branch = ""

    if quoted:
        marker = quoted[0]
        if marker in ("SECTION:", "BOUNDARY:"):
            section_type = marker.rstrip(":")
            # Look for BRANCH: marker to get branch name
            for i, q in enumerate(quoted):
                if q == "BRANCH:" and i + 1 < len(quoted):
                    branch = quoted[i + 1]
                    break
        elif marker == "GLOBAL":
            section_type = "GLOBAL"

    return {
        "name": var_name,
        "unit": unit,
        "branch": branch,
        "section_type": section_type,
        "description": description,
    }


def _load_profile_data(
    lines: list[str],
    start: int,
    catalog: list[dict],
    geometry: dict[str, np.ndarray],
) -> tuple[str, np.ndarray, dict[int, np.ndarray]]:
    """Load interleaved TIME SERIES profile block data.

    Data is organized as interleaved blocks per timestep:
    - Line 0: timestamp value (single float)
    - Line 1: spatial values for catalog variable 0
    - Line 2: spatial values for catalog variable 1
    - ...
    - Stride = n_vars + 1 lines per timestep

    Parameters
    ----------
    lines : list[str]
        All file lines.
    start : int
        Line index of the TIME SERIES marker.
    catalog : list[dict]
        Parsed catalog entries.
    geometry : dict[str, np.ndarray]
        Branch geometry for position count reference.

    Returns
    -------
    tuple
        (time_unit, timestamps_array, dict mapping catalog_index -> 2D array)
    """
    ts_line = lines[start].strip()

    # Extract time unit from marker line
    time_unit = "S"  # default
    unit_match = re.search(r"'\s*\((\w+)\)\s*'", ts_line)
    if unit_match:
        time_unit = unit_match.group(1)

    n_vars = len(catalog)
    stride = n_vars + 1  # 1 timestamp line + n_vars data lines per block

    # Collect data lines after marker (skip empty lines)
    data_start = start + 1
    data_lines: list[str] = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        # Check if line looks numeric
        try:
            float(stripped.split()[0])
            data_lines.append(stripped)
        except (ValueError, IndexError):
            break

    if not data_lines:
        raise OutputParseError("No data found in PPL TIME SERIES section")

    # Parse interleaved blocks
    n_timesteps = len(data_lines) // stride
    if n_timesteps == 0:
        raise OutputParseError(
            f"Insufficient data lines ({len(data_lines)}) for "
            f"{n_vars} variables (stride={stride})"
        )

    timestamps: list[float] = []
    # Initialize storage for each variable: list of spatial arrays per timestep
    var_rows: dict[int, list[np.ndarray]] = {i: [] for i in range(n_vars)}

    for t_idx in range(n_timesteps):
        block_start = t_idx * stride

        # Line 0 of block: timestamp
        ts_val = float(data_lines[block_start].split()[0])
        timestamps.append(ts_val)

        # Lines 1..n_vars: spatial values for each variable
        for v_idx in range(n_vars):
            line_idx = block_start + 1 + v_idx
            if line_idx >= len(data_lines):
                raise OutputParseError(
                    f"Unexpected end of data at timestep {t_idx}, variable {v_idx}"
                )
            vals = [float(x) for x in data_lines[line_idx].split()]
            var_rows[v_idx].append(np.array(vals))

    # Build 2D arrays (n_timesteps x n_positions) for each variable
    timestamps_array = np.array(timestamps)
    var_data: dict[int, np.ndarray] = {}
    for i in range(n_vars):
        var_data[i] = np.array(var_rows[i])

    return time_unit, timestamps_array, var_data


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
