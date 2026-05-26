"""JSON serialization helpers for MCP tool responses."""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path


class OlgaEncoder(json.JSONEncoder):
    """Custom JSON encoder handling Path, datetime, numpy types, and tuples."""

    def default(self, obj):
        """Convert non-JSON-serializable objects to JSON-serializable types."""
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()

        # Handle numpy types (import numpy only if needed)
        try:
            import numpy as np
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
        except ImportError:
            pass

        if isinstance(obj, tuple):
            return list(obj)

        return super().default(obj)


def serialize_result(obj, indent: int = 2) -> str:
    """Serialize a result object to JSON string.

    Parameters
    ----------
    obj : Any
        Object to serialize. Can be a dataclass, dict, list, or primitive type.
    indent : int, optional
        JSON indentation level, by default 2.

    Returns
    -------
    str
        JSON string representation of the object.
    """
    # Convert dataclasses to dict (including items inside lists)
    if is_dataclass(obj) and not isinstance(obj, type):
        data = asdict(obj)
    elif isinstance(obj, list):
        data = [
            asdict(item) if (is_dataclass(item) and not isinstance(item, type)) else item
            for item in obj
        ]
    elif isinstance(obj, dict):
        data = obj
    else:
        data = obj

    return json.dumps(data, cls=OlgaEncoder, indent=indent)
