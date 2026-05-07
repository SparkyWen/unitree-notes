# 摄像头障碍物检测 / 历史召回 / 多步行走 三大问题排查与修复

日期：2026-05-07
分支：`feature/audio-control`

本文逐项解释三个被用户报告的严重 bug：根因、为什么会这样、修了什么、还
剩什么风险。重点是问题 1 —— 用户对"为什么我让机器人用自己头顶的摄像头
检测障碍，结果它看到的是一个完全不同的世界"感到困惑，需要把整个架构讲
透。

---

## 0. TL;DR

| # | 症状 | 根因（一句话） | 修复（一句话） |
|---|---|---|---|
| 1 | "前面明明有障碍，机器人摄像头说没有" | 大脑端的"头顶摄像头"用的 MJCF（场景文件）跟仿真器加载的 MJCF 不是同一个，所以渲染出来的世界根本没有障碍 | 让大脑端 `cameras.head` 默认继承 `robot.mjcf_path`，而 `robot.mjcf_path` 跟 `unitree_mujoco/simulate_python/config.py` 里 `USE_TERRAIN=True` 时使用的 `scene_29dof_terrain.xml` 对齐 |
| 2 | "让它 recall 第一个动作，给的不是第一个" | 用户的怀疑（每次 `hi sparky` 都新建 jsonl）**不成立**；真实原因是 OpenAI Realtime 模型的上下文记忆是有损的，会按需丢/压缩老 turn | 加了一个新的 `recall_history` 工具，让大脑可以从持久化 jsonl 里按时间最早顺序取出过去所有 `tool_use`/`user`/`assistant` 事件，prompt 里要求 LLM 在被问"过去做了什么"时必须先调用这个工具 |
| 3 | "走 10 米被拆成 50 步，每步都要我按 y" | `safety.walk.duration_max_s = 1.0` 加上 prompt 里硬性规定 "Walk durations <= 1.0 s"，逼着 LLM 把一段长行走拆成 N 个 1 秒的小调用，每个调用在 `confirm` 模式下都会弹一次 y/N | 把 `duration_max_s` 提到 60 秒（≈ 12 m at 0.2 m/s），更新 prompt 让 LLM 用一次 `walk(vx=0.2, duration_s=50)` 完成长距离行走；`_skill_walk` 内部 0.2 秒一次的反应式 abort 已经覆盖障碍检测，所以"一次大调用"和"50 个小调用"在安全性上等价 |

跑全部测试：276 / 276 通过。三个问题的修复包含 3 个新 `recall_history`
回归测试，并把 `tool_schemas` 计数测试从 13/16/3 改成 14/17/4 以反映
新工具的加入。

---

## 1. 问题一：摄像头检测不到障碍 —— 这一节用户必读

### 1.1 用户的观察

用户说："我机器人都走到障碍面前了，我让它调用自己的摄像头检查是否有
障碍，它告诉我前方没有障碍。"

我用同一段会话的 jsonl（`logs/conversations/2026-05-07T09-16-15Z-4cd797df.jsonl`，
192 行，包含全部 14 个用户 turn）查到了原始证据。turn t-0013：

```
USER: Check with your camera, there seems like there are some obstacles
      just in front of you.
TOOL_USE: describe_scene({detail: "medium",
                          question: "Are there any obstacles directly in front?"})
TOOL_RESULT: {"description":
              "No people or obstacles are directly in front. The path forward looks clear."}
```

并且每一次 `query_scene_state` 返回的 `nearest_obstacle_m` 都是 `null`。
也就是说不仅是 GPT 视觉描述错了，**深度感知也认为前面什么都没有**。

### 1.2 用户最关心的问题：那个"摄像头"到底是什么？是不是实时的？

**核心结论先放在最前面：**

> 大脑用的"头顶摄像头"画面**对机器人的姿态而言是实时的**（机器人转头/
> 走路/侧倾，摄像头视角 20 Hz 跟着变），**但渲染出来的世界（地面、墙、
> 箱子、阶梯）来自大脑自己加载的一个 MJCF 文件**，**不是从仿真器那里
> 接收的视频流**。
>
> 在我修这个 bug 之前，这两个 MJCF 不是同一个文件。仿真器加载的是带
> 障碍物的 `scene_29dof_terrain.xml`，大脑加载的是干净空地板的
> `scene_29dof.xml`。所以机器人即使走到一个障碍正前方，它"自己"看到
> 的依然是一片空地板 —— 因为它根本就在另一个世界里渲染。

