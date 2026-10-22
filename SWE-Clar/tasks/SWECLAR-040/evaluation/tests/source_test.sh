#!/bin/sh
# SWECLAR_STRUCTURED_RESULTS
export SWECLAR_PROJECT_DIR="$1"
exec python -I "$(dirname "$0")/catalogue_contract.py"
