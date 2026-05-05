"""Safety layer for g1_brain.

Public entry points:

* :class:`RobotFsm` / :class:`RobotFsmState` — the high-level state machine.
* :class:`SafetySupervisor` — gates every skill call via ``await validate(tool, args)``.
* :class:`WatchdogManager` — background daemons that catch staleness and fall.
* :class:`EstopClient` — file-based E-stop flag accessor.
"""
from .estop_client import EstopClient
from .pose_check import gravity_proj_z_from_quat, is_upright
from .state_machine import IllegalTransitionError, RobotFsm, RobotFsmState
from .supervisor import (
    ALLOWED_MOTION_TOOLS,
    ALLOWED_TOOLS,
    ALLOWED_TOOLS_NO_MOTION,
    REAL_ROBOT_ONLY_TOOLS,
    SafetySupervisor,
)
from .watchdogs import WatchdogManager

__all__ = [
    "ALLOWED_MOTION_TOOLS",
    "ALLOWED_TOOLS",
    "ALLOWED_TOOLS_NO_MOTION",
    "REAL_ROBOT_ONLY_TOOLS",
    "EstopClient",
    "IllegalTransitionError",
    "RobotFsm",
    "RobotFsmState",
    "SafetySupervisor",
    "WatchdogManager",
    "gravity_proj_z_from_quat",
    "is_upright",
]
