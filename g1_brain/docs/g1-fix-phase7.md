# g1-fix-phase7 — 站不稳的真正修复 + 模仿功能下线

日期: 2026-05-06
分支: `fix/gestures`
前置: `g1-fix-phase6.md`（启动姿态、agent_main 起飞、手势表达性）

---

## 0. 阅读指南

这份文档**先讲清楚为什么 phase6 之后机器人还是站不稳**，再讲新一轮 4 处修复
分别解决了什么。如果你只想看修复，跳到第 §4 节；如果你想理解每一步推理，
按 §1 → §3 顺序读。文中所有时间戳都来自 2026-05-06 14:11–14:13 这次失败
跑产生的日志。

---

## 1. 操作员报告的症状

```
现在请您彻底给我修复我的机器人在没有任何指令下乱飞乱动的原因，
根本站不稳，只有我多次 reset 之后才能靠偶尔的运气站稳。
而且我希望目前机器人不要加入模仿功能。
```

具体表现：

1. **没有任何外部命令**（用户没说话、没敲键盘、未触发任何 LLM 工具调用）的
   情况下，机器人在 `agent_main` 启动后大约 7 秒开始倾斜，30 秒内倒地。
2. 多次 `Reset` MuJoCo 偶尔能"运气好"站稳一会儿，但仍然不可重复。
3. 用户**主动要求**关闭"实时模仿用户动作"功能（`mock_imitation`），未来再加。

phase6 已经修过 3 个相关问题（启动 sitting、policy 起飞、手势不到位），并且
那次修复在合并时 219 个 pytest 全过；可现场跑下来机器人还是站不稳。这意味着
phase6 没碰到的某个根因仍在。

---

## 2. 取证：日志时间线

下面这一段从用户发来的失败跑里抽取，按发生顺序排列：

```
14:11:14.159  waiting for first /rt/lowstate ...
14:11:14.264  waiting for ComboController policy_active ...
[combo]       mode_machine=0. Ramping to default pose over 5.0 s,
              then waiting for the robot to settle ...
14:11:20.292  fsm: BOOT -> STANDING (boot complete)
14:11:20.295  watchdog head_frame tripped: age=infs
14:11:20.297  watchdog usb_frame tripped: age=infs
14:11:20.299  watchdogs: started 6 threads
[combo]       policy engaged. wsadqe to walk; 1-8 arm gestures; 0 release.
14:11:20.596  fsm: STANDING -> ENGAGED (policy active)        ← T₀
14:11:25.604  fsm: ENGAGED -> EMERGENCY_STOP                  ← T₀+5s
              (watchdog head_frame: age=infs)
14:11:28.044  watchdog pose tripped: gravity_z=-0.77          ← T₀+7.4s 已倾 36°
14:11:28.549  watchdog pose cleared
14:11:39.119  watchdog pose tripped: gravity_z=-0.72
14:11:43.749  watchdog pose tripped: gravity_z=-0.68
14:11:47.627  watchdog pose tripped: gravity_z=-0.50          ← 已倾 60°
14:11:49.505  watchdog pose tripped: gravity_z=-0.78
14:11:49.909  watchdog pose tripped: gravity_z=-0.79
14:11:50.724  watchdog pose cleared
14:12:17.082  watchdog head_frame cleared                     ← 摄像头终于上线
14:12:22.364  fsm: EMERGENCY_STOP -> RECOVERING
14:12:22.367  fsm: RECOVERING -> STANDING (auto-recovery)
14:12:22.412  fsm: STANDING -> ENGAGED (policy active)        ← T₁ 重新接管
14:12:25.158  gesture auto-trigger started                    ← 此时才启动
14:12:25.162  connecting Realtime: wss://api.openai.com/...
14:12:51.775  watchdog pose tripped: gravity_z=-0.81          ← T₁+29s
14:12:52.298  fsm: ENGAGED -> EMERGENCY_STOP
              (watchdog pose: gravity_z=0.00)                  ← 完全倒地
```

`gravity_z` 是世界重力向量 (0,0,-1) 投影到机身坐标系后的 z 分量：
- `-1.0` ≈ 完美直立（机身 z 轴朝上，重力沿机身 -z）
- `-0.85` ≈ 倾斜 32°
- `-0.5`  ≈ 倾斜 60°
- `0.0`   ≈ 平躺
- `+1.0`  ≈ 倒立

所以 `gz` 从 `<-0.95`（接管时刻）一路飘到 `0.00`（倒地）。

### 关键观察

