# `unitree_mujoco` 使用深度指南（含你遇到的三个具体问题答案）

本文针对 `~/unitree/unitree-notes/unitree_mujoco/simulate_python/unitree_mujoco.py`（Python 版仿真器，G1 / Go2 / H1 等的 sim-to-real 桥），把以下内容讲透：

1. 仿真器到底在做什么；
2. **悬挂带（Elastic Band）三个键 7 / 8 / 9 的真实语义**，以及 “按 8 把它放到地面、再按 9 释放，机器人为什么会瞬间趴下站不起来”；
3. **为什么 “开着 mujoco 的窗口跑 `python stand_go2.py`，仿真没有任何反应”**；
4. **仿真器里到底支不支持 “高层指令” / SportModeCmd**；
5. MuJoCo viewer 的所有内建快捷键；
6. 排错速查表。

> 你的 `config.py` 现在的状态（来自项目记录）：
>
> ```python
> ROBOT = "g1"
> ROBOT_SCENE = "../unitree_robots/g1/scene.xml"   # → g1_29dof
> DOMAIN_ID = 1
> INTERFACE = "lo"
> USE_JOYSTICK = 0
> ENABLE_ELASTIC_BAND = True
> SIMULATE_DT = 0.005
> VIEWER_DT = 0.02
> ```
>
> 下面的所有解释都基于这个配置，如果你切到 Go2，就把 `ROBOT="go2"`、把 `ENABLE_ELASTIC_BAND` 关掉（四足不需要悬挂带）。

---

## 1. 仿真器进程到底在跑什么

`simulate_python/unitree_mujoco.py` 这一个 Python 进程同时承担三件事：

| 角色 | 实现 | 节拍 |
|---|---|---|
| **物理仿真** | `mujoco.mj_step(mj_model, mj_data)` | `SIMULATE_DT = 5 ms` |
| **可视化窗口** | `mujoco.viewer.launch_passive(...)` 弹出的 GLFW 窗口 | `VIEWER_DT = 20 ms`（50 fps） |
| **DDS 桥（假装是真机）** | `UnitreeSdk2Bridge`，3 个 `RecurrentThread` | 与物理同步 / 100 Hz |

桥（`unitree_sdk2py_bridge.py`）做的事就两件：

- **订阅** `rt/lowcmd`：拿到的 `LowCmd_` 直接被翻译成关节力矩写进 `mj_data.ctrl[i]`：
  ```
  mj_data.ctrl[i] = tau_ff + Kp*(q_des - q_actual) + Kd*(dq_des - dq_actual)
  ```
- **发布** `rt/lowstate`、`rt/sportmodestate`、`rt/wirelesscontroller`：把 mujoco 当前的关节角、速度、力矩、IMU、世界位置等打包，给外部脚本读。

**关键点：桥只懂 “低层 PD 控制”。** 你下发 `LowCmd_` 它就照着算力矩；你**不**下发，仿真里的电机就保持上一次的指令（`mj_data.ctrl` 不会清零，不过 PD 增益还是会让它去追上一帧的目标位置；如果是刚启动，`ctrl` 全 0，没有任何力矩抵抗重力）。

---

## 2. 悬挂带（Elastic Band）：7 / 8 / 9 三个键的真实语义

源码在 `simulate_python/unitree_sdk2py_bridge.py` 第 399~428 行：

```python
class ElasticBand:
    def __init__(self):
        self.stiffness = 200      # 弹簧刚度
        self.damping   = 100      # 阻尼
        self.point     = np.array([0, 0, 3])   # 悬挂点（世界系，Z=3 m）
        self.length    = 0        # 当前悬挂带 “未拉伸长度”
        self.enable    = True     # 是否真的把弹力施加到机器人

    def Advance(self, x, dx):
        δx       = self.point - x                                 # 悬挂点 - 机器人位置
        distance = np.linalg.norm(δx)
        direction= δx / distance
        v        = np.dot(dx, direction)
        f        = (self.stiffness * (distance - self.length) - self.damping * v) * direction
        return f                                                  # 返回一个 3 维力，作用在 torso/base

    def MujuocoKeyCallback(self, key):
        if key == glfw.KEY_7: self.length -= 0.1   # 悬挂带 “未拉伸长度” 缩短 10 cm → 把机器人往上吊
        if key == glfw.KEY_8: self.length += 0.1   # 悬挂带 “未拉伸长度” 拉长 10 cm → 机器人下降
        if key == glfw.KEY_9: self.enable = not self.enable   # 切换施加 / 不施加这股力
```

