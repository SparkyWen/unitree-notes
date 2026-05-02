# G1 仿真 Demo 完整解析

本文档面向**第一次想把 G1 在 MuJoCo 里动起来、并写自己动作**的开发者。它把
`unitree_mujoco / unitree_sdk2_python / g1_sim_demo` 三个仓库之间的耦合关系讲透，
并配套一个可直接交互的实时控制例子 `g1_sim_interactive.py`。

---

## 1. 工作区结构与三个仓库各自的职责

```
~/unitree/
└── unitree-notes/
    ├── unitree_sdk2_python/        # ① SDK：发/收 DDS 消息的 Python 绑定
    │   └── unitree_sdk2py/...
    ├── unitree_mujoco/              # ② 仿真器：MuJoCo + 一个内嵌 bridge
    │   ├── simulate_python/
    │   │   ├── unitree_mujoco.py        # 仿真主进程（终端 1 跑这个）
    │   │   ├── unitree_sdk2py_bridge.py # bridge：DDS ⇄ MuJoCo
    │   │   └── config.py
    │   └── unitree_robots/g1/...        # MJCF 资产（23dof / 29dof scene.xml）
    ├── unitree_rl_mjlab/            # ③ RL 训练/部署框架（本文不展开）
    └── g1_sim_demo/                 # ④ 我们的 demo 代码
        ├── g1_sim_low_level.py          # 上游官方 demo 的 sim 友好版
        ├── g1_sim_interactive.py        # ⭐ 本指南配套的交互式 demo
        └── demo-explain.md              # ⬅ 你正在看的这个文件
```

三者关系：

| 仓库 | 角色 | 你会用它做什么 |
|---|---|---|
| `unitree_sdk2_python` | **API 库** | 在你自己的脚本里 `import unitree_sdk2py.*`，发布 `LowCmd_` / 订阅 `LowState_`、计算 CRC、跑高频线程 |
| `unitree_mujoco` | **仿真器（含 bridge）** | 终端 1 启动 `simulate_python/unitree_mujoco.py`，它同时承担 “物理仿真” 与 “假装是真机的 DDS 节点” 两个角色 |
| `g1_sim_demo` | **你的控制脚本** | 终端 2 启动；纯逻辑层，不直接碰 MuJoCo |

**关键观念**：**bridge 不是独立进程，不需要单独开第三个窗口**。它只是 `unitree_mujoco.py`
里实例化的一个 `UnitreeSdk2Bridge` 对象（见 `simulate_python/unitree_mujoco.py:42`），跟物
理仿真共享同一个 Python 进程、同一份 `mj_model / mj_data`。

---

## 2. 数据流：两个进程，一条 DDS 总线

```
┌──────────────────────────────────────────────────────────┐
│ 终端 1: python unitree_mujoco.py                          │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ MuJoCo 物理线程 (SimulationThread)                   │ │
│ │   每 SIMULATE_DT (=5 ms) 调用 mj_step()              │ │
│ │   • 读 mj_data.ctrl[i]  → 真物理力矩                 │ │
│ │   • 更新 qpos / qvel / sensordata                     │ │
│ └──────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ MuJoCo 渲染线程 (PhysicsViewerThread)                │ │
│ │   每 VIEWER_DT (=20 ms) 调用 viewer.sync()           │ │
│ └──────────────────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ UnitreeSdk2Bridge（同进程，3 个 RecurrentThread）    │ │
│ │   • 订阅 rt/lowcmd  → 把 PD 公式算出的力矩写入 ctrl │ │
│ │   • 发布 rt/lowstate (周期 = SIMULATE_DT)            │ │
│ │   • 发布 rt/sportmodestate, rt/wirelesscontroller   │ │
│ └──────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
            ▲                                   │
   rt/lowcmd│                          rt/lowstate│
            │  CycloneDDS  (interface=lo)        ▼
┌──────────────────────────────────────────────────────────┐
│ 终端 2: python g1_sim_interactive.py                      │
│   • ChannelPublisher("rt/lowcmd",   LowCmd_)             │
│   • ChannelSubscriber("rt/lowstate", LowState_)          │
│   • 500 Hz 控制线程：填 LowCmd_ → 发                       │
└──────────────────────────────────────────────────────────┘
```

