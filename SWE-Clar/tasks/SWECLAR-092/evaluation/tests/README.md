# Browser evaluation

The five gates use Playwright Chromium to check actual data rendering, responsive element geometry, missing-data errors, sidebar clicks, and remote-request and text-injection behavior. The evaluator supplies several changing synthetic JSON fixtures before the local page loads. Tests stay outside the candidate workspace.

Run the official Python verifier with SWECLAR_PROJECT_DIR and SWECLAR_LOG_DIR set. Node, Playwright and Chromium belong to the evaluator environment; SWECLAR_NODE_REQUIRE_ROOT locates its Playwright installation. Missing browser dependencies are infrastructure errors. Bootstrap is vendored with its MIT license; the original Figma is not included or claimed to be reproduced.
