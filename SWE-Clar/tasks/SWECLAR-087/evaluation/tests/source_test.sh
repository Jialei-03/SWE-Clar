#!/bin/sh
# SWECLAR_STRUCTURED_RESULTS
export CANDIDATE_ROOT="$1"
exec python "$(dirname "$0")/test_inventory_sync.py"
