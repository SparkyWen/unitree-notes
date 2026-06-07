# Phase 1 Implementation Plan — Shared-World Two-G1 RL Locomotion

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put two RL-walking G1s in ONE shared MuJoCo world (one window), each able to navigate to a point and perceive the other, without falling.

**Architecture:** Compose two G1s into one `MjModel` via `mujoco.MjSpec.attach`. Drive each robot's joints by **reusing the proven `ComboController`** (from `g1_sim_demo/g1_sim_rl_combo.py`) through a no-DDS adapter: each tick build a duck-typed `LowState` from the robot's MjData slice, call `ctl._tick()`, and redirect `_publish` to write `(q_target,kp,kd)` → PD torque into that robot's actuators. A position→velocity nav outer loop feeds `set_command(vx,vy,wz)`. The 50 Hz control runs in a dedicated thread; no LLM/HTTP in this process.

**Tech Stack:** Python 3.11 (conda env `agi`), MuJoCo 3.5.0 (`MjSpec`), onnxruntime 1.22.1 (CPU), numpy, pytest. Reuse `g1_sim_demo/g1_sim_rl_combo.py` (`DeployCfg`, `Policy`, `ComboController`, `quat_rotate_inverse`).

**How to run tests:** from `/home/helios/unitree/unitree-notes/g1_brain`:
`conda run -n agi --no-capture-output python -m pytest tests/fleet/<file>::<test> -v`

**Key constants (verified from `deploy.yaml` + probe):**
- ONNX: `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx` (obs `[1,98]` → actions `[1,29]`)
- Child MJCF: `unitree_mujoco/unitree_robots/g1/g1_29dof.xml` (29 hinge + 1 free joint; MJCF joint order = policy order = legs(12), waist(3), left arm(7), right arm(7))
- Two-G1 attach compiles to: `nq=72`, `nu=58`, per-robot free joint `g1_a/floating_base_joint`, `g1_b/floating_base_joint`
- Command ranges: vx∈[-0.5,1.0], vy∈[-0.5,0.5], wz∈[-1.0,1.0]; step_dt=0.02 (50 Hz); gait_period=0.6

**Reuse adapter contract (the crux):** `ComboController` already implements BOOT/STANDBY/engage/stand-still-bypass/wind-down. We do NOT reimplement it. We feed it state and capture its output:
- Feed: set `ctl.low_state = <duck-typed LowState>` where `low_state.motor_state[i].q/.dq` (i∈0..28) and `low_state.imu_state.quaternion` (w,x,y,z) and `low_state.imu_state.gyroscope` (3) come from the robot's MjData slice.
- Drive: call `ctl._tick()` at 50 Hz.
- Capture: override `ctl._publish(q_target)` to stash `q_target` (29-D) + current `ctl.cfg.kp*ctl.kp_scale`, `ctl.cfg.kd`; the world turns these into torque `tau = kp*(q_target-q) - kd*dq`.
- Command: `ctl.set_command(vx,vy,wz)` from the nav outer loop.

---

## File Structure

**Create:**
- `g1_brain/g1_brain/fleet/sim/shared_world.py` — `RobotSlice`, `SharedG1World` (compose, slice access, PD step, neighbor sense)
- `g1_brain/g1_brain/fleet/sim/rl_adapter.py` — `FakeLowState`, `SharedWorldController` (wraps reused `ComboController`, no DDS)
- `g1_brain/g1_brain/fleet/sim/nav.py` — `nav_command` pure function
- `g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py` — `RlSharedBackend` (`MotionBackend` impl per robot)
- `g1_brain/g1_brain/fleet/sim/shared_world_node.py` — World Sim process entry + viewer + WS
- `g1_brain/g1_brain/fleet/sim/shared_world_demo.py` — one-command launcher
- Tests: `tests/fleet/test_shared_world.py`, `test_rl_adapter.py`, `test_nav.py`, `test_rl_shared_backend.py`

**Modify:**
- `g1_brain/g1_brain/fleet/contracts/models.py` — add `navigate` capability, `WALK` posture, populate `pose`/`neighbors`
- `g1_brain/g1_brain/fleet/agent/motion/base.py` — add `WALK` posture, optional `set_nav_goal` extension point

**Import shim:** `g1_sim_demo/` is a sibling dir (not a package). `shared_world_demo.py`/`rl_adapter.py` add `g1_sim_demo` to `sys.path` then `import g1_sim_rl_combo as combo`. Verify path: `_WS / "g1_sim_demo"` where `_WS = Path(__file__).resolve().parents[4]`.

---

## Task 1: `nav_command` pure navigation outer loop

