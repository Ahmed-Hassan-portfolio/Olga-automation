# Examples

Short scripts that exercise the parser/writer paths of `olga-automation`. None of these run an OLGA simulation — they only touch `opi_parser` and `output_parser`, so they work without an OLGA install or license.

## Sample data

- `sample.opi` — a hand-authored synthetic OPI XML file with three Case-level keywords (`OPTIONS`, `INTEGRATION`, `OUTPUT`) and one network component (`FLOWPATH_1` with a `PIPE`). Not a real well or production model; the schema is just enough to demonstrate the parser/writer pipeline.
- `sample.tpl` — a hand-authored minimal OLGA `.tpl` (header, NETWORK / GEOMETRY / BRANCH, CATALOG, columnar TIME SERIES) with three variables on a single-branch network. Matches the byte layout the real solver emits and that the parser expects.

## Scripts

- **`01_parse_opi.py`** — loads `sample.opi`, iterates every keyword across the three OPI scopes (Case / Library / NCCollection), and prints one key's value with its unit.
- **`02_modify_keyword.py`** — uses `create_variant` to clone `sample.opi` into a temp file with one key edited (PIPE `DIAMETER` 0.1 -> 0.15 m), then re-reads the variant and verifies the base file is untouched.
- **`03_parse_trend.py`** — parses `sample.tpl` with `parse_tpl`, prints the OLGA version, time-array shape, every variable's min/max, and a sample slice from the first variable's NumPy array.

## Running

From the project root with the package installed editable (`pip install -e .`):

```bash
python examples/01_parse_opi.py
python examples/02_modify_keyword.py
python examples/03_parse_trend.py
```
