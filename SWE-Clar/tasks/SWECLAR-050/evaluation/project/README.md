# Arena workshop

Complete the combat and replay behavior in this independently authored 3D auto-battler prototype. It already includes a WebGL arena, an editable unit catalog, two-team placement, a fixed-tick server interface and result presentation. Complete movement, attacks/projectiles and termination according to the client's clarification. Preserve the working editor, real 3D rendering and public regressions. A table of declared outcomes is not a playable battle.

This project uses only independently generated geometric models and synthetic units. The host, exact combat rules, stats and scene are benchmark designs. It does not claim compatibility with a proprietary game engine or include customer projects/assets. Later production features such as unique abilities, trait systems and asset pipelines are not represented as implemented by placeholder flags.

## Prepared environment

The benchmark provides Python 3.12, SQLite, Playwright/Chromium and a fixed software WebGL renderer in the `python-game` environment. Its protected preflight compiles real shaders and verifies depth occlusion with pixel readback, along with HTTP/storage checks. No GPU setup, SDK, game-engine installation, account or download is part of the coding attempt.

From `/workspace`, run `python server.py --port 8000 --db /tmp/arena.sqlite`, then open `http://127.0.0.1:8000`. Port `0` chooses an available HTTP port and prints it as JSON. Public checks: `python -I /public_tests/test_public.py`. Browser automation uses the supplied Chromium with `--use-angle=swiftshader --enable-unsafe-swiftshader`. These flags select the prepared software renderer; do not substitute hardware-specific settings between candidates.

Limits: 2 CPUs, 2 GiB RAM, 256 processes, 512 MiB workspace, 240 seconds per evaluation. A fresh database path resets all saved data. The server stores configuration and the current battle; restart with the same path to resume the same state. The manager provides independent temporary storage for each attempt. Keep the command-line, HTTP and UI hooks below; source structure and algorithms may change.

## Editor and scene

`workshop.py` validates editing operations; `battle.py` contains the fixed-tick simulation. `server.py` provides transactional HTTP/SQLite storage. `render.js` draws depth-tested 3D geometry, health bars, ranged projectiles and retained defeated units. `app.js` connects actual form, placement, camera and battle controls. Melee models use blocks and ranged models diamonds; no external meshes, fonts or textures are required. New template records can be added without changing renderer code.

The board has world extents x=-8..8 and z=-6..6. Units stand on y=0; radius is 0.4. Editor centers must fit x=-7.6..7.6, z=-5.6..5.6 and be at least 0.8 from every other center. Click the arena to place or reposition the current unit ID with the chosen template/team. A placement ID identifies one instance, independently of its template. Both teams can be placed anywhere legal. The initial scene has two synthetic templates and four placements, and can be cleared.

Right-drag orbits the camera, the mouse wheel zooms, and Other side rotates to the opposite view. Names can be toggled. Camera operations must not change game data. Start enters battle and plays automatic fixed steps; Pause/play controls browser playback, Step advances exactly one tick, and Reset returns to the unchanged editable setup. Editing is locked while any battle exists, including a finished battle, until Reset. No dependency installation or compilation repair is required before this scene can render.

## Public HTTP and data contract

`GET /api/state` returns `{config,battle}`. Configuration contains ordered `templates`, ordered `placements`, and `max_ticks`. A template has:

| Field | Range |
|---|---|
| `id` | ASCII letters/digits/underscore/hyphen, 1–40 characters |
| `name` | trimmed nonempty text, at most 60 characters |
| `kind` | `melee` or `ranged` |
| `health` | finite number, 1–1000 |
| `attack` | finite number, 1–100 |
| `defense` | finite number, 0–100 |
| `speed` | finite world units/second, 0.1–5 |
| `range` | finite center distance, 0.8–8 |
| `cooldown` | integer ticks between attacks, 1–100 |
| `projectile_speed` | finite world units/second, 0.1–20 |

Booleans are not numbers. A placement is `{id,template_id,team,x,z}` with team `A` or `B`. The template catalog and placements each allow at most 32 entries. Template IDs are unique within the catalog; placement IDs are unique within placements. Saving an existing template updates it; placing an existing instance ID moves/updates that instance. Template changes affect all its placements when a new battle begins; one team's instances do not receive a different private stat pool.

`POST /api/command` accepts one JSON command and returns the new `{config,battle}`:

| Type | Fields |
|---|---|
| `template` | `value`: complete template |
| `delete_template` | `id`; reject if still placed |
| `place` | complete placement fields |
| `remove` | placement `id` |
| `clear` | clear placements only |
| `limit` | `value`: integer 1–1000 |
| `start` | both teams must be present; requires `battle:null` |
| `step` | `ticks`: integer 1–50, default 1; requires running battle |
| `reset` | remove battle, retain configuration |

A running/finished battle includes `status,tick,winner,reason,units,projectiles,events,max_ticks,next_projectile`. Units combine placement/template fields and include current `hp,next_attack,damage_dealt`. A projectile includes `id,attacker,target,team,x,z,speed,attack`. A hit event includes `tick,type:"hit",kind,attacker,target,damage,remaining_hp`; a launch event includes `tick,type:"launch",kind:"ranged",attacker,target,projectile`. Preserve these observable fields; details of ordering, targeting, damage, travel, cooldown, termination and replay are client decisions. Simulation time uses 100 ms per tick rather than wall-clock speed. No API is allowed to declare a winner supplied by the caller.

Invalid commands return HTTP 400 with `{error:<code>}` and no partial changes. Expected categories include invalid_command, occupied, missing_template, template_in_use, missing_unit, editing_locked, reset_required, both_teams_required and not_running. Unknown routes return 404. Names must render as text. Whole-command atomicity and persistence are part of the task, not infrastructure work for the agent.

## Observable UI

Keep `#arena`, `#labels`, `#catalog`, `#template-form`, `#template-id`, `#template-name`, `#template-kind`, `#stat-<field>`, `#placement-template`, `#team`, `#placement-id`, `#placements`, `#clear`, `#limit`, `#save-limit`, `#start`, `#pause`, `#step`, `#reset`, `#camera-side`, `#names`, `#status`, `#results`, `#outcome` and `#team-results`. Result rows use `[data-result-unit]`, name/health overlays `[data-unit]`, and placement controls `[data-select-unit]`/`[data-remove-unit]`.

The existing public `window.arenaView.project({x,y,z})` and `.ground(clientX,clientY)` helpers translate world/viewport coordinates for interaction and debugging. They do not replace rendering verification: the harness observes real WebGL pixels and browser inputs as well as server state. The renderer is geometric, while movement is planar within the 3D arena. No original customer chat or reference implementation is supplied to the benchmark roles.

<!-- delivery-contract -->
## Delivery agreement

The public interface is also available in `DELIVERY_INTERFACE.json`. Its field names, signatures, defaults and error shapes are fixed; clarification may explain them but must not rename or contradict them. Business decisions intentionally left open above remain questions for the client. If a reply conflicts with this agreement, request a correction.
