# Fleet Command Center — NL Position Control + Demo Arena — Design

Date: 2026-06-08
Branch: feature/multi-geo
Repo: unitree-notes

## Goal

Two improvements to the live AI command center (`g1_brain.fleet.sim.command_center`):

1. **Make natural-language *position* control of the fleet explicit and reliable.**
   The web console already accepts NL and (with codex) can drive `navigate {x,y}`
   ops, but it is easy to miss, and without codex it cannot do free navigation at
   all. Add a deterministic offline NL→position parser (coords, named landmarks,
   relative moves, multi-robot) and make the console discoverable, so commanding
   positions works **with or without** the codex brain.

2. **Give the shared world a demo-worthy arena.** Today `SharedG1World` is a bare
   `mjGEOM_PLANE`. Add cheap walk-around props plus one gentle terrain test strip,
   reactive obstacle avoidance so robots route around props, and a `--solo`
   launcher so a single robot's behaviour can be tested on the same arena.

## Context: this is a *different* world from the existing terrain scene

The repo already has `unitree_mujoco/unitree_robots/g1/scene_29dof_terrain.xml`
(+ `terrain_tool/g1_terrain_config.py`), designed in
`docs/superpowers/specs/2026-05-07-mujoco-terrain-scene-design.md`. That terrain
serves the **standalone single-robot `unitree_mujoco` DDS simulator** (joystick /
SDK bridge), and is intentionally heavyweight (Perlin height-field, 8×8 rough
ground, ~79 geoms, `noise`/`opencv` deps).

The fleet command center does **not** use that simulator. It builds its own world
in-process via `SharedG1World` (`MjSpec.attach` of two `g1_29dof.xml` onto one
plane, two reused RL backends @50 Hz, no DDS). So we cannot reuse that scene file
directly. We **will** reuse its geometry *conventions* (ramp = tilted box, stairs
= stacked boxes) but only the cheap primitive parts — never the hfield/perlin/
rough-ground, which the performance constraint below rules out.

> **Size-convention pitfall (carried over).** The `terrain_generator` API takes
> `size` as *full edge length* and halves it internally. We are **not** using
> that API — we call `MjSpec` `worldbody.add_geom(size=...)` directly, where
> `size` is MuJoCo-native **half-extents**. State all geom sizes in this spec as
> half-extents to match the MjSpec call and avoid the doubling bug.

## Constraints

- **Performance first (user constraint).** The added geometry must barely move the
  needle on a WSL2 / Mesa-llvmpipe software-rendered viewer:
  - **Static geoms only**, added to `worldbody` with **no body and no joint** →
    no new DOFs, ~zero dynamics cost (`nq`/`nv` unchanged from the robots alone).
  - **Primitive shapes only** — `mjGEOM_BOX` and `mjGEOM_CYLINDER`. **No
    heightfield, no mesh, no plane re-tiling.** Hfield collision/render is the
    expensive thing on llvmpipe; it is explicitly out.
  - **No new lights** (a light would add a shadow pass) and **no reflective
    materials** (`trim_render_cost` already zeros `mat_reflectance`).
  - **Budget ≈ 12–15 added geoms total** for the `demo` scene.
  - Set `contype`/`conaffinity` so props collide with the robots but cheap-out
    where possible; the existing floor/robot contact behaviour is unchanged.
- **Locomotion compatibility.** The RL policy is trained for **flat-ground**
  velocity tracking. Props are walk-*around* (flat floor preserved); the terrain
  strip is **gentle** (≈10° ramp, low rolling bumps, one wide low step) so the
  robot stays upright. No re-tuning of the policy.
- **Spawn clearance.** No prop or terrain geom within the robots' spawn footprint
  or directly on the straight line a fresh `--viewer` demo walks (robots spawn at
  `(-1.5,0)` / `(1.5,0)`; keep the central lane and ±~0.8 m around each spawn
  clear) so startup matches today's behaviour.
- **Backward compatibility.** Default behaviour of existing entry points must be
  unchanged. `WorldSim()` / `command_center` keep the bare plane unless a scene is
  requested; `scene="bare"` reproduces today's world byte-for-byte in geometry.
- **No codex required.** Position commands must work in `--no-codex` mode.
- **Testing is "runs correctly", not exhaustive** (user constraint): a small set
  of focused smoke/unit tests plus one manual `--viewer` check.

## Non-Goals

- Re-tuning or retraining the RL policy for terrain.
- Heightfield / Perlin / procedural terrain in the fleet world (perf-excluded).
- Global path planning (A*/RRT). Avoidance is *reactive* only.
- Click-to-go / drag / coordinate-field UI. Input stays natural-language only
  (per the chosen "NL only, made reliable" direction).
- Touching the standalone `unitree_mujoco` terrain scene or its generator.

## Architecture

