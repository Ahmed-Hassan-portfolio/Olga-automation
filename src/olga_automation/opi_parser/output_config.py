"""Dynamic output variable configuration: set_output_variables.

Creates/replaces TRENDDATA and PROFILEDATA keywords in .opi files to
control what variables OLGA records during simulation. This is the key
function that makes the system dynamic -- before each run, Claude decides
what outputs are needed based on the engineering question.

XML schema reference (TRENDDATA):
    <Keyword>
      <Tag>FLOWPATH_7.TRENDDATA_22</Tag>
      <Type>TRENDDATA</Type>
      <KeyCollection>
        <Key Name="VARIABLE">
          <Values>
            <Value Unit="NoUnit">PT</Value>
            <Value Unit="NoUnit">TM</Value>
          </Values>
          <Unit/>
          <DefaultUnit>ValueUnitPair</DefaultUnit>
        </Key>
        <Key Name="POSITION">
          <Values><Value>WH</Value></Values>
          <Unit/>
          <DefaultUnit>NoUnit</DefaultUnit>
        </Key>
      </KeyCollection>
    </Keyword>
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from lxml import etree

from olga_automation.exceptions import KeywordNotFoundError
from olga_automation.opi_parser.xml_navigator import (
    find_nc_by_tag,
    iter_network_components,
    load_opi,
    save_opi,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_next_tag_number(nc_element) -> int:
    """Scan keywords in an NC element and return max tag suffix + 1.

    Parses the trailing ``_N`` from each keyword's ``<Tag>`` text and
    returns ``max(N) + 1``.  Returns 1 if no keywords have numeric
    suffixes.

    Parameters
    ----------
    nc_element : Element
        An ``<NC>`` XML element containing a ``<KeywordCollection>``.

    Returns
    -------
    int
        The next available tag number.
    """
    kw_collection = nc_element.find("KeywordCollection")
    if kw_collection is None:
        return 1

    max_num = 0
    for kw in kw_collection.findall("Keyword"):
        tag_el = kw.find("Tag")
        if tag_el is not None and tag_el.text:
            match = re.search(r"_(\d+)$", tag_el.text)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num

    return max_num + 1 if max_num > 0 else 1


def _remove_keywords_by_type(nc_element, keyword_type: str) -> None:
    """Remove all keywords of a given type from an NC element.

    Iterates over a copy of the keyword list to avoid mutation during
    iteration.

    Parameters
    ----------
    nc_element : Element
        An ``<NC>`` XML element.
    keyword_type : str
        The keyword type to remove, e.g. ``"TRENDDATA"`` or
        ``"PROFILEDATA"``.
    """
    kw_collection = nc_element.find("KeywordCollection")
    if kw_collection is None:
        return

    to_remove = []
    for kw in kw_collection.findall("Keyword"):
        type_el = kw.find("Type")
        if type_el is not None and type_el.text == keyword_type:
            to_remove.append(kw)

    for kw in to_remove:
        kw_collection.remove(kw)


def _add_variable_key(key_collection) -> object:
    """Add VARIABLE Key element scaffold to a KeyCollection.

    Creates the ``<Key Name="VARIABLE">`` with empty ``<Values>``,
    empty ``<Unit/>``, and ``<DefaultUnit>ValueUnitPair</DefaultUnit>``.

    Parameters
    ----------
    key_collection : Element
        The ``<KeyCollection>`` element to add the key to.

    Returns
    -------
    Element
        The ``<Values>`` element (caller appends Value children).
    """
    var_key = etree.SubElement(key_collection, "Key")
    var_key.set("Name", "VARIABLE")

    values_el = etree.SubElement(var_key, "Values")

    etree.SubElement(var_key, "Unit")  # empty <Unit/>

    default_unit_el = etree.SubElement(var_key, "DefaultUnit")
    default_unit_el.text = "ValueUnitPair"

    return values_el


def _add_variable_values(values_el, variables: list[str]) -> None:
    """Append ``<Value Unit="NoUnit">`` children to a Values element.

    Parameters
    ----------
    values_el : Element
        The ``<Values>`` element to append to.
    variables : list[str]
        Variable names, e.g. ``["PT", "TM"]``.
    """
    for var_name in variables:
        val_el = etree.SubElement(values_el, "Value")
        val_el.set("Unit", "NoUnit")
        val_el.text = var_name


def _create_trenddata_keyword(
    parent_kc,
    nc_tag: str,
    tag_num: int,
    variables: list[str],
    position: str,
) -> None:
    """Create a TRENDDATA keyword element and append it to parent_kc.

    Builds the full XML structure OLGA expects for trend output
    configuration including Variable values with ``Unit="NoUnit"``
    attributes and a POSITION key.

    Parameters
    ----------
    parent_kc : Element
        The ``<KeywordCollection>`` element to append to.
    nc_tag : str
        Parent NC tag, e.g. ``"FLOWPATH_7"``.
    tag_num : int
        Suffix number for the new keyword tag.
    variables : list[str]
        Variable names, e.g. ``["PT", "TM"]``.
    position : str
        Position label, e.g. ``"WH"``, ``"DHSV"``.
    """
    kw = etree.SubElement(parent_kc, "Keyword")

    tag_el = etree.SubElement(kw, "Tag")
    tag_el.text = f"{nc_tag}.TRENDDATA_{tag_num}"

    type_el = etree.SubElement(kw, "Type")
    type_el.text = "TRENDDATA"

    key_collection = etree.SubElement(kw, "KeyCollection")

    # VARIABLE key (shared structure)
    values_el = _add_variable_key(key_collection)
    _add_variable_values(values_el, variables)

    # POSITION key (TRENDDATA-specific)
    pos_key = etree.SubElement(key_collection, "Key")
    pos_key.set("Name", "POSITION")

    pos_values = etree.SubElement(pos_key, "Values")
    pos_val = etree.SubElement(pos_values, "Value")
    pos_val.text = position

    etree.SubElement(pos_key, "Unit")  # empty <Unit/>

    pos_default = etree.SubElement(pos_key, "DefaultUnit")
    pos_default.text = "NoUnit"


def _create_profiledata_keyword(
    parent_kc,
    nc_tag: str,
    tag_num: int,
    variables: list[str],
) -> None:
    """Create a PROFILEDATA keyword element and append it to parent_kc.

    Builds the full XML structure for profile output configuration.
    PROFILEDATA has no POSITION key -- profile data covers the entire
    flowpath length.

    Parameters
    ----------
    parent_kc : Element
        The ``<KeywordCollection>`` element to append to.
    nc_tag : str
        Parent NC tag, e.g. ``"FLOWPATH_7"``.
    tag_num : int
        Suffix number for the new keyword tag.
    variables : list[str]
        Variable names, e.g. ``["GT", "PT", "TM"]``.
    """
    kw = etree.SubElement(parent_kc, "Keyword")

    tag_el = etree.SubElement(kw, "Tag")
    tag_el.text = f"{nc_tag}.PROFILEDATA_{tag_num}"

    type_el = etree.SubElement(kw, "Type")
    type_el.text = "PROFILEDATA"

    key_collection = etree.SubElement(kw, "KeyCollection")

    # VARIABLE key (shared structure)
    values_el = _add_variable_key(key_collection)
    _add_variable_values(values_el, variables)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def set_output_variables(
    opi_path: Path,
    trend_vars: list[dict[str, str]] | None = None,
    profile_vars: list[dict[str, str]] | None = None,
    server_vars: list[str] | None = None,
    flowpath_tag: str | None = None,
) -> None:
    """Configure TRENDDATA and PROFILEDATA output keywords in an .opi file.

    This is the core function for dynamic output configuration. Before each
    simulation run, Claude decides what variables to record and calls this
    to update the .opi file.

    **Replace strategy:** Each call removes all existing keywords of the
    specified type from the target flowpath, then creates new ones.

    **None vs empty list:**
    - ``None`` means "leave existing unchanged" (do not touch)
    - ``[]`` (empty list) means "remove all existing"

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    trend_vars : list[dict] or None
        Trend variables to record. Each dict has ``"variable"`` and
        ``"position"`` keys.  Variables with the same position are grouped
        into one TRENDDATA keyword.  Example::

            [{"variable": "PT", "position": "WH"},
             {"variable": "TM", "position": "WH"},
             {"variable": "GT", "position": "DHSV"}]

        Creates 2 TRENDDATA keywords: one at WH with [PT, TM], one at
        DHSV with [GT].
    profile_vars : list[dict] or None
        Profile variables to record. Each dict has a ``"variable"`` key.
        All variables go into one PROFILEDATA keyword.  Example::

            [{"variable": "GT"}, {"variable": "PT"}]
    server_vars : list[str] or None
        Not supported in v1. Raises ``NotImplementedError``.
    flowpath_tag : str or None
        Target a specific flowpath NC by tag (e.g. ``"FLOWPATH_7"``).
        If ``None``, targets the first FLOWPATH-type NC found.

    Raises
    ------
    NotImplementedError
        If ``server_vars`` is not None.
    KeywordNotFoundError
        If ``flowpath_tag`` is specified but not found, or if no
        FLOWPATH NC exists in the file.
    """
    if server_vars is not None:
        raise NotImplementedError(
            "server_vars not supported in v1. Use trend_vars and profile_vars."
        )

    # Nothing to do
    if trend_vars is None and profile_vars is None:
        return

    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    # Find target NC
    if flowpath_tag is not None:
        nc = find_nc_by_tag(tree, flowpath_tag)
        if nc is None:
            raise KeywordNotFoundError(
                f"Flowpath '{flowpath_tag}' not found in {opi_path}"
            )
    else:
        # Find first FLOWPATH-type NC
        nc = None
        for nc_el in iter_network_components(tree):
            type_el = nc_el.find("Type")
            if type_el is not None and type_el.text == "FLOWPATH":
                nc = nc_el
                break
        if nc is None:
            raise KeywordNotFoundError(
                f"No FLOWPATH network component found in {opi_path}"
            )

    # Get the NC tag for naming new keywords
    nc_tag_el = nc.find("Tag")
    nc_tag_text = nc_tag_el.text if nc_tag_el is not None else "UNKNOWN"

    # Get the KeywordCollection
    kw_collection = nc.find("KeywordCollection")
    if kw_collection is None:
        kw_collection = etree.SubElement(nc, "KeywordCollection")

    # Handle trend_vars
    if trend_vars is not None:
        _remove_keywords_by_type(nc, "TRENDDATA")

        if trend_vars:
            # Group by position
            groups: dict[str, list[str]] = defaultdict(list)
            for tv in trend_vars:
                position = tv.get("position", "")
                variable = tv.get("variable", "")
                groups[position].append(variable)

            # Create one TRENDDATA keyword per position group
            for position, variables in groups.items():
                tag_num = _get_next_tag_number(nc)
                _create_trenddata_keyword(
                    kw_collection, nc_tag_text, tag_num, variables, position
                )

    # Handle profile_vars
    if profile_vars is not None:
        _remove_keywords_by_type(nc, "PROFILEDATA")

        if profile_vars:
            variables = [pv.get("variable", "") for pv in profile_vars]
            tag_num = _get_next_tag_number(nc)
            _create_profiledata_keyword(
                kw_collection, nc_tag_text, tag_num, variables
            )

    save_opi(tree, opi_path)
