"""Pluggable motion backends for the SimRobotHarness.

The harness, admission gate, thermal model and planner are backend-agnostic;
only the backend differs between CI (mock), the reliable elastic-PD path, and
the RL self-balance path.
"""
from g1_brain.fleet.agent.motion.base import MotionBackend, Posture

__all__ = ["MotionBackend", "Posture"]
