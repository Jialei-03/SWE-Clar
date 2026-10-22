#!/bin/sh
# SWECLAR_STRUCTURED_RESULTS
export CANDIDATE_ROOT="$1"
exec python -I "$(dirname "$0")/evaluate.py"
