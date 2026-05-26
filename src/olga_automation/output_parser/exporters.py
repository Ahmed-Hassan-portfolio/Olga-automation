"""Export helpers: export_to_csv, export_to_json.

Converts parsed OLGA output data (TrendData, ProfileData) to portable
formats. CSV export uses the csv module for proper escaping. JSON export
uses a custom NumpyEncoder to serialize numpy arrays as Python lists.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Union

import numpy as np

from olga_automation.exceptions import OutputParseError
from olga_automation.output_parser.models import (
    ProfileData,
    TrendData,
)


class NumpyEncoder(json.JSONEncoder):
    """JSON encoder that handles numpy types.

    Converts numpy arrays to lists, numpy integers to Python ints,
    numpy floats to Python floats, and numpy bools to Python bools.
    All other types are passed to the default encoder.
    """

    def default(self, obj):
        """Encode numpy objects to JSON-serializable types."""
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


def export_to_json(data: Union[TrendData, ProfileData]) -> dict:
    """Convert parsed OLGA data to a JSON-serializable dictionary.

    For TrendData, produces a dict with type="trend", the time array as a
    list, and variables as nested dicts with name/position/unit/values.

    For ProfileData, produces a dict with type="profile", timestamps as a
    list, and variables with name/unit/branch/positions/data (2D list).

    Parameters
    ----------
    data : TrendData | ProfileData
        Parsed output data to export.

    Returns
    -------
    dict
        JSON-serializable dictionary. Can be serialized with
        ``json.dumps(result)`` or ``json.dumps(result, cls=NumpyEncoder)``.
    """
    if isinstance(data, TrendData):
        variables = {}
        for key, vs in data.variables.items():
            variables[key] = {
                "name": vs.name,
                "position": vs.position,
                "unit": vs.unit,
                "values": vs.values.tolist(),
            }
        return {
            "type": "trend",
            "olga_version": data.olga_version,
            "time_unit": data.time_unit,
            "metadata": dict(data.metadata),
            "time": data.time.tolist(),
            "variables": variables,
        }

    if isinstance(data, ProfileData):
        variables = {}
        for key, pv in data.variables.items():
            variables[key] = {
                "name": pv.name,
                "unit": pv.unit,
                "branch": pv.branch,
                "positions": pv.positions.tolist(),
                "data": pv.data.tolist(),
            }
        return {
            "type": "profile",
            "olga_version": data.olga_version,
            "time_unit": data.time_unit,
            "metadata": dict(data.metadata),
            "timestamps": data.timestamps.tolist(),
            "variables": variables,
        }

    raise TypeError(
        f"Expected TrendData or ProfileData, got {type(data).__name__}"
    )


def export_to_csv(
    data: Union[TrendData, ProfileData],
    output_path: Path,
) -> None:
    """Export parsed OLGA data to a CSV file.

    For TrendData, produces a wide-format CSV with columns:
    ``time, var1_key, var2_key, ...``

    For ProfileData, produces a long-format CSV with columns:
    ``timestep, position, variable, value``

    Parameters
    ----------
    data : TrendData | ProfileData
        Parsed output data to export.
    output_path : Path
        Path to write the CSV file. Parent directory must exist.

    Raises
    ------
    OutputParseError
        If the parent directory of output_path does not exist.
    TypeError
        If data is not TrendData or ProfileData.
    """
    output_path = Path(output_path)

    if not output_path.parent.exists():
        raise OutputParseError(
            f"Parent directory does not exist: {output_path.parent}"
        )

    if isinstance(data, TrendData):
        _export_trend_csv(data, output_path)
    elif isinstance(data, ProfileData):
        _export_profile_csv(data, output_path)
    else:
        raise TypeError(
            f"Expected TrendData or ProfileData, got {type(data).__name__}"
        )


def _export_trend_csv(data: TrendData, output_path: Path) -> None:
    """Write TrendData to wide-format CSV."""
    var_keys = list(data.variables.keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header row
        writer.writerow(["time"] + var_keys)

        # Data rows
        for i in range(len(data.time)):
            row = [data.time[i]]
            for key in var_keys:
                row.append(data.variables[key].values[i])
            writer.writerow(row)


def _export_profile_csv(data: ProfileData, output_path: Path) -> None:
    """Write ProfileData to long-format CSV."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Header row
        writer.writerow(["timestep", "position", "variable", "value"])

        # Data rows: one per data point
        for key, pv in data.variables.items():
            for t_idx, t in enumerate(data.timestamps):
                for p_idx, pos in enumerate(pv.positions):
                    writer.writerow([
                        t,
                        pos,
                        key,
                        pv.data[t_idx, p_idx],
                    ])
