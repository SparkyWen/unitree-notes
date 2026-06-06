import asyncio
import pytest

from g1_brain.fleet.agent.robot_agent import RobotAgent
from g1_brain.scene_state.types import SceneState, GroundConstraint
from g1_brain.fleet.contracts.models import (
    CapabilityDescriptor, RobotStateMsg, RobotEvent, EventType,
)


class _FakeBus:
    def __init__(self):
        self.registered = None
        self.heartbeats = []
        self.events = []
    async def connect(self, cap): self.registered = cap
    async def heartbeat(self, st): self.heartbeats.append(st)
    async def publish(self, ev): self.events.append(ev)
    async def close(self): pass


class _FakeCore:
    robot_id = "r1"
    def __init__(self):
        self._q = asyncio.Queue()
    def get_capabilities(self):
        return CapabilityDescriptor(robot_id="r1", frame_id="r1/map")
    def get_state(self, *, seq=0):
        return RobotStateMsg(robot_id="r1", ts="t", seq=seq, fsm_state="ENGAGED")
    async def subscribe_events(self):
        while True:
            yield await self._q.get()
    def snapshot_scene(self):
        s = SceneState()
        s.ground = GroundConstraint(clear_path=True, nearest_obstacle_m=3.0,
                                    nearest_person_m=float("inf"),
                                    floor_visible_ratio=0.9, surface_tilt_deg=1.0)
        return s
    def push(self, ev):
        self._q.put_nowait(ev)


@pytest.mark.asyncio
async def test_agent_registers_heartbeats_forwards_and_perceives():
    bus, core = _FakeBus(), _FakeCore()
    agent = RobotAgent(core=core, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=0.05)
    await agent.start()
    core.push(RobotEvent.make(robot_id="r1", type=EventType.SAFETY_EVENT, ts="t", payload={}))
    await asyncio.sleep(0.16)
    await agent.stop()

    assert bus.registered.robot_id == "r1"
    assert len(bus.heartbeats) >= 2
    assert bus.heartbeats[0].seq == 1  # seq increments from 1
    assert any(e.type == EventType.SAFETY_EVENT for e in bus.events)
    assert any(e.type == EventType.SCENE_SNAPSHOT for e in bus.events)


@pytest.mark.asyncio
async def test_perception_loop_disabled_when_interval_none():
    bus, core = _FakeBus(), _FakeCore()
    agent = RobotAgent(core=core, bus=bus, heartbeat_interval_s=0.05,
                       perception_interval_s=None)
    await agent.start()
    await asyncio.sleep(0.16)
    await agent.stop()
    assert not any(e.type == EventType.SCENE_SNAPSHOT for e in bus.events)