| 事件 | 时间 | 取证 |
|---|---|---|
| 策略接管 | T₀ = 14:11:20.6 | "policy engaged" 打印 + FSM `STANDING -> ENGAGED` |
| 第一次 pose trip | T₀ + 7.4s | `gravity_z=-0.77`，已经倾斜 36° |
| Realtime 连接 | T₀ + 64s | "connecting Realtime" |
| Auto-trigger 启动 | T₀ + 64s | "gesture auto-trigger started" |
| 完全倒地 | T₁ + 29s | `gravity_z=0.00` |

**第一次倾斜发生时，OpenAI Realtime 还没连上，gesture auto-trigger 还没启动，
LLM 没收到任何输入，更不可能调任何工具。** 也就是：
**晃动不是来自模仿、不是来自语音命令、不是来自任何外部输入；它纯粹来自
ComboController 的 RL 策略自身的输出。**

这个时间线推翻了用户最初的猜想（"以为是 mock_imitation 的问题"）——但同时
确认了用户对策略本身的怀疑。

---

## 3. 根本原因（Why phase6 没解决）

phase6 的修复是必要的但**不充分**。它解决了"策略接管时机器人状态 OOD"
（boot ramp 期间机器人在弹力带中央晃，接管时序乱）。但没有解决"策略接管
之后维持站立"。

下面把现存 4 个相互独立的根因拆开。

### 3.1 RL 速度跟踪策略在 `cmd=(0,0,0)` 时边际不稳

策略来自 `unitree_rl_mjlab/.../velocity/v0/policy.onnx`。它的训练目标是
"以 `cmd = (vx, vy, wz)` 为目标线/角速度跟踪行走"。零命令在训练分布的
角落，模型对它的处理是"几乎不动，但允许小幅平衡修正"。

在 mjlab + MuJoCo Warp 的训练环境里这个策略学得不错。但部署到 vanilla
MuJoCo 仿真里有几个细节差异：

* **接触模型不同**：MuJoCo Warp 用 GPU 接触求解，vanilla MuJoCo 用 CPU
  分析接触；同样的力矩，足底接触摩擦/法向力的瞬时响应略有差别。
* **积分误差累积**：仿真步长 5 ms，策略步长 20 ms。同一关节目标在两次
  策略推理之间被积分 4 次，累积的状态偏差进入下一次 obs。
* **数值精度**：onnxruntime CPU FP32 vs 训练时的 FP32 GPU，量化为 ONNX 时
  又有一轮舍入。这些都会被一个边际不稳的系统放大。

具体表现是：即使 `cmd=(0,0,0)`、`gait_phase=(0,0)`，策略仍输出
`raw_action ∈ ~[-0.5, +0.5]` 的非零值（不是高斯零均值）。这个值经过
`q_target = raw_action * action_scale + action_offset` 公式：
* 髋 pitch/yaw 的 `action_scale = 0.55 rad`，所以 `raw_action = 0.5` 给出
  `q_target = default_q ± 0.275 rad`（约 16°）
* 膝 `scale = 0.35 rad`，类似量级
* 踝 `scale = 0.44 rad`

每 20 ms 给腿一个 ±0.2 rad 的关节目标抖动，腿用 Kp=99（膝）来追，足部
力矩在 ±0.3 × 99 ≈ ±30 Nm 之间抖动。这个量级的抖动在 vanilla MuJoCo
接触模型下不能被踝关节摩擦稳定吸收，机身就开始小幅振荡。振荡放大后超出
策略训练分布，策略产生更大动作 → 正反馈 → 倒地。

**关键证据**：boot 期间 (`BOOT_DUR_S = 5s`) 用 `default_q` 全 Kp 死保持时
机器人是稳的（`gz` 一直 ≤ -0.95）。一接管，30 秒内必倒。说明 **stiffness
和接触本身能稳住机器人，是策略输出在搅局**。

### 3.2 phase6 的 engagement gates 太松

phase6 的接管门槛：
* `ENGAGE_GRAV_Z = -0.85`（最大允许倾角 ≈ 32°）
* `ENGAGE_HOLD_S = 0.8s`（这些条件连续保持的时长）
* `ENGAGE_POSE_TOL = 0.08 rad`
* `ENGAGE_VEL_TOL = 0.30 rad/s`

`-0.85` 这个阈值意味着只要倾角 ≤ 32° 就允许接管。32° 对一个站立姿态来说**已
经很倾斜了**——人在这个倾角时基本要靠迈步或扶东西才能恢复，不算"完美直立"。
更致命的是，这个阈值**和 watchdog 的 trip 阈值（`gravity_z_min = -0.85`）
完全相等**：

```
接管要求:    gz <= -0.85
watchdog:    gz >  -0.85  trip
```