为什么会这么设计？让我把架构拆开来讲。

### 1.3 架构详解：为什么大脑要"自己再渲染一遍"

文件位置：`g1_brain/perception/mujoco_head_cam.py:46-113`。
关键代码片段（精简过）：

```python
class MuJoCoHeadCamera:
    def __init__(self, mjcf_path, ...):
        import mujoco
        self._mujoco = mujoco
        # 大脑自己加载 MJCF，得到一个"私有的"模型 + 数据。
        self._model = self._load_or_synthesize_model(mjcf_path, ...)
        self._data = mujoco.MjData(self._model)
        # 然后开一个线程，订阅 DDS 的 rt/lowstate 和 rt/sportmodestate，
        # 把 29 个关节位置 + 浮基位姿同步到这份私有 MjData 上，再用
        # mujoco.Renderer 渲染 RGB + 深度图。
        ...

    def _on_lowstate(self, msg):
        n = self._model.nu  # 29 个 actuated joint
        q = np.array([msg.motor_state[i].q for i in range(n)])
        quat = np.array(msg.imu_state.quaternion[:4])
        with self._state_lock:
            self._latest_motor_q = q
            self._latest_base_quat = quat

    def _on_sportmode(self, msg):
        pos = np.array(msg.position[:3])
        with self._state_lock:
            self._latest_base_pos = pos

    def _render_loop(self):
        # 每 1/20 秒：把最新的关节角度 + 浮基位姿写进 self._data.qpos，
        # 然后离屏渲染 RGB + 深度。
        ...
```

总结一下数据流：

```
                            DDS（共享内存 / UDP）
                                   │
            ┌──────────────────────┼─────────────────────┐
            ▼                      ▼                     ▼
  unitree_mujoco              g1_brain                 (其它订阅者)
  （仿真器，独立进程）         （大脑）
  - 加载 scene_29dof_terrain  - 加载 scene_29dof（修前）
  - 跑物理仿真                - 一份"克隆"的 MjData
  - 发布 rt/lowstate           - 用 DDS 同步关节 + 位姿
  - 发布 rt/sportmodestate     - 自己渲染一份 RGB + 深度
  - 显示在屏幕上               - 这份渲染喂给 describe_scene
                              - 这份深度喂给 query_scene_state
```

注意右边那一支：**大脑根本不订阅仿真器的视频/图像 topic**。它拿到的只是
关节角度和浮基姿态，然后用这些数字自己驱动一份本地的 MJCF 重新渲染。

为什么这么设计？历史原因有几个：

1. **跨平台一致**：真机部署的时候，机器人头部装的是物理摄像头，DDS 上没
   有"画面"这个 topic。MuJoCo 仿真器没有内置"把 GLFW 渲染流通过 DDS 发
   出去"的能力。所以为了 sim/real 的代码路径相同，sim 模式下大脑也是从
   "本地渲染"拿画面。
2. **避免 GPU 上下文跨进程**：MuJoCo 的 `Renderer` 用 EGL/GLFW，跨进程
   传 RGBA 缓冲（而且要带深度）非常复杂。复用一份 MJCF 自己渲染要简单
   得多，反正 MJCF 是静态文件，磁盘上一份地形就够了。
3. **方便加私有相机**：大脑可以在自己加载的 MJCF 上 `MjSpec.add_camera`
   合成一个 "head_camera"（见 `mujoco_head_cam.py:147-156`）。这一步如果
   要做在仿真器进程里，就得改 `unitree_mujoco`。

但这个设计有一个**强假设**：大脑加载的 MJCF 必须跟仿真器加载的 MJCF
**几何一致**。否则机器人姿态正确，但场景错了，画面就不真实。

修复前正好就破坏了这个假设。

### 1.4 具体到这次 bug：两个 MJCF 是怎么走散的

仿真器一侧 `unitree_mujoco/simulate_python/config.py:1-19`：

```python
ROBOT = "g1"
USE_TERRAIN = True
if ROBOT == "g1":
    if USE_TERRAIN:
        ROBOT_SCENE = "../unitree_robots/g1/scene_29dof_terrain.xml"
    else:
        ROBOT_SCENE = "../unitree_robots/g1/scene_29dof.xml"
```

