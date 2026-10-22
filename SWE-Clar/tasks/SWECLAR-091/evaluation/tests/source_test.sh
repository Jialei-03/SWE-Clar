#!/usr/bin/env bash
# SWECLAR_STRUCTURED_RESULTS: the Python suite emits one verdict per Requirement Unit.
set -euo pipefail

candidate="${1:?candidate directory is required}"
python3 "$(dirname "$0")/test_gui.py" "$candidate"
