# Fleet QA #1 — 「机器人没有定位能力，为什么 fleet 跑自然语言任务时还能自己处理位置、走位、绕开障碍？」

> 提问背景：g1_brain 里的单机机器人有快脑（Realtime 语音）+ 慢脑（Codex daemon）+ 可接 MCP，
> 但**印象里没有接任何定位 / 导航能力**。可是今天用 fleet 的自然语言指挥多台机器人跑任务时，
> 发现每台机器人都能自己算好位置、走到目标、还能绕开障碍，这和「要 ROS2 nav2 才能做到」的认知冲突，
> 难以置信。本文把整条链路从「一句话指令」一直拆到「MuJoCo 物理步进」，彻底解释清楚。

---

## 0. 一句话答案

**因为这是仿真。机器人的位置不是「估计」出来的，而是直接从 MuJoCo 物理引擎的状态向量 `qpos` 里
*读* 出来的——是上帝视角的真值（ground truth），零噪声、零延迟。障碍物也不是「感知」出来的，
而是写死在场景注册表 `scene.py` 里、把每个障碍的圆心和半径直接喂给导航器。**

真实世界里「我在哪？」「障碍在哪？」这两个最难的问题（正是 ROS2 nav2 存在的全部理由），
在仿真里**根本不需要解决，直接白送**。剩下的只是一段 50 行的几何函数把
（精确位置 + 目标 + 已知障碍列表）换算成一个速度指令——这就是你看到的「难以置信地好用」的真相。

你的记忆没错：**g1_brain 确实没有定位 / SLAM 模块。fleet 也没有偷偷加一个。
它是绕过了整个问题，而不是解决了整个问题。**

---

## 1. 先厘清：你印象里的「快慢脑 + MCP」和 fleet 是两套东西

这是第一个容易混淆的点，必须先分开：

| | 单机 g1_brain（你印象里的那套） | fleet 指挥调度中心（你今天跑的那套） |
|---|---|---|
| 控制路径 | 快脑 Realtime 语音 FSM → skill_server → safety supervisor | 网页/NL → `plan_mission` → `LiveExecutor` → `nav_command` → RL 策略 |
| LLM 在哪 | 在**控制回路上**（语音对话即时决策）| 只在**规划层**（NL→op 序列），**不在控制回路上** |
| 定位 | 无（你记得对）| 无 SLAM——直接读仿真真值 |
| 慢脑 Codex / MCP | 有（`ask_slow_brain`）| 可选，只用来把一句话拆成 op 序列，**从不算坐标、不绕障** |

**关键澄清**：fleet 里那个「AI 大脑」（Codex / `gpt-5.5`）做的事情是
*「navigate 到 (2,1)，然后绕圈」* 这种**离散动作编排**。它**从不**计算机器人当前在哪、
也**从不**自己绕障。位置和绕障是底下一段**确定性几何代码**干的，跟 LLM 一点关系都没有。

所以「每台机器人自己处理好位置信息和动作而且绕开障碍」——这句话里：
- **「位置信息」** = 从 MuJoCo `qpos` 读真值（第 2 节）
- **「动作 / 走位」** = RL 步态策略跟踪一个速度指令（第 4 节）
- **「绕开障碍」** = 势场法对**已知**障碍做斥力（第 3 节）

没有一项用到 LLM，也没有一项用到 SLAM。

---

## 2. 「位置信息」从哪来——仿真真值，不是定位

### 2.1 真实世界 vs. 仿真世界的根本差异

| | 真实 G1 | fleet 仿真 G1 |
|---|---|---|
| 「我在哪？」 | 未知。必须用激光雷达 SLAM / 视觉惯性里程计 / 动捕 / RTK-GPS **估计**出来，带漂移、带延迟、会丢 | **已知**。物理引擎就是世界本身，每个刚体的位姿它都精确知道 |
| 「障碍在哪？」 | 未知。必须激光/深度感知 → 建占据栅格 costmap | **已知**。场景里所有障碍的圆心+半径写死在注册表里 |
| 需要 ROS2 nav2 吗 | **需要**——nav2 = AMCL 定位 + 全局规划 + 局部避障 + 恢复行为，全是为了对抗「感知不确定 + 不完整」 | **不需要**——上面两个不确定性都不存在 |