**Files:**
- Create: `g1_brain/g1_brain/fleet/sim/nav.py`
- Test: `g1_brain/tests/fleet/test_nav.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/fleet/test_nav.py
import math
from g1_brain.fleet.sim.nav import nav_command, RANGES


def test_toward_goal_straight_ahead():
    # facing +x (yaw=0), goal 2m ahead -> forward vx>0, no lateral/turn
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(2.0, 0.0))
    assert vx > 0.1 and abs(vy) < 1e-6 and abs(wz) < 1e-6


def test_stops_within_radius():
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(0.05, 0.0), stop_radius=0.2)
    assert (vx, vy, wz) == (0.0, 0.0, 0.0)


def test_turns_toward_goal_behind():
    # goal behind-left -> nonzero yaw rate to turn
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(-1.0, 1.0))
    assert abs(wz) > 0.1


def test_clamps_to_ranges():
    vx, vy, wz = nav_command(pose=(0.0, 0.0, 0.0), goal=(100.0, 0.0))
    assert RANGES["vx"][0] <= vx <= RANGES["vx"][1]
    assert RANGES["vy"][0] <= vy <= RANGES["vy"][1]
    assert RANGES["wz"][0] <= wz <= RANGES["wz"][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_nav.py -v`
Expected: FAIL (`ModuleNotFoundError: g1_brain.fleet.sim.nav`)

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/sim/nav.py
"""Position->velocity navigation outer loop for the RL velocity policy.

Converts (current pose, goal xy) into a body-frame velocity command
[vx, vy, wz], clamped to the policy's trained command ranges so we never
drive the gait policy out of distribution."""
from __future__ import annotations

import math
from typing import Tuple

RANGES = {"vx": (-0.5, 1.0), "vy": (-0.5, 0.5), "wz": (-1.0, 1.0)}


