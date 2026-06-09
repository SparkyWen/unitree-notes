# Fleet Command Center — NL Position Control + Demo Arena — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the live AI command center reliable natural-language *position* control of the fleet (working with or without codex) and a cheap, demo-worthy arena (walk-around props + a gentle terrain strip) with reactive obstacle avoidance and a `--solo` launcher.

**Architecture:** A single declarative scene registry (`fleet/sim/scene.py`) is the one source of truth for static geometry + named landmarks. It feeds four consumers: the in-process MuJoCo world (`SharedG1World`), the offline NL→position parser (`nl_position.py`), the codex snapshot, and the web map. Navigation (`nav.py`) gains a bounded reactive repulsion term; the executor disables peer-avoidance only while robots are meant to converge.

**Tech Stack:** Python 3.11 (conda env `agi`), MuJoCo `MjSpec` (in-process model build), aiohttp, pydantic, pytest. No new third-party deps.

**How to run tests:** from the repo root `/home/helios/unitree/unitree-notes`:
`conda run -n agi python -m pytest g1_brain/tests/fleet/<file>.py -v`

**Performance contract (user constraint — keep it true in every task):** static geoms only (no body/joint → zero new DOFs), primitives only (`mjGEOM_BOX`/`mjGEOM_CYLINDER`), **no heightfield/mesh/lights/reflective materials**, ≈12–15 added geoms total. Verified by probe: 4 static geoms keep `nq=nv=0`.

---

## File Structure

| Path | Create/Modify | Responsibility |
|---|---|---|
| `g1_brain/g1_brain/fleet/sim/scene.py` | Create | `Geom`/`Scene` dataclasses, `SCENES` registry (`bare`/`demo`/`solo`), `get_scene`, `pitch_quat`, landmark resolution (`resolve_landmark` + alias map). |
| `g1_brain/g1_brain/fleet/sim/shared_world.py` | Modify | Accept `scene=`, add static geoms, generalize default spawn, expose `obstacles()`/`landmarks()`/`scene_render()`. |
| `g1_brain/g1_brain/fleet/sim/nav.py` | Modify | Add bounded reactive repulsion (props + optional peer) to `nav_command`. |
| `g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py` | Modify | Feed obstacles + peer into `nav_command`; add `peer_avoid` flag. |
| `g1_brain/g1_brain/fleet/sim/shared_world_node.py` | Modify | `WorldSim(scene=)`; thread-safe `set_peer_avoid`, `obstacles`, `landmarks`, `scene_render`. |
| `g1_brain/g1_brain/fleet/sim/live_executor.py` | Modify | Toggle `peer_avoid` off during `await_barrier`/`face`. |
| `g1_brain/g1_brain/fleet/coordinator/nl_position.py` | Create | Offline NL→`navigate` ops parser (coords/landmark/relative/multi-robot). |
| `g1_brain/g1_brain/fleet/coordinator/choreographer.py` | Modify | Route NL through the offline position parser (after codex, before choreography). |
| `g1_brain/g1_brain/fleet/sim/command_center.py` | Modify | `--scene`/`--solo`, `/scene` endpoint, snapshot landmarks+yaw, banner + browser open. |
| `g1_brain/g1_brain/fleet/sim/command_center_ui.py` | Modify | Draw props + landmark labels on the map; examples hint line. |
| `g1_brain/tests/fleet/test_scene.py` | Create | Scene registry + landmark resolution. |
| `g1_brain/tests/fleet/test_shared_world_scene.py` | Create | World compiles with scene, no new DOFs, accessors. |
| `g1_brain/tests/fleet/test_nav_avoid.py` | Create | Repulsion steers around an obstacle; no-obstacle path unchanged. |
| `g1_brain/tests/fleet/test_nl_position.py` | Create | Parser forms + routing without codex. |
| `g1_brain/tests/fleet/test_executor_peer_avoid.py` | Create | Peer-avoid toggles by op. |

---

## Task 1: Scene registry (`scene.py`)

**Files:**
- Create: `g1_brain/g1_brain/fleet/sim/scene.py`
- Test: `g1_brain/tests/fleet/test_scene.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_scene.py
from g1_brain.fleet.sim.scene import get_scene, resolve_landmark, Scene, Geom


def test_bare_scene_is_empty():
    s = get_scene("bare")
    assert isinstance(s, Scene) and s.geoms == [] and s.landmarks == {}


def test_demo_scene_has_props_and_landmarks():
    s = get_scene("demo")
    assert 8 <= len(s.geoms) <= 15            # props + terrain, within budget
    # rendezvous + four corners + named props all present
    for name in ("集合点", "左上角", "右上角", "左下角", "右下角",
                 "红色柱子", "蓝色箱子", "地形测试区"):
        assert name in s.landmarks
    # avoidance footprints exist on props, not on terrain
    assert any(g.avoid_r > 0 for g in s.geoms)
    assert any(g.avoid_r == 0 for g in s.geoms)


def test_solo_scene_reuses_demo_geometry():
    assert get_scene("solo").landmarks == get_scene("demo").landmarks


def test_resolve_landmark_direct_and_alias():
    lm = get_scene("demo").landmarks
    assert resolve_landmark(lm, "去红色柱子那里") == lm["红色柱子"]
    assert resolve_landmark(lm, "all go to center") == lm["集合点"]
    assert resolve_landmark(lm, "走到 top left") == lm["左上角"]
    assert resolve_landmark(lm, "随便走走") is None


def test_unknown_scene_raises():
    import pytest
    with pytest.raises(KeyError):
        get_scene("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_scene.py -v`
