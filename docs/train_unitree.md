# train_unitree.md

> 日期：2026-05-20  
> 主题：Unitree G1 稳定动作训练、RL / RF（Reward Function）笔记、功夫类动作 demo 路线  
> 目标：训练一套稳定动作，例如“打一套功夫”，而不是只播放一段容易摔倒的关节轨迹。

---

## 0. 结论

如果目标是让 **Unitree G1 打一套功夫 / 跳舞 / 高动态全身动作**，最推荐的路线不是“手写关节角轨迹直接播放”，而是：

```text
动作数据采集 / 生成
→ 人体动作处理
→ retarget 到 G1
→ 运动质量检查
→ motion imitation / whole-body tracking RL
→ domain randomization
→ IsaacGym / IsaacLab / MuJoCo 中训练
→ play / evaluation
→ MuJoCo sim2sim
→ 吊装、debug mode、安全限幅下 sim2real
```

核心点：

1. **需要 RL**，主流是 PPO / RSL-RL / IsaacGym / IsaacLab / MuJoCo 系。
2. **需要 Reward Function（RF）**，但通常不是训练一个神经网络 reward model，而是手写/配置一组奖励项和惩罚项。
3. 对功夫这类动作，最重要的不是单纯关节角像不像，而是：
   - root / torso / anchor 稳定；
   - 身体各 link 位置和朝向跟踪；
   - 身体线速度、角速度跟踪；
   - 足底接触、脚滑、非期望接触；
   - action rate、torque、joint acceleration、关节限位；
   - domain randomization 和外力扰动。
4. 真机 demo 必须先过 **sim2sim**。仿真中都不稳，真机上只会更危险。
5. 如果要“功夫”，目前最接近的公开项目是 **KungfuBot / PBHC**，它就是高动态 G1 功夫/舞蹈/踢腿动作的 RL motion tracking 项目。

---

## 1. “RF”在这里怎么理解

你提到的 **RF** 我按两层理解：

### 1.1 Reward Function

在 Unitree G1 RL 训练里，RF 通常指奖励函数配置：

```text
总 reward =
  动作跟踪 reward
+ 姿态稳定 reward
+ 生存/episode reward
- 力矩/能耗 penalty
- action rate penalty
- 关节速度/加速度 penalty
- 关节限位 penalty
- 脚滑 / 错误接触 penalty
- 摔倒 / 提前终止 penalty
```

这不是 “reward model”。你一般不需要从人类偏好训练一个神经网络奖励模型，而是自己定义 reward terms 和 weights。

### 1.2 Reinforcement Learning

真正训练稳定动作时，通常是 RL：

```text
policy observation -> neural network -> action -> PD target / residual target -> simulator -> reward -> PPO update
```

G1 的稳定性来自闭环 policy，而不是开环播放轨迹。

---

## 2. 我查到的核心仓库

### 2.1 `unitreerobotics/unitree_rl_mjlab`

仓库：`https://github.com/unitreerobotics/unitree_rl_mjlab`

定位：

- Unitree 官方 MuJoCo / mjlab 强化学习仓库。
- 支持 Go2、A2、As2、G1、R1、H1_2、H2。
- 官方流程是：

```text
Train → Play → Sim2Real
```

官方 G1 速度跟踪训练命令：

```bash
python scripts/train.py Unitree-G1-Flat --env.scene.num-envs=4096
```

官方 G1 动作模仿训练流程：

```bash
python scripts/csv_to_npz.py \
  --input-file src/assets/motions/g1/dance1_subject2.csv \
  --output-name dance1_subject2.npz \
  --input-fps 30 \
  --output-fps 50 \
  --robot g1
```

```bash
python scripts/train.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/dance1_subject2.npz \
  --env.scene.num-envs=4096
```

这个仓库对你最直接，因为它已经把 **G1 motion imitation** 写进 README 了。  
如果你要训练“功夫”，可以把功夫动作 retarget 成 G1 CSV / NPZ，然后用 tracking 任务训练。

---

### 2.2 `unitreerobotics/unitree_rl_lab`

仓库：`https://github.com/unitreerobotics/unitree_rl_lab`

定位：

- Unitree 官方 IsaacLab 强化学习仓库。
- 支持 Unitree Go2、H1、G1-29dof。
- 用 RSL-RL / PPO。
- 包含 G1-29dof velocity 和 mimic / dance 风格部署配置。

官方 G1-29dof 训练命令：

```bash
./unitree_rl_lab.sh -t --task Unitree-G1-29dof-Velocity
```

等价：

```bash
python scripts/rsl_rl/train.py --headless --task Unitree-G1-29dof-Velocity
```

play 命令：

```bash
./unitree_rl_lab.sh -p --task Unitree-G1-29dof-Velocity
```

等价：

```bash
python scripts/rsl_rl/play.py --task Unitree-G1-29dof-Velocity
```

部署流程：

```text
训练完成
→ MuJoCo sim2sim
→ 实机 sim2real
```

其中 G1-29dof 部署配置里已经有：

```text
Velocity
Mimic_Dance_102
Mimic_Gangnam_Style
```

这说明官方仓库已经把 G1-29dof 的 velocity policy 和 mimic dance policy 放进状态机思路里了。

---

### 2.3 `unitreerobotics/unitree_rl_gym`

仓库：`https://github.com/unitreerobotics/unitree_rl_gym`

定位：

- Unitree 官方较早期 IsaacGym / legged_gym 风格仓库。
- 对理解 reward 很有用。
- G1 旧配置是 12 dof 版本，不完全等于你现在的 29 dof 全身动作，但 reward 结构非常典型。

G1 rough config 中典型设置：

