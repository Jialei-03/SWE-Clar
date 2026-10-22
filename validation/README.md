# Implementation controls

Each task provides reference, equivalent and targeted incorrect implementation workspaces. Keep these controls outside scored coding-agent inputs. Use a copy with the corresponding task runtime.

`implementations.json` indexes workspace files, source patch hashes and the targeted requirement. Correction patches are text diffs against the released starter. Binary adaptations, if any, are listed with before/after hashes in `materialized_binary_adaptations`; full workspaces provide the corresponding bytes. Build native artifacts inside the Linux AMD64 environment.

Run `python validation/verify.py` to check implementation coverage and source integrity offline.
