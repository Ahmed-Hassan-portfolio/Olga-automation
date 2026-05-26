"""Data models: TrendData, ProfileData, VariableSeries, ProfileVariable.

These dataclasses hold parsed OLGA output data from .tpl (trend) and .ppl
(profile) files. All time-series and spatial data is stored as numpy arrays.

Key conventions:
- TrendData.variables keyed by "VarName@Position" (or "VarName" for GLOBAL)
- ProfileData.variables keyed by "VarName@Branch" (or "VarName" for GLOBAL)
- ProfileVariable has its own positions array (branches may differ in geometry)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class VariableSeries:
    """A single trend variable's time series data.

    Parameters
    ----------
    name : str
        OLGA variable name (e.g. "PT", "TM", "VOLGBL").
    position : str
        Measurement position (e.g. "WELLHEAD", "TIEIN"). Empty string for
        GLOBAL variables.
    unit : str
        Physical unit (e.g. "PA", "C", "-").
    values : np.ndarray
        1D array of values, one per timestep. Length matches TrendData.time.
    """

    name: str
    position: str
    unit: str
    values: np.ndarray


@dataclass
class TrendData:
    """Parsed trend plot data from an OLGA .tpl file.

    Parameters
    ----------
    olga_version : str
        OLGA version string from file header (e.g. "OLGA 2025.1.2").
    time_unit : str
        Unit of the time axis (e.g. "S" for seconds).
    time : np.ndarray
        1D array of timestep values.
    variables : dict[str, VariableSeries]
        Trend variables keyed by "VarName@Position" or "VarName" for GLOBAL.
    metadata : dict[str, str]
        Header info: input_file, date, project, title, author, restart_file.
    """

    olga_version: str
    time_unit: str
    time: np.ndarray
    variables: dict[str, VariableSeries] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ProfileVariable:
    """A single profile variable's spatial data across timesteps.

    Parameters
    ----------
    name : str
        OLGA variable name (e.g. "PT", "GG").
    unit : str
        Physical unit (e.g. "PA", "KG/S").
    branch : str
        Branch name this variable belongs to (e.g. "old_offshore").
    positions : np.ndarray
        1D array of spatial coordinates along the branch for this variable.
    data : np.ndarray
        2D array of shape (n_timestamps, n_positions). Each row is the
        spatial profile at one timestep.
    """

    name: str
    unit: str
    branch: str
    positions: np.ndarray
    data: np.ndarray


@dataclass
class ProfileData:
    """Parsed profile plot data from an OLGA .ppl file.

    Parameters
    ----------
    olga_version : str
        OLGA version string from file header.
    time_unit : str
        Unit of the time axis (e.g. "S" for seconds).
    timestamps : np.ndarray
        1D array of timestep values at which profiles were recorded.
    variables : dict[str, ProfileVariable]
        Profile variables keyed by "VarName@Branch" or "VarName" for GLOBAL.
    metadata : dict[str, str]
        Header info: input_file, date, project, title, author, restart_file.
    """

    olga_version: str
    time_unit: str
    timestamps: np.ndarray
    variables: dict[str, ProfileVariable] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