把它拆开看：

- **7（Key 7）**：把 `length -= 0.1`。`length` 越短，悬挂带 “以为你应该在的位置” 越靠近天花板（`point=[0,0,3]`），所以**会把机器人往上拽**。多按几次就吊到半空。
- **8（Key 8）**：`length += 0.1`，悬挂带逐渐拉长，等于你松绳子，机器人**慢慢落到地面**。
- **9（Key 9）**：切换 `enable`。`enable=True` 时每个物理步都把 `f = stiffness*(distance-length) - damping*v` 这股力施加到机器人 torso；`enable=False` 时**这股力直接为 0，相当于绳子被剪断**。

> 注意 `enable` 默认就是 `True`，所以你启动仿真时悬挂带**已经在工作**了；多数文档让你 “按 9 启用” 是因为他们在描述 “启动后第一次切换” 的语境，而 9 真正的语义是 **toggle**，不是 “enable”。

### 你的具体现象解释

> “我已经把机器人放到地面了（按了 8），然后按 9 放下的时候机器人瞬间倒地，站不起来。”

完全符合预期，原因有两层：

1. **9 是切换悬挂带，等于直接把保持机器人姿态的那股力撤掉**。不是 “把机器人放到地面再放手”，而是 “把绳子剪了”。机器人 torso 上一帧还在被一个 200 N/m 的弹簧 + 100 Ns/m 的阻尼器扶着，下一帧那股力直接归零。

2. **更关键：你没有任何脚本在向 `rt/lowcmd` 发指令**。没有指令意味着：
   - 仿真启动到现在 `mj_data.ctrl[:]` 还是全 0；
   - 没有 PD 控制器去维持每个关节的目标角；
   - G1 的 29 个电机都处于 “零力矩 + 零目标” 状态——本质上就是被关节摩擦力顶着的一堆死铁。

   悬挂带在的时候你看到机器人 “站着”，那不是机器人在站，是绳子在挂。一松手，它当然瘫成一摊。

**正确做法**应该是：

```
A. 终端 1 起 mujoco（悬挂带默认 enable=True，机器人被吊在原地）
B. 终端 2 起一个会持续发 LowCmd_ 的控制脚本（比如本仓库的 g1_sim_keyboard.py）
   等它打印 "got lowstate, ramping to zero pose" 之后，
   就说明 PD 控制器已经接管了
C. 这时候才在 viewer 里：
   8 → 把悬挂带逐步拉长（机器人慢慢下到地面）
   9 → 想要彻底松绳子的时候才按
```

如果是双足机器人（G1/H1）想测 “站立”，并且你**没有**站立 RL 策略 / MPC，那就**永远不要按 9**——双足在零控制下站不住，这是物理事实，跟仿真没关系。

> 想测站立 / 行走 RL 策略，请用同仓库的 `unitree_rl_mjlab` 跑一个训练好的 policy，policy 在 `rt/lowcmd` 上持续发指令，那时候按 9 才是合理的。

---

## 3. 为什么 “一个窗口开着 mujoco，另一个窗口跑 `python stand_go2.py`，仿真完全没反应”

这是**最常见**的 sim-to-sim 坑。`example/python/stand_go2.py` 是给 **Go2 四足** 写的，跟你当前仿真的 G1 完全不兼容，三处不匹配同时发作：

### 不匹配 ①：消息 IDL 是两套不同的协议

