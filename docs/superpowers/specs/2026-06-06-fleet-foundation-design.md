# Fleet 底座 + 统一感知（Read-only）设计 Spec

> **状态**：已通过 brainstorming 评审，待用户复核 → writing-plans。
> **日期**：2026-06-06。
> **作者上下文**：本 spec 是 AI Coordinator 指挥调度中心的**第一个切片**。它以现有 `g1_brain` 单机 harness 为绝对主体，把 `docs/coordinator-design.md` 当作参考资料而非蓝图。
> **关系**：`docs/coordinator-design.md` 是理想化的企业级 AMR 车队蓝图（VDA5050/Open-RMF/WMS/MILP）；本 spec 是贴合 g1_brain 真实形态（语音优先人形 G1、sim 为主）的落地切片。冲突时以本 spec 为准。

---

## 0. 决策快照（brainstorming 结论）

| 维度 | 结论 |
|---|---|
| 机群形态 | 多个**同构 G1**、**sim 为主**（可能 1 台真机）。swarm 是真需求；跨厂商 bridge 暂为前瞻抽象 |
| 第一切片 | **Fleet 底座 + 统一感知**（read-only 地基），后续切片再走各自 spec |
| 脑拓扑 | **headless 核心 + 可附着脑**：车队机跑无脑 harness core，Realtime 快脑/codex 慢脑按"操作员聚焦"附着 |
| 世界拓扑 | **现在 N 个独立世界**（每机一个 domain/sim，不互相碰撞），设计**留共享世界的缝** |
| FleetBus 传输 | **方案 A：aiohttp WebSocket + JSON**（复用 phone bridge 模式，零新基础设施）；接口抽象，Scale 阶段可换 NATS/Redis |
| 重构力度 | **渐进包裹**：不动现有 `agent_main` 逻辑，新增薄 `HarnessCore` facade 暴露统一只读接口 |

---

## 1. 范围与非目标

### 1.1 本切片做（read-only 地基）

1. 能力/状态/事件**合约 schema**（`fleet/contracts/`）。
2. **HarnessCore facade**（渐进包裹现有 SkillServer/Safety/FSM/SceneState）。
3. **headless robot-agent**（新进程入口，不挂快脑/慢脑）。
4. **FleetBus**（WebSocket+JSON 实现 + 抽象接口）。
5. **Coordinator 只读服务**：FleetRegistry / StateAggregator / PerceptionAggregator / EventLog(append-only) / Replay。
6. **只读 Console**（轻量 web/TUI）。

### 1.2 本切片明确不做（但留版本化的缝）

- `CommandEnvelope` 派发与执行（**coordinator→电机零路径**）。
- swarm 调度 / MRTA / 资源锁 / 物理走位去冲突。
- 跨厂商 adapter（VDA5050 / Open-RMF / 厂商 SDK）。
- NL coordinator agent（自然语言→任务 DAG）。
- 上帝视角全局感知融合。
- 多机焦点切换的完整实现（只定义 attach/detach 接口）。

### 1.3 最强不变量

> 本切片从 **coordinator 到任何电机没有任何代码路径**。所有控制仍只经各机本地 `SkillServer → SafetySupervisor`。这是最安全的第一步，也是后续所有切片的基线。

---

## 2. 已确定的分层形态

```
┌─ Coordinator (read-only, 本切片) ──────────────────────────┐
│  FleetRegistry · StateAggregator · PerceptionAggregator    │
│  EventLog(append-only SQLite+JSONL) · Replay · 只读 Console│
└───────────────▲──────────────────────────────────────────┘
                │  FleetBus (北向, 独立于 DDS, WebSocket+JSON)
                │  ← RobotState 心跳 / 语义 RobotEvent / CapabilityDescriptor 注册
┌───────────────┴── Robot-Agent ×N (headless 装配) ─────────┐
│  HarnessCore = SkillServer + SafetySupervisor + RobotFsm   │
│               + watchdogs + perception + scene_state + combo│
│  (本切片只上报, 不收命令; 脑=可附着, 暂不接)                │
└───────────────▲──────────────────────────────────────────┘
                │  DDS (域=每机一个, 仅机器人内部)
          MuJoCo sim ×N (各自独立世界)
```

**关键约束（已核实）**：`unitree_sdk2py` 的 `ChannelFactoryInitialize(domain_id, interface)` 是**进程级全局**；stock `unitree_mujoco` 单机器人 `DOMAIN_ID=1`。因此多 G1 = **N 组独立 (sim+harness) 配对，每组一个 domain_id**；DDS 只做机器人内部，coordinator↔harness 必须走独立的 FleetBus（不复用 DDS）。

