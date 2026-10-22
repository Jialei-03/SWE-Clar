# Dataset and evaluation guide

## Read a task

Start with `SWE-Clar/tasks/SWECLAR-013/`:

| Path | Purpose |
| --- | --- |
| `request.md` | Incomplete initial software request. |
| `input.yaml` | Selection of initial input materials. |
| `workspace/` | Synthetic starter project available to the candidate. |
| `environment.json` | Task runtime requirements. |
| `evaluation/requirement_units.yaml` | RU definitions, questions, references, interfaces and linked tests. |
| `evaluation/delivery_contract.json` | Canonical interface agreements and integrity hashes. |
| `evaluation/project/` | Formal project documents for private role grounding. |
| `evaluation/tests/` | Acceptance checks, excluded from candidate inputs. |
| `public_tests/` | Supporting files; the initial-input builder, not the directory name, determines candidate access. |

An RU is identified by a task-local `ru_id` and can include multiple related conditions. `source_visibility` records visibility in the source request. `benchmark_visibility` controls formal initial disclosure. All RUs in this dataset are marked `hidden`: the initial input does not inject a complete RU checklist. The request and starter code can nevertheless convey requirement information. Oracle supplies applicable requirements explicitly.

## Evaluation workflow

Follow the root README to install dependencies, build task environments and configure model roles. The candidate profile supplies clarification, Audit and Coding; Client, Supervisor and Judge are separately configurable. Credentials come from environment variables.

1. Initialize the candidate with the request and permitted workspace.
2. In `clarify`, the candidate asks questions; Client drafts are reviewed by Supervisor before delivery. `direct` skips interaction. `oracle` supplies applicable requirements and interfaces, excluding hidden tests and reference implementations.
3. Freeze the visible context and initialize independent Audit and Coding branches. Audit answers do not enter Coding.
4. Execute acceptance checks against submitted code and preserve per-RU outcomes and errors.
5. Compute the paper's understanding score from saved answers with `audit/grade_saved_answer.py` and `audit/understanding_judge.txt`, separately from execution-stage diagnostic scoring.

The CLI prints the session ID, status and result JSON path. Output directories must remain outside the dataset. Preserve session state, dialogue, answers, code, per-RU results, usage and input/configuration hashes. An interrupted run or reference conflict is not a completed passing task. Multi-cycle protocols are described in `interaction/PROTOCOL.md`.

## Scoring

- Task pass rate: fraction of evaluated tasks passing all required acceptance checks.
- RU pass rate: average passing-RU fractions within tasks, then average tasks equally.
- Understanding score: correct = 1, partial = 0.5, incorrect = 0; average RU judgments within tasks, then tasks equally. The judge may inspect reference test source but not candidate test outcomes.
- Usage: retain model-reported counts by role. Unknown usage is not zero cost; pricing is supplied separately. Retain the scoring method and supporting records for each reported result.

The grading helper handles one saved RU request, including the entire candidate answer set and corresponding reference/test material. It does not automatically export and aggregate all sessions. It uses Chat Completions; the execution harness also supports Responses and Anthropic Messages when offered by the configured provider.

Offline checks establish source consistency, not model performance. Full execution requires Docker and model access. This repository does not contain the complete paper-result archive or private source conversations.
