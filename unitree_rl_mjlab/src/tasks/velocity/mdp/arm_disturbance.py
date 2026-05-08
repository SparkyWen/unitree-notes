"""Arm-disturbance MDP components for Unitree-G1-Flat-Arm-Disturbance.

Provides:
  GestureLibrary        — loads gestures.npz pre-sampled at cfg.fps Hz
  ArmReferenceCommand   — Poisson-triggered gesture playback per env
  ArmReferenceCommandCfg
  arm_qpos_ref_obs      — obs: current arm reference [N, 14]
  gesture_onehot_obs    — obs: one-hot gesture indicator [N, N_g]
  arm_qpos_ref_horizon_obs — obs: k-step look-ahead [N, k*14]
  arm_track_l2          — reward: L2 penalty vs gesture reference
  ArmDisturbanceAction  — JointPositionAction with arm override
  ArmDisturbanceActionCfg
  gesture_intensity     — curriculum: ramp trigger rate / amplitude
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import torch

from mjlab.entity import Entity
from mjlab.envs.mdp.actions.actions import JointPositionAction, JointPositionActionCfg
from mjlab.managers import CommandTerm, CommandTermCfg
from mjlab.managers.scene_entity_config import SceneEntityCfg

if TYPE_CHECKING:
    from mjlab.envs import ManagerBasedRlEnv

# Arm joint indices in the G1 29-DOF joint vector (matches g1_sim_rl_combo.py).
_ARM_START = 15
_ARM_END = 29
_ARM_DIM = _ARM_END - _ARM_START  # 14

# Regex patterns that identify arm joints in the MJCF joint-name list.
_ARM_JOINT_PATTERNS = (
    r".*_shoulder_pitch_joint",
    r".*_shoulder_roll_joint",
    r".*_shoulder_yaw_joint",
    r".*_elbow_joint",
    r".*_wrist_roll_joint",
    r".*_wrist_pitch_joint",
    r".*_wrist_yaw_joint",
)

_DEFAULT_ASSET_CFG = SceneEntityCfg("robot")


# ── Gesture library ───────────────────────────────────────────────────────────

class GestureLibrary:
    """Pre-sampled gesture trajectory library loaded from gestures.npz.

    gestures.npz layout (created by make_gestures_npz.py):
      arm_qpos  – float32  [N_g, T_max, 14]  absolute joint positions (rad)
      lengths   – int32    [N_g]              valid frames per gesture
      names     – object   [N_g]              gesture name strings
    """

    def __init__(self, path: str, device: str = "cpu") -> None:
        data = np.load(path, allow_pickle=True)
        self.arm_qpos = torch.tensor(
            data["arm_qpos"], dtype=torch.float32, device=device
        )  # [N_g, T_max, 14]
        self.lengths = torch.tensor(
            data["lengths"], dtype=torch.long, device=device
        )  # [N_g]
        self.names: list[str] = list(data["names"])
        self.n_gestures: int = self.arm_qpos.shape[0]
        self.arm_dim: int = self.arm_qpos.shape[2]  # 14

    def get_frame(
        self, gesture_ids: torch.Tensor, frames: torch.Tensor
    ) -> torch.Tensor:
        """arm_qpos[gesture_ids, frames, :] with frame clamped to valid range."""
        clamped = torch.clamp(frames, 0, self.arm_qpos.shape[1] - 1)
        return self.arm_qpos[gesture_ids, clamped]  # [N, 14]


# ── Command term ──────────────────────────────────────────────────────────────

class ArmReferenceCommand(CommandTerm):
    """Randomised arm gesture command for arm-disturbance training.

    Behaviour per env:
    - Idle: counts down a random delay, then samples a random gesture.
    - Active: advances the gesture phase each step; exposes arm_qpos_ref,
      gesture_onehot, and arm_qpos_ref_horizon to observations and the
      action override.
    - On episode reset (_resample_command): state is cleared and a new
      random delay is sampled.
    """

    cfg: ArmReferenceCommandCfg

    def __init__(self, cfg: ArmReferenceCommandCfg, env: ManagerBasedRlEnv) -> None:
        super().__init__(cfg, env)

        self._lib = GestureLibrary(cfg.gesture_file, device=self.device)
        N = self.num_envs

        self._gesture_id = torch.zeros(N, dtype=torch.long, device=self.device)
        self._phase_frame = torch.zeros(N, dtype=torch.float32, device=self.device)
        self._active = torch.zeros(N, dtype=torch.bool, device=self.device)
        self._steps_until_trigger = self._sample_delays(
            torch.arange(N, device=self.device)
        )

        self._arm_qpos_ref = torch.zeros(N, self._lib.arm_dim, device=self.device)
        self._gesture_onehot = torch.zeros(
            N, self._lib.n_gestures, device=self.device
        )

        self.metrics["gesture_active_frac"] = torch.zeros(1, device=self.device)

    # ── Public interface ────────────────────────────────────────────────────

    @property
    def command(self) -> torch.Tensor:
        """Current arm reference positions [N, 14]."""
        return self._arm_qpos_ref

    @property
    def active(self) -> torch.Tensor:
        """Boolean mask: gesture active for each env [N]."""
        return self._active

    @property
    def arm_qpos_ref(self) -> torch.Tensor:
        """Current arm reference joint positions [N, 14]; zeros when idle."""
        return self._arm_qpos_ref

    @property
    def gesture_onehot(self) -> torch.Tensor:
        """One-hot gesture indicator [N, N_g]; zeros when idle."""
        return self._gesture_onehot

    def arm_qpos_ref_horizon(self, k: int = 5) -> torch.Tensor:
        """Next k arm reference frames concatenated [N, k*14]; zeros when idle."""
        arm_dim = self._lib.arm_dim
        horizon = torch.zeros(
            self.num_envs, k * arm_dim, device=self.device
        )
        active_ids = self._active.nonzero(as_tuple=False).view(-1)
        if active_ids.numel() == 0:
            return horizon
        for i in range(k):
            fi = (self._phase_frame[active_ids] + i).long()
            horizon[active_ids, i * arm_dim : (i + 1) * arm_dim] = (
                self._lib.get_frame(self._gesture_id[active_ids], fi)
            )
        return horizon

    # ── CommandTerm callbacks ───────────────────────────────────────────────

    def _update_metrics(self) -> None:
        pass  # metrics are updated inline in _update_command

    def _resample_command(self, env_ids: torch.Tensor) -> None:
        """Clear gesture state for reset envs and schedule a new delay."""
        self._gesture_id[env_ids] = 0
        self._phase_frame[env_ids] = 0.0
        self._active[env_ids] = False
        self._steps_until_trigger[env_ids] = self._sample_delays(env_ids)
        self._arm_qpos_ref[env_ids] = 0.0
        self._gesture_onehot[env_ids] = 0.0

    def _update_command(self) -> None:
        """Advance gesture phases; trigger / retire gestures."""
        frames_per_step = self._env.step_dt * self.cfg.fps

        # Advance active gestures.
        self._phase_frame[self._active] += frames_per_step

        # Retire completed gestures.
        done = self._active & (
            self._phase_frame >= self._lib.lengths[self._gesture_id].float()
        )
        if done.any():
            done_ids = done.nonzero(as_tuple=False).view(-1)
            self._active[done_ids] = False
            self._gesture_id[done_ids] = 0
            self._phase_frame[done_ids] = 0.0
            self._gesture_onehot[done_ids] = 0.0
            self._steps_until_trigger[done_ids] = self._sample_delays(done_ids)

        # Decrement idle counters (includes newly-idle envs — off-by-one is fine).
        idle = ~self._active
        self._steps_until_trigger[idle] -= 1

        # Trigger new gestures.
        trigger = idle & (self._steps_until_trigger <= 0)
        if trigger.any():
            trig_ids = trigger.nonzero(as_tuple=False).view(-1)
            n = trig_ids.numel()
            new_g = torch.randint(0, self._lib.n_gestures, (n,), device=self.device)
            self._gesture_id[trig_ids] = new_g
            self._phase_frame[trig_ids] = 0.0
            self._active[trig_ids] = True
            self._gesture_onehot[trig_ids] = 0.0
            self._gesture_onehot[trig_ids, new_g] = 1.0
            # Reset trigger counters so they aren't immediately re-triggered.
            self._steps_until_trigger[trig_ids] = self._sample_delays(trig_ids)

        # Refresh arm reference for active envs.
        if self._active.any():
            act = self._active
            fi = self._phase_frame[act].long()
            self._arm_qpos_ref[act] = self._lib.get_frame(self._gesture_id[act], fi)
        self._arm_qpos_ref[~self._active] = 0.0

        self.metrics["gesture_active_frac"][:] = self._active.float().mean()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _sample_delays(self, env_ids: torch.Tensor) -> torch.Tensor:
        lo_s, hi_s = self.cfg.trigger_interval_range_s
        step_dt = self._env.step_dt
        lo = max(1, int(lo_s / step_dt))
        hi = max(lo + 1, int(hi_s / step_dt) + 1)
        return torch.randint(lo, hi, (env_ids.numel(),), device=self.device)


@dataclass(kw_only=True)
class ArmReferenceCommandCfg(CommandTermCfg):
    """Configuration for ArmReferenceCommand."""

    gesture_file: str = ""
    """Path to gestures.npz (created by make_gestures_npz.py)."""

    fps: float = 50.0
    """Gesture keyframe rate (Hz). Must match the rate used when building gestures.npz."""

    trigger_interval_range_s: tuple[float, float] = (4.0, 8.0)
    """Range of random idle intervals (seconds) between gestures."""

    entity_name: str = "robot"
    """Robot entity name in the scene."""

    def build(self, env: ManagerBasedRlEnv) -> ArmReferenceCommand:
        return ArmReferenceCommand(self, env)


# ── Observation functions ─────────────────────────────────────────────────────

def arm_qpos_ref_obs(
    env: ManagerBasedRlEnv, command_name: str = "arm_ref"
) -> torch.Tensor:
    """Current arm reference positions [N, 14]; zeros when idle."""
    cmd: ArmReferenceCommand = env.command_manager.get_term(command_name)  # type: ignore[assignment]
    return cmd.arm_qpos_ref


def gesture_onehot_obs(
    env: ManagerBasedRlEnv, command_name: str = "arm_ref"
) -> torch.Tensor:
    """One-hot gesture indicator [N, N_g]; zeros when idle."""
    cmd: ArmReferenceCommand = env.command_manager.get_term(command_name)  # type: ignore[assignment]
    return cmd.gesture_onehot


def arm_qpos_ref_horizon_obs(
    env: ManagerBasedRlEnv, command_name: str = "arm_ref", k: int = 5
) -> torch.Tensor:
    """Horizon arm reference [N, k*14]; zeros for idle envs."""
    cmd: ArmReferenceCommand = env.command_manager.get_term(command_name)  # type: ignore[assignment]
    return cmd.arm_qpos_ref_horizon(k=k)


# ── Reward function ───────────────────────────────────────────────────────────

def arm_track_l2(
    env: ManagerBasedRlEnv,
    command_name: str = "arm_ref",
    asset_cfg: SceneEntityCfg = _DEFAULT_ASSET_CFG,
) -> torch.Tensor:
    """Penalise arm deviation from gesture reference; zero for idle envs.

    Returns −||q_arm − arm_ref||² per env (non-positive).
    """
    cmd: ArmReferenceCommand = env.command_manager.get_term(command_name)  # type: ignore[assignment]
    penalty = torch.zeros(env.num_envs, device=env.device)
    if not cmd.active.any():
        return penalty
    asset: Entity = env.scene[asset_cfg.name]
    q_arm = asset.data.joint_pos[:, _ARM_START:_ARM_END]  # [N, 14]
    ref = cmd.arm_qpos_ref  # [N, 14]
    penalty = -((q_arm - ref) ** 2).sum(dim=-1)  # [N]
    penalty[~cmd.active] = 0.0
    return penalty


# ── Action term ───────────────────────────────────────────────────────────────

class ArmDisturbanceAction(JointPositionAction):
    """JointPositionAction with gesture-driven arm override.

    When a gesture is active (ArmReferenceCommand.active[env] is True),
    the arm slice of _processed_actions is replaced with the current
    gesture reference positions before apply_actions() sends targets
    to the physics. This mirrors the post-policy arm override used in
    g1_sim_rl_combo.ComboController at deployment.
    """

    cfg: ArmDisturbanceActionCfg

    def __init__(self, cfg: ArmDisturbanceActionCfg, env: ManagerBasedRlEnv) -> None:
        super().__init__(cfg, env)

        # Resolve arm indices in the action's target space by name matching.
        arm_idxs = [
            i
            for i, name in enumerate(self._target_names)
            if any(re.fullmatch(p, name) for p in _ARM_JOINT_PATTERNS)
        ]
        if len(arm_idxs) != _ARM_DIM:
            raise RuntimeError(
                f"ArmDisturbanceAction expected {_ARM_DIM} arm joints, "
                f"found {len(arm_idxs)}: "
                f"{[self._target_names[i] for i in arm_idxs]}"
            )
        self._arm_act_idxs = torch.tensor(
            arm_idxs, dtype=torch.long, device=self.device
        )

    def apply_actions(self) -> None:
        # Override arm slice for envs with an active gesture.
        try:
            cmd = self._env.command_manager.get_term(self.cfg.command_name)
        except Exception:
            cmd = None

        if cmd is not None and isinstance(cmd, ArmReferenceCommand) and cmd.active.any():
            arm_ref = cmd.arm_qpos_ref  # [N, 14] absolute joint pos
            # torch.where over the arm columns, preserving the original values
            # for inactive envs.
            active_2d = cmd.active.unsqueeze(1).expand(-1, _ARM_DIM)  # [N, 14]
            current_arm = self._processed_actions[:, self._arm_act_idxs]  # [N, 14]
            self._processed_actions[:, self._arm_act_idxs] = torch.where(
                active_2d, arm_ref, current_arm
            )

        super().apply_actions()


@dataclass(kw_only=True)
class ArmDisturbanceActionCfg(JointPositionActionCfg):
    """JointPositionActionCfg that builds an ArmDisturbanceAction."""

    command_name: str = "arm_ref"
    """Name of the ArmReferenceCommand in the command manager."""

    def build(self, env: ManagerBasedRlEnv) -> ArmDisturbanceAction:
        return ArmDisturbanceAction(self, env)


# ── Curriculum ────────────────────────────────────────────────────────────────

class _IntensityStage:
    step: int
    trigger_interval_range_s: tuple[float, float] | None
    """New (lo, hi) trigger interval in seconds, or None to leave unchanged."""


def gesture_intensity(
    env: ManagerBasedRlEnv,
    env_ids: torch.Tensor,
    command_name: str = "arm_ref",
    stages: list[dict] | None = None,
) -> dict:
    """Curriculum: ramp arm-disturbance intensity over training steps.

    Each stage dict has:
      step                    – first step at which the stage takes effect
      trigger_interval_range_s – (lo_s, hi_s) tuple, optional
    """
    del env_ids  # unused — curriculum is global
    if not stages:
        return {}
    cmd: ArmReferenceCommand = env.command_manager.get_term(command_name)  # type: ignore[assignment]
    for stage in stages:
        if env.common_step_counter > stage["step"]:
            if "trigger_interval_range_s" in stage:
                cmd.cfg.trigger_interval_range_s = tuple(
                    stage["trigger_interval_range_s"]
                )
    return {}