---

## 3. 合约（`fleet/contracts/`）

Pydantic 模型为权威源，CI 导出 JSON Schema 双产物。core 字段稳定且小，厂商私货进 `extensions`。

### 3.1 `CapabilityDescriptor.v1`

**自动从 `g1_brain/skills/tool_schemas.py` 导出**（不手写），保证与真实 tool 表一致。

```yaml
schema_version: CapabilityDescriptor.v1
robot_id: g1-sim-01
embodiment: { type: humanoid_g1 }
harness_version: <git describe>
trust_level: sim          # sim | dev | production_certified
frame_id: g1-sim-01/map   # 本切片各机独立 frame
capabilities:             # 从 tool_schemas 导出, name+params_schema+risk_level
  - { name: walk,    risk_level: medium, params_schema: walk.v1 }
  - { name: gesture, risk_level: low,    params_schema: gesture.v1 }
  # ... 21 个 tool
safety:
  e_stop: true
  local_obstacle_avoidance: true
  watchdogs: [lowstate, head_frame, pose]
brain:
  attachable: true        # 可附着快慢脑
  attached: false         # 本切片车队机默认 false
```

### 3.2 `RobotState.v1`

贴合现有 `SceneState` + `RobotFsm` + combo 共享内存 flags。

```yaml
schema_version: RobotState.v1
robot_id: g1-sim-01
ts: <iso8601>
seq: <monotonic>          # 单调序号, 供 stale/乱序检测
fsm_state: ENGAGED        # BOOT|STANDING|ENGAGED|ACTING|EMERGENCY_STOP|FAULT|RECOVERING
motion_state: idle        # idle|moving
core:
  pose: { frame_id: g1-sim-01/map, x, y, theta }   # sim 真值或里程计
  safety_state:
    e_stop: false
    geofence_ok: true     # 本切片恒 true (无 geofence), 预留
    gravity_proj_z: -0.98
    watchdog_ok: { lowstate: true, head_frame: true, pose: true }
  policy_active: true
  battery: null           # sim 无电量, 预留
extensions: { g1_sim: { mode_machine: 1 } }
```

### 3.3 `RobotEvent.v1`

统一事件信封；type 覆盖现有 `ConversationLogger.log_*`。

```yaml
schema_version: RobotEvent.v1
event_id: evt-<ulid>
trace_id: <session 或 turn id>
robot_id: g1-sim-01
type: scene_snapshot      # 见下表
ts: <iso8601>
payload_hash: sha256:...
payload: { ... }
```

| type | 来源 |
|---|---|
| `fsm_transition` | RobotFsm.transition 订阅者 |
| `safety_event` | SafetySupervisor / watchdog（含拒绝原因 RULE-N） |
| `action_result` | SkillServer 执行结果（含 outcome_metrics） |
| `scene_snapshot` | SceneStateBus 快照（语义, 非原始帧） |
| `perception.human_detected` | 阈值触发（nearest_person_m 越界） |
| `perception.obstacle_detected` | 阈值触发（nearest_obstacle_m / clear_path） |

### 3.4 预留缝（写 schema 占位，标 `status: reserved`，本切片不接）

`CommandEnvelope.v1` / `TaskSpec.v1` / `AdmissionDecision.v1` / `ResultRefusalEvent.v1` —— 字段参照 `docs/coordinator-design.md §5`，但仅作占位，无任何执行路径。

---

## 4. HarnessCore facade（渐进包裹，`harness_core/core.py`）

不改 `agent_main` 内部逻辑；新增薄 facade 组合已有对象并暴露统一只读接口。

```python
class HarnessCore:
    def __init__(self, *, skill_server, supervisor, fsm,
                 scene_bus, robot_bus, combo, cfg): ...

    def get_capabilities(self) -> CapabilityDescriptor   # tool_schemas + cfg 导出
    def get_state(self) -> RobotState                     # 聚合 fsm + scene + combo flags
    def get_safety_state(self) -> SafetyState
    def subscribe_events(self) -> AsyncIterator[RobotEvent]

    # 预留 (本切片 reserved, 调用 raise NotImplementedError):
    async def admit(self, env: "CommandEnvelope") -> "AdmissionDecision": ...
```

**事件 fan-out（零侵入）**：在 `ConversationLogger.log_*` 上加一个 fan-out 回调，把现有日志同时投到 `subscribe_events` 的内部队列。不改日志现有行为。