def _clip(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def nav_command(pose: Tuple[float, float, float], goal: Tuple[float, float], *,
                stop_radius: float = 0.25, k_fwd: float = 1.2, k_lat: float = 1.2,
                k_yaw: float = 1.5, slow_yaw_deg: float = 60.0) -> Tuple[float, float, float]:
    x, y, yaw = pose
    gx, gy = goal
    ex, ey = gx - x, gy - y
    dist = math.hypot(ex, ey)
    if dist < stop_radius:
        return (0.0, 0.0, 0.0)
    # error in body frame
    c, s = math.cos(-yaw), math.sin(-yaw)
    e_fwd = c * ex - s * ey
    e_lat = s * ex + c * ey
    heading_err = math.atan2(ey, ex) - yaw
    heading_err = math.atan2(math.sin(heading_err), math.cos(heading_err))  # wrap
    wz = _clip(k_yaw * heading_err, *RANGES["wz"])
    # don't barrel forward until roughly facing the goal
    facing = max(0.0, math.cos(heading_err))
    if abs(math.degrees(heading_err)) > slow_yaw_deg:
        facing = 0.0
    vx = _clip(k_fwd * e_fwd * facing, *RANGES["vx"])
    vy = _clip(k_lat * e_lat * facing, *RANGES["vy"])
    return (vx, vy, wz)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_nav.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
cd /home/helios/unitree/unitree-notes
git add g1_brain/g1_brain/fleet/sim/nav.py g1_brain/tests/fleet/test_nav.py
git commit -m "feat(fleet): position->velocity nav outer loop (P1)"
```

---

## Task 2: `SharedG1World` — compose two G1s, slices, PD step

**Files:**
- Create: `g1_brain/g1_brain/fleet/sim/shared_world.py`
- Test: `g1_brain/tests/fleet/test_shared_world.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/fleet/test_shared_world.py
import numpy as np
from g1_brain.fleet.sim.shared_world import SharedG1World


def test_composes_two_g1s():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"))
    assert w.m.nu == 58 and w.m.nq == 72
    assert set(w.slices) == {"g1_a", "g1_b"}


def test_distinct_base_positions():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"), spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    xa, ya, _ = w.base_pose("g1_a")
    xb, yb, _ = w.base_pose("g1_b")
    assert xa < -1.0 and xb > 1.0


def test_joint_state_shapes():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"))
    q, dq = w.joint_state("g1_a")
    assert q.shape == (29,) and dq.shape == (29,)


def test_neighbor_sense_symmetric():
    w = SharedG1World(robot_ids=("g1_a", "g1_b"), spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    na = w.neighbors("g1_a")
    assert na and na[0]["peer"] == "g1_b"
    assert abs(na[0]["dist"] - 3.0) < 0.6  # ~3m apart at spawn
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_shared_world.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/sim/shared_world.py
"""Two G1s in ONE MjModel (MjSpec.attach), with per-robot slices, PD step,
and neighbor sense. The RL controller (rl_adapter) supplies (q_target,kp,kd);
this world turns them into joint torque tau = kp*(q_target-q) - kd*dq."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import mujoco

_WS = Path(__file__).resolve().parents[4]
_CHILD = _WS / "unitree_mujoco" / "unitree_robots" / "g1" / "g1_29dof.xml"
_NJ = 29
_STAND_Z = 0.78  # pelvis spawn height (m)


@dataclass
class RobotSlice:
    qpos_adr: int   # base free-joint qpos start (7: xyz + quat)
    qvel_adr: int   # base free-joint qvel start (6: lin + ang)
    qj_adr: int     # first hinge-joint qpos index
    dqj_adr: int    # first hinge-joint qvel index
    act_adr: int    # first actuator index
    torso_bid: int  # pelvis/torso body id (for xpos)


class SharedG1World:
    def __init__(self, *, robot_ids=("g1_a", "g1_b"),
                 spawn: Dict[str, Tuple[float, float]] | None = None,
                 timestep: float = 0.005):
        spawn = spawn or {robot_ids[0]: (-1.5, 0.0), robot_ids[1]: (1.5, 0.0)}
        spec = mujoco.MjSpec()
        spec.worldbody.add_geom(type=mujoco.mjtGeom.mjGEOM_PLANE,
                                size=[0, 0, 0.05])
        spec.worldbody.add_light(pos=[0, 0, 3], dir=[0, 0, -1], directional=True)
        for rid in robot_ids:
            x, y = spawn[rid]
            child = mujoco.MjSpec.from_file(str(_CHILD))
            frame = spec.worldbody.add_frame(pos=[x, y, _STAND_Z])
            frame.attach_body(child.worldbody.first_body(), f"{rid}/", "")
        self.m = spec.compile()
        self.m.opt.timestep = timestep
        self.d = mujoco.MjData(self.m)
        self.robot_ids = list(robot_ids)
        self.slices: Dict[str, RobotSlice] = {}
        for rid in robot_ids:
            base_j = self.m.joint(f"{rid}/floating_base_joint")
            first_hinge = self.m.joint(f"{rid}/left_hip_pitch_joint")
            torso = self.m.body(f"{rid}/pelvis") if _has_body(self.m, f"{rid}/pelvis") \
                else self.m.body(f"{rid}/torso_link")
            self.slices[rid] = RobotSlice(
                qpos_adr=base_j.qposadr[0], qvel_adr=base_j.dofadr[0],
                qj_adr=first_hinge.qposadr[0], dqj_adr=first_hinge.dofadr[0],
                act_adr=self.m.actuator(f"{rid}/left_hip_pitch_joint").id
                    if _has_act(self.m, f"{rid}/left_hip_pitch_joint")
                    else _first_act_for(self.m, rid),
                torso_bid=torso.id)
        # spawn upright
        for rid in robot_ids:
            sl = self.slices[rid]
            self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7] = (1.0, 0.0, 0.0, 0.0)
        mujoco.mj_forward(self.m, self.d)

    # ---- per-robot accessors ----
    def base_pose(self, rid: str) -> Tuple[float, float, float]:
        sl = self.slices[rid]
        x, y = self.d.qpos[sl.qpos_adr], self.d.qpos[sl.qpos_adr + 1]
        quat = self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7]
        yaw = math.atan2(2 * (quat[0] * quat[3] + quat[1] * quat[2]),
                         1 - 2 * (quat[2] ** 2 + quat[3] ** 2))
        return float(x), float(y), float(yaw)

    def base_quat(self, rid: str) -> np.ndarray:
        sl = self.slices[rid]
        return np.array(self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7])

    def base_angvel(self, rid: str) -> np.ndarray:
        sl = self.slices[rid]
        return np.array(self.d.qvel[sl.qvel_adr + 3:sl.qvel_adr + 6])

    def joint_state(self, rid: str):
        sl = self.slices[rid]
        q = np.array(self.d.qpos[sl.qj_adr:sl.qj_adr + _NJ])
        dq = np.array(self.d.qvel[sl.dqj_adr:sl.dqj_adr + _NJ])
        return q, dq

    def gravity_proj_z(self, rid: str) -> float:
        R = np.zeros(9)
        mujoco.mju_quat2Mat(R, self.base_quat(rid))
        return float((R.reshape(3, 3).T @ np.array([0.0, 0.0, -1.0]))[2])

    def set_pd(self, rid: str, q_target: np.ndarray, kp: np.ndarray, kd: np.ndarray) -> None:
        sl = self.slices[rid]
        q, dq = self.joint_state(rid)
        tau = kp * (q_target - q) - kd * dq
        self.d.ctrl[sl.act_adr:sl.act_adr + _NJ] = tau

    def neighbors(self, rid: str) -> List[dict]:
        sl = self.slices[rid]
        x, y, yaw = self.base_pose(rid)
        out = []
        for other in self.robot_ids:
            if other == rid:
                continue
            ox, oy, _ = self.base_pose(other)
            dx, dy = ox - x, oy - y
            dist = math.hypot(dx, dy)
            bearing = math.atan2(dy, dx) - yaw
            out.append({"peer": other, "dx": dx, "dy": dy, "dist": dist,
                        "bearing": math.atan2(math.sin(bearing), math.cos(bearing))})
        return out

    def step(self, n: int = 1) -> None:
        for _ in range(n):
            mujoco.mj_step(self.m, self.d)


def _has_body(m, name):
    try:
        m.body(name); return True
    except Exception:
        return False


def _has_act(m, name):
    try:
        m.actuator(name); return True
    except Exception:
        return False


def _first_act_for(m, rid):
    for i in range(m.nu):
        if m.actuator(i).name.startswith(f"{rid}/"):
            return i
    raise KeyError(rid)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_shared_world.py -v`
Expected: PASS (4 passed). If actuator/body names differ, fix the lookups using the names printed by `conda run -n agi python -c "import mujoco;..."` (probe pattern from the design phase).

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/shared_world.py g1_brain/tests/fleet/test_shared_world.py
git commit -m "feat(fleet): SharedG1World — two G1s in one MjModel + slices + neighbor sense (P1)"
```

---

## Task 3: `SharedWorldController` — reuse ComboController without DDS

**Files:**
- Create: `g1_brain/g1_brain/fleet/sim/rl_adapter.py`
- Test: `g1_brain/tests/fleet/test_rl_adapter.py`

**Why:** This is the reuse adapter (see "Reuse adapter contract" header). It builds a duck-typed `LowState` from MjData, drives `ctl._tick()`, and captures the published `(q_target,kp,kd)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/fleet/test_rl_adapter.py
import numpy as np
from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.sim.rl_adapter import SharedWorldController


def test_controller_produces_pd_targets():
    w = SharedG1World()
    ctl = SharedWorldController(w, "g1_a")
    ctl.set_command(0.0, 0.0, 0.0)
    q_target, kp, kd = ctl.compute()  # one tick of the reused ComboController
    assert q_target.shape == (29,) and kp.shape == (29,) and kd.shape == (29,)
    # at zero command the reused controller holds default_q (stand-still bypass)
    assert np.allclose(q_target, ctl.cfg.default_q, atol=0.3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_rl_adapter.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Write minimal implementation**

```python
# g1_brain/g1_brain/fleet/sim/rl_adapter.py
"""Drive the proven ComboController against a shared MjModel slice, no DDS.

ComboController (g1_sim_demo/g1_sim_rl_combo.py) owns the BOOT/STANDBY/engage/
stand-still-bypass/wind-down balance logic. We reuse it verbatim: feed a
duck-typed LowState built from MjData, call _tick(), capture _publish output."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

_WS = Path(__file__).resolve().parents[4]
_COMBO_DIR = _WS / "g1_sim_demo"
if str(_COMBO_DIR) not in sys.path:
    sys.path.insert(0, str(_COMBO_DIR))
import g1_sim_rl_combo as combo  # noqa: E402

_NJ = 29


class _MotorState:
    __slots__ = ("q", "dq")
    def __init__(self): self.q = 0.0; self.dq = 0.0


class _Imu:
    def __init__(self):
        self.quaternion = [1.0, 0.0, 0.0, 0.0]
        self.gyroscope = [0.0, 0.0, 0.0]


class FakeLowState:
    """Duck-typed LowState_: only the fields ComboController._build_obs reads."""
    def __init__(self):
        self.motor_state = [_MotorState() for _ in range(_NJ)]
        self.imu_state = _Imu()


class SharedWorldController:
    def __init__(self, world, rid: str):
        self.world = world
        self.rid = rid
        self.cfg = combo.DeployCfg(combo.POLICY_YAML)
        policy = combo.Policy(combo.POLICY_ONNX)
        self.ctl = combo.ComboController(self.cfg, policy)
        self.ctl.low_state = FakeLowState()
        self._captured = None
        # redirect _publish -> capture, never touch DDS
        def _capture(q_target):
            self._captured = np.asarray(q_target, dtype=np.float64).copy()
        self.ctl._publish = _capture  # type: ignore[assignment]
        # seed engagement so the controller leaves BOOT toward policy when walking
        self.ctl.start = lambda: None  # type: ignore[assignment]

    def set_command(self, vx, vy, wz):
        self.ctl.set_command(vx, vy, wz)

    def _refresh_lowstate(self):
        q, dq = self.world.joint_state(self.rid)
        ls = self.ctl.low_state
        for i in range(_NJ):
            ls.motor_state[i].q = float(q[i])
            ls.motor_state[i].dq = float(dq[i])
        ls.imu_state.quaternion = [float(v) for v in self.world.base_quat(self.rid)]
        ls.imu_state.gyroscope = [float(v) for v in self.world.base_angvel(self.rid)]

    def compute(self):
        """One 50 Hz control step: returns (q_target, kp, kd)."""
        self._refresh_lowstate()
        self.ctl._tick()
        q_target = self._captured if self._captured is not None else self.cfg.default_q.copy()
        kp = self.cfg.kp * getattr(self.ctl, "kp_scale", 1.0)
        kd = self.cfg.kd
        return q_target, kp, kd
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_rl_adapter.py -v`
Expected: PASS. **If it fails because `_tick` references DDS / threading / time state we didn't seed**, read the failing attribute in `g1_sim_rl_combo.py` around the cited line and stub it on `self.ctl` in `__init__` (e.g. set `self.ctl.boot_*`, `self.ctl._first_state_time`). Document each stub with a comment. This is the expected empirical step.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/rl_adapter.py g1_brain/tests/fleet/test_rl_adapter.py
git commit -m "feat(fleet): no-DDS adapter reusing ComboController balance logic (P1)"
```

---

## Task 4: PHYSICAL GATE — one robot stands + walks in the shared world

**Files:**
- Test: `g1_brain/tests/fleet/test_shared_world.py` (add)

**This is the make-or-break gate. It is empirical (run-and-observe), not a cheap unit assert.**

- [ ] **Step 1: Write the gate test**

```python
# append to tests/fleet/test_shared_world.py
import numpy as np
from g1_brain.fleet.sim.rl_adapter import SharedWorldController


def test_one_robot_stands_then_walks():
    w = SharedG1World()
    a = SharedWorldController(w, "g1_a")
    b = SharedWorldController(w, "g1_b")
    # hold both at default; step 50 Hz for 3 s -> must stay upright
    for _ in range(150):
        for c in (a, b):
            qt, kp, kd = c.compute()
            w.set_pd(c.rid, qt, kp, kd)
        w.step(int(0.02 / w.m.opt.timestep))  # 4 phys steps per control tick
    assert w.gravity_proj_z("g1_a") < -0.85, "g1_a fell while standing"
    # now command g1_a forward 3 s -> x should advance
    x0 = w.base_pose("g1_a")[0]
    a.set_command(0.6, 0.0, 0.0)
    for _ in range(150):
        for c in (a, b):
            qt, kp, kd = c.compute()
            w.set_pd(c.rid, qt, kp, kd)
        w.step(int(0.02 / w.m.opt.timestep))
    assert w.gravity_proj_z("g1_a") < -0.7, "g1_a fell while walking"
    assert w.base_pose("g1_a")[0] - x0 > 0.3, "g1_a did not walk forward"
```

- [ ] **Step 2: Run the gate**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_shared_world.py::test_one_robot_stands_then_walks -v`
Expected: PASS.

- [ ] **Step 3: If it FAILS — systematic debugging, do NOT fake it**

Invoke `superpowers:systematic-debugging`. Likely causes + fixes, in order:
1. **Falls immediately while standing** → controller never reached STANDBY/bypass. Check `ctl.kp_scale` (should ramp to 1.0) and that `_tick` is hitting the stand-still bypass at cmd=0. May need to call the controller's boot/engage seeding instead of stubbing `start`.
2. **Wobbles then falls** → PD torque sign or actuator slice wrong. Verify `set_pd` writes to the correct robot's actuator indices (print `w.slices[rid].act_adr` and `m.actuator(act_adr).name`).
3. **Walks but drifts/falls** → control rate mismatch. Ensure exactly 50 Hz control (`step_dt=0.02`) and `gait_period=0.6` phase advance per tick.
4. **Joint order mismatch** → obs built in wrong order. Confirm MJCF hinge order == policy order (legs,waist,arms) using the joint-name dump from the design phase.
If after focused effort it still falls, STOP and report to the user with the observed failure mode + the two fallback options (per-robot subprocess+namespaced-DDS reusing ComboController as-is over the existing bridge; or scripted waypoint locomotion). Do not proceed to Task 5 on a falling robot.

- [ ] **Step 4: Commit (only once green)**

```bash
git add g1_brain/tests/fleet/test_shared_world.py
git commit -m "test(fleet): physical gate — robot stands + walks in shared world (P1)"
```

---

## Task 5: PHYSICAL GATE — two robots navigate to points + meet at safe separation

**Files:**
- Test: `g1_brain/tests/fleet/test_shared_world.py` (add)

- [ ] **Step 1: Write the gate test**

```python
# append to tests/fleet/test_shared_world.py
from g1_brain.fleet.sim.nav import nav_command


def test_two_robots_rendezvous_no_collision():
    w = SharedG1World(spawn={"g1_a": (-1.5, 0.0), "g1_b": (1.5, 0.0)})
    a, b = SharedWorldController(w, "g1_a"), SharedWorldController(w, "g1_b")
    goals = {"g1_a": (-0.4, 0.0), "g1_b": (0.4, 0.0)}  # adjacent, NOT overlapping
    ctls = {"g1_a": a, "g1_b": b}
    min_sep = 99.0
    for _ in range(600):  # 12 s
        for rid, c in ctls.items():
            vx, vy, wz = nav_command(w.base_pose(rid), goals[rid], stop_radius=0.25)
            # simple avoidance: if peer within 0.5 m, stop
            if w.neighbors(rid)[0]["dist"] < 0.5:
                vx, vy, wz = 0.0, 0.0, 0.0
            c.set_command(vx, vy, wz)
            qt, kp, kd = c.compute()
            w.set_pd(rid, qt, kp, kd)
        w.step(int(0.02 / w.m.opt.timestep))
        min_sep = min(min_sep, w.neighbors("g1_a")[0]["dist"])
    assert w.gravity_proj_z("g1_a") < -0.7 and w.gravity_proj_z("g1_b") < -0.7
    assert abs(w.base_pose("g1_a")[0] - (-0.4)) < 0.4
    assert abs(w.base_pose("g1_b")[0] - 0.4) < 0.4
    assert min_sep > 0.3, "robots collided"
```

- [ ] **Step 2: Run the gate**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_shared_world.py::test_two_robots_rendezvous_no_collision -v`
Expected: PASS. If they fall on approach (OOD contact), widen goals / lower nav gains / raise avoidance radius; if still failing use `systematic-debugging` and report.

- [ ] **Step 3: Commit**

```bash
git add g1_brain/tests/fleet/test_shared_world.py
git commit -m "test(fleet): physical gate — two-robot rendezvous, no collision (P1)"
```

---

## Task 6: Contracts — `navigate` capability, `WALK` posture, pose/neighbors

**Files:**
- Modify: `g1_brain/g1_brain/fleet/contracts/models.py` (Capability Literal line 167), `g1_brain/g1_brain/fleet/agent/motion/base.py` (Posture enum)
- Test: `g1_brain/tests/fleet/test_contracts_nav.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/fleet/test_contracts_nav.py
from g1_brain.fleet.contracts.models import CommandEnvelope, Pose
from g1_brain.fleet.agent.motion.base import Posture


def test_navigate_capability_allowed():
    env = CommandEnvelope.make(issued_by="c", issued_to="g1_a",
                               capability="navigate", payload={"x": 1.0, "y": 2.0})
    assert env.capability == "navigate"


def test_walk_posture_exists():
    assert Posture.WALK.value == "WALK"


def test_pose_model():
    p = Pose(frame_id="g1_a/map", x=1.0, y=2.0, theta=0.5)
    assert (p.x, p.y, p.theta) == (1.0, 2.0, 0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_contracts_nav.py -v`
Expected: FAIL (`navigate` not in Capability Literal; `Posture.WALK` missing)

- [ ] **Step 3: Implement**

In `contracts/models.py` line 167, change:
```python
Capability = Literal["sleep", "wake", "patrol", "idle", "resume_task", "stop", "inject"]
```
to:
```python
Capability = Literal["sleep", "wake", "patrol", "idle", "resume_task", "stop", "inject", "navigate"]
```

In `agent/motion/base.py`, add to the `Posture` enum:
```python
    WALK = "WALK"       # navigating to a waypoint (RL gait, nonzero velocity cmd)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_contracts_nav.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/contracts/models.py g1_brain/g1_brain/fleet/agent/motion/base.py g1_brain/tests/fleet/test_contracts_nav.py
git commit -m "feat(fleet): navigate capability + WALK posture + Pose (P1)"
```

---

## Task 7: `RlSharedBackend` — MotionBackend over shared world + controller + nav

**Files:**
- Create: `g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py`
- Test: `g1_brain/tests/fleet/test_rl_shared_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/fleet/test_rl_shared_backend.py
from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.agent.motion.rl_shared_backend import RlSharedBackend
from g1_brain.fleet.agent.motion.base import Posture, MotionBackend


def test_is_motion_backend():
    w = SharedG1World()
    be = RlSharedBackend(w, "g1_a")
    assert isinstance(be, MotionBackend)


def test_nav_goal_sets_walk():
    w = SharedG1World()
    be = RlSharedBackend(w, "g1_a")
    be.set_nav_goal(0.0, 0.0)
    be.step()
    assert be.last_posture in (Posture.WALK, Posture.ACTIVE)
    ls = be.read_lowstate()
    assert len(ls.tau_est()) == 29
```

- [ ] **Step 2: Run test to verify it fails**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_rl_shared_backend.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement**

```python
# g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py
"""MotionBackend for one robot in a SharedG1World, driven by the reused RL
controller + nav outer loop. Posture maps to velocity command behaviour."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from g1_brain.fleet.agent.motion.base import Posture
from g1_brain.fleet.sim.nav import nav_command
from g1_brain.fleet.sim.rl_adapter import SharedWorldController


@dataclass
class _Lowstate:
    _tau: List[float]
    gravity_proj_z: float
    def tau_est(self) -> List[float]:
        return list(self._tau)


class RlSharedBackend:
    def __init__(self, world, rid: str):
        self.world = world
        self.rid = rid
        self.ctl = SharedWorldController(world, rid)
        self.last_posture: Posture = Posture.ACTIVE
        self._goal: Optional[Tuple[float, float]] = None
        self._last_tau = [0.0] * 29

    def set_posture(self, posture: Posture) -> None:
        self.last_posture = posture
        if posture in (Posture.ACTIVE, Posture.IDLE, Posture.STOP, Posture.SLEEP):
            self._goal = None
            self.ctl.set_command(0.0, 0.0, 0.0)

    def set_nav_goal(self, x: float, y: float) -> None:
        self._goal = (x, y)
        self.last_posture = Posture.WALK

    def step(self) -> None:
        if self._goal is not None:
            vx, vy, wz = nav_command(self.world.base_pose(self.rid), self._goal)
            if (vx, vy, wz) == (0.0, 0.0, 0.0):
                self.last_posture = Posture.ACTIVE
                self._goal = None
            else:
                self.last_posture = Posture.WALK
            self.ctl.set_command(vx, vy, wz)
        q_target, kp, kd = self.ctl.compute()
        self.world.set_pd(self.rid, q_target, kp, kd)
        q, dq = self.world.joint_state(self.rid)
        self._last_tau = list(np.abs(kp * (q_target - q) - kd * dq))

    def read_lowstate(self) -> _Lowstate:
        return _Lowstate(_tau=self._last_tau,
                         gravity_proj_z=self.world.gravity_proj_z(self.rid))

    def close(self) -> None:
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `conda run -n agi --no-capture-output python -m pytest tests/fleet/test_rl_shared_backend.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py g1_brain/tests/fleet/test_rl_shared_backend.py
git commit -m "feat(fleet): RlSharedBackend MotionBackend (P1)"
```

---

## Task 8: World Sim node + viewer + one-command launcher

**Files:**
- Create: `g1_brain/g1_brain/fleet/sim/shared_world_node.py`, `g1_brain/g1_brain/fleet/sim/shared_world_demo.py`

**Note:** This is integration/visual (no cheap unit assert); verify by running with `--viewer` and watching, plus a headless smoke run.

- [ ] **Step 1: Implement the World Sim node (control thread + telemetry buffers)**

```python
# g1_brain/g1_brain/fleet/sim/shared_world_node.py
"""World Sim: shared MjModel + two RL backends @50 Hz in a dedicated thread,
optional passive viewer. Exposes thread-safe set_nav_goal/set_posture and a
telemetry snapshot. No LLM/HTTP here (50 Hz must not be starved)."""
from __future__ import annotations

import argparse
import os
import threading
import time
from typing import Dict

from g1_brain.fleet.sim.shared_world import SharedG1World
from g1_brain.fleet.agent.motion.rl_shared_backend import RlSharedBackend
from g1_brain.fleet.agent.motion.base import Posture


class WorldSim:
    def __init__(self, robot_ids=("g1_a", "g1_b")):
        self.world = SharedG1World(robot_ids=robot_ids)
        self.backends: Dict[str, RlSharedBackend] = {
            rid: RlSharedBackend(self.world, rid) for rid in robot_ids}
        self._lock = threading.Lock()
        self._run = False
        self._phys_per_tick = max(1, int(round(0.02 / self.world.m.opt.timestep)))

    def set_nav_goal(self, rid, x, y):
        with self._lock:
            self.backends[rid].set_nav_goal(x, y)

    def set_posture(self, rid, posture: Posture):
        with self._lock:
            self.backends[rid].set_posture(posture)

    def telemetry(self) -> dict:
        with self._lock:
            return {rid: {"pose": self.world.base_pose(rid),
                          "gz": self.world.gravity_proj_z(rid),
                          "neighbors": self.world.neighbors(rid),
                          "posture": be.last_posture.value}
                    for rid, be in self.backends.items()}

    def _control_loop(self):
        dt = 0.02
        while self._run:
            t0 = time.perf_counter()
            with self._lock:
                for be in self.backends.values():
                    be.step()
                self.world.step(self._phys_per_tick)
            slp = dt - (time.perf_counter() - t0)
            if slp > 0:
                time.sleep(slp)

    def start(self):
        self._run = True
        self._t = threading.Thread(target=self._control_loop, daemon=True)
        self._t.start()

    def stop(self):
        self._run = False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--viewer", action="store_true")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = run forever")
    args = ap.parse_args()
    sim = WorldSim()
    sim.start()
    if args.viewer:
        os.environ.setdefault("MUJOCO_GL", "glfw")
        import mujoco.viewer
        # demo motion: send both to the centre so you SEE them meet
        sim.set_nav_goal("g1_a", -0.4, 0.0)
        sim.set_nav_goal("g1_b", 0.4, 0.0)
        with mujoco.viewer.launch_passive(sim.world.m, sim.world.d) as v:
            # cut cost (per memory: mujoco_viewer_perf / wsl2_gpu_rendering)
            v.opt.flags[mujoco.mjtVisFlag.mjVIS_SHADOW] = False
            v.opt.flags[mujoco.mjtVisFlag.mjVIS_REFLECTION] = False
            while v.is_running():
                v.sync()
                time.sleep(1 / 60)
    else:
        end = time.time() + (args.seconds or 5.0)
        sim.set_nav_goal("g1_a", -0.4, 0.0)
        sim.set_nav_goal("g1_b", 0.4, 0.0)
        while time.time() < end:
            time.sleep(0.5)
        print("[world_sim] telemetry:", sim.telemetry())
    sim.stop()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Headless smoke run**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && conda run -n agi --no-capture-output python -m g1_brain.fleet.sim.shared_world_node --seconds 8`
Expected: prints telemetry with both `gz < -0.7` and poses near the centre goals.

- [ ] **Step 3: Viewer run (human visual check)**

Run: `cd /home/helios/unitree/unitree-notes/g1_brain && conda run -n agi --no-capture-output python -m g1_brain.fleet.sim.shared_world_node --viewer`
Expected: ONE window, two G1s walk toward the centre and stop at safe separation. (If WSLg window doesn't appear, this is the localhost/display issue, not the code — see `docs/ip-gui-QA1.md` for the network analogue; for GL set `MUJOCO_GL`.)

- [ ] **Step 4: Commit**

```bash
git add g1_brain/g1_brain/fleet/sim/shared_world_node.py
git commit -m "feat(fleet): World Sim node — two RL G1s @50Hz + viewer (P1)"
```

---

## Self-Review (run after writing, before execution)

- **Spec coverage:** §4.1 SharedG1World→T2; §4.2 policy reuse→T3; §4.3 nav→T1; §4.4 RlSharedBackend→T7; §4.5 contracts→T6; §4.6 viewer/node→T8; §4.7 verification→T4/T5. ✓
- **Deferred to P2/P3 plans (out of P1 scope):** WS bridge to coordinator process, `/chat`, FleetCommander, RobotSubAgent, barrier, rendezvous scenario, full `RobotStateMsg` pose/neighbor wiring through the agent. P1 proves the physical foundation only.
- **Placeholders:** none — every code step has complete code.
- **Type consistency:** `SharedG1World.set_pd/base_pose/base_quat/base_angvel/joint_state/neighbors/gravity_proj_z`, `SharedWorldController.compute/set_command`, `nav_command` signature, `RlSharedBackend.set_nav_goal/step/read_lowstate` are consistent across tasks. ✓
- **Empirical risk is isolated to T4/T5** (physical gates) with explicit debugging + stop-and-report instructions; deterministic tasks (T1,T2,T6,T7) are cheap unit tests.
```
