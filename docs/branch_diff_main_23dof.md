# `main` vs `23_dof` 分支完整对比与 23_dof 测试启动说明

生成日期：2026-05-20  
仓库：`SparkyWen/unitree-notes`  
对比范围：`main` → `23_dof`  
对比方式：GitHub 分支比较 + 逐文件读取关键代码。说明：我没有在本机真实运行 MuJoCo / DDS / ONNX policy；以下启动流程是根据当前代码路径、配置、控制器逻辑和注释整理出的代码级说明。

---

## 0. 总结结论

`23_dof` 分支不是简单把 29 个电机改成 23 个电机，而是一次比较完整的 **23-DOF G1 policy / sim / skill / training 管线改造**。核心变化可以概括成下面几句话：

1. **主控制空间从 29-DOF 切到 23-DOF。** 23-DOF 保留双腿 12 个关节、waist yaw 1 个关节、双臂每臂 5 个关节，共 23 个 policy joint；禁用 / 不控制 waist roll、waist pitch，以及左右手腕 pitch/yaw 共 6 个关节。
2. **新增了部署用 23-DOF policy 包。** `g1_sim_demo/policy/policy.onnx`、`params/deploy.yaml`、`params/agent.yaml`、`params/env.yaml`、`gestures_23dof.npz` 都是新增部署 / 训练导出资产。
3. **`g1_sim_rl_combo.py` 被改造成 23-DOF arm-aware combo controller。** 它现在读取本地 policy 包、读取 `joint_ids_map` 做 23→29 SDK slot 映射、对未控制 SDK slot 发布零增益，并在 policy obs 中加入 gesture onehot + future arm reference horizon。
4. **新增 arm-disturbance 训练任务。** `unitree_rl_mjlab` 中新增 `ArmReferenceCommand`、`ArmDisturbanceAction`、gesture obs、arm tracking reward、gesture intensity curriculum，并注册 `Unitree-G1-23Dof-Flat-Arm-Disturbance`。
5. **MuJoCo 默认 G1 场景切到 23-DOF terrain scene。** `simulate_python/config.py` 默认 `ROBOT_SCENE` 从 29DOF terrain 切到 `scene_23dof_terrain.xml`，并把 default hold PD 从 23 维展开到 29 个 SDK motor slot。
6. **g1_brain / va-demo 主要是路径、摄像头、watchdog/agent 初始化稳定性改动。** 其中 `g1_brain` 仍有一个重要不一致点：配置里的 `robot.mjcf_path` 默认还是 `scene_29dof_terrain.xml`，如果你要让 brain/head camera 与 23-DOF MuJoCo 场景一致，需要手动改成 `scene_23dof_terrain.xml`。
7. **“watchdog”在当前代码里不是一个独立必须先启动的第二个程序。** 如果你运行 `g1_sim_demo/g1_sim_rl_combo.py`，只有 MuJoCo + controller 两步；如果你运行完整 `g1_brain.apps.agent_main`，它会在同一个 agent 进程里按顺序初始化 DDS、CameraHub、ComboProxy/ComboController、RobotStateBus/FSM、SafetySupervisor、WatchdogManager、Perception、SkillServer 和 Realtime agent。也就是说：**代码实际顺序不是“MuJoCo → watchdog → ctrl policy”，而更接近“MuJoCo → agent_main；agent_main 内部先加载 ctrl policy，再启动 watchdog”。**

---

## 1. Git 分支级别差异

GitHub compare 结果：

| 项目 | 结果 |
|---|---:|
| 分支关系 | `diverged` |
| `23_dof` 相对 `main` | ahead 20 commits |
| `23_dof` 相对 `main` | behind 2 commits |
| 变更文件数 | 35 files |
| base/main commit | `2b653a90ea64bccc2e7a403b15a5c64fa56d5915` |
| merge-base | `456c13ec32470e1398d8caf7d4d82b6c48c9a05b` |

注意：因为是 `diverged`，所以 `23_dof` 不是简单的 main 最新状态加 23DOF 补丁；它还落后 main 两个提交。如果以后要合并，应该先处理这两个 main 侧提交带来的冲突 / 缺失。

---

## 2. 35 个变更文件总表