```text
domain randomization:
  randomize_friction = True
  randomize_base_mass = True
  push_robots = True

control:
  control_type = P
  action_scale = 0.25
  decimation = 4

rewards:
  tracking_lin_vel = 1.0
  tracking_ang_vel = 0.5
  lin_vel_z = -2.0
  ang_vel_xy = -0.05
  orientation = -1.0
  base_height = -10.0
  dof_acc = -2.5e-7
  dof_vel = -1e-3
  action_rate = -0.01
  dof_pos_limits = -5.0
  alive = 0.15
```

这类配置适合理解“稳定走路”的 RF，但功夫动作最好看 motion imitation 仓库。

---

### 2.4 `unitreerobotics/unitree_mujoco`

仓库：`https://github.com/unitreerobotics/unitree_mujoco`

定位：

- 真机前的 sim2sim / deployment bridge。
- 用 MuJoCo + Unitree SDK2 模拟低层通信。
- 你训练好的策略不应该直接上真机，应该先进 `unitree_mujoco` 测。

对人形机器人尤其重要：

```text
策略训练仿真器中稳定
≠ MuJoCo 中稳定
≠ 真机中稳定
```

至少要做到：

```text
IsaacGym / IsaacLab / Mjlab 中稳定
→ MuJoCo sim2sim 稳定
→ 吊装 / debug mode / 限速 / 限力矩下实机测试
```

---

### 2.5 `TeleHuman/PBHC`：KungfuBot 官方实现

仓库：`https://github.com/TeleHuman/PBHC`

项目页：`https://kungfu-bot.github.io/`

这是目前和你“打一套功夫”目标最贴近的仓库。项目说明它是：

```text
KungfuBot: Physics-Based Humanoid Whole-Body Control for Learning Highly-Dynamic Skills
```

它支持：

- jump kick
- roundhouse kick
- side kick
- front kick
- back kick
- 360-degree spin
- dance
- Bruce Lee pose
- fighting combo
- horse stance punch
- hooks punch
- jabs punch
- horse stance pose
- stretch leg
- Tai Chi

它的流程：

```text
motion_source/
  从视频、LAFAN、AMASS 等来源获得人体动作，统一到 SMPL

smpl_retarget/
  把人体动作 retarget 到 G1

smpl_vis/ 和 robot_motion_process/
  可视化、插值、分析动作质量

humanoidverse/
  用 IsaacGym 训练 RL motion imitation policy

MuJoCo deployment
  sim2sim 验证
```

PBHC 训练命令示例：

```bash
python humanoidverse/train_agent.py \
+simulator=isaacgym +exp=motion_tracking +terrain=terrain_locomotion_plane \
project_name=MotionTracking num_envs=128 \
+obs=motion_tracking/main \
+robot=g1/g1_23dof_lock_wrist \
+domain_rand=main \
+rewards=motion_tracking/main \
experiment_name=debug \
robot.motion.motion_file="example/motion_data/Horse-stance_pose.pkl" \
seed=1 \
+device=cuda:0
```

论文实验中使用：

```text
num_envs = 4096
iterations = 50000
```

调试时可以：

```text
num_envs = 128
```

PBHC 的一般 motion policy 训练也有 teacher / student 结构：

```bash
# teacher
python humanoidverse/train_agent.py \
+simulator=isaacgym +exp=general_tracking +terrain=terrain_locomotion_plane \
project_name=MotionTracking num_envs=128 \
+obs=motion_tracking/obs_ppo_teacher \
+robot=g1/g1_23dof_general \
+domain_rand=main \
+rewards=motion_tracking/general_main \
experiment_name=debug-teacher \
robot.motion.motion_file="<path to your motion data>" \
seed=1 \
+device=cuda:0
```

```bash
# student
python humanoidverse/train_agent.py \
+simulator=isaacgym +exp=general_tracking +terrain=terrain_locomotion_plane \
project_name=MotionTracking num_envs=128 \
+obs=motion_tracking/obs_ppo_student \
+robot=g1/g1_23dof_general \
+domain_rand=main \
+rewards=motion_tracking/general_main \
experiment_name=debug-student \
robot.motion.motion_file="<path to your motion data>" \
algo.config.dagger_only=True \
algo.config.teacher_model_path="<path to your teacher ckpt>" \
seed=1 \
+device=cuda:0
```

这个项目是我建议重点复现的“功夫动作”路线。

---

### 2.6 `HybridRobotics/whole_body_tracking`

仓库：`https://github.com/HybridRobotics/whole_body_tracking`

定位：

- BeyondMimic motion tracking code。
- Unitree 官方 `unitree_rl_mjlab` 也在 README 中引用它。
- 适合学习通用 humanoid motion tracking 的 MDP 结构。

它强调：

```text
reference motion 应该 retargeted
应该使用 generalized coordinates
rewards.py 实现 DeepMimic reward functions 和 smoothing terms
events.py 实现 domain randomization
terminations.py 实现 early termination
```

训练命令示例：

```bash
python scripts/rsl_rl/train.py --task=Tracking-Flat-G1-v0 \
  --registry_name {your-organization}-org/wandb-registry-motions/{motion_name} \
  --headless --logger wandb --log_project_name {project_name} --run_name {run_name}
```

---

### 2.7 `leggedrobotics/rsl_rl`

仓库：`https://github.com/leggedrobotics/rsl_rl`

定位：

- 机器人 RL 里常用的轻量 PPO / student-teacher distillation 库。
- Unitree 官方仓库和 PBHC 都使用或引用 RSL-RL。
- 你不一定要改它，通常改环境、reward、obs、action 和 domain randomization。

---

## 3. Unitree G1 的稳定动作训练，本质上在训练什么？

### 3.1 不推荐：开环播放轨迹

