# g1_brain QA2: 启动序列澄清 —— estop_listener 究竟是不是被集成进了 agent_main？

> 问题（2026-05-06）：
> 我之前启动都是先 mujoco，然后再 teleimager，然后启动
> `python -m g1_brain.safety.estop_listener`，最后启动
> `python -m g1_brain.apps.agent_main --mode confirm`。请详细解释我现在
> 是不是只需要启动 mujoco 和最后一步即可？中间的 estop 是不是已经被
> 插入 agent_main 了？

## TL;DR

**没有**。estop_listener 没有被合并进 agent_main，它现在仍然是一个独立
进程。agent_main 里只装了 estop 的"**读者**"（`EstopClient`），它检查
共享标志文件 `/tmp/g1_brain_estop`。真正能够把那个文件**写出来**
（按 ESC → 触发停机）以及**通过 DDS 直接发零扭矩 LowCmd 把控制器
压下去**的代码，都还在 `estop_listener.py` 里。所以您的最小启动序列是：

| 终端 | 进程 | 必需性 | 不开会怎样？ |
|---|---|---|---|
| 1 | `unitree_mujoco.py` | **必需** | agent 等不到 `/rt/lowstate`，10 s 超时后退回 `--no-skills`（看不到机器人，所有动作工具都会失败） |
| 2 | `teleimager image_server` | **可选** | 用户视角的 USB 摄像头不工作；pose 检测和 `describe_scene` 中的"用户在挥手"信息丢失；不阻挡运动 |
| 3 | `estop_listener` | **可选（强烈建议保留）** | 失去 ESC 紧急按钮；失去零扭矩硬停；软安全（FSM、watchdog、supervisor）仍然有效 |
| 4 | `agent_main --mode confirm` | **必需** | 主程序本身 |

下面是**为什么**。

---

## 1. estop 在代码里是怎么分工的？

整个 e-stop 子系统由三个文件构成，每个文件职责非常清楚：

### 1.1 `g1_brain/safety/estop_client.py` —— 标志文件的薄封装（**读+写**）

```python
class EstopClient:
    def is_engaged(self) -> bool: ...   # flag_path.exists()
    def reason(self) -> Optional[str]:  # 读文件内容
    def engage(self, reason): ...       # 写文件
    def release(self): ...              # 删文件
```

这只是对一个普通文件 `/tmp/g1_brain_estop` 的薄封装。"engaged" 的语义
就是"这个文件存在"。多个 reader 和 writer 共享同一条路径
（来自 `cfg.safety.estop.flag_path`）。

### 1.2 `g1_brain/safety/estop_listener.py` —— 独立的"按钮+硬停"进程

这是 Terminal 3 跑的那个 `python -m g1_brain.safety.estop_listener`。
它做三件事：

1. 用 `pynput.keyboard.Listener` 在系统全局键盘上监听 **ESC 键**
   （`estop_listener.py` 第 161-180 行）
2. ESC 按下时调用 `EstopClient.engage("keyboard:ESC")` 把标志文件写出来
3. **更重要的**：还会在 `rt/lowcmd` 上**直接发 30 帧零扭矩 LowCmd**
   （第 130-156 行，`_publish_zero_torque`），这些帧 `kp=0, kd=0, tau=0,
   q=当前 q`，相当于直接把控制器的输出在 DDS 层覆盖掉。

```python
def engage(self, reason: str) -> None:
    ...
    self.client.engage(reason)            # 1. 写文件
    ...
    for i in range(self.zero_torque_count):  # 2. 发零扭矩
        self._publish_zero_torque(n_motors)
        time.sleep(0.005)
```

**这一步是"硬停"**：不依赖 agent_main 的 supervisor 是否在跑、policy
是否还在循环 —— 就是直接抢占 `rt/lowcmd` topic。`unitree_mujoco`
看到一系列 `kp=kd=tau=0` 的 LowCmd 就会让电机自由（瘫倒），不再被任何
PD 拉住。

> 注意：`estop_listener` 用的是 **pynput** 监听全局键盘事件，不是
> `agent_main` 里那个普通的 stdin readline。也就是说 ESC 是"无论焦点
> 在哪个窗口都生效"的全局快捷键，这是它必须独立成一个进程的原因
> 之一。

### 1.3 `g1_brain/apps/agent_main.py` —— 只构造一个"读者"

`agent_main.py` 第 852-862 行：

```python
from ..safety.estop_client import EstopClient

estop_path = cfg.get("safety", {}).get("estop", {}).get(
    "flag_path", "/tmp/g1_brain_estop")
estop = EstopClient(estop_path)            # ← 只是 reader
if estop.is_engaged():
    log.warning("E-stop is already engaged at startup: %s", estop.reason())
    try:
        fsm.transition(RobotFsmState.EMERGENCY_STOP, "estop engaged at boot")
    except Exception:
        pass
```

随后这个 `estop` 对象被注入 `SafetySupervisor`：

```python
safety = SafetySupervisor(
    cfg=cfg, scene_bus=scene_bus, robot_bus=robot_bus,
    fsm=fsm, estop=estop,           # ← 传给 supervisor
    run_mode=run_mode, ...)
```