你之前查资料得到「要 nav2」的结论，**针对的是真机**：真机你**读不到** `qpos`，
只能从带噪声的传感器里估计自己的位置，还得从激光雷达里现场建障碍地图。
**仿真里这两件事物理引擎直接白送给你。** 这就是「仿真里不可思议地简单」和
「真机上必须上 nav2」之间的全部鸿沟。

### 2.2 代码实证：位置就是 `qpos` 切片

`fleet/sim/shared_world.py` 的 `base_pose()` —— 机器人的 (x, y, yaw) 就是直接从状态向量里抠出来的：

```python
def base_pose(self, rid: str) -> Tuple[float, float, float]:
    sl = self.slices[rid]
    x, y = self.d.qpos[sl.qpos_adr], self.d.qpos[sl.qpos_adr + 1]   # ← 直接读真值
    quat = self.d.qpos[sl.qpos_adr + 3:sl.qpos_adr + 7]
    yaw = math.atan2(2 * (quat[0] * quat[3] + quat[1] * quat[2]),
                     1 - 2 * (quat[2] ** 2 + quat[3] ** 2))          # 四元数→yaw
    return float(x), float(y), float(yaw)
```

`self.d` 就是 `mujoco.MjData`——仿真器的完整状态。`qpos` 是广义坐标，浮动基座的前 3 维就是世界系
xyz，接着 4 维是姿态四元数。**没有卡尔曼滤波、没有粒子滤波、没有 AMCL、没有激光雷达**——
就是数组下标取值。这是「上帝视角」：仿真器当然知道它自己摆的每个物体在哪。

同一文件里 `neighbors()` 算「队友相对我多远」，也是同样的把戏——两台机器人的真值位姿直接相减：

```python
def neighbors(self, rid: str) -> List[dict]:
    x, y, yaw = self.base_pose(rid)
    for other in self.robot_ids:
        ox, oy, _ = self.base_pose(other)      # 队友真值
        dx, dy = ox - x, oy - y
        dist = math.hypot(dx, dy)
        ...
```

**这就是为什么 fleet 里多机协同（会合、保持间距、绕开队友）也「凭空」好用：
每台机器人都精确知道所有同伴在哪，无需任何机间通信或感知。**

---

## 3. 「绕开障碍」是怎么做到的——势场法 + 写死的障碍表

### 3.1 障碍物是声明出来的，不是感知出来的

`fleet/sim/scene.py` 是一张**静态场景注册表**。`demo` 场景里每个障碍长这样：

```python
Geom("cylinder", (-2.5, 1.8, 0.40), (0.15, 0.40), R, name="红色柱子", avoid_r=0.45),
Geom("box",      (2.5, 1.8, 0.40),  (0.25, 0.25, 0.40), B, name="蓝色箱子", avoid_r=0.50),
Geom("cylinder", (0.0, 1.30, 0.35), (0.18, 0.35), O, name="路障",  avoid_r=0.50),
Geom("box",      (0.0, 3.0, 0.30),  (1.5, 0.10, 0.30), W, name="矮墙", avoid_r=0.0),   # ← 不避
Geom("box",      (3.5, 0.0, 0.129), (0.60, 0.50, 0.025), W, ..., name="斜坡"),         # ← 地形，踩上去
```

`SharedG1World.obstacles()` 把这张表里 `avoid_r > 0` 的，整理成导航器要的**圆形脚印** `(x, y, r)`：

```python
def obstacles(self) -> List[Tuple[float, float, float]]:
    """Circular footprints (x, y, r) the navigator avoids (props only)."""
    return [(g.pos[0], g.pos[1], g.avoid_r)
            for g in self._scene.geoms if g.avoid_r > 0]
```

