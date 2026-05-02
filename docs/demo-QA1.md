# demo-QA1：MuJoCo 悬挂带、键盘 demo 与 RL 步行 demo 深入解答

本文回答你提出的两组问题：

1. 在 `unitree_mujoco`（Python 模拟器）里，悬挂带键 `7 / 8 / 9` 究竟做什么？是不是可以"按 8 慢慢把机器人放到地上"，然后再用 `g1_sim_keyboard.py` 通过键盘下发动作？
2. 为什么"走路 / 跑步"这种动作要靠 RL，而不是像挥手、鞠躬那样直接写关节角就能做出来？
3. 给出一个**前进 / 后退 / 左右 / 转向 / 跑（极速行走）**的 RL demo 运行脚本以及它的工作原理。

> 涉及的核心源码（你想刨根问底时可以直接读）：
> - 悬挂带逻辑：`unitree_mujoco/simulate_python/unitree_sdk2py_bridge.py:399-428` 的 `class ElasticBand`。
> - 键盘 demo：`g1_sim_demo/g1_sim_keyboard.py`、`g1_sim_demo/g1_sim_interactive.py`、`g1_sim_demo/g1_sim_low_level.py`。
> - 训练策略 / 部署描述：`unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/`（`policy.onnx` + `params/deploy.yaml`）。
> - 部署侧观测 / 动作实现：`unitree_rl_mjlab/deploy/include/isaaclab/envs/mdp/observations/observations.h`、`deploy/robots/g1/src/State_RLBase.cpp`。

---

## 1. 悬挂带 7 / 8 / 9 真正做什么

`ElasticBand` 是一段虚拟弹簧，挂在世界点 `(0, 0, 3)` 与机器人 `torso_link`（H1/G1 是 `torso_link`，四足是 `base_link`）之间。它每个仿真步根据 `f = stiffness*(distance - length) - damping*v` 给身体施加外力 `xfrc_applied`，所以"长度变短" = "把机器人吊得更高"。

```python
# unitree_mujoco/simulate_python/unitree_sdk2py_bridge.py
def MujuocoKeyCallback(self, key):
    glfw = mujoco.glfw.glfw
    if key == glfw.KEY_7:
        self.length -= 0.1     # 绳子缩短 0.1 m → 把机器人往上拉
    if key == glfw.KEY_8:
        self.length += 0.1     # 绳子加长 0.1 m → 让机器人往下落
    if key == glfw.KEY_9:
        self.enable = not self.enable   # 整条带子开关：开↔关
```

所以三个键的物理含义是：

| 键 | 行为 | 适合做什么 |
|---|---|---|
| `7` | 绳长 `-0.1 m`，立即把机器人**吊高** | 想反复给它一个"虚拟救援"——脚离地，可以静态摆 pose 而不会摔 |
| `8` | 绳长 `+0.1 m`，逐步**放低** | **慢慢把脚放到地面**，是"软着陆"的正确做法 |
| `9` | 切换 `enable`（瞬间剪断 / 接回绳子） | 完全脱离吊带，做需要真实接触的事情（比如行走）|

### 你的理解对在哪里、不全在哪里

> "MuJoCo 里不要按 9 剪绳子，只需要按 8 把机器人慢慢放在地上，然后再通过 `g1_sim_keyboard.py` 接收输入。"

**对的部分**：
- 仿真器一启动，G1 默认是悬挂状态（`length=0`，吊在 `(0,0,3)` 上方靠近躯干的位置）。直接按 `9` 会把弹簧外力撤掉，机器人**自由下落**——而 `g1_sim_keyboard.py` 这种基于"PD 关节位置控制"的脚本完全没有平衡能力，下落瞬间就会摔倒、四肢往奇怪方向蹬。
- 多按几下 `8`（比如 6~10 次）确实可以把绳子放长，让脚先慢慢着地。这一步是任何"想让 G1 真的站到地面"的 demo 的安全前提。

