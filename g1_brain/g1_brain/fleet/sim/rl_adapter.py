"""Drive the proven ComboController against a shared MjModel slice, no DDS.

ComboController (g1_sim_demo/g1_sim_rl_combo.py) owns the BOOT/engage/warm-up
balance logic. We reuse it verbatim: feed a duck-typed LowState built from
MjData, call _tick(), capture the (q_target, kp, kd) it would have published.

Two deviations from the on-robot deployment, both forced by the band-free
shared world (the policy self-balances; there is no elastic band to hold the
body up during spin-up):
  * boot_dur is shortened (default 5.0 s of default_q-PD would collapse the
    band-free robot in ~1.5 s before the policy engages).
  * the watchdog wall-clock is kept fresh each tick so it never trips.
Run compute() at ~50 Hz real time so the wall-clock POLICY_WARMUP_S completes.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

_WS = Path(__file__).resolve().parents[4]
_COMBO_DIR = _WS / "g1_sim_demo"
if str(_COMBO_DIR) not in sys.path:
    sys.path.insert(0, str(_COMBO_DIR))
import g1_sim_rl_combo as combo  # noqa: E402

_NJ = 29
_BOOT_DUR_S = 0.3  # band-free: get the policy driving before default_q collapses


class _MotorState:
    __slots__ = ("q", "dq")

    def __init__(self):
        self.q = 0.0
        self.dq = 0.0


class _Imu:
    def __init__(self):
        self.quaternion = [1.0, 0.0, 0.0, 0.0]   # w, x, y, z
        self.gyroscope = [0.0, 0.0, 0.0]


class FakeLowState:
    """Duck-typed LowState_: only the fields ComboController reads."""

    def __init__(self):
        self.motor_state = [_MotorState() for _ in range(_NJ)]
        self.imu_state = _Imu()
        self.mode_machine = 0


class SharedWorldController:
    def __init__(self, world, rid: str, *, boot_dur: float = _BOOT_DUR_S):
        self.world = world
        self.rid = rid
        self.cfg = combo.DeployCfg(combo.POLICY_YAML)
        policy = combo.Policy(combo.POLICY_ONNX)
        self.ctl = combo.ComboController(self.cfg, policy)

        # Redirect _publish -> capture (q_des, kp, kd); never touch DDS.
        self._captured = None

        def _capture(q_des):
            q_des = np.asarray(q_des, dtype=np.float64).copy()
            scale = np.full(_NJ, self.ctl.kp_scale, dtype=np.float64)
            scale[0:combo.ARM_START] *= self.ctl._leg_kp_boost
            scale[combo.ARM_START:combo.ARM_END] *= self.ctl._arm_kp_boost
            self._captured = (q_des, self.cfg.kp * scale, self.cfg.kd * scale)

        self.ctl._publish = _capture  # type: ignore[assignment]

        # Seed boot state (mirror start() without the DDS wait / control thread).
        self.ctl.low_state = FakeLowState()
        self._refresh_lowstate()
        self.ctl.first_state_received = True
        self.ctl.last_state_time = time.monotonic()
        self.ctl.boot_dur = float(boot_dur)
        self.ctl.boot_q_from = self.world.joint_state(rid)[0].copy()
        self.ctl.boot_t = 0.0
        self.ctl._boot_done = False
        self.ctl.policy_active = False
        self.ctl.kp_scale = self.ctl.boot_kp_floor
        self.ctl.global_phase = 0.0
        self.ctl.last_raw_action[:] = 0.0

    @property
    def arm_rest(self) -> np.ndarray:
        """The policy's default 14-D arm pose (basis for arm gestures)."""
        return np.asarray(self.cfg.default_q[combo.ARM_START:combo.ARM_END],
                          dtype=np.float64)

    def hands_up_pose(self) -> np.ndarray:
        """14-D arm target: both arms straight up overhead. NB: the velocity
        policy diverges holding this (CoM shifts forward) — use raise_arms_pose
        for a sustained hold; this stays for reference / brief gestures."""
        return combo.hands_up_pose(self.arm_rest)

    def raise_arms_pose(self) -> np.ndarray:
        """14-D arm target for a STABLE sustained 'raise both arms': arms out to
        the sides (T-pose). Overhead/forward raises shift the CoM forward and the
        balance policy drifts off; arms-to-the-sides keeps the CoM centred
        (verified: 0.04 m drift vs 9 m overhead)."""
        return combo.t_pose_pose(self.arm_rest)

    def push_arm_gesture(self, keyframes) -> None:
        """Queue an arm gesture through the combo controller's rate-limited
        blender (each keyframe = (duration_s, 14-D pose)). This is the ONLY
        safe way to move the arms: snapping a raw arm target spikes joint
        velocity and the balance policy falls — the combo's 2-2.5 s eased
        blend keeps it upright (verified)."""
        self.ctl.push_arm_action(list(keyframes))

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
        self.ctl.last_state_time = time.monotonic()  # keep watchdog from tripping
        self.ctl._tick()
        if self._captured is not None:
            return self._captured
        dq = self.cfg.default_q.copy()
        return dq, self.cfg.kp.copy(), self.cfg.kd.copy()
