# Scraper evaluation

The official verifier evaluates normalization and real HTML retrieval/extraction separately. `test_scrape.py` serves changing synthetic listing pages on a loopback HTTP server, then checks requested paths, extracted values, order, nested text, entities, and irrelevant script content. No live website is contacted. The normalizer-only negative control must fail the extraction gate.

Use Python 3.11 or later and pytest in the evaluator environment. Set `SWECLAR_PROJECT_DIR` to the candidate workspace and `SWECLAR_LOG_DIR` to a separate writable directory, then run `python tests/official_verifier.py`. Tests remain outside the coding agent workspace.