几个**必须知道的细节**（影响你对「绕障」能力边界的判断）：
- **障碍是手工标注的**：`avoid_r` 一个一个填在 `scene.py` 里。导航器只会绕「被标了 `avoid_r>0` 的东西」。
- **地形不算障碍**：斜坡 / 矮台阶 / 起伏 `avoid_r=0`，是「走上去」而不是「绕过去」。矮墙也设成 0。
- **方块也被当成圆**：导航器只看 `(x, y, r)` 圆脚印，不管原物体是 box 还是 cylinder——稀疏 demo 场地里这个近似完全够用。

### 3.2 nav.py：人工势场（attractive + repulsive + tangential）

真正干「绕障」的是 `fleet/sim/nav.py` 里 50 行的 `nav_command()`。它是经典的**人工势场 /
反应式转向（reactive steering）**，**不是路径规划**——没有 A*、没有全局路径、没有 costmap：

```python
def nav_command(pose, goal, *, stop_radius=0.25, ...,
                obstacles=(), peer=None, avoid_radius=0.9, k_avoid=0.9):
    x, y, yaw = pose
    ex, ey = gx - x, gy - y
    dist = math.hypot(ex, ey)
    if dist < stop_radius:
        return (0.0, 0.0, 0.0)          # 到了就停
    gxn, gyn = ex / dist, ey / dist     # ① 吸引项：朝目标的单位向量
    approach = min(1.0, dist / slow_radius)
    des_x, des_y = approach * gxn, approach * gyn   # 远处全速，近处减速

    obs = list(obstacles)
    if peer is not None:
        obs = obs + [(peer[0], peer[1], 0.45)]      # 队友 = 一个会动的圆障碍
    for ox, oy, orad in obs:
        dx, dy = x - ox, y - oy                      # 障碍 → 机器人
        d = math.hypot(dx, dy)
        reach = avoid_radius + orad
        if 1e-6 < d < reach:
            w = k_avoid * (reach - d) / reach        # ② 斥力项：越近推得越狠
            ux, uy = dx / d, dy / d
            des_x += w * ux; des_y += w * uy         # 径向往外推
            ahead = (-ux) * gxn + (-uy) * gyn
            if ahead > 0.3:                          # ③ 切向项：障碍正挡在去路上时
                cross = gxn * (-uy) - gyn * (-ux)
                sgn = 1.0 if cross >= 0 else -1.0
                des_x += 0.8 * w * (-uy) * sgn       # 加一个侧向「擦边绕过」分量，
                des_y += 0.8 * w * (ux) * sgn        # 逃出正对障碍时的局部极小值

    # 期望方向（世界系）→ 机体系速度 [vx, vy, wz]，并夹到策略训练过的范围
    heading_err = ...                                # 朝向误差
    wz = _clip(k_yaw * heading_err, *RANGES["wz"])
    e_fwd = c * des_x - s * des_y                    # 旋到机体系
    e_lat = s * des_x + c * des_y
    facing = max(0.0, math.cos(heading_err))         # 没对准目标就别冲
    vx = _clip(k_fwd * e_fwd * facing, *RANGES["vx"])
    vy = _clip(k_lat * e_lat * facing, *RANGES["vy"])
    return (vx, vy, wz)
```

三项叠加，就是势场法的全部：
1. **吸引项**：把机器人往目标拉（远处满速，`slow_radius` 内减速软着陆）。
2. **斥力项**：每个进入 `avoid_radius + 障碍半径` 范围的障碍，沿「障碍→我」方向往外推，越近越狠。
   **队友被当成一个 0.45 m 的移动圆障碍塞进同一份列表**——这就是机器人之间也会互相让的原因。
3. **切向项**：当障碍正卡在「我→目标」的连线上（`ahead>0.3`，约 72° 内），光靠径向斥力会
   正面顶牛卡死（势场法经典的局部极小值）。这里加一个垂直于径向的侧推（约径向的 80%），
   让机器人**擦着障碍侧滑绕过去**。

