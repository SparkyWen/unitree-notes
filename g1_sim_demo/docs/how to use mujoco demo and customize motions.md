# Unitree MuJoCo 仿真 — 深入解析与实时操控指南

本文档对应 `unitree_mujoco/simulate_python/` 这一套基于 Python 的仿真器，目标是让你彻底搞清楚:

1. `python unitree_mujoco.py` 启动后到底在跑什么；
2. 为什么 G1 机器人启动时悬浮在空中，按 `9` 之后又会摔下来；
3. 「demo」 这个概念到底是什么，是不是只能写成"一段动作"；
4. 如何自己写完整的 demo（含模板）；
5. 如何做**实时**键盘 / 鼠标 / 网络指令操控（多种实现方案）。

文中所有代码引用都给到 `文件:行号`，方便对照源码阅读。

---

## 0. 一张图说清楚整个架构

```
 ┌─────────────────────────────────────────────────────────────┐
 │ 进程 A:   python unitree_mujoco.py                          │
 │                                                             │
 │  ┌──────────────┐   读 sensordata     ┌─────────────────┐   │
 │  │ MuJoCo 物理  │ ────────────────►   │ UnitreeSdk2     │   │
 │  │ mj_step 仿真 │                    │ Bridge (DDS发布) │   │
 │  │ 渲染 viewer  │ ◄─────────────────  │                 │   │
 │  └──────────────┘   写 mj_data.ctrl  └─────────────────┘   │
 │         │                                       │           │
 │         │ ElasticBand (按 7/8/9 控制)            │           │
 └─────────┼───────────────────────────────────────┼───────────┘
           │              DDS over loopback ("lo", domain_id=1)
 ┌─────────▼───────────────────────────────────────▼───────────┐
 │                                                             │
 │ rt/lowstate (机器人状态)        rt/lowcmd (电机指令)         │
 │ rt/sportmodestate (高层位姿)    rt/wirelesscontroller       │
 │                                                             │
 └─────────┬───────────────────────────────────────┬───────────┘
           │                                       │
 ┌─────────▼─────────────────┐   ┌─────────────────▼───────────┐
 │ 进程 B:                   │   │ 进程 B':                    │
 │ 你的 demo / 控制器        │   │ stand_go2.py / 你的实时操控 │
 │ (订阅 lowstate, 发 lowcmd)│   │                             │
 └───────────────────────────┘   └─────────────────────────────┘
```

**关键点**: `unitree_mujoco.py` 自身 **不控制机器人**, 它只是一个"仿真服务器"——把 MuJoCo 里的传感器读数当作机器人状态发到 DDS 上; 同时订阅 DDS 上的 `lowcmd` 把电机命令写回 MuJoCo。

所以"机器人不动"是正常的, 因为没有 demo 进程去发 `lowcmd`。要让它动, 你必须**另开一个进程**, 通过 DDS 给它发指令。

---

## 1. `python unitree_mujoco.py` 究竟在做什么

### 1.1 启动入口

`unitree_mujoco/simulate_python/unitree_mujoco.py:78-83`:

```python
if __name__ == "__main__":
    viewer_thread = Thread(target=PhysicsViewerThread)
    sim_thread = Thread(target=SimulationThread)
    viewer_thread.start()
    sim_thread.start()
```

启动后总共跑了 **5 个并发循环**:

| # | 来源 | 频率 | 干什么 |
|---|------|------|--------|
| 1 | `SimulationThread` (`unitree_mujoco.py:38`) | 200 Hz (`SIMULATE_DT=0.005`) | 调 `mujoco.mj_step()` 推进物理 |
| 2 | `PhysicsViewerThread` (`unitree_mujoco.py:70`) | 50 Hz (`VIEWER_DT=0.02`) | 调 `viewer.sync()` 刷新画面 |
| 3 | `lowStateThread` (`unitree_sdk2py_bridge.py:63`) | 200 Hz | 把传感器读数打成 `LowState_` 发到 `rt/lowstate` |
| 4 | `HighStateThread` (`unitree_sdk2py_bridge.py:71`) | 200 Hz | 把==基座位姿打成 `SportModeState_` 发到 `rt/sportmodestate`== |
| 5 | `WirelessControllerThread` (`unitree_sdk2py_bridge.py:81`) | 100 Hz | 把手柄按键发到 `rt/wirelesscontroller` |