不稳定写法大概是：

```python
for t in range(T):
    send_joint_position(q_ref[t])
```

问题：

- 当前机器人姿态偏了，它还会继续播放下一帧；
- 脚底接触和仿真不同；
- 腿部力矩、摩擦、IMU、延迟和模型不同；
- 没有根据实际状态修正；
- 踢腿、转身、下蹲、马步时 COM 很容易出支撑多边形。

### 3.2 推荐：闭环 motion tracking policy

训练后运行时应该像这样：

```text
observation:
  motion command / motion phase / reference motion features
  anchor orientation
  base angular velocity
  joint position
  joint velocity
  last action
  sometimes projected gravity / previous frames

policy:
  neural network

action:
  joint position target / residual joint target

low-level controller:
  PD control or implicit actuator
```

最终策略每一帧都会根据当前状态修正动作。

---

## 4. Unitree G1 velocity RF 笔记

来自 `unitree_rl_lab` 的 G1-29dof velocity 环境。

### 4.1 observation

policy observation 包含：

| 项 | 含义 |
|---|---|
| `base_ang_vel` | base 角速度 |
| `projected_gravity` | 重力在机体系投影，反映姿态 |
| `velocity_commands` | 目标速度命令 |
| `joint_pos_rel` | 相对默认姿态的关节位置 |
| `joint_vel_rel` | 关节速度 |
| `last_action` | 上一帧动作 |
| `history_length = 5` | 堆叠历史帧 |
| `enable_corruption = True` | 加 observation noise，提高鲁棒性 |

critic 有 privileged observation，例如 base linear velocity。

### 4.2 action

```text
JointPositionAction
scale = 0.25
use_default_offset = True
```

也就是 policy 输出不是直接 torque，而是关节目标角偏移：

```text
q_des = q_default + scale * action
```

### 4.3 domain randomization / events

| 随机化项 | 配置含义 |
|---|---|
| friction | static/dynamic friction 随机 |
| base mass | torso mass 加随机扰动 |
| reset root pose | x/y/yaw 初始随机 |
| reset joint velocity | 关节速度随机 |
| push_robot | 每 5 秒设置随机 xy velocity |

这就是“训练时故意把世界变难”，让策略学会稳。

### 4.4 reward terms

| reward term | weight | 作用 |
|---|---:|---|
| `track_lin_vel_xy` | `+1.0` | 跟踪 xy 线速度 |
| `track_ang_vel_z` | `+0.5` | 跟踪 yaw 角速度 |
| `alive` | `+0.15` | 存活奖励 |
| `base_linear_velocity` | `-2.0` | 惩罚 z 方向速度 |
| `base_angular_velocity` | `-0.05` | 惩罚 roll/pitch 角速度 |
| `joint_vel` | `-0.001` | 惩罚关节速度 |
| `joint_acc` | `-2.5e-7` | 惩罚关节加速度 |
| `action_rate` | `-0.05` | 惩罚动作突变 |
| `dof_pos_limits` | `-5.0` | 惩罚接近/超过关节限位 |
| `energy` | `-2e-5` | 惩罚能量消耗 |
| `joint_deviation_arms` | `-0.1` | 手臂偏离默认姿态 |
| `joint_deviation_waists` | `-1.0` | 腰部偏离默认姿态 |
| `joint_deviation_legs` | `-1.0` | hip roll/yaw 偏离 |
| `flat_orientation_l2` | `-5.0` | 保持身体姿态平 |
| `base_height` | `-10.0` | 保持目标高度 0.78 |
| `gait` | `+0.5` | 鼓励步态相位 |
| `feet_slide` | `-0.2` | 惩罚脚滑 |
| `feet_clearance` | `+1.0` | 鼓励足部抬脚高度 |
| `undesired_contacts` | `-1.0` | 惩罚非脚部接触 |

### 4.5 termination

| termination | 条件 |
|---|---|
| `time_out` | episode 到时 |
| `base_height` | root height 低于 0.2 |
| `bad_orientation` | 姿态角超过限制 |

---

## 5. Unitree G1 motion imitation RF 笔记

来自 `unitree_rl_lab` mimic / dance 任务。

### 5.1 command

motion command 包含：

| 项 | 含义 |
|---|---|
| `motion_file` | 参考动作 NPZ |
| `anchor_body_name = torso_link` | 用躯干作为 anchor |
| `pose_range` | 初始 pose 随机扰动 |
| `velocity_range` | 初始速度扰动 |
| `joint_position_range` | 初始关节扰动 |
| `body_names` | 参与跟踪的关键 body links |

G1 dance 任务跟踪的 body 包括：

```text
pelvis
left_hip_roll_link
left_knee_link
left_ankle_roll_link
right_hip_roll_link
right_knee_link
right_ankle_roll_link
torso_link
left_shoulder_roll_link
left_elbow_link
left_wrist_yaw_link
right_shoulder_roll_link
right_elbow_link
right_wrist_yaw_link
```

这个列表非常重要：它不是只跟踪关节角，而是跟踪身体关键 link 的位置和朝向。

### 5.2 policy observation

| 项 | 含义 |
|---|---|
| `motion_command` | 当前参考动作命令 |
| `motion_anchor_ori_b` | anchor 在 body frame 的朝向 |
| `base_ang_vel` | 当前 base 角速度 |
| `joint_pos_rel` | 当前关节位置 |
| `joint_vel_rel` | 当前关节速度 |
| `last_action` | 上一帧动作 |

并且启用 observation corruption。

### 5.3 critic privileged observation

critic 能看到更多信息：

