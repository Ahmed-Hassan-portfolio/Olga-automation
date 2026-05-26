# Architecture

This project has two layers:

1. A deterministic Python tool layer that works with simulator files.
2. A prompt-based orchestration layer that tells agents when and how to use those tools.

The design goal is simple: an LLM can help run a simulation campaign, but it only acts through narrow, inspectable tools.

## System Map

```text
Claude Code session
    |
    v
OLGA campaign skill
    |
    +--> optional flowsim-tutor lookup
    +--> optional multiflash-mcp thermodynamic check
    |
    v
Subagents
    |
    +--> olga-creator: create one .opi variant
    +--> olga-runner: run one case
    +--> olga-parser: parse one case
    +--> olga-analyst: compare cases
    |
    v
olga-automation tool layer
    |
    +--> MCP server for interactive LLM tool calls
    +--> CLI for fresh subprocess calls from subagents
    |
    v
Python backend modules
    |
    +--> opi_parser
    +--> execution_manager
    +--> output_parser
```

The public repo contains the OLGA automation tool layer and the orchestration prompts. It does not contain OLGA, OLGA manuals, customer models, or licensed data.

## Layer 1: Python Tool Layer

### `opi_parser`

Owns `.opi` model-file inspection and editing.

It can:

- read model summaries,
- list keywords,
- read one parameter,
- set one parameter,
- create a new variant from a base model,
- add or remove keywords,
- validate a model through `opi.exe` when available.

The key technical point is XML preservation. OLGA `.opi` files are XML-like, but the GUI is sensitive to structure, tags, key order, and formatting. The parser uses `lxml` where possible so edited files can be reopened by the simulator.

### `execution_manager`

Owns live simulation execution.

It builds a fixed command list for `opi.exe` and runs it with `subprocess.Popen(..., shell=False)`. It passes `-outDir` explicitly, tracks status, captures stdout/stderr, handles timeouts, and can cancel a running case.

OLGA may still write outputs beside the `.opi` file on some installations. The runner therefore searches both the requested output directory and the model directory, then normalizes discovered outputs for downstream parsing.

Batch runs use a semaphore so the code does not start more simulations than the local license/hardware policy allows.

### `output_parser`

Owns result-file parsing.

It reads:

- `.tpl` trend files into time-series structures,
- `.ppl` profile files into time-position grids,
- `.out` logs into status, warnings, and errors.

The parsers are pure Python and run without OLGA. That is why the public test suite can verify most of the agent-facing surface without a commercial simulator install.

### `mcp_server`

Owns LLM-facing tool schemas.

It exposes 20 tools across model inspection, model modification, execution, output parsing, and batch comparison. The MCP server is best for small interactive calls, such as reading a case summary or checking one parameter.

### `cli`

Owns subprocess-friendly access to the same backend.

The CLI mirrors the MCP tools and prints JSON to stdout. Subagents use the CLI because each command starts a fresh process. That avoids long-lived stdio pipes stalling when a large model or output file produces a large response.

## Layer 2: Agent Orchestration

The Python layer does not decide what study to run. It only exposes safe operations.

The orchestration layer lives in:

- `.claude/skills/olga/SKILL.md`
- `.claude/agents/olga-creator.md`
- `.claude/agents/olga-runner.md`
- `.claude/agents/olga-parser.md`
- `.claude/agents/olga-analyst.md`

The skill acts as the campaign controller. It checks the user's intent, decides which variants are needed, assigns work to subagents, waits for their JSON outputs, and asks for human confirmation when the requested change is ambiguous or risky.

The four agents have separate jobs:

| Agent | Scope | Why separate |
|---|---|---|
| `olga-creator` | One model variant | Keeps model edits small and verifiable. |
| `olga-runner` | One simulation run | Protects existing outputs and avoids accidental parallel runs. |
| `olga-parser` | One result set | Extracts structured JSON without cross-case speculation. |
| `olga-analyst` | Whole campaign | Performs cross-case reasoning after all data is parsed. |

This separation keeps mechanical work parallelizable while keeping engineering interpretation in one place.

## Optional Companion Tools

### `flowsim-tutor`

The public `flowsim-tutor` repo demonstrates a documentation-tutor pattern with synthetic docs. It is not an OLGA manual.

In a private licensed environment, the same retrieval layer can point at approved OLGA keyword documentation. That lets the agent look up keyword semantics and allowed values without publishing vendor material.

### `multiflash-mcp`

`multiflash-mcp` provides deterministic thermodynamic calculations through MCP. The OLGA analyst agent can use it to check saturation pressure, density, phase boundaries, or other fluid-property context before making an engineering interpretation.

## End-To-End Flow

1. The user asks for a study, such as a pressure sweep.
2. The skill checks whether the request changes one factor or many.
3. Optional documentation lookup finds valid keyword/value choices.
4. Optional Multiflash calls check whether the requested operating range crosses a phase boundary.
5. Creator agents create `.opi` variants through the CLI.
6. Runner agents run cases through the CLI, one at a time by default.
7. Parser agents convert `.tpl`, `.ppl`, and `.out` files into JSON.
8. The analyst agent compares cases and writes an engineering summary.
9. The user receives a report with assumptions, warnings, and next steps.

## Key Design Choices

### Typed tool boundary

Agents do not freely edit files or run arbitrary shell strings. They call named tools with typed inputs. This keeps behavior auditable.

### CLI plus MCP

MCP is useful for interactive tool calls. The CLI is safer for subagents and large outputs because each command is a fresh subprocess.

### Simulator as source of physics

The agent does not infer simulator behavior from text. It edits model files, runs the licensed simulator, parses the simulator outputs, and reports what it found.

### Public-safe data boundary

The repo uses synthetic `.opi`, `.tpl`, `.ppl`, and `.out` fixtures. It proves the automation pattern without publishing protected data.

### Human review gates

The workflow asks for human confirmation when a change affects multiple study factors, when documentation is unavailable, or when a result could affect an operational decision.

## What Is Tested Publicly

Public CI runs without OLGA.

It verifies:

- parser behavior on synthetic output files,
- model validation behavior with mocked subprocess calls,
- CLI importability and JSON-facing behavior,
- error handling for missing files and timeouts.

Live execution through `opi.exe` is not tested in public CI because it requires a licensed OLGA installation.

## Known Limits

- The public repo cannot demonstrate a real live run without OLGA.
- Public `flowsim-tutor` uses synthetic docs, not OLGA manuals.
- The orchestration layer is prompt-source-code; it is reviewable, but it requires a Claude Code session to execute end to end.
- Human engineers must approve operational conclusions.
