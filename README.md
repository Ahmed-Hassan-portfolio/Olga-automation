# olga-automation

This repo is my agent-facing wrapper around OLGA-style flow-assurance workflows. It shows how I would let an LLM agent inspect a simulator model, make controlled edits, run batches, and parse outputs without handing the agent an unrestricted shell or proprietary project files.

The examples are synthetic, but the integration pattern is the real point: keep the simulator as the source of physics, expose a narrow typed tool layer, and make every run auditable by a human engineer.

## What's technically interesting

- **lxml round-trip of an undocumented vendor XML schema.** OLGA's GUI is picky about whitespace, attribute order, and the exact `Tag`/`Type`/`KeyCollection` structure of `.opi` files; the parser preserves all of it so edited models reopen cleanly.
- **FastMCP server registering 20 tools** (read, modify, run, parse) so an LLM agent can drive an entire simulation campaign conversationally — create variants, kick off batches, inspect logs, compare runs.
- **Dual entrypoint: MCP server AND Typer CLI.** The CLI exists specifically because MCP's stdio transport deadlocks when streaming large keyword trees from `list_keywords` on big models. Sub-agents get a stable fresh-subprocess JSON interface.
- **Semaphore-gated subprocess pool for batch execution**, sized to the OLGA license count (typically 6-10). Threads block on the semaphore rather than polling, so the runner respects the license without busy-waiting.
- **Synthetic-output generator fixtures** (`tests/conftest.py`) reproduce OLGA's `.tpl`/`.ppl`/`.out` formats byte-accurately, so the test suite runs hermetically without an OLGA install or any proprietary `.opi`/`.tpl` data.

## Architecture

The pipeline is linear: an `.opi` XML file is parsed and optionally edited, the resulting model is handed to an OLGA subprocess, and the three output formats (`.tpl`, `.ppl`, `.out`) are parsed back into typed objects. Both the MCP server and the CLI are thin adapters over the same four backend modules.

```
.opi (XML)  -->  opi_parser  -->  execution_manager  -->  opi.exe
                                         |
                    .tpl/.ppl/.out  <----+
                           |
                      output_parser  -->  TrendData / ProfileData / dict
                           ^
                           |
                 MCP server / CLI (twin entry points)
```

## Stack

Python 3.11+ · lxml · numpy · pydantic · FastMCP · Typer · pytest

## Evaluation and reproducibility

The test suite is the evaluation harness for the tool layer. **18 tests** pin the parsers and the model validator against byte-accurate synthetic fixtures so the agent-facing surface is verified without an OLGA install or proprietary data.

- **Synthetic OLGA-output generators** live in [tests/conftest.py](tests/conftest.py) (`create_synthetic_tpl`, `create_synthetic_ppl`, `create_synthetic_out`). Each generator emits a file that matches the real solver's byte layout — header block, NETWORK / GEOMETRY / CATALOG, columnar TIME SERIES, completion markers — and uses a deterministic data formula so expected values are computable in the assertion.
- **[tests/test_tpl_parser.py](tests/test_tpl_parser.py)** — 11 tests: structural shape, variable keying (`PT@WELLHEAD` vs. `GLOBAL` keyed by name alone), `VariableSeries` fields, time array endpoints, deterministic-value reconstruction (`1e7 - t*100 + i*1000`), metadata round-trip, missing-file error, custom variable lists, single and many-timestep edge cases.
- **[tests/test_validator.py](tests/test_validator.py)** — 7 tests with `subprocess.run` mocked: clean validation, error parsing, warnings-only stays valid, file-not-found, opi-command-not-on-PATH, timeout, raw-output preservation.
- **CI**: every push and PR runs `python -m pytest -q` on Python 3.11 ([.github/workflows/ci.yml](.github/workflows/ci.yml)). Pinned deps mean a fresh checkout reproduces the same 18 passes.

The deliberate gap: the live-OLGA path (`run_simulation`, `run_batch`) cannot be tested hermetically because it shells out to `opi.exe`. The runner and batch logic are covered by the synthetic-output round-trip plus mocked subprocesses; end-to-end live-run verification requires a real OLGA install and is out of scope for this portfolio repo.

## Try it

```bash
python -m venv .venv && .\.venv\Scripts\activate     # Windows
pip install -r requirements.txt
pip install -e .
python examples/01_parse_opi.py
pytest -q
```

## Status

Portfolio/research project maintained for demonstration and reproducibility. It uses synthetic examples and does not include proprietary OLGA models or simulator binaries.

## My Contribution

I designed and implemented the parser/writer boundary, MCP tool surface, CLI mirror, batch execution model, synthetic fixtures, and tests that make OLGA-style workflows callable by an LLM agent without shipping proprietary simulator data.

## Safety and limitations

- File access is scoped to user-supplied `.opi` paths; the tools never execute arbitrary shell commands on behalf of the agent.
- No proprietary OLGA models, customer data, or vendor binaries are shipped; examples use hand-authored synthetic fixtures.
- Simulation logs and model metadata are surfaced to the agent as untrusted text — treat them as a prompt-injection surface and require a human engineer to sign off on operational decisions.
- See [SECURITY.md](SECURITY.md) for the full set of agent-safety notes and failure modes.

## See also

This project is the transient-flow/simulator side of the portfolio. For the thermodynamic-tool side, see [`multiflash-mcp`](https://github.com/Ahmed-Hassan-portfolio/multiflash-mcp). For retrieval and workflow memory around technical documentation, see [`flowsim-tutor`](https://github.com/Ahmed-Hassan-portfolio/flowsim-tutor).
