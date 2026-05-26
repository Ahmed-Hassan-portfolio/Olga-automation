"""Default key-value mappings for OLGA keyword types.

When ``add_keyword()`` creates a new keyword, it pre-populates any keys the
caller did not explicitly provide with OLGA defaults from this dict. Defaults
were extracted from real .opi files in ``base_models/``.

Structure::

    KEYWORD_DEFAULTS = {
        "KEYWORD_TYPE": {
            "KEY_NAME": {
                "values": ["default_value"],
                "unit": "unit_string_or_None",
                "default_unit": "NoUnit_or_unit_string",
            },
            ...
        },
        ...
    }

For keyword types not listed here, ``add_keyword()`` logs a debug message
and proceeds without defaults.
"""

from __future__ import annotations

KEYWORD_DEFAULTS: dict[str, dict[str, dict]] = {
    "SOURCE": {
        "SOURCETYPE": {
            "values": ["MASS"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "GASFRACTION": {
            "values": ["0"],
            "unit": "-",
            "default_unit": "-",
        },
        "TEMPERATURE": {
            "values": ["15"],
            "unit": "C",
            "default_unit": "C",
        },
    },
    "VALVE": {
        "EQUILIBRIUMMODEL": {
            "values": ["FROZEN"],
            "unit": None,
            "default_unit": "NoUnit",
        },
    },
    "OPTIONS": {
        "STEADYSTATE": {
            "values": ["OFF"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "COMPOSITIONAL": {
            "values": ["SINGLE"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "FLASHMODEL": {
            "values": ["HYDROCARBON"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "FLOWMODEL": {
            "values": ["OLGAHD"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "SOLVER": {
            "values": ["STANDARD"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "LICENSE": {
            "values": ["STANDARD"],
            "unit": None,
            "default_unit": "NoUnit",
        },
    },
    "INTEGRATION": {
        "ENDTIME": {
            "values": ["3600"],
            "unit": "s",
            "default_unit": "s",
        },
        "MAXDT": {
            "values": ["1"],
            "unit": "s",
            "default_unit": "s",
        },
        "MINDT": {
            "values": ["0.001"],
            "unit": "s",
            "default_unit": "s",
        },
        "STARTTIME": {
            "values": ["0"],
            "unit": "s",
            "default_unit": "s",
        },
        "DTSTART": {
            "values": ["0.001"],
            "unit": "s",
            "default_unit": "s",
        },
    },
    "HEATTRANSFER": {
        "INTERPOLATION": {
            "values": ["SECTIONWISE"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "HOUTEROPTION": {
            "values": ["HGIVEN"],
            "unit": None,
            "default_unit": "NoUnit",
        },
        "HMININNERWALL": {
            "values": ["10"],
            "unit": "W/m2-C",
            "default_unit": "W/m2-C",
        },
    },
    "RESTART": {
        "READFILE": {
            "values": ["OFF"],
            "unit": None,
            "default_unit": "NoUnit",
        },
    },
    "GEOMETRY": {
        "XSTART": {
            "values": ["0"],
            "unit": "m",
            "default_unit": "m",
        },
        "YSTART": {
            "values": ["0"],
            "unit": "m",
            "default_unit": "m",
        },
        "ZSTART": {
            "values": ["0"],
            "unit": "m",
            "default_unit": "m",
        },
    },
}