### 3.3 为什么这套「简陋」的东西在 demo 里表现这么好

- 障碍**数量少、位置精确已知**——没有感知误差，斥力中心是准的。
- 场地**开阔、障碍稀疏**——势场法最怕的「凹形障碍 / 窄通道里的局部极小值」基本遇不到，
  偶尔正对障碍也有切向项兜底。
- 队友也是真值，互让逻辑天然成立。

**这就是「难以置信地好」的代价：它好，是因为问题被仿真简化到了势场法刚好够用的程度。**

---

## 4. 「走位 / 动作」是怎么实现的——双层嵌套回路

第二个关键认知：`nav_command` **不直接动关节**。它只输出一个**速度意图**，
由底下的 RL 步态策略去实现这个速度。整个系统是**两层嵌套回路**：

```
┌─ 外环 ~50 Hz「导航」(nav.py) ────────────────────────────────┐
│  位置误差 + 已知障碍  ──►  速度指令 [vx, vy, wz] (机体系)      │  ← 简单几何，"去哪"
└───────────────────────────────┬─────────────────────────────┘
                                 ▼
┌─ 内环 RL 策略 + 200 Hz PD (rl_adapter / shared_world) ───────┐
│  速度指令 ──► ONNX 速度跟踪策略 ──► 29 关节目标 q_target      │  ← 学出来的，"怎么走"
│           ──► PD: tau = kp*(q_target - q) - kd*dq ──► MuJoCo  │
└──────────────────────────────────────────────────────────────┘
```

### 4.1 外环→内环：速度指令喂给 RL 策略

`fleet/agent/motion/rl_shared_backend.py` 的 `_drive()` 是两层的接缝：

```python
def _drive(self):
    if self._mode == "walk" and self._goal is not None:
        pose = self.world.base_pose(self.rid)                 # 真值位姿
        obstacles = self.world.obstacles()                    # 已知障碍表
        peer = None
        if self.peer_avoid:                                   # 协同时把队友算进去
            nb = self.world.neighbors(self.rid)
            if nb:
                peer = (pose[0] + nb[0]["dx"], pose[1] + nb[0]["dy"])
        vx, vy, wz = nav_command(pose, self._goal, obstacles=obstacles, peer=peer)
        self.ctl.set_command(vx, vy, wz)                      # ← 速度指令交给 RL 策略
```

`self.ctl` 是 `SharedWorldController`（`rl_adapter.py`），它**原样复用**了 `g1_sim_demo` 里
那个跑通的 `ComboController`——也就是 `unitree_rl_mjlab` 训练出来的**速度跟踪策略（ONNX）**。
`compute()` 每 50 Hz 跑一次策略，吐出 `(q_target, kp, kd)`。

### 4.2 关键：把速度夹在策略「训练过的范围」内

`nav.py` 顶部：

```python
RANGES = {"vx": (-0.5, 1.0), "vy": (-0.5, 0.5), "wz": (-1.0, 1.0)}
```

外环算出的速度**一律夹到这个范围**。这是**绝不能省**的一步：这个范围就是 RL 策略当初训练时
命令分布的边界。一旦超出，策略进入「分布外」（out-of-distribution），步态就崩、机器人就摔。
所以外环导航再怎么折腾，也只是在策略「会走的速度集合」里挑一个，**永远不会把步态策略带到它没见过的地方**。

这就是「**分层**」的精髓——把「难学的部分（怎么用 29 个关节走出稳定步态）」交给 RL，
把「好算的部分（往哪个方向走多快）」交给确定性几何。两边各管一段，互不污染。

### 4.3 内环：PD 力矩每个物理子步重算（这条是 fleet 的头号坑）

`shared_world.py` 的 `step()` —— 力矩必须在**每个 200 Hz 物理子步**用最新 q/dq 重算，
**不能只在 50 Hz 控制步算一次**：

