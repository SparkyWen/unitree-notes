# demo-QA3：静态动作 demo 真的能"落地站住"吗？以及 `g1_sim_rl_combo.py` 启动崩溃的诊断

> 承接 `docs/demo-QA1.md`、`docs/demo-QA2.md`、`g1_sim_demo/docs/use1.md`。
> 涉及源码：
> - `g1_sim_demo/g1_sim_keyboard.py`（纯静态姿态 demo，本文中称"静态 demo"）
> - `g1_sim_demo/g1_sim_rl_walk.py`（RL 速度跟踪策略，闭环平衡）
> - `g1_sim_demo/g1_sim_rl_combo.py`（RL 平衡 + 键盘上半身姿态合并版）
> - `unitree_mujoco/simulate_python/unitree_sdk2py_bridge.py`（仿真桥 + 悬挂带逻辑）
> - `unitree_mujoco/simulate_python/unitree_mujoco.py`（仿真主进程）

---

## TL;DR

**你的直觉 100% 是对的**：

1. `g1_sim_keyboard.py` 这种静态动作 demo **没有任何闭环平衡**——它只是高 Kp PD 把每一个关节硬锁到一组预设角度。
2. 在地面上"站着接收键盘命令"的能力**只能由闭环 RL 策略提供**——也就是 `g1_sim_rl_walk.py`，或者把它合进键盘演示的 `g1_sim_rl_combo.py`。
3. 如果你**不挂悬挂带 / 按了 viewer 里的 `9`**，跑静态 demo 几乎一定会摔；你看到的 `WARNING: Nan, Inf or huge value in QACC at DOF 5. The simulation is unstable. Time = 19.6950.` 就是 **MuJoCo 物理因机器人摔倒、足底接触穿模、加速度爆掉**而打出来的。
4. 因此**不是要"给静态 demo 加闭环平衡"——而是不要在地面上跑静态 demo**，需要在地面上跑就直接用 `g1_sim_rl_walk.py` 或 `g1_sim_rl_combo.py`。
5. `g1_sim_rl_combo.py` 启动后崩溃，traceback 落在 `select.select([sys.stdin], ...)` 上，**和策略本身无关**——这是终端 / TTY 输入层的问题（详细诊断在 §5）。

---

## 1. "为什么按 `9` 就会倒地？"——把整条链路捋一遍

### 1.1 `9` 键到底做了什么

`unitree_sdk2py_bridge.py:421-428`：

```python
def MujuocoKeyCallback(self, key):
    glfw = mujoco.glfw.glfw
    if key == glfw.KEY_7:
        self.length -= 0.1     # 悬挂绳变短 0.1 m
    if key == glfw.KEY_8:
        self.length += 0.1     # 悬挂绳变长 0.1 m
    if key == glfw.KEY_9:
        self.enable = not self.enable  # 切换悬挂带启用 / 关闭
```

`9` 是真正的**剪绳子开关**——一按它，弹簧公式

```
f = stiffness*(distance - length) - damping*v
```

整条不再被 `mj_data.xfrc_applied` 注入到 `torso_link`。机器人此刻**完全靠自身关节力矩在重力下维持姿态**。

### 1.2 静态 demo 此时能做什么

`g1_sim_keyboard.py` 的控制循环（500 Hz）只做一件事：

```python
self._publish(self.q_cmd)   # 把当前 q_cmd 转成 LowCmd_，PD 增益 = KP_DEFAULT * kp_scale
```

而 `q_cmd` 的来源**只**有"对 `(q_from, q_to)` 做 cosine ease-in-out 插值"——`q_from` 是上一个关键帧的关节角，`q_to` 是用户按键触发的预设姿态。**整段代码里没有读 IMU、没有看脚底接触力、没有 ZMP / CoM、没有线性 / 角动量反馈**。这是开环（open-loop）位置追踪，不是闭环（closed-loop）平衡。

桥那头收到 `LowCmd_`，按 `unitree_sdk2py_bridge.py` 里的 PD 公式

```
τ_i = τ_ff_i + Kp_i * (q_des_i - q_meas_i) + Kd_i * (dq_des_i - dq_meas_i)
```

