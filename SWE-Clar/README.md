# SWE-Clar dataset

100 independently reconstructed software tasks and 512 requirement units (RUs), each linked to a question and executable acceptance checks. Understanding and RU scores average RUs within each task, then average tasks equally.

Each task contains `request.md`, `input.yaml`, `environment.json`, synthetic `workspace/` code, `public_tests/`, and evaluator-only `evaluation/` requirements, contracts and tests. The elicitation runtime deliberately withholds formal requirement/interface documents from the initial candidate context; the Client/Supervisor receive private task projections. Never mount the whole dataset into a candidate container. The progressive Oracle runner reveals requirements according to its saved schedule; Audit and hidden test outputs must not be fed back to Coding.

Build recipes under `environments/` use public dependency registries and local synthetic fixture services. Target Linux AMD64, Python 3.12+, Node.js and Docker. Build outputs and results must be outside this dataset. Run `python environments/build.py --output /path/to/build --plan` to inspect the plan; omit `--plan` to build, or add `--task SWECLAR-013` for a single task. A local loopback image registry is started by the builder. External publication/pushing is opt-in through its registry argument.

No customer source attachments, personal accounts, original conversations, identity mappings, model credentials, hosted images or internal model gateway are included. Audio fixtures are independently synthesized English speech, not classroom recordings. Public dependency license notices retain their original attribution. See the root README and `../docs/EVALUATION_GUIDE.md` for setup and runtime limitations.