The keystone is a **single declarative scene registry**. One source of truth
(geoms + landmark names→coords) feeds four consumers, so "natural-language
positions" stay consistent everywhere:

```
                         fleet/sim/scene.py
                    SCENES = {bare, demo, solo}
            geoms[]   terrain[]   landmarks{name:(x,y)}
                    /        |          |        \
                   /         |          |         \
        SharedG1World   command_center  nl_position  codex snapshot
        (build geoms)   /scene endpoint (resolve     (landmark names
                         + 2D map draw   names)        in prompt)
```

Data flow for an operator command (unchanged transport, new routing):

```
browser NL ─POST /command─> plan_mission(nl, snapshot+landmarks)
   1) codex (if available)        → rich ops
   2) nl_position (offline)       → navigate ops   ← NEW, works w/o codex
   3) deterministic choreography  → circle/face/arms
   4) FleetCommander              → rendezvous/relay
        → LiveExecutor.submit() preempts → WorldSim drives robots
        → nav_command now steers around props + peer (auto-off converging)
```

## Components

### New: `fleet/sim/scene.py`

```python
@dataclass
class Geom:      # one static primitive (box|cylinder)
    type: str; pos: tuple; size: tuple; euler: tuple = (0,0,0)
    rgba: tuple = (...); name: str = ""

@dataclass
class Scene:
    geoms: list[Geom]            # props + terrain (all static)
    landmarks: dict[str, tuple]  # name -> (x, y)

SCENES: dict[str, Scene]   # "bare" (empty), "demo", "solo"
def get_scene(name) -> Scene
def resolve_landmark(scene, name) -> tuple | None   # shared name lookup
```

`demo` scene contents (half-extents; all on/above the flat floor):

- **Props (walk-around, flat floor preserved):** ~2 boxes + ~2 cylinders + 1 low
  wall, placed off the central lane. Each is a named landmark, e.g.
  `红色柱子 (cylinder)`, `蓝色箱子 (box)`, `矮墙 (box wall)`.
- **Terrain strip (gentle, off to one side, e.g. around `x≈3.5`):** a ~10° ramp
  (tilted thin box, lowest corner on floor — z computed as
  `sin θ·half_len + cos θ·half_thick`), 2–3 low rolling bumps (short flat boxes
  /low cylinders, top ≈2–4 cm above floor), and one wide low step (~5 cm). Named
  landmark `地形测试区 / terrain`.
- **Landmarks (named spots, no geometry):** `集合点/中间 (0,0)`, `左上角`,
  `右上角`, `左下角`, `右下角` (corners at e.g. ±3.5, ±2.5), plus each prop above.

`solo` scene = `demo` minus the second robot's spawn-lane clearance concerns
(same geoms; robot list differs at the `WorldSim` layer, not here).

### Modify: `fleet/sim/shared_world.py`

- `SharedG1World(..., scene: str = "bare")`. After attaching robots, for each
  `Geom` in the scene call `spec.worldbody.add_geom(type=..., pos=..., size=...,
  euler=..., rgba=...)` — static, no body/joint.
- Add `self.scene` and accessors: `obstacles() -> list[(x,y,radius)]` (a cheap
  circular footprint per prop, for the nav avoidance term; terrain geoms are
  excluded — robots walk over them) and `landmarks() -> dict`.
- `scene="bare"` adds nothing → geometry identical to today.

### Modify: `fleet/sim/nav.py`

`nav_command(pose, goal, *, obstacles=(), peer=None, avoid_radius=0.9, ...)`:
- Compute the existing go-to-goal `(vx,vy,wz)`.
- Add a **bounded reactive repulsion**: for each obstacle (and `peer` if given)
  within `avoid_radius`, add a body-frame push away from it, magnitude scaled by
  `(avoid_radius - dist)` and capped. Sum, then **re-clip to the policy's trained
  `RANGES`** so we never leave distribution.
- Suppress repulsion when within `stop_radius` of the goal (don't jitter at the
  target). Pure-Python, no new deps.

### Modify: `fleet/agent/motion/rl_shared_backend.py`

- `_drive()` (walk mode) gathers `obstacles = world.obstacles()` and, if
  `self.peer_avoid`, `peer = nearest neighbor (x,y)` from `world.neighbors()`,
  and passes them to `nav_command`.
- New `self.peer_avoid: bool = True` plus `set_peer_avoid(bool)`.

### Modify: `fleet/sim/shared_world_node.py` (`WorldSim`)

- Pass `scene` through to `SharedG1World`; default `"bare"` (unchanged).
- Thread-safe `set_peer_avoid(rid, bool)`, `obstacles()`, `landmarks()` wrappers.
- Already supports arbitrary `robot_ids` → `--solo` just passes
  `robot_ids=("g1_a",)`.

### Modify: `fleet/sim/live_executor.py`

