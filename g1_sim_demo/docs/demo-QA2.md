# demo-QA2：闭环平衡策略、双 demo 是否能并行、以及"边走边挥手"的正确做法

承接 `demo-QA1.md`。本文回答你新提的四个问题，并补一个**单进程合并 demo**（`g1_sim_rl_combo.py`），把"RL 步行 / 站立平衡"和"键盘上半身姿态"塞进同一个控制器里。

> 涉及的源码：
> - `g1_sim_demo/g1_sim_keyboard.py`：纯静态姿态 demo（无平衡反馈）
> - `g1_sim_demo/g1_sim_rl_walk.py`：RL 速度跟踪 demo（**这就是闭环平衡策略**）
> - `g1_sim_demo/g1_sim_rl_combo.py`（**新增**）：上面两件事合在一个进程里跑
> - `unitree_mujoco/simulate_python/unitree_sdk2py_bridge.py`：仿真桥（订阅 `rt/lowcmd`，发布 `rt/lowstate`）

---

## 1. "我的两个 demo 里都没有闭环平衡策略？我希望补上？"——其实已经有了

**结论：闭环平衡策略已经在 `g1_sim_rl_walk.py` 里**。它就是你要的那个东西，不需要额外补。

`g1_sim_rl_walk.py` 加载的是 `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx`，每 20 ms 跑一次：

1. 从 `rt/lowstate` 读 IMU + 29 关节角 / 角速度，组成 98 维 obs；
2. 喂给 ONNX 策略，得到 29 维 raw action；
3. `q_target = raw_action × scale + default_joint_pos`；
4. 用 yaml 里的 stiffness/damping 作 Kp/Kd，发 `rt/lowcmd`；
5. 仿真桥把它转成 `τ = Kp·Δq + Kd·Δdq` 写进 MuJoCo `mj_data.ctrl`。

**这里"闭环"体现在哪一步**？——第 1 步把"当前 IMU 姿态 + 重力方向投影 + 关节实际状态 + 上一帧 raw action"整套**反馈量**塞回 obs。策略是在仿真里被"重力骚扰、地面摩擦随机化、电机延迟、力矩饱和、外力 push"训出来的，所以它输出的 `raw action` 本身就是"为了让我在干扰下还能站稳 / 跟上速度命令"而生成的修正量。这就是闭环。

> 一句话区分：
> - `g1_sim_keyboard.py`：**开环 PD 关节位置控制**——目标就是预设关节角，不看 IMU、不看脚底接触力，纯"硬撑"。
> - `g1_sim_rl_walk.py`：**闭环全身 RL 控制**——每帧根据 IMU + 关节状态，经过神经网络算出关节目标偏移；目标随姿态变化而变化。

所以你想要的"在地面上站着接收键盘命令"的能力，**`g1_sim_rl_walk.py` 已经具备**：把它启动起来、按 `r` 让命令清零，机器人就站着不动；按 `w` 它就往前走；松开后再按 `r` 又站住。它不需要悬挂带（吊带可以剪掉）。

**唯一缺失**的是"边站着 / 走着，边按键挥手 / 鞠躬 / T-pose"——这是 §4 里要讲的**合并 demo**。

---

## 2. "为什么我只是按 8 把机器人放到地上，静态动作 demo 也能跑？"

这个问题问得非常好，正确答案是**它能跑是个"侥幸"，并不是真的有平衡能力**。具体拆开看：

### 2.1 按 `8` 不等于关掉悬挂带

回顾 `unitree_sdk2py_bridge.py` 里 `ElasticBand`：

```python
if key == glfw.KEY_8:
    self.length += 0.1     # 绳子变长 0.1 m，而不是断开
if key == glfw.KEY_9:
    self.enable = not self.enable   # 真正断开 / 接回
```

按几次 8，绳子从 `length=0` 变成例如 `length=1.2`。但 `enable` 还是 `True`，弹簧公式继续生效：

```
f = stiffness*(distance - length) - damping*v
```

`stiffness ≈ 200 N/m`、`damping ≈ 100`（具体数见 `ElasticBand.__init__`）。即使 `distance ≈ length`（绳子不绷紧也不太松），只要机器人姿态有偏（躯干往前栽 5 cm），`distance` 就比 `length` 大 5 cm，弹簧立刻产生 `200 × 0.05 = 10 N` 的回拉力——这是一个"看不见的隐形扶手"。

