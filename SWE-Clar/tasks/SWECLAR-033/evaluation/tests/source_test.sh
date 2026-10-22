#!/bin/sh
# SWECLAR_STRUCTURED_RESULTS
export SWECLAR_PROJECT_DIR="$1"
export SWECLAR_SOLUTION_PATH="$1/solution.py"
exec python -I "$(dirname "$0")/evaluate.py"
