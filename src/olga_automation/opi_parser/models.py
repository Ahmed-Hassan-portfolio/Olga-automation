"""Data models for OPI parser: OlgaKeyword, KeyValue, ModelSummary, etc."""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class KeyValue:
    """A single key's data from a Keyword's KeyCollection.

    Represents one <Key> element inside a <KeyCollection>:
        <Key Name="MASSFLOW">
            <Values><Value>100</Value></Values>
            <Unit>kg/s</Unit>
            <DefaultUnit>kg/s</DefaultUnit>
        </Key>
    """
    name: str               # Key Name attribute, e.g. "MASSFLOW"
    values: list[str]       # All <Value> texts
    unit: str | None        # <Unit> text, None if empty
    default_unit: str       # <DefaultUnit> text, e.g. "Pa", "NoUnit", "ValueUnitPair"


@dataclass
class OlgaKeyword:
    """A parsed Keyword element from the .opi file.

    Represents one <Keyword> element:
        <Keyword>
            <Tag>FLOWPATH_7.SOURCE_18</Tag>
            <Type>SOURCE</Type>
            <KeyCollection>...</KeyCollection>
        </Keyword>
    """
    tag: str                # <Tag> text, e.g. "FLOWPATH_7.SOURCE_18"
    keyword_type: str       # <Type> text, e.g. "SOURCE"
    keys: dict[str, KeyValue]  # key Name -> KeyValue


@dataclass
class NetworkComponent:
    """A parsed NC (Network Component) element.

    Represents one <NC> element inside <NCCollection>:
        <NC>
            <Tag>FLOWPATH_7</Tag>
            <Type>FLOWPATH</Type>
            <KeywordCollection>...</KeywordCollection>
        </NC>
    """
    tag: str                # NC <Tag>, e.g. "FLOWPATH_7"
    nc_type: str            # NC <Type>, e.g. "FLOWPATH", "NODE", "ANNULUS"
    keywords: list[OlgaKeyword] = field(default_factory=list)


@dataclass
class Connection:
    """A connection between network components.

    Represents connectivity information (e.g. FLOWCONNECTION linking
    two flowpaths or a flowpath to a node).
    """
    tag: str                        # e.g. "FLOWCONNECTION_19"
    terminals: list[dict[str, str]] = field(default_factory=list)
    # Each terminal: {"Name": "INLET", "NCTag": "FLOWPATH_7"}


@dataclass
class FlowpathInfo:
    """Summary info for a FLOWPATH network component."""
    tag: str
    label: str
    pipe_count: int
    pipe_labels: list[str] = field(default_factory=list)
    has_valve: bool = False
    has_source: bool = False
    geometry_label: str | None = None


@dataclass
class NodeInfo:
    """Summary info for a NODE network component."""
    tag: str
    label: str
    node_type: str              # INTERNAL, CLOSED, PRESSURE, MASSFLOW
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)  # (x, y, z)


@dataclass
class ValveInfo:
    """Summary info for a VALVE keyword within a flowpath."""
    tag: str
    label: str
    parent_flowpath: str
    abs_position: float | None = None
    diameter: float | None = None


@dataclass
class SourceInfo:
    """Summary info for a SOURCE keyword within a flowpath."""
    tag: str
    label: str
    parent_flowpath: str
    source_type: str = ""           # MASS, etc.
    position_label: str | None = None


@dataclass
class TrendDataInfo:
    """Summary info for a TRENDDATA output configuration."""
    tag: str
    parent_flowpath: str
    variables: list[str] = field(default_factory=list)  # e.g. ["GT", "PT", "TM"]
    position: str | None = None     # e.g. "WH"


@dataclass
class ProfileDataInfo:
    """Summary info for a PROFILEDATA output configuration."""
    tag: str
    parent_flowpath: str
    variables: list[str] = field(default_factory=list)


@dataclass
class IntegrationInfo:
    """Integration (time stepping) settings from INTEGRATION keyword."""
    end_time: float
    max_dt: float
    min_dt: float
    start_time: float = 0.0
    dt_start: float = 0.0
    unit: str = "s"


@dataclass
class ModelSummary:
    """Complete summary of an .opi model file.

    Aggregates all parsed components into a single structure that
    represents the full model at a glance. Used by MCP tools like
    get_model_summary to return structured info to Claude.
    """
    flowpaths: list[FlowpathInfo] = field(default_factory=list)
    nodes: list[NodeInfo] = field(default_factory=list)
    valves: list[ValveInfo] = field(default_factory=list)
    sources: list[SourceInfo] = field(default_factory=list)
    trend_data: list[TrendDataInfo] = field(default_factory=list)
    profile_data: list[ProfileDataInfo] = field(default_factory=list)
    integration: IntegrationInfo | None = None
    connections: list[Connection] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)  # OPTIONS key-value pairs
    case_level_keywords: list[OlgaKeyword] = field(default_factory=list)