| 机型 | LowCmd 用的 IDL | 字段差异 |
|---|---|---|
| Go2 / B2 / H1 / Go2w / B2w | `unitree_go::msg::dds_::LowCmd_` | 20 个 motor_cmd，无 `mode_pr` / `mode_machine` |
| **G1 / H1-2** | `unitree_hg::msg::dds_::LowCmd_` | 35 个 motor_cmd，有 `mode_pr` / `mode_machine` |

`bridge.py` 顶部根据 `config.ROBOT` 二选一：

```python
if config.ROBOT == "g1":
    from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_   # ← 你当前是这条
else:
    from unitree_sdk2py.idl.unitree_go.msg.dds_ import LowCmd_, LowState_
```

而 `stand_go2.py` 写死了 `unitree_go.msg.dds_.LowCmd_`。**虽然 topic 名都是 `rt/lowcmd`，但 DDS 是按消息类型签名匹配的**，类型不一致 → 桥的 subscriber 直接不会触发回调 → `mj_data.ctrl` 永远不会被更新 → mujoco 看起来啥反应都没有。

### 不匹配 ②：DOMAIN_ID 也不一样

`stand_go2.py` 的代码：

```python
if len(sys.argv) < 2:
    ChannelFactoryInitialize(1, "lo")     # 这个分支跟仿真匹配
else:
    ChannelFactoryInitialize(0, sys.argv[1])
```

如果你不带任何参数跑 `python stand_go2.py`，domain 是对上的（1）。但**只要带任何参数**，它会切到 domain 0 + 网卡名，那时候 `lo` 的 `rt/lowcmd` 根本没人发。这不是你现在的问题，但是个常见坑。

### 不匹配 ③：关节数量 / 机型不对

即使你把上面两个修了，`stand_go2.py` 内部只填了 12 个 motor_cmd（四足 12 自由度），G1 是 29 自由度，前 12 个对应 G1 的双腿，关节定义和零位都不一样。强行下发会让 G1 双腿做出 “想做 Go2 趴下” 的姿势，腰、手臂、踝完全没指令，瞬间炸开。

### 解决方法

**最简单**：要测站立，请用本仓库给 G1 准备的脚本，不要去碰 `stand_go2.py`：

```bash
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_low_level.py            # 上游官方 demo 的 sim 友好版
# 或者
python g1_sim_interactive.py          # 已有的交互式 demo
# 或者（本指南配套的）
python g1_sim_keyboard.py             # 详见 use1.md
```

**或者**真的要跑 Go2 demo：把 `simulate_python/config.py` 改回 `ROBOT = "go2"`、`ENABLE_ELASTIC_BAND = False`，重启 mujoco。然后再跑 `stand_go2.py`，这次它就能控住 Go2。

### 怎么自查 “消息有没有真的到达 bridge”

bridge 的 `LowCmdHandler` 没打日志，但你可以临时加一行：

```python
def LowCmdHandler(self, msg: LowCmd_):
    print(".", end="", flush=True)   # 临时调试
    if self.mj_data != None:
        ...
```

如果终端 1 一直没有 `.` 滚出来，说明终端 2 的脚本根本没把消息送过来——99% 是 IDL 不匹配 / domain 不匹配。

---

## 4. 仿真器里到底支不支持 “高层指令”（HighCmd / SportModeCmd / LocoClient）？

**不支持。** `unitree_mujoco` 是给低层 sim-to-real 验证用的，bridge 里只挂了 4 个东西：

| Topic | 方向 | 类型 | 用途 |
|---|---|---|---|
| `rt/lowcmd` | bridge **订阅** | `LowCmd_` (hg or go) | 你下发关节级 PD 目标 |
| `rt/lowstate` | bridge **发布** | `LowState_` | 关节角速度力矩 + IMU |
| `rt/sportmodestate` | bridge **发布** | `SportModeState_` | 世界位置、速度（只读，给你拿，不接收 cmd） |
| `rt/wirelesscontroller` | bridge **发布** | `WirelessController_` | 模拟 Unitree 手柄按键 |

**没有** `rt/sportmodecmd`、`SportClient`、`LocoClient`、`G1ArmActionClient`、`MotionSwitcherClient` 这些高层服务的实现——它们在真机上是由出厂运动控制服务跑的，仿真里没有这块代码。

