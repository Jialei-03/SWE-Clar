# Portable evaluation harness

See the package-root README for setup, role profiles and execution commands. Credentials are supplied by a user-selected environment variable; candidate tools receive a restricted environment rather than host credentials. Results, model settings and frozen input hashes are persisted outside the dataset.

`harness.py` runs one Direct/Clarify/Oracle trajectory; `batch.py` is the baseline scheduler. `runtime/` implements role boundaries and private evaluation. `pi/` contains the pinned adapter, not installed dependencies. `tests/` contains offline/mocked framework tests, not paid model experiments. The interaction runners are separate. Compute the paper's understanding score from saved Audit answers with `audit/grade_saved_answer.py`; do not substitute the execution-stage diagnostic score. See `../docs/EVALUATION_GUIDE.md` for the complete workflow.
