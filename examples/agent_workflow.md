# Agent workflow example

A reviewer-oriented walkthrough of how an LLM agent uses the MCP tools in this repository to drive an OLGA-style simulation campaign end to end. The numbered steps are the public tool surface; each step lists which parts run hermetically against the synthetic fixtures in this repo and which parts require a real OLGA install.

The scenario: the agent is asked to study how PIPE `DIAMETER` affects a trend variable across a small set of variants, and report whether the result is conclusive enough for a human engineer to look at.

## 1. Read the base model

The agent loads `base.opi` and gets a structured view of the model.

- Tools: [`read_case_summary`](../src/olga_automation/mcp_server/tools_model.py), [`list_keywords`](../src/olga_automation/mcp_server/tools_model.py), [`get_parameter`](../src/olga_automation/mcp_server/tools_model.py), [`get_output_config`](../src/olga_automation/mcp_server/tools_model.py).
- Hermetic: yes — `examples/sample.opi` is a synthetic fixture sufficient to exercise these tools.
- Verify locally with `python examples/01_parse_opi.py`.

## 2. Modify a keyword or output selection

The agent edits a single parameter (PIPE `DIAMETER`) and, if needed, expands the output variable list so the post-run parser sees what it expects.

- Tools: [`set_parameter`](../src/olga_automation/mcp_server/tools_modify.py), [`set_output_variables`](../src/olga_automation/mcp_server/tools_modify.py), [`create_variant`](../src/olga_automation/mcp_server/tools_modify.py), [`add_keyword`](../src/olga_automation/mcp_server/tools_modify.py), [`remove_keyword`](../src/olga_automation/mcp_server/tools_modify.py).
- Hermetic: yes — `create_variant` writes a new `.opi` next to the base file without touching the base.
- Verify locally with `python examples/02_modify_keyword.py`.

## 3. Validate the modified model before running

The agent runs structural validation on the new `.opi`. This is the first safety gate: if validation fails, no license slot is consumed.

- Tools: [`validate_model`](../src/olga_automation/mcp_server/tools_modify.py).
- Hermetic: yes — validation is pure-Python and operates on the parsed XML tree.
- Failure mode: validation returns a structured list of errors; the agent surfaces it to the human and does **not** proceed to step 4.

## 4. Build the variant sweep and run a license-aware batch

The agent generates the full set of variants from a sweep spec, then submits the batch under a `threading.Semaphore` whose count equals the available OLGA license seats.

- Tools: [`build_sweep`](../src/olga_automation/mcp_server/tools_batch.py), [`run_batch`](../src/olga_automation/mcp_server/tools_batch.py), [`run_simulation_async`](../src/olga_automation/mcp_server/tools_execution.py), [`get_run_status`](../src/olga_automation/mcp_server/tools_execution.py), [`cancel_run`](../src/olga_automation/mcp_server/tools_execution.py).
- Hermetic: **no** — this step shells out to a locally installed `opi.exe` (configured via `OPI_COMMAND` in `.env`). Without an OLGA install, the runner returns a `FileNotFoundError` early.
- Failure modes: license slot exhaustion (semaphore blocks new jobs); per-run timeout (`DEFAULT_TIMEOUT` kills the subprocess and reports `status="timeout"`); explicit cancellation by the agent on the human's request.

## 5. Parse the outputs

For each completed run, the agent parses the three OLGA output formats into typed Python objects suitable for JSON serialization back through MCP.

- Tools: [`parse_trend_data`](../src/olga_automation/mcp_server/tools_execution.py) (for `.tpl`), [`parse_profile_data`](../src/olga_automation/mcp_server/tools_execution.py) (for `.ppl`), [`get_simulation_log`](../src/olga_automation/mcp_server/tools_execution.py) (for `.out`).
- Hermetic: yes for the parsers themselves — `examples/sample.tpl` is a hand-authored synthetic fixture that exercises `parse_tpl` byte-accurately.
- Verify locally with `python examples/03_parse_trend.py`.

## 6. Compare runs and decide whether to escalate

The agent calls `compare_runs` to align trend series across the variants on the variable of interest, then reports the result to the human with a confidence statement.

- Tools: [`compare_runs`](../src/olga_automation/mcp_server/tools_batch.py).
- Hermetic: yes when given pre-existing `.tpl` files; the comparator is pure-Python.
- Escalation rule (agent-side, not enforced by the library): if any run is `status="timeout"`, if the variable of interest is missing from any output, or if the spread across variants is below the noise floor of the synthetic fixtures, the agent must report the comparison as **inconclusive** and ask a human engineer to review before recommending an action.

## What's hermetic vs. what needs a real OLGA install

| Step | Hermetic | Needs OLGA install |
| --- | :---: | :---: |
| 1. Read | yes |   |
| 2. Modify | yes |   |
| 3. Validate | yes |   |
| 4. Run / batch |   | yes |
| 5. Parse outputs | yes (parsers) | (only if outputs come from a real run) |
| 6. Compare | yes |   |

The three example scripts (`01_parse_opi.py`, `02_modify_keyword.py`, `03_parse_trend.py`) cover steps 1, 2, and 5 against the synthetic fixtures. Steps 3, 4, and 6 are exercised by the test suite in `tests/`.