| 项 | 含义 |
|---|---|
| command | 完整 motion command |
| motion anchor pos/ori | 参考 anchor 位置/朝向 |
| body pos/ori | 当前 body link 状态 |
| base lin/ang vel | base 线速度/角速度 |
| joint pos/vel | 关节状态 |
| last action | 上一帧动作 |

这是典型 asymmetric actor-critic：actor 部署时只看能用的观测，critic 训练时能看更多信息。

### 5.4 mimic reward terms

| reward term | weight | 作用 |
|---|---:|---|
| `joint_acc` | `-2.5e-7` | 惩罚关节加速度 |
| `joint_torque` | `-1e-5` | 惩罚力矩 |
| `action_rate_l2` | `-0.1` | 强烈惩罚动作突变 |
| `joint_limit` | `-10.0` | 强烈惩罚关节限位 |
| `motion_global_anchor_pos` | `+0.5` | root/torso anchor 全局位置跟踪 |
| `motion_global_anchor_ori` | `+0.5` | root/torso anchor 朝向跟踪 |
| `motion_body_pos` | `+1.0` | 身体各 link 相对位置跟踪 |
| `motion_body_ori` | `+1.0` | 身体各 link 朝向跟踪 |
| `motion_body_lin_vel` | `+1.0` | 身体各 link 线速度跟踪 |
| `motion_body_ang_vel` | `+1.0` | 身体各 link 角速度跟踪 |
| `undesired_contacts` | `-0.1` | 非期望接触惩罚 |

### 5.5 mimic reward 公式结构

Unitree mimic reward 不是简单 L2，而是指数 reward：

```text
reward = exp(-error / std^2)
```

例如：

```text
anchor position:
  error = ||reference_anchor_pos - robot_anchor_pos||^2
  reward = exp(-error / std^2)

body position:
  error = mean over tracked bodies of ||reference_body_pos - robot_body_pos||^2
  reward = exp(-error / std^2)

body orientation:
  error = mean quaternion error^2
  reward = exp(-error / std^2)
```

这类 reward 的好处：

- error 小时给高 reward；
- error 大时 reward 接近 0；
- `std` 控制容忍度；
- 适合 motion tracking。

### 5.6 termination

mimic 任务终止项：

| termination | 条件 |
|---|---|
| `time_out` | 超时 |
| `anchor_pos` | anchor z 误差超过阈值 |
| `anchor_ori` | anchor orientation 误差过大 |
| `ee_body_pos` | ankle/wrist 等末端 body z 误差过大 |

这比单纯“摔倒终止”更严格，因为它会让策略不要偏离参考动作太远。

---

## 6. PBHC / KungfuBot RF 笔记

PBHC 是功夫动作最相关的项目。

### 6.1 motion tracking reward

PBHC `motion_tracking/main.yaml` 中有这些 reward scales：

| reward | weight | 解释 |
|---|---:|---|
| `teleop_contact_mask` | `+0.5` | 接触模式匹配 |
| `teleop_max_joint_position` | `+1.0` | 最大关节位置跟踪 |
| `teleop_body_position_extend` | `+1.0` | 身体扩展位置跟踪 |
| `teleop_vr_3point` | `+1.6` | 三点关键位姿跟踪 |
| `teleop_body_position_feet` | `+1.5` | 足部位置跟踪 |
| `teleop_body_rotation_extend` | `+0.5` | 身体朝向跟踪 |
| `teleop_body_ang_velocity_extend` | `+0.5` | 身体角速度跟踪 |
| `teleop_body_velocity_extend` | `+0.5` | 身体线速度跟踪 |
| `teleop_joint_position` | `+1.0` | 关节位置跟踪 |
| `teleop_joint_velocity` | `+1.0` | 关节速度跟踪 |
| `penalty_torques` | `-0.000001` | 力矩惩罚 |
| `penalty_action_rate` | `-0.5` | 实机需要更强 action smoothness |
| `feet_air_time` | `+1.0` | 足部离地时间 |
| `penalty_feet_contact_forces` | `-0.01` | 过大足端接触力 |
| `penalty_stumble` | `-2.0` | 绊脚 |
| `penalty_slippage` | `-1.0` | 脚滑 |
| `limits_dof_pos` | `-10.0` | 关节位置限位 |
| `limits_dof_vel` | `-5.0` | 关节速度限位 |
| `limits_torque` | `-5.0` | 力矩限位 |
| `termination` | `-200.0` | 提前终止 |
| `collision` | `-30.0` | 碰撞 |

特别注意：

```text
penalty_action_rate = -0.5
```

PBHC 直接注释说 real robot 需要 tune 到 -0.5。  
这说明功夫动作想上真机，动作平滑非常关键。

### 6.2 PBHC tracking sigma

PBHC 使用不同 tracking sigma 控制容忍度：

| sigma | 值 |
|---|---:|
| `teleop_upper_body_pos` | `0.015` |
| `teleop_lower_body_pos` | `0.015` |
| `teleop_vr_3point_pos` | `0.015` |
| `teleop_feet_pos` | `0.01` |
| `teleop_body_rot` | `0.1` |
| `teleop_body_vel` | `1.0` |
| `teleop_body_ang_vel` | `15.0` |
| `teleop_joint_pos` | `0.3` |
| `teleop_joint_vel` | `30.0` |

直觉：

- 足部和身体位置 sigma 很小，说明位置跟踪很严格；
- 速度类 sigma 较大，说明速度误差容忍更大；
- high dynamic 动作不能每个维度都过于严格，否则训练容易崩。

### 6.3 adaptive tracking sigma

PBHC 有：

```yaml
adaptive_tracking_sigma:
  enable: True
  alpha: 1e-3
  type: origin
  scale: 1.0
```