`USE_TERRAIN` 默认 True，仿真器加载的是 `scene_29dof_terrain.xml` —— 这
个场景里有大量 `<geom>` 静态障碍：

```xml
<geom pos="3.0 0.0 0.155" type="box" size="0.75 0.5 0.025" .../>
<geom pos="5.0 0.0 0.218" type="box" size="0.75 0.5 0.025" .../>
<geom type="hfield" hfield="perlin_hfield" pos="7.5 0.0 0.0" .../>
<geom pos="0.25 4.0 0.05"  type="box" size="0.125 0.5 0.05"  .../>  ← 阶梯
<geom pos="0.5  4.0 0.15"  type="box" size="0.125 0.5 0.05"  .../>
... （大量小箱子 + 圆柱）
```

大脑一侧 `g1_brain/perception/cameras.py:75`（修复前）：

```python
mjcf = cfg.get("mjcf_path") or os.path.expanduser(
    os.environ.get(
        "G1_MJCF_PATH",
        "~/unitree/unitree-notes/unitree_mujoco/unitree_robots/g1/scene_29dof.xml",
    )
)
```

而 `configs/g1_brain.yaml` 的 `cameras.head` 段并没有写 `mjcf_path`，所以
落到默认值 —— `scene_29dof.xml`。这个文件是干净的空地板，没有任何箱子
/阶梯/heightfield。

所以画面确实是"实时"的（机器人浮基从 0 走到 5 米，大脑渲染出来的画面
也是从同一个角度往前推进），**但推进过程中两侧地板全是空的**，因为大脑
那份 MJCF 里就没把箱子写进去。

加上 `_skill_describe_scene`（`skill_server.py:252-268`）的实现：

```python
async def _skill_describe_scene(self, question="", detail="auto"):
    jpeg_b64 = self._latest_jpeg_b64_preferring_head()  # 从大脑那份渲染拿 JPEG
    text = await self.vision.describe(image_jpeg_b64=jpeg_b64, ...)
    return {"description": text}
```

GPT-5.5 收到的图片就是空地板的 JPEG，于是它如实回答："empty checkered
floor, no obstacles, path looks clear" —— **视觉模型没有错，错在喂给它的
图就不对**。

同理 `query_scene_state` 拿的是 `MuJoCoNativeDepth` 从同一个渲染器读到的
深度图。空地板 → 深度只有"远处地板"，cone 区域 [0.5, 1.5] m 内没有任何
有限值 → `nearest_obstacle_m = float('inf')` → JSON 序列化后变成 `null`，
`clear_path = True`。

### 1.5 用户的核心担忧

> "这意味着这个视频不是实时的是吗？所以我机器人在做出行为决策判断的
> 时候也不可靠？"

回答这个问题分三层：

**(a) "实时性"分两个维度：姿态实时 vs 几何实时**

- **姿态实时**（机器人当前转头/侧倾/位置）：实时的。因为大脑的 MjData
  每 1/20 秒同步一次 DDS 来的最新 motor_q + base_quat + base_pos，再
  调 `mj_forward` 走一次正运动学。所以画面里机器人腰部往前推进、视
  野往前移、头部如果有俯仰也会跟着动 —— 这些都是实时的。
- **几何实时**（场景里有什么东西）：**不是从仿真器实时拷贝过来的**。
  几何来源是大脑启动时一次性加载的 MJCF。如果仿真器在运行时动态加了
  一个箱子（实际上 unitree_mujoco 不会这么干，但理论上可以），大脑这边
  渲不出来。

**(b) 修复前是不是不可靠？**

是。**严重不可靠**。修复前大脑视觉做出的所有判断都建立在"前方是空地板"
的虚假前提上。`describe_scene` / `query_scene_state` / 深度避障这三条全
都瞎掉。`_skill_walk` 内部那个 0.2 秒一次的反应式 abort（见
`skill_server.py:313-334`）也跟着瞎掉，因为它读的是同一个 scene_bus，
ground constraint 永远 clear。换句话说，**修复前在仿真里跑 walk，机器人
是闭着眼睛在走** —— 仿真器物理引擎会在它撞到箱子时让它摔倒（物理碰撞
是仿真器一侧负责的），但大脑事先没有任何机会预警或绕开。

这就是为什么用户哪怕走到障碍前面再问一遍，回答仍是"无障碍"。

**(c) 修复后是否可靠？**

