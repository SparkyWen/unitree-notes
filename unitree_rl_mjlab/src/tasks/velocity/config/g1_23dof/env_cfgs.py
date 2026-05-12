"""Unitree G1-23DOF velocity environment configurations."""

from pathlib import Path

from src.assets.robots import (
  G1_23DOF_ACTION_SCALE,
  get_g1_23dof_robot_cfg,
)
from mjlab.envs import ManagerBasedRlEnvCfg
from mjlab.envs import mdp as envs_mdp
from mjlab.envs.mdp.actions import JointPositionActionCfg
from mjlab.managers.curriculum_manager import CurriculumTermCfg
from mjlab.managers.event_manager import EventTermCfg
from mjlab.managers.observation_manager import ObservationTermCfg
from mjlab.managers.reward_manager import RewardTermCfg
from mjlab.sensor import ContactMatch, ContactSensorCfg, RayCastSensorCfg
from mjlab.tasks.velocity import mdp
from mjlab.tasks.velocity.mdp import UniformVelocityCommandCfg
from src.tasks.velocity.mdp.arm_disturbance import (
  ArmDisturbanceActionCfg,
  ArmReferenceCommandCfg,
  arm_idle_l2,
  arm_qpos_ref_horizon_obs,
  arm_track_l2,
  gesture_intensity,
  gesture_onehot_obs,
)
from src.tasks.velocity.velocity_env_cfg import make_velocity_env_cfg

_SRC_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent  # .../src
_GESTURES_NPZ_23DOF = str(
  _SRC_ROOT / "assets" / "motions" / "g1" / "gestures_23dof.npz"
)


def unitree_g1_23dof_rough_env_cfg(play: bool = False) -> ManagerBasedRlEnvCfg:
  """Create Unitree G1-23DOF rough terrain velocity configuration."""
  cfg = make_velocity_env_cfg()

  cfg.sim.mujoco.ccd_iterations = 500
  cfg.sim.contact_sensor_maxmatch = 500
  cfg.sim.nconmax = 48

  cfg.scene.entities = {"robot": get_g1_23dof_robot_cfg()}

  # Set raycast sensor frame to G1-23DOF pelvis.
  for sensor in cfg.scene.sensors or ():
    if sensor.name == "terrain_scan":
      assert isinstance(sensor, RayCastSensorCfg)
      sensor.frame.name = "pelvis"

  site_names = ("left_foot", "right_foot")
  geom_names = tuple(
    f"{side}_foot{i}_collision" for side in ("left", "right") for i in range(1, 8)
  )

  feet_ground_cfg = ContactSensorCfg(
    name="feet_ground_contact",
    primary=ContactMatch(
      mode="subtree",
      pattern=r"^(left_ankle_roll_link|right_ankle_roll_link)$",
      entity="robot",
    ),
    secondary=ContactMatch(mode="body", pattern="terrain"),
    fields=("found", "force"),
    reduce="netforce",
    num_slots=1,
    track_air_time=True,
  )
  self_collision_cfg = ContactSensorCfg(
    name="self_collision",
    primary=ContactMatch(mode="subtree", pattern="pelvis", entity="robot"),
    secondary=ContactMatch(mode="subtree", pattern="pelvis", entity="robot"),
    fields=("found", "force"),
    reduce="none",
    num_slots=1,
    history_length=4,
  )
  cfg.scene.sensors = (cfg.scene.sensors or ()) + (
    feet_ground_cfg,
    self_collision_cfg,
  )

  if cfg.scene.terrain is not None and cfg.scene.terrain.terrain_generator is not None:
    cfg.scene.terrain.terrain_generator.curriculum = True

  joint_pos_action = cfg.actions["joint_pos"]
  assert isinstance(joint_pos_action, JointPositionActionCfg)
  joint_pos_action.scale = G1_23DOF_ACTION_SCALE

  cfg.viewer.body_name = "torso_link"

  twist_cmd = cfg.commands["twist"]
  assert isinstance(twist_cmd, UniformVelocityCommandCfg)
  twist_cmd.viz.z_offset = 1.15

  cfg.observations["critic"].terms["foot_height"].params[
    "asset_cfg"
  ].site_names = site_names

  cfg.events["foot_friction"].params["asset_cfg"].geom_names = geom_names
  cfg.events["base_com"].params["asset_cfg"].body_names = ("torso_link",)

  # Rationale for std values:
  # - Knees/hip_pitch get the loosest std to allow natural leg bending during stride.
  # - Hip roll/yaw stay tighter to prevent excessive lateral sway and keep gait stable.
  # - Ankle roll is very tight for balance; ankle pitch looser for foot clearance.
  # - Waist roll/pitch stay tight to keep the torso upright and stable.
  # - Shoulders/elbows get moderate freedom for natural arm swing during walking.
  # - Wrists are loose (0.3) since they don't affect balance much.
  # Running values are ~1.5-2x walking values to accommodate larger motion range.
  cfg.rewards["pose"].params["std_standing"] = {".*": 0.05}
  cfg.rewards["pose"].params["std_walking"] = {
    # Lower body.
    r".*hip_pitch.*": 0.5,
    r".*hip_roll.*": 0.15,
    r".*hip_yaw.*": 0.15,
    r".*knee.*": 0.5,
    r".*ankle_pitch.*": 0.15,
    r".*ankle_roll.*": 0.1,
    # Waist.
    r".*waist_yaw.*": 0.15,
    # Arms.
    r".*shoulder_pitch.*": 0.15,
    r".*shoulder_roll.*": 0.1,
    r".*shoulder_yaw.*": 0.1,
    r".*elbow.*": 0.1,
    r".*wrist.*": 0.1,
  }
  cfg.rewards["pose"].params["std_running"] = {
    # Lower body.
    r".*hip_pitch.*": 0.5,
    r".*hip_roll.*": 0.25,
    r".*hip_yaw.*": 0.25,
    r".*knee.*": 0.5,
    r".*ankle_pitch.*": 0.25,
    r".*ankle_roll.*": 0.1,
    # Waist.
    r".*waist_yaw.*": 0.25,
    # Arms.
    r".*shoulder_pitch.*": 0.25,
    r".*shoulder_roll.*": 0.1,
    r".*shoulder_yaw.*": 0.1,
    r".*elbow.*": 0.1,
    r".*wrist.*": 0.1,
  }

  cfg.rewards["body_orientation_l2"].params["asset_cfg"].body_names = ("torso_link",)
  cfg.rewards["body_ang_vel"].params["asset_cfg"].body_names = ("torso_link",)
  cfg.rewards["foot_clearance"].params["asset_cfg"].site_names = site_names
  cfg.rewards["foot_slip"].params["asset_cfg"].site_names = site_names
  cfg.rewards["self_collisions"] = RewardTermCfg(
    func=mdp.self_collision_cost,
    weight=-1.0,
    params={"sensor_name": self_collision_cfg.name, "force_threshold": 10.0},
  )

  # Apply play mode overrides.
  if play:
    # Effectively infinite episode length.
    cfg.episode_length_s = int(1e9)

    cfg.observations["actor"].enable_corruption = False
    cfg.events.pop("push_robot", None)
    cfg.curriculum = {}
    cfg.events["randomize_terrain"] = EventTermCfg(
      func=envs_mdp.randomize_terrain,
      mode="reset",
      params={},
    )

    if cfg.scene.terrain is not None:
      if cfg.scene.terrain.terrain_generator is not None:
        cfg.scene.terrain.terrain_generator.curriculum = False
        cfg.scene.terrain.terrain_generator.num_cols = 5
        cfg.scene.terrain.terrain_generator.num_rows = 5
        cfg.scene.terrain.terrain_generator.border_width = 10.0

  return cfg


