"""Write operations for OLGA .opi files.

File-level write operations that compose Phase 1 XML navigator
primitives into convenient user-facing functions for modifying
OLGA .opi simulation models.

``set_parameter`` modifies a parameter in-place on disk.
``create_variant`` copies a base .opi and applies a batch of
modifications to produce a new variant file.
``add_keyword`` adds a new keyword to any scope (case, library, NC).
``add_network_component`` adds a new NC container to NCCollection.
``remove_keyword`` removes a keyword from any scope with output cleanup.
``remove_network_component`` removes an NC and all its children.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from olga_automation.exceptions import KeywordNotFoundError
from olga_automation.opi_parser.keyword_defaults import KEYWORD_DEFAULTS
from olga_automation.opi_parser.xml_navigator import (
    _find_keyword_and_parent,
    _find_keyword_collection,
    _find_nc_collection,
    _generate_unique_tag,
    _scan_dangling_references,
    etree,
    find_keyword_by_tag,
    find_nc_by_tag,
    get_key_values,
    iter_keywords,
    load_opi,
    save_opi,
    set_key_values,
    _element_text,
)

logger = logging.getLogger(__name__)


def set_parameter(
    opi_path: Path,
    tag: str,
    key_name: str,
    new_values: list[str],
    unit: str | None = None,
) -> None:
    """Modify a parameter in an .opi file in-place.

    Loads the file, finds the keyword by tag, updates the specified key
    with new values (and optionally a new unit), then saves back to disk.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify.
    tag : str
        Keyword tag, e.g. ``"FLOWPATH_7.SOURCE_18"``.
    key_name : str
        Key name within the keyword, e.g. ``"MASSFLOW"``.
    new_values : list[str]
        New value strings to write.
    unit : str or None
        If provided, also update the unit.

    Raises
    ------
    KeywordNotFoundError
        If no keyword with the given tag exists.
    OpiParseError
        If the file cannot be loaded (propagated from load_opi).
    """
    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    keyword = find_keyword_by_tag(tree, tag)
    if keyword is None:
        # Fallback: tag might be a bare NC tag (e.g. "NODE_10").
        # Find the NC element, then locate its primary keyword.
        nc_el = find_nc_by_tag(tree, tag)
        if nc_el is not None:
            nc_type = _element_text(nc_el, "Type")
            kw_collection = nc_el.find("KeywordCollection")
            if kw_collection is not None:
                for kw_el in kw_collection.findall("Keyword"):
                    kw_type = _element_text(kw_el, "Type")
                    if kw_type in ("PARAMETERS", nc_type):
                        keyword = kw_el
                        break
        if keyword is None:
            raise KeywordNotFoundError(
                f"Keyword with tag '{tag}' not found in {opi_path}"
            )

    set_key_values(keyword, key_name, [str(v) for v in new_values], unit)
    save_opi(tree, opi_path)


def _fix_pvt_path_in_tree(
    tree, src_dir: Path, dst_dir: Path, pvt_file: Path | None = None
) -> None:
    """Rewrite the PVTFILE relative path so it resolves from *dst_dir*.

    Finds the FILES keyword in *tree*, reads its PVTFILE key, resolves
    the path relative to *src_dir* (the original .opi location), and if
    the file exists, rewrites the value as a relative path from *dst_dir*.

    When the PVT file cannot be resolved from the source location:

    - If *pvt_file* is provided, the file is copied into a ``Multiflash/``
      subdirectory next to the destination .opi, and the PVTFILE key is
      updated to ``./Multiflash/{filename}``.
    - If *pvt_file* is **not** provided, a :class:`ValueError` is raised
      with a clear message asking the caller to supply the path.

    If there is no PVTFILE key at all, the function returns silently.

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi XML tree (modified in-place).
    src_dir : Path
        Parent directory of the source .opi file.
    dst_dir : Path
        Parent directory of the destination .opi file.
    pvt_file : Path or None
        Optional explicit path to the PVT file. Used as a fallback when the
        PVT file cannot be resolved from the source location.

    Raises
    ------
    ValueError
        If the PVT file cannot be resolved and *pvt_file* is not provided,
        or if *pvt_file* is provided but does not exist.
    """
    src_dir = Path(src_dir).resolve()
    dst_dir = Path(dst_dir).resolve()

    if src_dir == dst_dir and pvt_file is None:
        return  # Same directory; no path adjustment needed

    # Find the FILES keyword
    files_kw = None
    for _scope, kw_el in iter_keywords(tree):
        kw_type = _element_text(kw_el, "Type")
        if kw_type == "FILES":
            files_kw = kw_el
            break

    if files_kw is None:
        return

    kv = get_key_values(files_kw, "PVTFILE")
    if not kv or not kv.values or not kv.values[0]:
        return

    pvt_rel_path = kv.values[0]

    # Resolve the PVT file relative to the source .opi location
    pvt_absolute = (src_dir / pvt_rel_path).resolve()

    if not pvt_absolute.exists():
        # PVT file not found at source location -- use pvt_file fallback
        if pvt_file is not None:
            pvt_file = Path(pvt_file)
            if not pvt_file.exists():
                raise ValueError(
                    f"Provided pvt_file does not exist: '{pvt_file}'"
                )
            # Copy PVT file into Multiflash/ subdirectory next to the destination .opi
            mf_dir = dst_dir / "Multiflash"
            mf_dir.mkdir(parents=True, exist_ok=True)
            dst_pvt = mf_dir / pvt_file.name
            shutil.copy2(pvt_file, dst_pvt)

            # Update the PVTFILE key to the co-location convention
            new_rel_path = f"./Multiflash/{pvt_file.name}"
            set_key_values(files_kw, "PVTFILE", [new_rel_path])
            logger.info(
                "Copied PVT file '%s' -> '%s' and updated PVTFILE to '%s'",
                pvt_file,
                dst_pvt,
                new_rel_path,
            )
            return
        else:
            raise ValueError(
                f"PVT file not found. The .opi references '{pvt_rel_path}' "
                f"which resolves to '{pvt_absolute}' (does not exist). "
                f"Please provide the pvt_file parameter with the correct "
                f"path to the PVT file."
            )

    # Compute the new relative path from the destination directory
    try:
        new_rel_path = os.path.relpath(pvt_absolute, dst_dir)
    except ValueError:
        # os.path.relpath raises ValueError on Windows when paths are on
        # different drives. Fall back to absolute path.
        new_rel_path = str(pvt_absolute)

    # Normalize to forward slashes for OLGA compatibility
    new_rel_path = new_rel_path.replace("\\", "/")

    if new_rel_path != pvt_rel_path:
        set_key_values(files_kw, "PVTFILE", [new_rel_path])
        logger.info(
            "Adjusted PVTFILE path: '%s' -> '%s'",
            pvt_rel_path,
            new_rel_path,
        )


def create_variant(
    base_opi: Path,
    output_opi: Path,
    modifications: list[dict[str, Any]],
    pvt_file: str | Path | None = None,
) -> Path:
    """Create a variant .opi file from a base model with modifications.

    Copies the base .opi to the output path, then applies all
    modifications in a single load-modify-save cycle. The base file
    is never modified.

    Each modification dict has the following keys:

    - ``tag`` (str): Keyword tag to modify.
    - ``key`` (str): Key name within the keyword.
    - ``values`` (list[str]): New values to set.
    - ``unit`` (str, optional): New unit to set.

    Parameters
    ----------
    base_opi : Path
        Path to the base .opi file. Must exist.
    output_opi : Path
        Path for the new variant file. Parent directories are created
        if they do not exist.
    modifications : list[dict]
        List of modification dicts to apply.
    pvt_file : str, Path, or None
        Optional path to a PVT fluid property file (``.tab``). Required
        when the base model's PVT path won't resolve from the new variant
        location. The file is copied into a ``Multiflash/`` subdirectory
        next to the variant and the PVTFILE key is updated accordingly.

    Returns
    -------
    Path
        The output_opi path (for chaining convenience).

    Raises
    ------
    FileNotFoundError
        If base_opi does not exist.
    KeywordNotFoundError
        If any modification references a tag that does not exist.
    ValueError
        If the PVT file cannot be resolved and *pvt_file* is not provided,
        or if the provided *pvt_file* does not exist.
    """
    base_opi = Path(base_opi)
    output_opi = Path(output_opi)

    if not base_opi.exists():
        raise FileNotFoundError(f"Base .opi file not found: {base_opi}")

    # Create parent directories for the output file
    output_opi.parent.mkdir(parents=True, exist_ok=True)

    # Copy the base file (preserving metadata)
    shutil.copy2(base_opi, output_opi)

    # Load the copy once for PVT fix + modifications, save once at the end
    tree = load_opi(output_opi)

    # Fix PVT file path: if the source .opi references a PVT file via a
    # relative path, recompute the relative path from the new location so
    # that OLGA can still find it.
    pvt_path = Path(pvt_file) if pvt_file is not None else None
    _fix_pvt_path_in_tree(tree, base_opi.parent, output_opi.parent, pvt_file=pvt_path)

    # If no modifications, save the (possibly PVT-fixed) copy and return
    if not modifications:
        save_opi(tree, output_opi)
        return output_opi

    for mod in modifications:
        tag = mod["tag"]
        keyword = find_keyword_by_tag(tree, tag)
        if keyword is None:
            # Fallback: tag might be a bare NC tag (e.g. "NODE_10").
            nc_el = find_nc_by_tag(tree, tag)
            if nc_el is not None:
                nc_type = _element_text(nc_el, "Type")
                kw_collection = nc_el.find("KeywordCollection")
                if kw_collection is not None:
                    for kw_el in kw_collection.findall("Keyword"):
                        kw_type = _element_text(kw_el, "Type")
                        if kw_type in ("PARAMETERS", nc_type):
                            keyword = kw_el
                            break
            if keyword is None:
                raise KeywordNotFoundError(
                    f"Keyword with tag '{tag}' not found in {output_opi}"
                )

        set_key_values(
            keyword,
            mod["key"],
            [str(v) for v in mod["values"]],
            mod.get("unit"),
        )

    save_opi(tree, output_opi)
    return output_opi


# ---------------------------------------------------------------------------
# Add keyword / NC
# ---------------------------------------------------------------------------


def _build_key_element(parent, key_name: str, key_data: dict) -> None:
    """Build a ``<Key>`` XML element under parent.

    Parameters
    ----------
    parent : Element
        The ``<KeyCollection>`` element to append to.
    key_name : str
        The key name attribute, e.g. ``"MASSFLOW"``.
    key_data : dict
        Dict with ``"values"`` (list[str]), ``"unit"`` (str or None),
        and optionally ``"default_unit"`` (str).
    """
    key_el = etree.SubElement(parent, "Key")
    key_el.set("Name", key_name)

    values_el = etree.SubElement(key_el, "Values")
    for val_str in key_data.get("values", []):
        val_el = etree.SubElement(values_el, "Value")
        val_el.text = str(val_str)

    unit_el = etree.SubElement(key_el, "Unit")
    unit_value = key_data.get("unit")
    if unit_value is not None:
        unit_el.text = unit_value
    else:
        # Empty <Unit/> -- no text
        pass

    default_unit_el = etree.SubElement(key_el, "DefaultUnit")
    default_unit = key_data.get("default_unit")
    if default_unit:
        default_unit_el.text = default_unit
    elif unit_value:
        default_unit_el.text = unit_value
    else:
        default_unit_el.text = "NoUnit"


def _build_output_var_keyword(
    parent_kc,
    tag_text: str,
    keyword_type: str,
    output_vars: list[dict],
) -> None:
    """Build a TRENDDATA or PROFILEDATA keyword element.

    Parameters
    ----------
    parent_kc : Element
        The ``<KeywordCollection>`` to append to.
    tag_text : str
        The tag for the new keyword.
    keyword_type : str
        Either ``"TRENDDATA"`` or ``"PROFILEDATA"``.
    output_vars : list[dict]
        Output variable dicts. For TRENDDATA, each has ``"variable"``
        and optionally ``"position"``, ``"leak"``, ``"valve"``, or
        ``"source"``. For PROFILEDATA, only ``"variable"``.
    """
    kw = etree.SubElement(parent_kc, "Keyword")

    tag_el = etree.SubElement(kw, "Tag")
    tag_el.text = tag_text

    type_el = etree.SubElement(kw, "Type")
    type_el.text = keyword_type

    key_collection = etree.SubElement(kw, "KeyCollection")

    # VARIABLE key with Value Unit="NoUnit" and DefaultUnit="ValueUnitPair"
    var_key = etree.SubElement(key_collection, "Key")
    var_key.set("Name", "VARIABLE")

    values_el = etree.SubElement(var_key, "Values")
    for ov in output_vars:
        val_el = etree.SubElement(values_el, "Value")
        val_el.set("Unit", "NoUnit")
        val_el.text = ov.get("variable", "")

    etree.SubElement(var_key, "Unit")  # empty <Unit/>

    default_unit_el = etree.SubElement(var_key, "DefaultUnit")
    default_unit_el.text = "ValueUnitPair"

    # Reference keys (TRENDDATA only): POSITION, LEAK, VALVE, SOURCE
    if keyword_type == "TRENDDATA":
        # Collect unique references for each key type
        ref_keys = ["position", "leak", "valve", "source"]
        for ref_key in ref_keys:
            refs = []
            for ov in output_vars:
                ref = ov.get(ref_key)
                if ref and ref not in refs:
                    refs.append(ref)

            if refs:
                ref_el = etree.SubElement(key_collection, "Key")
                ref_el.set("Name", ref_key.upper())

                ref_values = etree.SubElement(ref_el, "Values")
                for ref in refs:
                    ref_val = etree.SubElement(ref_values, "Value")
                    ref_val.text = ref

                etree.SubElement(ref_el, "Unit")  # empty <Unit/>

                ref_default = etree.SubElement(ref_el, "DefaultUnit")
                ref_default.text = "NoUnit"


def add_keyword(
    opi_path: Path,
    keyword_type: str,
    keys: dict | None = None,
    parent_tag: str | None = None,
    output_vars: list[dict] | None = None,
) -> str:
    """Add a new keyword to an .opi file.

    Creates a new ``<Keyword>`` element with the specified type under the
    target scope (case-level, library, or within an NC). Generates a
    unique tag automatically. Pre-populates OLGA defaults for known
    keyword types.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    keyword_type : str
        The keyword type, e.g. ``"SOURCE"``, ``"VALVE"``, ``"TRENDDATA"``.
    keys : dict or None
        Key-value data to set. Dict of ``{key_name: {"values": [...],
        "unit": str_or_None}}``. Caller-provided keys override any
        defaults from ``KEYWORD_DEFAULTS``.
    parent_tag : str or None
        - ``None`` -- add at case level
        - ``"Library"`` -- add at library level
        - NC tag -- add under that NC's KeywordCollection
    output_vars : list[dict] or None
        For TRENDDATA/PROFILEDATA keywords. Each dict has ``"variable"``
        and optionally ``"position"`` and ``"unit"`` keys.

    Returns
    -------
    str
        The generated tag for the new keyword.

    Raises
    ------
    KeywordNotFoundError
        If ``parent_tag`` references a non-existent NC.
    """
    if not keyword_type or not keyword_type.strip():
        raise ValueError("keyword_type must be a non-empty string")

    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    # Generate unique tag
    scope = parent_tag  # None=case, "Library"=library, else NC tag
    tag = _generate_unique_tag(tree, keyword_type, scope=scope)

    # Find target KeywordCollection
    kc = _find_keyword_collection(tree, parent_tag=parent_tag)

    # Handle output variable keywords (TRENDDATA/PROFILEDATA)
    if keyword_type in ("TRENDDATA", "PROFILEDATA") and output_vars:
        _build_output_var_keyword(kc, tag, keyword_type, output_vars)
        save_opi(tree, opi_path)
        return tag

    # Build standard keyword element
    kw = etree.SubElement(kc, "Keyword")

    tag_el = etree.SubElement(kw, "Tag")
    tag_el.text = tag

    type_el = etree.SubElement(kw, "Type")
    type_el.text = keyword_type

    key_collection = etree.SubElement(kw, "KeyCollection")

    # Merge defaults with caller-provided keys
    merged_keys: dict[str, dict] = {}

    # Step 1: Load defaults for this keyword type
    defaults = KEYWORD_DEFAULTS.get(keyword_type)
    if defaults is not None:
        for key_name, key_data in defaults.items():
            merged_keys[key_name] = dict(key_data)  # shallow copy
    else:
        logger.debug("No defaults available for %s", keyword_type)

    # Step 2: Caller-provided keys override defaults
    if keys:
        for key_name, key_data in keys.items():
            merged_keys[key_name] = key_data

    # Step 3: Build Key elements
    for key_name, key_data in merged_keys.items():
        if not key_data.get("values"):
            logger.warning(
                "Key '%s' on %s has no values specified", key_name, keyword_type
            )
        if key_data.get("unit") is None and key_name not in (
            "SOURCETYPE", "EQUILIBRIUMMODEL", "STEADYSTATE", "COMPOSITIONAL",
            "FLASHMODEL", "FLOWMODEL", "SOLVER", "LICENSE", "READFILE",
            "INTERPOLATION", "HOUTEROPTION",
        ):
            logger.warning(
                "Key '%s' on %s has no unit specified", key_name, keyword_type
            )
        _build_key_element(key_collection, key_name, key_data)

    save_opi(tree, opi_path)
    return tag


def add_network_component(
    opi_path: Path,
    nc_type: str,
    label: str,
    initial_keywords: list[dict] | None = None,
) -> str:
    """Add a new network component to the NCCollection.

    Creates an ``<NC>`` element with ``<Tag>``, ``<Type>``, and an
    empty ``<KeywordCollection>``. Optionally populates initial child
    keywords.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    nc_type : str
        The NC type, e.g. ``"FLOWPATH"``, ``"NODE"``, ``"ANNULUS"``.
    label : str
        Human-readable label (stored but not used in tag generation;
        tag is auto-generated like ``"FLOWPATH_8"``).
    initial_keywords : list[dict] or None
        Optional list of keyword dicts to create inside the new NC.
        Each dict has ``"keyword_type"`` (str) and optionally ``"keys"``
        (dict) and ``"output_vars"`` (list[dict]).

    Returns
    -------
    str
        The generated tag for the new NC.

    Raises
    ------
    OpiParseError
        If NCCollection is not found.
    """
    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    nc_collection = _find_nc_collection(tree)

    # Generate unique NC tag by scanning existing NCs
    tag = _generate_unique_tag(tree, nc_type, scope="__nc__")

    # Build NC element
    nc = etree.SubElement(nc_collection, "NC")

    tag_el = etree.SubElement(nc, "Tag")
    tag_el.text = tag

    type_el = etree.SubElement(nc, "Type")
    type_el.text = nc_type

    kw_collection = etree.SubElement(nc, "KeywordCollection")

    # Add initial keywords if provided
    if initial_keywords:
        for kw_spec in initial_keywords:
            kw_type = kw_spec["keyword_type"]
            kw_keys = kw_spec.get("keys")
            kw_output_vars = kw_spec.get("output_vars")

            # Generate child keyword tag
            child_tag = f"{tag}.{kw_type}_1"

            # Build keyword element in-memory (not via add_keyword which
            # saves to disk each time -- we batch into one save)
            kw = etree.SubElement(kw_collection, "Keyword")

            kw_tag_el = etree.SubElement(kw, "Tag")
            kw_tag_el.text = child_tag

            kw_type_el = etree.SubElement(kw, "Type")
            kw_type_el.text = kw_type

            key_coll = etree.SubElement(kw, "KeyCollection")

            # Merge defaults with caller keys
            merged: dict[str, dict] = {}
            defaults = KEYWORD_DEFAULTS.get(kw_type)
            if defaults:
                for k, v in defaults.items():
                    merged[k] = dict(v)
            if kw_keys:
                for k, v in kw_keys.items():
                    merged[k] = v

            for key_name, key_data in merged.items():
                _build_key_element(key_coll, key_name, key_data)

    save_opi(tree, opi_path)
    return tag


# ---------------------------------------------------------------------------
# Remove keyword / NC
# ---------------------------------------------------------------------------


def _cleanup_output_references(
    tree, removed_tag: str, removed_label: str | None = None
) -> None:
    """Auto-cleanup stale TRENDDATA/PROFILEDATA references after keyword removal.

    Scans all TRENDDATA and PROFILEDATA keywords across the tree. If a
    TRENDDATA/PROFILEDATA keyword's POSITION key contains the removed
    keyword's label, that entire TRENDDATA/PROFILEDATA keyword is removed
    (since it references a position that no longer exists).

    Parameters
    ----------
    tree : ElementTree
        Parsed .opi tree (modified in-place).
    removed_tag : str
        The tag of the keyword that was removed.
    removed_label : str or None
        The LABEL value of the removed keyword, if it had one.
    """
    if removed_label is None:
        return

    # Collect output keywords to remove (can't modify while iterating)
    to_remove: list[tuple] = []

    for scope, kw_el in iter_keywords(tree):
        kw_type = _element_text(kw_el, "Type")
        if kw_type not in ("TRENDDATA", "PROFILEDATA"):
            continue

        key_collection = kw_el.find("KeyCollection")
        if key_collection is None:
            continue

        # Check POSITION key values
        for key_el in key_collection.findall("Key"):
            if key_el.get("Name") != "POSITION":
                continue

            values_el = key_el.find("Values")
            if values_el is None:
                continue

            for val_el in values_el.findall("Value"):
                val_text = val_el.text
                if val_text and val_text.strip() == removed_label:
                    # This TRENDDATA/PROFILEDATA references the removed label
                    to_remove.append(kw_el)
                    break
            break  # Only one POSITION key per keyword

    # Remove the stale output keywords
    for kw_el in to_remove:
        result = _find_keyword_and_parent(
            tree, _element_text(kw_el, "Tag") or ""
        )
        if result is not None:
            kw, parent_kc = result
            parent_kc.remove(kw)


def remove_keyword(opi_path: Path, tag: str) -> bool:
    """Remove a keyword from an .opi file by tag.

    Finds the keyword with the given tag across all scopes (case,
    library, NC) and removes it. Also auto-cleans any TRENDDATA or
    PROFILEDATA keywords that reference the removed keyword's label
    in their POSITION key.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    tag : str
        The keyword tag to remove, e.g. ``"FLOWPATH_7.SOURCE_18"``.

    Returns
    -------
    bool
        ``True`` if the keyword was found and removed, ``False`` if
        no keyword with the given tag exists (logged as warning).
    """
    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    result = _find_keyword_and_parent(tree, tag)
    if result is None:
        logger.warning("Keyword '%s' not found in %s", tag, opi_path)
        return False

    keyword_el, parent_kc = result

    # Extract label for output cleanup before removing
    removed_label: str | None = None
    key_collection = keyword_el.find("KeyCollection")
    if key_collection is not None:
        for key_el in key_collection.findall("Key"):
            if key_el.get("Name") == "LABEL":
                values_el = key_el.find("Values")
                if values_el is not None:
                    val_el = values_el.find("Value")
                    if val_el is not None and val_el.text:
                        removed_label = val_el.text.strip()
                break

    # Remove the keyword from its parent KeywordCollection
    parent_kc.remove(keyword_el)

    # Auto-cleanup stale output references
    _cleanup_output_references(tree, tag, removed_label)

    save_opi(tree, opi_path)
    return True


def remove_network_component(opi_path: Path, nc_tag: str) -> bool:
    """Remove a network component and all its children from an .opi file.

    Finds the NC with the given tag in NCCollection and removes the
    entire ``<NC>`` element (including all child keywords). Before
    removing, scans for dangling references from other keywords that
    reference children of this NC, and logs a warning if any are found.

    Parameters
    ----------
    opi_path : Path
        Path to the .opi file to modify (in-place).
    nc_tag : str
        The NC tag to remove, e.g. ``"FLOWPATH_7"``.

    Returns
    -------
    bool
        ``True`` if the NC was found and removed, ``False`` if no NC
        with the given tag exists (logged as warning).
    """
    opi_path = Path(opi_path)
    tree = load_opi(opi_path)

    nc_el = find_nc_by_tag(tree, nc_tag)
    if nc_el is None:
        logger.warning("NC '%s' not found in %s", nc_tag, opi_path)
        return False

    # Scan for dangling references before removing
    dangling = _scan_dangling_references(tree, nc_tag)
    if dangling:
        logger.warning(
            "Removing %s will create dangling references: %s",
            nc_tag,
            "; ".join(dangling),
        )

    # Find NCCollection parent and remove the NC element
    nc_collection = _find_nc_collection(tree)
    nc_collection.remove(nc_el)

    save_opi(tree, opi_path)
    return True
