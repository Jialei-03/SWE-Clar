# Contributing to SWE-Clar

Thank you for your interest in SWE-Clar. We welcome bug reports, fixes to the harness and tools, and corrections to task data.

## Reporting issues

Open a GitHub issue and include:

- the task ID (for example `SWECLAR-013`) and requirement unit (for example `RU-004`), if the issue concerns task data;
- the command you ran, your operating system, and Python and Node.js versions;
- the full error output, or a description of the expected and actual behavior.

Do not report security vulnerabilities in public issues. See [SECURITY.md](SECURITY.md).

## Pull requests

1. Fork the repository and create a branch from `master`.
2. Keep each pull request focused on one change.
3. Run the offline checks before submitting:

   ```sh
   python tools/validate_dataset.py
   PYTHONPATH=harness python -m pytest harness/tests -q
   PYTHONPATH=interaction:harness python -m pytest interaction -q
   python validation/verify.py
   ```

4. Describe what changed and why in the pull request description.

All pull requests require review from a maintainer before merging.

## Changes to task data

SWE-Clar is a published benchmark, so changes to task data can affect comparability with reported results.

- If you edit `evaluation/requirement_units.yaml`, update `requirements_sha256` in the same task's `evaluation/delivery_contract.json`. `tools/validate_dataset.py` checks this.
- If you change hidden tests or implementation controls, confirm that the reference and equivalent implementations still pass and the incorrect implementation still fails its target requirement.
- Explain in the pull request whether the change could affect previously reported scores.

Never add original client materials, personal data, credentials or proprietary content. All task records must remain synthetic reconstructions.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