| 文件 | 状态 | 增删 | 模块 | 作用 |
|---|---|---:|---|---|
| `docs/g1_arm_aware_policy_plan.md` | modified | +341 / -90 | 文档 | arm-aware policy 方案从规划扩展到 baseline、mimic smoke test、arm-disturbance 训练设计和结论。 |
| `docs/policy_baselines/baseline_2026-05-08.md` | added | +97 | 文档 | 记录 stand / walk_slow 下 gestures 的 baseline：站立+手势失败，走路+手势通过。 |
| `docs/policy_baselines/baseline_2026-05-08_stand_yaw.md` | added | +59 | 文档 | 记录 `wz=0.1` falsification：遥测能站住，但视觉上在绕圈，不能作为站立手势方案。 |
| `g1_brain/configs/g1_brain.yaml` | modified | +3 / -3 | brain config | 路径从 `${HOME}/unitree/unitree-notes` 改成 `${HOME}/unitree-notes`；但 MJCF 仍指向 29DOF terrain。 |
| `g1_brain/g1_brain/apps/agent_main.py` | modified | +5 / -5 | brain app | sibling repo import 路径从 `~/unitree/unitree-notes` 改为 `~/unitree-notes`。 |
| `g1_brain/g1_brain/perception/cameras.py` | modified | +1 / -1 | perception | head camera fallback MJCF 路径从 `~/unitree/unitree-notes/...` 改为 `~/unitree-notes/...`，仍默认 29DOF terrain。 |
| `g1_brain/g1_brain/skills/keyframe_extras.py` | modified | +67 / -92 | skills | 从 29DOF arm slice 15:29 改为 23DOF arm slice 13:23；salute/hug 改成 10D arm-local 动作。 |
| `g1_brain/g1_brain/skills/skill_server.py` | modified | +1 / -1 | skills | g1_sim_demo 搜索路径从 `~/unitree/unitree-notes` 改为 `~/unitree-notes`。 |
| `g1_sim_demo/g1_sim_baseline_runner.py` | added | +357 | sim demo | 新增 policy baseline 自动测试器，跑 gestures × speeds 并生成指标。 |
| `g1_sim_demo/g1_sim_interactive.py` | modified | +24 / -40 | sim demo | 低层交互 demo 从 29DOF 改为 23DOF；移除 waist roll/pitch、wrist pitch/yaw；移除 bow waist pitch。 |
| `g1_sim_demo/g1_sim_rl_combo.py` | modified | +332 / -195 | sim demo | 主 23DOF RL walking + gesture combo controller。最大核心改动。 |
| `g1_sim_demo/g1_sim_rl_mimic.py` | added | +469 | sim demo | 新增 29DOF mimic/dance policy adapter，用于 whole-body tracking smoke test，不是 23DOF velocity controller。 |
| `g1_sim_demo/g1_sim_rl_walk.py` | modified | +49 / -34 | sim demo | walk-only controller 改为 23DOF，动态 obs/action dim，23→29 SDK slot 映射。 |
| `g1_sim_demo/policy/gestures_23dof.npz` | added | binary | policy asset | 23DOF gesture trajectory library，arm_qpos 为 10D。 |
| `g1_sim_demo/policy/params/agent.yaml` | added | +55 | policy config | 23DOF arm-disturbance PPO runner / checkpoint metadata。 |
| `g1_sim_demo/policy/params/deploy.yaml` | added | +62 | policy config | 23DOF deploy cfg：23 joints、joint_ids_map、Kp/Kd/default/action scale/ranges。 |
| `g1_sim_demo/policy/params/env.yaml` | added | +1599 | policy config | 23DOF arm-disturbance training env export，包含 obs/reward/action/commands/events。 |
| `g1_sim_demo/policy/policy.onnx` | added | binary | policy asset | 部署用 23DOF ONNX policy。 |
| `unitree_mujoco/simulate_python/config.py` | modified | +36 / -25 | MuJoCo sim | 默认 G1 scene 改为 23DOF terrain；default hold PD 改成 23→29 展开。 |
| `unitree_mujoco/unitree_robots/g1/images/mygo_cover.png` | added | binary | asset | 视觉测试墙贴图 PNG。 |
| `unitree_mujoco/unitree_robots/g1/images/「BanG Dream! It's MyGO!!!!!」＃01 Cover.jpg` | added | binary | asset | 原始视觉测试图片。 |
| `unitree_mujoco/unitree_robots/g1/scene_23dof_terrain.xml` | added | +23 | MuJoCo scene | 新增 23DOF terrain scene，include `g1_23dof.xml`，含地形 / 阶梯 / box / hfield。 |
| `unitree_mujoco/unitree_robots/g1/scene_29dof.xml` | modified | +16 | MuJoCo scene | 给 29DOF flat scene 增加 test-photo wall，用于 vision validation。 |
| `unitree_rl_mjlab/scripts/train_arm_disturbance.sh` | added | +124 | training | 新增一键训练脚本，生成 gestures_23dof，warm-start 或 cold-start 训练 23DOF arm disturbance。 |
| `unitree_rl_mjlab/src/assets/motions/g1/make_gestures_npz.py` | added | +208 | training asset | 从 combo/keyframe extras 生成 `gestures_23dof.npz` / `gestures.npz`。 |
| `unitree_rl_mjlab/src/tasks/velocity/config/g1/__init__.py` | modified | +9 | training registry | 注册 29DOF `Unitree-G1-Flat-Arm-Disturbance`。 |
| `unitree_rl_mjlab/src/tasks/velocity/config/g1/env_cfgs.py` | modified | +136 | training cfg | 给 29DOF G1 也加入 arm-disturbance env cfg。 |
| `unitree_rl_mjlab/src/tasks/velocity/config/g1_23dof/__init__.py` | modified | +9 | training registry | 注册 23DOF `Unitree-G1-23Dof-Flat-Arm-Disturbance`。 |
| `unitree_rl_mjlab/src/tasks/velocity/config/g1_23dof/env_cfgs.py` | modified | +118 | training cfg | 给 23DOF G1 增加 arm-disturbance env cfg。 |
| `unitree_rl_mjlab/src/tasks/velocity/mdp/__init__.py` | modified | +12 | training mdp | 导出 arm-disturbance MDP symbols。 |
| `unitree_rl_mjlab/src/tasks/velocity/mdp/arm_disturbance.py` | added | +408 | training mdp | 新增 GestureLibrary、ArmReferenceCommand、ArmDisturbanceAction、obs/reward/curriculum。 |
| `va-demo/requirements.txt` | modified | +1 | va-demo | 新增 `python-dotenv>=1.0.0`。 |
| `va-demo/va_demo/main.py` | modified | +56 / -9 | va-demo | 新增 `.env` 加载、`--mujoco-camera`、DDS-before-camera 初始化。 |
| `va-demo/va_demo/mujoco_camera.py` | added | +357 | va-demo | 新增 MuJoCo offscreen head-camera renderer。 |
| `va-demo/va_demo/skills.py` | modified | +17 / -3 | va-demo | g1_sim_demo path discovery 从单一路径改为多候选路径。 |

---

## 3. 最核心功能差异：29DOF → 23DOF 控制空间

### 3.1 main 分支的控制空间

`main` 分支的 `g1_sim_demo/g1_sim_rl_combo.py` 是 29DOF：

- `G1_NUM_MOTOR = 29`
- arms slice：`ARM_START = 15`, `ARM_END = 29`, `ARM_DIM = 14`
- 包含：
  - 双腿 12
  - waist yaw / roll / pitch 3
  - 左臂 7：shoulder pitch/roll/yaw、elbow、wrist roll/pitch/yaw
  - 右臂 7：shoulder pitch/roll/yaw、elbow、wrist roll/pitch/yaw
- policy obs/action 固定：
  - `OBS_DIM = 98`
  - `ACT_DIM = 29`
- policy 路径指向 upstream deploy：
  - `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx`
  - `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml`

### 3.2 23_dof 分支的控制空间

`23_dof` 的 combo controller 改成：

- `G1_NUM_MOTOR = 23`
- `G1_SDK_MOTOR_TOTAL = 29`
- 23DOF policy joint order：

```text
0  LeftHipPitch
1  LeftHipRoll
2  LeftHipYaw
3  LeftKnee
4  LeftAnklePitch
5  LeftAnkleRoll
6  RightHipPitch
7  RightHipRoll
8  RightHipYaw
9  RightKnee
10 RightAnklePitch
11 RightAnkleRoll
12 WaistYaw
13 LeftShoulderPitch
14 LeftShoulderRoll
15 LeftShoulderYaw
16 LeftElbow
17 LeftWristRoll
18 RightShoulderPitch
19 RightShoulderRoll
20 RightShoulderYaw
21 RightElbow
22 RightWristRoll
```

保留 / 控制的 SDK motor slots：

```python
joint_ids_map = [
  0,1,2,3,4,5,
  6,7,8,9,10,11,
  12,
  15,16,17,18,19,
  22,23,24,25,26,
]
```

不控制 / 禁用的 SDK motor slots：

```text
13 WaistRoll
14 WaistPitch
20 LeftWristPitch
21 LeftWristYaw
27 RightWristPitch
28 RightWristYaw
```

也就是说，MuJoCo / DDS 消息仍然有 29 个 motor slot，但 policy 和 controller 只对 23 个 slot 负责。controller 每次 `_publish()` 都会先把 excluded slots 写成：

```text
mode = 0
q = 0
dq = 0
tau = 0
kp = 0
kd = 0
```

然后只给 `joint_ids_map` 里的 23 个 slot 写 PD command。

---

## 4. `g1_sim_demo/g1_sim_rl_combo.py` 详细变化

这是整个分支最重要的改动文件。

### 4.1 policy 路径从 upstream deploy 改成 branch 内置 policy 包

`main`：

```python
POLICY_DIR = ~/unitree-notes/unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0
POLICY_ONNX = POLICY_DIR / "exported" / "policy.onnx"
POLICY_YAML = POLICY_DIR / "params" / "deploy.yaml"
```

`23_dof`：