所以下面这些上游例子在仿真里 **跑不通**：

- `unitree_sdk2_python/example/g1/high_level/g1_loco_client_example.py`
- `unitree_sdk2_python/example/g1/high_level/g1_arm_action_example.py`（"shake hand", "high five", "hug" 等等都是高层 RPC）
- `unitree_sdk2_python/example/go2/sport_client.py`

它们调 RPC 的时候会卡在 `client.Init()`，因为找不到对端服务。

### 那 “高层动作” 怎么在仿真里搞？

**只能你自己在低层（关节级 PD）上 “编排” 动作**：写一组目标关节角的关键帧，然后用你自己的控制器在 `rt/lowcmd` 上把这些关键帧平滑播放出来。这正是 `g1_sim_interactive.py` 和本指南配套的 `g1_sim_keyboard.py` 在做的事——**用低层模拟出 “伪高层” 接口**：你按一个键，对应一个预设动作（招手、敬礼、深蹲、抬腿……）。

如果想要 “走路 / 跑步” 这种动态动作，单纯的 PD 关键帧不够（机器人会摔），需要：
- RL 策略（`unitree_rl_mjlab`），或
- 基于模型的控制器（MPC），或
- 复现一段已有动作捕捉数据。

这些都已经超出 “mujoco demo” 的范畴了。本仓库的两个交互 demo 只覆盖**静态 / 准静态** 的 “手臂、腰、单腿抬” 一类动作。

---

## 5. MuJoCo viewer 内建快捷键速查（passive viewer，3.5.0）

`mujoco.viewer.launch_passive(...)` 会弹出标准的 MuJoCo viewer。除了上面 `key_callback` 注册的 7 / 8 / 9，剩下的全是 MuJoCo 自带的，你应该都能用。**鼠标点到 viewer 窗口里再按，不要在终端里按！**

| 键 | 功能 |
|---|---|
| **空格** | 暂停 / 继续物理仿真（仿真冻结，桥的 thread 还在跑，但 mj_step 不前进） |
| **←** / **→** | 仿真单步前 / 后退一帧（仅暂停时） |
| **Tab** | 显示 / 隐藏左侧的 “Help / Option / Simulation / Camera / Visualization / Group / Joint” 控制面板 |
| **F1** | 显示帮助（不太全，建议看官方手册） |
| **F2** | 显示信息覆盖层（仿真步数、时间、求解器迭代等） |
| **F5** | 全屏切换 |
| **F6** | 立体视图切换（一般不用） |
| **F7** | 显示 “label”（关节 / body 名字浮在物体上） |
| **H** | 显示帮助（替代 F1） |
| **R** | 重置仿真到 `keyframe 0`（如果 MJCF 里没定义 keyframe，就回到初始 qpos / qvel） |
| **C** | 显示接触点（红色箭头是法向力） |
| **B** | 显示接触力（带数值） |
| **F** | 显示外力（包括我们悬挂带施加的那股力） |
| **I** | 显示 inertia box |
| **J** | 显示关节坐标系 |
| **G** | 显示 / 隐藏地面 grid |
| **;** | 关节 / actuator 标签开关 |
| **D** | 加速 / 慢速切换（rt-factor）。多按可循环切几个挡 |
| **=** / **-** | 增大 / 减小 visualization 元素的缩放（例如箭头长度） |
| **0–4** | 切换 “半透明、wireframe、纹理、阴影” 等渲染模式 |
| **Esc** | 关闭 viewer 窗口（会让两个 thread 退出 while loop，进程结束） |
| **左键拖** | 旋转视角 |
| **右键拖** | 平移视角 |
| **滚轮** | 缩放 |
| **左 + 右键拖** / **中键拖** | 平移视角 |
| **Ctrl + 左键拖某个 body** | 给那个 body 施加外力（这是真物理力，G1 上你能直接 “推” 它） |
| **Ctrl + 右键拖某个 body** | 给那个 body 施加力矩 |
| **双击某个 body** | 选中并显示属性 |

