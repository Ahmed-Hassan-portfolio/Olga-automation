# Workflow — end-to-end campaign example

A worked example of how a single user request flows through the two-layer architecture, showing cross-MCP composition and where each component owns which decision.

## Scenario

A user with `olga-automation`, `flowsim-tutor`, and `multiflash-mcp` all registered as MCP servers in their Claude Code session types:

> Create 5 variants of `base.opi` varying injection pressure from 20 to 200 bar. Check what materials are available and change to a CO2-compatible one. Summarize cross-case behavior.

Total Python code in `olga-automation` involved in interpreting that prompt: **zero**. All prompt-to-action translation happens in the LLM by reading `.claude/skills/olga/SKILL.md`. The Python in this repo only runs once the skill has decided exactly which deterministic calls to make.

## The 10-step flow

### 1. Skill activation
Claude loads `.claude/skills/olga/SKILL.md`: sub-commands, output-config verification protocol, parser/analyst handoff schema, data-protection rules, single-factor discipline. This is the operating manual for the campaign.

### 2. Pre-flight (single-factor check)
Skill calls primitives in this repo:
- `olga-automation.read_case_summary(base.opi)` — current model state.
- `olga-automation.get_parameter(base.opi, "NODE_10", "PRESSURE")` — current value and unit.

If more than one Tier-1 factor would change between base and variants, the skill halts and asks the user to confirm. Single-factor discipline is enforced by the **skill**, not by the primitive code.

### 3. Material discovery — cross-MCP call to `flowsim-tutor`
Skill calls `flowsim-tutor.search_docs("MATERIAL keyword")` to retrieve valid material values from OLGA's keyword reference. Without `flowsim-tutor`, this would require either hard-coding the list inside the skill (brittle, ages with OLGA releases) or interrupting the user.

`flowsim-tutor` is a separate sibling project. NOT bundled here.

### 4. PVT sanity check — cross-MCP call to `multiflash-mcp`
Skill calls `multiflash.get_saturation_pressure(fluid="pure CO2", temperature=...)` to verify that the proposed 20-200 bar range does not cross a phase boundary the user did not intend to cross. If P_sat is inside the range, the skill surfaces it and asks before proceeding.

`multiflash-mcp` is a separate sibling project. NOT bundled here.

### 5. Variant generation — parallel, inside this repo
Skill spawns 5 `olga-creator` subagents (see `.claude/agents/olga-creator.md`). Each runs in parallel and calls the CLI (not MCP, to avoid stdio deadlock on long-lived pipes):

```bash
python -m olga_automation.cli modify create-variant base.opi variant_<P>bar.opi \
  --modifications '[{"tag":"NODE_10","key":"PRESSURE","values":["<P>"],"unit":"bara"}]'
```

Each subagent verifies the output config (TRENDDATA / PROFILEDATA) before returning a JSON status the orchestrator consumes.

### 6. Execution — parallel, inside this repo
Skill spawns 5 `olga-runner` subagents. Each calls:

```bash
python -m olga_automation.cli execute run-simulation variant_<P>bar.opi
```

Concurrency is capped by the OLGA license — the `threading.Semaphore` in `execution_manager.runner` enforces this at the Python layer regardless of how many subagents the skill spawns. The skill cannot exceed the license; it can only fail to saturate it.

### 7. Parsing — parallel, inside this repo
Skill spawns 5 `olga-parser` subagents. Each parses one case's `.tpl` / `.ppl` into structured JSON conforming to the schema spelled out in `.claude/agents/olga-parser.md`. The strict schema is the synchronization primitive between the parallel workers and the next serial stage.

### 8. Cross-case analysis — serial, inside this repo, optional cross-MCP
Skill spawns ONE `olga-analyst` subagent (opus-class — reasoning, not mechanics). It reads all 5 parser JSON outputs together. Optionally re-queries `multiflash-mcp` to cross-validate observed fluid densities against the EOS at the simulated conditions. Produces a single cross-case report.

### 9. Documentation
Skill updates a project-level campaign registry. The registry itself lives in the user's project tree, not in this repo.

### 10. Final summary
Skill returns the analyst's report to the user: pressure vs. peak flow rate, identified anomalies, suggested next steps.

## What each layer owned

| Decision | Who decided |
|---|---|
| What pressures to use (linear 20-200) | User + Skill (LLM reasoning) |
| Single-factor sanity check | Skill |
| Which material to pick | Skill + `flowsim-tutor` (cross-MCP doc lookup) |
| Whether the pressure range is physically reasonable | Skill + `multiflash-mcp` (cross-MCP PVT check) |
| How to write a parameter change into XML | `olga-automation` primitive code |
| How to spawn `opi.exe` and capture exit codes | `olga-automation` primitive code |
| How to parse `.tpl` bytes into NumPy arrays | `olga-automation` primitive code |
| When to spawn subagents in parallel vs. serial | Skill |
| Per-case JSON output schema | Subagent markdown |
| What cross-case patterns matter for this study | Analyst subagent (LLM reasoning) |

The pattern: **deterministic mechanics in code, fuzzy reasoning in prompts.**

## Composition partners

- **`flowsim-tutor`** — separate sibling project. MCP server indexing the OLGA keyword reference manual so agents do not have to guess keyword semantics. Repo: <https://github.com/Ahmed-Hassan-portfolio/flowsim-tutor>.
- **`multiflash-mcp`** — separate sibling project. MCP server wrapping a thermodynamic engine for PVT properties and phase-boundary lookups. Repo: <https://github.com/Ahmed-Hassan-portfolio/multiflash-mcp>.

Neither is required to use `olga-automation` standalone — the primitives in this repo work without them. The skill degrades gracefully when the companion servers are absent: the keyword-lookup and PVT-sanity steps fall back to asking the user (or proceeding without those guards if the user opts in).

## Verification of the primitive layer

A reproducible end-to-end check of steps 5-7 above (the parts that live in this repo) without any OLGA install:

```bash
pip install -e .
python examples/01_parse_opi.py
python examples/02_modify_keyword.py
python examples/03_parse_trend.py
pytest -q
```

Expected output: each example prints a small structured summary; pytest reports `18 passed`.

The orchestration layer (steps 1-4, 8-10) cannot be fully exercised without a live Claude Code session that has `flowsim-tutor` and `multiflash-mcp` also registered. The SKILL.md and the four `.claude/agents/olga-*.md` files describe the protocol — an LLM-engineering reviewer can read them end-to-end and follow the wiring without running it.