这对应 KungfuBot 论文中的 adaptive motion tracking 思想：  
高动态动作难度不同，固定 tracking tolerance 可能不适合所有阶段，训练时动态调 tracking 容忍度可以更稳定。

### 6.4 reward penalty curriculum

PBHC 有 penalty curriculum：

```text
reward_penalty_curriculum = True
reward_initial_penalty_scale = 0.10
reward_min_penalty_scale = 0.0
reward_max_penalty_scale = 1.0
reward_penalty_level_down_threshold = 40
reward_penalty_level_up_threshold = 42
```

直觉：

- 初期不要让 torque/action_rate/limit 等 penalty 太强，否则 policy 连动作都学不会；
- 等动作跟踪学起来，再逐步增强安全、平滑、限位惩罚；
- 这是训练功夫动作非常实用的技巧。

### 6.5 PBHC general motion reward

`general_main.yaml` 中 reward 更像通用 tracker：

| reward | weight |
|---|---:|
| `teleop_root_vel` | `+1.0` |
| `teleop_anchor_body_position` | `+1.5` |
| `teleop_anchor_body_rotation` | `+1.5` |
| `local_key_body_position` | `+3.0` |
| `local_key_body_rotation` | `+2.0` |
| `key_body_velocity` | `+2.0` |
| `key_body_ang_velocity` | `+2.0` |
| `penalty_action_rate` | `-0.1` |
| `penalty_dof_vel` | `-0.0001` |
| `penalty_dof_acc` | `-3e-7` |
| `foot_slip_penalty` | `-0.1` |
| `limits_dof_pos` | `-10.0` |
| `limits_torque` | `-5.0` |
| `termination` | `-200.0` |
| `collision` | `-30.0` |

这里 key body tracking 权重很高：

```text
local_key_body_position = 3.0
local_key_body_rotation = 2.0
```

这说明对功夫这种全身动作，重点不是所有关节逐帧死跟，而是关键身体 link 的位置、朝向、速度要对。

### 6.6 PBHC domain randomization

PBHC `domain_rand/main.yaml` 中有：

| 项 | 配置 |
|---|---|
| `push_robots` | True |
| `push_interval_s` | `[5, 10]` |
| `max_push_vel_xy` | `0.1` |
| `randomize_base_com` | True |
| `base_com_range` | x/y/z 随机 |
| `randomize_link_mass` | True |
| `link_mass_range` | `[0.9, 1.1]` |
| `randomize_link_inertia` | True |
| `link_inertia_range` | `[0.9, 1.1]` |
| `randomize_pd_gain` | True |
| `kp_range` | `[0.9, 1.1]` |
| `kd_range` | `[0.9, 1.1]` |
| `randomize_friction` | True |
| `friction_range` | `[0.2, 1.2]` |
| `randomize_torque_rfi` | True |
| `randomize_ctrl_delay` | True |
| `ctrl_delay_step_range` | `[0, 2]` |

这对 sim2real 很关键。  
功夫动作不加 delay、PD gain、mass、COM、friction randomization，真机很容易崩。

---

## 7. 怎样训练一套稳定“功夫”动作

### 7.1 先定义动作类型

功夫动作可以分为三类：

| 类型 | 难度 | 建议路线 |
|---|---:|---|
| 原地上肢动作，例如抱拳、冲拳 | 低 | 可以 motion imitation，lower body 保守 |
| 原地马步、太极、慢速转身 | 中 | whole-body tracking RL |
| 高踢腿、旋风腿、跳踢、连招 | 高 | PBHC / KungfuBot 风格，多阶段处理 + adaptive tracking |

### 7.2 采集或生成动作

可选来源：

1. 真人视频；
2. mocap / BVH；
3. AMASS / LAFAN1；
4. 手工设计关键帧；
5. 从已有数据集中找 Tai Chi / kick / punch；
6. PBHC 示例动作。

如果从视频来，建议路线：

```text
video
→ human pose / SMPL extraction
→ filtering
→ contact correction
→ retarget to G1
→ visual check
→ robot motion processing
```

PBHC 已经有：

```text
motion_source/
smpl_retarget/
smpl_vis/
robot_motion_process/
```

### 7.3 retarget 到 G1

retarget 不是简单“人体关节角 = 机器人关节角”。

必须处理：

| 问题 | 处理 |
|---|---|
| 人体比例和 G1 不一样 | IK / retarget 优化 |
| 脚底穿地 | contact correction |
| 脚滑 | foot lock / contact mask |
| 重心太靠外 | 降低动作幅度 / root 修正 |
| high kick 超过 G1 关节限位 | clip / smooth / 改动作 |
| 手腕/手指不需要 | lock wrist 或降权 |
| 高跳/腾空动作 | 先不要真机，先分阶段 |

### 7.4 先做运动质量检查

在训练 RL 前先检查：

```text
1. 动作 replay 是否脚底穿地？
2. 单脚支撑时间是否太长？
3. COM 是否离支撑脚太远？
4. 膝盖、髋、踝是否超过 G1 限位？
5. root height 是否连续？
6. yaw/turn 是否过快？
7. 手臂大幅动作是否破坏躯干平衡？
8. 动作总时长是否太长？
```

如果参考动作本身不物理可行，RL 会非常难学，甚至学出奇怪补偿动作。

### 7.5 训练任务设计

对功夫 demo，我建议：

```text
第一阶段：单动作短片段
  例如马步冲拳 2-5 秒

第二阶段：慢速连招
  例如起势 → 马步 → 冲拳 → 收势

第三阶段：加入转身/踢腿
  先低幅度，后高幅度

第四阶段：长序列
  多个动作拼接，带 phase / command
```

不要一开始就训练 30 秒复杂连招。

### 7.6 推荐训练路线 A：Unitree RL Mjlab