```python
POLICY_ONNX = g1_sim_demo/policy/policy.onnx
POLICY_YAML = g1_sim_demo/policy/params/deploy.yaml
```

这点很重要：**23_dof 推荐用 `g1_sim_rl_combo.py` 测试，因为它直接使用 branch 内置的 23DOF policy 包，不依赖你本地是否另有 `unitree_rl_mjlab/deploy/robots/g1_23dof/...`。**

### 4.2 `DeployCfg` 改成读取 23DOF `joint_ids_map`

新增 / 强化逻辑：

- 从 `deploy.yaml` 读取 `joint_ids_map`。
- 检查 `kp/kd/default_q/action_scale/action_offset` shape 必须等于 23。
- 计算：

```python
excluded_sdk_slots = sorted(set(range(29)) - set(joint_ids_map))
```

这避免了 23DOF policy 输出直接错误写到 29DOF slot 的问题。

### 4.3 `Policy` 不再固定 98→29，而是从 ONNX 动态读取维度

`main` 的 policy wrapper 固定：

```python
OBS_DIM = 98
ACT_DIM = 29
```

`23_dof` 的 policy wrapper 会读取 ONNX input/output shape：

- `obs_dim = model input last dim`
- `act_dim = model output last dim`
- 要求 `act_dim == 23`

如果 obs dim 比 base obs 大，controller 会自动追加 gesture obs。

### 4.4 base observation 从 98D 变为 80D

23DOF base obs：

| slice | dim |
|---|---:|
| IMU angular velocity | 3 |
| projected gravity | 3 |
| velocity command vx/vy/wz | 3 |
| gait phase sin/cos | 2 |
| joint_pos_rel | 23 |
| joint_vel_rel | 23 |
| last_action | 23 |
| 合计 | 80 |

公式：

```text
11 + 3 * num_motors = 11 + 3 * 23 = 80
```

### 4.5 arm-aware policy observation：gesture onehot + arm horizon

如果 ONNX `obs_dim > 80`，`_build_obs()` 会追加：

1. `gesture_onehot`：长度为 gesture library 中的 gesture 数量。
2. `arm_qpos_ref_horizon`：`_GESTURE_K * ARM_DIM = 5 * 10 = 50`。

如果 gesture 数为 9，则 actor obs 为：

```text
80 + 9 + 50 = 139D
```

这正好对应 23DOF arm-disturbance 训练：policy 不只是看到当前手臂状态，还能看到“未来 5 帧的手臂参考动作”，从而提前用腿 / 躯干补偿重心扰动。

### 4.6 gesture library：`gestures_23dof.npz`

新增：

```python
_GESTURE_FILE = g1_sim_demo/policy/gestures_23dof.npz
_GESTURE_FPS = 50.0
_GESTURE_K = 5
```

当前代码把部分键映射到 library gesture：

```python
_KEY_TO_GESTURE_IDX = {
  "1": 0,  # wave_right
  "2": 1,  # wave_left
  "3": 2,  # hands_up
  "4": 3,  # t_pose
  "hug": 8,
}
```

注意：键 `5-8` 没有直接放入 `_KEY_TO_GESTURE_IDX`，注释原因是旧 library 中这些姿态不正确；controller 会 fallback 到 keyframe 动作。

### 4.7 arm overlay 和 Kp boost

23_dof 的 combo controller 把手臂动作分为两类：

- **library gesture**：从 `gestures_23dof.npz` 逐帧播放；policy obs 同步收到 onehot + horizon。
- **keyframe fallback**：普通 keyframe overlay，比如 salute/clap/guard/punch/bow 等。

新增的 Kp 设计：

```python
ARM_GESTURE_KP_SCALE = 2.8
ARM_KP_RAMP_PER_SEC = 4.0
STAND_KP_BOOST_TARGET = 1.4
STAND_KP_RAMP_PER_SEC = 4.0
```

含义：

- 手势执行时只提高 arm joints 的 Kp/Kd，让手臂真正跟上姿态，不提高腿部 Kp。
- BOOT 或 policy 未 active 时提高 leg/waist Kp，让默认姿态 hold 更硬一点。
- policy active 后 leg/waist gain 回到训练时 deploy gain，减少 sim-to-policy mismatch。

### 4.8 BOOT / engage 逻辑的关键修复

`23_dof` 文件注释中明确记录了一个 root-cause：

- 以前假设 `default_q + PD` 可以静态站稳。
- headless MuJoCo 验证证明这个假设错误：default_q + PD 会在约 1.5 秒塌掉。
- 训练好的 policy 在 `cmd=(0,0,0)` 时反而能长期保持 `gz=-1.0`。

所以现在：

1. BOOT：从 measured pose 平滑 ramp 到 `default_q`。
2. BOOT 完成后：不再长时间用 default_q 等待 settle gates。
3. 直接 engage policy：打印

```text
[combo] policy engaged. wsadqe to walk; 1-8 arm gestures; 0 release.
```

4. policy phase 中：即使 `cmd=0` 也继续跑 policy，不再切回 default_q stand-still bypass。

这对你的启动流程非常关键：**不要让机器人在地上长期只靠 default_q PD 站立；要让 policy 尽快接管。**

### 4.9 keyboard UI

23_dof `g1_sim_rl_combo.py` 运行后支持：

| 键 | 功能 |
|---|---|
| `w/s` | forward / backward，vx ±0.2 m/s |
| `a/d` | strafe left / right，vy ±0.1 m/s |
| `q/e` | yaw left / right，wz ±0.3 rad/s |
| `r` | stop walking，cmd → 0,0,0 |
| `f` | full forward，vx → vx_max |
| `1-8` | arm gestures |
| `0` | release arms，blend 回 rest |
| `space` | soft-disable Kp/Kd，机器人会塌，慎用 |
| `?` | 打印帮助 |
| `x` / Ctrl-C | soft settle 后退出 |

---

## 5. `g1_sim_demo/policy/*` 新增 policy 包

### 5.1 `params/deploy.yaml`

新增 23DOF 部署配置，关键内容：

```yaml
joint_ids_map: [0,1,2,3,4,5,6,7,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26]
step_dt: 0.02
```

默认姿态：

```text
left leg:  -0.1, 0, 0, 0.3, -0.2, 0
right leg: -0.1, 0, 0, 0.3, -0.2, 0
waist yaw: 0
left arm:  0.35, 0.18, 0, 0.87, 0
right arm: 0.35, -0.18, 0, 0.87, 0
```

command range：

```yaml
lin_vel_x: [-0.5, 1.0]
lin_vel_y: [-0.5, 0.5]
ang_vel_z: [-1.0, 1.0]
```

gait period：

```yaml
gait_phase.period: 0.6
```

obs terms：

- base angular velocity
- projected gravity
- velocity command
- gait phase
- joint_pos_rel
- joint_vel_rel
- last_action

controller 另外根据 ONNX obs_dim 决定是否追加 gesture obs。

### 5.2 `params/agent.yaml`

新增 PPO / runner metadata：

- experiment：`g1_23dof_arm_disturbance`
- resume：true
- load run：`2026-05-08_21-13-34`
- actor/critic hidden dims：`512, 256, 128`
- activation：`elu`
- observation normalization：true

