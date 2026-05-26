# olga-automation

AI-agent-safe automation layer for OLGA-style flow-simulator work.

OLGA is a commercial engineering simulator used for transient flow studies. This repo does not include OLGA. It shows how I would let an AI agent work around that kind of simulator without giving it free access to a shell, vendor manuals, customer models, or licensed data.

The agent gets typed tools: inspect a model, create a variant, validate it, run a case, parse outputs, and hand the result back to a human engineer.

The public examples are synthetic. The architecture is the point.

## What I Built

Flow-simulator studies are slow and easy to break. A small mistake in a model file can waste a long run; a missing output variable can make a successful run useless. This project wraps that workflow in a controlled tool layer.

The repo has five parts:

| Part | What it does |
|---|---|
| `opi_parser` | Reads and edits OLGA `.opi` XML model files while preserving structure the GUI expects. |
| `execution_manager` | Starts the OLGA command-line solver (`opi.exe`) through a fixed subprocess command, tracks status, handles timeouts, and respects license-aware concurrency. |
| `output_parser` | Parses `.tpl`, `.ppl`, and `.out` simulator outputs into structured Python objects and JSON. |
| `mcp_server` | Exposes 20 typed tools to an LLM agent through MCP, the Model Context Protocol. |
| `cli` | Mirrors the same tools as terminal commands so subagents can call fresh subprocesses instead of long-lived MCP pipes. |

On top of that tool layer, the repo includes a Claude Code orchestration layer:

- `.claude/skills/olga/SKILL.md` describes the campaign workflow.
- `.claude/agents/olga-creator.md` creates one model variant.
- `.claude/agents/olga-runner.md` runs one case safely.
- `.claude/agents/olga-parser.md` extracts one case into JSON.
- `.claude/agents/olga-analyst.md` compares cases and adds thermodynamic interpretation.

That split is deliberate: Python handles deterministic mechanics; prompts handle planning, review, and multi-case reasoning.

## Model-Agnostic Boundary

I used Claude Code to demonstrate the workflow, so the shipped skill and agent files use Claude Code's `.claude/` format. The underlying automation is not tied to Claude as a model.

Any agent runtime can reuse the same backend if it can call one of these interfaces:

- MCP tools from `mcp_server`,
- JSON-returning CLI commands from `python -m olga_automation.cli`,
- the Python modules directly.

For example, a Gemini-, OpenAI-, or local-LLM-based agent could use the same CLI/MCP tool layer. The `.claude/skills` files are the reference orchestration prompts; another agent framework would translate that workflow into its own prompt, planner, or tool-calling format.

## What This Is Not

This is not OLGA, an OLGA clone, or an OLGA documentation dump.

It does not include:

- OLGA binaries or license files,
- OLGA manuals or vendor keyword references,
- customer models,
- real production data,
- proprietary simulator outputs.

The public repo is safe to inspect because it uses hand-written synthetic fixtures. In a private licensed environment, the same architecture can be pointed at real simulator installs and approved internal documentation.

## How an Agent Uses It

```text
User request
    |
    v
Claude Code skill decides the campaign plan
    |
    +--> optional docs lookup through flowsim-tutor
    +--> optional thermodynamic checks through multiflash-mcp
    |
    v
Subagents call the olga-automation CLI/MCP tools
    |
    +--> create .opi variants
    +--> validate model files
    +--> run OLGA cases when a licensed install exists
    +--> parse .tpl/.ppl/.out outputs
    |
    v
One analyst agent writes the cross-case engineering summary
```

The companion repos are optional:

- [`flowsim-tutor`](https://github.com/Ahmed-Hassan-portfolio/flowsim-tutor) demonstrates the documentation-tutor pattern with synthetic public docs. In private use, the same pattern can point at licensed OLGA keyword documentation.
- [`multiflash-mcp`](https://github.com/Ahmed-Hassan-portfolio/multiflash-mcp) exposes thermodynamic calculations for fluid properties and phase-boundary checks.

## Why It Matters

For an AI/LLM engineering reviewer, the interesting parts are:

- typed tool boundaries instead of unrestricted shell access,
- model-agnostic backend access through MCP, CLI, or Python modules,
- MCP tools plus a CLI fallback for long or large responses,
- multi-agent division of labor with strict JSON handoffs,
- human-review gates around model edits and operational conclusions,
- synthetic tests that verify the public parts without licensed software.

For an engineering reviewer, the important constraint is that the simulator remains the source of physics. The agent edits, runs, parses, and summarizes; it does not invent thermodynamics.

## If You Only Have Five Minutes

Start here:

1. Read this README for the purpose and safety boundary.
2. Read [ARCHITECTURE.md](ARCHITECTURE.md) for the two-layer design.
3. Read [WORKFLOW.md](WORKFLOW.md) for one end-to-end campaign example.
4. Skim `.claude/skills/olga/SKILL.md` to see the agent orchestration rules.
5. Run `pytest -q` to verify the public parser and validation layer.

## Architecture

```text
                  Claude Code orchestration
        skill + creator/runner/parser/analyst agents
                              |
                              v
                    MCP server / CLI wrapper
                              |
        +---------------------+---------------------+
        |                     |                     |
        v                     v                     v
   opi_parser          execution_manager       output_parser
  .opi XML I/O          opi.exe process       .tpl/.ppl/.out
        |                     |                     |
        +---------- synthetic tests + CI -----------+
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full component review and [WORKFLOW.md](WORKFLOW.md) for a campaign walkthrough.

## Try It Without OLGA

The public examples do not require an OLGA install.

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
pip install -e .

python examples/01_parse_opi.py
python examples/02_modify_keyword.py
python examples/03_parse_trend.py
pytest -q
```

Expected result: the examples print small structured summaries, and pytest reports `18 passed`.

## Evaluation and CI

The test suite verifies the public tool layer with synthetic data:

- parser behavior for `.tpl` and `.ppl`-style files,
- `.opi` validation behavior with mocked subprocess calls,
- missing-file and timeout handling,
- stable JSON-facing behavior for the agent surface.

Live `run_simulation` and `run_batch` require a licensed OLGA install because they call `opi.exe`. Those paths are intentionally not exercised in public CI.

Every push runs `python -m pytest -q` on Python 3.11 through GitHub Actions.

## Safety

- The tools operate on user-supplied model paths and fixed command tokens.
- `subprocess.Popen` is called with `shell=False`.
- Existing outputs are backed up before re-runs in the agent workflow.
- Simulator logs and model metadata are treated as untrusted text.
- Human engineers remain responsible for operational decisions.

See [SECURITY.md](SECURITY.md) for the full safety notes.

## Status

Portfolio/research project maintained for demonstration and reproducibility.

## My Contribution

I designed and implemented the parser/writer boundary, MCP tool surface, CLI mirror, batch execution model, synthetic fixtures, tests, and the agent orchestration prompts that make OLGA-style workflows callable by an LLM agent without publishing proprietary simulator material.
