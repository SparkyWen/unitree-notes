import time
import mujoco
import mujoco.viewer
import numpy as np
from threading import Thread
import threading

from unitree_sdk2py.core.channel import ChannelFactoryInitialize
from unitree_sdk2py_bridge import UnitreeSdk2Bridge, ElasticBand

import config


locker = threading.Lock()

mj_model = mujoco.MjModel.from_xml_path(config.ROBOT_SCENE)
mj_data = mujoco.MjData(mj_model)


def _set_g1_default_qpos():
    """Initialise mj_data.qpos to the trained G1 default pose.

    Without this the simulator opens with all-zero joints (legs fully
    straight, knees locked) and the robot is then either yanked to the
    elastic-band anchor or collapses under gravity before any controller
    is running. By writing the policy's `default_joint_pos` directly into
    mj_data.qpos at startup, the very first viewer frame already shows
    the robot in the in-distribution trained pose — and once the bridge
    seeds the default-pose holding PD (see `_maybe_seed_default_hold_cmd`
    in unitree_sdk2py_bridge.py), the robot stays in that pose until the
    external controller takes over.
    """
    if getattr(config, "ROBOT", None) != "g1":
        return
    q_def = getattr(config, "G1_DEFAULT_JOINT_POS", None)
    if q_def is None:
        return
    nq_motors = mj_model.nu
    if mj_data.qpos.shape[0] != 7 + nq_motors:
        return
    mj_data.qpos[7:7 + nq_motors] = np.asarray(q_def, dtype=np.float64)
    # Identity orientation; default torso height is whatever the MJCF set
    # (pelvis pos="0 0 0.793" for the g1_29dof model). The elastic band
    # will lift the robot toward the anchor when ELASTIC_BAND_INIT_LENGTH
    # < distance, or hold it on the ground when length is large.
    if np.linalg.norm(mj_data.qpos[3:7]) < 1e-6:
        mj_data.qpos[3:7] = (1.0, 0.0, 0.0, 0.0)
    mujoco.mj_forward(mj_model, mj_data)


_set_g1_default_qpos()


def _apply_low_quality_viewer(model):
    """Lower per-frame render cost so mouse rotation stays smooth on WSL2.

    Mouse-rotation responsiveness in the viewer is bounded by MuJoCo's C++
    render_loop frame time. On WSL2 the GL path is Mesa -> D3D12 translator,
    which charges per-call overhead -- so multi-pass effects (shadow map,
    reflection probe, MSAA) drive the per-frame budget past the 16.6 ms
    60 Hz vsync window and trigger 60 -> 30 fps drops that read as "laggy
    when rotating the view".

    We disable the heavy effects at the *source* (model fields), not via
    `MjvScene.flags`, because the passive viewer's C++ Simulate owns its
    MjvScene and doesn't expose it to Python. Disabling here is permanent
    for this run; turn `LOW_QUALITY_VIEWER` off in config.py to restore.

    Specifically:
      * `light_castshadow[i] = 0` -- skip the shadow-map pass entirely for
        every directional light. The biggest single win (~one full extra
        render pass per shadow-casting light per frame).
      * `mat_reflectance[i] = 0` -- zero out floor reflection. Otherwise
        the scene is rendered a second time mirrored through the floor.
      * `vis.quality.shadowsize 4096 -> 1024` -- shrink the shadow texture
        even though shadows are off, in case the operator toggles them
        back on from the viewer UI; keeps that toggle cheap.
      * `vis.quality.offsamples 4 -> 2` -- halve MSAA. Fragment-shader
        work scales ~linearly with sample count, 2x still softens edges.
    """
    if not getattr(config, "LOW_QUALITY_VIEWER", False):
        return
    for i in range(model.nlight):
        model.light_castshadow[i] = 0
    for i in range(model.nmat):
        model.mat_reflectance[i] = 0.0
    model.vis.quality.shadowsize = 1024
    model.vis.quality.offsamples = 2


_apply_low_quality_viewer(mj_model)

if config.ENABLE_ELASTIC_BAND:
    elastic_band = ElasticBand()
    # Pre-set band length so the robot sits near standing height instead of
    # being yanked up to z=3. See ELASTIC_BAND_INIT_LENGTH in config.py.
    if hasattr(config, "ELASTIC_BAND_INIT_LENGTH"):
        elastic_band.length = float(config.ELASTIC_BAND_INIT_LENGTH)
    if config.ROBOT == "h1" or config.ROBOT == "g1":
        band_attached_link = mj_model.body("torso_link").id
    else:
        band_attached_link = mj_model.body("base_link").id
    viewer = mujoco.viewer.launch_passive(
        mj_model, mj_data, key_callback=elastic_band.MujuocoKeyCallback
    )
else:
    viewer = mujoco.viewer.launch_passive(mj_model, mj_data)

mj_model.opt.timestep = config.SIMULATE_DT
num_motor_ = mj_model.nu
dim_motor_sensor_ = 3 * num_motor_

time.sleep(0.2)


def SimulationThread():
    global mj_data, mj_model

    ChannelFactoryInitialize(config.DOMAIN_ID, config.INTERFACE)
    unitree = UnitreeSdk2Bridge(mj_model, mj_data)

    if config.USE_JOYSTICK:
        unitree.SetupJoystick(device_id=0, js_type=config.JOYSTICK_TYPE)
    if config.PRINT_SCENE_INFORMATION:
        unitree.PrintSceneInformation()

    while viewer.is_running():
        step_start = time.perf_counter()

        locker.acquire()

        # Refresh PD torques every step from the latest cached lowcmd. This
        # has to run at sim rate (200 Hz here), not at cmd-arrival rate
        # (~50 Hz from the controller), or the closed loop oscillates.
        unitree.ApplyControl()

        if config.ENABLE_ELASTIC_BAND:
            if elastic_band.enable:
                mj_data.xfrc_applied[band_attached_link, :3] = elastic_band.Advance(
                    mj_data.qpos[:3], mj_data.qvel[:3]
                )
        mujoco.mj_step(mj_model, mj_data)

        locker.release()

        time_until_next_step = mj_model.opt.timestep - (
            time.perf_counter() - step_start
        )
        if time_until_next_step > 0:
            time.sleep(time_until_next_step)


def PhysicsViewerThread():
    while viewer.is_running():
        locker.acquire()
        viewer.sync()
        locker.release()
        time.sleep(config.VIEWER_DT)


if __name__ == "__main__":
    viewer_thread = Thread(target=PhysicsViewerThread)
    sim_thread = Thread(target=SimulationThread)

    viewer_thread.start()
    sim_thread.start()
