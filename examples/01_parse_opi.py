"""Demonstrate reading an .opi model file.

Loads the synthetic sample.opi, walks every keyword across all three
scopes (Case, Library, NCCollection), prints a tag/type summary, and
extracts a single key value (PIPE LENGTH) to show how key data is
returned as a KeyValue dataclass with values + unit.

Run from project root:
    python examples/01_parse_opi.py
"""

from __future__ import annotations

from pathlib import Path

from olga_automation.opi_parser.xml_navigator import (
    find_keyword_by_tag,
    get_key_values,
    get_keyword_data,
    iter_keywords,
    iter_network_components,
    load_opi,
)


SAMPLE = Path(__file__).parent / "sample.opi"


def main() -> None:
    # Load the .opi as an XML tree (lxml ElementTree).
    tree = load_opi(SAMPLE)

    # Walk all keywords across Case + Library + NC scopes.
    # iter_keywords yields (scope, keyword_element) tuples; the scope is
    # "case", "library", or the NC tag string for NC-scoped keywords.
    print(f"Keywords in {SAMPLE.name}:")
    print(f"{'Scope':<14} {'Tag':<32} {'Type':<14}")
    print("-" * 64)

    total = 0
    for scope, kw_el in iter_keywords(tree):
        kw = get_keyword_data(kw_el)
        print(f"{scope:<14} {kw.tag:<32} {kw.keyword_type:<14}")
        total += 1

    # NCs (FLOWPATH/NODE/ANNULUS) are containers, not keywords themselves.
    nc_count = sum(1 for _ in iter_network_components(tree))
    print("-" * 64)
    print(f"Total keywords: {total}   Network components: {nc_count}")

    # Pull a specific key value out of one keyword.
    # find_keyword_by_tag searches all three scopes by <Tag> text.
    pipe = find_keyword_by_tag(tree, "FLOWPATH_1.PIPE_1")
    if pipe is None:
        raise SystemExit("FLOWPATH_1.PIPE_1 not found in sample.opi")

    length = get_key_values(pipe, "LENGTH")
    diameter = get_key_values(pipe, "DIAMETER")
    print()
    print("PIPE FLOWPATH_1.PIPE_1:")
    print(f"  LENGTH   = {length.values[0]} {length.unit}")
    print(f"  DIAMETER = {diameter.values[0]} {diameter.unit}")


if __name__ == "__main__":
    main()