接收一侧只有 1 个回调:

- `LowCmdHandler` (`unitree_sdk2py_bridge.py:111`) — 一旦有人在 `rt/lowcmd` 上发指令, 立刻把 `tau + kp*(q_des-q) + kd*(dq_des-dq)` 算出来写到 `mj_data.ctrl[i]`。这就是 PD + 前馈力矩的低层控制接口, 跟真机一模一样。

### 1.2 配置文件

`unitree_mujoco/simulate_python/config.py`:

```python
ROBOT = "g1"                                     # 选机型
ROBOT_SCENE = "../unitree_robots/g1/scene.xml"   # MJCF 场景文件
DOMAIN_ID = 1                                    # DDS 域 (避开真机的 0)
INTERFACE = "lo"                                 # 走本地回环
ENABLE_ELASTIC_BAND = True                       # 关键!  G1 默认开启虚拟吊带
```

注意 `config.py:11` 的 `ENABLE_ELASTIC_BAND = True` —— 这就是机器人悬空的元凶。

### 1.3 PD 控制接口的语义

`unitree_sdk2py_bridge.py:111-123`:

```python
def LowCmdHandler(self, msg: LowCmd_):
    for i in range(self.num_motor):
        self.mj_data.ctrl[i] = (
            msg.motor_cmd[i].tau
            + msg.motor_cmd[i].kp * (msg.motor_cmd[i].q  - sensordata[i])
            + msg.motor_cmd[i].kd * (msg.motor_cmd[i].dq - sensordata[i+num])
        )
```

这就告诉你**给机器人发指令的格式**: 每个电机需要 5 个量

- `q`: 目标关节角 (rad)
- `dq`: 目标角速度 (rad/s, 一般填 0)
- `kp`, `kd`: PD 增益, 决定刚度和阻尼
- `tau`: 前馈力矩 (Nm)

最终输出力矩 = `tau + kp*(q_des - q) + kd*(dq_des - dq)`。
**只想做位置控制**: 给一个合理的 `q`, kp/kd 设非零, dq=tau=0。
**纯力矩控制**: kp=kd=0, 直接给 tau。

---

## 2. 为什么机器人悬浮 / 为什么按 9 之后会摔下来

这是 `ElasticBand`（虚拟弹性吊带）做的, 专为人形机器人 H1/G1 设计, 因为人形不能直接放在地上自由站立 —— 没有控制器它会立刻倒下。

### 2.1 弹性吊带的物理模型

`unitree_sdk2py_bridge.py:399-419`:

```python
class ElasticBand:
    def __init__(self):
        self.stiffness = 200      # 弹簧刚度
        self.damping = 100        # 阻尼
        self.point = np.array([0, 0, 3])   # 吊带挂在世界坐标 (0,0,3) 这个点
        self.length = 0           # 吊绳的"自然长度"
        self.enable = True

    def Advance(self, x, dx):
        δx = self.point - x       # 当前位置到挂点的向量
        distance = np.linalg.norm(δx)
        direction = δx / distance
        v = np.dot(dx, direction)
        f = (self.stiffness * (distance - self.length)
             - self.damping * v) * direction
        return f                  # 这个力被外加到 torso_link 上
```

`unitree_mujoco.py:54-58` 把这个力施加到 `xfrc_applied`:

```python
if elastic_band.enable:
    mj_data.xfrc_applied[band_attached_link, :3] = elastic_band.Advance(
        mj_data.qpos[:3], mj_data.qvel[:3]
    )
```