### 2.2 PD 把关节硬锁在零位

`g1_sim_keyboard.py` 默认 Kp 给得很高（髋 60、膝 100、踝 40、腰 60、肩肘腕 40），并且把 29 个关节都硬锁在 zero pose：

- zero pose 下两腿伸直（hip pitch = 0、knee = 0、ankle = 0），脚踩在地上时**身体是直立的**；
- 高 Kp 意味着哪怕躯干微微前栽 1°，膝盖会被强行拉回 0°；
- 这相当于"把两根铁棍当腿"——不是平衡，是**靠刚度把姿态钉死**。

### 2.3 上半身动作幅度小、惯性可忽略

挥手 / 敬礼 / 鞠躬这些动作只让 1~3 个手臂关节动 ±0.5~1.5 rad，质量很小（手臂占整机 < 5%），重心位移量在 1~3 cm 量级。隐形扶手 + 大刚度的"两根铁棍腿"足够吸收这种小扰动，所以**看上去机器人能站着挥手**。

### 2.4 但下半身动作 / 急扰动 / 持续扰动就会暴露问题

- 按 `c`（深蹲）：膝盖弯到 1.3 rad，髋关节角度 −0.8，**重心整个往下走 20 cm**——隐形扶手 + 高 Kp 不一定够。多按几次往往会摔；
- 按 `v`（右腿前踢）：单脚支撑，**这是欠驱动问题**，没有平衡器必摔；
- 按 `b`（鞠躬）后躯干前倾 28°：腰关节直接命令到 0.5 rad，质心剧烈前移，仅靠隐形扶手 + 髋膝刚度勉强维持，但很容易引发振荡；
- 按 `9` **真的剪绳子**之后做任何动作：基本必摔（除非地面摩擦异常大且姿态正好对）。

### 2.5 一句话总结这件事

> 在按 `8` 之后还能做静态动作 = **(a) 弹簧没真的关 + (b) 高 Kp 把腿钉成铁棍 + (c) 上半身动作幅度小**，三个条件叠加出来的"假象"。
> 不是平衡控制器在干活——所以你**不能指望它去走、去单脚支撑、去真摔之后爬起来**。这些事必须交给 §1 里的 RL 策略。

---

## 3. 走路 demo 该怎么跑（一步一步）

`g1_sim_rl_walk.py` 已经写好，路径 `~/unitree/unitree-notes/g1_sim_demo/g1_sim_rl_walk.py`。这是一个完整的**双终端流程**。

### 3.1 一次性环境检查

```bash
conda activate unitree
python -c "import onnxruntime; print('ort', onnxruntime.__version__)"
# 期望：能打印一个版本号（如 1.20.x）。如果报 ImportError，先：
#   pip install onnxruntime
# 不需要 onnxruntime-gpu，CPU 推理 50 Hz 占 < 5% CPU。
```

确认 `unitree_mujoco/simulate_python/config.py`：

```python
ROBOT = "g1"
ROBOT_SCENE = "../unitree_robots/g1/scene.xml"
DOMAIN_ID = 1
INTERFACE = "lo"
USE_JOYSTICK = 0
ENABLE_ELASTIC_BAND = True   # 仿真启动那一刻挂着，落地时再放
```

### 3.2 终端 1：起仿真器

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

看到 MuJoCo viewer 弹出、G1 默认被吊在 `(0,0,3)` 附近后：

1. **先按几下 `8`**：每按一下绳子放长 0.1 m。一般按 5~8 次脚就触地了。
2. **可选** 按 `9`：彻底关掉弹簧（带子从场景里消失）。落地后关或不关都行——下面的 RL 策略不依赖弹簧。
3. **避免**：在脚还悬空时按 `9`——机器人会在策略接管前就自由下落，落地姿态可能不可控。

> 这两步决定了机器人"启动姿态"，影响后面策略的初始 obs。如果它落地时是斜的或者腿姿势奇怪，按几下 `7` 把它吊起来重新放就好。`R`（大写）也能让 MuJoCo 复位到 keyframe 0。

