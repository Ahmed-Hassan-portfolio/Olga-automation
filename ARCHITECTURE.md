# Architecture

## Components

**`opi_parser`** — reads, validates, modifies, and writes OLGA `.opi` XML model files. Uses lxml (with stdlib `xml.etree` as fallback) for round-trip preservation of whitespace, attribute order, and element nesting that the OLGA GUI silently rejects when broken. Exposes a low-level `xml_navigator` (load/save, find-by-tag, iterate keywords across the three scopes — Case, Library, NCCollection) and higher-level `reader`/`writer` modules that compose those primitives into business objects (`ModelSummary`, `FlowpathInfo`, etc.) and convenience operations (`set_parameter`, `create_variant`, `add_keyword`, `remove_keyword`). Does NOT run simulations or parse outputs.

**`execution_manager`** — spawns the `opi.exe` solver as a subprocess and tracks each run's state, exit code, stdout, and produced output files. Single runs go through `run_simulation`; batches go through a thread-pool with a `threading.Semaphore` whose count is the OLGA license cap. Does NOT modify `.opi` files or interpret outputs; it only orchestrates the binary.

**`output_parser`** — parses the three OLGA output formats: `.tpl` (time-series trend data → `TrendData` with NumPy arrays keyed by `VarName@Position`), `.ppl` (spatial profile data → `ProfileData`, a 2D `time × position` grid per variable), and `.out` (text log → dict with completion status, warnings, errors). Each parser is pure-Python and operates only on bytes-on-disk; no OLGA install needed.

**`mcp_server`** — FastMCP-based server that exposes 20 tools spanning all three backend modules: read (`read_case_summary`, `list_keywords`, `get_parameter`, `get_output_config`), modify (`set_parameter`, `set_output_variables`, `create_variant`, `validate_model`, `add_keyword`, `remove_keyword`), execute (`run_simulation`, `run_simulation_async`, `get_run_status`, `cancel_run`, `parse_trend_data`, `parse_profile_data`, `get_simulation_log`), and batch (`build_sweep`, `run_batch`, `compare_runs`). Pydantic models serialize results to JSON-compatible payloads. Does NOT contain simulation logic itself — it's a thin protocol-level adapter.

**`cli`** — Typer-based CLI mirror of the MCP toolset. Each command shells out to the same backend functions and prints JSON to stdout. The CLI exists because MCP's stdio transport stalls when streaming large keyword dumps to a long-running sub-agent; a fresh subprocess per command sidesteps the pipe-buffer deadlock. Same API surface as MCP, different transport.

## Data flow on a single run

1. User (or LLM via MCP) calls `create_variant(base.opi, new.opi, modifications)`.
2. `opi_parser.writer.create_variant` copies the base file, loads the XML tree once, applies each `{tag, key, values, unit}` edit via `set_key_values`, and writes `new.opi`.
3. Caller invokes `execution_manager.runner.run_simulation(new.opi)`. The runner spawns `opi.exe new.opi` via `subprocess.Popen`; for batch runs, a `ThreadPoolExecutor` submits jobs and a `threading.Semaphore(N)` caps concurrent licenses in flight.
4. OLGA writes its output files (`.tpl`, `.ppl`, `.out`, `.rsw`) next to `new.opi` — no `-outDir` plumbing.
5. `output_parser.tpl_parser.parse_tpl` reads the `.tpl`, walks the OLGA-format header (version, network geometry, catalog of variables) and time-series block, and returns a `TrendData` whose `.variables` map gives a NumPy array per variable.
6. `output_parser.ppl_parser.parse_ppl` does the analogous job for `.ppl`, returning a `ProfileData` with a 2D `(n_timesteps, n_positions)` array per variable. `output_parser.out_parser.parse_out` extracts log-level status and any error/warning lines from the `.out` text log.
7. Results return to the caller. MCP serializes each dataclass through a Pydantic schema and emits JSON; the CLI prints the same JSON to stdout for sub-agents to consume.

## Key design decisions

- **lxml over xml.etree**: needed for accurate whitespace and attribute-order preservation. OLGA's GUI silently rejects round-tripped files that lose these, so the stricter parser is the default with stdlib as a fallback.
- **Subprocess (not Python bindings)**: OLGA has no public Python API; only `opi.exe` is exposed and licensed. Subprocess gives a clean process boundary, real exit codes, and natural per-run isolation.
- **Semaphore-based concurrency**: the OLGA license caps parallelism at N (typically 6 in our setup). A `ThreadPoolExecutor` plus `threading.Semaphore(N)` enforces it without polling and degrades cleanly when a long-running case blocks others.
- **Dataclasses for internal models, Pydantic for MCP I/O**: dataclasses are fast and mutable and live across the four backend modules; Pydantic only appears at the protocol boundary where strict schemas and JSON serialization actually pay off.
- **MCP via stdio plus a CLI mirror**: stdio transport is convenient for Claude integration but deadlocks on large keyword trees streamed from `list_keywords` on big models. The CLI gives sub-agents a fresh-subprocess JSON interface that bypasses the stdio pipe entirely.
- **Synthetic output generators in conftest**: lets the test suite run hermetically — no OLGA install, no proprietary `.opi` or `.tpl` data needed to verify the parsers against the exact byte format the solver emits.
- **Outputs colocated with the `.opi`**: matches how OLGA itself writes by default, eliminates `-outDir` plumbing, and avoids a class of "files written somewhere else" footguns.

## Orchestration layer

The four library modules + MCP server + CLI in this repo are the *primitive layer* - deterministic, testable Python. Real-world campaign workflows happen one level up, in a Claude Code skill (`.claude/skills/olga/SKILL.md`) that can compose this server with two adjacent MCP servers: [`flowsim-tutor`](https://github.com/Ahmed-Hassan-portfolio/flowsim-tutor) for documentation retrieval patterns, and [`multiflash-mcp`](https://github.com/Ahmed-Hassan-portfolio/multiflash-mcp) for PVT and EOS sanity checks.

The documentation side is intentionally split. The public `flowsim-tutor` repo ships synthetic, non-proprietary docs to demonstrate the RAG/workflow-memory layer. In a licensed private environment, the same interface can be pointed at OLGA keyword documentation. Vendor manuals and licensed reference material are not stored in this repository.

```
Claude Code session
      |
      +-- skill: olga campaign  (.claude/skills/olga/SKILL.md)
            |
            +-- MCP: olga-automation  (this repo: parse/modify/run/parse)
            +-- MCP: flowsim-tutor    (public synthetic docs; private OLGA docs adapter)
            +-- MCP: multiflash-mcp   (PVT/EOS; separate repo)
            |
            +-- subagents (parallel parsers, single analyst, runners, creators)
                  -- see .claude/agents/olga-*.md
```

The reason for the split: primitives are deterministic logic — easy to test, easy to version, easy to call from a library. Orchestration is fuzzy reasoning — which pressures to vary, when to query Multiflash for a saturation pressure, whether the model needs a structural change versus a value-only tweak, how to interpret a stalled solver. That kind of decision-making is better expressed in prompt-source-code (a skill) than in Python decision trees, and skills compose with other skills/servers in ways source code can't.

The four subagents implement a deliberate division: three sonnet-class workers (`olga-creator`, `olga-runner`, `olga-parser`) handle per-case mechanical work in parallel, conforming to a strict JSON schema; one opus-class analyst (`olga-analyst`) reasons across the set of cases serially. The schema is the synchronization primitive between them.
