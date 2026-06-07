"""Typed plan/op contracts for the hierarchical dispatch layer (P2)."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class RobotAssignment(BaseModel):
    robot_id: str
    role: str = ""
    objective: str = ""
    goal: Optional[Tuple[float, float]] = None   # nav target if applicable


class Coordination(BaseModel):
    type: str = "none"   # rendezvous | relay | cover | patrol | none
    point: Optional[Tuple[float, float]] = None
    handoff_task: Optional[str] = None
    handoff_from: Optional[str] = None
    handoff_to: Optional[str] = None


class FleetPlan(BaseModel):
    summary: str = ""
    coordination: Coordination = Field(default_factory=Coordination)
    assignments: List[RobotAssignment] = Field(default_factory=list)
    needs_clarification: Optional[str] = None
    risk: str = "low"


class SubAgentOp(BaseModel):
    op: str                       # navigate | await_barrier | patrol | idle | sleep | wake
    args: Dict = Field(default_factory=dict)