### 5.3 `params/env.yaml`

这是导出的训练环境配置，核心表明这个 policy 来自 23DOF arm-disturbance 任务：

- robot spec：`src.assets.robots.unitree_g1.g1_23dof_constants.get_spec`
- action：`JointPositionAction`，23DOF。
- actor obs 除 base velocity obs 之外还包括：
  - `gesture_onehot`
  - `arm_qpos_ref_horizon`，`k=5`
- critic obs 有更多 privileged terms。
- command 中新增 `arm_ref`：
  - gesture file：`gestures_23dof.npz`
  - fps：50
  - trigger interval：8–16 秒，curriculum 后变成 4–8 秒。
- reward 中新增：
  - `arm_track_l2`
  - arms pose std 被放大到 `1e6`，避免普通 posture reward 跟手势 reference 打架。

### 5.4 `policy.onnx`

新增 binary ONNX。controller 会自动读取 input/output dim。

### 5.5 `gestures_23dof.npz`

新增 binary gesture library：

- arm_qpos：`[N_g, T_max, 10]`
- lengths：每个 gesture 的有效帧数
- names：gesture names
- 23DOF arm dim = 10，即每臂 5 个 joint。

---

## 6. `g1_sim_demo/g1_sim_rl_walk.py` 变化

这个文件是 walk-only controller，不带完整 gesture overlay。主要变化：

| 项目 | main | 23_dof |
|---|---|---|
| DOF | 29 | 23 |
| obs | 固定 98 | `11 + 3 * num_motors = 80` |
| act | 固定 29 | 23 |
| SDK slots | 直接 0..28 | 通过 `joint_ids_map` 映射 |
| excluded slots | 无 | 13,14,20,21,27,28 置零增益 |

需要注意：`g1_sim_rl_walk.py` 的 policy 路径仍指向：

```text
~/unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1_23dof/config/policy/velocity/v0
```

而 `g1_sim_rl_combo.py` 已经使用 `g1_sim_demo/policy/` 内置 policy。因此测试 `23_dof` 分支时，**优先运行 `g1_sim_rl_combo.py`**；除非你确认本地 `unitree_rl_mjlab/deploy/robots/g1_23dof/...` 已经存在并匹配。

---

## 7. `g1_sim_demo/g1_sim_baseline_runner.py` 新增

这是新的自动 baseline 测试脚本。

功能：

- 自动创建 `ComboController`。
- 使用 `set_command(vx, vy, wz)` 设置速度。
- 对 gesture 表逐个调用 `push_arm_action()` 或 unified gesture table。
- 记录 lowstate 指标。
- 生成 pass / marginal / fail。

默认 speed cases：

```python
stand      = (0.0, 0.0, 0.0)
stand_yaw  = (0.0, 0.0, 0.1)
walk_slow  = (0.2, 0.0, 0.0)
```

指标包括：

- `gz`：projected gravity z
- `max |gz + 1|`
- final gz
- max joint velocity
- pelvis pitch
- fall detection

典型使用：

```bash
cd ~/unitree-notes/g1_sim_demo
python g1_sim_baseline_runner.py --speeds stand,stand_yaw,walk_slow --report /tmp/baseline_23dof.md
```

注意：这个 runner 本身会启动 ComboController，所以不要同时再开一个 `g1_sim_rl_combo.py`，否则两个 controller 会抢 `rt/lowcmd`。

---

## 8. `g1_sim_demo/g1_sim_rl_mimic.py` 新增

这个文件容易误解，必须单独说明。

它是 **29DOF mimic/dance policy adapter**，不是 23DOF velocity policy controller。

关键点：

- 使用 mimic policy：

```text
unitree_rl_mjlab/deploy/robots/g1/config/policy/mimic/dance1_subject2/
```

- `_MIMIC_NUM_MOTOR = 29`
- `EXPECTED_OBS_DIM = 154`
- obs 组成：

```text
motion_command: 58
motion_anchor_ori_b: 6
ang_vel: 3
joint_pos_rel: 29
joint_vel_rel: 29
last_action: 29
合计: 154
```

- 它复用了 `ComboController` 的 DDS / publish / soften 等 plumbing，但 override：
  - `MimicDeployCfg`
  - `MimicPolicy`
  - `_build_obs(frame)`
  - `_tick()`
  - `_engage()`

用途：whole-body tracking / dance smoke test。它证明 MuJoCo bridge 可以跑全身 tracking policy，但 **不能用它来验证 23DOF arm-disturbance policy 是否正确**。

---

## 9. `g1_sim_demo/g1_sim_interactive.py` 变化

这是低层 keyframe demo，不是 RL policy。

变化：

- `G1_NUM_MOTOR` 从 29 改为 23。
- joint enum 删除：
  - WaistRoll
  - WaistPitch
  - LeftWristPitch
  - LeftWristYaw
  - RightWristPitch
  - RightWristYaw
- Kp/Kd 数组从 29 个值改为 23 个值。
- pose helper 全部返回 23 维 pose。
- `bow_pose()` 被移除，因为 23DOF 没有 waist pitch。
- `TRAJECTORIES` 删除 `b` bow，只保留：
  - `z` zero pose
  - `w` wave right arm
  - `k` lift left knee
  - `a` clap

注意：这个 demo 的 `_publish()` 循环是 `for i in range(G1_NUM_MOTOR)`，直接写 `low_cmd.motor_cmd[i]`，**没有像 combo 一样用 `joint_ids_map` 映射到 SDK 29 slots**。这意味着它更像一个简化低层 demo；测试 23DOF policy 不应优先用它。

---

## 10. MuJoCo 侧变化

### 10.1 `unitree_mujoco/simulate_python/config.py`

`main`：

```python
if ROBOT == "g1":
    if USE_TERRAIN:
        ROBOT_SCENE = "../unitree_robots/g1/scene_29dof_terrain.xml"
    else:
        ROBOT_SCENE = "../unitree_robots/g1/scene_29dof.xml"
```

`23_dof`：

```python
if ROBOT == "g1":
    if USE_TERRAIN:
        ROBOT_SCENE = "../unitree_robots/g1/scene_23dof_terrain.xml"
    else:
        ROBOT_SCENE = "../unitree_robots/g1/scene_23dof.xml"
```

新增 23DOF default hold 逻辑：

```python
_G1_CTRL_MAP_23TO29 = [0,1,2,3,4,5,6,7,8,9,10,11,12,15,16,17,18,19,22,23,24,25,26]
G1_DEFAULT_JOINT_POS = [0.0] * 29
G1_DEFAULT_KP = [0.0] * 29
G1_DEFAULT_KD = [0.0] * 29
for i, j in enumerate(_G1_CTRL_MAP_23TO29):
    G1_DEFAULT_JOINT_POS[j] = _G1_CTRL_JOINTS_23DOF[i]
    G1_DEFAULT_KP[j] = _G1_KP_JOINTS_23DOF[i]
    G1_DEFAULT_KD[j] = _G1_KD_JOINTS_23DOF[i]
```

含义：MuJoCo bridge 在 controller 尚未启动前，会给 23DOF 控制 joint 一个默认 hold pose；未使用的 6 个 SDK slot Kp/Kd 为 0。