`band_attached_link` 对 G1 / H1 是 `torso_link`, 对四足是 `base_link` (`unitree_mujoco.py:21-24`)。

物理含义: 一根挂在 `(0, 0, 3)`（世界坐标 3 米高）上、刚度 200 N/m、阻尼 100 N·s/m、自然长度 `length` 的弹簧, 拉着躯干。当机器人离挂点远于 `length` 时, 弹簧把它拉回; 阻尼项消耗速度。

### 2.2 键盘按键

`unitree_sdk2py_bridge.py:421-428`:

```python
def MujuocoKeyCallback(self, key):
    glfw = mujoco.glfw.glfw
    if key == glfw.KEY_7: self.length -= 0.1   # 拉短吊绳 → 机器人被拽高
    if key == glfw.KEY_8: self.length += 0.1   # 放长吊绳 → 机器人下沉
    if key == glfw.KEY_9: self.enable = not self.enable  # 总开关
```

- **`9`**: 一按 `enable=False`, 弹簧消失 → 重力把机器人摔下来。再按一次开回来, 但此时机器人姿态可能已经躺平。
- **`7` / `8`**: 调吊绳长度, 实现"放下来 / 提起来"。

只有 `unitree_mujoco.py:19` 的 `if config.ENABLE_ELASTIC_BAND:` 分支 才会注册 `key_callback`, 所以这三个键只在弹性带启用时有效。

### 2.3 正确的"放机器人下来站立"流程

按 README (`unitree_mujoco/readme.md:234`) 描述, 标准做法是:

1. 启动 `unitree_mujoco.py` (G1 默认开吊带, 悬空 3 米)
2. **先在另一个终端启动控制器** (例如 `g1_low_level_example.py`), 它会以 PD 模式锁住所有关节到一个稳定姿态
3. 多次按 `8` 慢慢放下机器人, 让脚先着地
4. 按 `9` 释放吊带, 此时控制器已经在维持站姿, 机器人能稳定站住

**你只按 9 会摔下来, 是因为没有任何控制器在维持姿态** —— 没人给电机发 `kp/kd`, 所有关节都在自由摆动, 加上没有平衡控制器, 必倒。

如果想暂时关掉弹性带做调试, 改 `config.py:11` 的 `ENABLE_ELASTIC_BAND = False`。但 G1 这样直接放地上也会立刻趴。

---

## 3. "Demo" 这个概念到底是什么

源码中没有"demo" 这个抽象。所谓 demo 就是**任何一个连接到同一个 DDS 域、订阅 `rt/lowstate` 并往 `rt/lowcmd` 发指令的进程**。

参考 `unitree_mujoco/example/python/stand_go2.py` 和 `unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py`, 它们的统一结构是:

```
1. ChannelFactoryInitialize(domain_id, interface)   # 接入 DDS
2. 创建 ChannelPublisher("rt/lowcmd", LowCmd_)
3. 创建 ChannelSubscriber("rt/lowstate", LowState_)  # 可选, 但要做闭环必备
4. 在一个高频(2~5 ms)循环里:
       根据当前状态 + 时间 + 输入 → 计算 (q, dq, kp, kd, tau)
       打包成 LowCmd_ 写出
```

### 3.1 一个 demo 能不能包含多段动作

**当然能**, 而且 G1 的官方 demo 就是这么做的。看 `g1_low_level_example.py:130-184`:

```python
def LowCmdWrite(self):
    self.time_ += self.control_dt_

    if self.time_ < self.duration_:
        # [Stage 1]: 慢慢回零位
        ratio = np.clip(self.time_ / self.duration_, 0.0, 1.0)
        ...
    elif self.time_ < self.duration_ * 2:
        # [Stage 2]: 用 PR 模式摆脚踝
        L_P_des = max_P * np.sin(2.0 * np.pi * t)
        ...
    else:
        # [Stage 3]: 切到 AB 模式继续摆 + 摆腕
        ...
```

