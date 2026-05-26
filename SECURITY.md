# Security and agent-safety notes

This repository exposes an OLGA-automation toolchain to an LLM agent via an MCP server and a Typer CLI. The notes below describe the boundaries that an agent integrator should preserve, the inputs an agent must treat as untrusted, and the operational failure modes a human engineer is expected to handle.

## File access

- Every tool that reads or writes a model takes an explicit path argument. There is no recursive directory scan, no glob expansion of user input, and no automatic upload step.
- `create_variant` writes only to the `output_opi` path the caller supplied. Base files are copied with `shutil.copy2` and never mutated in place, so an accidental edit cannot destroy the original model.
- Outputs (`.tpl`, `.ppl`, `.out`, `.rsw`) land next to the `.opi` that produced them. There is no `-outDir` redirection from agent input, so the agent cannot scatter artifacts across the filesystem.
- An integrator deploying this server should pin the working directory to a project-owned root (for example `runs/` and `base_models/`) and reject paths outside that root before calling the tools.

## No proprietary data, no vendor binaries

- The repository ships only synthetic, hand-authored fixtures (`examples/sample.opi`, `examples/sample.tpl`).
- No real `.opi`, `.tpl`, `.ppl`, or `.out` files from a customer or operator are included.
- The OLGA solver itself (`opi.exe`) is not redistributed; the tools shell out to a locally installed binary whose path is configured per environment (see [.env.example](.env.example)).
- The license-aware batch runner reads `MAX_PARALLEL_RUNS` from configuration; it does not probe a license server or transmit license information.

## No arbitrary shell execution

- `execution_manager.runner` builds the OLGA command as a fixed token list (`[opi_command, opi_path, ...flags]`) passed to `subprocess.Popen` with `shell=False`. The agent never supplies a shell string.
- No tool evaluates Python source, no tool downloads or executes binaries the agent named, and no tool exposes the underlying shell.
- Timeouts and explicit `cancel_run` exist to keep a runaway simulation from holding a license slot.

## Prompt-injection surface

The following content is read from disk and returned to the agent verbatim. An attacker who can plant text in any of these channels can attempt to influence the agent:

- `.out` solver logs, parsed by `output_parser.out_parser`.
- Comment text and string keywords inside `.opi` XML.
- `BatchExecutionSummary.txt` content surfaced through `compare_runs`.
- Any error message that quotes the solver's stderr.

An integrator should treat these as untrusted text and apply the usual mitigations: do not let the agent grant itself new tools based on the content, do not let solver output rewrite the agent's system prompt, and require explicit human approval before acting on instructions discovered inside logs or models.

## Human review before operational decisions

This project is a portfolio/research artifact, not a production-grade controller for a real well or facility.

- An agent using these tools must escalate to a human engineer before any change that would be applied to a real OLGA model, a real well, a real pipeline, or a real production schedule.
- Agent-suggested keyword edits should be reviewed by a flow-assurance engineer who can spot domain-invalid combinations (for example pressure boundaries that are physically inconsistent with a chosen PVT table).
- Confidence in `compare_runs` outputs should be reported alongside the numbers; do not let the agent collapse a small sample of synthetic runs into operational guidance.

## Failure modes the integrator must handle

| Failure | Detection | Recommended response |
| --- | --- | --- |
| OLGA executable missing or path wrong | `FileNotFoundError` from `subprocess.Popen` | Surface to the human; do not retry blindly. |
| Run exceeds `DEFAULT_TIMEOUT` | Runner kills the process and returns `status="timeout"` | Treat as inconclusive; do not interpret partial outputs as a finished run. |
| `.opi` validation fails | `validate_model` returns a structured error list | Block downstream `run_simulation`; surface the error list to the human. |
| Output parser sees an unexpected header or truncated block | Parser raises `ValueError` with the offending line | Treat the run as failed; do not return partial NumPy arrays as if they were the full series. |
| Batch run hits the license cap | Semaphore blocks new jobs until a slot frees | Expected behaviour; expose queue depth in `get_run_status`. |
| Agent supplies a path outside the project root | Integrator-level check (not enforced by the library) | The MCP host must validate paths before calling the tools. |

## Reporting

If you discover a real security issue (for example a path traversal that escapes the configured root, a way to coerce arbitrary shell execution, or a vendor-data leak), please open an issue against this repository describing the failure mode and a minimal reproduction.
