# Shared Node SDK and image environment

This extends the shared `python-vision` recipe with the Node runtime already supplied by Playwright and the locked S3/Rekognition SDK dependencies. It contains no task answers, source-client material or service credentials. Dependency package license files remain in the installed modules.

Build it with `python SWE-Clar/environments/build.py` (see the repository README), which prepares the base profiles automatically; no manual preparation step is needed. Host Docker, Python and npm are build tools; network access for locked public npm artifacts occurs before agent budgets. Package lifecycle scripts are disabled.

The supplied base record is verified against the base recipe files. A newly rebuilt base is accepted through its new record; no original developer-local image identifier is required. The resulting immutable image identifier and recipe hashes are recorded for the experiment. Runtime execution is offline and uses ordinary-user SDK, image and browser checks.