这就是一个 demo 包含 **3 段不同动作** 的例子。区分阶段的方式可以是:
- **时间分段** (像上面这样)
- **状态机** (用一个 `self.state` 枚举, 在按键 / 收到目标点等事件时切换)
- **任务队列** (列表里塞一系列目标关节角, 每个跑完切下一个)
- **轨迹回放** (从文件读时间序列动作)
- **强化学习策略** (每一步把 obs 输给神经网络拿动作)

只要你愿意, 一个进程里可以无穷多个阶段。

### 3.2 写自己的 demo: G1 模板

下面是一个**完整可运行**的 G1 demo 骨架, 复制改改就能用。

```python
# my_g1_demo.py — 在仿真器旁边另开一个终端运行
import sys, time, numpy as np
from unitree_sdk2py.core.channel import (
    ChannelFactoryInitialize, ChannelPublisher, ChannelSubscriber,
)
from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
from unitree_sdk2py.utils.crc import CRC
from unitree_sdk2py.utils.thread import RecurrentThread

G1_NUM_MOTOR = 29

# G1 关节索引 (摘自 g1_joint_index_dds.md)
class J:
    LeftHipPitch=0;  LeftHipRoll=1;  LeftHipYaw=2;  LeftKnee=3
    LeftAnklePitch=4; LeftAnkleRoll=5
    RightHipPitch=6; RightHipRoll=7; RightHipYaw=8; RightKnee=9
    RightAnklePitch=10; RightAnkleRoll=11
    WaistYaw=12; WaistRoll=13; WaistPitch=14
    LeftShoulderPitch=15; LeftShoulderRoll=16; LeftShoulderYaw=17; LeftElbow=18
    LeftWristRoll=19; LeftWristPitch=20; LeftWristYaw=21
    RightShoulderPitch=22; RightShoulderRoll=23; RightShoulderYaw=24; RightElbow=25
    RightWristRoll=26; RightWristPitch=27; RightWristYaw=28

# 与官方 g1_low_level_example.py 一致的 PD 增益
Kp = [60,60,60,100,40,40, 60,60,60,100,40,40, 60,40,40,
      40,40,40,40,40,40,40, 40,40,40,40,40,40,40]
Kd = [1,1,1,2,1,1, 1,1,1,2,1,1, 1,1,1,
      1,1,1,1,1,1,1, 1,1,1,1,1,1,1]

class Demo:
    def __init__(self):
        self.dt = 0.002
        self.t = 0.0
        self.cmd = unitree_hg_msg_dds__LowCmd_()
        self.state = None
        self.mode_machine = 0
        self.mode_synced = False
        self.crc = CRC()

    def init(self):
        # 仿真情况下不需要 MotionSwitcher; 真机必须先关运动控制服务
        self.pub = ChannelPublisher("rt/lowcmd", LowCmd_); self.pub.Init()
        self.sub = ChannelSubscriber("rt/lowstate", LowState_)
        self.sub.Init(self.on_state, 10)

    def on_state(self, msg: LowState_):
        self.state = msg
        if not self.mode_synced:
            self.mode_machine = msg.mode_machine
            self.mode_synced = True

    def start(self):
        while not self.mode_synced: time.sleep(0.1)
        RecurrentThread(interval=self.dt, target=self.tick, name="ctrl").Start()

    def tick(self):
        self.t += self.dt
        s = self.state
        if s is None: return

        self.cmd.mode_pr = 0
        self.cmd.mode_machine = self.mode_machine

        # ===== 这里随便写你的动作逻辑 =====
        # 阶段一 (0~3s): 当前姿态 → 全零位
        if self.t < 3.0:
            r = self.t / 3.0
            for i in range(G1_NUM_MOTOR):
                self.cmd.motor_cmd[i].mode = 1
                self.cmd.motor_cmd[i].q  = (1-r) * s.motor_state[i].q
                self.cmd.motor_cmd[i].dq = 0.0
                self.cmd.motor_cmd[i].kp = Kp[i]
                self.cmd.motor_cmd[i].kd = Kd[i]
                self.cmd.motor_cmd[i].tau = 0.0
        # 阶段二 (3s~): 双臂正弦挥手
        else:
            t = self.t - 3.0
            wave = 0.6 * np.sin(2 * np.pi * 0.5 * t)
            self.cmd.motor_cmd[J.LeftShoulderPitch ].q = -wave
            self.cmd.motor_cmd[J.RightShoulderPitch].q = -wave
            self.cmd.motor_cmd[J.LeftElbow ].q = 1.0
            self.cmd.motor_cmd[J.RightElbow].q = 1.0
        # =================================

        self.cmd.crc = self.crc.Crc(self.cmd)
        self.pub.Write(self.cmd)

if __name__ == "__main__":
    # 仿真器: domain=1, "lo"; 真机: 默认 domain=0 + 网卡名
    if len(sys.argv) > 1:
        ChannelFactoryInitialize(0, sys.argv[1])
    else:
        ChannelFactoryInitialize(1, "lo")
    d = Demo(); d.init(); d.start()
    while True: time.sleep(1)
```