**导出一致性**：`get_capabilities` 直接读 `tool_schemas.py` 的 schema + `SafetySupervisor` 的 ALLOWED/risk 分类，避免合约与真实能力漂移。

---

## 5. Robot-Agent 装配（`fleet/agent/robot_agent.py`，headless）

与 `agent_main` 平行的新进程入口：

1. 解析 cfg（robot_id、domain_id、interface、coordinator ws url）。
2. 实例化 HarnessCore——**不挂 Realtime 快脑、不挂 codex 慢脑**（headless）。复用 agent_main 的 DDS/combo/perception/safety 初始化序列，但跳过 brain/memory/phone。
3. 连 FleetBus → `register(CapabilityDescriptor)`。
4. 周期 `heartbeat(RobotState)`（默认 2s，参照 phone keepalive 思路）。
5. 流式 `publish(RobotEvent)`（订阅 HarnessCore.subscribe_events）。
6. **本切片不收命令**：FleetBus 入向仅处理 `ping` / `attach 协商`（占位）。
7. 每进程绑自己的 DDS 域（domain_id 来自 cfg）。

---

## 6. FleetBus（`fleet/bus/`）

### 6.1 抽象接口

```python
class FleetBus(Protocol):
    async def register(self, cap: CapabilityDescriptor) -> None
    async def heartbeat(self, st: RobotState) -> None
    async def publish(self, ev: RobotEvent) -> None
    def subscribe(self, flt: EventFilter) -> AsyncIterator[RobotEvent]
```

### 6.2 WebSocket 实现（方案 A）

- coordinator 侧：aiohttp server `ws://…/fleet`（复用 `phone/bridge_server.py` 模式）。
- robot-agent 侧：client 主动外连，带**重连+指数退避**（照搬 `brain/realtime_agent.py` 的退避：1s→15s，capped）。
- 心跳超时 → coordinator 标该机 `stale`（阈值 cfg，默认 5s，对应 doc 的 `mark_robot_state_stale_after_sec`）。
- 消息为 JSON，含 `seq` 单调序号，coordinator 丢弃过期/乱序 state。
- backpressure：事件队列有界，满则丢最旧 `scene_snapshot`（保留 safety/action 事件）。
- Scale 阶段可换 NATS/Redis Streams 实现同接口（非本切片）。

---

## 7. Coordinator 只读服务（`coordinator/`）

- **FleetRegistry**：`robot_id → {CapabilityDescriptor, 最新 RobotState, last_seen, status}`；status ∈ `online|stale|offline`。
- **StateAggregator**：维护最新状态 + staleness 判定（心跳超时）。
- **PerceptionAggregator**：见 §8。
- **EventLog**：append-only **SQLite + JSONL**（复用 memory 子系统的存储模式）；按 `trace_id` / `robot_id` / 时间窗查询；replay 按 trace_id 回放事件时间线。
- **只读 API**：
  ```
  GET /robots
  GET /robots/{id}
  GET /events?trace_id=&robot_id=&since=&until=
  GET /replay/{trace_id}
  ```
- **只读 Console**：轻量 web 或 TUI——fleet 状态表 + 每机本地语义视图 + 事件时间线 + replay。先做能用即可，不追求成品 UI。

---

## 8. 统一感知（重点）

- 每机 HarnessCore 已产 `SceneState`（detections / nearest_obstacle_m / nearest_person_m / clear_path / human poses）。robot-agent 转成**语义 RobotEvent**（`scene_snapshot` + 阈值触发的 `human_detected`/`obstacle_detected`），**只传语义，不传原始帧**（doc 原则：中心不默认收所有视频/点云）。
- **PerceptionAggregator** = N 份本地语义视图聚合：每机最新 SceneState + 车队 roll-up（如"3 台 clear_path=false / 2 台附近有人"）。
- **共享缝**（"留共享缝"）：每个位置带 `frame_id` / `map_id`；定义 `FleetWorldModel` 接口：
  ```python
  class FleetWorldModel(Protocol):
      def to_global(self, robot_id: str, pose) -> GlobalPose   # 本切片 identity
      def fuse_detections(self, per_robot) -> FleetSpatialView # 本切片各机独立
  ```
  本切片只写接口 + identity 实现（各机独立 frame）。未来若同世界，按注册 transform（参照 doc §8.5 `map_transform`）融合成全局帧。
- **按需拉帧**：coordinator 可向"聚焦"的某机请求一张快照图（占位接口，类似 phone focus），绝不全量推流。