**不全在的部分（很关键，避免你走弯路）**：
1. **光按 `8` 把脚放到地面，机器人自己仍然站不住**。`ElasticBand.enable` 还是 `True`，弹簧只是"绳子很长、张力很小"，机器人靠的是这一点点残余张力 + 你脚底刚好踩到地面的接触力。一旦它姿态有偏差，弹簧仍然会把躯干往 `(0,0,3)` 那个点拉，脚底接触和弹簧拉力打架，姿态会很别扭。
2. **`g1_sim_keyboard.py` 是"挂着玩"的 demo**——它命令的全是静态预设关节角（招手、T-pose、鞠躬、抬腿、深蹲……），没有任何"动态平衡"反馈。所以**它的设计假设是吊带保持启用、脚不踩实地**。你想让它做的所有"地面动作"，包括脚下的抬腿、深蹲、kick，本质都是"在吊带下做完这个 pose 然后回零位"，并不是真的能站着做完。
3. 想"把机器人放到地面上、然后让它真正站着接收键盘命令做动作"——这件事**就需要 RL（或一个手写的、复杂的全身平衡控制器）**了，原因详见第 2 节。

### 推荐的两种用法分流

| 你的目标 | 操作流程 |
|---|---|
| 想看挥手 / 鞠躬 / T-pose / 抬腿 / 深蹲等**静态姿态** | 启动模拟器 → **不动悬挂带（保持挂着）** → 在第二个终端运行 `g1_sim_keyboard.py` → 按字母键看动作 → 退出前先按 `q`（脚本会自动回零位） |
| 想看**站立、前进、后退、转向、慢跑** | 启动模拟器 → 按几下 `8` 把脚放到地面 → 这时候按 `9` 关掉弹簧也无所谓（机器人此刻应已与地面建立接触）→ 在第二个终端运行**新的 RL demo**（本文第 3 节）→ 按 `w/s/a/d/q/e` 控制速度命令 |

> 实际操作小诀窍：先按 `9` 看一下默认状态——很多时候 G1 默认的 `length=0` 已经把脚悬空在地面附近。先关一次 `9` 确认它落地姿态再开 `9`（或者按几下 `8` 缓慢放下），可以把"摔倒"这一步控制在你想要的时间点。

---

## 2. 为什么"走 / 跑"必须用 RL（而摆 pose 不用）

这是一个从控制理论 + 机器人学 + 学习方法整体回答的问题。

### 2.1 摆 pose 和走路在控制问题上是两件事

`g1_sim_keyboard.py` 控制 29 个关节用的是最简单的"关节空间 PD 位置控制"：每 2 ms 发一条 LowCmd，每个电机告诉它"你现在该转到 q_des"。机器人内部的电机驱动器自己执行 `τ = Kp*(q_des - q) + Kd*(0 - dq)`。这套方法的**核心假设**是：

> **目标姿态本身就是机械稳定的**——也就是无论谁去维持这个姿态，机器人都不会自己摔。

挂在吊带上时，所有 29 个关节都处于"被弹簧吊住的悬空状态"，重力被绳子卸掉了大头；脚不接地，足部地面反作用力 = 0；身体是否倾斜也不致命，因为弹簧会把它拉回来。所以：

- 挥右手 = 让 `right_shoulder_pitch / roll / elbow` 三个角度变到目标值。
- 鞠躬 = 让 `waist_pitch = 0.5`。
- 抬左腿 = 让 `left_hip_pitch / left_knee / left_ankle_pitch` 几个角度过去。

**摆 pose 是一个静态运动学问题**：只要算出来"哪几个关节角度凑出我想要的姿态"就行；不用解动力学方程，不用考虑接触力，更不用考虑能否平衡。

而走路 / 跑步是完全不同的问题——它是一个 **混合系统下的高维动态最优控制问题**：