运行步骤:

```bash
# 终端 1: 起仿真
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# (悬空 → 按 8 几次放下来 → 启动控制器后按 9 切吊带)

# 终端 2: 跑 demo
python my_g1_demo.py
```

**为什么要先发指令再放吊带?** 因为 `kp/kd` 参数让电机进入位置保持模式, 关节不会乱晃。否则一松吊带四肢就软掉。

---

## 4. 实时操控: 让你"边跑边控制"机器人

这是你提的核心问题。"实时操控"可以分成几种实现思路, 按复杂度从低到高排:

### 方案 A: 用手柄模拟无线遥控器 (内建支持)

仿真器 **已经内置**这个能力。`config.py` 里把 `USE_JOYSTICK = 1` 打开 + 接 Xbox/Switch 手柄, 它会:

1. `unitree_sdk2py_bridge.py:295-352` 调 pygame 初始化手柄
2. 每 10 ms 把按键 / 摇杆值打成 `WirelessController_` 发到 `rt/wirelesscontroller`
3. 你的 demo 进程**订阅** `rt/wirelesscontroller`, 用摇杆值当输入

骨架:

```python
from unitree_sdk2py.idl.unitree_go.msg.dds_ import WirelessController_

def on_joy(msg):
    # msg.lx, msg.ly, msg.rx, msg.ry ∈ [-1, 1]; msg.keys 是按键位掩码
    target_yaw_rate = msg.rx * 1.5       # 摇杆右 → 转身
    target_x_vel    = msg.ly * 0.8       # 摇杆前 → 前进
    ...

ChannelSubscriber("rt/wirelesscontroller", WirelessController_).Init(on_joy, 10)
```

适合: 想用手柄遥控, 跟真机操作流程一致。

### 方案 B: 在 demo 进程里读键盘(`pygame` / `pynput`)

你不需要任何特殊接口, 只是普通的 Python 进程, 想读什么输入都行。和方案 A 唯一的区别是输入设备来自键盘而不是手柄。

```python
import threading
import pygame  # 或 from pynput import keyboard

target = {"shoulder": 0.0, "elbow": 1.0}

def keyboard_thread():
    pygame.init(); pygame.display.set_mode((100,100))
    while True:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_w: target["shoulder"] -= 0.1
                if ev.key == pygame.K_s: target["shoulder"] += 0.1
                if ev.key == pygame.K_a: target["elbow"]    -= 0.1
                if ev.key == pygame.K_d: target["elbow"]    += 0.1

threading.Thread(target=keyboard_thread, daemon=True).start()

# 在控制循环里读 target["..."] 当目标关节角即可
```