DDS 的几个细节：

- **传输介质**：CycloneDDS 走系统的 `lo`（loopback）网卡，靠 IP 多播在同机进程间通信。
  这就是 `INTERFACE = "lo"` 的含义。
- **域 (Domain)**：`DOMAIN_ID = 1`。真机出厂默认 0，仿真特意改成 1，避免你跑仿真时
  误把指令发到旁边正在工作的真机。**两端必须一致才能通信**。
- **Topic 名固定**：`rt/lowcmd`、`rt/lowstate` 等是上游协议约定的名字，bridge 与 SDK
  写死在代码里，不能改。
- **消息 IDL**：G1 / H1-2 用 `unitree_hg`（带 `mode_pr` / `mode_machine` 字段、29 个电机
  位）；Go2 / B2 / H1 用 `unitree_go`（20 个电机位）。bridge 里靠 `if config.ROBOT=="g1"`
  自动选。**你写客户端时也要 import 对版本**。

---

## 3. 控制律：bridge 里到底发生了什么

`simulate_python/unitree_sdk2py_bridge.py` 的 `LowCmdHandler` 收到 `LowCmd_` 后，对每个
电机执行的就一行：

```python
mj_data.ctrl[i] = (
    msg.motor_cmd[i].tau
    + msg.motor_cmd[i].kp * (msg.motor_cmd[i].q  - sensordata[i])     # 当前角度
    + msg.motor_cmd[i].kd * (msg.motor_cmd[i].dq - sensordata[i+nu])  # 当前速度
)
```

也就是 **τ_applied = τ_ff + Kp·(q_des − q) + Kd·(dq_des − dq)**，一个标准的 PD 位置控制器
带前馈力矩。所以你下发的每一帧 `LowCmd_` 就是 29 组 `(q, dq, tau, kp, kd)`：

| 字段 | 含义 | 你最常改 | 备注 |
|---|---|---|---|
| `q` | 目标角度 (rad) | ✅ | 主要操作量 |
| `dq` | 目标角速度 (rad/s) | 偶尔 | 速度跟踪 / 力矩前馈解耦时用 |
| `tau` | 前馈力矩 (Nm) | 罕见 | 低层力矩控制时用 |
| `kp`, `kd` | PD 增益 | 固定 | 按部位给（腿膝盖最大，手腕最小） |
| `mode` | 电机使能 | 1 | 0 表示停摆 |

`g1_sim_low_level.py` 里给的 Kp/Kd 是经过调试的、能让 G1 在仿真里稳住的一套合理值，
**你写自己的脚本时直接照搬即可**，不要乱改：

```python
Kp = [60,60,60,100,40,40,  60,60,60,100,40,40,  60,40,40,
      40,40,40,40,40,40,40,  40,40,40,40,40,40,40]   # 29 维
Kd = [1,1,1,2,1,1,  1,1,1,2,1,1,  1,1,1,
      1,1,1,1,1,1,1,  1,1,1,1,1,1,1]                  # 29 维
```

膝盖 Kp=100、Kd=2，是因为膝盖承重最大，需要更硬的伺服。手臂 Kp=40 比较软，是为了
让手臂动作平顺、撞到东西时不至于太硬。

---

## 4. PR 模式 vs AB 模式（G1 特有）

G1 的 **踝关节** 和 **腰部** 在硬件上是两个并联连杆驱动的（不是普通两个独立电机），
所以协议给了你两种坐标表达：

- **`mode_pr = 0` (PR)**：直接给关节空间的 Pitch / Roll。直观，适合写动作。
- **`mode_pr = 1` (AB)**：给底层电机 A / B 的角度。仿真器都支持，但我们一般用 PR。

具体哪些索引在两种模式下含义不同，看 `unitree_robots/g1/g1_joint_index_dds.md` 的加粗
项（4/5、10/11、13/14）。**本指南和 demo 代码全部用 PR 模式**，无脑设
`low_cmd.mode_pr = 0` 即可。

---

## 5. G1 29-DOF 关节索引速查

PR 模式下：

