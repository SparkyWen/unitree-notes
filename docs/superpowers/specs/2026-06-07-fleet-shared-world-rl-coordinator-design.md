# 设计：双 G1 共享世界 · 分层 AI 调度 · 会合接力

> 状态：草案，待用户评审
> 日期：2026-06-07
> 关联：`docs/coordinator-design.md`（总体架构）、`g1_brain/g1_brain/fleet/`（现有 fleet 代码）

## 1. 目标与背景

把现有的 fleet coordinator 演示升级到用户的最终目标：

1. **同一个世界、彼此感知**：两台 G1 在**一个 MuJoCo 世界、一个窗口**里，真实共享物理（靠近会真碰撞），能感知对方相对位置。
2. **文字指令 + OpenAI 智能调度**：仪表盘像聊天框一样接收自然语言，coordinator 用**自己的 OpenAI API** 拆解意图并调度。
3. **分层子 agent + 彼此配合**：coordinator 大脑把任务**分别委派给每台机器人的子 agent**，子 agent 各自规划并通过协调协议**配合**完成一个**会合 / 接力**任务。

### 1.1 已锁定的决策（来自评审对齐）

| 维度 | 决策 |
|---|---|
| 共享世界 | 单一 MjModel（`MjSpec.attach` 合两台 G1）、一个 viewer 窗口、真实共享物理 |
| 移动方式 | **RL 真步态**：接入 `unitree_rl_mjlab` 速度跟踪策略（ONNX），每机一份策略实例 |
| 调度形态 | **分层子 agent**：`FleetCommander`（OpenAI 拆解）→ 每机 `RobotSubAgent`（OpenAI 会话）→ 确定性协调 barrier |
| 配合场景 | **会合 / 接力**：两机各自走到会合点，barrier 同步后把巡逻任务从 a 交接给 b |
| 交付 | 一份写全 P1+P2+P3 的分阶段 spec；按 P1→P2→P3 顺序实现，各阶段独立可验证 |

### 1.2 现状关键缺口

- `fleet/agent/motion/base.py` 的 `Posture` 只有 `ACTIVE / PATROL(摆肘) / SLEEP / WAKE / IDLE / STOP`——**全是原地姿势**。
- 机器人被绑带悬吊在固定锚点（`fleet/sim/mujoco_world.py`），`HarnessCore.get_state` 里 `pose=None`——**没有位置、不会移动**。
- DDS demo（`verify_dds_fleet.py`）跑**两个独立 MjModel**（domain 1/2），两窗口互不可见。
- 仪表盘（`coordinator/dashboard.py`）**只有按钮**；`OpenAIChatLLM` 只把一句话解析成**单个 op**，没有多机计划、没有子 agent。

→ 会合/接力**强制**补齐：导航（会走）、位置（pose）、互相感知（neighbor sense）、多机 LLM 规划、确定性协调。

## 2. 复用的现成资产

| 资产 | 路径 | 用途 |
|---|---|---|
| G1 速度策略（ONNX） | `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx` | 98 维 obs → 29 维动作；`onnxruntime` CPU 推理，无需 torch |
| 部署参数 | `.../velocity/v0/params/deploy.yaml` | Kp/Kd、action scale/offset、default_q、step_dt=0.02(50Hz)、命令范围 vx∈[-0.5,1.0] vy∈[-0.5,0.5] wz∈[-1,1]、gait_period=0.6 |
| 单机参考实现 | `g1_sim_demo/g1_sim_rl_combo.py` | obs 构造 + 策略环 + 手臂叠加；抽取出可复用单机 `G1VelocityPolicy` |
| 子进程隔离教训 | `g1_brain/safety/combo_proxy.py` | 50Hz 控制环与 LLM/感知**必须隔离**，否则 GIL 争用 ~12s 摔倒 |
| fleet 骨架 | `fleet/bus/*`（WS 总线）、`fleet/coordinator/{controller,gateway,dispatch,registry,event_log,anomaly,lease}.py`、`fleet/contracts/models.py`、`fleet/agent/{robot_agent,sim_harness,admission_gate}.py` | 安全门 / 审计 / 注册表 / 命令信封照旧复用 |
| OpenAI 适配 | `fleet/coordinator/agent_llm.py`（`OpenAIChatLLM`） | 扩展为结构化多机计划 + 子 agent |

