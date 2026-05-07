"""Generate scene_29dof_terrain.xml for the G1 four-direction terrain test.

Run this from inside the terrain_tool/ directory (the upstream
terrain_generator.py uses paths relative to its own location):

    cd unitree_mujoco/terrain_tool
    python g1_terrain_config.py

This monkey-patches the module-level constants in terrain_generator so
the existing TerrainGenerator class loads the clean scene_29dof.xml as
its base and writes scene_29dof_terrain.xml plus terrain_perlin.png
into unitree_robots/g1/. Re-run after editing parameters below.

See docs/superpowers/specs/2026-05-07-mujoco-terrain-scene-design.md
for the design and rationale behind every parameter.
"""

import math
import terrain_generator as tg_mod


def main() -> None:
    tg_mod.ROBOT = "g1"
    tg_mod.INPUT_SCENE_PATH = "../unitree_robots/g1/scene_29dof.xml"
    tg_mod.OUTPUT_SCENE_PATH = "../unitree_robots/g1/scene_29dof_terrain.xml"

    tg = tg_mod.TerrainGenerator()

    # ---- East (+X): two ramps and a Perlin field --------------------------
    ramp_half_len = 0.75
    ramp_half_thk = 0.025

    angle_10 = math.radians(10.0)
    z_10 = math.sin(angle_10) * ramp_half_len + math.cos(angle_10) * ramp_half_thk
    tg.AddBox(
        position=[3.0, 0.0, z_10],
        euler=[0.0, angle_10, 0.0],
        size=[1.5, 1.0, 0.05],
    )

    angle_15 = math.radians(15.0)
    z_15 = math.sin(angle_15) * ramp_half_len + math.cos(angle_15) * ramp_half_thk
    tg.AddBox(
        position=[5.0, 0.0, z_15],
        euler=[0.0, angle_15, 0.0],
        size=[1.5, 1.0, 0.05],
    )

    # Perlin hfield: dropped resolution 128->32 (and smooth 80->20 to keep
    # the same feature size: smooth/image_width ratio 80/128 == 20/32).
    # 128x128 = 32k visual triangles per frame, which under WSL2's
    # virtualized GPU was the dominant cause of "the viewer feels laggy".
    # 32x32 = ~2k triangles, no perceivable physics change at our scale.
    tg.AddPerlinHeighField(
        position=[7.5, 0.0, 0.0],
        euler=[0.0, 0.0, 0.0],
        size=[1.0, 1.0],
        height_scale=0.08,
        negative_height=0.05,
        image_width=32,
        img_height=32,
        smooth=20.0,
        output_hfield_image="terrain_perlin.png",
    )

    # AddPerlinHeighField writes file="../terrain_perlin.png". This looks
    # wrong at first glance, but g1_29dof.xml declares meshdir="meshes",
    # which MuJoCo applies to hfield file lookups too. So MuJoCo resolves
    # it as <xml_dir>/meshes/../terrain_perlin.png == <xml_dir>/terrain_perlin.png,
    # which is where the PNG actually lives. Leave the path alone.

    # ---- North (+Y): stairs ----------------------------------------------
    tg.AddStairs(
        init_pos=[0.0, 4.0, 0.0],
        yaw=0.0,
        width=0.25,
        height=0.10,
        length=1.0,
        stair_nums=8,
    )

    # ---- South (-Y): scattered obstacles ---------------------------------
    tg.AddBox(
        position=[0.5, -3.5, 0.10],
        euler=[0.0, 0.0, 0.0],
        size=[0.40, 0.40, 0.20],
    )
    tg.AddBox(
        position=[1.2, -4.0, 0.20],
        euler=[0.0, 0.0, 0.5],
        size=[0.30, 0.30, 0.40],
    )
    tg.AddGeometry(
        position=[0.0, -4.5, 0.15],
        euler=[0.0, 0.0, 0.0],
        size=[0.24, 0.30],
        geo_type="cylinder",
    )
    tg.AddGeometry(
        position=[1.5, -5.0, 0.30],
        euler=[0.0, 0.0, 0.0],
        size=[0.20, 0.60],
        geo_type="cylinder",
    )

    # ---- West (-X): rough ground -----------------------------------------
    # Dropped count from 8x8=64 to 4x4=16. 64 separate box geoms means 64
    # extra draw calls per viewer frame, which compounds the hfield's render
    # cost. 4x4 still gives a clearly-visible "pebbly path" the operator can
    # walk the robot into.
    tg.AddRoughGround(
        init_pos=[-4.0, -1.0, 0.02],
        euler=[0.0, 0.0, 0.0],
        nums=[4, 4],
        box_size=[0.08, 0.08, 0.08],
        box_euler=[0.0, 0.0, 0.0],
        separation=[0.20, 0.20],
        box_size_rand=[0.02, 0.02, 0.02],
        box_euler_rand=[0.10, 0.10, 0.0],
        separation_rand=[0.0, 0.0],
    )

    # Tag every appended terrain geom with group="2" and explicit
    # contype/conaffinity so:
    #   1. The viewer key '2' toggles all terrain visibility on/off (the
    #      escape hatch when the operator wants the original flat-ground
    #      render speed back without re-editing config.py).
    #   2. The defaults are explicit instead of implicit (defensive: if
    #      g1_29dof.xml ever changes its <default> class, terrain geoms
    #      keep working).
    # The floor plane itself is kept untouched so it stays visible always.
    for geom in tg.worldbody.findall("geom"):
        if geom.attrib.get("name") == "floor":
            continue
        geom.attrib.setdefault("group", "2")
        geom.attrib.setdefault("contype", "1")
        geom.attrib.setdefault("conaffinity", "1")

    tg.Save()
    print(f"Wrote {tg_mod.OUTPUT_SCENE_PATH}")


if __name__ == "__main__":
    main()