也就是说，策略**刚一接管时机器人就处在 watchdog 触发线上**——只要策略下一
个 tick 让 `gz` 上飘 0.001，watchdog 立刻报警。phase6 加了 0.5s 的
`hold_down`，所以单个瞬态样本不会立刻 EMERGENCY_STOP，但策略**就在阈值
线附近"擦边"**地接管，本来就没有余量给它产生小的修正。

### 3.3 EMERGENCY_STOP 只是 FSM 簿记，没真停控制器

这是 phase6 没碰过的层。代码上 FSM 的状态转移和 ComboController 的
`_tick` 是**完全解耦**的：

```
WatchdogManager._tick_pose:
    if gz > gravity_z_min:
        self._set_trip("pose", ..., emergency=True)
            → fsm.transition(EMERGENCY_STOP, ...)

ComboController._tick (毫不知情):
    if not self._boot_done: ...
    if not self.policy_active: ...
    obs = self._build_obs()
    raw_action = self.policy(obs)        ← 继续推理
    q_target = ...                       ← 继续发布 lowcmd
    self._publish(q_target)              ← 机器人继续被驱动
```

也就是说，watchdog 把 FSM 切到 `EMERGENCY_STOP` 之后，**combo 控制器还在 50 Hz
推理 + 发布**。FSM 的作用只有"拒绝新的工具调用（walk / gesture / ...）"和
"驱动 auto-recovery"，它**不会让机器人安全停下**。

具体到日志里：14:11:25.6 `EMERGENCY_STOP` 之后，pose 还在不停 trip
（14:11:28、14:11:39、14:11:43、14:11:47、14:11:49…），就是因为 combo 还在
全速运行那个不稳的策略。

### 3.4 mock_imitation 不是元凶但用户不要它

用户怀疑模仿功能。从日志看：

| 事件 | 时间 |
|---|---|
| 第一次 pose trip | 14:11:28.044 |
| `gesture auto-trigger started` | **14:12:25.158** |

模仿模块比第一次倾斜**晚了 57 秒**才启动，因果上不可能是它造成的。但是
用户明确表态"现在不要这个功能，未来再加"，所以即使无关也要干净下线，避免
将来分析时再混淆。

---

## 4. 修复设计

下面的修复**保持 phase6 全部成果不变**，在它之上加补丁。一共 4 个独立小改
动，各自负责上面 4 个根因之一。

### 4.1 Stand-still bypass（解决 §3.1）

**核心思想**：既然 RL 速度策略在 `cmd=0` 时本来就不能稳，而 bridge 的
`G1_DEFAULT_KP` + `default_q` PD 在 STANDBY 阶段已经验证过能稳，那么
**在 cmd 为零时就用 PD，不要让策略接手**。策略只在用户真的想走（`cmd ≠ 0`）
时才推理。

具体改动 `g1_sim_demo/g1_sim_rl_combo.py` 的 `_tick`，在 POLICY 阶段加判断：

```python
# 50 Hz tick, POLICY 阶段
cmd = self.get_command()
cmd_norm = float(np.linalg.norm(cmd))
now = time.monotonic()

# 滞回：cmd 必须连续 STAND_HYST_HOLD_S 秒低于阈值才进 stand 模式
if cmd_norm < self.STAND_CMD_THRESH:        # = 0.08
    if self._stand_below_thresh_since is None:
        self._stand_below_thresh_since = now
    if (self._stand_active
            or (now - self._stand_below_thresh_since)
                >= self.STAND_HYST_HOLD_S):  # = 0.3s
        self._stand_active = True
else:
    # cmd 一上来就立刻进 walking 模式（无延迟）
    self._stand_below_thresh_since = None
    self._stand_active = False

if self._stand_active:
    # 旁路策略：直接发布 default_q
    q_target = self.cfg.default_q.copy()
    self.last_raw_action[:] = 0.0
    self.global_phase = 0.0       # 重置 gait 相位
else:
    # 标准 POLICY 路径：跑 ONNX 推理 + warm-up 渐入
    obs = self._build_obs()
    raw_action = self.policy(obs)
    ... # phase6 的 warm-up 逻辑保留
    q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
    self.last_raw_action[:] = raw_action
```

**为什么 0.08**：实际行走命令（`walk(vx=0.2)`）会让 `cmd_norm = 0.2`，远超
0.08。但 OpenAI Realtime 偶发的"空命令"（LLM 调 `walk(vx=0)` 或 `stop()`
的瞬间）也会触发。0.08 选在 `vy_max=0.1` 之下，确保走方向命令一定能进
walking 模式。