算出 29 个力矩塞进 `mj_data.ctrl`，物理引擎按牛顿欧拉方程推进。**没人在告诉踝关节"现在重心已经偏了，给我向后蹬"**。

### 1.3 因此，按 `9` 之后的物理过程

1. 第 0 ms：悬挂带消失，外力 `xfrc_applied` 归零；
2. 第 0~50 ms：机器人略微下沉（脚底落地或穿模一点），重力开始把躯干往随机方向拉（实际上初始姿态从来不是数学上严格平衡的，IMU quat 里就有几度的偏差）；
3. 第 50~500 ms：踝关节虽然还在追"零位"，但**踝下面的足板和地面之间没有反向加速踝关节的策略**——质心一旦越过支撑多边形，就再也回不来；
4. 第 0.5~2 s：身体倾斜越来越大，膝、髋的位置 PD 反而把姿态往"奇怪的内八 / 外八"方向锁；
5. 第 2~20 s：终于摔到地面，上身 / 头部和地面接触 → MuJoCo 求解的接触约束爆炸（穿透、两个刚体共线、雅可比奇异等），**`QACC` 出现 NaN/Inf**，于是你看到的：

   ```
   WARNING: Nan, Inf or huge value in QACC at DOF 5. The simulation is unstable. Time = 19.6950.
   ```

   `DOF 5` 是 `floating_base_joint` 的最后一个自由度（浮基的 z 方向旋转 / 偏航的微分位置），加速度爆掉典型出现在"高速碰撞 + 大角速度 + 小接触面积"组合下，正好对应"摔倒瞬间"。

> 一句话：**没有闭环策略 + 按 9 = 必倒。** 你完全理解对了。

### 1.4 为什么 use1.md 反复强调"viewer 里别按 9"

正因为静态 demo 没有平衡能力，`use1.md` §2 写得非常死：

> **不要按 9！** 按了就剪绳子，机器人会摔。

`use1.md` §3"下半身 / 控制系统键"那段也再次强调**抬腿 / 踢腿这些单脚支撑动作即使在悬挂带启用时都建议用 `7` 把脚抬离地 5 cm**——更别说释放悬挂带了。

---

## 2. "那为什么我之前按 `8` 把绳子放长，机器人也站住了？"

这个问题在 `demo-QA2.md` §2 已经详细回答过，这里再压缩一下：

- `8` 只让 `self.length += 0.1`，不动 `self.enable`。弹簧公式继续生效；
- `stiffness ≈ 200 N/m`，机器人躯干随便偏几厘米就会被弹簧拉回去，相当于**"看不见的扶手"**；
- 上半身动作（挥手 / T-pose / 敬礼）只让 1~3 个轻质关节小幅度运动，质心位移 1~3 cm，扶手 + 高 Kp 锁腿足够吸收，所以**视觉上像是"站着"，其实是被吊着**；
- 一旦你按 `9`（`enable = False`）或者动到下半身大动作（深蹲 / 踢腿），扶手消失或者扰动太大，立刻就摔。

**结论**：你在 `8`/`7` 状态下看到机器人"能站"，那是悬挂带在替你做平衡，不是你的 demo 学会了平衡。

---

## 3. "我应该给静态 demo 加闭环平衡策略吗？"——别加，直接用 RL combo

技术上可以"在 `g1_sim_keyboard.py` 上面叠一个 PID 平衡控制器"，但是：

- 双足平衡不是一个 PID 或几个状态机能搞定的问题——经典做法（如 Capture Point、ZMP preview、Whole-Body Inverse Dynamics）需要全身动力学模型 + 优化求解器，工程量大；
- 你**已经**有训好的闭环 RL 策略：`unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx`；
- 并且**你已经有把它和键盘动作合在一起的 demo**：`g1_sim_rl_combo.py`。

`g1_sim_rl_combo.py` 的设计正是为了回答你这个问题——它在 `__doc__` 里写得很清楚（line 1-46）：