### 3.3 终端 2：起 RL demo

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_walk.py
```

期望输出：

```
[rl] simulator mode on lo (domain 1).
[rl] loaded deploy.yaml (vx∈(-0.5, 1.0), vy∈(-0.5, 0.5), wz∈(-1.0, 1.0), period=0.60s, step_dt=0.02s)
[rl] loaded policy: /home/.../policy.onnx
[rl] waiting for first /rt/lowstate ...
[rl] mode_machine=0. Ramping to default pose over 3.0 s ...
[rl] policy ready, standing in place. wsadqe to drive.
```

### 3.4 关键时间线

```
t = 0.00 s   demo 开始，订阅 lowstate，等首帧
t ≈ 0.10 s   收到首帧（mode_machine、29 关节角）
t = 0.10 s   开始 3 s cosine 过渡：从"实测姿态" → "policy default_joint_pos"
             这一段没动 RL 策略，只是把姿态慢慢摆成训练时的初始姿态，避免一上来 obs 偏离训练分布
t = 3.10 s   policy_active = True，进入 50 Hz 主循环：
                obs (98) → policy.run() → raw_action (29)
                q_target = raw_action × scale + offset
                Kp/Kd 来自 yaml stiffness/damping
                发 rt/lowcmd
             此时 cmd = (0, 0, 0)：策略输出"原地踏步 / 站住"
```

按 `r` 后命令保持 (0,0,0)，机器人就站着；按 `w` 后 vx 变成 +0.2 m/s，策略立刻开始迈步前进。

### 3.5 完整按键表

| 键 | 作用 | 命令变化 |
|---|---|---|
| `w` | 加速前进 | `vx += 0.2 m/s`（夹到 [-0.5, 1.0]） |
| `s` | 加速后退 | `vx -= 0.2 m/s` |
| `a` / `d` | 左 / 右平移 | `vy ± 0.1 m/s`（夹到 [-0.5, 0.5]） |
| `q` / `e` | 左 / 右转身 | `wz ± 0.3 rad/s`（夹到 [-1.0, 1.0]） |
| `r` | 站住 | `(vx, vy, wz) = (0, 0, 0)` |
| `f` | 全速前进 | `vx = 1.0 m/s` |
| `space` | 软关 | Kp/Kd 在 1 s 内拉到 0；机器人慢慢瘫倒 |
| `?` | 打印帮助 | — |
| `x` / Ctrl-C | 退出 | 先 1 s 软关，再停止发 lowcmd |

### 3.6 排错速查

| 现象 | 原因 | 修复 |
|---|---|---|
| `ImportError: onnxruntime` | conda env 没装 | `conda activate unitree && pip install onnxruntime` |
| 卡在 `waiting for first /rt/lowstate` | 仿真没起 / DOMAIN_ID 不对 / interface 不是 lo | 见 `mujoco_use.md` §6 |
| 落地瞬间机器人甩飞 | 弹簧还在拉，PD 还没接管 | 让仿真先稳定 1~2 s，再开 demo |
| 机器人拼命踏步但走不动 / 走偏 | 落地姿态歪、IMU 四元数有 NaN、地面摩擦太低 | 退出 demo → viewer 按 `R` 重置 → 重启 demo |
| 走着走着突然跪下 | 命令超出训练范围（比如 `vx = 1.5`）/ 持续侧向加速度 | 按 `r` 立刻清零；`vx` 上限就是 1.0（yaml 里写的） |
| 退出后机器人维持着最后一帧目标 | 退出虽然把 Kp 拉到 0，但停止发 lowcmd 后桥保留最后值 | viewer 按 `R` 重置物理 |

---

## 4. "我能不能让 `g1_sim_rl_walk.py` 和 `g1_sim_keyboard.py` 同时跑？" —— **不行，会互相打架**

### 4.1 为什么不行：DDS publisher 冲突

两个脚本都做了同一件事：

```python
# g1_sim_keyboard.py:423
self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)   # 500 Hz 发