**为什么有 0.3s 滞回**：从 walking 切回 stand 时如果立刻切，brain 一句
"先走 0.5 米然后停"会出现一个瞬时 `cmd=0` 的真空窗口（命令切换之间），
策略应该继续完成轨迹而不是立即切回 PD。0.3s 比 walk 命令默认 0.5–1s 时长
小，比命令更替间隔大。

**进 walking 模式无延迟**：cmd 一旦从 0 跳到非零值，立刻让策略接管，否则
"前进"指令会卡住一拍。

**`global_phase = 0.0` 重置**：当从 stand 切到 walking 时，gait 相位从 0
开始，第一次 obs 的 `gait = (sin 0, cos 0) = (0, 1)`，是步态周期的标准
起点，避免 "stride mid-cycle restart" 引起的乱迈步。

**`last_raw_action[:] = 0` 重置**：obs 里有一个 29D 的 `last_action` 槽位，
策略在 stand 模式下没推理过任何动作，下次接管时这个槽位应该是 0（"上一次
命令什么都不做"），保持 obs in-distribution。

**为什么不在 stand 模式下也跑一次策略推理（仅用于保持 obs 历史）**：策略是
MLP，**没有循环状态**——`history_length` 在 `deploy.yaml` 里全 = 1，意味着
每次推理只看当前一帧 obs，不依赖前一帧。所以跳过推理对策略本身无副作用。
省下 50 Hz 的一次 ONNX 推理也是 CPU 收益。

**手势如何处理**：手势是覆盖 `q_target[15:29]` 的 14 个臂关节，腿/腰仍由
combo 控制。stand 模式下手势的 arm overlay 路径和 phase6 一致：
```python
arm_q = self._advance_arms()
if arm_q is not None:
    q_target[ARM_START:ARM_END] = arm_q
```
而**腿/腰此时的 `q_target = default_q`**，PD 全 Kp 锁住——比让策略带动腰
跟着挥手响应更稳定。挥手时机器人的整体响应是"腿不动、腰不动、只有手在动"，
这正是用户希望看到的"挥手不会摔倒"行为。

### 4.2 收紧 engagement gates（解决 §3.2）

```python
# 旧：phase6
ENGAGE_GRAV_Z  = -0.85   # 32° 倾角
ENGAGE_HOLD_S  =  0.8

# 新：phase7
ENGAGE_GRAV_Z  = -0.95   # 18° 倾角
ENGAGE_HOLD_S  =  1.5
```

* `gz <= -0.95` 等价于"机身 z 轴和世界 -z 之间夹角 ≤ 18°"，这是**真正的
  直立姿态**，不是"近似直立"。`cos(18°) ≈ 0.951`，所以 -0.95 是几乎贴着
  18° 的紧界。
* `1.5s` 让机器人有充足时间静止下来，过滤掉弹力带刚松开瞬间的低频晃动。
* 还有一个 `ENGAGE_TIMEOUT_S = 30s` 的超时兜底（phase6 已有，未变）：
  万一门槛永不通过，30 秒后强制接管并 log，避免无限挂住。

值得说明的是：**现在即使接管了策略，stand-still bypass 也会让控制器立刻
回到 `default_q` 模式**。所以接管的成功更多是"开放策略接管的权限"，而不是
"立刻交给策略开始跑"。这两个机制叠加之后，从用户视角看："policy engaged
(idling on default_q)"——策略可用，但不动手。

### 4.3 Safe-hold：让 EMERGENCY_STOP 真正停控制器（解决 §3.3）

新增 `ComboController.set_safe_hold(active: bool)`。`_tick` 里在所有路径
**最前面**插一个早返：

```python
def _tick(self):
    if self._stop.is_set() or not self.first_state_received:
        return
    ... 软化 Kp ramp ...
    ... LOWSTATE_TIMEOUT 看门狗 ...

    # NEW: safe-hold 早返
    if self._safe_hold:
        q_des = self.cfg.default_q.copy()
        self.kp_scale = 1.0                    # 强制满 Kp
        arm_q = self._advance_arms()           # 仍允许 release_arms 平滑收回
        if arm_q is not None:
            arm_q = self._clamp_arm_to_safe_envelope(arm_q)
            arm_q = self._rate_limit_arm_step(arm_q)
            q_des[ARM_START:ARM_END] = arm_q
        self._publish(q_des)
        self._last_arm_q_published = q_des[ARM_START:ARM_END].copy()
        return                                 # 跳过 BOOT/STANDBY/POLICY

    if not self._boot_done: ...
    ...
```

也就是说 safe_hold=True 时：
* **完全绕开**策略推理
* 全 Kp 主动驱动到 `default_q`（不是零力矩——零力矩会让机器人瘫倒，全 Kp 会让它**重新站起来**）
* 仍然处理任何排队的 `release_arms()` 让臂关节平滑回到 rest

