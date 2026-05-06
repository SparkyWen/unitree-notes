我会先把“是否值得做”拆成**产品价值/技术价值/风险边界**，再基于宇树官方开源栈梳理一套可落地的 harness → G1 框架。重点不会建议 agent 直接控制电机，而是做“高层决策 + 安全约束 + 技能调用”。

我已经核对了宇树官方 SDK2、ROS2、MuJoCo、RL Gym/Lab、IsaacLab、LeRobot 相关仓库。一个核心结论是：**harness 很适合做“任务级智能中枢”，但不适合进入 2ms/毫秒级底层控制闭环**。

Thought for 1m 11s

# 结论先说：**有价值，但必须做成“分层式机器人智能架构”**

你想把 **harness 多 agents 协作系统接入 Unitree G1**，我认为非常有价值，但前提是：

> **harness / LLM / multi-agent 不应该直接控制 G1 的每个电机。**
>  它应该作为 **任务规划层、感知理解层、安全审核层、技能调度层、记忆与日志层**，然后调用已经验证过的 **skill / controller / policy**。

换句话说：

```
正确方向：
人类自然语言 / 任务目标
        ↓
harness 多 agent 推理、规划、安全检查
        ↓
Skill Server / ROS2 Action / Unitree Adapter
        ↓
高层 locomotion / manipulation policy / 预定义动作
        ↓
Unitree SDK2 / ROS2 / DDS
        ↓
G1 真机或仿真

错误方向：
LLM / Agent 直接生成 29 个关节 LowCmd
        ↓
直接发给电机
        ↓
极高风险，不稳定，不可解释，容易摔机
```

------

# 1. 为什么这件事有价值？

## 1.1 G1 已经有足够开放的底层接口，适合接入外部智能系统

宇树官方开源栈已经给了几类关键接口：

| 开源栈                              | 作用                                        | 对 harness 的价值                            |
| ----------------------------------- | ------------------------------------------- | -------------------------------------------- |
| `unitree_sdk2`                      | 真机通信与控制 SDK                          | harness 最终可以通过 adapter 调用 G1         |
| `unitree_sdk2_python`               | Python 接口                                 | 方便和 Python/agent/harness 连接             |
| `unitree_ros2`                      | ROS2 / DDS 通信                             | 适合把 robot skill 包装成 ROS2 node / action |
| `unitree_mujoco`                    | MuJoCo 仿真，兼容 SDK2 / ROS2 / Python SDK2 | 可以先在仿真里验证 harness 行为              |
| `unitree_rl_gym` / `unitree_rl_lab` | RL locomotion 训练、仿真、Sim2Real          | 用于训练/部署底层运动策略                    |
| `unitree_sim_isaaclab`              | IsaacLab 高保真任务仿真、数据采集、模型验证 | 适合 manipulation / pick-place / 数据生成    |
| `unitree_lerobot` / LeRobot G1      | 模仿学习、遥操作、locomanipulation policy   | 适合接入“技能库”与任务执行策略               |

官方 GitHub 页面显示，`unitree_sdk2` 是用于 Go2、B2、H1、G1、H2、R1、A2 等真实机器人开发的 SDK；同时官方也提供 `unitree_sdk2_python`、URDF、USD、ROS1/ROS2、IsaacLab、teleimager 等开源资源。

------

## 1.2 G1 不缺“控制接口”，缺的是“任务级智能编排”

现在 G1 相关开源库更偏向：

- 机器人通信；
- 关节控制；
- locomotion；
- sim2real；
- 遥操作；
- policy training；
- pick-place task；
- 数据采集。

但这些库本身不会自动解决：

- 用户说一句“去桌边拿杯子然后递给我”，系统如何拆任务？
- 任务失败后如何反思？
- 摄像头看到物体偏移，如何重新规划？
- 多个子系统冲突时谁有最终裁决权？
- 低层 policy 报错时如何 fallback？
- 哪些动作必须二次确认？
- 哪些动作只允许仿真，不允许真机？

这正是 **harness 多 agents 系统的价值**。

------

# 2. 但是要明确边界：harness 不能做实时控制器

