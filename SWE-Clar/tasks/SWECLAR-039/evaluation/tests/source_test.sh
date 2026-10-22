#!/bin/sh
# SWECLAR_STRUCTURED_RESULTS
export SWECLAR_PROJECT_DIR="$1"
exec python "$(dirname "$0")/devices_contract.py"