Expected: FAIL — `ModuleNotFoundError: ... fleet.sim.scene`.

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/sim/scene.py
"""Declarative arena registry: one source of truth for the command center's
static world geometry and named landmarks.

Consumed by SharedG1World (build geoms), nl_position (resolve names), the codex
snapshot, and the web map. PERFORMANCE: geoms are static primitives only
(box/cylinder) added to the worldbody with no body/joint -> zero new DOFs and
no extra render passes on WSL2/llvmpipe. No heightfield/mesh/lights."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class Geom:
    """One static primitive. ``size`` is MuJoCo-native HALF-extents
    (box: hx,hy,hz; cylinder: radius,half_len). ``avoid_r`` is the circular
    footprint radius the navigator steers around (0 = scenery/terrain, walked
    over, not avoided)."""
    gtype: str                       # "box" | "cylinder"
    pos: Tuple[float, float, float]
    size: Tuple[float, ...]
    rgba: Tuple[float, float, float, float] = (0.6, 0.6, 0.6, 1.0)
    quat: Tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0)
    name: str = ""
    avoid_r: float = 0.0


@dataclass
class Scene:
    geoms: List[Geom] = field(default_factory=list)
    landmarks: Dict[str, Tuple[float, float]] = field(default_factory=dict)


def pitch_quat(deg: float) -> Tuple[float, float, float, float]:
    """Quaternion for a rotation about +Y (pitch) — used to tilt a thin box
    into a ramp."""
    th = math.radians(deg) / 2.0
    return (math.cos(th), 0.0, math.sin(th), 0.0)


# alias substring (lowercased) -> canonical landmark name (must exist in scene)
LANDMARK_ALIASES: Dict[str, str] = {
    "center": "集合点", "centre": "集合点", "middle": "集合点",
    "中间": "集合点", "中心": "集合点", "会合": "集合点", "集合": "集合点",
    "top left": "左上角", "top-left": "左上角", "upper left": "左上角",
    "top right": "右上角", "top-right": "右上角", "upper right": "右上角",
    "bottom left": "左下角", "bottom-left": "左下角", "lower left": "左下角",
    "bottom right": "右下角", "bottom-right": "右下角", "lower right": "右下角",
    "terrain": "地形测试区", "ramp": "地形测试区",
}


def resolve_landmark(landmarks: Dict[str, Tuple[float, float]],
                     text: str) -> Optional[Tuple[float, float]]:
    """Return (x,y) if any landmark name or alias appears in ``text``."""
    low = text.lower()
    # direct name match first (longest name wins, so "右上角" beats "上角")
    for name in sorted(landmarks, key=len, reverse=True):
        if name.lower() in low:
            xy = landmarks[name]
            return (float(xy[0]), float(xy[1]))
    for alias, canon in LANDMARK_ALIASES.items():
        if alias in low and canon in landmarks:
            xy = landmarks[canon]
            return (float(xy[0]), float(xy[1]))
    return None


def _demo_scene() -> Scene:
    R, B, G, Y, O, W = (
        (0.86, 0.20, 0.20, 1), (0.20, 0.42, 0.95, 1), (0.20, 0.75, 0.35, 1),
        (0.95, 0.78, 0.20, 1), (0.95, 0.55, 0.15, 1), (0.55, 0.57, 0.60, 1))
    geoms: List[Geom] = [
        # --- walk-around props (avoid_r > 0), off the central rendezvous lane ---
        Geom("cylinder", (-2.5, 1.8, 0.40), (0.15, 0.40), R, name="红色柱子", avoid_r=0.45),
        Geom("box",      (2.5, 1.8, 0.40),  (0.25, 0.25, 0.40), B, name="蓝色箱子", avoid_r=0.50),
        Geom("cylinder", (-2.5, -1.8, 0.40), (0.15, 0.40), G, name="绿色柱子", avoid_r=0.45),
        Geom("box",      (2.5, -1.8, 0.30), (0.25, 0.25, 0.30), Y, name="黄色箱子", avoid_r=0.50),
        Geom("cylinder", (0.0, 1.30, 0.35), (0.18, 0.35), O, name="路障", avoid_r=0.50),
        # backdrop wall (scenery, far north, not avoided)
        Geom("box",      (0.0, 3.0, 0.30),  (1.5, 0.10, 0.30), W, name="矮墙", avoid_r=0.0),
        # --- gentle terrain strip along +X (walked over, avoid_r=0) ---
        Geom("box", (3.5, 0.0, 0.129), (0.60, 0.50, 0.025), W, quat=pitch_quat(10.0), name="斜坡"),
        Geom("box", (4.2, 0.30, 0.03), (0.20, 0.20, 0.03), W, name="起伏1"),
        Geom("box", (4.2, -0.30, 0.025), (0.20, 0.20, 0.025), W, name="起伏2"),
        Geom("box", (4.8, 0.0, 0.025), (0.50, 0.60, 0.025), W, name="矮台阶"),
    ]
    landmarks: Dict[str, Tuple[float, float]] = {
        "集合点": (0.0, 0.0),
        "左上角": (-3.5, 2.5), "右上角": (3.5, 2.5),
        "左下角": (-3.5, -2.5), "右下角": (3.5, -2.5),
        "红色柱子": (-2.5, 1.8), "蓝色箱子": (2.5, 1.8),
        "绿色柱子": (-2.5, -1.8), "黄色箱子": (2.5, -1.8),
        "路障": (0.0, 1.3), "地形测试区": (4.0, 0.0),
    }
    return Scene(geoms=geoms, landmarks=landmarks)


SCENES: Dict[str, Scene] = {"bare": Scene()}
SCENES["demo"] = _demo_scene()
SCENES["solo"] = SCENES["demo"]


def get_scene(name: str) -> Scene:
    return SCENES[name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_scene.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/scene.py g1_brain/tests/fleet/test_scene.py
git commit -m "feat(fleet): scene registry — props/terrain geoms + named landmarks"
```

---

## Task 2: Wire the scene into `SharedG1World`

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/shared_world.py`
- Test: `g1_brain/tests/fleet/test_shared_world_scene.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_shared_world_scene.py
from g1_brain.fleet.sim.shared_world import SharedG1World


def test_bare_world_geometry_unchanged():
    bare = SharedG1World(scene="bare")
    assert bare.m.nq == 72 and bare.m.nu == 58          # same as today
    assert bare.obstacles() == [] and bare.landmarks() == {}


def test_demo_world_adds_static_geoms_no_dofs():
    bare = SharedG1World(scene="bare")
    demo = SharedG1World(scene="demo")
    # static geoms add NO degrees of freedom (the performance contract)
    assert demo.m.nq == bare.m.nq and demo.m.nv == bare.m.nv
    assert demo.m.ngeom > bare.m.ngeom                  # geoms were added
    assert len(demo.obstacles()) >= 4                   # avoidance footprints
    assert all(len(o) == 3 for o in demo.obstacles())   # (x, y, r)
    assert "集合点" in demo.landmarks()


def test_demo_world_render_footprints():
    demo = SharedG1World(scene="demo")
    fp = demo.scene_render()
    assert fp and {"type", "x", "y", "sx", "sy", "rgba", "name"} <= set(fp[0])


def test_solo_spawn_defaults_for_one_robot():
    w = SharedG1World(robot_ids=("g1_a",), scene="demo")
    x, y, _ = w.base_pose("g1_a")
    assert x < -1.0                                      # spawned, no KeyError
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_shared_world_scene.py -v`
Expected: FAIL — `SharedG1World.__init__() got an unexpected keyword argument 'scene'`.

- [ ] **Step 3: Write minimal implementation**

In `g1_brain/g1_brain/fleet/sim/shared_world.py`:

(a) Add the import near the top (after the existing imports):

```python
from g1_brain.fleet.sim.scene import get_scene
```

(b) Add a module-level helper above `class SharedG1World` (after `_load_default_q`):

```python
def _default_spawn(robot_ids) -> Dict[str, Tuple[float, float]]:
    """Spread robots along x at y=0. Handles any count (1 robot -> -1.5,0)."""
    n = len(robot_ids)
    if n == 1:
        return {robot_ids[0]: (-1.5, 0.0)}
    xs = [-1.5 + 3.0 * i / (n - 1) for i in range(n)]
    return {rid: (xs[i], 0.0) for i, rid in enumerate(robot_ids)}
```

(c) Change the constructor signature and spawn default, and add the scene geoms.
Replace the signature line and the `spawn = spawn or {...}` line:

```python
    def __init__(self, *, robot_ids=("g1_a", "g1_b"),
                 spawn: Dict[str, Tuple[float, float]] | None = None,
                 timestep: float = 0.005, scene: str = "bare"):
        spawn = spawn or _default_spawn(robot_ids)
        self.scene_name = scene
        self._scene = get_scene(scene)
        self.default_q = _load_default_q()
        spec = mujoco.MjSpec()
        spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE, size=[0, 0, 0.05])
        self._add_scene_geoms(spec)
        for rid in robot_ids:
```

(Leave the rest of the robot-attach loop and everything after it unchanged.)

(d) Add these methods to `SharedG1World` (e.g. after `neighbors`):

```python
    _GTYPE = {"box": mujoco.mjtGeom.mjGEOM_BOX,
              "cylinder": mujoco.mjtGeom.mjGEOM_CYLINDER}

    def _add_scene_geoms(self, spec) -> None:
        """Add the scene's static primitives to the worldbody (no body/joint)."""
        for g in self._scene.geoms:
            geom = spec.worldbody.add_geom(
                type=self._GTYPE[g.gtype], pos=list(g.pos),
                size=list(g.size), rgba=list(g.rgba))
            geom.quat = list(g.quat)
            if g.name:
                geom.name = g.name

    def obstacles(self) -> List[Tuple[float, float, float]]:
        """Circular footprints (x, y, r) the navigator avoids (props only)."""
        return [(g.pos[0], g.pos[1], g.avoid_r)
                for g in self._scene.geoms if g.avoid_r > 0]

    def landmarks(self) -> Dict[str, Tuple[float, float]]:
        return dict(self._scene.landmarks)

    def scene_render(self) -> List[dict]:
        """Top-down footprints for the web map (box: half-extents sx,sy;
        cylinder: radius in sx,sy)."""
        out = []
        for g in self._scene.geoms:
            sx = g.size[0]
            sy = g.size[1] if g.gtype == "box" else g.size[0]
            out.append({"type": g.gtype, "x": g.pos[0], "y": g.pos[1],
                        "sx": sx, "sy": sy, "rgba": list(g.rgba), "name": g.name})
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_shared_world_scene.py g1_brain/tests/fleet/test_shared_world.py -v`
Expected: PASS (new file's 4 tests + the existing 5 still green — backward compatible).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/shared_world.py g1_brain/tests/fleet/test_shared_world_scene.py
git commit -m "feat(fleet): SharedG1World loads scene geoms (static, zero DOFs) + accessors"
```