然后在 `g1_brain/safety/watchdogs.py` 的 `WatchdogManager._on_fsm_transition`
（订阅 FSM 转移的钩子）里**接两根线**：

```python
def _on_fsm_transition(self, old, new, reason):
    if old == RECOVERING and new == STANDING:
        # phase6 已有：自动恢复后重置 boot grace
        self._started_at = time.monotonic()

    # NEW: combo safe-hold 切换
    if self.combo is not None and hasattr(self.combo, "set_safe_hold"):
        if new == EMERGENCY_STOP:
            self.combo.set_safe_hold(True)
        elif old == EMERGENCY_STOP:
            self.combo.set_safe_hold(False)
```

这样全链路是：

```
pose 倾斜过大
    → watchdog._tick_pose 判 trip
    → fsm.transition(EMERGENCY_STOP)
    → fsm 通知所有订阅者 (含 watchdog 自己的 _on_fsm_transition)
    → watchdog 调 combo.set_safe_hold(True)
    → 下一次 combo._tick 走 safe-hold 早返，发 default_q 满 Kp
    → 机器人开始往直立姿态回拉
    → gz 慢慢回到 -0.95 以下
    → recovery_hold_s = 5s 之后 watchdog auto-recover
    → fsm: EMERGENCY_STOP -> RECOVERING -> STANDING
    → fsm 通知所有订阅者
    → watchdog 调 combo.set_safe_hold(False)
    → combo 恢复正常 _tick；stand-still bypass 让它继续守 default_q
    → 直到下一次 walk 命令
```

这是个**自我修复**的环：摔了 → safe-hold 拉直 → 自动恢复 → 等命令。再也不会
出现"FSM 显示 EMERGENCY_STOP，可机器人继续在地上扑腾"的状态。

**为什么 safe-hold 用 default_q 而不是零力矩**：
* 零力矩 = 直接瘫倒。对 SDK 上的真实 e-stop 流程合适（用户按 ESC 主动放弃
  控制），但对 watchdog 触发的瞬态偏离不合适——我们想让机器人**自救**回到
  直立，不是让它倒在地上。
* `default_q` 全 Kp = 强 PD 把每个关节往训练好的站姿拉。如果机器人只是稍微
  歪了，这个力会把它推回直立（如同 STANDBY 一样）。如果机器人已经倒地，
  `default_q` 也无害——因为机身约束加上重力，关节会停在地面接触决定的位
  置，PD 想拉但拉不动，没有任何"扑腾"。

**`set_safe_hold` 的副作用清理**：进 safe-hold 时把 `_stand_below_thresh_since`
清掉、`_stand_active = True`，让退出后 stand-still bypass 的滞回从一个干净
状态开始。退出 safe-hold 时把 `_engage_quiet_since` 清掉，让 `_can_engage_policy`
重新评估接管条件而不是直接信任之前的状态。

### 4.4 干净下线 mock_imitation（用户请求）

**目标**：感知层继续看用户做手势（这是用户要的"实时视频流理解"的一部分），
但**禁止**机器人据此自动镜像，也禁止 LLM 在它的 tool list 里看到
`mock_imitate` 工具。

改动一共 4 个文件：

#### 4.4.1 `configs/g1_brain.yaml`

```yaml
mock_imitation:
  enabled: false        # 从 true 改为 false
  ...
```

`apps/agent_main.py` 里早就有 `if cfg.mock_imitation.enabled: build auto_trigger`
的判断，所以**自动触发器整个不启动**。原代码：

```python
if (brain_agent is not None
    and (cfg.get("mock_imitation", {}) or {}).get("enabled", False)):
    auto_trigger = _try_build_gesture_auto_trigger(...)
```

#### 4.4.2 `g1_brain/skills/tool_schemas.py`

```python
def build_tool_schemas(*, sim=True, vision_only=False,
                      mock_imitate_enabled=True):
    ...
    schemas = l1 + l2
    if not sim:
        schemas = schemas + real_only
    if not mock_imitate_enabled:
        schemas = [s for s in schemas if s["name"] != "mock_imitate"]
    if vision_only:
        keep = {"say", "describe_scene", "query_scene_state"}
        schemas = [s for s in schemas if s["name"] in keep]
    return schemas
```

工具列表条件性剔除 `mock_imitate`。LLM 拿到的 schema 里看不到这个工具，
就根本调不出来。

#### 4.4.3 `g1_brain/brain/realtime_agent.py`