def unitree_g1_23dof_flat_env_cfg(play: bool = False) -> ManagerBasedRlEnvCfg:
  """Create Unitree G1-23DOF flat terrain velocity configuration."""
  cfg = unitree_g1_23dof_rough_env_cfg(play=play)

  cfg.sim.njmax = 300
  cfg.sim.mujoco.ccd_iterations = 50
  cfg.sim.contact_sensor_maxmatch = 64
  cfg.sim.nconmax = None

  # Switch to flat terrain.
  assert cfg.scene.terrain is not None
  cfg.scene.terrain.terrain_type = "plane"
  cfg.scene.terrain.terrain_generator = None

  # Remove raycast sensor and height scan (no terrain to scan).
  cfg.scene.sensors = tuple(
    s for s in (cfg.scene.sensors or ()) if s.name != "terrain_scan"
  )
  del cfg.observations["actor"].terms["height_scan"]
  del cfg.observations["critic"].terms["height_scan"]

  # Disable terrain curriculum (not present in play mode since rough clears all).
  cfg.curriculum.pop("terrain_levels", None)

  if play:
    twist_cmd = cfg.commands["twist"]
    assert isinstance(twist_cmd, UniformVelocityCommandCfg)
    twist_cmd.ranges.lin_vel_x = (-0.5, 1.0)
    twist_cmd.ranges.lin_vel_y = (-0.5, 0.5)
    twist_cmd.ranges.ang_vel_z = (-0.5, 0.5)

  return cfg