而 `supervisor.py` 第 294-299 行在每次 `validate(tool, args)` 时检查：

```python
if self.estop.is_engaged():
    reason = self.estop.reason() or "engaged"
    ...
    return False, f"estop engaged: {reason}", {}
```

**关键点**：agent_main 里**没有**任何 `pynput` 导入、没有任何
`on_press` 回调、没有任何往 `rt/lowcmd` 发零扭矩的代码。在 agent_main
的进程里：

```bash
$ grep -n "pynput\|on_press" g1_brain/apps/agent_main.py
$ # 0 hits
```

```bash
$ grep -rn "pynput" g1_brain/
g1_brain/safety/estop_listener.py:163:  from pynput import keyboard
g1_brain/safety/estop_listener.py:165:  _stderr("[estop] FATAL: pynput not installed
```

只有 `estop_listener.py` 用 pynput。

---

## 2. 那么如果我不开 estop_listener，我会失去什么？

精确清单：

### 失去：

1. **ESC 紧急按钮**。任何窗口里按 ESC 都不会触发停机；
   终端 4 里键入 ESC 也只是个普通键码进入 stdin，被 supervisor 的
   `_confirm_in_terminal` 当成"非 y"处理，仅相当于拒绝当前那一次 motion call。
2. **DDS 层硬停（零扭矩 LowCmd）**。即使有什么外部代码把
   `/tmp/g1_brain_estop` 给 `touch` 出来了，agent_main 这边也只能让
   supervisor **从下次 motion call 开始拒绝**。但是
   `ComboController` 仍然会以原本的 PD（甚至带 1.4× 的 stand-Kp boost）
   持续往 `rt/lowcmd` 发命令，机器人不会自由瘫倒 —— **engage 是软停，
   不是硬停**。

### 仍然保留：

- **SafetySupervisor 的全部规则**：还会逐条检查 walk 速度上限、scene
  距离、pose、watchdog、FSM 状态、estop（reads file）。所有 LLM 发
  起的 motion call 仍然要走这一道关。
- **WatchdogManager**：lowstate 老化、head_frame 老化、pose tilt 这些
  watchdog 跑得跟原来一样。watchdog 不会去 *engage estop* —— 它走
  的是 FSM `ENGAGED -> EMERGENCY_STOP` 这条路（`watchdogs.py` 第
  223-232 行），并通过 `combo.set_safe_hold(True)` 让 ComboController
  把当前姿势锁住（safe-hold），但 **不写 estop 标志文件**。
- **`run_mode: confirm` 的 y/N 终端确认**。每次 motion call 都仍然
  会在 Terminal 4 弹 `[g1_brain confirm] execute walk(...) ? [y/N]`，
  这与 estop 是两套独立机制。

> 用一句话概括：watchdog 跟 estop 在这套设计里**走两条不同的路**。
> watchdog 让 FSM 进 `EMERGENCY_STOP` + safe-hold（仍然有 PD 把
> 关节锁住，机器人站着不动），estop 让 SafetySupervisor 把所有
> motion call 挡掉 + listener 把 lowcmd 直接归零（机器人瘫掉）。
> 它们的目的不一样，估计您也不想 watchdog 一跳就让机器人瘫地上。

---

## 3. 那 teleimager 呢？我可以跳过吗？

**可以跳过，但要看您是否在意这两件事**：

### 3.1 teleimager 服务的是哪一台摄像头？

按照 `configs/g1_brain.yaml`：

```yaml
cameras:
  usb:                       # ← 这是 teleimager 服务的摄像头
    enabled: true
    source: "teleimager"     # 或者 "cv2"
    teleimager_host: "127.0.0.1"
    teleimager_request_port: 60000
  head:                      # ← 这一台是 MuJoCo 合成的，跟 teleimager 无关
    enabled: true
```

YAML 注释直接说清了：

> **head**: 机器人自己第一人称视角的摄像头 —— 由 MuJoCo 在
> `torso_link` 上合成出来，是 robot 自己"看到"的。**这是必须的，
> 否则 describe_scene、ground constraint、head-stream YOLO 都没数据。**
>
> **usb**: 一台单独的摄像头（默认是笔记本的网络摄像头）对着用户。
> 它喂给 MediaPipe 做 pose 检测，所以感知层能识别用户挥手 / T-pose
> 等手势，进而触发 mock_imitate（"用户挥手 → 机器人也挥手"演示）。
> **它是可选的**。设 `enabled: false` 也完全可以 —— 手势、走路、
> describe_scene 都不依赖它。失去 USB 流只会产生一条信息性警告，
> 永远不会阻挡运动。

### 3.2 teleimager 跳过后的几种走法

**走法 A —— 把 USB 摄像头关了**（最干净）

```yaml
cameras:
  usb:
    enabled: false
```

启动序列就变成 mujoco + estop_listener + agent_main 三件套
（如果连 estop_listener 也不要就两件）。