## 3. 总体架构（进程模型）

RL 真步态的 50Hz deadline 约束决定了进程划分（见 §6 风险①）。"单一共享世界"指**一个 MjModel、一个窗口**——但**控制环与 LLM 必须分进程**。

```
┌────────────────────────── Coordinator 进程（无 50Hz 实时约束）──────────────────────────┐
│  aiohttp app (现 coordinator/app.py 扩展)                                               │
│   ├── 仪表盘 + 新增聊天卡片  ──POST /chat {nl}──►                                         │
│   ├── FleetCommander (OpenAI)   意图 → FleetPlan（多机角色 + 协调契约）                    │
│   ├── RobotSubAgent × N (OpenAI 会话)  每机目标 → 校验过的 op 序列                         │
│   ├── RendezvousBarrier / Blackboard  确定性协调（两边到达才放行交接）                      │
│   └── DispatchController + CommandGateway + DispatchEngine + EventLog（全部复用）          │
└───────────────────────────────────┬────────────────────────────────────────────────────┘
                                     │  WS 总线 (fleet/bus)：CommandEnvelope 下行 / 遥测 + admission 上行
┌───────────────────────────────────▼──────────────────────── World Sim 进程（50Hz 隔离）──┐
│  共享 MjModel（MjSpec.attach 合 g1_a + g1_b，一个 floor / 一个窗口）                       │
│   ├── 控制线程 @50Hz（专用线程，MuJoCo / ONNX 调用释放 GIL）                               │
│   │     for rid in (a,b): obs←_build_obs(MjData slice) → policy(rid) → q_target → ctrl     │
│   │     nav 外环：pose 误差 → 速度指令[vx,vy,wz]（夹到策略范围）→ 作为 obs 的 cmd            │
│   │     mj_step(共享模型) ；neighbor sense（两机相对位姿）；thermal(tau)                     │
│   ├── 每机 RobotAgent + AdmissionGate + LocalPlanner（轻量，非 LLM）                       │
│   │     接受的 CommandEnvelope → 控制环 setpoint（nav goal / posture）                      │
│   └── mujoco.viewer.launch_passive 窗口（关阴影/反射，WSLg 屏显）                           │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

关键点：
- **OpenAI 调用全部在 Coordinator 进程**，绝不进 World Sim 的 50Hz 路径。
- World Sim 进程只跑：物理 + 双策略 + nav 外环 + 轻量 admission/agent + viewer。50Hz 控制放**专用线程**；asyncio 总线在主线程；两者用线程安全的 setpoint/telemetry 缓冲通信。若仍抖动，回退到**子进程**跑控制环（combo_proxy 模式）。
- 安全门（AdmissionGate）贴近机器人（在 World Sim 进程），是本地最终裁决，符合 `docs/coordinator-design.md` 原则。

## 4. Phase 1 — 共享世界 + 双机 RL 真步态 + 导航 + 互相感知 + viewer

**目标**：证明"两台 RL G1 在同一个 MjModel 里、50Hz 不摔、能各自导航到点、会合不撞、能互相感知"。先用程序接口 + 现有按钮驱动，不依赖 LLM。

### 4.1 共享世界 `fleet/sim/shared_world.py`（新）

- 用 `mujoco.MjSpec`：加载 `unitree_mujoco/unitree_robots/g1/g1_29dof.xml` 子 spec，`attach` 两次，前缀 `g1_a/`、`g1_b/`，附着帧分别置于 `(-1.5, 0)`、`(+1.5, 0)`；父 spec 提供 `scene_29dof.xml` 的 floor（保留 `friction/condim=6/priority=1`，见 MJCF 注释 QA5 防滑）、灯光、skybox。`compile()` → 单一 `MjModel`（2×(7+29) qpos、2×29 actuator）。
- `RobotSlice` 数据类：每机的 `qpos_adr`（free joint 起点）、关节切片、actuator 切片、torso/pelvis body id、IMU/sensor 名（实现期核对 attach 后命名）。
- API：`set_ctrl(rid, q_target)`、`base_pose(rid)→(x,y,yaw)`、`base_angvel(rid)`、`base_quat(rid)`、`joint_state(rid)→(q,dq)`、`tau_est(rid)`、`gravity_proj_z(rid)`、`neighbors(rid)→[(peer,dx,dy,dist,bearing)]`、`step(n)`、`viewer_sync()`。
- 初始 qpos：每机 base 抬到站立高度、`default_q`（来自 deploy.yaml）；**去掉绑带**（RL 策略自己维持平衡，不再悬吊）。

### 4.2 单机策略 `fleet/sim/rl_policy.py`（新，抽取自 `g1_sim_rl_combo.py`）

- `G1VelocityPolicy(cfg_path, onnx_path)`：持有 `onnxruntime` session、`default_q/action_scale/kp/kd`、`global_phase`、`last_raw_action`。
- `build_obs(world, rid, cmd)`→98 维：`[base_ang_vel(3) | projected_gravity(3) | cmd[vx,vy,wz](3) | gait_phase sin/cos(2) | joint_pos_rel(29) | joint_vel_rel(29) | last_action(29)]`。从 **MjData 直接构造**（base_ang_vel←free joint 角速度转体坐标；projected_gravity←base quat 逆旋 `[0,0,-1]`；`gait_phase` 每 tick += step_dt/gait_period，`‖cmd‖<0.1` 时清零）。
- `act(obs)`→`q_target = raw*action_scale + default_q`；缓存 `last_raw_action`。
- 多机：实例化两份（各自 phase/last_action），obs 各自从对应 slice 构造。

### 4.3 导航外环 `fleet/sim/nav.py`（新）

- `nav_command(pose, goal, *, stop_radius, gains, ranges)`→`(vx,vy,wz)`：世界系位置误差 → 体坐标 → `vx=clip(k_fwd·e_fwd, vx_range)`、`vy=clip(k_lat·e_lat, vy_range)`、`wz=clip(k_yaw·heading_err, wz_range)`；`dist<stop_radius` 返回 `(0,0,0)`（策略转为站立）。所有命令**夹在策略训练范围内**（防 OOD）。
- 避撞：`dist_to_peer < safe_radius` 时缩放速度 / 暂停，避免两机真贴上去（贴上去对平地策略是 OOD，易摔）。

### 4.4 RL 运动后端 `fleet/agent/motion/rl_shared_backend.py`（新，实现 `MotionBackend`）

- 每机一个，包住 `SharedG1World` + 该机 `G1VelocityPolicy` + nav 外环。
- `set_posture(posture)`：`ACTIVE/IDLE/STOP`→cmd=0（策略站立）；`PATROL`→沿巡逻航点序列移动；`SLEEP`→crouch 覆盖（cmd=0 + 蹲姿 + 降刚度，沿用现有 SLEEP 语义）；`WAKE`→站立。
- 新增 `set_nav_goal(x,y)`：进入"走向目标"模式。
- `step()`：算 cmd（nav/patrol/0）→ `build_obs` → `act` → `world.set_ctrl`（由控制线程在 50Hz 调用）。
- `read_lowstate()`→`tau_est + gravity_proj_z`（喂 thermal / 异常检测，复用）。

### 4.5 契约与状态扩展（`fleet/contracts/models.py`）

- `Capability` 增加 `"navigate"`（payload `{x,y}`）。
- `Posture` 增加 `WALK`（导航中的步态显示态）。
- `RobotStateMsg`：填 `core.pose = Pose(x,y,theta)`；`extensions.neighbors = [{peer,dx,dy,dist,bearing}]`；`motion_state="moving"` 当 ‖vel‖>阈值。
- 语义事件：`peer_near`（进入感知半径）。

### 4.6 viewer 与启动器

- `fleet/sim/shared_world_node.py`（新）：World Sim 进程入口。`--viewer` 开 `launch_passive` 窗口（按内存 `mujoco_viewer_perf` / `wsl2_gpu_rendering`：关 shadow/reflection/MSAA，屏显走 WSLg）；连 coordinator WS。
- `MUJOCO_GL`：屏显默认 glfw；headless 验证用 egl。ONNX 用 CPUExecutionProvider（torch 非必需）。

### 4.7 Phase 1 验收

- headless：两机从 `(-1.5,0)/(+1.5,0)` 各自 `navigate` 到目标点，60s 全程 `gravity_proj_z<-0.85`（不摔）、`pose` 收敛到目标半径内、`neighbors` 正确、相向会合保持安全间距不相撞。
- `--viewer`：一个窗口里看到两台 G1 真步态走动 + 会合。

## 5. Phase 2 — 分层 AI 调度（聊天 → 大脑 → 子 agent → 协调）

**目标**：你在仪表盘打字 → coordinator 用 OpenAI 拆解 → 每机一个子 agent 规划 → 确定性 barrier 协调 → 经安全门下发到 Phase 1 的机器人。无 key 时回退确定性规则计划（沿用现有"无 key 也可用"原则）。

### 5.1 大脑 `fleet/coordinator/fleet_commander.py`（新）

- `FleetCommander(llm)`：输入 = 操作员 NL + 实时 fleet 快照（每机 pose/battery/health/当前任务 + 会合点等世界事实）。
- OpenAI **结构化输出** `FleetPlan`：
  ```json
  {
    "summary": "...",
    "coordination": {"type": "rendezvous|relay|cover|patrol|formation|none", "params": {"point": [x,y], "handoff_task": "patrol", "from": "g1_a", "to": "g1_b"}},
    "assignments": [{"robot_id": "g1_a", "role": "...", "objective": "..."}],
    "needs_clarification": null,
    "risk": "low|medium|high"
  }
  ```
- 确定性校验：robot_id/坐标/能力是否存在；不确定 → `needs_clarification`，不臆造（对应 coordinator-design §6.4）。

### 5.2 子 agent `fleet/coordinator/robot_subagent.py`（新）

- `RobotSubAgent(robot_id, llm)`：每机一个独立 OpenAI 会话；输入 = 自己的 objective + 本机状态 + 邻居信息 + 协调契约。
- 输出 = **校验过的 op 序列**：`[{op:"navigate",args:{x,y}}, {op:"await_barrier",args:{id}}, {op:"patrol"}, {op:"idle"} ...]`。
- 每个 op 走既有 `CoordinatorAgent.validate` + `CommandGateway` + AdmissionGate（LLM 提议、确定性裁决，绝不绕过安全门）。

### 5.3 协调 `fleet/coordinator/barrier.py`（新，确定性）

- `RendezvousBarrier(participants, release_when)`：子 agent 的 `await_barrier` 挂起；coordinator 从遥测判定"全部到达会合点半径内"→ 释放 → 触发交接（给 b 下 `patrol`、给 a 下 `idle`）。
- 时序由确定性原语保证，不靠 LLM 掐表 → 安全可解释（对应 coordinator-design §7 资源锁思想）。

### 5.4 路由与 UI

- `POST /chat {nl}`（`coordinator/app.py`）：跑 `FleetCommander.plan` → 起/复用 `RobotSubAgent` → 生成 op 序列 → `DispatchController` 带 barrier 下发 → 返回 transcript（计划 + 每机 op + 解释 + 校验结果）。
- 仪表盘 `dashboard.py` 新增**聊天卡片**：文本框 + 发送 + 对话流，渲染上面的 transcript，让"委派子 agent"过程可见。按钮保留（走 `/commands`）。

### 5.5 Phase 2 验收

- 输入一句中文/英文意图，返回结构化 FleetPlan + 每机子 agent 的 op；无效坐标/机器人被拒并给出原因；无 `OPENAI_API_KEY` 时回退规则计划仍能跑通。

## 6. Phase 3 — 会合 / 接力演示

- `fleet/sim/scenario_rendezvous.py`（新，+`--viewer`）：起 World Sim（两机分置）+ coordinator；脚本化操作员聊天："让 g1_a、g1_b 到中间会合，然后 a 把巡逻交给 b"。
- 流程：FleetCommander → rendezvous(M)+relay(patrol a→b) → 两子 agent 各自 navigate 到 M 附近（安全间距）→ barrier 同步 → **巡逻令牌可见地 a→b**（b 起步巡逻、a 转 idle）。
- 叠加自治：途中任一机 `inject` 过热 → 既有 anomaly→reassign 让健康机接管并走完路线（现在是"走过去"而非原地）。
- 验收：headless 断言（两机到 M 半径内 / barrier 触发 / 令牌 a→b / 全程站立 / 审计事件齐全）进 CI；`--viewer` 给人看。
- 一键启动器 `python -m g1_brain.fleet.sim.shared_world_demo --viewer`：开窗口 + coordinator + 仪表盘，你用聊天驱动。

## 7. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| ① | 50Hz 控制环被 LLM/HTTP 饿死 → 摔（combo_proxy 教训） | LLM 全在 coordinator 进程；控制环专用线程（MuJoCo/ONNX 释放 GIL）；抖动则回退子进程 |
| ② | 两机相向会合相撞 = OOD → 摔 | 会合点相邻非重叠 + 安全间距停车 + 避撞缩速 + 接触软化 |
| ③ | nav 速度超训练范围 → OOD | 速度指令一律夹到 deploy.yaml 的 vx/vy/wz 范围 |
| ④ | `MjSpec.attach` 前缀后命名/传感器错位 | 实现期核对 attach 后 body/joint/actuator/IMU 命名；obs 直接从 MjData 构造，不依赖 DDS bridge |
| ⑤ | WSL2 屏显/渲染 | viewer 关 shadow/reflection/MSAA（内存 `mujoco_viewer_perf`）；ONNX 走 CPU；屏显 WSLg |
| ⑥ | OpenAI 不可用 / 幻觉 | 无 key 回退确定性规则计划；LLM 输出全部 schema 校验 + 安全门；不确定走 needs_clarification |

## 8. 文件改动清单

**新增**
- `fleet/sim/shared_world.py`、`fleet/sim/rl_policy.py`、`fleet/sim/nav.py`、`fleet/sim/shared_world_node.py`、`fleet/sim/scenario_rendezvous.py`、`fleet/sim/shared_world_demo.py`
- `fleet/agent/motion/rl_shared_backend.py`
- `fleet/coordinator/fleet_commander.py`、`fleet/coordinator/robot_subagent.py`、`fleet/coordinator/barrier.py`
- 测试：`tests/fleet/test_shared_world.py`、`test_rl_policy.py`、`test_nav.py`、`test_fleet_commander.py`、`test_robot_subagent.py`、`test_barrier.py`、`test_scenario_rendezvous.py`

**修改**
- `fleet/contracts/models.py`（`navigate` 能力、`WALK` 姿态、`pose`/`neighbors` 字段、`peer_near` 事件）
- `fleet/coordinator/app.py`（`POST /chat`、装配 FleetCommander/subagents/barrier）
- `fleet/coordinator/dashboard.py`（聊天卡片）
- `fleet/coordinator/agent_llm.py`（结构化多机计划适配）
- `fleet/agent/motion/base.py`（`WALK`、`set_nav_goal` 扩展点）

## 9. 不在本设计范围（未来）

- 跨厂商 remote bridge / VDA5050 / Open-RMF（见 coordinator-design §8）。
- >2 台机器人、复杂 MRTA / 资源锁全集（§7）。
- 真实硬件部署、安全合规文档（§9、§14 Phase 6）。
- 把会合升级成真实碰撞/握手等高保真接触交互。

## 10. 实现顺序

P1（4.1→4.2→4.3→4.4→4.5→4.6→4.7 验收）→ P2（5.1→5.2→5.3→5.4→5.5 验收）→ P3（§6 验收）。每阶段独立可运行、独立验收，再进下一阶段。