```
- 50 Hz RL tick: builds 98-D obs from rt/lowstate, runs policy.onnx,
  converts raw_action -> q_target (29-D).
- When an arm gesture is active, the arm slice (joint indices 15..28)
  of q_target is overridden by a cosine-blended keyframe target.
- Legs (0..11) and waist (12..14) are always under the RL policy.
  ...
Why only arms can be overridden:
  Legs are responsible for balance; waist orientation feeds directly
  into the projected_gravity observation, so a commanded waist tilt
  would make the policy think "I'm falling" and drive the wrong
  recovery torques. Arms are mass-light and the policy is robust to
  arm motion, so this overlay is safe for slow upper-body gestures.
```

也就是说 combo 的工作划分：

| 关节段 | 索引 | 控制源 | 原因 |
|---|---|---|---|
| 腿 | 0..11 | RL 策略 | 平衡的全部责任在双腿 |
| 腰 | 12..14 | RL 策略 | 腰的姿态进 `projected_gravity` obs，乱动等于骗策略 |
| 手臂 | 15..28 | 键盘 overlay（cosine blend） | 质量轻 + 策略对手臂运动鲁棒 |

**这就是你想要的"在地面上站着接收键盘命令"的正确姿势**——不需要再去给静态 demo 加平衡。

---

## 4. 怎么"正确地"在地面上跑（不挂悬挂带）

### 4.1 先用 `g1_sim_rl_walk.py` 验证策略本身能站

终端 1：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# 在 viewer 里按 8 几次把绳子放长（safety net）
# 之后等终端 2 的策略 ready 之后再按 9 剪绳
```

终端 2：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_walk.py
# 等到策略 ramp 完成 / 打印 ready
```

**策略 ready 之后才去按 viewer 的 9**——此时机器人应该能在原地站稳，按 `w/s/a/d` 才会开始走。

### 4.2 然后用 `g1_sim_rl_combo.py` 在站立同时挥手

按 `use1.md` 的两终端流程，把第二终端换成 `g1_sim_rl_combo.py`：

```bash
python g1_sim_rl_combo.py
# 等 "[combo] policy ready" → 再去 viewer 按 9
# 之后键盘里：
#   w/s/a/d/q/e   走 / 转
#   1..8          挥手 / T-pose / 敬礼 / 出拳
#   0             把手臂还给策略默认
#   space         软关 PD（机器人会瘫）
```

### 4.3 一定要遵守的两条顺序

1. **先等策略 ready，再按 9**。如果 boot ramp 还没结束 / ONNX 还没第一次 inference 就剪绳子，机器人没人维持姿态，必摔。
2. **按 9 之前先确认终端 2 没有报 `LowstateTimeout` / 没有挂死**。combo 里有 watchdog（line 367、509），但那只能让它"hold default pose"，机器人没法靠它真正平衡。

---

## 5. `g1_sim_rl_combo.py` 启动后崩溃的诊断

你贴的 traceback：

```
[combo] policy ready. wsadqe to walk; 1-8 arm gestures; 0 release.
Traceback (most recent call last):
  File ".../g1_sim_rl_combo.py", line 765, in <module>
    main()
  File ".../g1_sim_rl_combo.py", line 709, in main
    ch = kb.get(0.1)
  File ".../g1_sim_rl_combo.py", line 650, in get
    r, _, _ = select.select([sys.stdin], [], [], timeout)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
```

注意几件事：

1. **策略已经 ready**——也就是说 `Policy(ONNX)` 加载、`ChannelFactoryInitialize`、`init_dds`、boot ramp、第一次 policy inference 全部都成功了。
2. 崩溃位置是**主线程的键盘读取**，不是控制线程的策略 / DDS。所以**绝对不是策略本身的问题**。
3. traceback 你只贴到 `select.select(...)` 那一行，**真正的异常类型 / 消息没贴**。请下次把 `Error: ...` 那一行也复制出来——那一行才告诉我具体是 `OSError: [Errno 9] Bad file descriptor`、`ValueError: I/O operation on closed file`、`KeyboardInterrupt` 还是别的。

下面按"最常见 → 较少见"列出可能原因，并给出**针对性修复**：

### 5.1 你按了 Ctrl-C，自己中断了（最常见）

`select.select` 在等待时如果收到 SIGINT，Python 会抛 `KeyboardInterrupt`。如果你在策略 ready 之后看到机器人姿态不对（比如腿在抖、要往前栽），下意识按 `Ctrl-C`，就会出现这个 traceback。

