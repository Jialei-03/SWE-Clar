#!/usr/bin/env bash
set -euo pipefail
# SWECLAR_STRUCTURED_RESULTS
python3 -I "$(dirname "$0")/evaluate.py"