G1 真实控制里有明显的实时性要求。比如官方 low-level 示例中，低层控制使用 `rt/lowcmd`、`rt/lowstate`、`rt/secondary_imu` 等 DDS topic，并定义了 29 个电机、`q_target`、`dq_target`、`kp`、`kd`、`tau_ff` 等底层电机命令结构。

另一个 G1 双臂 low-level 示例中，控制周期设置为 `0.002` 秒，也就是 **2ms**，并通过 recurrent thread 周期性写命令和执行控制逻辑。

所以：

| 层级                       | 是否适合 agent/harness 介入   | 原因                                 |
| -------------------------- | ----------------------------- | ------------------------------------ |
| 2ms 电机控制循环           | ❌ 不适合                      | LLM/agent 延迟不可控，输出不确定     |
| PD / torque / joint target | ⚠️ 只能间接配置                | 必须由稳定控制器执行                 |
| locomotion policy          | ⚠️ 可以选择/切换，不应实时生成 |                                      |
| skill 调度                 | ✅ 非常适合                    | 比如站立、停止、走到某处、挥手、抓取 |
| 任务规划                   | ✅ 非常适合                    | 多 agent 可拆解、检查、重试          |
| 安全审核                   | ✅ 非常适合                    | 动作前检查环境、人、姿态、约束       |
| 日志/记忆/复盘             | ✅ 非常适合                    | 适合 harness 的长上下文与结构化记录  |

------

# 3. 推荐整体架构：**Agentic Skill-Oriented Robotics Framework**

我建议你不要把它设计成“Agent 控制机器人”，而是设计成：

> **harness 多 agent 负责理解任务、规划步骤、选择技能、检查安全、追踪状态；G1 只执行已经封装好的 robot skills。**

## 3.1 总体框架

```
┌─────────────────────────────────────────────┐
│ User / Operator                              │
│ 自然语言任务、语音、UI、手柄、急停按钮        │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│ Harness Multi-Agent Orchestrator             │
│ - Task Planner Agent                          │
│ - Perception Agent                            │
│ - Skill Router Agent                          │
│ - Safety Supervisor Agent                     │
│ - Execution Monitor Agent                     │
│ - Memory / Log Agent                          │
└─────────────────────┬───────────────────────┘
                      ↓ JSON / Action Goal
┌─────────────────────────────────────────────┐
│ Robot Skill Server                            │
│ ROS2 Action Server / FastAPI / gRPC / ZMQ     │
│ - stand_up                                    │
│ - sit                                         │
│ - walk_velocity                               │
│ - stop                                        │
│ - wave_hand                                   │
│ - grasp_object                                │
│ - pick_place                                  │
│ - return_to_safe_pose                         │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│ G1 Adapter Layer                              │
│ Unitree SDK2 / SDK2 Python / ROS2 / DDS       │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│ Controller / Policy Layer                     │
│ Built-in Loco / RL Policy / LeRobot Policy    │
│ PD Controller / Whole-body Controller         │
└─────────────────────┬───────────────────────┘
                      ↓
┌─────────────────────────────────────────────┐
│ Unitree G1 / MuJoCo / IsaacLab                │
└─────────────────────────────────────────────┘
```

------

# 4. 技术路线应该分三条

## 路线 A：最快 MVP —— 用 **G1 high-level loco client + skill server**

这是最适合你现在做 demo 的路线。

官方 G1 high-level 示例里，会先初始化 DDS channel，再创建 `unitree::robot::g1::LocoClient`，然后调用 `client.Init()` 和 `client.SetTimeout()`。

这个 high-level client 能读取/设置很多 G1 locomotion 状态，例如：

- `GetFsmId`
- `GetFsmMode`
- `GetBalanceMode`
- `GetSwingHeight`
- `GetStandHeight`
- `GetPhase`
- `SetFsmId`
- `SetBalanceMode`
- `SetVelocity`

示例代码里可以看到它读取 `fsm_id`、`fsm_mode`、`balance_mode`、`swing_height`、`stand_height`、`phase`，也支持设置 `fsm_id`、`balance_mode` 等。