注: 不能直接复用仿真器自身的 `viewer.key_callback` —— 那是 MuJoCo viewer 进程的, 你要在自己的进程里搞独立窗口或后台键盘监听。

### 方案 C: HTTP / WebSocket / Socket 服务端

如果想从浏览器 / Electron 前端发指令 (跟你 `cs47-command-center/` 那一套很像), 在 demo 里多起一个 FastAPI / Flask 线程:

```python
from fastapi import FastAPI
import uvicorn, threading

app = FastAPI()
state = {"mode": "stand"}

@app.post("/cmd/{action}")
def set_action(action: str):
    state["mode"] = action
    return {"ok": True}

threading.Thread(
    target=lambda: uvicorn.run(app, host="127.0.0.1", port=8000, log_level="warning"),
    daemon=True,
).start()

# 控制循环里根据 state["mode"] 走不同分支
```

这正是 `cs47-command-center/services/robot-bridge/src/sim/mujoco_runner.py` 的设计: 一个后台线程跑 MuJoCo 仿真 + DDS 桥, 主线程跑 HTTP 服务, 前端 Electron 通过 REST/WS 下发指令, 桥里用 `LowCmdAdapter` 把高层意图翻成 PD 指令。

### 方案 D: 真正的"实时拖拽" — 直接读 viewer 鼠标交互

MuJoCo 自带的 passive viewer (`mujoco.viewer.launch_passive`) 默认就支持**右键拖拽给物体施力**。但当前 `simulate_python` 用 passive viewer 时, 只在弹性带模式注册了一个 `key_callback`, 没有挂鼠标回调。如果想让用户拖拽某个 link, 让其变成"目标位置", 你可以自己调 MuJoCo 接口:

```python
# 主循环中, 读 mj_data.xfrc_applied 是否被用户拖拽 (passive viewer 内置)
# 或者使用 mujoco.mj_applyFT 之类手工施力
```

这是高级玩法, 一般不推荐 —— 想要"拖动一个目标点, 机器人手去摸" 应该走逆运动学(IK), 而不是直接拖关节。

### 方案 E: 替换默认 viewer, 自己做一个集成键盘 / GUI 的仿真器入口

把 `unitree_mujoco.py` 复制成你自己的 `my_sim.py`, 在 `viewer = mujoco.viewer.launch_passive(...)` 时传入自定义的 `key_callback`, 维护一个全局 `desired_action` 字典, 然后在 `SimulationThread` 里把它打成 `LowCmd_` 直接调 `unitree.LowCmdHandler(cmd)` —— **跳过 DDS, 同进程直接控制**。

好处: 延迟最低, 没有 DDS 序列化开销。
坏处: 跟真机的部署模式不一样, 调试好的代码不能直接迁移到真机。

### 方案 F: 把意图发到 DDS 的自定义 topic

最架构化的方式: 在 demo 进程里做一个 `rt/intent` 主题, 发布"目标速度 / 目标姿态 / 目标动作名"; 跑一个 controller 进程订阅 `rt/intent` 同时输出 `rt/lowcmd`。这就是 ROS / 服务化机器人的常规做法, 把"高层意图"和"低层控制"拆开, 但对单人调试 demo 来说有点重。

### 方案选择建议

| 你想要 | 推荐方案 |
|--------|----------|
| 跟真机操作流程一致, 用手柄 | A |
| 简单的键盘控制 demo | B |
| 跟你 `cs47-command-center` 集成, 浏览器 / Electron 控 | C |
| 极致低延迟 / 不在乎跟真机一致 | E |
| 多模块, 长期项目 | F |

---

## 5. 控制策略层面的注意点

### 5.1 高频率, 短指令

控制循环必须 ≥ 200 Hz (`dt ≤ 0.005s`)。仿真器的物理也是 200 Hz, 命令到得太慢 PD 跟不上, 关节会抖。

### 5.2 PD 增益要分关节给