### 10.2 `scene_23dof_terrain.xml` 新增

新增 scene：

```xml
<mujoco model="g1_23dof scene">
  <include file="g1_23dof.xml" />
  ...
</mujoco>
```

包含：

- floor，friction=`1.5 0.05 0.005`，`condim=6`，`priority=1`
- ramps
- stairs
- Perlin hfield
- boxes / cylinders / rough patches

### 10.3 `scene_29dof.xml` 新增 vision validation wall

虽然 23DOF 默认使用 `scene_23dof_terrain.xml`，但分支也改了 `scene_29dof.xml`：

- 新增 `images/mygo_cover.png` texture。
- 新增 non-collision photo wall：

```xml
<geom name="test_photo_wall" type="box" pos="2.0 0 1.24"
      xyaxes="0 -1 0 0 0 1" size="0.75 0.5 0.02"
      material="test_photo" contype="0" conaffinity="0"/>
```

用途：给 head-camera / vision model 做端到端视觉验证。

---

## 11. training 侧：arm-disturbance MDP 新增

### 11.1 `arm_disturbance.py`

新增模块提供：

| 类 / 函数 | 功能 |
|---|---|
| `GestureLibrary` | 从 `gestures*.npz` 读取 gesture trajectory。 |
| `ArmReferenceCommand` | 每个 env 随机触发 gesture；维护 gesture id、phase、active mask。 |
| `ArmReferenceCommandCfg` | command term config。 |
| `arm_qpos_ref_obs` | 当前 arm reference observation。 |
| `gesture_onehot_obs` | 当前 gesture onehot observation。 |
| `arm_qpos_ref_horizon_obs` | 未来 k 帧 arm reference observation。 |
| `arm_track_l2` | active gesture 时惩罚实际 arm 与 reference 偏差。 |
| `ArmDisturbanceAction` | 在 action apply 前把 arm action slice override 成 gesture reference。 |
| `ArmDisturbanceActionCfg` | action term config。 |
| `gesture_intensity` | curriculum：调整 gesture trigger frequency。 |

默认 23DOF arm slice：

```python
_ARM_START = 13
_ARM_END = 23
_ARM_DIM = 10
```

23DOF arm joint patterns：

```python
shoulder_pitch
shoulder_roll
shoulder_yaw
elbow
wrist_roll
```

29DOF 可通过 `_ARM_JOINT_PATTERNS_29DOF` 增加 wrist pitch/yaw。

### 11.2 `g1_23dof/env_cfgs.py`

新增：

```python
unitree_g1_23dof_flat_arm_disturbance_env_cfg(play=False)
```

它在原 23DOF flat velocity env 上加：

- `commands["arm_ref"] = ArmReferenceCommandCfg(...)`
- `actions["joint_pos"] = ArmDisturbanceActionCfg(...)`
- actor / critic obs 添加：
  - `gesture_onehot`
  - `arm_qpos_ref_horizon`
- pose reward 的 arm std 设为 `1e6`
- reward 添加 `arm_track_l2`，weight `0.05`
- curriculum 添加 `gesture_intensity`

23DOF actor obs 维度逻辑：

```text
base 80 + gesture_onehot 9 + horizon 5*10 = 80 + 9 + 50 = 139
```

### 11.3 task registration

`g1_23dof/__init__.py` 新增注册：

```python
register_mjlab_task(
  task_id="Unitree-G1-23Dof-Flat-Arm-Disturbance",
  env_cfg=unitree_g1_23dof_flat_arm_disturbance_env_cfg(),
  play_env_cfg=unitree_g1_23dof_flat_arm_disturbance_env_cfg(play=True),
  rl_cfg=unitree_g1_23dof_ppo_runner_cfg(),
  runner_cls=VelocityOnPolicyRunner,
)
```

`g1/__init__.py` 也类似新增 29DOF arm-disturbance task。

### 11.4 `make_gestures_npz.py`

作用：从 `g1_sim_rl_combo.build_arm_actions()` 和 `keyframe_extras.build_extra_arm_actions()` 采样 gesture keyframes，保存成 NPZ。

支持：

```bash
python src/assets/motions/g1/make_gestures_npz.py --dof 23
python src/assets/motions/g1/make_gestures_npz.py --dof 29
```

23DOF 输出：

```text
gestures_23dof.npz
arm_qpos: [N_g, T_max, 10]
lengths:  [N_g]
names:    [N_g]
```

29DOF 输出：

```text
gestures.npz
arm_qpos: [N_g, T_max, 14]
```

### 11.5 `train_arm_disturbance.sh`

新增一键训练脚本：

```bash
cd ~/unitree-notes/unitree_rl_mjlab
bash scripts/train_arm_disturbance.sh
```

它会：

1. activate `~/unitree_sdk2_python/unitree-env`
2. export `PYTHONPATH=${REPO_ROOT}:${PYTHONPATH}`
3. 生成 `gestures_23dof.npz`
4. 如果存在 `g1_23dof_velocity` checkpoint，则 symlink warm-start。
5. 如果没有 checkpoint，则 cold-start。
6. 启动：

```bash
python scripts/train.py \
  Unitree-G1-23Dof-Flat-Arm-Disturbance \
  --env.scene.num-envs "${NUM_ENVS}" \
  --agent.experiment-name g1_23dof_arm_disturbance \
  --agent.max-iterations "${MAX_ITER}" \
  --gpu-ids "${GPU_IDS}" \
  --video True
```

修复点：

- `GPU_IDS` 会自动包成 `[0]` 这种 tyro list[int] 格式。
- `RECORD_VIDEO=false` 可关闭视频。
- 没有 warm-start checkpoint 时不再失败，而是 cold-start。

---

## 12. 文档与 baseline 结论变化

### 12.1 `docs/g1_arm_aware_policy_plan.md`

该文档从“策略计划”变成了包含实测结论的完整方案记录。

关键结论：

- 原 velocity policy 没见过 arm motion。
- 旧 workaround 是隐藏 arm motion：post-policy override arms、mask arm slice obs、降低或控制 arm Kp。
- 小动作可用，大动作会破坏平衡。
- option 1：先做 baseline characterization。
- option 2：继续训练 velocity policy，加 arm-disturbance task。
- option 3：如果失败，再上 whole-body tracking / BeyondMimic / HOVER 等。

### 12.2 `baseline_2026-05-08.md`

重要实测结果：

- `cmd=(0,0,0)` 站立 + gesture：失败。
  - `wave_right` FAIL：`max|Δgz| = 0.464`
  - `hands_up` FAIL：`max|Δgz| = 1.814`，gz crossed 0，视为 fall。
- `cmd=(0.2,0,0)` walk_slow + 所有 9 个 gestures：全部 PASS，`max|Δgz| ≤ 0.03`。

文档结论：

```text
standing balance + arm gesture = failure mode
walking + arm gesture = already works
```

这说明问题不是单纯“手臂动作太大”，而是 policy 在 `cmd=0` standing 状态下没有学会对手臂扰动作主动平衡。

### 12.3 `baseline_2026-05-08_stand_yaw.md`

