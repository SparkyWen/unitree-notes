"""Headless unitree_mujoco — real physics + DDS bridge, NO viewer.

Same DDS contract as the GUI ``unitree_mujoco.py`` (publishes rt/lowstate,
subscribes rt/lowcmd, elastic band + default-hold PD keep the G1 upright) but
without a window, so it can run in automated/headless verification. For the
visible demo the operator runs the GUI ``unitree_mujoco.py`` instead — the
robot_node + coordinator are identical either way.

  python -m g1_brain.fleet.sim.headless_sim --domain 1
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import mujoco

_WS = Path(__file__).resolve().parents[4]
_SIMDIR = _WS / "unitree_mujoco" / "simulate_python"
_DEFAULT_SCENE = str(_WS / "unitree_mujoco" / "unitree_robots" / "g1" / "scene_29dof.xml")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", type=int, default=1)
    ap.add_argument("--interface", default="lo")
    ap.add_argument("--scene", default=_DEFAULT_SCENE)
    ap.add_argument("--band-length", type=float, default=1.5)
    args = ap.parse_args()

    sys.path.insert(0, str(_SIMDIR))
    from unitree_sdk2py.core.channel import ChannelFactoryInitialize
    import config  # noqa: F401  (bridge reads config.ROBOT / G1 defaults)
    from unitree_sdk2py_bridge import UnitreeSdk2Bridge, ElasticBand

    model = mujoco.MjModel.from_xml_path(args.scene)
    data = mujoco.MjData(model)
    model.opt.timestep = 0.005

    ChannelFactoryInitialize(args.domain, args.interface)
    bridge = UnitreeSdk2Bridge(model, data)  # seeds default-hold PD + qpos
    band = ElasticBand()
    band.length = args.band_length
    torso = model.body("torso_link").id
    print(f"[headless_sim] domain={args.domain} scene={Path(args.scene).name} "
          f"publishing rt/lowstate, applying rt/lowcmd", flush=True)

    try:
        while True:
            t0 = time.perf_counter()
            bridge.ApplyControl()
            if band.enable:
                data.xfrc_applied[torso, :3] = band.Advance(data.qpos[:3], data.qvel[:3])
            mujoco.mj_step(model, data)
            dt = model.opt.timestep - (time.perf_counter() - t0)
            if dt > 0:
                time.sleep(dt)
    except KeyboardInterrupt:
        print(f"[headless_sim] domain={args.domain} stopped", flush=True)


if __name__ == "__main__":
    main()