---

## 9. 可附着脑的缝（`harness_core`，本切片只定义接口）

把现有 `BrainRealtimeAgent`(快脑) + `MemorySubsystem`(慢脑) 抽象成 `OperatorBrainSession`，可 attach 到某机 HarnessCore 的 SkillServer：

```python
class OperatorBrainSession(Protocol):
    async def attach(self, core: HarnessCore) -> None
    async def detach(self) -> None
```

本切片：定义接口 + 让现有语音 `agent_main` 改用它装配（证明渐进包裹不破坏现状）。多机焦点切换留下一切片。

---

## 10. 保留的安全不变量（doc 不可破坏项）

1. `SafetySupervisor` 仍是唯一控制门。
2. 本切片 coordinator→电机**零路径**。
3. 每机 DDS 域隔离。
4. local refusal / admission 作为合约一等概念**预留**（`AdmissionDecision.v1`）。
5. 全程可追溯：每事件带 `trace_id` / `payload_hash` / 来源 / 时间戳。
6. 网络分区默认会发生：robot-agent 断开 coordinator 不影响本地安全（headless core 自治）。

---

## 11. 数据流（read-only）

```
HarnessCore.SceneState / FSM / ConversationLogger
   → robot-agent 转 RobotState / RobotEvent
   → FleetBus(WS) → Coordinator{Registry, StateAgg, PerceptionAgg}
   → EventLog(append-only) → Console / Replay
(无任何反向控制路径)
```

---

## 12. 测试

- **Unit**：合约 schema 校验 + 往返序列化；`get_capabilities` 与 `tool_schemas` 一致性；`get_state` 快照正确性。
- **FleetBus**：重连/指数退避；心跳超时→stale；乱序 `seq` 丢弃；backpressure 丢最旧 scene 保留 safety。
- **EventLog**：append + replay 幂等；trace_id 查询正确。
- **集成（端到端）**：先起 2~3 个 sim G1（各自 domain）→ 注册 → 心跳 → 感知语义事件 → Console 可见 → replay 与实况一致。
- **不变量测试**：静态/运行时断言 coordinator 无任何写向 SkillServer 的路径。

---

## 13. 模块布局

```
fleet/
  contracts/   # pydantic schemas + json schema 导出 + reserved 占位
  bus/         # FleetBus 接口 + ws 实现
  agent/       # robot_agent.py (headless 入口)
  console/     # 只读 UI/API
coordinator/   # registry / state_agg / perception_agg / event_log / replay
harness_core/  # core.py facade + OperatorBrainSession 接口 + FleetWorldModel 接口
```

（具体落在 `g1_brain/` 包内还是同级新包，writing-plans 阶段定。）

---

## 14. 复用清单（贴合现状的证据）

| 复用对象 | 现有位置 | 本切片用途 |
|---|---|---|
| SkillServer / SafetySupervisor / RobotFsm | `g1_brain/skills`, `g1_brain/safety` | HarnessCore 包裹 |
| SceneStateBus / SceneState | `g1_brain/scene_state/fusion.py` | RobotState + 感知事件 |
| ConversationLogger.log_* | `g1_brain/brain/conversation_logger.py` | RobotEvent fan-out 源 |
| tool_schemas | `g1_brain/skills/tool_schemas.py` | CapabilityDescriptor 自动导出 |
| aiohttp WebSocket bridge | `g1_brain/phone/bridge_server.py` | FleetBus WS 实现模式 |
| 指数退避重连 | `g1_brain/brain/realtime_agent.py` | robot-agent 重连 |
| SQLite + JSONL 存储 | `g1_brain/memory/storage.py` | EventLog append-only |
| combo 共享内存 flags | `g1_brain/safety/combo_proxy.py` | policy_active 等状态字段 |

---

## 15. 后续切片（各自再走 spec，本切片只留缝）

1. **批量指令派发**：`CommandEnvelope` 落地 + 本地 admission gate + 监控。
2. **真·swarm 协同**：任务分配 + 逻辑资源锁（→ 共享世界时加物理走位去冲突）。
3. **AI coordinator agent**：NL → TaskDAG → verifier → 派发 → 解释/重规划。
4. **跨厂商 remote bridge**：VDA5050 / Open-RMF / 厂商 adapter 实现 FleetBus 同接口。
5. **Scale & 安全合规**：NATS/Redis、zone coordinator、网络分区、SBOM/签名、IEC 62443/ISO 文档。
