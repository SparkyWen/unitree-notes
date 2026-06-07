"""WorldSim render-lock: a passive MuJoCo viewer copies mjData (mj_copyData /
mj_copyDataVisual) on another thread to render. If the 50 Hz control thread is
mid-`mj_step` on the SAME mjData, the copy aborts with 'attempting to copy
mjData while stack is in use'. WorldSim.set_render_lock(lock) makes the control
loop step under that mutex so the viewer (holding the same lock for its copy)
never races the step. Headless reproduction below (no GUI needed)."""
import threading
import time

import mujoco
import pytest

from g1_brain.fleet.sim.shared_world_node import WorldSim


@pytest.mark.slow
def test_render_lock_serializes_data_copy_with_stepping():
    sim = WorldSim()
    lock = threading.Lock()
    sim.set_render_lock(lock)          # what a viewer loop would pass: viewer.lock()
    sim.start()
    dst = mujoco.MjData(sim.world.m)
    errors = []
    end = time.time() + 1.5
    try:
        # stand in for the viewer's render thread: copy mjData under the shared
        # lock, fast, while the control loop is stepping under the same lock.
        while time.time() < end:
            try:
                with lock:
                    mujoco.mj_copyData(dst, sim.world.m, sim.world.d)
            except Exception as e:  # noqa: BLE001
                errors.append(repr(e))
    finally:
        sim.stop()
    assert not errors, f"data copy raced mj_step: {errors[:3]}"
