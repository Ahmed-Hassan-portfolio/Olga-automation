"""Demonstrate creating a modified variant of an .opi model file.

Uses `create_variant` to clone sample.opi, apply a single edit
(PIPE DIAMETER 0.1 -> 0.15 m), and write the result to a temp file.
Then re-loads the variant to confirm the change persisted while the
original sample.opi is unchanged.

create_variant is the standard pattern for parameter studies: never
mutate the base model, always emit a new file. The base file is
copied with shutil.copy2 first, then edited in a single
load-modify-save cycle.

Run from project root:
    python examples/02_modify_keyword.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from olga_automation.opi_parser.writer import create_variant
from olga_automation.opi_parser.xml_navigator import (
    find_keyword_by_tag,
    get_key_values,
    load_opi,
)


SAMPLE = Path(__file__).parent / "sample.opi"
TARGET_TAG = "FLOWPATH_1.PIPE_1"
TARGET_KEY = "DIAMETER"
NEW_VALUE = "0.15"
NEW_UNIT = "m"


def read_diameter(opi_path: Path) -> tuple[str, str]:
    """Return (value, unit) for the target PIPE DIAMETER."""
    tree = load_opi(opi_path)
    pipe = find_keyword_by_tag(tree, TARGET_TAG)
    if pipe is None:
        raise SystemExit(f"{TARGET_TAG} not found in {opi_path}")
    kv = get_key_values(pipe, TARGET_KEY)
    return kv.values[0], kv.unit or ""


def main() -> None:
    # Before: confirm the baseline value on the sample model.
    before_val, before_unit = read_diameter(SAMPLE)
    print(f"Baseline {TARGET_TAG}.{TARGET_KEY} = {before_val} {before_unit}")

    # Write the variant into a temp directory so the repo stays clean.
    with tempfile.TemporaryDirectory(prefix="olga_variant_") as tmpdir:
        variant_path = Path(tmpdir) / "sample_d150mm.opi"

        # A modification list is the standard create_variant API:
        # each dict has {tag, key, values, unit}. Multiple edits in
        # one call share a single load/save round-trip.
        modifications = [
            {
                "tag": TARGET_TAG,
                "key": TARGET_KEY,
                "values": [NEW_VALUE],
                "unit": NEW_UNIT,
            },
        ]

        create_variant(
            base_opi=SAMPLE,
            output_opi=variant_path,
            modifications=modifications,
        )

        # After: re-read the variant and confirm the change landed.
        after_val, after_unit = read_diameter(variant_path)
        print(f"Variant  {TARGET_TAG}.{TARGET_KEY} = {after_val} {after_unit}")

        # And confirm the original was not touched.
        orig_val, _ = read_diameter(SAMPLE)
        assert orig_val == before_val, "create_variant should not mutate base"
        print(f"Original {TARGET_TAG}.{TARGET_KEY} = {orig_val} {before_unit} (unchanged)")


if __name__ == "__main__":
    main()