1. **欠驱动 + 浮基 (floating base)**。29 个电机控制不了重心相对地面的位置——重心由脚底反作用力间接决定，谁也没法直接命令"重心 x 加速度等于多少"。这就是欠驱动。所有人形机器人步行的根本难点都是这一条。
2. **接触不连续**。脚一会儿着地一会儿离地，整个动力学方程在每次"足底切换"时都换一组（左脚单支撑 / 双支撑 / 右脚单支撑 / 飞行相），这是混合系统。要让机器人在切换时不抖、不滑、不卡，需要专门的接触模型。
3. **强非线性动力学**。29 自由度的人形机器人质量分布很复杂（手臂摆动也会影响平衡），动力学是 `M(q)q̈ + C(q,q̇)q̇ + G(q) = τ + Jᵀf_ext`，其中 `M` 是 29×29 的耦合质量矩阵、`f_ext` 是脚底接触力。
4. **必须实时反馈**。一阵风吹来、脚底打滑、地面有 1 cm 凸起——这些都会让规划好的轨迹失效，需要在毫秒级反应。

### 2.2 传统方法能不能写出走路控制器？能，但代价巨大

历史上有过很多方法（按时间线粗排）：

- **ZMP（Zero Moment Point）控制**（Honda P2 / Asimo / HRP-2）。手算 ZMP 轨迹，做预观（preview）控制，适合在平地小步慢走。需要离线规划脚步、在线 LQR 跟踪 CoM、接触力分配……一个完整管线少说 5 万行 C++。
- **WBC（Whole-Body Control）+ 步态规划器**（Atlas / TALOS / DigiT 早期）。把任务分层（重心轨迹 > 足底轨迹 > 关节力矩），通过 QP 求解每一步的最优力矩。能跑、能跨障碍，但调参极其精细，上下楼梯、不平地形要专门人工切换不同步态。
- **MPC（Model Predictive Control）**（MIT Cheetah / Quattro / 部分四足公司）。每控制周期解一次 30~50 ms 的预测问题。计算量极大（要 1 kHz 内解 QP），建模假设（线性化、单刚体、平面）很苛刻，对碰撞模型敏感。
- **强化学习（RL）**（最近 5 年从 ANYmal、Cassie 开始席卷整个领域）。

四种里，**前三种都需要"工程师**手写控制器**"**：你要懂动力学方程、写解算器、调参数、维护一堆切换条件、为每种地形 / 每个机型 / 每种步态单独调一遍。这就是为什么 Asimo 团队用了 30 年才让它能上下楼梯，而且依然走得很别扭。

### 2.3 RL 解决的不是"我不知道怎么写控制器"，而是"我不想为每个新场景都写一遍"

RL 的核心做法是：

1. **不显式写控制律，只写"奖励函数"**。例如"前进速度跟得上指令 = +1.0；身体倾倒 > 30° = 终止 + 大惩罚；脚滑 = 小惩罚；动作平滑 = 小奖励"。
2. 在 GPU 上**并行跑几千个仿真环境**（mjlab + MuJoCo Warp 一次跑 4096 个 G1），用 PPO 之类的策略梯度算法训神经网络。
3. **训练时大量随机化**（Domain Randomization）：地面摩擦、电机延迟、IMU 噪声、机身质量、外力扰动……让策略学到一种"在各种工况下都能走"的鲁棒控制律。
4. 训完之后**得到一个 MLP 或 RNN**：输入 ≈ 100 维（关节角、关节速、IMU、上一帧动作、目标速度），输出 29 维（每个关节相对默认姿态的偏移量），50 Hz 跑。

这等价于：**让神经网络自己学出来一个比手写 ZMP/MPC 都鲁棒的全身控制器**。代价是你需要 GPU、需要写一个能跑的 MuJoCo 训练环境（mjlab 已经写好了）、需要调奖励函数；好处是同一套训练管线对 Go2 / G1 / H1 / R1 / A2 都能跑出能上真机的策略，而且训出来的策略对地形 / 扰动 / 力矩饱和都非常鲁棒。

### 2.4 具体到这个仓库里你能直接用的策略

`unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx` 就是 Unitree 训好的 G1 速度跟踪策略。它的接口（来自 `params/deploy.yaml`）：

