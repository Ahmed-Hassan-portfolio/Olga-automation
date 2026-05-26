"""Read operations: parse_opi, get_model_summary, get_parameter, list_keywords.

Higher-level read functions that compose xml_navigator primitives into
business objects (ModelSummary, FlowpathInfo, NodeInfo, etc.).

All functions accept a Path to an .opi file and return populated dataclasses.
They are intentionally stateless -- each call loads the XML tree fresh so that
callers always see the current on-disk state.
"""

from __future__ import annotations

from pathlib import Path

from olga_automation.exceptions import KeywordNotFoundError
from olga_automation.opi_parser.models import (
    Connection,
    FlowpathInfo,
    IntegrationInfo,
    KeyValue,
    ModelSummary,
    NetworkComponent,
    NodeInfo,
    OlgaKeyword,
    ProfileDataInfo,
    SourceInfo,
    TrendDataInfo,
    ValveInfo,
)
from olga_automation.opi_parser.xml_navigator import (
    find_keyword_by_tag,
    get_connections,
    get_key_values,
    get_keyword_data,
    get_nc_data,
    iter_keywords,
    iter_network_components,
    load_opi,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_key_value(keyword: OlgaKeyword, key_name: str) -> str | None:
    """Safely get the first value from a keyword's key, or None."""
    kv = keyword.keys.get(key_name)
    if kv and kv.values:
        return kv.values[0]
    return None


def _safe_float(value: str | None, default: float = 0.0) -> float:
    """Convert a string to float, returning *default* on failure or None."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parent_flowpath_from_tag(tag: str) -> str:
    """Extract parent flowpath tag from a dotted keyword tag.

    E.g. ``"FLOWPATH_7.TRENDDATA_20"`` -> ``"FLOWPATH_7"``.
    Returns the full tag unchanged if no dot is present.
    """
    parts = tag.split(".", 1)
    return parts[0] if len(parts) > 1 else tag


# ---------------------------------------------------------------------------
# Integration parsing
# ---------------------------------------------------------------------------


def _parse_integration(keyword: OlgaKeyword) -> IntegrationInfo:
    """Build an IntegrationInfo from an INTEGRATION keyword."""
    end_time = _safe_float(_get_key_value(keyword, "ENDTIME"))
    max_dt = _safe_float(_get_key_value(keyword, "MAXDT"))
    min_dt = _safe_float(_get_key_value(keyword, "MINDT"))
    start_time = _safe_float(_get_key_value(keyword, "STARTTIME"))
    dt_start = _safe_float(_get_key_value(keyword, "DTSTART"))

    # Get unit from the ENDTIME key (representative of time unit)
    unit = "s"
    endtime_kv = keyword.keys.get("ENDTIME")
    if endtime_kv and endtime_kv.unit:
        unit = endtime_kv.unit

    return IntegrationInfo(
        end_time=end_time,
        max_dt=max_dt,
        min_dt=min_dt,
        start_time=start_time,
        dt_start=dt_start,
        unit=unit,
    )


# ---------------------------------------------------------------------------
# Flowpath child extraction
# ---------------------------------------------------------------------------


def _extract_valve_info(keyword: OlgaKeyword, parent_tag: str) -> ValveInfo:
    """Build a ValveInfo from a VALVE keyword."""
    return ValveInfo(
        tag=keyword.tag,
        label=_get_key_value(keyword, "LABEL") or "",
        parent_flowpath=parent_tag,
        abs_position=_safe_float(_get_key_value(keyword, "ABSPOSITION"), default=None),  # type: ignore[arg-type]
        diameter=_safe_float(_get_key_value(keyword, "DIAMETER"), default=None),  # type: ignore[arg-type]
    )


def _extract_source_info(keyword: OlgaKeyword, parent_tag: str) -> SourceInfo:
    """Build a SourceInfo from a SOURCE keyword."""
    return SourceInfo(
        tag=keyword.tag,
        label=_get_key_value(keyword, "LABEL") or "",
        parent_flowpath=parent_tag,
        source_type=_get_key_value(keyword, "SOURCETYPE") or "",
        position_label=_get_key_value(keyword, "POSITION"),
    )


def _extract_trend_data_info(
    keyword: OlgaKeyword, parent_tag: str
) -> TrendDataInfo:
    """Build a TrendDataInfo from a TRENDDATA keyword."""
    variables: list[str] = []
    var_kv = keyword.keys.get("VARIABLE")
    if var_kv:
        variables = list(var_kv.values)

    return TrendDataInfo(
        tag=keyword.tag,
        parent_flowpath=parent_tag,
        variables=variables,
        position=_get_key_value(keyword, "POSITION"),
    )


def _extract_profile_data_info(
    keyword: OlgaKeyword, parent_tag: str
) -> ProfileDataInfo:
    """Build a ProfileDataInfo from a PROFILEDATA keyword."""
    variables: list[str] = []
    var_kv = keyword.keys.get("VARIABLE")
    if var_kv:
        variables = list(var_kv.values)

    return ProfileDataInfo(
        tag=keyword.tag,
        parent_flowpath=parent_tag,
        variables=variables,
    )


# ---------------------------------------------------------------------------
# Flowpath and Node parsing
# ---------------------------------------------------------------------------


def _parse_flowpath(nc: NetworkComponent) -> tuple[
    FlowpathInfo,
    list[ValveInfo],
    list[SourceInfo],
    list[TrendDataInfo],
    list[ProfileDataInfo],
]:
    """Parse a FLOWPATH NetworkComponent into FlowpathInfo + child info lists."""
    pipe_count = 0
    pipe_labels: list[str] = []
    has_valve = False
    has_source = False
    geometry_label: str | None = None
    label = ""

    valves: list[ValveInfo] = []
    sources: list[SourceInfo] = []
    trend_data: list[TrendDataInfo] = []
    profile_data: list[ProfileDataInfo] = []

    for kw in nc.keywords:
        kw_type = kw.keyword_type

        if kw_type == "PIPE":
            pipe_count += 1
            pipe_label = _get_key_value(kw, "LABEL")
            if pipe_label:
                pipe_labels.append(pipe_label)

        elif kw_type == "VALVE":
            has_valve = True
            valves.append(_extract_valve_info(kw, nc.tag))

        elif kw_type == "SOURCE":
            has_source = True
            sources.append(_extract_source_info(kw, nc.tag))

        elif kw_type == "GEOMETRY":
            geometry_label = _get_key_value(kw, "LABEL")

        elif kw_type == "PARAMETERS":
            label = _get_key_value(kw, "LABEL") or ""

        elif kw_type == "TRENDDATA":
            trend_data.append(_extract_trend_data_info(kw, nc.tag))

        elif kw_type == "PROFILEDATA":
            profile_data.append(_extract_profile_data_info(kw, nc.tag))

    fp_info = FlowpathInfo(
        tag=nc.tag,
        label=label,
        pipe_count=pipe_count,
        pipe_labels=pipe_labels,
        has_valve=has_valve,
        has_source=has_source,
        geometry_label=geometry_label,
    )

    return fp_info, valves, sources, trend_data, profile_data


def _parse_node(nc: NetworkComponent) -> NodeInfo:
    """Parse a NODE NetworkComponent into NodeInfo."""
    label = ""
    node_type = ""
    x = 0.0
    y = 0.0
    z = 0.0

    for kw in nc.keywords:
        if kw.keyword_type == "PARAMETERS":
            label = _get_key_value(kw, "LABEL") or ""
            node_type = _get_key_value(kw, "TYPE") or ""
            x = _safe_float(_get_key_value(kw, "X"))
            y = _safe_float(_get_key_value(kw, "Y"))
            z = _safe_float(_get_key_value(kw, "Z"))
            break  # Only one PARAMETERS keyword per node

    return NodeInfo(
        tag=nc.tag,
        label=label,
        node_type=node_type,
        position=(x, y, z),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_model_summary(opi_path: Path) -> ModelSummary:
    """Load an .opi file and produce a full ModelSummary.

    Steps:

    1. Load the tree with ``load_opi()``.
    2. Parse case-level keywords (OPTIONS, INTEGRATION, etc.).
    3. Iterate NC elements, classify by type (FLOWPATH, NODE).
    4. Within each FLOWPATH, extract child keywords (VALVE, SOURCE,
       TRENDDATA, PROFILEDATA).
    5. Parse connections.
    6. Assemble and return ``ModelSummary``.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file.

    Returns
    -------
    ModelSummary
        Complete summary of the model.
    """
    tree = load_opi(opi_path)

    # ------------------------------------------------------------------
    # 1. Parse case-level keywords
    # ------------------------------------------------------------------
    options: dict[str, str] = {}
    integration: IntegrationInfo | None = None
    case_keywords: list[OlgaKeyword] = []

    for scope, kw_el in iter_keywords(tree):
        if scope != "case":
            continue
        kw = get_keyword_data(kw_el)
        case_keywords.append(kw)

        if kw.keyword_type == "OPTIONS":
            # Flatten all option key-values into the dict
            for key_name, kv in kw.keys.items():
                if kv.values:
                    options[key_name] = kv.values[0]

        elif kw.keyword_type == "INTEGRATION":
            integration = _parse_integration(kw)

    # ------------------------------------------------------------------
    # 2. Parse network components
    # ------------------------------------------------------------------
    flowpaths: list[FlowpathInfo] = []
    nodes: list[NodeInfo] = []
    all_valves: list[ValveInfo] = []
    all_sources: list[SourceInfo] = []
    all_trend_data: list[TrendDataInfo] = []
    all_profile_data: list[ProfileDataInfo] = []

    for nc_el in iter_network_components(tree):
        nc = get_nc_data(nc_el)

        if nc.nc_type == "FLOWPATH":
            fp_info, valves, sources, td, pd = _parse_flowpath(nc)
            flowpaths.append(fp_info)
            all_valves.extend(valves)
            all_sources.extend(sources)
            all_trend_data.extend(td)
            all_profile_data.extend(pd)

        elif nc.nc_type == "NODE":
            nodes.append(_parse_node(nc))
        # ANNULUS: skip for now (as per plan)

    # ------------------------------------------------------------------
    # 3. Parse connections
    # ------------------------------------------------------------------
    connections = get_connections(tree)

    # ------------------------------------------------------------------
    # 4. Assemble summary
    # ------------------------------------------------------------------
    return ModelSummary(
        flowpaths=flowpaths,
        nodes=nodes,
        valves=all_valves,
        sources=all_sources,
        trend_data=all_trend_data,
        profile_data=all_profile_data,
        integration=integration,
        connections=connections,
        options=options,
        case_level_keywords=case_keywords,
    )


def get_parameter(
    opi_path: Path, tag: str, key_name: str
) -> KeyValue | None:
    """Get a single parameter value from a keyword by tag and key name.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file.
    tag : str
        The keyword tag, e.g. ``"OPTIONS_0"`` or ``"FLOWPATH_7.VALVE_15"``.
    key_name : str
        The key name, e.g. ``"MASSFLOW"``.

    Returns
    -------
    KeyValue or None
        The key's value data, or ``None`` if the key is not found on the
        keyword.

    Raises
    ------
    KeywordNotFoundError
        If no keyword with the given tag exists in the file.
    """
    tree = load_opi(opi_path)
    kw_el = find_keyword_by_tag(tree, tag)
    if kw_el is None:
        raise KeywordNotFoundError(f"Keyword with tag '{tag}' not found")
    return get_key_values(kw_el, key_name)


def list_keywords(
    opi_path: Path,
    keyword_type: str | None = None,
    include_ncs: bool = True,
) -> list[OlgaKeyword]:
    """List all keywords in the file, optionally filtered by type.

    Iterates all keywords across case, library, and NC scopes.
    When *include_ncs* is True (the default), network components
    (NODE, FLOWPATH, ANNULUS) are also returned as OlgaKeyword entries
    using their PARAMETERS keys.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file.
    keyword_type : str or None
        If provided, only return keywords matching this type
        (e.g. ``"PIPE"``, ``"VALVE"``, ``"NODE"``, ``"FLOWPATH"``).
    include_ncs : bool
        Include network components as pseudo-keywords. Default True.

    Returns
    -------
    list[OlgaKeyword]
        All matching keywords.
    """
    tree = load_opi(opi_path)
    results: list[OlgaKeyword] = []

    for _scope, kw_el in iter_keywords(tree):
        kw = get_keyword_data(kw_el)
        if keyword_type is None or kw.keyword_type == keyword_type:
            results.append(kw)

    if include_ncs:
        for nc_el in iter_network_components(tree):
            nc = get_nc_data(nc_el)
            if keyword_type is None or nc.nc_type == keyword_type:
                nc_keys: dict[str, KeyValue] = {}
                for kw in nc.keywords:
                    if kw.keyword_type == "PARAMETERS":
                        nc_keys = kw.keys
                        break
                results.append(OlgaKeyword(
                    tag=nc.tag,
                    keyword_type=nc.nc_type,
                    keys=nc_keys,
                ))

    return results


def get_output_configuration(opi_path: Path) -> dict:
    """Get the current output configuration from the .opi file.

    Extracts TREND, PROFILE, TRENDDATA, and PROFILEDATA settings
    that control what OLGA writes to output files.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file.

    Returns
    -------
    dict
        Dictionary with keys:

        - ``"trend"``: dict of TREND_0 key-value pairs (DTPLOT, TIME)
        - ``"profile"``: dict of PROFILE_0 key-value pairs (DTPLOT, DTTIME)
        - ``"trend_data"``: list of dicts with tag, variables, position,
          parent_flowpath
        - ``"profile_data"``: list of dicts with tag, variables,
          parent_flowpath
    """
    tree = load_opi(opi_path)

    # ------------------------------------------------------------------
    # TREND_0 and PROFILE_0 case-level keywords
    # ------------------------------------------------------------------
    trend_config: dict[str, list[str]] = {}
    profile_config: dict[str, list[str]] = {}

    trend_el = find_keyword_by_tag(tree, "TREND_0")
    if trend_el is not None:
        trend_kw = get_keyword_data(trend_el)
        for key_name in ("DTPLOT", "TIME"):
            kv = trend_kw.keys.get(key_name)
            if kv:
                trend_config[key_name] = list(kv.values)

    profile_el = find_keyword_by_tag(tree, "PROFILE_0")
    if profile_el is not None:
        profile_kw = get_keyword_data(profile_el)
        for key_name in ("DTPLOT", "DTTIME"):
            kv = profile_kw.keys.get(key_name)
            if kv:
                profile_config[key_name] = list(kv.values)

    # ------------------------------------------------------------------
    # TRENDDATA and PROFILEDATA from all scopes
    # ------------------------------------------------------------------
    trend_data_list: list[dict] = []
    profile_data_list: list[dict] = []

    for _scope, kw_el in iter_keywords(tree):
        kw = get_keyword_data(kw_el)

        if kw.keyword_type == "TRENDDATA":
            variables: list[str] = []
            var_kv = kw.keys.get("VARIABLE")
            if var_kv:
                variables = list(var_kv.values)

            position = _get_key_value(kw, "POSITION")
            parent = _parent_flowpath_from_tag(kw.tag)

            trend_data_list.append({
                "tag": kw.tag,
                "variables": variables,
                "position": position,
                "parent_flowpath": parent,
            })

        elif kw.keyword_type == "PROFILEDATA":
            variables = []
            var_kv = kw.keys.get("VARIABLE")
            if var_kv:
                variables = list(var_kv.values)

            parent = _parent_flowpath_from_tag(kw.tag)

            profile_data_list.append({
                "tag": kw.tag,
                "variables": variables,
                "parent_flowpath": parent,
            })

    return {
        "trend": trend_config,
        "profile": profile_config,
        "trend_data": trend_data_list,
        "profile_data": profile_data_list,
    }