```python
@dataclass
class BrainRealtimeAgent(RealtimeAgent):
    ...
    mock_imitate_enabled: bool = True

    def _resolve_tool_schemas(self):
        return build_tool_schemas(
            sim=True,
            vision_only=self.vision_only,
            mock_imitate_enabled=self.mock_imitate_enabled,
        )
```

把开关传到 `build_tool_schemas`。

#### 4.4.4 `g1_brain/apps/agent_main.py`

```python
mock_imitation_enabled = bool(
    (cfg.get("mock_imitation", {}) or {}).get("enabled", False)
)

brain_agent = _try_build_brain_agent(
    skill_server=skill_server,
    scene_bus=scene_bus,
    mock_imitate_trigger=None,
    mock_imitate_enabled=mock_imitation_enabled,   # NEW
    ...
)
```

把 YAML 的 `mock_imitation.enabled` 透传到 brain，让"工具列表"和"自动触发"
两条路用同一个开关。

#### 4.4.5 `g1_brain/brain/prompts.py`

LLM system prompt 里原来有大段"看到用户做手势就 mock_imitate 镜像"的指令。
全部删掉，换成：

```
- (Optional) A USB camera that watches the human user. The perception layer
  can describe what the user is doing ("user is waving", "user is pointing").
  Mirroring those gestures back automatically is currently DISABLED — only
  perform an arm action when the user explicitly asks for one in voice.

...
- Do NOT take physical action on your own initiative. Move only when the user
  voice-commands it. Seeing the user wave on camera is NOT a command — describe
  it if asked, but do not auto-mirror it.
```

这样即使将来某天用户重新打开 `mock_imitation.enabled: true`，prompt 里也不
会有针对它的特殊指令——LLM 看到 schema 里有 `mock_imitate` 自然会用。
prompt 不再依赖这个开关。

#### 4.4.6 `tests/test_brain_prompts.py`

测试套里有一行参数化测试要求 system prompt 必须 mention 每个工具名。把
`mock_imitate` 从必现工具列表里挪走（理由写在测试注释里），其他工具仍然
要求出现。

### 4.5 感知保留

phase7 不动 `g1_brain/perception/` 任何代码：
* MediaPipe 姿态识别仍然跑（识别用户挥手、举手等）
* YOLO 仍然跑（识别物体）
* `query_scene_state` 仍然返回 `user_gesture` 字段，brain 仍能"知道"用户在
  做什么——只是不会自动模仿。

用户语音问 "你看到我现在在干什么？" → describe_scene / query_scene_state
照常工作。这与用户想保留"实时视频流理解和感知"的目标吻合。

---

## 5. 完整运行时序（修复后）

### 5.1 阶段图

```
                  ┌─────────────────────────┐
                  │  unitree_mujoco.py 启动  │
                  └────────────┬────────────┘
                               ↓
       qpos = default_q   bridge 种子 PD 满 Kp 守 default_q
                               ↓
                  ┌─────────────────────────┐
                  │ agent_main.py 启动       │
                  └────────────┬────────────┘
                               ↓
       DDS init   →  combo.init_dds() & start()
                               ↓
                  ┌─────────────────────────┐
                  │ ComboController BOOT    │ 5s
                  │ kp_scale: 0.3 → 1.0     │
                  │ q: boot_q_from→default_q│
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │ ComboController STANDBY │
                  │ 守 default_q 满 Kp       │
                  │ 等接管门槛通过           │
                  │  gz<=-0.95 1.5s 持续    │
                  │  pose_err<0.08         │
                  │  vel_err<0.30          │
                  └────────────┬────────────┘
                               ↓
                  ┌─────────────────────────┐
                  │ ComboController POLICY  │
                  │ idle: stand-still bypass│ ← cmd=0 时持续走这条
                  │ q_target = default_q    │
                  │ kp_scale = 1.0          │
                  └────────────┬────────────┘
                               ↓ (用户说"前进")
                  ┌─────────────────────────┐
                  │ ComboController POLICY  │
                  │ walking: 跑 ONNX policy │
                  │ q_target = raw*scale+off│
                  └────────────┬────────────┘
                               ↓ (cmd 回到 0)
                       (回到上面的 idle)
```

如果**任何**时刻 watchdog 检测到 `gz > -0.85` 持续 0.5s：

```
   POLICY (任意子状态) ──watchdog pose trip──┐
                                              ↓
                                   set_safe_hold(True)
                                              ↓
                            combo._tick safe-hold 早返
                                              ↓
                              q = default_q, kp_scale = 1.0
                                              ↓
                           机器人被 PD 拉回直立姿态
                                              ↓
                  watchdog 检测 gz <= -0.85 持续 5s
                                              ↓
                       set_safe_hold(False)
                                              ↓
                       fsm: STANDING → ENGAGED
                                              ↓
                       combo POLICY 但 stand-still bypass
                       让它继续守 default_q（除非有 cmd）
```