修复后两边 MJCF 同步加载 `scene_29dof_terrain.xml`，大脑渲染出来的画面
和仿真器看到的画面在几何上**完全一致**（同一份地形、同样的箱子、同样的
heightfield，包括 `terrain_perlin.png` 都是同一张图）。所以：

- `describe_scene` 给视觉模型的 JPEG 现在是真实场景，模型能看到障碍并
  如实描述。
- `query_scene_state.nearest_obstacle_m` 在机器人靠近箱子时会真的报出
  距离（受限于 cone 范围 [0.5, 1.5] m 和摄像头几何 —— 见 §1.6 残余风险）。
- `_skill_walk` 的反应式 abort（路径不通 / 障碍 < 0.5 m）会真的触发。

**所以答案是：修复前严重不可靠，修复后在静态地形里可靠。**

**(d) 真机会怎样？**

真机部署的时候大脑根本不需要 MJCF —— 它会从机器人头部物理摄像头读 RGB
和深度（或者用 Depth-Anything 这类单目深度模型补深度）。`MuJoCoHeadCamera`
是 sim-only 类。仿真器侧的这套坐标流转换成真机时变成：

```
真机硬件相机 → CameraHub.latest_head_bgr → 同样喂给 describe_scene / 深度推理
```

真机不存在"两份 MJCF 不一致"这种问题，因为根本没有 MJCF —— 真机看到的
就是物理世界。仿真里出现这个 bug 的根本原因是仿真世界被两个进程独立
"想象"了一遍，而想象的版本不一致。

### 1.6 残余风险（修复后还要注意的）

1. **如果 `unitree_mujoco/simulate_python/config.py` 改了 `USE_TERRAIN`，
   要同步改 g1_brain 这边的 `robot.mjcf_path`。** 我加了一段注释提醒这件
   事（`configs/g1_brain.yaml:9-15`）。
2. **大脑的头部摄像头几何 vs 障碍高度**：当前摄像头挂在 torso_link 上，
   位置 (0.08, 0, 0.45)，仰角水平。机器人站立时摄像头世界坐标 z ≈ 1.15 m，
   vfov = 60°（半角 30°）。所以画面下边沿打在地板上的水平距离约 2.0 m。
   如果一个高度 0.18 m 的小箱子在机器人 1 m 正前方，箱子顶在摄像头视野
   下方边缘以下，**摄像头看不到**。这是几何决定的，不是 bug。设计上对
   策有几条：(a) 把头部摄像头朝下倾一点；(b) 在腰部加一颗第二摄像头看
   近场地面；(c) 用 LIDAR/超声补盲区。这些都属于硬件/MJCF 层增量改动，
   超出当前 issue 范围。
3. **静态场景假设**：如果有一天 `unitree_mujoco` 引入了运行时动态生成
   障碍，大脑就看不到 —— 因为大脑加载的 MJCF 是磁盘上的快照。届时需要
   把仿真器的真实 MJCF 状态通过 DDS 推过来，或者改用"从仿真器 viewport
   截屏"的方案。
4. **`compute_ground_constraint` 的 cone 带 [0.5, 1.5] m**：这个范围是为
   "近场避障"设计的。地板深度通常是 2.0+ m（见 §1.6.2 的几何分析），所
   以地板天然不会被错报为障碍 —— 但低矮障碍如果离摄像头很近（< 0.5 m）
   也会"穿透"出 cone 下沿，深度报不出来。这跟 (2) 同源。

### 1.7 修了什么文件 / 哪几行

| 文件 | 改动 |
|---|---|
| `configs/g1_brain.yaml` | `robot.mjcf_path` 改成 terrain；`cameras.head.mjcf_path: null`（继承 `robot.mjcf_path`） |
| `g1_brain/perception/cameras.py` | `CameraHub.__init__` 新增 `robot_mjcf_path=` kwarg；`_build_head` 优先级：`cameras.head.mjcf_path` > `robot_mjcf_path` > `G1_MJCF_PATH` 环境变量 > terrain 默认 |
| `g1_brain/perception/runner.py` | `PerceptionRunner.start` 把 `robot_mjcf_path` 透传给 `CameraHub` |
| `g1_brain/apps/agent_main.py` | 主流程构造 `CameraHub` 时把 `cfg.robot.mjcf_path` 传进去 |

---

## 2. 问题二：recall 第一个动作返回错误