适合你自己准备 CSV 动作。

```bash
git clone https://github.com/unitreerobotics/unitree_rl_mjlab.git
cd unitree_rl_mjlab
```

准备动作：

```bash
python scripts/csv_to_npz.py \
  --input-file src/assets/motions/g1/your_kungfu.csv \
  --output-name your_kungfu.npz \
  --input-fps 30 \
  --output-fps 50 \
  --robot g1
```

训练：

```bash
python scripts/train.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/your_kungfu.npz \
  --env.scene.num-envs=4096
```

验证：

```bash
python scripts/play.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/your_kungfu.npz \
  --checkpoint_file=logs/rsl_rl/g1_tracking/<date>/model_xx.pt
```

如果动作不稳，优先调：

```text
action_rate penalty ↑
joint_limit penalty ↑
undesired contact penalty ↑
torque penalty ↑
motion tracking std 放宽一点
reference motion 速度降低
动作幅度降低
随机 push 先小再大
```

### 7.7 推荐训练路线 B：PBHC / KungfuBot

适合你要“真的功夫动作”。

```bash
git clone https://github.com/TeleHuman/PBHC.git
```

建议先复现 horse stance pose：

```bash
python humanoidverse/train_agent.py \
+simulator=isaacgym +exp=motion_tracking +terrain=terrain_locomotion_plane \
project_name=MotionTracking num_envs=128 \
+obs=motion_tracking/main \
+robot=g1/g1_23dof_lock_wrist \
+domain_rand=main \
+rewards=motion_tracking/main \
experiment_name=debug \
robot.motion.motion_file="example/motion_data/Horse-stance_pose.pkl" \
seed=1 \
+device=cuda:0
```

调试没问题再上：

```text
num_envs = 4096
iterations = 50000
```

评估：

```bash
python humanoidverse/eval_agent.py \
+device=cuda:0 \
+env.config.enforce_randomize_motion_start_eval=False \
+checkpoint=<path_to_ckpt>
```

导出 ONNX 后 MuJoCo：

```bash
python humanoidverse/urci.py \
+opt=record \
+simulator=mujoco \
+checkpoint=<path_to_onnx>
```

### 7.8 推荐训练路线 C：Unitree RL Lab 自定义 mimic

适合你希望基于 Unitree 官方 IsaacLab/G1-29dof 代码继续改。

可以参考现有：

```text
source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/dance_102/tracking_env_cfg.py
source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/gangnanm_style/tracking_env_cfg.py
```

新增你的动作任务：

```text
source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/kungfu_combo/tracking_env_cfg.py
```

改：

```python
motion_file = "your_kungfu_motion.npz"
body_names = [...]
pose_range = {...}
velocity_range = {...}
reward weights = ...
termination thresholds = ...
```

然后注册任务，训练，play，sim2sim。

---

## 8. 功夫动作 reward function 模板

### 8.1 总 reward

```python
reward = 0.0

# A. 动作跟踪
reward += w_anchor_pos * exp(-anchor_pos_err / sigma_anchor_pos**2)
reward += w_anchor_ori * exp(-anchor_ori_err / sigma_anchor_ori**2)
reward += w_body_pos   * exp(-body_pos_err   / sigma_body_pos**2)
reward += w_body_ori   * exp(-body_ori_err   / sigma_body_ori**2)
reward += w_body_vel   * exp(-body_vel_err   / sigma_body_vel**2)
reward += w_body_ang   * exp(-body_ang_err   / sigma_body_ang**2)

# B. 接触与脚步
reward += w_contact_mask * contact_pattern_match
reward -= w_foot_slip    * foot_slip
reward -= w_stumble      * stumble
reward -= w_bad_contact  * undesired_contacts

# C. 平滑和能耗
reward -= w_action_rate  * ||a_t - a_{t-1}||^2
reward -= w_joint_acc    * ||qdd||^2
reward -= w_torque       * ||tau||^2
reward -= w_energy       * |tau * qd|

# D. 安全
reward -= w_joint_limit  * joint_limit_violation
reward -= w_vel_limit    * joint_velocity_limit_violation
reward -= w_torque_limit * torque_limit_violation

# E. 终止
if fall_or_bad_tracking:
    reward -= termination_penalty
```

### 8.2 推荐初始权重

如果你自己从零配一个功夫动作 RF，可以从这个方向开始：

| 类别 | 建议 |
|---|---|
| anchor pos/ori | 中等权重，防止躯干偏太远 |
| key body pos/ori | 高权重，保证动作像 |
| body velocity | 中等权重，保证动作节奏 |
| action rate | 一开始中等，后期增强 |
| torque | 小权重，后期增强 |
| joint limit | 高权重 |
| foot slip | 高权重 |
| collision | 高权重 |
| termination | 非常高惩罚 |

建议分阶段：

```text
初期：
  motion tracking 权重大
  penalty 小一点
  让 policy 先学会动作

中期：
  加强 action_rate / torque / limit
  加强 foot_slip / contact

后期：
  加强 domain randomization
  加强 sim2real 相关 penalty
```

---

## 9. 为什么功夫动作比走路难

### 9.1 支撑多边形变化剧烈

走路时通常是一脚或两脚支撑，动作比较规律。  
功夫里可能有：

```text
单脚高踢
快速转身
躯干大幅俯仰
双臂大幅摆动
重心快速横移
```

这会让 COM 很容易跑出支撑区域。

### 9.2 接触模式复杂

功夫动作中的脚掌可能需要：

```text
脚尖抬起
脚跟转动
快速落地
单脚支撑
短时间腾空
```

如果参考动作 contact 不准，就会学出脚滑或抖动。

### 9.3 真机延迟和 PD 差异会放大不稳定