```python
def _apply_pd(self):
    for rid, (q_target, kp, kd) in self._pd.items():
        q, dq = self.joint_state(rid)
        self.d.ctrl[...] = kp * (q_target - q) - kd * dq   # 用"此刻"的 q/dq

def step(self, n=1):
    for _ in range(n):
        self._apply_pd()                 # ← 每个子步刷新，不是每个 50 Hz tick
        mujoco.mj_step(self.m, self.d)
```

若只在 50 Hz 算一次力矩，力矩相对积分器就「过期」了，会激起 Kp 振荡 → RL 机器人抖→摔。
这条和 workspace memory 里 `fleet_shared_world_p1` 记的「THE gotcha」是同一件事。

---

## 5. 从一句话到机器人迈腿：完整链路

把前面拼起来，一条 NL 指令的全流程：

```
① 你在网页控制台输入「g1_a 走到 2,1」「去红色柱子」「两机都去集合点」「顺时针绕圈」
   └─ POST /command  (command_center.py)

② plan_mission(nl, snapshot)  (choreographer.py) 按优先级路由：
   1. 有 Codex → 让 LLM 直接编排 op 序列（任意自然语言）
   2. nl_position.parse_position_command —— 确定性正则解析器（无需 LLM）：
        · 绝对坐标 "2,1"        → navigate{x:2, y:1}
        · 地标 "红色柱子"        → 查 scene.py 注册表 → navigate{x:-2.5, y:1.8}
        · 相对 "前进1米"         → 按当前 yaw 推算 navigate
        · 多机 "两机/都/all"     → 同一目标发给所有机器人
   3. 确定性编排（绕圈 / 面对面 / 抬手）
   4. 兜底 FleetCommander（会合 / 接力 / 巡逻）
   产物：每台机器人一串 op —— navigate{x,y} / await_barrier / circle / face / arms_up / hold ...

③ LiveExecutor.submit(plan, ops) —— 成为"当前任务"，抢占掉上一条
   （最新指令永远胜出；不排队、不堆栈，直接换掉）

④ LiveExecutor.step()  50 Hz，可抢占，推进每台机器人的 op 指针：
   · navigate op → world.set_nav_goal(rid, x, y)，盯 pose 直到进 arrive_radius=0.45m → 指针+1
   · await_barrier → RendezvousBarrier 判定两机都进集合圈 → 放行
   · 会合 / 面向对方 这类 op 期间还会 set_peer_avoid(off)，让它们能贴近而不是互相排斥

⑤ WorldSim 控制线程 50 Hz：RlSharedBackend._drive()
   → nav_command(真值pose, goal, 已知障碍, 队友) → 速度 [vx,vy,wz]
   → RL 策略 compute() → (q_target, kp, kd)

⑥ SharedG1World.step() 200 Hz 子步：PD 力矩 → mujoco.mj_step → 机器人在 3D 窗口里真的迈腿
   俯视 2D 图 + 事件流实时刷新
```

> 注意 ④ 里那个 `set_peer_avoid` 的开关（`live_executor.py`：
> `op.op not in ("await_barrier", "face")`）——**走路时互相让，会合/对视时关掉互斥**，
> 否则两台机器人永远靠不拢。这是「绕开队友」和「主动靠近队友」用同一套势场代码、靠一个布尔位切换实现的。

---

## 6. 诚实的边界——别把「仿真好用」误读成「能力齐了」

这是最重要的一节，避免你对真机能力做出过度乐观的判断：

1. **它好用 100% 是因为它是仿真。** 搬到真机，你必须：
   - 把 `world.base_pose()`（读 `qpos` 真值）换成**真实状态估计**——激光雷达 SLAM / VIO / 动捕 / RTK；
   - 把 `world.obstacles()`（静态注册表）换成**实时感知 costmap**——激光/深度 → 占据栅格。
   - `nav_command` 这个势场外环**可以留着**，但喂给它的是**估计的**位姿和**检测到的**障碍——
     于是漂移、漏检、延迟这些真实失效模式全部回来。**这一整包，正是 ROS2 nav2 替你封装的东西。**
     所以你查到「要 nav2」没错——只是那是真机的故事，仿真把这一层整个跳过了。