- **控制频率**：50 Hz（`step_dt: 0.02`）。
- **观测向量**（98 维，按顺序拼接）：
  - `base_ang_vel`（3）：IMU 角速度，body frame。
  - `projected_gravity`（3）：把世界系下的 `(0,0,-1)` 重力方向用 IMU 四元数旋转到机身坐标系——告诉策略"上下方向在我身上是哪个轴"。
  - `velocity_commands`（3）：`[vx, vy, ωz]`，用户给的目标线速度 + 偏航角速度。
  - `gait_phase`（2）：`[sin(2π·φ), cos(2π·φ)]`，相位以 `period=0.6 s` 一周期递增；命令模长 < 0.1 时强制为 (0, 0)（站立时不要求踏步相位）。
  - `joint_pos_rel`（29）：`q - q_default`。
  - `joint_vel_rel`（29）：关节角速度。
  - `last_action`（29）：上一帧策略的原始输出（不乘 scale、不加 offset）。
- **动作向量**（29 维，每个关节一个数）：策略输出 raw action，**部署时**做 `q_target = action * scale + default_joint_pos`（scale/offset 都在 yaml 里），然后用 yaml 里给的 stiffness/damping 作 Kp/Kd 直接发 LowCmd。
- **训练时的速度区间**：`vx ∈ [-0.5, 1.0] m/s, vy ∈ [-0.5, 0.5], ωz ∈ [-1.0, 1.0]`。也就是说**这一版策略最多 1 m/s 前进**——这是"快走"，**不是真正的跑**。要真跑（>2 m/s）需要重新训练时把上限放开（参考 `src/tasks/velocity/config/g1/env_cfgs.py:114-132` 里 `std_running` 那一段是为高速训练预留的奖励参数，但 flat 默认配置不会触发它）。

---

## 3. RL demo 脚本：前进 / 后退 / 跑（极速行走）/ 转向

我在 `~/unitree/unitree-notes/g1_sim_demo/g1_sim_rl_walk.py` 写了一个完整的演示脚本，**风格与 `g1_sim_keyboard.py` 完全一致**（同样 DDS 通信、同样键盘读取、同样安全收尾），把"键盘命令 → 速度命令向量 → ONNX 推理 → 关节目标 → LowCmd"整条链路完整跑通。

### 3.1 安装依赖

策略是 ONNX 格式的，需要装 onnxruntime（你的 `unitree` conda 环境暂时只装了 `onnx` 而没装 `onnxruntime`）：

```bash
conda activate unitree
pip install onnxruntime          # CPU 推理就够用，50 Hz 推理只占很少 CPU
# 如果你想用 CUDA（其实没必要，模型很小）：pip install onnxruntime-gpu
```

### 3.2 运行（双终端，与 keyboard demo 节奏一致）

```bash
# 终端 1：模拟器（确认 simulate_python/config.py 里 ROBOT="g1", ENABLE_ELASTIC_BAND=True, USE_JOYSTICK=0）
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 弹出后：
#   - 按几下 8 让绳子放长，机器人脚落地
#   - 也可以按 9 关掉弹簧（落地后再关比较安全）
```

```bash
# 终端 2：RL 步行 demo
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_walk.py
# 等它打印 "[rl] policy ready, standing in place." 后再开始按键
```

键位：

| 键 | 作用 |
|---|---|
| `w / s` | 前进 / 后退（vx 加 / 减 0.2 m/s，被夹到训练区间） |
| `a / d` | 左 / 右平移（vy ±0.1 m/s） |
| `q / e` | 左 / 右原地转（ωz ±0.3 rad/s） |
| `r` | 把命令清零（站立） |
| `f` | 把 vx 直接拉到训练上限（1.0 m/s）——"全速跑"（极速行走）|
| `space` | 紧急清零并把刚度衰减到 0（软着陆，准备退出）|
| `?` | 打印帮助 |
| `Ctrl-C` 或 `x` | 退出（先把 Kp/Kd 收到 0，然后停止发 LowCmd）|

> **注意**：策略训练上限是 1.0 m/s。如果你按 `f`，机器人会以"全速"前进——这已经是这一版策略能力上限了。**如果你需要真正的"跑"（>2 m/s），需要按第 2.4 节的最后一段重新训练策略**，本仓库的 `unitree_rl_mjlab/scripts/train.py` 就是为此而生。