| Idx | 名称 | Idx | 名称 | Idx | 名称 |
|---|---|---|---|---|---|
| 0 | LeftHipPitch | 10 | RightAnklePitch | 20 | LeftWristPitch |
| 1 | LeftHipRoll | 11 | RightAnkleRoll | 21 | LeftWristYaw |
| 2 | LeftHipYaw | 12 | WaistYaw | 22 | RightShoulderPitch |
| 3 | LeftKnee | 13 | WaistRoll | 23 | RightShoulderRoll |
| 4 | LeftAnklePitch | 14 | WaistPitch | 24 | RightShoulderYaw |
| 5 | LeftAnkleRoll | 15 | LeftShoulderPitch | 25 | RightElbow |
| 6 | RightHipPitch | 16 | LeftShoulderRoll | 26 | RightWristRoll |
| 7 | RightHipRoll | 17 | LeftShoulderYaw | 27 | RightWristPitch |
| 8 | RightHipYaw | 18 | LeftElbow | 28 | RightWristYaw |
| 9 | RightKnee | 19 | LeftWristRoll |  |  |

代码里写成 `J.LeftKnee` 这样的常量更安全，见 `g1_sim_interactive.py` 顶部。

---

## 6. 上游官方 demo 在仿真里跑不通的两个坑

`unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py` 是为真机写的，
直接拿到仿真上会卡两个地方，**自己写脚本时一定要绕开**：

1. **域 ID 写死了 0**
   上游强制 `ChannelFactoryInitialize(0, "interface")`，但 `simulate_python/config.py`
   默认 `DOMAIN_ID=1`。两边不一致 → topic 不互通 → 你以为没崩，但其实啥也没收到。
   👉 仿真模式必须 `ChannelFactoryInitialize(1, "lo")`。

2. **MotionSwitcherClient 在仿真不存在**
   上游会先调 `MotionSwitcherClient.CheckMode()` 询问当前运动模式，但 bridge 只
   暴露 `rt/lowcmd / rt/lowstate / rt/sportmodestate / rt/wirelesscontroller` 四个
   topic，没有这个 RPC 服务 → 调用永远不返回 → 脚本在初始化时就卡死。
   👉 仿真路径直接跳过 MotionSwitcher，等收到第一帧 `lowstate` 拿到 `mode_machine`
   就开始控制环。

`g1_sim_low_level.py` 和 `g1_sim_interactive.py` 都已经处理好这两点了。

---

## 7. 完整运行步骤

> **环境**：conda env `unitree`（Python 3.11，已装 `unitree_sdk2py / mujoco==3.5.0
> / pygame / cyclonedds`），路径在 `~/miniforge3/envs/unitree`。

### Step 0 — 一次性配置（已经做好了的话跳过）

确认 `unitree_mujoco/simulate_python/config.py` 是这个状态：

```python
ROBOT = "g1"
ROBOT_SCENE = "../unitree_robots/" + ROBOT + "/scene.xml"   # → g1_29dof
DOMAIN_ID = 1
INTERFACE = "lo"
USE_JOYSTICK = 0           # 没接手柄就关掉，不然进程会 sys.exit()
ENABLE_ELASTIC_BAND = True # 双足必开，否则 G1 落地就摔
```

### Step 1 — 终端 1：起仿真器

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

弹出 MuJoCo viewer 后：

- **必做**：在 viewer 窗口（不是终端）按 `9` → 启用悬挂带，把 G1 吊在原地。
  - `7` = 把机器人放到地面
  - `8` = 把机器人吊起来
  - `9` = 切换悬挂带启用 / 释放
- 终端会打印一长串 link / joint / sensor 信息，最后停在 `mj_step` 循环里 = 正常。

### Step 2 — 终端 2：跑控制脚本

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_interactive.py
```

预期输出：

```
[g1] simulator mode on lo (domain 1).
[g1] waiting for first /rt/lowstate ...
[g1] got lowstate (mode_machine=0). Ramping to zero pose over 3 s.
Keys (focus this terminal):
  z = ramp to zero pose
  w = wave right arm
  ...