def unitree_g1_23dof_flat_arm_disturbance_env_cfg(
  play: bool = False,
) -> ManagerBasedRlEnvCfg:
  """G1-23DOF flat env with randomised arm-gesture disturbance.

  Extends ``unitree_g1_23dof_flat_env_cfg`` with:
    - ``ArmReferenceCommand``: Poisson-triggered gesture playback at 8–16 s
      intervals, ramping to 4–8 s after 120 k steps.
    - ``ArmDisturbanceAction``: arm joint targets overridden with gesture
      reference when a gesture is active (5 joints per arm = 10-D).
    - New actor + critic observations: ``gesture_onehot`` (9-D) and
      ``arm_qpos_ref_horizon`` (5×10 = 50-D).
    - Arm joint ``pose`` reward disabled (std → 1e6).
    - Weak ``arm_track_l2`` reward (weight 0.05).
  """
  cfg = unitree_g1_23dof_flat_env_cfg(play=play)

  # ── Arm-reference command ──────────────────────────────────────────────
  cfg.commands["arm_ref"] = ArmReferenceCommandCfg(
    gesture_file=_GESTURES_NPZ_23DOF,
    fps=50.0,
    trigger_interval_range_s=(8.0, 16.0),
    entity_name="robot",
    resampling_time_range=(1e9, 1e9),
  )

  # ── Replace standard action with arm-override variant ─────────────────
  cfg.actions["joint_pos"] = ArmDisturbanceActionCfg(
    entity_name="robot",
    actuator_names=(".*",),
    scale=G1_23DOF_ACTION_SCALE,
    use_default_offset=True,
    command_name="arm_ref",
    # default arm_joint_patterns = 23-DOF (5 per arm: shoulder×3, elbow, wrist_roll)
  )

  # ── Additional observations ───────────────────────────────────────────
  new_obs = {
    "gesture_onehot": ObservationTermCfg(
      func=gesture_onehot_obs,
      params={"command_name": "arm_ref"},
    ),
    # arm_qpos_ref_horizon: 5 future frames × 10 joints = 50-D.
    "arm_qpos_ref_horizon": ObservationTermCfg(
      func=arm_qpos_ref_horizon_obs,
      params={"command_name": "arm_ref", "k": 5},
    ),
  }
  cfg.observations["actor"].terms.update(new_obs)
  cfg.observations["critic"].terms.update(new_obs)

  # ── Disable pose reward on arm joints ─────────────────────────────────
  # std_standing uses a catch-all ".*" so we must replace the whole dict;
  # adding arm patterns alongside ".*" would cause a multiple-match error.
  # std_walking/running already have per-joint patterns — .update() is fine.
  _arm_loose_std = 1e6
  cfg.rewards["pose"].params["std_standing"] = {
    r".*_hip_pitch.*":   0.05,
    r".*_hip_roll.*":    0.05,
    r".*_hip_yaw.*":     0.05,
    r".*_knee.*":        0.05,
    r".*_ankle_pitch.*": 0.05,
    r".*_ankle_roll.*":  0.05,
    r".*waist_yaw.*":    0.05,
    r".*shoulder_pitch.*": _arm_loose_std,
    r".*shoulder_roll.*":  _arm_loose_std,
    r".*shoulder_yaw.*":   _arm_loose_std,
    r".*elbow.*":          _arm_loose_std,
    r".*wrist.*":          _arm_loose_std,
  }
  for std_key in ("std_walking", "std_running"):
    cfg.rewards["pose"].params[std_key].update({
      r".*shoulder_pitch.*": _arm_loose_std,
      r".*shoulder_roll.*":  _arm_loose_std,
      r".*shoulder_yaw.*":   _arm_loose_std,
      r".*elbow.*":          _arm_loose_std,
      r".*wrist.*":          _arm_loose_std,
    })

  # ── Arm tracking reward (active during gesture) ───────────────────────
  cfg.rewards["arm_track_l2"] = RewardTermCfg(
    func=arm_track_l2,
    weight=0.05,
    params={"command_name": "arm_ref", "arm_start": 13, "arm_end": 23},
  )

  # ── Arm rest reward (active during idle) ─────────────────────────────
  # Penalise arm deviation from default pose when no gesture is playing.
  # Zero during gestures so the arm override is not fought. Weight 0.2
  # is strong enough to suppress spurious arm waving without disrupting
  # the leg/balance gradient signal.
  cfg.rewards["arm_idle_l2"] = RewardTermCfg(
    func=arm_idle_l2,
    weight=0.2,
    params={"command_name": "arm_ref", "arm_start": 13, "arm_end": 23},
  )

  # ── Curriculum: ramp disturbance frequency ────────────────────────────
  cfg.curriculum["gesture_intensity"] = CurriculumTermCfg(
    func=gesture_intensity,
    params={
      "command_name": "arm_ref",
      "stages": [
        {"step": 0,            "trigger_interval_range_s": (8.0, 16.0)},
        {"step": 120_000 * 24, "trigger_interval_range_s": (4.0, 8.0)},
      ],
    },
  )

  return cfg
