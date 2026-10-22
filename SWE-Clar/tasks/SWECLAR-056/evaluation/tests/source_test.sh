#!/usr/bin/env bash
set -euo pipefail
# SWECLAR_STRUCTURED_RESULTS
node "$(dirname "$0")/socket_contract.cjs"