腿部 (尤其膝盖) 要 ≥ 100, 手腕可以 40, 见 `g1_low_level_example.py:18-32`。增益过低 → 不跟随; 过高 → 不稳定 / 发散。

### 5.3 指令必须**每帧重发**

DDS 是 fire-and-forget, 不会自己保持。如果你某帧没发, 那一帧 `mj_data.ctrl[i]` 上次值还在, 短时间没事, 但停止发布超过几十毫秒控制器就异常。

### 5.4 平滑过渡, 不要瞬移

切换阶段时一定要做插值, 别让 `q` 突变 0.5 rad —— PD 会瞬间产生几百牛顿米力矩, 仿真直接爆掉。模板里的 `(1-r)*current + r*target`、`tanh(t/τ)` 都是常用平滑。

### 5.5 23DOF vs 29DOF

`config.ROBOT="g1"` 默认指向 `scene.xml` → `g1_29dof.xml`。如果用 23DOF, 改 `config.py:2` 的 `ROBOT_SCENE` 指向 `scene_23dof.xml`, 同时 demo 里只控制 23 个关节的索引(腰部 13/14 和手腕 20/21/27/28 是无效的, 见 `g1_joint_index_dds.md:53-60`)。

### 5.6 G1 没有现成的 stand demo

`unitree_mujoco/example/python/` 只有 `stand_go2.py` (四足), 没给 G1 的站立 demo。要想让 G1 真的能放地上稳定站, 需要平衡控制 (起码是 ZMP 或质心反馈), 这超过本仿真器配套示例范围。简单的"假站立"做法是: 先开吊带, 控制器把所有关节锁到默认姿态(全 0), 然后**保持吊带不释放**, 你就有一个永远不倒的"展示模型"。要更真实, 看 `unitree_rl_mjlab/` 那一套 RL 训练出来的 policy。

---

## 6. 排错速查

| 现象 | 原因 | 解决 |
|------|------|------|
| 启动后机器人悬空在 3m 高度 | `ENABLE_ELASTIC_BAND=True` + `length=0` | 多按 `8` 把吊绳放长 |
| 按 `9` 后立刻摔倒 | 没有控制器维持姿态 | **先**起 demo 进程, **再**按 `9` |
| demo 跑了但机器人不动 | DDS 域 / 网口不匹配 | demo 必须 `ChannelFactoryInitialize(1, "lo")`, 跟 `config.py` 一致 |
| 关节抖动 / 发散 | kp 太大 / dt 太长 | 降 kp、提高发指令频率 |
| `mode_machine` 一直拿不到 | `LowState_` 还没收到 | 等 `lowstate_subscriber` 触发回调; G1 例子里靠 `update_mode_machine_` 阻塞 |
| 打印 `MotionSwitcher` 报错 | 仿真器没有这个服务 | 仿真模式下**注释掉** `MotionSwitcherClient` 那段(只在真机需要) |
| 只能控制 12 个关节 | 用错 IDL: 用了 `unitree_go` (四足 20 槽) 而不是 `unitree_hg` (G1 35 槽) | G1 必须 `from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_` |

---

## 7. 一句话总结

`unitree_mujoco.py` 只是个**仿真服务器**: 它把 MuJoCo 物理状态以真机一样的 DDS 协议暴露出来, 等待你的控制进程接入。机器人悬空是因为开启了吊带 (按 9 切换), 摔下来是因为没人在控制它。Demo 就是任意一个发 `rt/lowcmd` 的 Python 进程, 内部想要几段动作、想接键盘 / 手柄 / HTTP / WebSocket 都可以, 关键是控制循环至少 200 Hz、每帧给每个电机 `(q, dq, kp, kd, tau)` 五元组、阶段切换要平滑。实时操控的核心思路是把"输入源"(键盘 / 手柄 / 网络) 跟"控制循环" 解耦: 输入侧只更新一份共享目标, 控制侧高频读这份目标计算指令。