> 不同版本（3.x）的快捷键可能略有差别。**`H` / `Tab`** 一定能调出当前版本真正生效的列表。

### 我们仓库额外注册的（来自 `ElasticBand.MujuocoKeyCallback`）

| 键 | 功能 | 备注 |
|---|---|---|
| **7** | 悬挂带 “未拉伸长度” -0.1 m → 把机器人往**上吊** | 多按几次能吊到半空 |
| **8** | 悬挂带 “未拉伸长度” +0.1 m → 把机器人往**下放** | 多按到 length ≈ 与高度差相等时刚好踩地 |
| **9** | 切换 `enable`：True ↔ False | **toggle，不是 "enable"！** 详见第 2 节 |

注册的逻辑是 `mujoco.viewer.launch_passive(..., key_callback=elastic_band.MujuocoKeyCallback)`，**MuJoCo viewer 没消费的键**才会传到这个 callback。所以 7/8/9 跟内建键不冲突；如果你想加更多键，只要避开内建键即可。

---

## 6. 排错速查

| 现象 | 直接原因 | 修复 |
|---|---|---|
| 启动后 G1 在空中 | 悬挂带 `enable=True, length=0`，把它吊在 Z=3 m | 想放下来按 8（注意第 2 节的警告） |
| 按 9 后机器人瘫倒 | 没有控制器在发 LowCmd_ | 先在终端 2 起 `g1_sim_*.py`，再按 9 |
| 终端 2 卡 “waiting for first /rt/lowstate” | DOMAIN_ID 不一致 / INTERFACE 不是 lo / 仿真器没起来 | 检查 `config.py` 是 `DOMAIN_ID=1, INTERFACE="lo"` |
| 终端 2 在跑但 mujoco 没反应 | IDL 不匹配（hg vs go）or 机型不一致 | G1 必须用 `unitree_hg`；Go2 必须用 `unitree_go` |
| viewer 弹不出来（WSL2） | WSLg 没启 / `$DISPLAY` 没设 | WSL2 默认有 WSLg；ssh 进去要 `ssh -X` |
| 仿真步骤跑得慢 / 卡 | `SIMULATE_DT` 比 `viewer.sync()` 时间还小 | 把 `SIMULATE_DT` 调大到 0.005~0.008 |
| 关节抽搐 / 嗡嗡颤 | Kp 太大 | 用 `g1_sim_*.py` 提供的那一套 Kp/Kd，不要乱改 |
| `USE_JOYSTICK=1` 但脚本退出 | pygame 找不到手柄 | 改回 `USE_JOYSTICK=0` |
| `CRC mismatch` 警告 | 没在 `Write` 之前 `low_cmd.crc = crc.Crc(low_cmd)` | 每帧都要算 |
| 想测站立但摔倒 | 双足在零策略下站不住，物理决定 | 用 RL policy 或本仓库的 `g1_sim_keyboard.py`（关键帧式 PD 保持） |

---

## 7. 一个完整的 “最小可工作” 流程（适用于 G1 + 本仓库 demo）

```bash
# === 终端 1 ===
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python

# 确认 config.py 是这个状态：
#   ROBOT="g1", DOMAIN_ID=1, INTERFACE="lo",
#   USE_JOYSTICK=0, ENABLE_ELASTIC_BAND=True
python unitree_mujoco.py
# 预期：弹出 viewer，G1 被悬挂带吊住；终端会打印 link/joint/sensor 列表
```

```bash
# === 终端 2 ===
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_keyboard.py        # 详见 ./use1.md
# 预期：终端打印 "got lowstate, ramping to zero pose"，
# G1 在 viewer 里平滑落到零位姿态，然后等你按键。
```

到这一步，控制器已经接管了。**只有这时候**你才可以回 viewer 窗口按：

- `8` → 慢慢放到地面（每按一次 -10 cm）
- `9` → 真正释放绳子（要承担它会摔的风险，除非你的控制器能站立）

如果只是测手臂、敬礼、招手之类的动作，**不需要按 9**——保持悬挂状态最稳。