测试假设：给一个很小 yaw command `cmd=(0,0,0.1)` 是否能“唤醒腿部 torque”，从而不用 retrain。

结果：

- telemetry 全部 PASS。
- 但视觉 FAIL：机器人在 gesture 过程中走小圈 / 转了约 0.8 rad，不是站立不动。

结论：不能用 brain-side 注入微小 yaw 作为 workaround，必须 retrain 让 policy 学会：

```text
cmd=0 + arm motion => shift weight, do not step / do not yaw drift
```

---

## 13. g1_brain 变化

### 13.1 路径变化

`23_dof` 将多个路径从：

```text
~/unitree/unitree-notes
```

改成：

```text
~/unitree-notes
```

影响文件：

- `g1_brain/configs/g1_brain.yaml`
- `g1_brain/g1_brain/apps/agent_main.py`
- `g1_brain/g1_brain/perception/cameras.py`
- `g1_brain/g1_brain/skills/skill_server.py`

这说明分支作者当前主要假设 repo 位于：

```text
~/unitree-notes
```

但 `g1_sim_rl_walk.py` 仍有 `~/unitree/unitree-notes` 路径，所以建议保留兼容软链接，见后文启动流程。

### 13.2 `g1_brain.yaml` 的重要不一致

`23_dof` 中：

```yaml
robot:
  mjcf_path: "${HOME}/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof_terrain.xml"
```

而 MuJoCo simulator 默认已经切到：

```text
scene_23dof_terrain.xml
```

这会导致：

- operator 在 MuJoCo viewer 里看的是 23DOF terrain。
- brain 的 head camera / perception 可能加载 29DOF terrain。
- describe_scene / ground constraint 看到的世界可能与 viewer 不一致。

如果要跑完整 `g1_brain`，建议把 `g1_brain.yaml` 改为：

```yaml
robot:
  mjcf_path: "${HOME}/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_23dof_terrain.xml"
```

或者复制一个专用 config：

```bash
cp g1_brain/configs/g1_brain.yaml /tmp/g1_brain_23dof.yaml
# 编辑 /tmp/g1_brain_23dof.yaml，把 robot.mjcf_path 改成 scene_23dof_terrain.xml
```

### 13.3 `keyframe_extras.py`

`main`：

- 29DOF arm slice：`15:29`
- `ARM_DIM = 14`
- salute/hug 先构造 29D pose，再 slice arms。
- 包含 wrist pitch/yaw。

`23_dof`：

- 23DOF arm slice：`13:23`
- `ARM_DIM = 10`
- 直接构造 arm-local 10D target。
- 去掉 wrist pitch/yaw。
- 只保留 physical joint limit clamp。

`salute` 目标：

```python
RightShoulderPitch = -0.6
RightShoulderRoll  = -0.4
RightElbow         =  1.55
```

`hug` 目标：

```python
LeftShoulderPitch  = -0.8
LeftShoulderRoll   =  0.6
LeftElbow          =  1.5
RightShoulderPitch = -0.8
RightShoulderRoll  = -0.6
RightElbow         =  1.5
```

### 13.4 `agent_main.py` 中 watchdog / controller 的真实初始化顺序

完整 `g1_brain.apps.agent_main` 的关键顺序是：

1. 检查 `OPENAI_API_KEY`。
2. 单实例 lock。
3. 启动 audio mic / speaker。
4. DDS `ChannelFactoryInitialize`。
5. 创建 `CameraHub`。
6. 创建并启动 controller：默认用 `ComboProxy` 子进程隔离 controller；如果失败则 fallback 到 in-process `ComboController`。
7. 等待 `ComboController policy_active`。
8. 创建 `SceneStateBus` / `RobotStateBus`。
9. FSM transition 到 `STANDING`。
10. 创建 E-stop client。
11. 创建 `SafetySupervisor`。
12. 创建并 `watchdogs.start()`。
13. 启动 perception。
14. 创建 OpenAI TTS / vision。
15. 创建 `VisionRiskGate`。
16. 创建 `SkillServer`。
17. 创建 Realtime agent / wakeword / conversation state machine。

因此：

- 不是先 watchdog 后 ctrl policy。
- watchdog 构造时会拿到 `combo_ctl`、`scene_bus`、`robot_bus`、`fsm`、`supervisor`。
- controller policy 先启动，watchdog 再根据 robot state / lowstate / pose / frame age 做监控和状态切换。

---

## 14. va-demo 变化

### 14.1 `requirements.txt`

新增：

```text
python-dotenv>=1.0.0
```

### 14.2 `.env` 加载

`va-demo/va_demo/main.py` 现在会读取：

1. `~/.env`
2. `va-demo/.env`

这样 `OPENAI_API_KEY` 等可以放在 repo 外。

### 14.3 新增 `--mujoco-camera`

`va-demo` 新增命令行：

```bash
python -m va_demo.main --mujoco-camera
```

启用后不再从 teleimager / USB 拿画面，而是用 MuJoCo offscreen render 出 simulated G1 head camera。

### 14.4 DDS 初始化提前

以前 camera 先建，DDS 后建。现在如果不是 `--no-skills`，会先：

```python
ChannelFactoryInitialize(domain_id, interface)
```

再创建 MuJoCo camera。原因是 MuJoCoHeadCamera 构造时会订阅 `rt/lowstate`，DDS factory 未初始化时 subscriber 会绑定失败。

### 14.5 `mujoco_camera.py` 新增

新增 offscreen head-camera renderer：

- 默认 `MUJOCO_GL=egl`
- 如果 MJCF 没有 `head_camera`，会动态挂到 `torso_link`
- 默认 camera pose：

```python
attach_body = "torso_link"
attach_pos = (0.08, 0.0, 0.45)
attach_xyaxes = (0.0, -1.0, 0.0, 0.0, 0.0, 1.0)
attach_fovy = 60.0
```

- 订阅：
  - `rt/lowstate`
  - `rt/sportmodestate`
- 同步 qpos 后渲染 RGB / depth。

### 14.6 `skills.py` path discovery 改进

`main` 只找：

```text
~/unitree/unitree-notes/g1_sim_demo
```

`23_dof` 改成多候选：

```python
repo sibling g1_sim_demo
~/unitree/unitree-notes/g1_sim_demo
~/unitree-notes/g1_sim_demo
```

这对不同机器上的 clone layout 更稳。

---

## 15. 重要风险 / 不一致点

### 15.1 g1_brain head camera 仍默认 29DOF scene

如前所述，`g1_brain.yaml` 和 `cameras.py` fallback 仍默认 29DOF terrain。若运行完整 brain，请改成 23DOF scene。

### 15.2 repo 路径混用

分支多数地方改成：

```text
~/unitree-notes
```

但部分脚本仍出现：

```text
~/unitree/unitree-notes
```

建议建立软链接：

```bash
# 如果你的真实仓库在 ~/unitree-notes
mkdir -p ~/unitree
ln -sfn ~/unitree-notes ~/unitree/unitree-notes
```

或者反过来：

```bash
# 如果你的真实仓库在 ~/unitree/unitree-notes
ln -sfn ~/unitree/unitree-notes ~/unitree-notes
```