**走法 B —— 让 UsbCamera 自己开 /dev/video0**

```yaml
cameras:
  usb:
    enabled: true
    source: "cv2"          # ← 改这里
```

`UsbCamera` 会直接 `cv2.VideoCapture(0)` 而不去找 teleimager。
**但要小心**：teleimager 和 cv2 都抢同一个 `/dev/video0`，**不能
同时开**。WSL2 上还要先把 webcam 通过 `usbipd-win` 挂到 WSL，否则
`/dev/video0` 不存在。

**走法 C —— 保留 teleimager**

跟您原本的启动序列一样。**如果您还希望机器人能感知到您（比如
说"the user is waving"被 LLM 用作上下文），保留 teleimager 是
最方便的方式**。

### 3.3 那 mock_imitation（人挥手机器人也挥手）跟这个有关吗？

当前 `g1_brain.yaml` 第 162-176 行已经写明：

```yaml
mock_imitation:
  enabled: false      # 用户明确要求关闭
```

也就是说现在跑起来 USB 摄像头**只是给 LLM 提供 "用户姿态" 的描述
信息**，不会真的让机器人模仿。所以即便您关 teleimager / 关 USB 摄像头，
功能损失只是 LLM 不知道您在挥手 —— 不影响走路、不影响手势、不影响
describe_scene 中关于环境的描述。

---

## 4. 综合：您这次实际可以怎么启动？

### 4.1 最小化（不安全 —— 只是为了开发演示）

```bash
# Terminal 1
conda activate unitree && export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# Terminal 2
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

前提：要么 USB 摄像头关了 (`cameras.usb.enabled: false`)，
要么把 `source` 改成 `cv2`，要么接受启动后日志里持续打印
"teleimager 取不到图" 的警告。

**风险**：没有 ESC 紧急按钮，没有零扭矩硬停。如果机器人
在 sim 里出了非预期行为（开始转圈走、撞墙、policy 抽风），
您只能：
- 在 Terminal 4 拒绝下一次 confirm 提示（但当前已经在跑的
  动作不会立即停 —— 比如 `walk(duration_s=1.0)` 已经发出去
  就要跑完 1 秒）
- 或者 Ctrl-C agent_main（它会触发 `combo.stop_and_settle()` 走
  正常退出流程，但需要约 5 秒把 Kp 缓降到 0）
- 或者 Ctrl-C MuJoCo（直接关物理仿真）

### 4.2 推荐（保留 estop_listener）

```bash
# Terminal 1 — 同上 mujoco
# Terminal 2 — agi 环境
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
# Terminal 3 — agent
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
export OPENAI_API_KEY=sk-...
python -m g1_brain.apps.agent_main --mode confirm
```

把 USB 摄像头关掉或者改 `cv2` source 之后，**这套三终端
组合是当前 g1_brain 仿真链路里安全且最少的搭配**。

### 4.3 完整（您原本的 4 终端）

加回 teleimager 即可。**优点**：LLM 能感知到您（pose detection
喂入），将来某天打开 mock_imitation 也是直接生效。

---

## 5. 结论：直接回答您的问题

> "我是不是现在只需要启动 mujoco 和最后一步即可，中间的 estop 已经
> 被插入 agent_main 了吗？"

- **estop 没有被插入 agent_main**。agent_main 里只有 EstopClient（读者
  + 标志文件检查），**没有键盘监听器，也没有零扭矩 LowCmd 发布器**。
  ESC 键只在 estop_listener 进程里被监听。
- **不开 estop_listener** 您的程序仍然能跑、SafetySupervisor 仍然
  在 gate motion，但失去 (1) ESC 紧急按钮 (2) DDS 层硬停。这是软安全
  对硬停的取舍 —— 风险您自己评估，仿真环境下风险有限，真机上千万
  不要跳过。
- **不开 teleimager** 是相对安全的选择，前提是把 `cameras.usb.enabled`
  设成 `false`，或者把 `source` 改成 `cv2`。失去的只是 USB 摄像头通道
  下的 pose 检测，不影响 head 摄像头、不影响走路 / 手势 / describe_scene。
- **mujoco 必须开**。没有 `/rt/lowstate` 流入 ComboController，agent_main
  会等待 10 秒后超时回退到 `--no-skills` —— 整个动作链路都不可用。

如果您只是想先跑通 LLM + 视觉 + describe_scene 而不操心运动，请
用 `--vision-only` 启动 agent_main。这种模式下 mujoco 都可以不开
（DDS 整体都不初始化）：

```bash
python -m g1_brain.apps.agent_main --mode confirm --vision-only
```

---

## 附：how_to_run.md 已经声明过的一段话

仓库里 `docs/how_to_run.md` 第 126-127 行就已经写明了这件事，
节录如下：

> 您可以省掉 Terminal 3（estop_listener），如果只想要 soft safety
> （supervisor 仍然 gate 一切；只是失去那个 panic-button 出口）。

这跟本文档结论一致 —— 只是把 estop 内部的两个角色（reader vs.
listener+硬停）讲透，避免误以为它们是同一个东西。