你可以把这些 high-level API 包装成技能：

```
/skills/stand_up
/skills/sit
/skills/squat
/skills/damp
/skills/zero_torque
/skills/move_velocity
/skills/stop_move
/skills/high_stand
/skills/low_stand
/skills/wave_hand
/skills/shake_hand
```

然后 harness agent 不直接操作 SDK，而是输出：

```
{
  "skill": "move_velocity",
  "args": {
    "vx": 0.2,
    "vy": 0.0,
    "omega": 0.0,
    "duration": 2.0
  },
  "safety_checks": [
    "robot_is_standing",
    "no_human_in_front",
    "operator_confirmed"
  ]
}
```

### 这个路线的优点

| 优点              | 解释                                  |
| ----------------- | ------------------------------------- |
| 最安全            | 复用官方 high-level locomotion        |
| 最快落地          | 不需要自己写 29 关节控制              |
| 最适合 demo       | 可以展示自然语言 → 多 agent → G1 动作 |
| 出错容易 fallback | 失败就 `stop_move` / `damp` / `sit`   |
| 可迁移到 ROS2     | 后续可以包装成 ROS2 action            |

### 这个路线的缺点

| 缺点                    | 解释                           |
| ----------------------- | ------------------------------ |
| 行为能力受限            | 只能调用已有 high-level 功能   |
| manipulation 能力有限   | 抓取、双臂精细操作还要其他策略 |
| 不是真正 embodied agent | 更像 agentic control panel     |

------

## 路线 B：中级路线 —— **ROS2 Action + Unitree SDK2 / DDS bridge**

如果你想做一个更工程化、更长期的系统，我建议引入 ROS2 action。

ROS2 官方文档说明，Action 适合长时间任务，支持 goal、feedback、result，并且可以 cancel / preempt。

这正好适合机器人技能：

```
Task: walk_to_pose
Goal:
  target_pose: x, y, yaw
Feedback:
  current_pose
  progress
  safety_state
Result:
  success / failed / aborted
```

这样 harness 可以：

- 发起任务；
- 监控中间状态；
- 发现危险时 cancel；
- 执行失败时调用 recovery skill；
- 把执行轨迹写入 memory。

## 推荐 ROS2 Action 设计

```
g1_msgs/action/ExecuteSkill.action
# Goal
string skill_name
string skill_json
bool require_human_confirm
---
# Result
bool success
string final_state
string error_code
string error_message
---
# Feedback
string phase
float32 progress
string robot_state_json
string safety_state_json
```

然后你的 harness 只要做 action client：

```
harness_agent
   ↓
g1_skill_action_client
   ↓
g1_skill_action_server
   ↓
unitree_sdk2 / ROS2 DDS
   ↓
G1
```

这个路线特别适合你的多 agent 协作系统，因为每个 agent 都可以围绕 action 生命周期工作：

| Agent                   | 作用                          |
| ----------------------- | ----------------------------- |
| Task Planner Agent      | 把自然语言拆成 skill graph    |
| Skill Router Agent      | 选择调用哪个 skill            |
| Safety Agent            | 检查 skill 是否允许执行       |
| Perception Agent        | 读取 camera / state / map     |
| Execution Monitor Agent | 监听 feedback，判断是否继续   |
| Recovery Agent          | 失败时选择 stop / sit / retry |
| Memory Agent            | 存储成功/失败经验             |

------

## 路线 C：高级路线 —— **LeRobot / RL Policy / IsaacLab 作为技能库**

如果你未来想做更高级的 G1 embodied AI，比如：

- 看见物体；
- 走过去；
- 伸手抓取；
- 放到指定位置；
- 根据环境变化重新规划；

那就应该把 LeRobot / RL / IsaacLab 的 policy 也封装成 skill。

LeRobot 官方文档已经说明 G1 现在支持 teleoperation、locomanipulation policy 训练、sim 测试，并且支持 29 DoF 和 23 DoF 两种 G1 版本。