这样两种路径都能工作。

### 15.3 `g1_sim_rl_walk.py` 不如 `g1_sim_rl_combo.py` 稳妥

因为 `walk.py` 仍依赖 `unitree_rl_mjlab/deploy/robots/g1_23dof/...`；而 `combo.py` 使用 branch 内置 `g1_sim_demo/policy`。测试 `23_dof` 首选 combo。

### 15.4 `g1_sim_interactive.py` 没有 23→29 slot mapping

它直接写 0..22 slots。低层 demo 可以参考，但不是 23DOF policy 测试主入口。

### 15.5 mimic 脚本是 29DOF

`g1_sim_rl_mimic.py` 很有价值，但不是 23DOF policy test。不要把 mimic pass/fail 当作 23DOF velocity policy 的结果。

### 15.6 training env 里曾有绝对路径痕迹

导出的 `g1_sim_demo/policy/params/env.yaml` 中的 `arm_ref.gesture_file` 可能包含训练机路径，例如：

```text
/home/capstone-cs47-2/unitree-notes/...
```

这对已经导出的 ONNX 普通运行通常不重要；但如果你要继续训练 / 重新导出，请改成你本机路径或使用 `make_gestures_npz.py` 重新生成。

---

# 16. 如何启动 `23_dof` 分支进行测试

下面分两类：

1. **最小直接 policy/controller 测试**：MuJoCo + `g1_sim_rl_combo.py`。这是我建议你首先做的。
2. **完整 g1_brain / watchdog / SkillServer 测试**：MuJoCo + `agent_main.py`。这是要测试安全监督、watchdog、vision、LLM tools 时用的。

---

## 16.1 准备环境

假设你的仓库在：

```bash
~/unitree-notes
```

执行：

```bash
cd ~/unitree-notes
git fetch origin
git checkout 23_dof
```

建议加兼容软链接：

```bash
mkdir -p ~/unitree
ln -sfn ~/unitree-notes ~/unitree/unitree-notes
```

激活环境。代码里不同文件注释有 `conda activate unitree` 和 `source ~/unitree_sdk2_python/unitree-env/bin/activate` 两种写法；用你机器上实际可用的那个。例如：

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
```

或：

```bash
conda activate unitree
```

检查关键依赖：

```bash
python - <<'PY'
import numpy, yaml
print('numpy/yaml ok')
try:
    import onnxruntime
    print('onnxruntime ok')
except Exception as e:
    print('onnxruntime missing:', e)
PY
```

如果缺：

```bash
pip install onnxruntime pyyaml numpy
pip install -r va-demo/requirements.txt
```

如果要跑 `g1_brain` / `va-demo`，还需要 OpenAI key：

```bash
export OPENAI_API_KEY='sk-...'
```

或者放到：

```bash
~/.env
```

---

## 16.2 最推荐的最小测试：MuJoCo + `g1_sim_rl_combo.py`

### Terminal 1：启动 MuJoCo

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/unitree_mujoco/simulate_python
export MUJOCO_GL=glfw
python unitree_mujoco.py
```

确认 `simulate_python/config.py` 中：

```python
ROBOT = "g1"
USE_TERRAIN = True
ROBOT_SCENE = "../unitree_robots/g1/scene_23dof_terrain.xml"
DOMAIN_ID = 1
INTERFACE = "lo"
ENABLE_ELASTIC_BAND = True
ELASTIC_BAND_INIT_LENGTH = 0.0
```

MuJoCo viewer 操作建议：

| 键 | 用途 |
|---|---|
| `7` | shorten band / lift robot |
| `8` | lengthen band / lower robot |
| `9` | disable band |

**建议流程**：

1. 启动 MuJoCo 后先不要立刻按 `9` 关弹性带。
2. 让机器人保持被 band 托住 / 接近默认姿态。
3. 先启动 controller，让 policy engage。
4. 看到 controller 端打印 policy engaged 后，再在 viewer 里按 `8` 逐步下放。
5. 脚接触地面并且站稳后，再按 `9` 禁用 band。

原因：当前代码注释明确指出，default_q + PD 不是可靠静态站立方案；policy 才是站稳的主要来源。所以不要让机器人在地上长期只靠 MuJoCo bridge 的 default hold PD。

### Terminal 2：启动 23DOF combo controller / ctrl policy

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
```

你应该看到类似：

```text
[combo] simulator mode on lo (domain 1).
[combo] loaded deploy.yaml (... num_motors=23, arm_start=13)
[combo] loaded policy: .../g1_sim_demo/policy/policy.onnx (obs_dim=..., act_dim=23)
[combo] gesture library: ... gestures loaded from gestures_23dof.npz
[combo] waiting for first /rt/lowstate ...
[combo] mode_machine=... Ramping to default pose over 5.0 s ...
[combo] policy engaged. wsadqe to walk; 1-8 arm gestures; 0 release.
```

看到 `policy engaged` 后，再开始在 MuJoCo viewer 里慢慢下放 band。

### 手动测试顺序

建议按这个顺序测试：

#### A. 静止站立

不要按任何 walk key，观察 10–20 秒。

期望：

- 机器人不应几秒内塌掉。
- 如果 band 还没完全关闭，先降低 band；完全站稳后按 `9`。

#### B. 小速度走路

在 controller terminal 按：

```text
w
```

它会把 `vx` 增加 0.2 m/s。

然后按：

```text
r
```

回到 `cmd=0`。

#### C. 站立手势

依次测试：

```text
1 wave_right
2 wave_left
3 hands_up
4 t_pose
5 salute
6 clap
7 guard
8 punch_combo
0 release arms
```

每个 gesture 后等几秒再测下一个。

重点观察：

- `hands_up`、`t_pose` 这类大动作是否能站稳。
- 手势结束后是否能回到 arm rest。
- gz / 姿态是否出现明显 tipping。

#### D. 走路 + 手势

先按：

```text
w
```

再在走路过程中按 `1-8`。

根据 baseline 文档，旧 velocity policy 在 walk_slow + gesture 已经能通过；现在 23DOF arm-disturbance policy 应该也应通过。

#### E. yaw / strafe

```text
a / d  # 左右平移
q / e  # yaw
r      # stop
```

#### F. 退出

```text
x
```

它会 soft settle 后退出。

不要用 `space` 除非你故意测试 soft-disable；`space` 会把 Kp/Kd soft-disable，机器人会塌。

---

## 16.3 自动 baseline 测试

只开 MuJoCo，不要另开 combo。

### Terminal 1

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/unitree_mujoco/simulate_python
export MUJOCO_GL=glfw
python unitree_mujoco.py
```

### Terminal 2

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/g1_sim_demo
python g1_sim_baseline_runner.py \
  --speeds stand,stand_yaw,walk_slow \
  --report /tmp/baseline_23dof.md