### 2.1 用户的怀疑 vs 实情

用户怀疑："是不是每一轮 hi sparky 都给我新开启了一轮对话的 jsonl 文件，
导致我无法正确 recall 我第一个执行的动作？"

**这个怀疑不成立**。我用 `wc -l` + 逐行解析验证了
`logs/conversations/2026-05-07T09-16-15Z-4cd797df.jsonl`：单文件 192 行，
覆盖全部 14 个用户 turn（`t-0001` ~ `t-0014`），中间用户说了多次 "hi
sparky" 触发 wake-word，jsonl **没有切分**。

代码侧验证：`g1_brain/brain/conversation_logger.py:122-134` 显示文件 path
在 `ConversationLogger.__init__` 里**只生成一次**；wake 事件走的是
`log_wake_event` / `log_barge_in`，只是往同一个 fh 追加 meta line，**不会
重新 open**。`audio-control-update01.md` §1 也明文写了 "Per-process
conversation jsonl. Each `agent_main` run writes one file"。

所以 jsonl 持久层没问题。问题在另一个地方。

### 2.2 真实根因：OpenAI Realtime 上下文的有损记忆

回放 jsonl turn t-0014：

```
USER: Tell me what was my first motion in this car?
ASSIST: From what I can recall, your first motion command in this conversation
        was asking me to raise my right hand.
```

但实际第一动作是 turn t-0003 的 `walk`：

```
USER turn t-0003: Move forward.
TOOL_USE: walk({vx: 0.2, duration_s: 1.0})  ← 第一个 motion
...
USER turn t-0008: Raise your right hand.
TOOL_USE: gesture({name: "wave_right"})  ← 第六/七个 motion
```

模型答错了。**模型没有去查 jsonl，它只是凭对话上下文里残留的记忆回
答**。OpenAI Realtime 的 conversation context 在 server 侧维护，但在长
对话或大量 tool_call 的情况下会做隐式压缩 / 截断 / 摘要 —— 老 turn 不一
定能字面保留。况且模型即便保留了原文，也可能"以为" raise hand 比 walk
更"motion-y"。

总之：**靠模型的内省记忆做"召回"是不可靠的**，必须给它一个能查持久化
日志的工具。

### 2.3 修复：新增 `recall_history` 工具

新工具签名（OpenAI Function 格式）：

```jsonc
{
  "name": "recall_history",
  "parameters": {
    "kind":  "actions" | "user_turns" | "all",   // 默认 "actions"
    "limit": int 1..200                           // 默认 20
  }
}
```

实现见 `g1_brain/skills/skill_server.py:_skill_recall_history`：

1. 读 `self.conv_logger.path`（即当前 session 的 jsonl）；
2. 解析每行 JSON；
3. 按 `kind` 过滤：
   - `actions` 只保留 `tool_use` 且 `tool_name in {walk, turn, gesture,
     static_pose, look_at, approach, mock_imitate, stop, release_arms}`
     —— 严格的"机器人执行了什么动作"。
   - `user_turns` 只保留用户说话的 turn；
   - `all` 三类（user / assistant / tool_use）交错。
4. **最早的在前**（`events[0]` 就是真正的第一条），在末尾按 `limit` 截
   断 —— 这样 "first action" 类问题永远拿到正确答案。
5. 返回 `{ok, kind, session_id, total_matched, returned, events}`。

prompt 同步更新（`g1_brain/brain/prompts.py`）：

> Look up the persistent session log via recall_history when the user asks
> about past actions ("what did you just do", "what was my first command",
> "list everything you've executed"). Your in-context memory may have lost
> or reordered older turns; the jsonl is the canonical record. Always call
> recall_history before answering recall questions instead of guessing.

工具也加进 `safety/supervisor.py` 的 `ALLOWED_TOOLS_NO_MOTION`，并补了
sanitize 分支检查 `kind` 合法性。

### 2.4 测试

`tests/test_skill_server.py` 新增三个回归测试：

1. `test_recall_history_returns_actions_in_jsonl_order` —— **专门防止刚
   才那个 "raise hand" 错答**：jsonl 里先 walk 后 gesture，断言返回时
   walk 在前；同时验证非 motion 工具（describe_scene）被正确过滤掉。
2. `test_recall_history_disabled_when_no_logger` —— 当 transcript 关闭
   时，工具返回 `ok=false, reason="transcript disabled"`，不会崩。