LeRobot 文档还给出了 G1 仿真安装、MuJoCo 依赖、`lerobot-teleoperate`、`GrootLocomotionController` / `HolosomaLocomotionController` 等控制器说明。

宇树自己的 `unitree_lerobot` 项目也说明，它是基于 LeRobot 改造的开源项目，用于训练和测试从 G1 双臂灵巧手采集的数据，并包含训练、数据处理、真机推理验证等目录。

这意味着你可以把 policy 也注册成 harness skill：

```
{
  "skill": "pick_place_policy",
  "policy": "g1_dex3_pick_red_block",
  "args": {
    "object": "red_block",
    "target": "blue_box"
  }
}
```

------

# 5. 推荐你采用的最终分层设计

## 5.1 五层架构

| 层级 | 名称                      | 负责什么                         | 关键技术                             |
| ---- | ------------------------- | -------------------------------- | ------------------------------------ |
| L5   | Human Interaction Layer   | 用户输入、语音、UI、确认         | Web UI / voice / keyboard / joystick |
| L4   | Harness Multi-Agent Layer | 任务理解、规划、安全、记忆       | 你的 harness / Codex agents / LLM    |
| L3   | Skill Orchestration Layer | 技能注册、权限、状态机、回滚     | ROS2 Action / FastAPI / gRPC         |
| L2   | Robot Adapter Layer       | 把 skill 翻译成 SDK/ROS/DDS 调用 | Unitree SDK2 / SDK2 Python / ROS2    |
| L1   | Controller / Policy Layer | 稳定执行动作                     | Built-in Loco / RL / LeRobot / PD    |
| L0   | Hardware / Sim Layer      | G1 真机或仿真                    | G1 / MuJoCo / IsaacLab               |

------

# 6. Harness 多 agents 应该怎么拆？

我建议你不要搞成“很多 agent 互相聊天”，而是做成 **任务状态驱动的 agent pipeline**。

## 6.1 推荐 agent 角色

### 1. `TaskUnderstandingAgent`

负责把用户语言变成结构化任务。

输入：

```
“让 G1 走到桌子前，向我挥手，然后坐下。”
```

输出：

```
{
  "intent": "demo_sequence",
  "steps": [
    {"skill": "stand_up"},
    {"skill": "move_velocity", "args": {"vx": 0.2, "duration": 3}},
    {"skill": "wave_hand"},
    {"skill": "sit"}
  ]
}
```

------

### 2. `SkillPlannerAgent`

负责把任务转换成可执行 skill graph。

```
{
  "graph": [
    {
      "id": "s1",
      "skill": "stand_up",
      "preconditions": ["robot_power_ok", "area_clear"],
      "postconditions": ["robot_standing"]
    },
    {
      "id": "s2",
      "skill": "move_velocity",
      "depends_on": ["s1"],
      "args": {"vx": 0.15, "vy": 0, "omega": 0, "duration": 2.0},
      "postconditions": ["robot_moved_forward"]
    },
    {
      "id": "s3",
      "skill": "wave_hand",
      "depends_on": ["s2"]
    }
  ]
}
```

------

### 3. `SafetySupervisorAgent`

这是最重要的 agent。

它不应该只是 LLM 判断，而应该结合规则引擎：

```
rules:
  - low_level_control_requires_simulation_first: true
  - max_forward_velocity_demo: 0.2
  - max_yaw_velocity_demo: 0.3
  - require_human_confirm_for_motion: true
  - forbid_motion_if_person_distance_lt_m: 1.5
  - forbid_lowcmd_from_llm: true
  - require_stop_skill_available: true
```

输出：

```
{
  "approved": false,
  "reason": "move_velocity requires human confirmation and area_clear sensor check",
  "required_checks": [
    "operator_confirm",
    "front_camera_clear",
    "robot_balance_ok"
  ]
}
```

------

### 4. `PerceptionAgent`

负责从 camera / depth / lidar / state 里抽象环境状态。

可以接：

- `teleimager`；
- RealSense；
- G1 自带相机；
- MuJoCo/IsaacLab camera；
- VLM；
- SLAM / map；
- object detector。