# g1_sim_rl_walk.py:239
self.cmd_pub = ChannelPublisher("rt/lowcmd", LowCmd_)   # 50 Hz 发
```

`rt/lowcmd` 是 DDS topic，**两个 publisher 都被仿真桥的 subscriber 收到**。仿真桥每收到一条就把 29 个 motor_cmd 全量覆盖到 `mj_data.ctrl[*]`，所以：

- 50 Hz 的 RL 策略写入"想让机器人保持平衡的关节目标"；
- 500 Hz 的键盘 demo 写入"挥手姿态对应的关节目标"；
- **键盘 demo 频率高 10 倍**，绝大多数物理步看到的都是它的目标 → RL 策略输出基本被冲掉 → 平衡能力丧失 → 机器人摔倒。

如果反过来 RL 写得更频繁，那键盘 demo 的挥手会几乎看不见，因为只有偶尔一帧能"突围"到 ctrl 上。**两个 publisher 同时存在 = 一个胜出 + 抖动 + 控制行为完全不可预测**。这是分布式系统里的典型坑，不是 Unitree 仓库的 bug，是 DDS 的"last writer wins"语义本身带来的。

### 4.2 viewer 是同一个 MuJoCo，没问题

你担心的"两个进程是不是用的同一个 MuJoCo viewer"——**是同一个**。MuJoCo 物理过程在 `unitree_mujoco.py`（终端 1）那个进程里，两个 demo 都是 DDS 客户端，只动 `rt/lowcmd`。viewer 永远只显示终端 1 进程持有的 `mj_data`。

所以"同一个 mujoco 显示"这件事天然成立，**问题完全在于 `rt/lowcmd` 由谁来写**。

### 4.3 三种正确做法

| 你想做的事 | 怎么做 |
|---|---|
| 只想看挥手 / 鞠躬 / T-pose | 终端 1 起 sim → 保持悬挂带启用 → 终端 2 跑 `g1_sim_keyboard.py` |
| 只想看走路 / 站立 / 转向 | 终端 1 起 sim → 按几下 `8`（可选 `9`）→ 终端 2 跑 `g1_sim_rl_walk.py` |
| 想"边站 / 边走 + 键盘控制上半身姿态" | 终端 1 起 sim → 终端 2 跑 **`g1_sim_rl_combo.py`**（**新增**，详见 §5）|

### 4.4 你*可以*在第三个终端开个观察脚本

如果只是想看状态、不发命令，可以另开终端起一个**纯订阅** `rt/lowstate` 的观察脚本（参考 `g1_sim_low_level.py` 里 `LowStateHgHandler`，只保留 subscriber 部分）。**只读不写**就不会冲突。

---

## 5. 新增的 `g1_sim_rl_combo.py`：单进程合并 demo

### 5.1 设计思路

只允许**一个** publisher 往 `rt/lowcmd` 写，从根本上避免 §4 的冲突。流程：

```
                   ┌──────────────────────────────┐
                   │  Combo controller (single proc)│
                   │                                │
   key thread ────►│  walking cmd: vx, vy, wz       │
   key thread ────►│  arm gesture queue (keyframes) │
                   │                                │
                   │  50 Hz tick:                   │
                   │     1. policy(obs) → raw_action│
                   │     2. q_target_full =         │
                   │           raw_action·scale+off │
                   │     3. if gesture active:      │
                   │           q_target[15:29] =    │
                   │             arm_q_blended      │
                   │     4. publish rt/lowcmd       │
                   └──────────────────────────────┘
```

关键约束：

- **腿（0~11）和腰（12~14）始终交给 RL 策略管**——它们决定平衡，不能被键盘姿态覆盖；
- **手臂（15~28）允许键盘覆盖**——手臂质量小，慢速挥动对平衡的扰动可以被腿/腰策略实时补偿；
- 策略 obs 里的 `joint_pos_rel` 永远来自**真实测量值**（包括被键盘覆盖的手臂），所以策略能感知"手臂在做什么"，并通过腿/腰自动补偿；
- 手臂"无姿态"时回到 `policy_default[15:29]`（也就是 yaml 里的 `default_joint_pos`，不是 zero pose）——这样不会让策略 obs 突然落到训练分布外。

### 5.2 启动顺序

终端 1（仿真器）：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# 按几下 8 让脚落地，可选按 9 关弹簧
```