### 5.2 站立的稳定性证明（非正式）

**断言**：修复后机器人在没有命令时能无限期站稳，前提是没有外力把它推到
`gz > -0.85`。

**论证**：
1. STANDBY 阶段 q_target = default_q，kp_scale = 1.0。这个状态下机器人是
   稳的（取证：phase6 修复后 STANDBY 期间 gz 保持在 -1 附近）。
2. 接管之后，因为 `||cmd||₂ < STAND_CMD_THRESH = 0.08`（用户没下命令），
   `_stand_active = True`。
3. stand-still bypass 让 q_target = default_q，kp_scale = 1.0。
4. 这与 STANDBY 阶段**完全相同的控制律**。所以稳定性也相同。
5. 即使有小扰动让 gz 短暂偏离 -1：
   * 如果 |偏离| < 8°（gz > -0.99），PD 把它拉回，watchdog 不 trip。
   * 如果 8° < |偏离| < 32°（-0.99 < gz < -0.85），PD 仍在拉，watchdog
     在 0.5s hold-down 内不 trip。
   * 如果 |偏离| > 32°（gz > -0.85）持续 0.5s，watchdog trip → safe-hold
     → 仍然是 q = default_q kp = 1.0，机器人继续被拉回（没有任何"切换"
     代价，因为 stand bypass 和 safe-hold 输出同样的 q）。

也就是说，**stand bypass 和 safe-hold 输出一致**。watchdog trip 只是把"拒绝
工具调用 + log warn"加进来，控制层面 nothing changes。这种一致性消除了
phase6 那种"接管时刻擦边、watchdog 反复 trip 触发 ENGAGED↔EMERGENCY_STOP
flap"的失败模式。

### 5.3 走路如何工作

1. 用户说话 → wake-word "hi sparky" → Realtime 上行 → LLM 解析 →
   决定调 `walk(vx=0.2, duration=1.0)`
2. SkillServer.execute("walk", ...) → safety.validate → ok →
   `combo.set_command(0.2, 0, 0)` → 等 1.0s → `combo.set_command(0, 0, 0)`
3. `set_command(0.2, 0, 0)` 后下一次 `_tick` 的 `cmd_norm = 0.2 > 0.08`：
   * `_stand_active = False`（立即生效，无滞回延迟）
   * 走 POLICY 路径，跑 ONNX 推理，q_target = policy_output
   * **POLICY_WARMUP_S = 0.6s 的渐入仍然生效**——这是 phase6 的功能保留：
     第一次推理被 cosine ease-in 渐入，clip 到 ±0.8，避免单次坏推理炸腿。
4. 1.0s 之后命令被设回 (0,0,0)：
   * 滞回：要 `cmd_norm < 0.08` 持续 0.3s 才进 stand
   * 0.3s 内策略仍在跑（让步态自然收尾）
   * 0.3s 后 `_stand_active = True`，q_target = default_q，机器人停下

**为什么走路本身不会重现 §3.1 的不稳**：走路时 `cmd ≠ 0`，gait_phase 是
[0,1] 旋转，policy obs 在训练分布的"行走"区间——这是策略的强项。phase6
观察到走路是稳的（"Walking and running motions remained correct"），phase7
没动这条路径。

---

## 6. 文件变更清单

| 文件 | 变更 |
|---|---|
| `g1_sim_demo/g1_sim_rl_combo.py` | 新增 `STAND_CMD_THRESH` `STAND_HYST_HOLD_S`；收紧 `ENGAGE_GRAV_Z`/`ENGAGE_HOLD_S`；新增 `set_safe_hold()`/`_safe_hold`；`_tick` 里 safe-hold 早返 + stand-still bypass；`start()` 重置新状态 |
| `g1_brain/g1_brain/safety/watchdogs.py` | `_on_fsm_transition` 在 EMERGENCY_STOP 进/退时调 `combo.set_safe_hold()` |
| `g1_brain/configs/g1_brain.yaml` | `mock_imitation.enabled: true → false` + 注释解释 |
| `g1_brain/g1_brain/skills/tool_schemas.py` | `build_tool_schemas` 新增 `mock_imitate_enabled` 形参，false 时移除工具 |
| `g1_brain/g1_brain/brain/realtime_agent.py` | 新增 `mock_imitate_enabled` dataclass 字段；`_resolve_tool_schemas` 透传 |
| `g1_brain/g1_brain/apps/agent_main.py` | 从 YAML 读 `mock_imitation.enabled` 透传给 BrainRealtimeAgent |
| `g1_brain/g1_brain/brain/prompts.py` | 删除 mock_imitate 段，新增"不要主动模仿"硬约束 |
| `g1_brain/tests/test_brain_prompts.py` | 把 `mock_imitate` 从必现工具列表里移走（已变成可选工具） |

