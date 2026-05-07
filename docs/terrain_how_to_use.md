# G1 MuJoCo 地形测试场使用说明

> 分支 `feature/terrain`，2026-05-07 实现。
> 完整设计/计划：`docs/superpowers/specs/2026-05-07-mujoco-terrain-scene-design.md`、
> `docs/superpowers/plans/2026-05-07-mujoco-terrain-scene.md`。

## 这是什么

在不动现有 `scene_29dof.xml`（干净地板）的前提下，新增了一个 G1 地形测试场
`scene_29dof_terrain.xml`。机器人仍在原点出生，半径约 2m 内是干净平地，
四个方向放了不同地形：

```
                       +Y (北)
                          │
                  ▲ 8 级台阶（每级 0.10m × 0.25m）
                          │
                  init (0, +4, 0)
                          │
   西 -X：粗糙地面         │      东 +X：10° 斜坡 → 15° 斜坡 → Perlin 起伏
   8×8 小盒子阵列 ───── (0,0) ─────►  位置 (+3, 0)、(+5, 0)、(+7.5, 0)
   init (-4, -1, 0.02)  G1 出生
                          │
                          ▼
                 散落障碍：2 个箱子 + 2 个圆柱
                 范围 y ∈ (-3.5, -5.0)
                       -Y (南)
```

设计意图：
- **原点 ±2m 完全干净** —— 弹性带降落、policy 启动期机器人不会接触任何地形，
  和 `scene_29dof.xml` 行为完全一致
- **地板摩擦不变** —— 沿用 `scene_29dof.xml` 调好的 `friction="1.5 0.05 0.005"
  condim=6 priority=1`，避免 QA5 那个滑步问题复发
- **干净场景仍是默认值** —— 不主动开 `USE_TERRAIN`，已有的 agent_main /
  sim_rl_walk 启动行为零变化

## 文件清单

新增：
- `unitree_mujoco/unitree_robots/g1/scene_29dof_terrain.xml` — 地形场景
- `unitree_mujoco/unitree_robots/g1/terrain_perlin.png` — Perlin 高度图
- `unitree_mujoco/terrain_tool/g1_terrain_config.py` — 重跑生成脚本

修改：
- `unitree_mujoco/simulate_python/config.py` — 加了 `USE_TERRAIN = False` 开关

未动（git diff main 零差异）：`scene_29dof.xml`、`g1_29dof.xml`、`scene.xml`、
`height_field.png`、`unitree_hfield.png`。

## 怎么启动（含 WSL2 GPU 设置）

你之前的启动方式不变，只需要在启动前**编辑一行 config**：

### 1. 切换到地形场景

编辑 `~/unitree/unitree-notes/unitree_mujoco/simulate_python/config.py`，把：

```python
USE_TERRAIN = False
```

改成：

```python
USE_TERRAIN = True
```

要切回干净场景就改回 `False`。无需重新生成任何文件。

### 2. 启动 MuJoCo（你原来的命令）

```bash
conda activate unitree
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

启动后机器人在原点干净地板上出生（行为和之前完全一样），用手柄/键盘
把它走向四个方向之一就会遇到地形。

## 怎么改地形参数

所有参数集中在 `unitree_mujoco/terrain_tool/g1_terrain_config.py`。改完
重跑：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/terrain_tool
python g1_terrain_config.py
```

会重新生成 `../unitree_robots/g1/scene_29dof_terrain.xml` 和
`../unitree_robots/g1/terrain_perlin.png`。下次启动 MuJoCo（`USE_TERRAIN=True`）
就用新参数。

**首次运行需要装两个依赖**（一次性）：
```bash
conda run -n unitree pip install noise opencv-python
```

### 当前各地形参数

| 区域 | 地形 | 关键参数 |
|---|---|---|
| 东 +X (3.0, 0) | 10° 斜坡 | size=[1.5, 1.0, 0.05] |
| 东 +X (5.0, 0) | 15° 斜坡 | size=[1.5, 1.0, 0.05] |
| 东 +X (7.5, 0) | Perlin 高度场 | 2×2m，最大起伏 0.08m |
| 北 +Y (0, 4) | 8 级台阶 | 每级高 0.10m × 深 0.25m × 宽 1.0m |
| 南 -Y | 散落障碍 | 2 箱（40×40×20cm 和 30×30×40cm 旋转）+ 2 圆柱 |
| 西 -X (-4, -1) | 粗糙地面 | 8×8 阵列，~8cm 小盒子，±2cm 大小抖动 + ±5.7° 旋转 |

## 实施过程中踩到的两个坑（留作参考）

### 坑 1：`terrain_generator.py` 的 size 参数是"完整边长"不是"半边长"

`AddBox`、`AddGeometry`、`AddRoughGround` 内部都把 `size` 除以 2 再写进
MJCF（MuJoCo 原生用的是半边长）。所以脚本里要传"完整边长"。比如想要一个
40×40×20cm 的箱子，要写 `size=[0.40, 0.40, 0.20]`。圆柱的约定是
`size=[diameter, full_length]`。

### 坑 2：Perlin 高度图的 `file="../terrain_perlin.png"` 看似是 bug 实际是对的

`AddPerlinHeighField` 把 PNG 写到 `unitree_robots/g1/terrain_perlin.png`，
但 hfield XML 元素的 `file` 属性写成 `"../terrain_perlin.png"`。从 XML
所在目录看 `..` 是 `unitree_robots/`，那里没这个文件——一开始我以为是
upstream bug 给"修"成了纯文件名 `terrain_perlin.png`，结果 MuJoCo 加载时
报错：

```
ValueError: Error: Error opening file 'meshes/terrain_perlin.png'
```

原因是 `g1_29dof.xml` 顶部声明了 `<compiler meshdir="meshes" />`，
**MuJoCo 把 meshdir 也应用到 hfield 文件查找上**。所以：

- 纯文件名 `"terrain_perlin.png"` → 解析为 `<xml_dir>/meshes/terrain_perlin.png`（错）
- `"../terrain_perlin.png"` → 解析为 `<xml_dir>/meshes/../terrain_perlin.png`
  = `<xml_dir>/terrain_perlin.png`（对）

upstream 的 `"../"` 前缀正是为了消化这个 meshdir。最终保持原样，加了注释。

## 验证已通过

- 两个场景都能用 `mujoco.MjModel.from_xml_path` 成功加载
- 地形场景 `nq=36`（和干净场景一致，机器人没变）、`ngeom=153`（多了 79 个
  地形 geom：2 斜坡 + 1 hfield + 8 台阶 + 4 障碍 + 64 粗糙地面）、`nhfield=1`
- `USE_TERRAIN=False` 时 `ROBOT_SCENE = ../unitree_robots/g1/scene_29dof.xml`，
  和改动前完全一致
- 5 个受保护文件相对 `main` 字节级零差异

未做（需要你手动验证）：
- 视觉检查地形布局（启动 MuJoCo viewer 看一眼）
- 走向各个方向看 policy 能不能扛得住

如果发现某个地形太难或太容易，调 `g1_terrain_config.py` 重跑即可。