---

## Task 3: Reactive avoidance in `nav.py`

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/nav.py`
- Test: `g1_brain/tests/fleet/test_nav_avoid.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_nav_avoid.py
from g1_brain.fleet.sim.nav import nav_command, RANGES


def test_no_obstacle_matches_plain_goal():
    # empty obstacles -> behaves like the plain go-to-goal
    a = nav_command((0.0, 0.0, 0.0), (4.0, 0.0))
    b = nav_command((0.0, 0.0, 0.0), (4.0, 0.0), obstacles=())
    assert a == b


def test_obstacle_induces_lateral_or_turn():
    base = nav_command((1.0, 0.0, 0.0), (4.0, 0.0))
    avo = nav_command((1.0, 0.0, 0.0), (4.0, 0.0), obstacles=[(2.0, 0.0, 0.4)])
    # the obstacle straddling the path forces a sideways/heading change
    assert abs(avo[1]) > abs(base[1]) + 1e-3 or abs(avo[2]) > abs(base[2]) + 1e-3


def test_peer_pushes_away():
    avo = nav_command((0.0, 0.0, 0.0), (4.0, 0.0), peer=(0.6, 0.4))
    assert abs(avo[1]) > 1e-3 or abs(avo[2]) > 1e-3


def test_still_clamped_to_ranges_with_obstacles():
    vx, vy, wz = nav_command((1.0, 0.0, 0.0), (100.0, 0.0),
                             obstacles=[(2.0, 0.1, 0.4)])
    assert RANGES["vx"][0] <= vx <= RANGES["vx"][1]
    assert RANGES["vy"][0] <= vy <= RANGES["vy"][1]
    assert RANGES["wz"][0] <= wz <= RANGES["wz"][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nav_avoid.py -v`
Expected: FAIL — `nav_command() got an unexpected keyword argument 'obstacles'`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `nav_command` in `g1_brain/g1_brain/fleet/sim/nav.py` with this (keep the module docstring, `RANGES`, and `_clip` above it):

```python
def nav_command(pose: Tuple[float, float, float], goal: Tuple[float, float], *,
                stop_radius: float = 0.25, k_fwd: float = 1.2, k_lat: float = 1.2,
                k_yaw: float = 1.5, slow_yaw_deg: float = 60.0,
                slow_radius: float = 0.8,
                obstacles=(), peer: Tuple[float, float] = None,
                avoid_radius: float = 0.9, k_avoid: float = 0.9
                ) -> Tuple[float, float, float]:
    x, y, yaw = pose
    gx, gy = goal
    ex, ey = gx - x, gy - y
    dist = math.hypot(ex, ey)
    if dist < stop_radius:
        return (0.0, 0.0, 0.0)
    gxn, gyn = ex / dist, ey / dist                 # unit goal direction
    # goal pull: full speed far away, eased within slow_radius
    approach = min(1.0, dist / slow_radius)
    des_x, des_y = approach * gxn, approach * gyn

    # reactive repulsion from obstacle circles (+ optional peer as a moving one)
    obs = list(obstacles)
    if peer is not None:
        obs = obs + [(peer[0], peer[1], 0.45)]
    for ox, oy, orad in obs:
        dx, dy = x - ox, y - oy                      # obstacle -> robot
        d = math.hypot(dx, dy)
        reach = avoid_radius + orad
        if 1e-6 < d < reach:
            w = k_avoid * (reach - d) / reach
            ux, uy = dx / d, dy / d                  # radial push (away)
            des_x += w * ux
            des_y += w * uy
            # tangential bias to escape head-on local minima: only when the
            # obstacle is roughly ahead toward the goal
            ahead = (-ux) * gxn + (-uy) * gyn
            if ahead > 0.3:
                cross = gxn * (-uy) - gyn * (-ux)
                sgn = 1.0 if cross >= 0 else -1.0
                des_x += 0.8 * w * (-uy) * sgn
                des_y += 0.8 * w * (ux) * sgn

    heading_err = math.atan2(des_y, des_x) - yaw
    heading_err = math.atan2(math.sin(heading_err), math.cos(heading_err))
    wz = _clip(k_yaw * heading_err, *RANGES["wz"])
    c, s = math.cos(-yaw), math.sin(-yaw)
    e_fwd = c * des_x - s * des_y
    e_lat = s * des_x + c * des_y
    facing = max(0.0, math.cos(heading_err))
    if abs(math.degrees(heading_err)) > slow_yaw_deg:
        facing = 0.0
    vx = _clip(k_fwd * e_fwd * facing, *RANGES["vx"])
    vy = _clip(k_lat * e_lat * facing, *RANGES["vy"])
    return (vx, vy, wz)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nav_avoid.py g1_brain/tests/fleet/test_nav.py -v`
Expected: PASS — new avoidance tests AND the 4 existing `test_nav.py` tests (no-obstacle behaviour preserved).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/nav.py g1_brain/tests/fleet/test_nav_avoid.py
git commit -m "feat(fleet): nav_command reactive repulsion (props + peer), range-clamped"
```

---

## Task 4: Feed obstacles + peer into the backend

**Files:**
- Modify: `g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py`

- [ ] **Step 1: Add the `peer_avoid` flag (constructor)**

In `RlSharedBackend.__init__`, after `self._last_tau = [0.0] * 29` add:

```python
        self.peer_avoid: bool = True       # avoid the other robot unless converging
```

- [ ] **Step 2: Add the setter**

After `set_idle` (or any method), add:

```python
    def set_peer_avoid(self, on: bool) -> None:
        self.peer_avoid = bool(on)
```

- [ ] **Step 3: Use obstacles + peer in `_drive`**

Replace the `walk` branch at the top of `_drive` (the `if self._mode == "walk" ...` block) with:

```python
        if self._mode == "walk" and self._goal is not None:
            pose = self.world.base_pose(self.rid)
            obstacles = self.world.obstacles() if hasattr(self.world, "obstacles") else ()
            peer = None
            if self.peer_avoid:
                nb = self.world.neighbors(self.rid)
                if nb:
                    peer = (pose[0] + nb[0]["dx"], pose[1] + nb[0]["dy"])
            vx, vy, wz = nav_command(pose, self._goal,
                                     obstacles=obstacles, peer=peer)
            if (vx, vy, wz) == (0.0, 0.0, 0.0):
                self.last_posture = Posture.ACTIVE
                self._mode = "idle"
            self.ctl.set_command(vx, vy, wz)
```

- [ ] **Step 4: Run the existing backend + RL adapter tests to verify no regression**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_rl_shared_backend.py g1_brain/tests/fleet/test_rl_adapter.py -v`
Expected: PASS (existing tests still green; the bare world's `obstacles()` is `[]` so behaviour is unchanged off the demo scene).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py
git commit -m "feat(fleet): backend feeds scene obstacles + peer into nav (peer_avoid flag)"
```

---

## Task 5: `WorldSim` scene + thread-safe wrappers

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/shared_world_node.py`

- [ ] **Step 1: Add `scene` to the constructor**

Change `WorldSim.__init__`:

```python
    def __init__(self, robot_ids=("g1_a", "g1_b"), spawn=None, scene="bare"):
        self.world = SharedG1World(robot_ids=robot_ids, spawn=spawn, scene=scene)
```

(Leave the rest of `__init__` unchanged.)

- [ ] **Step 2: Add the wrappers**

After `set_arms_up` add:

```python
    def set_peer_avoid(self, rid, on: bool):
        with self._lock:
            self.backends[rid].set_peer_avoid(on)

    def obstacles(self):
        return self.world.obstacles()

    def landmarks(self):
        return self.world.landmarks()

    def scene_render(self):
        return self.world.scene_render()
```

(`obstacles`/`landmarks`/`scene_render` are static, so no lock is required.)

- [ ] **Step 3: Verify solo + scene construct and tick**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_shared_world_scene.py -v && conda run -n agi python -c "import sys; from g1_brain.fleet.sim.shared_world_node import WorldSim; w=WorldSim(robot_ids=('g1_a',), scene='demo'); w._step_once(); print('solo+demo tick OK', list(w.telemetry()))"`
Expected: prints `solo+demo tick OK ['g1_a']` with no errors.

- [ ] **Step 4: Run the world-node smoke test if present**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_world_render_lock.py -v`
Expected: PASS (no regression).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/shared_world_node.py
git commit -m "feat(fleet): WorldSim(scene=) + set_peer_avoid/obstacles/landmarks/scene_render"
```

---

## Task 6: Executor disables peer-avoid while converging

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/live_executor.py`
- Test: `g1_brain/tests/fleet/test_executor_peer_avoid.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_executor_peer_avoid.py
from g1_brain.fleet.sim.live_executor import LiveExecutor
from g1_brain.fleet.coordinator.fleet_plan import FleetPlan, SubAgentOp, Coordination


class FakeWorld:
    def __init__(self):
        self.pose = {"g1_a": (0.0, 0.0, 0.0)}
        self.peer_avoid = {}
    def telemetry(self):
        return {"g1_a": {"pose": self.pose["g1_a"], "neighbors": []}}
    def set_nav_goal(self, rid, x, y): pass
    def set_face(self, rid, x, y): pass
    def set_idle(self, rid): pass
    def set_peer_avoid(self, rid, on): self.peer_avoid[rid] = on


def _exec_with(op):
    w = FakeWorld()
    ex = LiveExecutor(w)
    plan = FleetPlan(summary="t", coordination=Coordination(type="navigate"))
    ex.submit(plan, {"g1_a": [op]})
    ex.step()
    return w.peer_avoid["g1_a"]


def test_navigate_keeps_peer_avoid_on():
    assert _exec_with(SubAgentOp(op="navigate", args={"x": 2.0, "y": 0.0})) is True


def test_face_turns_peer_avoid_off():
    assert _exec_with(SubAgentOp(op="face", args={"x": 1.0, "y": 0.0})) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_executor_peer_avoid.py -v`
Expected: FAIL — `KeyError: 'g1_a'` (executor never calls `set_peer_avoid`).

- [ ] **Step 3: Write minimal implementation**

In `LiveExecutor.step`, inside the `for rid in m.ops:` loop, immediately after the line `op = m.ops[rid][i]` (just before `px, py, yaw = t["pose"]`), add:

```python
            if hasattr(self._world, "set_peer_avoid"):
                self._world.set_peer_avoid(rid, op.op not in ("await_barrier", "face"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_executor_peer_avoid.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run existing executor/command-center tests for no regression**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_command_center_app.py g1_brain/tests/fleet/test_command_center_e2e.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/live_executor.py g1_brain/tests/fleet/test_executor_peer_avoid.py
git commit -m "feat(fleet): executor disables peer-avoid during await_barrier/face"
```

---

## Task 7: Offline NL → position parser (`nl_position.py`)

**Files:**
- Create: `g1_brain/g1_brain/fleet/coordinator/nl_position.py`
- Test: `g1_brain/tests/fleet/test_nl_position.py`

- [ ] **Step 1: Write the failing test**

```python
# g1_brain/tests/fleet/test_nl_position.py
from g1_brain.fleet.coordinator.nl_position import parse_position_command

SNAP = {
    "robots": [
        {"robot_id": "g1_a", "x": -1.5, "y": 0.0, "yaw": 0.0},
        {"robot_id": "g1_b", "x": 1.5, "y": 0.0, "yaw": 3.14159},
    ],
    "landmarks": {"集合点": [0.0, 0.0], "红色柱子": [-2.5, 1.8], "左上角": [-3.5, 2.5]},
}


def test_absolute_coords():
    r = parse_position_command("g1_a 走到 2,1", SNAP)
    assert list(r["ops"]) == ["g1_a"]
    op = r["ops"]["g1_a"][0]
    assert op.op == "navigate" and op.args == {"x": 2.0, "y": 1.0}


def test_named_landmark():
    r = parse_position_command("让 g1_a 去红色柱子", SNAP)
    assert r["ops"]["g1_a"][0].args == {"x": -2.5, "y": 1.8}


def test_relative_forward():
    # g1_a faces +x (yaw 0), forward 2m -> x grows by 2
    r = parse_position_command("g1_a 前进 2米", SNAP)
    args = r["ops"]["g1_a"][0].args
    assert abs(args["x"] - 0.5) < 1e-6 and abs(args["y"]) < 1e-6


def test_multi_robot_all():
    r = parse_position_command("两机都去集合点", SNAP)
    assert set(r["ops"]) == {"g1_a", "g1_b"}
    assert r["ops"]["g1_a"][0].args == {"x": 0.0, "y": 0.0}


def test_ambiguous_returns_none():
    # two robots, no id, not "all" -> let codex/commander handle
    assert parse_position_command("走到 2,1", SNAP) is None


def test_choreography_not_hijacked():
    assert parse_position_command("两机顺时针绕圈", SNAP) is None


def test_non_positional_returns_none():
    assert parse_position_command("你好", SNAP) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nl_position.py -v`
Expected: FAIL — `ModuleNotFoundError: ... coordinator.nl_position`.

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/coordinator/nl_position.py
"""Deterministic offline NL -> position parser. Lets the command center drive
robot positions WITHOUT codex: absolute coords, named landmarks, relative moves,
and multi-robot ("all") targeting. Returns navigate ops or None if the command
isn't a position command (so plan_mission can fall through to choreography /
the commander). Choreography verbs (circle/face/arms) are deliberately NOT
handled here -> returns None so they reach the choreographer."""
from __future__ import annotations

import math
import re
from typing import Dict, List, Optional

from g1_brain.fleet.coordinator.fleet_plan import SubAgentOp
from g1_brain.fleet.sim.scene import resolve_landmark

_RID_RE = re.compile(r"(g1_[a-z])", re.I)
_COORD_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*[,，\s]\s*(-?\d+(?:\.\d+)?)")
_DIST_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:米|m\b|metre|meter)")
_FWD = ("前进", "向前", "forward", "advance")
_BACK = ("后退", "向后", "backward", "retreat")
_ALL = ("两机", "所有", "都去", "全部", "all ", "both", "everyone")
# choreography hints -> not our job (let the choreographer/codex handle)
_CHOREO = ("绕圈", "转圈", "走圈", "circle", "面对面", "面朝", "对视", "face",
           "抬手", "举手", "双手", "arms", "hands up", "排成", "列队")


def parse_position_command(nl: str, snapshot: dict) -> Optional[dict]:
    text = (nl or "").strip()
    if not text:
        return None
    low = text.lower()
    if any(k in low for k in _CHOREO):
        return None

    robots = snapshot.get("robots", [])
    ids = [r["robot_id"] for r in robots]
    if not ids:
        return None
    pose = {r["robot_id"]: (float(r.get("x", 0.0)), float(r.get("y", 0.0)),
                            float(r.get("yaw", 0.0))) for r in robots}
    landmarks = snapshot.get("landmarks", {}) or {}

    # which robots?
    lid = {i.lower(): i for i in ids}
    named = [lid[m.lower()] for m in _RID_RE.findall(text) if m.lower() in lid]
    if any(k in low for k in _ALL):
        targets = list(ids)
    elif named:
        targets = named
    elif len(ids) == 1:
        targets = list(ids)
    else:
        return None                                   # ambiguous -> fall through
    if not targets:
        return None

    # relative move?
    if any(k in low for k in _FWD + _BACK):
        m = _DIST_RE.search(low)
        d = float(m.group(1)) if m else 1.0
        sign = -1.0 if any(k in low for k in _BACK) else 1.0
        ops: Dict[str, List[SubAgentOp]] = {}
        for rid in targets:
            px, py, yaw = pose[rid]
            gx = round(px + sign * d * math.cos(yaw), 3)
            gy = round(py + sign * d * math.sin(yaw), 3)
            ops[rid] = [SubAgentOp(op="navigate", args={"x": gx, "y": gy})]
        return {"summary": f"相对移动 {sign * d:+.1f}m", "ops": ops}

    # landmark, else absolute coords
    goal = resolve_landmark(landmarks, text)
    if goal is None:
        mm = _COORD_RE.search(text)
        if mm:
            goal = (float(mm.group(1)), float(mm.group(2)))
    if goal is None:
        return None
    gx, gy = goal
    ops = {rid: [SubAgentOp(op="navigate", args={"x": gx, "y": gy})]
           for rid in targets}
    return {"summary": f"前往 ({gx:.1f}, {gy:.1f})", "ops": ops}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nl_position.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/coordinator/nl_position.py g1_brain/tests/fleet/test_nl_position.py
git commit -m "feat(fleet): offline NL position parser (coords/landmark/relative/multi)"
```

---

## Task 8: Route position commands in `plan_mission`

**Files:**
- Modify: `g1_brain/g1_brain/fleet/coordinator/choreographer.py`
- Test: `g1_brain/tests/fleet/test_nl_position.py` (add a routing test)

- [ ] **Step 1: Add the failing routing test**

Append to `g1_brain/tests/fleet/test_nl_position.py`:

```python
from g1_brain.fleet.coordinator.choreographer import plan_mission


def test_plan_mission_routes_position_without_codex():
    res = plan_mission("g1_a 走到 2,1", SNAP, llm=None)
    assert res["ok"] is True
    assert res["plan"].coordination.type == "navigate"
    assert res["ops"]["g1_a"][0].op == "navigate"


def test_plan_mission_still_does_circle_without_codex():
    # choreography path is not stolen by the position parser
    res = plan_mission("两机顺时针绕圈", SNAP, llm=None)
    assert res["ok"] is True
    assert res["plan"].coordination.type == "choreography"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nl_position.py::test_plan_mission_routes_position_without_codex -v`
Expected: FAIL — routed to the commander, `coordination.type` is not `"navigate"` (or ok is False).

- [ ] **Step 3: Write minimal implementation**

In `g1_brain/g1_brain/fleet/coordinator/choreographer.py`, inside `plan_mission`, insert a new block **between** the codex block (step 1) and the deterministic-choreography block (step 2). Place it right after the codex `try/except` and before the `# 2) deterministic choreography ...` comment:

```python
    # 1.5) deterministic offline position parser (coords/landmark/relative/multi)
    #      — makes NL position control work WITHOUT codex.
    from g1_brain.fleet.coordinator.nl_position import parse_position_command
    pos = parse_position_command(nl, snapshot)
    if pos is not None and pos.get("ops"):
        try:
            ops = parse_ops(pos["ops"], known)
            if any(ops.values()):
                plan = FleetPlan(summary=pos["summary"],
                                 coordination=Coordination(type="navigate"))
                return {"ok": True, "plan": plan, "ops": ops,
                        "needs_clarification": None, "reason": None}
        except ValueError as e:
            return {"ok": False, "plan": None, "ops": {},
                    "needs_clarification": None, "reason": str(e)}
```

(The position parser already returns `None` for choreography verbs, so the circle/face/arms path below is untouched.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_nl_position.py -v`
Expected: PASS (all 9 tests, including the 2 routing tests).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/coordinator/choreographer.py g1_brain/tests/fleet/test_nl_position.py
git commit -m "feat(fleet): plan_mission routes positions via offline parser (no codex needed)"
```

---

## Task 9: Command-center launcher — scene/solo, snapshot, /scene, banner

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/command_center.py`
- Test: `g1_brain/tests/fleet/test_command_center_app.py` (extend)

- [ ] **Step 1a: Extend `FakeWorld` so it can serve the arena**

The file already has a `FakeWorld` class and an async `client` fixture
(pytest-aiohttp style). Add these three methods to `FakeWorld` (e.g. right after
`telemetry`) so the `/scene` endpoint has data:

```python
    def landmarks(self):
        return {"集合点": (0.0, 0.0)}

    def scene_render(self):
        return [{"type": "cylinder", "x": -2.5, "y": 1.8, "sx": 0.15,
                 "sy": 0.15, "rgba": [1, 0, 0, 1], "name": "红色柱子"}]

    def obstacles(self):
        return [(-2.5, 1.8, 0.45)]
```

- [ ] **Step 1b: Write the failing tests**

The file already imports `build_command_center_app`. Add the `_world_snapshot`
import next to it:

```python
from g1_brain.fleet.sim.command_center import build_command_center_app, _world_snapshot
```

Then append these tests (the `client` fixture already builds an app around a
`FakeWorld`, so `/scene` is served by the extended fake):

```python
def test_snapshot_carries_landmarks_and_yaw():
    snap = _world_snapshot(FakeWorld({"g1_a": (-1.5, 0.0)}))
    assert snap["robots"][0]["yaw"] == 0.0
    assert snap["landmarks"] == {"集合点": (0.0, 0.0)}


async def test_scene_endpoint_returns_geoms_and_landmarks(client):
    r = await client.get("/scene")
    data = await r.json()
    assert data["landmarks"]["集合点"] == [0.0, 0.0]
    assert data["geoms"][0]["name"] == "红色柱子"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_command_center_app.py -k "snapshot or scene_endpoint" -v`
Expected: FAIL — `_world_snapshot` has no `yaw`/`landmarks`; no `/scene` route.

- [ ] **Step 3: Write minimal implementation**

(a) Replace `_world_snapshot` in `command_center.py`:

```python
def _world_snapshot(world) -> dict:
    """Commander's fleet snapshot: robot poses (x,y,yaw) + named landmarks."""
    snap = {"robots": [{"robot_id": rid, "x": t["pose"][0], "y": t["pose"][1],
                        "yaw": t["pose"][2]}
                       for rid, t in world.telemetry().items()]}
    if hasattr(world, "landmarks"):
        snap["landmarks"] = world.landmarks()
    return snap
```

(b) In `build_command_center_app`, add the `/scene` route next to the others:

```python
    app.router.add_get("/scene", _scene)
```

(c) Add the `_scene` handler near `_world`:

```python
async def _scene(request: web.Request) -> web.Response:
    world = request.app["world"]
    geoms = world.scene_render() if hasattr(world, "scene_render") else []
    lms = world.landmarks() if hasattr(world, "landmarks") else {}
    return web.json_response({"geoms": geoms,
                              "landmarks": {k: list(v) for k, v in lms.items()}})
```

(d) Update `run(...)` to take `scene`/`solo`, build the world accordingly, print a banner, and open the browser. Replace the start of `run`:

```python
def run(*, viewer: bool = False, host: str = "127.0.0.1", port: int = 8787,
        use_codex: bool = True, model: str = "gpt-5.5", reasoning: str = "xhigh",
        scene: str = "demo", solo: bool = False) -> None:
    import webbrowser
    from g1_brain.fleet.sim.shared_world_node import WorldSim, trim_render_cost

    robot_ids = ("g1_a",) if solo else ("g1_a", "g1_b")
    sim = WorldSim(robot_ids=robot_ids, scene=scene)  # control loop not started yet
    llm = _build_codex_llm(model, reasoning, Path.cwd()) if use_codex else None
    app = build_command_center_app(sim, llm=llm)
    state = _serve_in_thread(app, host, port)
    url = f"http://{host}:{port}/"
    print("\n" + "=" * 60, flush=True)
    print(f"[command-center] 控制台 / console:  {url}", flush=True)
    print(f"[command-center] 场景 scene={scene}  机器人 {list(robot_ids)}"
          + ("  (solo)" if solo else ""), flush=True)
    print("[command-center] 试试 / try:  g1_a 走到 2,1 · 去红色柱子 · "
          "两机都去集合点 · 顺时针绕圈", flush=True)
    print("=" * 60 + "\n", flush=True)
    try:
        webbrowser.open(url)               # best-effort; harmless if headless
    except Exception:                       # noqa: BLE001
        pass
    try:
```

(Leave everything from the existing `if viewer:` line onward unchanged — it already references `sim`.)

(e) In `main()`, add the two flags and pass them through. After the `--reasoning` argument add:

```python
    ap.add_argument("--scene", default="demo", choices=["bare", "demo"],
                    help="arena scene (demo = props + terrain; bare = flat)")
    ap.add_argument("--solo", action="store_true",
                    help="single robot (g1_a) for solo performance testing")
```

and change the `run(...)` call to:

```python
    run(viewer=args.viewer, host=args.host, port=args.port,
        use_codex=not args.no_codex, model=args.model, reasoning=args.reasoning,
        scene=args.scene, solo=args.solo)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/test_command_center_app.py -v`
Expected: PASS (existing + 2 new tests).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/command_center.py g1_brain/tests/fleet/test_command_center_app.py
git commit -m "feat(fleet): command center --scene/--solo, /scene endpoint, snapshot landmarks+yaw, banner"
```

---

## Task 10: Web map draws props + landmarks; examples hint

**Files:**
- Modify: `g1_brain/g1_brain/fleet/sim/command_center_ui.py`

This task is HTML/JS inside the `INDEX_HTML` string; verification is by load + a JS-free structural check plus the manual viewer check in Task 11.

- [ ] **Step 1: Add the examples hint under the chat input**

In `INDEX_HTML`, find the chat card's `.row` div and add a hint line right after the closing `</div>` of that `.row` (before `<div id="chatlog">`):

```html
    <div class="muted" style="margin-top:6px">
      例 / examples: g1_a 走到 2,1 · 去红色柱子 · 两机都去集合点 · g1_a 前进 2米 · 顺时针绕圈
    </div>
```

- [ ] **Step 2: Fetch the scene once and draw it on the map**

In the `<script>`, after the `let order = [];` line add:

```javascript
let scene = {geoms:[], landmarks:{}};
fetch('/scene').then(r=>r.json()).then(s=>{scene=s; world();}).catch(()=>{});
```

Then, inside `drawMap`, right after the grid/ring lines are appended (after the
`for(const r of [1,2]) ...` line), insert the scene-drawing block:

```javascript
  // static arena: props (filled) + named landmarks (labelled)
  for(const g of scene.geoms){
    const gx=fx(g.x), gy=fy(g.y);
    const col = `rgba(${(g.rgba[0]*255)|0},${(g.rgba[1]*255)|0},${(g.rgba[2]*255)|0},0.85)`;
    if(g.type==='cylinder'){
      s += `<circle cx="${gx}" cy="${gy}" r="${g.sx*SC}" fill="${col}" stroke="#0b0e13"/>`;
    } else {
      s += `<rect x="${gx-g.sx*SC}" y="${gy-g.sy*SC}" width="${g.sx*2*SC}" `+
           `height="${g.sy*2*SC}" fill="${col}" stroke="#0b0e13"/>`;
    }
  }
  for(const name in scene.landmarks){
    const p=scene.landmarks[name], lx=fx(p[0]), ly=fy(p[1]);
    s += `<circle cx="${lx}" cy="${ly}" r="2.5" fill="#8b949e"/>`+
         `<text x="${lx+5}" y="${ly-4}" style="fill:#6e7681">${name}</text>`;
  }
```

- [ ] **Step 3: Verify the page still serves and contains the new bits**

Run: `conda run -n agi python -c "from g1_brain.fleet.sim.command_center_ui import INDEX_HTML; assert '/scene' in INDEX_HTML and 'examples' in INDEX_HTML and 'scene.geoms' in INDEX_HTML; print('UI OK', len(INDEX_HTML), 'bytes')"`
Expected: prints `UI OK <n> bytes` with no AssertionError.

- [ ] **Step 4: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/command_center_ui.py
git commit -m "feat(fleet): web map draws arena props + landmark labels; examples hint"
```

---

## Task 11: Full-suite regression + manual viewer check + usage doc

**Files:**
- Create: `docs/command-center-arena-how-to-use.md`

- [ ] **Step 1: Run the whole fleet test suite**

Run: `conda run -n agi python -m pytest g1_brain/tests/fleet/ -q`
Expected: all green. If any pre-existing test fails for an unrelated reason, note it; the new/changed tests must pass.

- [ ] **Step 2: Headless real-time sanity (perf contract)**

Run: `conda run -n agi python -c "
import time
from g1_brain.fleet.sim.shared_world_node import WorldSim
w=WorldSim(scene='demo'); 
t0=time.perf_counter()
for _ in range(50): w._step_once()
dt=(time.perf_counter()-t0)/50
print('avg step', round(dt*1000,2), 'ms (budget 20ms @50Hz)')
assert dt < 0.02, 'demo scene broke real-time'
print('PERF OK')"`
Expected: `avg step <ms>` well under 20 ms, then `PERF OK`.

- [ ] **Step 3: Manual viewer check (operator)**

Run (operator, not automated):
`conda run -n agi python -m g1_brain.fleet.sim.command_center --viewer --scene demo`
then open `http://127.0.0.1:8787/`. Confirm:
- props (red/green pillars, blue/yellow boxes, 路障, 矮墙) and the gentle terrain
  strip are visible in both the 3D window and the 2D map, with landmark labels;
- type `g1_a 走到 2,1` (works with `--no-codex` too) → g1_a walks there;
- type `去红色柱子` → robot heads to the red pillar and the others are avoided;
- type `两机都去集合点` → both converge (peer-avoid auto-off lets them meet);
- send a robot to `地形测试区` → it traverses the ramp without falling.
Also try `--solo`:
`conda run -n agi python -m g1_brain.fleet.sim.command_center --viewer --solo --no-codex`

- [ ] **Step 4: Write the usage doc**

```markdown
# AI 指挥调度中心 — 障碍/地形 Demo 场景 & 自然语言位置控制

> 分支 feature/multi-geo，2026-06-08。设计/计划见
> docs/superpowers/specs/2026-06-08-fleet-command-center-positions-and-arena-design.md
> docs/superpowers/plans/2026-06-08-fleet-command-center-positions-and-arena.md

## 启动

完整体验（codex 大脑 + 3D 窗口 + 网页控制台 + demo 场景）：
\`\`\`bash
conda run -n agi python -m g1_brain.fleet.sim.command_center --viewer --scene demo
# 浏览器会自动打开 http://127.0.0.1:8787/
\`\`\`
不依赖 codex（确定性，离线也能做位置控制）：加 \`--no-codex\`。
单机测试：加 \`--solo\`（只有 g1_a）。回到空地板：\`--scene bare\`。

## 自然语言位置控制（无需 codex 也可用）

在网页 "AI 指挥官" 输入框里直接说：
- 绝对坐标：\`g1_a 走到 2,1\` / \`g1_a go to 2,1\`
- 命名地标：\`去红色柱子\` / \`到集合点\` / \`左上角\`
- 相对移动：\`g1_a 前进 2米\` / \`g1_a 后退 1m\`
- 多机：\`两机都去集合点\` / \`all go to center\`
- 编队动作仍然有效：\`顺时针绕圈\` / \`面对面\` / \`抬双手\`

地图上会画出所有障碍物和地标名字，方便你按名字下指令。

## 场景内容（轻量，性能友好）

- 走绕障碍（机器人自动绕行）：红/绿柱子、蓝/黄箱子、路障；矮墙是背景。
- 缓地形测试带（沿 +X，机器人走上去）：~10° 斜坡 + 低起伏 + 矮台阶。
- 全部是静态 box/cylinder 基本体（无 body/关节 → 0 自由度增加，无高度场/网格/
  额外光源），对 WSL2 软件渲染几乎零额外开销。

## 避障 vs 会合

导航默认绕开静态障碍；会合 / 面对面（await_barrier / face）时自动关闭"机器人
互相躲避"，所以两机仍能贴到一起。
```

- [ ] **Step 5: Commit**

```bash
git add docs/command-center-arena-how-to-use.md
git commit -m "docs(fleet): command center arena + NL position control usage guide"
```

---

## Self-Review

**Spec coverage:**
- Single scene registry feeding 4 consumers → Task 1 (registry), consumed in Tasks 2 (world), 7/8 (parser+routing), 9/10 (snapshot+map). ✓
- Offline NL parser (coords/landmark/relative/multi) → Task 7; routing without codex → Task 8. ✓
- Lightweight arena (props + gentle terrain), perf contract (static primitives, no hfield/DOFs) → Task 1 geoms + Task 2 (asserts no new DOFs) + Task 11 Step 2 (real-time). ✓
- Reactive avoidance (props + peer) → Task 3; backend wiring → Task 4; peer auto-off while converging → Task 6. ✓
- `--solo` + command-one-in-fleet → Task 9 (`--solo`) + general robot_ids; solo spawn default → Task 2. ✓
- Discoverability (banner + browser + examples + map labels) → Tasks 9, 10. ✓
- Backward compatibility (`scene="bare"` unchanged) → Task 2 `test_bare_world_geometry_unchanged`. ✓
- Light testing only → focused unit/smoke tests + one manual check (Task 11). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `Geom(gtype,pos,size,rgba,quat,name,avoid_r)`, `Scene(geoms,landmarks)`, `get_scene`, `resolve_landmark(landmarks,text)` used identically across Tasks 1/2/7. `obstacles()`→`list[(x,y,r)]` produced in Task 2, consumed in Tasks 3/4. `scene_render()` keys `{type,x,y,sx,sy,rgba,name}` produced in Task 2, asserted in Task 9, drawn in Task 10. `set_peer_avoid(rid,on)` on WorldSim (Task 5) called by executor (Task 6) → backend `set_peer_avoid(on)` (Task 4). `nav_command(..., obstacles=, peer=)` defined Task 3, called Task 4. `parse_position_command(nl,snapshot)` defined Task 7, called Task 8. `coordination.type == "navigate"` set Task 8, asserted Task 8 test. All consistent. ✓
