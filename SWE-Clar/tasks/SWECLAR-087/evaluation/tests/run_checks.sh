#!/usr/bin/env bash
set -euo pipefail
candidate="${1:?candidate root required}"
test_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHONDONTWRITEBYTECODE=1 CANDIDATE_ROOT="$candidate" \
  python3 "$test_dir/test_inventory_sync.py"