---

## 7. 验证

* `pytest tests/`：218 passed（一个测试文件随设计同步更新；不是测试失败）
* 静态导入 + 常量检查：
  * `ENGAGE_GRAV_Z = -0.95`
  * `ENGAGE_HOLD_S = 1.5`
  * `STAND_CMD_THRESH = 0.08`
  * `STAND_HYST_HOLD_S = 0.3`
  * `ComboController.set_safe_hold` 存在
* 手动取证（这次 fail run 的日志逐条核对）：
  * 14:11:28 第一次 pose trip 时 gesture auto-trigger 还没启动 → 现在 auto-trigger 永不启动
  * 14:11:20.6 接管 → 现在接管要等 gz<=-0.95 持续 1.5s（更严格）
  * 14:11:25.6 EMERGENCY_STOP 后机器人继续晃 → 现在会立刻 safe-hold

不会有这次失败跑的复现，因为：
1. **没有命令的时候根本不跑策略**（最大改动）
2. 接管时机已经和 watchdog 阈值留了 10° 余量
3. EMERGENCY_STOP 真停得下控制器

---

## 8. 操作流程（用户视角）

跟 phase6 一样，没有任何新步骤：

```bash
# 终端 1
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# 机器人挂在弹力带上、保持 default_q 姿态。
# 按 8 几次让机器人下到地面；按 9 关闭弹力带。

# 终端 2
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --mode active

# 等到 "[combo] policy engaged (idling on default_q)"
# 此时机器人原地直立、纹丝不动（因为 stand-still bypass 在守 default_q）。
# 唤醒词 "hi sparky" → 说话 → LLM 调 walk/turn → 策略接管行走 → 走完回到 idling
```

预期日志（修复后正常情形）：

```
[combo] mode_machine=0. Ramping to default pose over 5.0 s, ...
fsm: BOOT -> STANDING (boot complete)
watchdogs: started 6 threads
[combo] policy engaged (idling on default_q). wsadqe to walk; ...
fsm: STANDING -> ENGAGED (policy active)
... (静默 — 没有 pose trip，没有 EMERGENCY_STOP)
gesture auto-trigger started        ← 注意：mock_imitation.enabled=false 时这行不会出现
connecting Realtime: ...
wake-word enabled: phrases=['hi sparky', ...]
... (持续待命，等用户语音)
```

如果出现 pose trip（被推、被踢、地不平等），日志会是：

```
watchdog pose tripped: gravity_z=-0.80
fsm: ENGAGED -> EMERGENCY_STOP (watchdog pose: gravity_z=-0.80)
watchdogs: combo safe-hold engaged (FSM -> EMERGENCY_STOP)
... (PD 把机器人拉回直立) ...
watchdog pose cleared
... (5 秒 hold) ...
fsm: EMERGENCY_STOP -> RECOVERING (watchdogs clear for 5.0s)
fsm: RECOVERING -> STANDING (auto-recovery complete)
fsm: STANDING -> ENGAGED (policy active)
watchdogs: combo safe-hold released (FSM EMERGENCY_STOP -> ENGAGED)
... (回到 idling)
```

---

## 9. 未来 Re-enable mock_imitation 的步骤

1. `configs/g1_brain.yaml`: `mock_imitation.enabled: true`
2. （可选）调 `auto_suggest_high_conf` / `auto_suggest_persist_s` 来调灵敏度
3. 完。Tool schema、prompt、auto-trigger 都按这个开关条件激活，没有其他需要
   改的地方。

---

## 10. 已知未解 / 后续

* **真机部署**：phase7 的修复是仿真层面的。真机 `kp_scale = 1.0` 守 `default_q`
  在站立阶段是合适的，但走路稳定性还需要在真机上重新评估——本仓库目前没有
  真机回归测试。
* **Stand-still bypass 的代价**：策略不再做"小幅平衡修正"，而是 PD 死守。
  如果将来需要更柔顺的站立（例如顺应外部推力），需要重新考虑这个 bypass，
  也许换成"策略输出乘 0.2 的衰减系数"或者"在 cmd=0 时混合 80% PD + 20%
  策略"。目前就用最简单粗暴的版本。
* **Engagement timeout (30s)**：如果用户的弹力带操作慢导致 30 秒还没让机器
  人完全静止，timeout 会强行接管。phase6 已有的 `print` 会列出当时的 gate
  状态，方便诊断。

phase7 完。