宇树官方 GitHub 页面中 `teleimager` 被描述为可以从 UVC、OpenCV、RealSense 捕获多路视频流，并通过 ZeroMQ 或 WebRTC 发布。

注意：如果你用 `unitree_mujoco` 做 SLAM 或视觉仿真，要小心它的传感器能力限制。一个 2026 年 1 月的 issue 中，用户提到当时 MuJoCo 里主要只暴露 joint states，想获取 camera / lidar 信息用于 SLAM 还存在困难。

------

### 5. `ExecutionMonitorAgent`

负责监听执行结果。

它应该订阅：

```
robot_state
skill_feedback
lowstate_summary
imu_summary
battery_state
network_latency
safety_events
```

它做的事情：

```
if robot_tilt_angle > threshold:
    cancel current action
    execute stop_move
    execute damp or sit
    notify operator
```

------

### 6. `RecoveryAgent`

负责失败恢复。

比如：

| 失败类型               | 恢复策略                          |
| ---------------------- | --------------------------------- |
| skill timeout          | stop → retry once → abort         |
| robot unstable         | stop_move → balance_stand → sit   |
| perception lost object | pause → rescan → ask user         |
| network delay too high | stop → disable physical execution |
| policy output abnormal | switch to safe pose               |

------

### 7. `MemoryAgent`

负责积累可复用经验。

例如：

```
{
  "task": "wave_hand_demo",
  "environment": "lab_room",
  "successful_sequence": [
    "stand_up",
    "move_velocity(vx=0.1,duration=1.5)",
    "wave_hand",
    "sit"
  ],
  "failure_notes": [
    "Do not wave while walking",
    "Need 1.5m free space in front"
  ]
}
```

这正是 harness 的强项：**把机器人执行过程变成可检索、可复盘、可复用的经验库**。

------

# 7. 你应该如何接入开源库？

## 7.1 最小可行版本：先接 `unitree_sdk2_python` 或 C++ SDK2

你可以做一个 `g1_skill_server`：

```
g1_skill_server/
  app.py
  skills/
    stand_up.py
    sit.py
    stop_move.py
    move_velocity.py
    wave_hand.py
  adapters/
    unitree_loco_adapter.py
  safety/
    rules.yaml
    safety_checker.py
  state/
    robot_state_store.py
```

API 设计：

```
POST /skills/execute
GET  /skills/{task_id}
POST /skills/{task_id}/cancel
GET  /robot/state
POST /robot/emergency_stop
```

请求：

```
{
  "skill": "move_velocity",
  "args": {
    "vx": 0.1,
    "vy": 0.0,
    "omega": 0.0,
    "duration": 2.0
  },
  "source": "harness",
  "requires_confirmation": true
}
```

返回：

```
{
  "accepted": true,
  "task_id": "skill_20260506_001",
  "status": "running"
}
```

------

## 7.2 Harness 侧只暴露“安全工具”，不要暴露 LowCmd

你的 harness tool registry 应该这样设计：

```
[
  {
    "name": "g1_stand_up",
    "risk": "medium",
    "requires_confirmation": true
  },
  {
    "name": "g1_stop",
    "risk": "low",
    "requires_confirmation": false
  },
  {
    "name": "g1_move_velocity",
    "risk": "high",
    "requires_confirmation": true,
    "limits": {
      "max_vx": 0.2,
      "max_vy": 0.1,
      "max_omega": 0.3,
      "max_duration": 3.0
    }
  },
  {
    "name": "g1_lowcmd_raw",
    "enabled": false,
    "reason": "Never expose raw motor command to LLM/harness."
  }
]
```

非常关键：

> **LLM / agent 永远不应该拿到 `LowCmd` 原始写入权限。**

------

# 8. 仿真验证路线

## 8.1 先用 `unitree_mujoco`

`unitree_mujoco` 是基于 Unitree SDK2 和 MuJoCo 的仿真器，官方 README 说明它可以让基于 `unitree_sdk2`、`unitree_ros2`、`unitree_sdk2_python` 开发的控制程序接入仿真，从而更平滑地从仿真过渡到真机。

