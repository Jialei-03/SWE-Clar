# Five-player lineup optimizer

Implement `solution.py::optimize_lineups(players, limit, mode)`. The existing request reader and console interface work; lineup selection currently returns an empty placeholder. This is an algorithm component with a JSON console application. All inputs are synthetic projections.

From `/workspace`, run `python cli.py example.json`, or pipe one request into `python cli.py`. Run `python /public_tests/test_public.py` for the prepared interpreter, request parsing and output-envelope smoke checks. A smoke pass does not establish optimizer correctness. No build, service, account, download or package installation is needed. Python and the standard library are prepared by the benchmark using the shared `python-web` environment. There is no persistent service to reset: each console invocation reads a fresh request.

Each request has `players`, `limit` and `mode`. Each player has a nonempty string `id`, a `position` from `QB`, `RB`, `WR`, `TE`, and finite numeric `projected_points` (not Boolean). Extra player metadata can occur. Successful output contains `lineups`, `considered` and `unused_player_ids`; each lineup contains ordered `player_ids` and numeric `score`. Rejections use `{"error":{"code":"..."}}`. The meanings of modes, counts, ranking and rejection rules can be clarified. Additional nonconflicting output metadata is permitted.

The supported workload is at most 600 players and at most 10,000 requested lineups. The optimization call has a 15 CPU-second budget in the declared environment; environment preparation and process startup are excluded. Inputs must not be mutated. Required output fields must be deterministic. No algorithm, internal data structure or package-specific implementation is prescribed. Player records, scores and positions are supplied as data; do not embed the example as an answer table.

The five ordered slots are QB, RB, WR, WR-or-TE and FLEX (RB, WR or TE). Each lineup uses five distinct IDs. Different eligible slot assignments count as different lineups even when they contain the same five players. Different output lineups may reuse players.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