2. **避障是反应式的，不是规划式的。** 势场法没有全局路径，**会卡在局部极小值**
   （凹形障碍、窄缝、一排障碍）。切向项只是缓解、不是根治。nav2 的全局规划器（A*/Dijkstra）
   才保证完备性。demo 场地是**故意设得开阔稀疏**，才让这个弱点不暴露。

3. **只避「被标注的」障碍。** `avoid_r=0` 的（地形、矮墙）根本不在避障列表里；方块被当成圆。
   换个杂乱场景，这套标注就得重做。

4. **没有感知—行动闭环里的"看"。** fleet 机器人不"看"世界，它"查表"。单机 g1_brain 那套
   YOLO/MediaPipe 感知、深度→地面约束，**没有**接到 fleet 导航里。fleet 的"感知"=读仿真状态。

---

## 7. 给你的一句话收尾

> **你的直觉完全正确：g1_brain 没有定位能力，真机绕障导航确实要 nav2。**
> **fleet 之所以"难以置信地好"，不是因为它偷偷实现了 nav2，而是因为它是仿真——
> 把 nav2 要解决的两个最难问题（我在哪、障碍在哪）用物理引擎真值直接白送了，
> 于是剩下的只是一段 50 行势场几何 + 一个把速度夹进训练范围、交给 RL 步态策略去执行的分层结构。**
>
> 真正的工程价值在那个**分层**：确定性几何管"去哪"、RL 策略管"怎么走"、LLM 只管"把人话拆成动作"——
> 三层解耦、各自简单、合起来看着像很聪明。这套结构是真的；只是它跑在一个"上帝视角"的世界里。

---

## 附录：本文引用的关键文件

| 文件 | 作用 |
|---|---|
| `g1_brain/g1_brain/fleet/sim/nav.py` | 势场法外环：`nav_command(pose, goal, obstacles, peer)` → 速度 |
| `g1_brain/g1_brain/fleet/sim/shared_world.py` | 共享 MjModel；`base_pose`(读真值)、`obstacles`(障碍表)、`neighbors`、200Hz PD |
| `g1_brain/g1_brain/fleet/sim/scene.py` | 静态场景注册表：障碍 `avoid_r`、地标坐标、别名解析 |
| `g1_brain/g1_brain/fleet/sim/rl_adapter.py` | 复用 `ComboController`(ONNX 速度策略)，速度→(q_target,kp,kd) |
| `g1_brain/g1_brain/fleet/agent/motion/rl_shared_backend.py` | 外环↔内环接缝：`_drive()` 调 nav_command，`set_peer_avoid` 开关 |
| `g1_brain/g1_brain/fleet/sim/shared_world_node.py` | `WorldSim`：50Hz 控制线程、线程安全 `set_nav_goal/telemetry` |
| `g1_brain/g1_brain/fleet/sim/live_executor.py` | 可抢占任务执行器：推进 op 指针，到点判定，barrier，peer_avoid 切换 |
| `g1_brain/g1_brain/fleet/coordinator/choreographer.py` | `plan_mission`：NL→op 路由（codex / 位置解析 / 编排 / 会合兜底）|
| `g1_brain/g1_brain/fleet/coordinator/nl_position.py` | 确定性 NL→位置解析（坐标/地标/相对/多机），无需 LLM |
| `g1_brain/g1_brain/fleet/coordinator/fleet_commander.py` | 会合/接力/巡逻指挥（LLM 提议 + 确定性兜底）|
| `g1_brain/g1_brain/fleet/sim/command_center.py` | 总装：WorldSim + 3D viewer + 网页控制台 + Codex 指挥官 |
</content>
</invoke>