但它当前更适合 **low-level controller 的 sim2real 验证**，README 也说明当前版本主要支持 low-level development，支持的消息包括 `LowCmd`、`LowState`、`SportModeState`、G1 的 `IMUState`。

因此你可以这样做：

```
harness
  ↓
skill_server
  ↓
unitree_sdk2_python adapter
  ↓
unitree_mujoco
  ↓
观察 lowstate / imu / robot state
```

适合验证：

- skill 调用顺序；
- stop / cancel / timeout；
- 状态监控；
- 日志；
- agent planning；
- safety rule。

不适合一开始就验证：

- 高精度视觉抓取；
- SLAM；
- 复杂传感器融合；
- 全身灵巧操作。

------

## 8.2 更高级用 `unitree_sim_isaaclab`

`unitree_sim_isaaclab` 是基于 IsaacLab 的仿真环境，官方说明它用于任务仿真、数据采集、回放、生成和模型验证，并采用和真机相同的 DDS 通信协议；它还提供 G1/H1-2 多种任务场景，包括 pick-place、stack 等。

所以：

| 目标                                      | 推荐仿真                   |
| ----------------------------------------- | -------------------------- |
| 测试 SDK2 / lowcmd / state loop           | MuJoCo                     |
| 测试 pick-place / manipulation / 数据生成 | IsaacLab                   |
| 测试 LeRobot policy                       | LeRobot G1 sim             |
| 测试 harness 多 agent 流程                | 三者都可以，先 MuJoCo 最快 |

------

# 9. RL / policy 这层应该怎么和 harness 连接？

宇树 `unitree_rl_gym` 的基本流程是：

```
Train → Play → Sim2Sim → Sim2Real
```

官方 README 对这四步的解释是：先在 Gym 中训练 policy，再 Play 验证，再 Sim2Sim 放到其他仿真器检查不是过拟合 Gym 特性，最后 Sim2Real 部署到实体机器人。

这说明你的 harness 不应该替代 RL policy，而应该调用 policy：

```
harness:
  “走到桌边”
      ↓
navigation / locomotion skill:
  调用已训练 policy 或官方 loco
      ↓
controller:
  每 2ms / 高频控制
```

## 正确接口形式

```
{
  "skill": "locomotion_policy",
  "policy_id": "g1_flat_walk_v1",
  "command": {
    "vx": 0.15,
    "vy": 0.0,
    "yaw_rate": 0.1
  },
  "duration": 2.0
}
```

## 错误接口形式

```
{
  "lowcmd": {
    "motor_0": {"q": 0.2, "kp": 60},
    "motor_1": {"q": -0.1, "kp": 60}
  }
}
```

------

# 10. 一个可落地的开发计划

## Phase 1：纯仿真 harness demo

目标：

```
自然语言 → 多 agent 规划 → skill JSON → MuJoCo / fake robot 执行 → 日志复盘
```

实现：

```
harness/
  agents/
    task_planner.py
    safety_supervisor.py
    skill_router.py
    execution_monitor.py
  tools/
    g1_skill_client.py
  memory/
    episode_store.py

g1_skill_server/
  adapters/
    fake_adapter.py
    mujoco_adapter.py
  skills/
    stand_up.py
    move_velocity.py
    wave_hand.py
    sit.py
    stop.py
```

先不用真机。

------

## Phase 2：接 G1 high-level loco

目标：

```
harness 只调用 high-level safe skills
```

技能：

```
stand_up
sit
squat
balance_stand
move_velocity
stop_move
wave_hand
shake_hand
```

安全规则：

```
所有运动技能必须 operator confirm
所有速度限制在 demo safe range
所有任务执行前检查 robot state
任何异常立即 stop_move
```

------

## Phase 3：接 ROS2 Action

目标：

```
把每个技能变成 ROS2 action server
```

结构：

```
g1_bringup
g1_skill_server
g1_state_monitor
g1_safety_monitor
g1_harness_bridge
```

harness 只做 action client。

------

## Phase 4：接 perception

目标：

```
G1 能根据视觉状态执行任务
```

接入：