终端 2（合并 demo）：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
# 等 [combo] policy ready 之后开始按键
```

### 5.3 按键表

```
====  G1 RL walk + arm gesture combo ====
  Walking:
    w / s    forward / backward   (vx ±0.2 m/s)
    a / d    strafe left / right  (vy ±0.1 m/s)
    q / e    yaw left / right     (wz ±0.3 rad/s)
    r        stop walking (cmd → 0,0,0)
    f        full forward (vx → 1.0 m/s)
  Arm gestures (overlay; legs/waist still RL):
    1   wave right arm
    2   wave left arm
    3   hands up (cheer)
    4   T-pose
    5   salute
    6   clap (twice)
    7   boxer guard
    8   punch combo (jab L+R)
    0   release arms (back to policy default)
  System:
    space   soft-disable Kp/Kd (robot collapses)
    ?       help
    x       quit (settles softly)
==========================================
```

> 数字键 `7 / 8 / 9` 在 demo 终端是手势触发；在 viewer 窗口它们仍然是悬挂带控制——不冲突，因为焦点在哪个窗口键就归哪个进程。

### 5.4 行为预期

- 按 `r` 不按任何手势 → 机器人原地站立、双臂自然摆在策略默认姿态（前伸约 0.35 rad，肘弯 0.87 rad）；
- 按 `5`（敬礼）→ 右手臂在 1 s 内抬起到敬礼姿态，停 1.2 s，再 1 s 内回到策略默认姿态。整个过程**腿和腰仍由策略实时调节**，所以姿态变化不会让机器人摔；
- 按 `w` 让机器人前进，再按 `1` 挥右手 → 一边走一边挥手；
- 按 `0` 立刻取消手势，手臂软回到策略默认；
- 按 `space` 紧急 Kp 软关，机器人慢慢瘫到地上（用于退出前避免硬掉电）。

### 5.5 风险与边界

| 想做 | 能做吗 | 原因 |
|---|---|---|
| 边走边挥手 / 敬礼 / 拍手 | ✅ 可以 | 手臂动作幅度小、慢，策略能补偿 |
| 边走边深蹲 | ❌ 不要做 | 深蹲改的是腿，会和策略打架；本 demo 也不允许覆盖腿关节 |
| 边走边鞠躬 | ⚠️ 不在本 demo 范围 | 鞠躬改腰，腰直接影响 IMU 重力投影，会让策略觉得"我快倒了" |
| 站立时摆 T-pose | ✅ 可以 | 手臂展开重心几乎不动 |
| 走路时快速出拳 | ⚠️ 边缘 | 速度太快会让策略 obs 突变；建议先停步再出拳 |

如果你确实要"边走边鞠躬"，需要重新训一个支持 `commanded_waist_pitch` 的策略（mjlab 里加一个 observation + 一个 reward）。这超出本 demo 范围。

### 5.6 进阶：自定义新手势

`g1_sim_rl_combo.py` 复用了 `g1_sim_keyboard.py` 的 pose 函数（`wave_right_pose`、`salute_pose` 等），所以你想加新手势，只要：

1. 在 `g1_sim_rl_combo.py` 里写一个 `my_pose() -> np.ndarray`（**只用手臂索引 15~28，其它索引留空**——`zero_pose()` 帮你做了）；
2. 在 `ARM_ACTIONS` 列表里加一行 `Action("9", "my gesture", [(1.0, my_pose()), hold(my_pose(), 0.5), (1.0, ARM_REST)])`；
3. 重启 demo，按 `9` 触发。

`ARM_REST` 是脚本里的常量 = `policy_default[15:29]`，确保手势结束后回到策略期望姿态。

---

## 6. 一页 cheat sheet

```
                      g1_sim_keyboard.py        g1_sim_rl_walk.py        g1_sim_rl_combo.py
                      ────────────────────      ────────────────────     ────────────────────
   闭环平衡           ✗（开环 PD）              ✓（ONNX 策略）           ✓（ONNX 策略）
   能站在地上          ✗（必须挂吊带）            ✓                       ✓
   能走路              ✗                         ✓ wsadqe                ✓ wsadqe
   能挥手 / 敬礼       ✓                         ✗                       ✓ 数字键 1~8
   控制频率           500 Hz                    50 Hz                   50 Hz
   rt/lowcmd 写者     键盘 demo                 RL demo                 合并 demo
   跟另一个并行?      ✗ 会冲突                  ✗ 会冲突                ✓ 自己单独跑就够了
```

走通这一节后，你就有了三个互不冲突的演示模式：纯静态姿态（吊带）、纯走路（地面）、走路 + 上半身（地面）。
