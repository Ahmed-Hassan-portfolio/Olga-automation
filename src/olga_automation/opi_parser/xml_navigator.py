"""Low-level XML traversal for .opi files.

Provides functions to load, save, iterate, find, read, and write
keyword data in OLGA .opi XML files. Works with lxml (preferred)
or stdlib xml.etree.ElementTree as a fallback.

XPath constants define the three keyword scopes:
  - Case-level: APIData > Case > KeywordCollection > Keyword
  - Library:    APIData > Case > Library > Flowpath > KeywordCollection > Keyword
  - NC-level:   APIData > Case > NCCollection > NC > KeywordCollection > Keyword

All public functions operate on ElementTree objects returned by load_opi().
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

try:
    from lxml import etree

    USING_LXML = True
except ImportError:
    import xml.etree.ElementTree as etree  # type: ignore[no-redef]

    USING_LXML = False

from olga_automation.exceptions import KeywordNotFoundError, OpiParseError
from olga_automation.opi_parser.models import (
    Connection,
    KeyValue,
    NetworkComponent,
    OlgaKeyword,
)

# ---------------------------------------------------------------------------
# XPath patterns (from RESEARCH.md)
# These work with both lxml and stdlib findall().
# ---------------------------------------------------------------------------

CASE_KEYWORDS_XPATH = ".//APIData/Case/KeywordCollection/Keyword"
LIBRARY_KEYWORDS_XPATH = (
    ".//APIData/Case/Library/Flowpath/KeywordCollection/Keyword"
)
NC_COLLECTION_XPATH = ".//APIData/Case/NCCollection"
NC_XPATH = ".//APIData/Case/NCCollection/NC"
CONNECTION_XPATH = (
    ".//APIData/Case/NCCollection/ConnectionCollection/Connection"
)


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def load_opi(opi_path: Path):
    """Load an .opi file into an XML ElementTree.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file.

    Returns
    -------
    ElementTree
        Parsed XML tree (lxml or stdlib).

    Raises
    ------
    OpiParseError
        If the file does not exist or contains invalid XML.
    """
    opi_path = Path(opi_path)
    if not opi_path.exists():
        raise OpiParseError(f"OPI file not found: {opi_path}")
    try:
        tree = etree.parse(str(opi_path))
    except Exception as exc:
        raise OpiParseError(
            f"Failed to parse OPI file {opi_path}: {exc}"
        ) from exc
    return tree


def save_opi(tree, opi_path: Path) -> None:
    """Save an XML tree back to an .opi file.

    Writes with XML declaration and UTF-8 encoding.

    Parameters
    ----------
    tree : ElementTree
        The XML tree to write.
    opi_path : Path
        Destination path.
    """
    opi_path = Path(opi_path)
    try:
        tree.write(
            str(opi_path),
            xml_declaration=True,
            encoding="utf-8",
        )
    except Exception as exc:
        raise OpiParseError(
            f"Failed to save OPI file {opi_path}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_apidata_case(tree):
    """Return the ``APIData/Case`` element from the tree.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.

    Returns
    -------
    Element
        The ``<Case>`` element under ``<APIData>``.

    Raises
    ------
    OpiParseError
        If the element is not found.
    """
    root = tree.getroot()
    case = root.find(".//APIData/Case")
    if case is None:
        raise OpiParseError(
            "Could not find APIData/Case element in .opi file"
        )
    return case


def _element_text(element, child_tag: str) -> str | None:
    """Get the text content of a direct child element, or None."""
    child = element.find(child_tag)
    if child is None:
        return None
    text = child.text
    if text is not None:
        text = text.strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------


def iter_keywords(tree) -> Iterator[tuple[str, object]]:
    """Iterate ALL keywords across all three scopes.

    Yields ``(scope, keyword_element)`` tuples where:

    - ``scope='case'`` for Case > KeywordCollection > Keyword
    - ``scope='library'`` for Library > Flowpath > KeywordCollection > Keyword
    - ``scope=nc_tag`` (e.g. ``'FLOWPATH_7'``) for NC-level keywords

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.

    Yields
    ------
    tuple[str, Element]
        (scope string, Keyword XML element)
    """
    root = tree.getroot()

    # 1. Case-level keywords
    for kw_el in root.findall(CASE_KEYWORDS_XPATH):
        yield ("case", kw_el)

    # 2. Library keywords
    for kw_el in root.findall(LIBRARY_KEYWORDS_XPATH):
        yield ("library", kw_el)

    # 3. NC-level keywords (inside each NC's KeywordCollection)
    for nc_el in root.findall(NC_XPATH):
        nc_tag = _element_text(nc_el, "Tag") or "UNKNOWN_NC"
        kw_collection = nc_el.find("KeywordCollection")
        if kw_collection is None:
            continue
        for kw_el in kw_collection.findall("Keyword"):
            yield (nc_tag, kw_el)


def iter_network_components(tree) -> Iterator[object]:
    """Iterate all ``<NC>`` elements in NCCollection.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.

    Yields
    ------
    Element
        Each ``<NC>`` XML element.
    """
    root = tree.getroot()
    yield from root.findall(NC_XPATH)


# ---------------------------------------------------------------------------
# Finders
# ---------------------------------------------------------------------------


def find_keyword_by_tag(tree, tag: str):
    """Find a Keyword element by its ``<Tag>`` text.

    Searches all three scopes (case, library, NC-level).

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    tag : str
        The keyword tag to find, e.g. ``"OPTIONS_0"`` or
        ``"FLOWPATH_7.VALVE_15"``.

    Returns
    -------
    Element or None
        The matching ``<Keyword>`` element, or ``None`` if not found.
    """
    for _scope, kw_el in iter_keywords(tree):
        kw_tag = _element_text(kw_el, "Tag")
        if kw_tag == tag:
            return kw_el
    return None


def find_nc_by_tag(tree, nc_tag: str):
    """Find an NC element by its ``<Tag>`` text.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    nc_tag : str
        The NC tag to find, e.g. ``"FLOWPATH_7"`` or ``"NODE_9"``.

    Returns
    -------
    Element or None
        The matching ``<NC>`` element, or ``None`` if not found.
    """
    for nc_el in iter_network_components(tree):
        tag_text = _element_text(nc_el, "Tag")
        if tag_text == nc_tag:
            return nc_el
    return None


# ---------------------------------------------------------------------------
# Keyword data extraction
# ---------------------------------------------------------------------------


def _parse_key_element(key_el) -> KeyValue:
    """Parse a single ``<Key>`` element into a KeyValue dataclass."""
    name = key_el.get("Name", "")

    # Parse values
    values: list[str] = []
    values_el = key_el.find("Values")
    if values_el is not None:
        for val_el in values_el.findall("Value"):
            text = val_el.text
            values.append(text.strip() if text else "")

    # Parse unit -- <Unit /> or <Unit></Unit> means None
    unit_el = key_el.find("Unit")
    unit: str | None = None
    if unit_el is not None:
        unit_text = unit_el.text
        if unit_text is not None:
            unit_text = unit_text.strip()
            if unit_text:
                unit = unit_text

    # Parse default unit
    default_unit = _element_text(key_el, "DefaultUnit") or ""

    return KeyValue(
        name=name,
        values=values,
        unit=unit,
        default_unit=default_unit,
    )


def get_keyword_data(keyword_el) -> OlgaKeyword:
    """Parse a Keyword XML element into an ``OlgaKeyword`` dataclass.

    Reads the ``<Tag>``, ``<Type>``, and all ``<Key>`` children from
    the ``<KeyCollection>``.

    Parameters
    ----------
    keyword_el : Element
        A ``<Keyword>`` XML element.

    Returns
    -------
    OlgaKeyword
        Parsed keyword with all key-value data.
    """
    tag = _element_text(keyword_el, "Tag") or ""
    keyword_type = _element_text(keyword_el, "Type") or ""

    keys: dict[str, KeyValue] = {}
    key_collection = keyword_el.find("KeyCollection")
    if key_collection is not None:
        for key_el in key_collection.findall("Key"):
            kv = _parse_key_element(key_el)
            keys[kv.name] = kv

    return OlgaKeyword(tag=tag, keyword_type=keyword_type, keys=keys)


def get_key_values(keyword_el, key_name: str) -> KeyValue | None:
    """Get a specific key's values from a Keyword element.

    Parameters
    ----------
    keyword_el : Element
        A ``<Keyword>`` XML element.
    key_name : str
        The key name attribute to look for, e.g. ``"MASSFLOW"``.

    Returns
    -------
    KeyValue or None
        The parsed key data, or ``None`` if the key is not found.
    """
    key_collection = keyword_el.find("KeyCollection")
    if key_collection is None:
        return None

    for key_el in key_collection.findall("Key"):
        if key_el.get("Name") == key_name:
            return _parse_key_element(key_el)

    return None


# ---------------------------------------------------------------------------
# Keyword data modification
# ---------------------------------------------------------------------------


def set_key_values(
    keyword_el,
    key_name: str,
    new_values: list[str],
    unit: str | None = None,
) -> None:
    """Set values for a specific key on a Keyword element.

    If the key exists, clears its current ``<Value>`` elements and writes
    new ones.  If ``unit`` is provided, also updates the ``<Unit>`` element.

    If the key does not exist, creates a new ``<Key>`` element with
    ``Name`` attribute, ``<Values>``, ``<Unit>``, and ``<DefaultUnit>``
    children.

    Parameters
    ----------
    keyword_el : Element
        A ``<Keyword>`` XML element.
    key_name : str
        The key name attribute, e.g. ``"MASSFLOW"``.
    new_values : list[str]
        New value strings to write.
    unit : str or None
        If provided, update the ``<Unit>`` element text.
    """
    key_collection = keyword_el.find("KeyCollection")

    # If KeyCollection doesn't exist (self-closing <KeyCollection />),
    # we need to create a proper one.
    if key_collection is None:
        # Remove any existing empty self-closing KeyCollection element.
        # In lxml, find returns None for self-closing elements only if they
        # truly don't exist. But <KeyCollection /> is a valid empty element.
        # Let's look harder -- iterate direct children.
        key_collection = None
        for child in keyword_el:
            if child.tag == "KeyCollection":
                key_collection = child
                break

        if key_collection is None:
            key_collection = etree.SubElement(keyword_el, "KeyCollection")

    # Find existing key
    target_key = None
    for key_el in key_collection.findall("Key"):
        if key_el.get("Name") == key_name:
            target_key = key_el
            break

    if target_key is not None:
        # Key exists -- update values
        values_el = target_key.find("Values")
        if values_el is None:
            values_el = etree.SubElement(target_key, "Values")

        # Clear existing Value elements
        for old_val in list(values_el.findall("Value")):
            values_el.remove(old_val)

        # Write new values
        for val_str in new_values:
            val_el = etree.SubElement(values_el, "Value")
            val_el.text = val_str

        # Update unit if provided
        if unit is not None:
            unit_el = target_key.find("Unit")
            if unit_el is None:
                unit_el = etree.SubElement(target_key, "Unit")
            unit_el.text = unit
    else:
        # Key does not exist -- create it
        new_key = etree.SubElement(key_collection, "Key")
        new_key.set("Name", key_name)

        values_el = etree.SubElement(new_key, "Values")
        for val_str in new_values:
            val_el = etree.SubElement(values_el, "Value")
            val_el.text = val_str

        unit_el = etree.SubElement(new_key, "Unit")
        if unit is not None:
            unit_el.text = unit

        default_unit_el = etree.SubElement(new_key, "DefaultUnit")
        default_unit_el.text = "NoUnit"


# ---------------------------------------------------------------------------
# Network component parsing
# ---------------------------------------------------------------------------


def get_nc_data(nc_el) -> NetworkComponent:
    """Parse an NC XML element into a ``NetworkComponent`` dataclass.

    Parameters
    ----------
    nc_el : Element
        An ``<NC>`` XML element.

    Returns
    -------
    NetworkComponent
        Parsed network component with its keywords.
    """
    tag = _element_text(nc_el, "Tag") or ""
    nc_type = _element_text(nc_el, "Type") or ""

    keywords: list[OlgaKeyword] = []
    kw_collection = nc_el.find("KeywordCollection")
    if kw_collection is not None:
        for kw_el in kw_collection.findall("Keyword"):
            keywords.append(get_keyword_data(kw_el))

    return NetworkComponent(tag=tag, nc_type=nc_type, keywords=keywords)


# ---------------------------------------------------------------------------
# Connection parsing
# ---------------------------------------------------------------------------


def get_connections(tree) -> list[Connection]:
    """Parse all Connection elements from ConnectionCollection.

    Each Connection has a ``<Tag>`` and multiple ``<Terminal>`` elements
    with ``Name`` and ``NCTag`` attributes.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.

    Returns
    -------
    list[Connection]
        All parsed connections.
    """
    root = tree.getroot()
    connections: list[Connection] = []

    for conn_el in root.findall(CONNECTION_XPATH):
        tag = _element_text(conn_el, "Tag") or ""
        terminals: list[dict[str, str]] = []

        for term_el in conn_el.findall("Terminal"):
            terminal = {
                "Name": term_el.get("Name", ""),
                "NCTag": term_el.get("NCTag", ""),
            }
            terminals.append(terminal)

        connections.append(Connection(tag=tag, terminals=terminals))

    return connections


# ---------------------------------------------------------------------------
# Add-keyword helpers
# ---------------------------------------------------------------------------


def _generate_unique_tag(tree, keyword_type: str, scope=None) -> str:
    """Generate a unique tag for a new keyword of the given type.

    Scans existing tags in the relevant scope to find the highest numeric
    suffix, then returns ``max + 1``.  If no existing keywords of that
    type exist, starts at 1.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    keyword_type : str
        The keyword type, e.g. ``"SOURCE"``, ``"VALVE"``.
    scope : str or None
        - ``None`` -- case-level (tags like ``"SOURCE_1"``)
        - ``"Library"`` -- library-level (tags like ``"Library.MATERIAL_2"``)
        - ``"__nc__"`` -- top-level NC (tags like ``"FLOWPATH_8"``)
        - NC tag string -- NC-level keywords (tags like ``"FLOWPATH_7.SOURCE_19"``)

    Returns
    -------
    str
        A unique tag string for the new keyword.
    """
    import re

    # Determine prefix and collect existing tags in scope
    if scope is None:
        # Case-level: scan case keywords
        prefix = ""
        existing_tags: list[str] = []
        root = tree.getroot()
        for kw_el in root.findall(CASE_KEYWORDS_XPATH):
            tag_text = _element_text(kw_el, "Tag")
            if tag_text:
                existing_tags.append(tag_text)
    elif scope == "Library":
        # Library-level: scan library keywords
        prefix = "Library."
        existing_tags = []
        root = tree.getroot()
        for kw_el in root.findall(LIBRARY_KEYWORDS_XPATH):
            tag_text = _element_text(kw_el, "Tag")
            if tag_text:
                existing_tags.append(tag_text)
    elif scope == "__nc__":
        # Top-level NC: scan NC tags in NCCollection
        prefix = ""
        existing_tags = []
        root = tree.getroot()
        for nc_el in root.findall(NC_XPATH):
            tag_text = _element_text(nc_el, "Tag")
            if tag_text:
                existing_tags.append(tag_text)
    else:
        # NC-level: scan keywords within the specified NC
        prefix = f"{scope}."
        existing_tags = []
        nc_el = find_nc_by_tag(tree, scope)
        if nc_el is not None:
            kw_collection = nc_el.find("KeywordCollection")
            if kw_collection is not None:
                for kw_el in kw_collection.findall("Keyword"):
                    tag_text = _element_text(kw_el, "Tag")
                    if tag_text:
                        existing_tags.append(tag_text)

    # Find the max numeric suffix for this keyword_type among existing tags
    # Pattern: look for tags ending in {TYPE}_{N}
    max_num = 0
    pattern = re.compile(rf"(?:^|\.){re.escape(keyword_type)}_(\d+)$")
    for tag in existing_tags:
        match = pattern.search(tag)
        if match:
            num = int(match.group(1))
            if num > max_num:
                max_num = num

    next_num = max_num + 1 if max_num > 0 else 1
    return f"{prefix}{keyword_type}_{next_num}"


def _find_keyword_collection(tree, parent_tag=None):
    """Return the appropriate KeywordCollection element for the given scope.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    parent_tag : str or None
        - ``None`` -- returns Case > KeywordCollection
        - ``"Library"`` -- returns Library > Flowpath > KeywordCollection
        - NC tag string -- returns that NC's KeywordCollection
          (creates one if the NC exists but has no KeywordCollection)

    Returns
    -------
    Element
        The ``<KeywordCollection>`` element.

    Raises
    ------
    KeywordNotFoundError
        If the specified parent cannot be found.
    """
    root = tree.getroot()

    if parent_tag is None:
        # Case-level
        case = root.find(".//APIData/Case")
        if case is None:
            raise KeywordNotFoundError(
                "Could not find APIData/Case in .opi tree"
            )
        kc = case.find("KeywordCollection")
        if kc is None:
            kc = etree.SubElement(case, "KeywordCollection")
        return kc

    if parent_tag == "Library":
        # Library-level
        flowpath = root.find(".//APIData/Case/Library/Flowpath")
        if flowpath is None:
            raise KeywordNotFoundError(
                "Could not find Library/Flowpath in .opi tree"
            )
        kc = flowpath.find("KeywordCollection")
        if kc is None:
            kc = etree.SubElement(flowpath, "KeywordCollection")
        return kc

    # NC-level: find the NC by tag
    nc_el = find_nc_by_tag(tree, parent_tag)
    if nc_el is None:
        raise KeywordNotFoundError(
            f"Network component with tag '{parent_tag}' not found"
        )
    kc = nc_el.find("KeywordCollection")
    if kc is None:
        kc = etree.SubElement(nc_el, "KeywordCollection")
    return kc


def _find_nc_collection(tree):
    """Return the NCCollection element from the tree.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.

    Returns
    -------
    Element
        The ``<NCCollection>`` element.

    Raises
    ------
    OpiParseError
        If NCCollection is not found.
    """
    root = tree.getroot()
    nc_coll = root.find(NC_COLLECTION_XPATH)
    if nc_coll is None:
        raise OpiParseError("NCCollection not found in .opi tree")
    return nc_coll


# ---------------------------------------------------------------------------
# Remove-keyword helpers
# ---------------------------------------------------------------------------


def _find_keyword_and_parent(tree, tag: str):
    """Find a keyword and its parent KeywordCollection by tag.

    Searches all three scopes (case, library, NC) for a keyword with
    the given tag. Returns both the keyword element and the parent
    ``<KeywordCollection>`` element so that the caller can remove the
    keyword from the parent.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    tag : str
        The keyword tag to find, e.g. ``"FLOWPATH_7.SOURCE_18"``.

    Returns
    -------
    tuple[Element, Element] or None
        ``(keyword_element, parent_keyword_collection)`` if found,
        or ``None`` if no keyword with the given tag exists.
    """
    root = tree.getroot()

    # 1. Case-level keywords
    case_kc = root.find(".//APIData/Case/KeywordCollection")
    if case_kc is not None:
        for kw_el in case_kc.findall("Keyword"):
            kw_tag = _element_text(kw_el, "Tag")
            if kw_tag == tag:
                return (kw_el, case_kc)

    # 2. Library keywords
    lib_kc = root.find(
        ".//APIData/Case/Library/Flowpath/KeywordCollection"
    )
    if lib_kc is not None:
        for kw_el in lib_kc.findall("Keyword"):
            kw_tag = _element_text(kw_el, "Tag")
            if kw_tag == tag:
                return (kw_el, lib_kc)

    # 3. NC-level keywords
    for nc_el in root.findall(NC_XPATH):
        kw_collection = nc_el.find("KeywordCollection")
        if kw_collection is None:
            continue
        for kw_el in kw_collection.findall("Keyword"):
            kw_tag = _element_text(kw_el, "Tag")
            if kw_tag == tag:
                return (kw_el, kw_collection)

    return None


def _scan_dangling_references(tree, nc_tag: str) -> list[str]:
    """Scan for keywords outside an NC that reference its children.

    A reference is any ``<Value>`` text that starts with ``{nc_tag}.``
    found in keywords that are NOT inside the specified NC. Returns a
    list of human-readable warning strings describing each dangling
    reference found.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree.
    nc_tag : str
        The NC tag being removed, e.g. ``"FLOWPATH_7"``.

    Returns
    -------
    list[str]
        Warning strings like ``"FLOWPATH_10.CONTROLLER_3 key CONTROLLED
        references FLOWPATH_7.VALVE_15"``.
    """
    prefix = f"{nc_tag}."
    warnings: list[str] = []

    for scope, kw_el in iter_keywords(tree):
        # Skip keywords that are inside the NC being removed
        if scope == nc_tag:
            continue

        kw_tag = _element_text(kw_el, "Tag") or "UNKNOWN"
        key_collection = kw_el.find("KeyCollection")
        if key_collection is None:
            continue

        for key_el in key_collection.findall("Key"):
            key_name = key_el.get("Name", "")
            values_el = key_el.find("Values")
            if values_el is None:
                continue

            for val_el in values_el.findall("Value"):
                val_text = val_el.text
                if val_text and val_text.startswith(prefix):
                    warnings.append(
                        f"{kw_tag} key {key_name} references {val_text}"
                    )

    return warnings