3. `test_recall_history_user_turns_filter` —— `kind="user_turns"` 只返回
   user 内容。

### 2.5 修了什么文件

| 文件 | 改动 |
|---|---|
| `g1_brain/skills/skill_server.py` | `__init__` 新增 `conversation_logger=` kwarg；新增 `_skill_recall_history` |
| `g1_brain/skills/tool_schemas.py` | 新增 `_recall_history()` schema；接到 L1；vision_only 白名单加上它 |
| `g1_brain/safety/supervisor.py` | `ALLOWED_TOOLS_NO_MOTION` 加上 `recall_history`；FAULT 状态白名单加上；`_sanitize_no_motion` 加 sanitize 分支 |
| `g1_brain/brain/prompts.py` | 两个 prompt（full / vision_only）都加了 recall_history 使用指引 |
| `g1_brain/apps/agent_main.py` | `conv_logger` 提到 `skill_server` 之前构造，传给 `_try_build_skill_server` |
| `tests/test_skill_server.py` | 3 个新测试 |
| `tests/test_tool_schemas.py` | 数量从 13/16/3 改成 14/17/4 |

---

## 3. 问题三：走 10 米被拆成 50 步，每步都要 y/N

### 3.1 root cause

在 `confirm` 模式下，`SafetySupervisor._confirm_in_terminal`
（`g1_brain/safety/supervisor.py:100`）每个 motion 工具调用都会弹一次
y/N。原 yaml 限制 `safety.walk.duration_max_s = 1.0`，加上 prompt 里写：

> Walk durations <= 1.0 s, vx <= 0.2 m/s, ...

所以 LLM 看到"走 10 米" → 在心里算 10 / 0.2 = 50 秒 → 觉得自己只能 1
秒一次 → 拆成 50 个 `walk(0.2, 1.0)`。jsonl turn t-0005 / t-0012 直接看
得到这种连发：

```
walk(vx=0.2, duration_s=1.0)
walk(vx=0.2, duration_s=1.0)
...（10 次）
```

每次都过一次 `safety.validate()`，每次都弹 y/N。用户体验完全崩。

### 3.2 修复方案

关键认知：`_skill_walk`（`skill_server.py:294`）**已经实现了** 0.2 秒一
次的反应式场景检查 —— 一旦 ground constraint 报 `clear_path=False` 或者
`nearest_obstacle_m < 0.5 m`，立即 break + 把 vel 设回 0。所以**长持续
时间的 walk 跟"很多个短 walk"在安全性上等价**：障碍出现的瞬间都会停。
唯一的区别是 confirm 次数。

所以最干净的修法：

1. **抬高单次 walk 的最大 duration**：yaml 从 1.0 → 60.0 秒（≈ 12 m at
   0.2 m/s 一次确认）；tool schema 的 `duration_s.maximum` 同步到 60.0。
2. **改 prompt**，把"<= 1.0s"硬性规则去掉，改成显式要求"用一次长 walk
   完成多米请求"，并解释为什么（confirm 模式 y/N 成本）：

   > vx <= 0.2 m/s, vy <= 0.1 m/s, wz <= 0.3 rad/s. Single walk call may
   > run up to 60 s (≈ 12 m at 0.2 m/s); the skill polls perception every
   > 0.2 s and aborts on its own when the path becomes blocked or an
   > obstacle is within 0.5 m, so DO NOT chain many short walks for
   > multi-meter requests — issue ONE walk(vx=0.2, duration_s = distance
   > / vx) call. Operator confirmation in confirm-mode is per-call, so
   > chaining 50 × walk(0.2, 1.0) for "10 m" produces 50 y/N prompts and
   > is forbidden.

3. **不动 SafetySupervisor 的 confirm 逻辑**：保留 confirm 是显式安全开
   关，只是让一次确认覆盖更长距离。

### 3.3 为什么不直接做"组合技 walk_distance"工具？

也是一个选项，但有缺点：

- 增加了一个 LLM 必须学的新工具名；
- 内部还是要循环调用 `_skill_walk`，不会比"一次长 walk"更安全；
- `combo.set_command(vx, vy, wz)` 是无心跳的设值（`g1_sim_rl_combo.py:850`），
  设一次后就一直生效到下次设值，不会自己超时停下。所以一次长 walk 完
  全不需要循环 set —— 内部 sleep 就够了。