仿真里动作很漂亮，真机中可能：

```text
手臂甩动导致 torso 晃
踢腿时支撑脚打滑
腰部 yaw 太快导致整机转倒
电机跟不上导致相位滞后
```

所以要加强：

```text
ctrl_delay randomization
PD gain randomization
friction randomization
COM randomization
mass / inertia randomization
action rate penalty
```

---

## 10. 常见不稳定问题与修复

### 10.1 一开始就摔

可能原因：

```text
初始姿态和 reference 第一帧差太大
reference root height 不合理
termination 太严格
tracking reward 太难
动作速度太快
```

修复：

```text
把动作前 1-2 秒改成稳定站立过渡
降低动作速度
放宽 tracking sigma
降低初始扰动
先关闭强 push
检查 retarget 是否穿地
```

### 10.2 脚滑

可能原因：

```text
contact mask 不对
foot position reward 太弱
friction randomization 太激进
参考动作脚底本身滑
```

修复：

```text
加 foot_slip penalty
加 contact mask reward
修正 retarget 后的脚底轨迹
先固定地面摩擦训练，再逐渐随机
```

### 10.3 动作很像，但身体不稳

可能原因：

```text
motion body reward 太强，稳定 reward 太弱
anchor / torso tracking 不合理
上肢动作破坏 COM
```

修复：

```text
加强 anchor orientation / base stability
降低手臂动作幅度
降低 upper-body tracking weight
提高 action rate penalty
提高 torque penalty
```

### 10.4 动作不抖但不像

可能原因：

```text
penalty 太强
tracking reward 太弱
动作被 policy 学成保守站立
```

修复：

```text
提高 key body position/rotation reward
降低 action_rate / torque penalty
使用 curriculum，先学动作后加平滑
```

### 10.5 仿真稳定，MuJoCo 不稳定

可能原因：

```text
训练仿真器和 MuJoCo 动力学差异
PD / action scale / joint order 不一致
摩擦、质量、关节限位不一致
```

修复：

```text
检查 joint_sdk_names 顺序
检查 policy observation 顺序
检查 action scale
检查 PD gain
检查单位和 fps
加强 domain randomization
```

### 10.6 MuJoCo 稳定，真机不稳定

可能原因：

```text
真机延迟
IMU 噪声
电机响应差异
地面摩擦不同
安全模式 / 底层控制状态不一致
```

修复：

```text
ctrl_delay randomization
PD gain randomization
降低动作幅度和速度
先吊装测试
增加 action_rate penalty
部署中加速度/力矩/位置限幅
```

---

## 11. 功夫动作训练 checklist

### 11.1 数据 checklist

- [ ] 动作文件能 replay。
- [ ] 没有明显穿地。
- [ ] 没有大范围脚滑。
- [ ] 关节角没有超过 G1 限位。
- [ ] root height 连续。
- [ ] 单脚支撑段不过长。
- [ ] 动作速度适合 G1 电机。
- [ ] 前 1-2 秒有稳定过渡。
- [ ] 结尾能回到稳定姿态或自然停止。

### 11.2 训练 checklist

- [ ] 先用 128 env debug。
- [ ] reward 每项都能正常计算。
- [ ] episode length 没有一开始就归零。
- [ ] action 不爆。
- [ ] torque 不爆。
- [ ] joint limit violation 不频繁。
- [ ] foot slip 逐步降低。
- [ ] motion tracking error 逐步降低。
- [ ] 再用 4096 env 大规模训练。
- [ ] 保存多个 checkpoint，不只看最后一个。

### 11.3 evaluation checklist

- [ ] Play 中连续跑完整动作。
- [ ] 多 seed 测试。
- [ ] 随机初始姿态测试。
- [ ] 随机摩擦测试。
- [ ] 小 push 测试。
- [ ] MuJoCo sim2sim 测试。
- [ ] ONNX 导出后测试。
- [ ] observation/action 顺序检查。
- [ ] 真机前吊装测试。

### 11.4 真机安全 checklist

- [ ] 实机吊装。
- [ ] 人远离机器人运动范围。
- [ ] 急停可用。
- [ ] debug mode。
- [ ] on-board control program 状态确认。
- [ ] 限制最大 joint velocity。
- [ ] 限制最大 torque。
- [ ] 限制最大 action change。
- [ ] 先 0.5x speed。
- [ ] 先低幅度版本。
- [ ] 只测试短片段。
- [ ] 每次只改一个变量。

---

## 12. 我建议你真正动手时的顺序

### Phase 0：跑通官方环境

先不要上功夫。

```bash
./unitree_rl_lab.sh -t --task Unitree-G1-29dof-Velocity
./unitree_rl_lab.sh -p --task Unitree-G1-29dof-Velocity
```

目标：确保环境、模型、GPU、机器人资源、play 都能正常运行。

### Phase 1：跑通官方 mimic / dance

用官方 dance 或 gangnam_style：

```text
Mimic_Dance_102
Mimic_Gangnam_Style
```

目标：理解官方 mimic 的 observation、reward、termination、policy export、deployment。

### Phase 2：复现 PBHC Horse-stance pose

```bash
python humanoidverse/train_agent.py \
+simulator=isaacgym +exp=motion_tracking +terrain=terrain_locomotion_plane \
project_name=MotionTracking num_envs=128 \
+obs=motion_tracking/main \
+robot=g1/g1_23dof_lock_wrist \
+domain_rand=main \
+rewards=motion_tracking/main \
experiment_name=debug \
robot.motion.motion_file="example/motion_data/Horse-stance_pose.pkl" \
seed=1 \
+device=cuda:0
```

目标：复现一个最接近“功夫”的动作。