**判定**：traceback 倒数第一行写的是 `KeyboardInterrupt`。

**修复**：用脚本提供的 `x` 键退出（line 712），它会调用 `stop_and_settle` 软关 PD 后再退；不要直接 Ctrl-C 杀进程。如果非要支持 Ctrl-C 优雅退出，把 `kb.get` 包一层：

```python
def get(self, timeout: float = 0.1):
    try:
        r, _, _ = select.select([sys.stdin], [], [], timeout)
    except (KeyboardInterrupt, InterruptedError):
        return "\x03"   # 让上层把 \x03 当 quit 处理
    return sys.stdin.read(1) if r else None
```

并在 main 里：

```python
if ch in ("x", "\x03"):
    print("\n[combo] softening and exiting ...")
    break
```

（line 712 已经处理了 `\x03`，只是被 traceback 路径绕过去了。）

### 5.2 终端 / 父进程关闭了 stdin（次常见）

如果你用 `nohup`、`&` 后台运行、或者从 IDE 里用一个不接 TTY 的 shell launcher 启动 `python g1_sim_rl_combo.py`，`sys.stdin` 不是真 TTY：

- `RawKeyReader.__enter__` 调用 `termios.tcgetattr(sys.stdin.fileno())`——非 TTY 会立刻 `termios.error`，但你的 traceback 是从 `kb.get(0.1)` 抛的，说明 enter 没出错；
- 在 WSL2 / Windows Terminal 下，**有时**第一次 select 没问题，但隔一段时间 stdin 描述符会失效，然后 select 抛 `OSError: [Errno 9] Bad file descriptor`。

**判定**：traceback 末行是 `OSError: [Errno 9] Bad file descriptor` 或 `ValueError: I/O operation on closed file.`。

**修复**：

- 老老实实从一个真正的 WSL2 shell 里直接跑这个脚本（不要从 VSCode 内置 terminal、不要用 nohup、不要 `&`）；
- 或者把 `RawKeyReader` 改成不依赖 `sys.stdin`，直接 `open("/dev/tty", "rb", buffering=0)` 拿一个独立的 TTY 文件句柄：

  ```python
  class RawKeyReader:
      def __enter__(self):
          self._tty = open("/dev/tty", "rb", buffering=0)
          self._fd = self._tty.fileno()
          self._old = termios.tcgetattr(self._fd)
          tty.setcbreak(self._fd)
          return self

      def __exit__(self, *exc):
          termios.tcsetattr(self._fd, termios.TCSADRAIN, self._old)
          self._tty.close()

      def get(self, timeout: float = 0.1):
          r, _, _ = select.select([self._tty], [], [], timeout)
          return self._tty.read(1).decode("latin-1") if r else None
  ```

  这样和 `sys.stdin` 解耦，不会因为父进程 / IDE 的 stdin 行为踩坑。

### 5.3 仿真器物理已经爆掉，DDS 异步回调改写了 stdin 状态？

你之前那条 `WARNING: Nan, Inf or huge value in QACC at DOF 5` 是仿真器在 t=19.7s 抛出的。如果你**先在终端 1 跑了一次 mujoco，机器人已经摔了 / 物理已经爆掉**，然后才在终端 2 起 combo——大概率：

- combo 还能拿到 `rt/lowstate`（哪怕是 NaN / 离谱值），boot ramp 也能跑完；
- 但是 `Policy(obs)` 一旦输入 NaN，输出也是 NaN；
- `q_target` 变 NaN 写回 `rt/lowcmd` → bridge 把 NaN 塞进 `mj_data.ctrl` → 仿真彻底失稳；
- 这种情况下脚本本身**不会**在 `select.select` 报错，但仿真窗口会冻死。

**判定**：用 `top` 看 mujoco 的 CPU 占用是否飙到 100% 卡住；切到 viewer 看机器人是不是飘到很远的地方 / 关节角全是 NaN（visualizer 会显示成黑色三角片穿模）。

**修复**：

```bash
# 终端 1：完全关掉仿真
Ctrl-C   # 杀掉 unitree_mujoco.py
# 或者：先在 viewer 里按 R（大写）reset 物理状态

# 然后重新起
python unitree_mujoco.py
# viewer 里按 8 几次（safety net），别按 9

# 终端 2 再起 combo
python g1_sim_rl_combo.py
```