```

3 秒后 G1 在 viewer 里平滑回到 zero pose，然后**这个终端窗口**等你按键：

| 按键 | 动作 |
|---|---|
| `z` | 回零位（任何时候都能按，2s 平滑插值） |
| `w` | 右臂招手 |
| `b` | 弯腰 |
| `k` | 抬左膝 |
| `a` | 双臂拍手两次 |
| `q` | 先回零位再退出 |

---

## 8. 交互式 Demo 的代码骨架（`g1_sim_interactive.py`）

为了让你能轻松改出自己的动作，整段代码遵循一个简单原则：
**“关键帧 + 平滑插值” 永远不会让机器人瞬移**。

### 8.1 数据结构

```python
# 一个 “pose” = 长度 29 的 numpy 数组（每个关节的目标角，单位 rad）
def zero_pose() -> np.ndarray: ...
def wave_right_arm_pose() -> np.ndarray: ...

# 一个 “trajectory” = 一组 (duration_seconds, target_pose) 的列表
TRAJECTORIES = {
    "w": [(1.5, wave_right_arm_pose()),
          (0.6, wave_right_arm_pose()),   # 停留 0.6 s
          (1.5, zero_pose())],
    ...
}
```

按一次 `w` 键，主循环就把 `TRAJECTORIES["w"]` 这三段一次性塞进控制器队列。

### 8.2 控制器三件套

```python
class G1Controller:
    CONTROL_DT = 0.002              # 500 Hz

    def init_dds(self):              # 起 publisher / subscriber
    def _on_state(self, msg):        # 收到 lowstate 就更新 self.low_state
    def push(self, trajectory):      # 把关键帧塞进 self._queue
    def start(self):                 # 起 RecurrentThread（500 Hz 调 _tick）
    def _tick(self):                 # 每 2 ms 算下一帧 q_cmd 并发布
    def _publish(self, q_des):       # 把 q_des 写进 LowCmd_ → 算 CRC → Write
    def stop_and_settle(self):       # 退出前先回零位
```

### 8.3 平滑插值（关键算法）

```python
# self._active = [q_from, q_to, dur, t]
s = 0.5 - 0.5 * np.cos(np.pi * (t / dur))     # cosine ease-in-out, s ∈ [0,1]
self.q_cmd = (1 - s) * q_from + s * q_to
```

为什么用 cosine 而不是线性插值？因为 cosine 在两端的导数都是 0 —— **起步和落点都
没有速度跳变**，电机不会被狠抽一下。线性插值起步那一瞬间的目标速度是阶跃，硬件
和 PD 控制器都不喜欢。

### 8.4 怎么加你自己的动作

只要写一个 “返回 29 维 numpy 数组” 的函数，再加进 `TRAJECTORIES`：

```python
def my_squat_pose():
    p = zero_pose()
    p[J.LeftKnee]     =  1.2
    p[J.RightKnee]    =  1.2
    p[J.LeftHipPitch] = -0.8
    p[J.RightHipPitch]= -0.8
    p[J.LeftAnklePitch]  = -0.4
    p[J.RightAnklePitch] = -0.4
    return p

TRAJECTORIES["s"] = [(2.0, my_squat_pose()),
                     (1.5, my_squat_pose()),
                     (2.0, zero_pose())]
KEY_HELP += "\n  s = squat"
```

按 `s` 就深蹲。**不要绕过 trajectory 系统直接修改 `q_target`**——那会跳过插值，可能
导致 G1 一个跟头。

### 8.5 进阶：实时连续控制（不用预设动作）

如果你要做的是 **遥操作 / VR / RL 推理** 这种连续输入场景，控制器的 `q_cmd` 就是
你每帧重新计算的“最新目标”。最简单的接法：把队列换成 “只保留最新一个” 的单元格，
`_tick` 里直接以一个固定的小时间常数（比如 0.1 s）一阶追踪 `q_cmd → q_target`：

```python
alpha = self.CONTROL_DT / 0.1     # 100 ms 时间常数
self.q_cmd += alpha * (self.q_target - self.q_cmd)
```

这样上层每隔几十毫秒往 `q_target` 写一次新值就行，不会有跳变。

---

## 9. Sim → Real：唯一要改的一行

`g1_sim_interactive.py` 的入口已经处理好了：

```python
if len(sys.argv) > 1 and sys.argv[1] not in ("lo", "sim"):
    ChannelFactoryInitialize(0, sys.argv[1])    # 真机：domain 0 + 网卡