- teleimager / RealSense；
- object detection；
- VLM scene caption；
- 近距离安全检测；
- object pose estimation。

------

## Phase 5：接 LeRobot / RL policy

目标：

```
任务级 agent + skill-level policy
```

例如：

```
“把红色积木放到盒子里”
    ↓
TaskPlannerAgent
    ↓
PerceptionAgent 找红色积木
    ↓
SkillPlannerAgent 选择 pick_place_policy
    ↓
SafetySupervisorAgent 检查人和障碍物
    ↓
LeRobot / IsaacLab trained policy 执行
    ↓
ExecutionMonitorAgent 监控
```

------

# 11. 我建议你的第一个 demo 做什么？

我建议你第一个 demo 不要做复杂抓取，而是做：

## Demo：**Natural Language Controlled G1 Skill Orchestration**

用户说：

```
G1，请进入演示模式，向前走一点，停下，挥手，然后坐下。
```

harness 输出：

```
{
  "task_name": "g1_intro_demo",
  "steps": [
    {"skill": "stand_up", "requires_confirmation": true},
    {"skill": "move_velocity", "args": {"vx": 0.1, "vy": 0, "omega": 0, "duration": 2}},
    {"skill": "stop_move"},
    {"skill": "wave_hand"},
    {"skill": "sit"}
  ],
  "safety_policy": {
    "max_vx": 0.2,
    "require_operator_confirm": true,
    "abort_on_instability": true
  }
}
```

然后 ExecutionMonitor 实时显示：

```
[Planner] Task decomposed into 5 skills
[Safety] Approved after operator confirmation
[Skill] stand_up started
[Skill] stand_up completed
[Skill] move_velocity started
[Monitor] robot stable, vx=0.1
[Skill] stop_move completed
[Skill] wave_hand completed
[Skill] sit completed
[Memory] demo saved as successful episode
```

这个 demo 的价值非常强，因为它展示的是：

> **LLM/harness 不是“聊天机器人”，而是一个能安全调度实体机器人的 agentic operating system。**

------

# 12. 关键风险与规避方案

| 风险            | 具体问题                       | 规避方案                                     |
| --------------- | ------------------------------ | -------------------------------------------- |
| Agent 误判      | LLM 可能选择危险动作           | 所有动作必须过 SafetySupervisor              |
| 实时性不足      | agent 不能 2ms 控制            | agent 只做 skill-level 调度                  |
| 真机摔倒        | 速度/姿态/地面不稳定           | 初期只用 high-level loco，低速，空旷场地     |
| 仿真到真机差距  | MuJoCo/IsaacLab 不等于真实世界 | 先 Sim2Sim，再小范围真机                     |
| 视觉不稳定      | 物体识别错误                   | perception 输出置信度，低置信度不执行        |
| 多 agent 冲突   | planner 说走，safety 说停      | safety agent 拥有最高优先级                  |
| 网络延迟        | laptop 控制真机不稳定          | 本地 skill server 尽量跑在机器人侧或同局域网 |
| raw LowCmd 暴露 | 极危险                         | 永远不作为 harness tool 暴露                 |

------

# 13. 最推荐的实现路径

你的情况，我建议这样做：

```
第一步：harness + fake G1 adapter
第二步：harness + unitree_mujoco
第三步：harness + G1 high-level LocoClient
第四步：封装 ROS2 Action Server
第五步：接 teleimager / camera perception
第六步：接 LeRobot / IsaacLab manipulation policy
第七步：做 memory + self-debug + skill library
```

最终你要做的不是一个简单控制程序，而是：

> **G1 Agentic Skill OS**
>  一个让 G1 可以被自然语言、多 agent、记忆、技能库、安全策略共同驱动的 embodied AI 框架。

这条路线非常值得做，而且比“单纯让 LLM 控制机器人”高级很多。它的核心竞争力不是某个动作，而是：

1. **任务拆解能力**；
2. **多 agent 协同能力**；
3. **技能库调用能力**；
4. **仿真验证能力**；
5. **真机安全执行能力**；
6. **长期记忆与经验复用能力**。