简单方案胜出。

### 3.4 残余风险

- `_skill_walk` 走完 finally 时会 `combo.set_command(0,0,0)`，所以正常退
  出会停。
- 如果中途用户 "hi sparky" 触发 barge-in，
  `BrainConversationStateMachine._handle_barge_in` 会调
  `stop_skill_callable()`（`agent_main.py:1163-1168`），里面执行
  `skill_server.execute("stop", {})` → `_skill_stop` → 把 vel 设 0。**正
  在跑的 walk 协程**仍在 sleep 循环里，但它的 set_command 是一次性的，
  不会再覆盖 stop 的 0；所以机器人停下，walk 协程跑完 duration 自然结
  束。这点已经在 `audio-control-update01.md` §3 描述过。

### 3.5 修了什么文件

| 文件 | 改动 |
|---|---|
| `configs/g1_brain.yaml` | `safety.walk.duration_max_s: 1.0 → 60.0`，加注释说明取舍 |
| `g1_brain/skills/tool_schemas.py` | walk 的 `duration_s.maximum: 1.5 → 60.0`；description 改成"用一次长 walk，反应式 abort 已经覆盖障碍" |
| `g1_brain/brain/prompts.py` | 重写 walk 时长约束段；新增"禁止把 10 m 拆成 50 个 1 s walk"的硬规则 |
| `tests/test_tool_schemas.py` | `duration_s.maximum` 断言改成 60.0 |

---

## 4. 三个问题之间的关联

这三个 bug 看似独立，但其实都暴露出同一个深层架构问题：

> **大脑的"自我感知"和"自我记忆"都不可信，除非有持久化外部源做锚。**

- 问题 1：自我感知（视觉）依赖大脑端 MJCF；MJCF 跟仿真器走散 → 视觉失
  真。修复的本质是**让感知锚定到一个外部权威**（这里是仿真器加载的同
  一份 MJCF）。
- 问题 2：自我记忆（对话历史）依赖 OpenAI Realtime 内部 context；context
  有损 → 召回失真。修复的本质是**让记忆锚定到持久化 jsonl**（这是用户
  之前已经为 Claude harness 设计好的）。
- 问题 3：表面看是 UX 问题（多步确认），但深层是 **prompt 逼着 LLM 把
  长动作切碎，用户只能逐步审批**；切碎的每一步都依赖大脑当时对场景的
  自我感知判断。修复让它一次干完，**安全交还给反应式 abort**（更可靠
  的，因为反应式 abort 直接读 ground constraint，不依赖 LLM 推理）。

下一步如果要继续提高自治度，建议方向：

1. **持久记忆 → 检索增强**：`recall_history` 当前是全量返回，未来可加
   FTS5 索引（用户已经在 g1_brain_voice_persistence_intent 备忘里规划
   过），让大脑"按关键词"回忆。
2. **感知 → 多源融合**：除了 MuJoCo 头部摄像头，还可以接 USB 用户摄像
   头 / 仿真器 viewport 截屏 / LIDAR 模拟器，避免单源失真。
3. **UX → 模式分级**：`confirm` 适合调试；日常运行考虑用 `active` 模
   式 + 显式"危险动作"才询问。yaml 里已经有 `run_mode: active`（默认），
   只是用户当前用 `--mode confirm` 启动覆盖了。

---

## 5. 验证

`pytest tests/ -q` ：276 passed。

包含：
- 273 个原测试 + 3 个新 `recall_history` 测试。
- `test_tool_schemas` 计数测试更新（13/16/3 → 14/17/4），确保 `recall_history`
  在 sim 模式被列出，并且在 vision-only 子集里也被保留（视觉模式下大
  脑无法移动，但仍然要能召回过去说过的话）。
- `test_skill_server` 里新加的回归用例直接覆盖 "first action returned
  walk not gesture" 这种具体失败模式。

需要用户验证的（不能自动化的部分）：

1. 重新启动 `agent_main` 之后，让机器人走到地形里，问 "what do you see"
   或 "are there obstacles"，应该看到机器人描述出箱子/阶梯/heightfield。
2. 让机器人 "walk forward 10 meters"，应该只看到一次 y/N 提示。
3. 走完之后问 "what was my first command"，应该听到机器人调用
   `recall_history` 然后返回正确的 `t-0001` 用户原话。