else:
    ChannelFactoryInitialize(1, "lo")           # 仿真：domain 1 + lo
```

所以：

```bash
python g1_sim_interactive.py              # 跑仿真
python g1_sim_interactive.py enp3s0       # 跑真机（网卡名按你机器实际填）
```

**真机上的额外注意事项**（demo 没替你处理）：

1. **务必先关掉运动模式服务**。真机出厂带一个 `MotionSwitcher` 高层服务，会跟你的
   `LowCmd_` 打架。生产代码应该用 `MotionSwitcherClient.SetMode("idle")` 或类似手段
   先释放控制权。本 demo 在仿真里没有这个步骤，移到真机时要自己加。
2. **第一帧前先读 `mode_machine`**。真机会上报真实的硬件型号 ID，**必须把 lowstate 里
   读到的值原样回填到 `low_cmd.mode_machine`**，否则会被拒收。本 demo 已经这样做了。
3. **重力与悬挂**。真机不需要 `9` 键悬挂带，但你**必须保证 zero pose 在站立姿态附近
   且机器人本来就在一个稳定可控的状态**，否则一上 PD 它会立刻摔。
4. **CRC**。`self.crc.Crc(low_cmd)` 必须在每次 `Write` 之前算，仿真和真机都要。

---

## 10. 故障排查

| 现象 | 可能原因 | 解决 |
|---|---|---|
| 终端 2 卡在 `waiting for first /rt/lowstate` | 仿真器没起来 / domain 不一致 / 网卡不一致 | 检查 `config.py` 是 `DOMAIN_ID=1, INTERFACE="lo"`；仿真器进程还活着；防火墙没拦 lo |
| viewer 没弹出来 | WSL2 / SSH 缺 X 转发 | WSL2 默认有 WSLg 应该 OK；SSH 用 `ssh -X` |
| G1 一上来就摔 | 没按 `9` 启用悬挂带 | 在 viewer 窗口按 `9` |
| 关节抽搐 / 嗡嗡颤 | Kp 太大或自己改了 Kd | 用 demo 提供的那一套增益，不要乱调 |
| 动作幅度对了但方向反了 | 关节正方向不熟 | 用 viewer 上的关节滑块（`Joint` 面板）手动拖一下，看看正方向是哪边 |
| `CRC mismatch` 警告 | 忘了在 `Write` 前算 CRC，或 IDL 用错（go vs hg） | 每次 `_publish` 末尾都要 `low_cmd.crc = crc.Crc(low_cmd)`；G1 用 `unitree_hg` |
| 按键没反应 | 终端 2 没获得焦点 | 把鼠标点到运行 demo 的那个终端窗口；不是 viewer 窗口 |
| 仿真步数跑不动 / 视觉卡顿 | `SIMULATE_DT` 太小 | 默认 5 ms 已经合理；机器太弱可改成 8 ms |

---

## 11. 一页流程图

```
   你写脚本                           仿真器（终端 1）
   ─────────                         ───────────────
1. ChannelFactoryInitialize(1,"lo")
2. ChannelPublisher("rt/lowcmd")  ─DDS─►  UnitreeSdk2Bridge.LowCmdHandler
3. ChannelSubscriber("rt/lowstate")          │
4. 等第一帧 lowstate                          ▼
5. 拿到 mode_machine                       mj_data.ctrl[i] = τ_ff+Kp·Δq+Kd·Δdq
6. 每 2 ms：                                  │
     算 q_des → 填 LowCmd_                  mj_step() 推进物理
     CRC                                      │
     Write()                                  ▼
7. 收到 lowstate → 更新 q_cmd            发 LowState_  ─DDS─►  你的 _on_state
   循环回 6
```

只要把这张图刻进脑子，G1 / H1-2 / Go2 全家桶你都会用了 —— 区别只是 IDL 名字
（`unitree_hg` vs `unitree_go`）和电机数量。