- When stepping a robot whose current op is `await_barrier` or `face`, call
  `world.set_peer_avoid(rid, False)`; otherwise `True`. This is the
  "peer-avoid auto-off while converging" — props are always avoided, the peer is
  only avoided while the robots are *not* meant to meet.

### New: `fleet/coordinator/nl_position.py`

Deterministic offline parser. `parse_position_command(nl, snapshot) -> dict|None`
returning `{"summary", "ops": {rid:[navigate]}}` or `None` if not positional.
Handled forms (zh + en):
- **Absolute coords:** `g1_a 走到 2,1` / `g1_a go to (2, 1)` / `g1_a 去 2 1`.
- **Named landmarks:** `去红色柱子` / `到集合点` / `左上角` (resolved via the
  scene landmarks carried in `snapshot["landmarks"]`).
- **Relative:** `g1_a 前进 2米` / `g1_a 后退 1m` / `左/右移` (uses current pose
  + yaw from snapshot).
- **Multi-robot:** `两机都去中间` / `all go to center` → same goal for every id;
  default robot = the only one (solo) or requires an id when ambiguous (returns a
  `needs_clarification`-style miss so the caller falls through).
Output ops are validated through the existing `choreographer.parse_ops`.

### Modify: `fleet/coordinator/choreographer.py` (`plan_mission`)

Insert the offline parser into the routing **after codex, before deterministic
choreography**:
1. codex `plan_choreography` (if available) — unchanged.
2. **`nl_position.parse_position_command`** — NEW; if it returns ops, build a
   `FleetPlan(coordination=Coordination(type="navigate"))` and return.
3. deterministic choreography (circle/face/arms) — unchanged.
4. `_commander_mission` (rendezvous/relay) — unchanged.

### Modify: `fleet/sim/command_center.py`

- `_world_snapshot(world)` adds `"landmarks": world.landmarks()` so both codex and
  the offline parser can resolve names.
- New flags: `--scene {bare,demo}` (default `demo` for the live launcher so the
  demo looks good out of the box; headless tests use `bare`), `--solo` (one
  robot), kept alongside `--viewer/--no-codex/...`.
- New `GET /scene` endpoint → `{obstacles:[...], landmarks:{...}}` (static;
  fetched once by the UI).
- On launch: print a clear banner with the URL + a couple of example commands,
  and `webbrowser.open(url)` (best-effort; harmless if headless) for
  discoverability.

### Modify: `fleet/sim/command_center_ui.py`

- On load, fetch `/scene` once; draw props (boxes/cylinders as rects/circles) and
  **named landmark labels** on the top-down map, so the operator can *see* where
  "红色柱子" / "左上角" are when typing positions.
- Add a one-line **examples / 快速指令** hint under the chat box (e.g.
  `g1_a 走到 2,1 · 去红色柱子 · 两机都去中间 · 顺时针绕圈`).
- Input remains natural-language only.

## Performance accounting

| Item | Cost |
|---|---|
| ~12–15 static box/cylinder geoms | broadphase/narrowphase on primitives only; no new DOFs |
| No hfield / mesh / extra lights / reflections | render cost ≈ flat plane today (after `trim_render_cost`) |
| nav avoidance | a few inverse-distance terms per tick, pure Python |
| `/scene` endpoint | served once on page load, static payload |

Verification target: the 50 Hz control loop in `WorldSim._control_loop` still
holds real-time (`dt=0.02` sleep stays positive) with the demo scene loaded.

## Testing / Verification (kept light)

Unit / smoke (pytest, headless, `scene="bare"` or `"demo"` as needed):
1. `scene.get_scene("demo")` returns geoms + landmarks; `resolve_landmark`
   resolves a known name and returns `None` for unknown.
2. `SharedG1World(scene="demo")` compiles; `nq`/`nv` equal the `bare` world
   (static geoms add no DOFs); `obstacles()`/`landmarks()` populated.
3. `nav_command` with an obstacle straddling the straight line to the goal
   produces a non-zero lateral velocity component (it steers); with no obstacles
   it equals today's output.
4. `nl_position.parse_position_command` parses each form (coords, landmark,
   relative, multi-robot) and returns `None` for a non-positional command.
5. `plan_mission(nl, snapshot, llm=None)` routes a position command to `navigate`
   ops **without codex**.
6. `WorldSim(robot_ids=("g1_a",), scene="demo")` runs N ticks and reports
   telemetry (solo path).
7. `live_executor` sets `peer_avoid=False` during `await_barrier`/`face`, `True`
   otherwise (small unit on a fake world).

Manual:
8. `command_center --viewer --scene demo` — props + gentle terrain visible,
   robots reach goals, steer around a prop, robot traverses the ramp without
   falling, `--solo` shows one robot.

## Out-of-Scope / Future Work

- Click-to-go / coordinate fields (deliberately excluded now).
- Global path planning; difficulty presets for terrain; hfield terrain in-fleet.
- Persisting custom arenas / an arena editor.