### Phase 3：做你自己的第一个功夫动作

不要先做连招。先做：

```text
站立 → 马步 → 一次冲拳 → 收势
```

动作长度建议：

```text
3-5 秒
```

### Phase 4：加难度

按顺序加：

```text
双拳
→ 转腰
→ 低扫腿
→ 慢速踢腿
→ 快速踢腿
→ 转身
→ 连招
```

---

## 13. 代码改动建议

### 13.1 如果用 Unitree RL Lab

复制：

```text
source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/dance_102/
```

改成：

```text
source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/kungfu_001/
```

修改：

```text
motion_file
body_names
pose_range
velocity_range
joint_position_range
RewardsCfg
TerminationsCfg
episode_length_s
```

### 13.2 你最可能需要调的 RF 参数

优先级：

```text
1. action_rate_l2
2. joint_limit
3. undesired_contacts
4. motion_body_pos / ori
5. motion_body_lin_vel / ang_vel
6. motion_global_anchor_pos / ori
7. joint_torque
8. joint_acc
```

### 13.3 如果动作太抖

```text
action_rate_l2: -0.1 → -0.2 → -0.5
joint_torque: -1e-5 → -2e-5
joint_acc: -2.5e-7 → -5e-7
动作 fps 降低
参考轨迹平滑
```

### 13.4 如果动作不像

```text
motion_body_pos: +1.0 → +1.5 / +2.0
motion_body_ori: +1.0 → +1.5
motion_body_lin_vel: +1.0 保持
motion_body_ang_vel: +1.0 保持
action_rate penalty 先降低一点
tracking sigma 适度缩小
```

### 13.5 如果总是摔

```text
加稳定过渡段
降低动作速度
降低踢腿高度
放宽 termination threshold
降低 push randomization
先固定摩擦
增强 anchor orientation
增强 base height / torso stability
```

---

## 14. 推荐的 reward curriculum

### Stage 1：能学会动作

```text
tracking rewards: high
penalties: low-medium
domain randomization: low
push: off or very weak
termination: not too strict
```

### Stage 2：动作变稳

```text
action_rate penalty ↑
joint_limit penalty ↑
foot_slip penalty ↑
undesired_contacts penalty ↑
domain randomization ↑
```

### Stage 3：准备 sim2real

```text
ctrl_delay randomization on
PD gain randomization on
friction randomization on
mass / inertia randomization on
COM randomization on
push on
action_rate penalty strong
torque / velocity / limit penalty strong
```

### Stage 4：真机前 final check

```text
MuJoCo sim2sim
ONNX deployment path
joint order
observation order
action scale
PD gain
fps
network interface
debug mode
吊装
emergency stop
```

---

## 15. 关键源码路径

### Unitree RL Lab

```text
unitree_rl_lab/
  README.md
  source/unitree_rl_lab/unitree_rl_lab/tasks/locomotion/robots/g1/29dof/velocity_env_cfg.py
  source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/robots/g1_29dof/dance_102/tracking_env_cfg.py
  source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/mdp/rewards.py
  source/unitree_rl_lab/unitree_rl_lab/tasks/mimic/mdp/terminations.py
  source/unitree_rl_lab/unitree_rl_lab/assets/robots/unitree.py
  deploy/robots/g1_29dof/config/config.yaml
```

### Unitree RL Mjlab

```text
unitree_rl_mjlab/
  README_zh.md
  scripts/train.py
  scripts/play.py
  scripts/csv_to_npz.py
  src/assets/motions/g1/
  deploy/robots/g1/
  simulate/
```

### PBHC / KungfuBot

```text
PBHC/
  README.md
  INSTALL.md
  motion_source/
  smpl_retarget/
  smpl_vis/
  robot_motion_process/
  humanoidverse/
    README.md
    config/rewards/motion_tracking/main.yaml
    config/rewards/motion_tracking/general_main.yaml
    config/domain_rand/main.yaml
```

---

## 16. 参考资料

### Unitree 官方

- Unitree RL Mjlab  
  `https://github.com/unitreerobotics/unitree_rl_mjlab`
- Unitree RL Lab  
  `https://github.com/unitreerobotics/unitree_rl_lab`
- Unitree RL Gym  
  `https://github.com/unitreerobotics/unitree_rl_gym`
- Unitree MuJoCo  
  `https://github.com/unitreerobotics/unitree_mujoco`

### Kungfu / high dynamic motion

- KungfuBot project page  
  `https://kungfu-bot.github.io/`
- PBHC official implementation  
  `https://github.com/TeleHuman/PBHC`
- KungfuBot paper  
  `https://arxiv.org/abs/2506.12851`

### Whole-body tracking

- BeyondMimic / whole_body_tracking  
  `https://github.com/HybridRobotics/whole_body_tracking`
- RSL-RL  
  `https://github.com/leggedrobotics/rsl_rl`

### 相关最新论文方向

- RobotDancing: residual-action RL for Unitree G1 long-horizon dance tracking  
  `https://arxiv.org/abs/2509.20717`
- CLF-RL: Control Lyapunov Function guided RL on Unitree G1  
  `https://arxiv.org/abs/2508.09354`
- RoboForge: text-guided whole-body locomotion for Unitree G1  
  `https://arxiv.org/abs/2603.17927`

---

## 17. 一句话总结

你要训练 G1 打功夫，应该走：

```text
PBHC / KungfuBot 风格的 motion processing + whole-body tracking RL
```

或者走：

```text
Unitree RL Mjlab / Unitree RL Lab 的 G1 motion imitation
```

而不是手写开环轨迹。  
RF 的核心是：

```text
动作像 + 不摔 + 不滑 + 不抖 + 不撞 + 不超限 + 能 sim2real
```