### 3.3 脚本里发生了什么（高层）

1. **加载部署描述**：读 `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml`，拿到 `default_joint_pos / scale / offset / stiffness / damping / step_dt / commands.base_velocity.ranges`。
2. **加载策略**：`onnxruntime.InferenceSession("policy.onnx")`，验证输入维度 = 98、输出维度 = 29。
3. **DDS 启动**：和 `g1_sim_keyboard.py` 一样，订阅 `rt/lowstate`（拿到 29 个关节状态、IMU 四元数、IMU 角速度、`mode_machine`）+ 发布 `rt/lowcmd`。
4. **预备阶段**：从首帧测得的初始姿态用 cosine ease-in-out **3 秒平滑过渡**到 `default_joint_pos`，刚度用 yaml 的值。这一步避免策略一上来 obs 就远离训练分布、动作炸开。
5. **策略主循环（50 Hz）**：每 20 ms：
   - 把最新 `LowState_` → 观测 98 维（注意 `projected_gravity = R(q_imu)^T · (0,0,-1)`，正是 C++ deploy 里 `data.root_quat_w.conjugate() * GRAVITY_VEC_W` 的事情）。
   - `gait_phase` 自己累积 `Δφ = step_dt / 0.6`，命令模长 < 0.1 时强置 (0, 0)。
   - `last_action` 用上一帧的 raw action（**注意是 raw，不是乘了 scale 之后的**）。
   - `policy.run()` → 29 维 raw action。
   - `q_target = raw_action * scale + default_joint_pos`，写进 `low_cmd.motor_cmd[i].q`，搭配 yaml 的 stiffness/damping 作为 Kp/Kd，CRC 后发出去。
6. **键盘线程**：单独读键，更新一份共享的 `[vx, vy, ωz]`；策略主循环每帧拷贝过来塞进 obs。
7. **退出**：刚度收到 0 → 等若干 100 ms 让机器人姿态稳定 → 退出主循环 → 清理 DDS。
8. **保险机制**：如果 `LowState_` 超过 0.2 s 没更新（仿真挂了），策略循环主动把 q_target 锁回 `default_joint_pos` 并打印警告。

### 3.4 这个 demo 和 `unitree_rl_mjlab/scripts/play.py` 的差别

| 维度 | `play.py` | 本 demo（`g1_sim_rl_walk.py`） |
|---|---|---|
| 物理引擎 | mjlab 自己起一个 MuJoCo（GPU/Warp 后端） | 走标准的 `unitree_mujoco/simulate_python` 桥 |
| 通信 | 直接拿 mjlab tensor，无 DDS | 完整走 DDS（`rt/lowstate` / `rt/lowcmd`），**和真机一致** |
| 策略 | PyTorch `.pt` checkpoint | ONNX，部署版本 |
| 输入 | gamepad 或随机命令 | 键盘 wsadqe |
| 用途 | 验证训练效果（quick play） | 验证"sim2real 部署链路"在 Python 端能跑通 |

也就是说，`play.py` 是研究流程里"训完看看效果"的工具，**本 demo 更接近真机部署的形态**——走的链路和你之后把 ONNX 烧到真 G1 控制板上是同一套。

---

## 4. 一句话总结

- 悬挂带按 `8` 慢慢放下脚是**对的安全做法**；`9` 是"剪绳子"的硬开关，留给"我已经准备好让机器人站起来"的时刻。
- `g1_sim_keyboard.py` 是**纯静态姿态 demo**，走 / 跑这种**动态平衡问题**它解不了。
- 走 / 跑要么用传统的 ZMP/WBC/MPC（手写、复杂、机型敏感），要么用 RL（仿真训练、对扰动鲁棒、跨机型可复用）；本仓库的 `unitree_rl_mjlab` 走的是 RL 路线，并已经提供了 G1 的 `policy.onnx`。
- 想立刻看到 G1 在 MuJoCo 里 "wsad 走起来"：按本文 §3.2 跑 `g1_sim_rl_walk.py`。