### 5.4 `tty.setcbreak` 失败 → 进入 main loop 时 stdin 已经被设为非阻塞但读不到

更罕见。如果 `__enter__` 里 `tcgetattr` / `setcbreak` 抛了异常但**被吞了**（你的代码里没吞，但有时候 IDE 会接管），后续 select 会立刻返回但 read 永远 EOF。

**判定**：select 不报错，但 main loop 飞速空转 / `kb.get` 总是 `None`。这不是你看到的现象，所以可以排除。

### 5.5 行动清单

按下面顺序排查：

1. **复制完整的 traceback**——把 `^^^^^^^^^^^^^` 后面那行（`Error: ...` 那行）也贴出来，这是关键证据；
2. 确认你是从一个**真正的 WSL2 bash shell**（不是 VSCode 内置 terminal、不是 tmux 嵌套层）启动的；
3. 确认终端 1 的 mujoco 是**新启动的、物理没爆**（viewer 里机器人姿态正常）；
4. 终端 2 启动 combo 后，等到 `[combo] policy ready` 打印，**先不要按任何键**，等 5 秒看会不会自己崩——
   - 自己崩 → 大概率 5.2（stdin 异常），按 5.2 改 `RawKeyReader` 用 `/dev/tty`；
   - 不崩 → 你之前是在策略 ready 之后按了某个键 / Ctrl-C 才挂的，按 5.1 处理。

---

## 6. 为什么"静态 demo 在悬挂带下能跑、却在地面 NaN"是同一个根因

最后回到你最初的疑问，把因果链合并写一遍：

```
[启动 unitree_mujoco.py] ── 默认 ENABLE_ELASTIC_BAND=True、length=0
        │
        │  (悬挂带把 torso_link 牢牢吊在初始位置，弹簧 stiffness ~200 N/m)
        ▼
[启动 g1_sim_keyboard.py] ── 500 Hz 给 29 关节发 PD 位置目标，没读 IMU
        │
        ├── 你按 w / e / s 等 → 上半身小幅动作，悬挂带 + 高 Kp 锁住，看上去能站
        │
        ├── 你按 8 几次 → 绳子变长，但 enable=True，扶手还在
        │
        ├── 你按 c / v 等大幅度下半身动作 → 重心移动 > 扶手能拉回的量 → 摔
        │
        └── 你按 9 → enable=False → 扶手消失 → 失去全部平衡能力 → 几秒内摔倒
                │
                ▼
        [机器人头 / 肩 / 手腕和地面碰撞]
                │
                │  (足底 / 头部 / 手腕几何与地面 mesh 接触穿模、雅可比奇异)
                ▼
        [MuJoCo 求解 QACC 时数值爆炸]
                │
                ▼
        WARNING: Nan, Inf or huge value in QACC at DOF 5.
        The simulation is unstable. Time = 19.6950.
```

要打破这条链，**只有一个办法**：在按 9 之前 / 同时，让一个**真正的闭环平衡控制器**接管 `rt/lowcmd`。这个控制器你已经有了——`g1_sim_rl_walk.py` 或 `g1_sim_rl_combo.py`。

---

## 7. 一句话回答你的两个问题

| 问题 | 回答 |
|---|---|
| 静态 demo 不需要闭环平衡也能在地面"站着接收键盘命令"吗？ | **不能。** 没有闭环平衡的开环 PD 双足必摔，按 `9` 几秒内 NaN。你的理解完全正确。 |
| 是否需要给静态 demo 加平衡策略？ | **不要加在静态 demo 上。** 直接用 `g1_sim_rl_combo.py`——它用 RL 策略管腿和腰，键盘只 overlay 手臂。这就是为这个场景设计的 demo。 |
| `g1_sim_rl_combo.py` 启动崩溃？ | 崩在 `select.select(stdin)`，和策略无关。最可能是你按了 Ctrl-C，或 stdin 不是真 TTY（VSCode terminal / nohup / 后台）。请贴**完整 traceback** 的最后一行（`Error: ...`），按 §5 的清单排查。 |