```

如果 runner 有 prompt，按提示操作 band。它会自己启动 ComboController，不要再运行 `g1_sim_rl_combo.py`。

输出看：

```bash
cat /tmp/baseline_23dof.md
```

---

## 16.4 完整 g1_brain / watchdog / SkillServer 测试

如果你说的“watchdog”是 `g1_brain` 的安全 watchdog，那么它是在 `agent_main.py` 里创建的，不需要单独启动一个 `watchdog.py`。

### 正确理解顺序

外部进程层面：

```text
Terminal 1: MuJoCo simulator
Terminal 2: g1_brain.apps.agent_main
```

`agent_main` 内部顺序大致是：

```text
DDS init
CameraHub
ComboProxy / ComboController start
wait policy_active
RobotStateBus / SceneStateBus
FSM -> STANDING
SafetySupervisor
WatchdogManager.start()
PerceptionRunner
SkillServer
Realtime / wakeword
```

所以不是：

```text
MuJoCo -> watchdog -> ctrl policy
```

而是：

```text
MuJoCo -> agent_main
agent_main 内部：先加载 / 启动 ctrl policy，再启动 watchdog
```

### 先修正 23DOF MJCF path

因为当前 `g1_brain.yaml` 仍指向 29DOF terrain，建议建一个临时 23DOF config：

```bash
cp ~/unitree-notes/g1_brain/configs/g1_brain.yaml /tmp/g1_brain_23dof.yaml
python - <<'PY'
from pathlib import Path
p = Path('/tmp/g1_brain_23dof.yaml')
s = p.read_text()
s = s.replace(
    '${HOME}/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof_terrain.xml',
    '${HOME}/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_23dof_terrain.xml',
)
p.write_text(s)
print(p)
PY
```

如果你不想启动 perception，或者只想测试 controller + watchdog，可以加 `--no-perception`。

### Terminal 1：MuJoCo

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/unitree_mujoco/simulate_python
export MUJOCO_GL=glfw
python unitree_mujoco.py
```

保持 band，不要过早按 `9`。

### Terminal 2：agent_main，带 watchdog / SkillServer

基础无 Realtime 测试：

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes
export OPENAI_API_KEY='sk-...'
python -m g1_brain.apps.agent_main \
  --config /tmp/g1_brain_23dof.yaml \
  --mode active \
  --no-realtime \
  --no-perception \
  -v
```

说明：

- `--no-realtime`：不连 Realtime，agent idle，但会初始化 audio、DDS、controller、FSM、SafetySupervisor、WatchdogManager、SkillServer 等。
- `--no-perception`：跳过 perception，避免 GPU/YOLO/MediaPipe 压力；同时 SafetySupervisor 会知道你显式关闭视觉路径检查。
- 代码顶部仍要求 `OPENAI_API_KEY`，即使 `--no-realtime`，因为 TTS / vision client 构造也需要 OpenAI client。因此最好仍 export。

如果你要测试完整语音 / vision / skill call：

```bash
python -m g1_brain.apps.agent_main \
  --config /tmp/g1_brain_23dof.yaml \
  --mode active \
  -v
```

如果要关闭 wakeword，让 mic 连续进入 Realtime：

```bash
python -m g1_brain.apps.agent_main \
  --config /tmp/g1_brain_23dof.yaml \
  --mode active \
  --no-wakeword \
  -v
```

### agent_main 启动时应关注的日志

你应该看到：

```text
DDS initialized: domain=1 iface=lo
spawning combo subprocess ... waiting for first /rt/lowstate
waiting for ComboController policy_active ...
run_mode=active
vision_gate enabled ...
realtime disabled; idling. Ctrl-C to exit.
```

如果它卡在：

```text
waiting for first /rt/lowstate
```

说明 MuJoCo 没起来、domain/interface 不一致，或 DDS 没通。

如果它报：

```text
policy not active after 30s
```

说明 controller 没能正常 engage policy；检查 MuJoCo viewer 中机器人是否已经塌了，或者 band 是否过早关闭。

如果它启动后 FSM 在 `STANDING` 但 tool 被拒绝，可能是 policy_active 没稳定到 `ENGAGED`，或 watchdog/pose/head frame 检查不通过。

---

## 16.5 va-demo + MuJoCo head camera 测试

如果你只想测 va-demo 的视觉路径：

```bash
source ~/unitree_sdk2_python/unitree-env/bin/activate
cd ~/unitree-notes/va-demo
export OPENAI_API_KEY='sk-...'
export G1_MJCF_PATH=$HOME/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_23dof_terrain.xml
python -m va_demo.main --mujoco-camera --no-realtime
```

如果要让 va-demo 也控制机器人：

1. 先启动 MuJoCo。
2. 再运行：

```bash
python -m va_demo.main --mujoco-camera --mode active
```

但注意：va-demo 的 SkillBackend 会通过 `g1_sim_rl_combo.py` 构建 controller。如果你已经单独开了 `g1_sim_rl_combo.py`，不要再开 va-demo skills，否则会抢 `rt/lowcmd`。

---

## 17. 推荐测试路线

如果你今天只是想验证 `23_dof` branch 是否能跑：

1. **先跑最小直接测试**：

```text
MuJoCo -> g1_sim_rl_combo.py
```

2. 确认：

```text
policy.onnx loads
act_dim=23
gesture library loads
policy engaged
band 下放后能站住
w/r 能走停
1-8 能出手势
```

3. 再跑自动 baseline：

```text
MuJoCo -> g1_sim_baseline_runner.py
```

4. 最后才跑完整 brain/watchdog：

```text
MuJoCo -> g1_brain.apps.agent_main
```

不要一开始就把 MuJoCo、watchdog、controller、perception、Realtime、voice、vision 全部打开；这样出问题时很难判断是 DDS、policy、camera、watchdog、OpenAI、audio 还是 scene mismatch。

---

## 18. 一句话回答你的启动顺序问题

你之前的“三步”如果是：

```text
1. 打开 MuJoCo
2. 打开 watchdog
3. 加载 ctrl policy
```

按当前 `23_dof` 代码，应改成：

### 直接 policy 测试

```text
1. 打开 MuJoCo
2. 打开 g1_sim_rl_combo.py，让 ctrl policy 接管
3. 不需要单独 watchdog
```

### 完整 brain / watchdog 测试

```text
1. 打开 MuJoCo
2. 打开 g1_brain.apps.agent_main
3. agent_main 内部会先启动 ComboProxy/ComboController 加载 ctrl policy，再启动 SafetySupervisor/WatchdogManager
```

也就是说：**不要把 watchdog 放在 ctrl policy 前面作为一个独立必跑步骤；至少在当前代码结构里，watchdog 是 agent_main 内部的 safety subsystem，依赖 controller / robot state / FSM。**

---

## 19. 最终建议

- 用 `g1_sim_rl_combo.py` 作为 23DOF policy 主测试入口。
- MuJoCo 启动后保持 elastic band，不要过早按 `9`。
- 让 policy engage 后再慢慢按 `8` 下放，站稳后再按 `9`。
- 完整 brain 测试前，把 `g1_brain.yaml` 的 `robot.mjcf_path` 改成 `scene_23dof_terrain.xml`。
- 不要同时运行多个会写 `rt/lowcmd` 的程序，例如 `g1_sim_rl_combo.py` + `agent_main.py` + `va-demo` skills。
- 如果只想测 watchdog，不要另找独立 watchdog 命令；运行 `agent_main --no-realtime --no-perception -v` 更接近当前代码设计。

