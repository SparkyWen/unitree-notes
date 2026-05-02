# `g1_sim_keyboard.py` 使用教程（键盘式高层动作 Demo）

`~/unitree/unitree-notes/g1_sim_demo/g1_sim_keyboard.py`

把 MuJoCo 仿真器当作 G1 真机替身，用键盘触发**预设的高层动作**（招手、敬礼、拥抱、深蹲、左右抬腿、出拳……），并提供：

- **`r` / `i` —— 一键回到初始姿态**（脚本启动时第一帧测到的真实姿态，永远可恢复）；
- **`z` —— 平滑回到零位姿态**（代码默认参考姿态）；
- **`x` —— 软关 PD**（在按 viewer 的 `9` 释放悬挂带之前 “松力”，避免突然跳）；
- **`+` / `-` —— 全局动作慢放 / 快放**；
- **`q` —— 优雅退出**（先回零位再关闭，不会让机器人砸到地面）。

它和现有的 `g1_sim_interactive.py` 走的是同一套 “关键帧 + cosine ease-in-out 平滑插值” 架构，但动作库扩了一倍，并且 reset 是真的回到 “启动那一刻的姿态”，不是单纯回零。

> **重要前提**：必须 **先** 在另一个终端起好 `unitree_mujoco/simulate_python/unitree_mujoco.py`，并且在 viewer 里 **保持悬挂带启用**（启动后默认就是 enable=True）。**双足在零策略下站不住**——本 demo 不是站立 / 行走 RL 控制器，只能在悬挂状态下做静态 / 准静态动作。详情见 `~/unitree/unitree-notes/docs/mujoco_use.md` 第 2、4 节。

---

## 1. 一次性环境检查

```bash
# 你已经配好的 conda env：
conda activate unitree
python -c "import unitree_sdk2py, mujoco, numpy; print(unitree_sdk2py.__file__, mujoco.__version__)"
# 期望：路径在 ~/miniforge3/envs/unitree/...,  mujoco 3.5.0
```

`unitree_mujoco/simulate_python/config.py` 必须是这样：

```python
ROBOT = "g1"
ROBOT_SCENE = "../unitree_robots/g1/scene.xml"   # → g1_29dof
DOMAIN_ID = 1
INTERFACE = "lo"
USE_JOYSTICK = 0           # 没接手柄就关掉，否则 sim 进程会 sys.exit()
ENABLE_ELASTIC_BAND = True # 双足必开
```

---

## 2. 启动两个终端

### 终端 1 — MuJoCo 仿真器

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

预期：

- 弹出 MuJoCo viewer，G1 被悬挂带吊在原地（`enable=True, length=0`）；
- 终端打印 link / joint / actuator / sensor 列表，然后停在物理循环里；
- **不要按 `9`！** 按了就剪绳子，机器人会摔。

### 终端 2 — Demo 脚本

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_keyboard.py
```

预期：

```
[g1] simulator mode on lo (domain 1).
[g1] waiting for first /rt/lowstate ...
[g1] got lowstate (mode_machine=0). Ramping to zero pose.

==== G1 keyboard playground ====
(Focus this terminal; viewer keys 7/8/9 still control band.)

  z  ramp to zero pose
  w  wave right arm
  e  wave left arm
  ...
  r / i   reset to initial pose captured at startup
  x       soften PD (ramp Kp,Kd -> 0 over 1.5 s)
  +       slow-mo all actions (0.7x duration scale)
  -       fast-mo all actions (1.4x duration scale)
  =       reset duration scale to 1.0x
  ?       print this help
  q       quit (settles to zero pose first)
===============================
```

3 秒后 G1 在 viewer 里平滑落到零位姿态，**这个终端窗口** 等你按键。

> **焦点不在终端就没反应**。鼠标点回这个窗口后再按键。
> 7 / 8 / 9 三个键依然只在 **viewer 窗口** 里管悬挂带，跟本 demo 无关。

---

## 3. 完整按键表

### 上半身

| 键 | 动作 | 描述 |
|---|---|---|
| `w` | wave right arm | 右臂招手（侧上方） |
| `e` | wave left arm | 左臂招手 |
| `u` | hands up (cheer) | 双臂笔直举高 |
| `t` | T-pose | 双臂水平张开 |
| `s` | salute | 右手敬礼（停 1.2 s 再放下） |
| `a` | clap (twice) | 拍手两次 |
| `h` | hug | 抱拳 / 拥抱姿势（双肘内合） |
| `g` | boxer guard | 拳击预备姿态 |
| `p` | punch right (jab) | guard → 右直拳 → guard → 左直拳 → guard |

### 腰部

| 键 | 动作 | 描述 |
|---|---|---|
| `b` | bow | 弯腰（waist pitch 0.5 rad ≈ 28°） |
| `[` | lean left | 向左侧倾（waist roll +0.35） |
| `]` | lean right | 向右侧倾（waist roll −0.35） |
| `,` | twist left | 左转身（waist yaw +0.5） |
| `.` | twist right | 右转身（waist yaw −0.5） |

### 下半身（**只在悬挂带启用时安全！**）

| 键 | 动作 | 描述 |
|---|---|---|
| `k` | lift left knee | 抬左膝 |
| `l` | lift right knee | 抬右膝 |
| `c` | squat (hold 1.5 s) | 双腿下蹲 |
| `v` | right kick (hold) | 右腿前踢悬停 |

> **下半身动作在没有平衡控制器的情况下，落地后会让重心不稳**。建议保持 viewer 中按 `7` 把机器人吊起来一点（机器人足底离地 5 cm 左右），动作做完后再按 `8` 慢慢放下。

### 控制 / 系统键

| 键 | 含义 |
|---|---|
| `z` | 平滑回到代码定义的零位姿态（2 s 插值） |
| `r` 或 `i` | **reset：平滑回到 demo 启动时第一次测到的真实姿态**（`init_pose`） |
| `x` | 软关：把 Kp、Kd 在 1.5 s 内降到 0（关节失能，机器人靠悬挂带挂着） |
| `+` | 慢放：`duration_scale ×= 0.7`（动作变慢） |
| `-` | 快放：`duration_scale ×= 1.4` |
| `=` | 复位 `duration_scale = 1.0` |
| `?` | 打印按键表（任何时候都能查） |
| `q` | 安全退出：先回零位再退 |
| `Ctrl-C` | 同 `q`：脚本会捕获并先回零位 |

---

## 4. `reset` 的真实语义

代码里 “初始姿态” 不是硬编码的零位，而是**脚本启动时收到的第一帧 `LowState_` 里的关节角**：

```python
def _on_state(self, msg: LowState_):
    self.low_state = msg
    if not self.first_state_received:
        self.mode_machine = msg.mode_machine
        measured = np.array(
            [msg.motor_state[i].q for i in range(G1_NUM_MOTOR)],
            dtype=np.float64,
        )
        self.q_cmd     = measured.copy()
        self.init_pose = measured.copy()    # ← 这就是 reset 要去的姿态
        self.first_state_received = True
```

- 你在 viewer 里启动仿真时 G1 有什么姿态（被悬挂带挂着、双臂自然下垂），`init_pose` 就是那个姿态；
- 之后无论你按 `w` / `c` / `p` 怎么折腾，按 `r` 总能让它回到那个姿态；
- 它**不**会去重置 viewer 的 `mj_data.qpos` 和 `qvel`（那是物理状态，不归 demo 管）。如果你想让物理状态也归零（比如机器人飘走了），请到 viewer 里按 **`R`**（大写）—— MuJoCo 内建的 “重置仿真到 keyframe 0”。这是两件事：
  - viewer `R` = 重置物理；
  - terminal `r` = 让控制器重新去追初始关节姿态。

> 如果你要的 “完全重启” 是 “物理 + 控制器 + 重新挂悬挂带”，最简单的办法是：在终端 2 按 `q` 退出 → 在 viewer 里按 `R` → 重新跑 `python g1_sim_keyboard.py`。

---

## 5. 进阶：自定义动作

### 写一个新姿态

```python
# 在 g1_sim_keyboard.py 里，跟 wave_right_pose() 一起加：
def my_squat_with_arms_up_pose():
    p = squat_pose()
    p[J.LeftShoulderPitch]  = -1.6
    p[J.RightShoulderPitch] = -1.6
    return p
```

### 把它注册成一个动作（按键 `n`）

在 `build_actions()` 的 list 里追加一行：

```python
Action("n", "squat with arms up",
       [(2.0, my_squat_with_arms_up_pose()),
        hold(my_squat_with_arms_up_pose(), 1.0),
        (2.0, zero_pose())]),
```

`hold(pose, t)` 是工具函数，等价于 `(t, pose.copy())`，让机器人在那个姿态停 `t` 秒。

### 注意事项

- 每个 pose 都要是 **长度 29 的 numpy 数组**，单位 **rad**；
- 关节限位见 `unitree_robots/g1/g1_29dof.xml` 中每个 `<joint .. range="..."/>`，不要超出；
- **不要**在脚本里直接修改 `ctl.q_cmd`——用 `push()` 走插值队列，不会跳；
- 如果你想做的是 “连续遥操作 / VR / RL 推理”，参考 `demo-explain.md` 第 8.5 节的一阶低通替代方案，本 demo 的离散关键帧不适合。

---

## 6. 我应该按什么键来 “走路”？

**没有这个键**，原因见 `mujoco_use.md` 第 4 节：

- 仿真器只支持低层 PD（`rt/lowcmd`）；
- 真机上的 “走路 / 转向” 是出厂运动控制服务（`SportClient` / `LocoClient`）的功能，**仿真里没有这个服务**；
- 静态关键帧不能让双足真的走路（即使在仿真里，重心一动就摔）。

如果你要在仿真里走路：

1. 用 `~/unitree/unitree-notes/unitree_rl_mjlab` 训一个 RL 策略（mjlab + rsl_rl，velocity tracking）；
2. 或者跑现成的预训练 checkpoint（仓库里有）；
3. policy 会持续往 `rt/lowcmd` 写关节目标 → bridge 算 PD → 物理推进。
   那时候按 viewer 的 `9` 释放悬挂带是合理的，因为有控制器在维持平衡。

---

## 7. 故障排查（针对本 demo）

| 现象 | 原因 | 修复 |
|---|---|---|
| 终端 2 卡在 `waiting for first /rt/lowstate` | 仿真器没起来 / domain 不是 1 / interface 不是 lo / config.py 不是 G1 | 见 `mujoco_use.md` 第 6 节 |
| 按键完全没反应 | 焦点在 viewer 窗口里 | 鼠标点回 demo 终端 |
| G1 能动，但所有动作都很 “肉”，跟不上目标 | `kp_scale` 还是 0（你之前按了 `x`） | 按 `r` 或 `i`，会把 kp_scale 恢复成 1.0 |
| `r` 之后机器人跑去一个奇怪姿态 | 启动时 `init_pose` 就采到那个姿态 | 退出 demo，在 viewer 里按 `R`（重置物理）+ 按 `7` 调整悬挂高度 → 重启 demo，让 `init_pose` 重新采样 |
| 切到 Go2 / B2 后 demo 报错 | 这个 demo 写死 `unitree_hg`（G1 / H1-2） | Go2 系列请用 `example/python/stand_go2.py` 或自己写 `unitree_go` 版本 |
| 终端打印 lowstate 心跳 / `imu rpy: …` | 不是本 demo 的输出，是 `g1_sim_low_level.py` 的 | 不要同时跑两个客户端，会互相覆盖 `rt/lowcmd` |
| 退出后 mujoco 里机器人变 “死沉” | 退出时 demo 已发了零位 + 默认 PD，最后一次的 ctrl 还残留在 `mj_data.ctrl`；新进程接管前不会被清 | 想完全释放就在 viewer 里按 `R` 重置仿真 |

---

## 8. 一页流程图（再贴一次，方便对照）

```
   你（终端 2 按键）        g1_sim_keyboard.py            unitree_mujoco.py        MuJoCo 物理
   ─────────────             ────────────────────          ────────────────         ────────────
   按 w / e / s / ...    →   push 关键帧到 _queue
                              (每帧 cosine ease-in-out)
                              500 Hz 算 q_cmd → LowCmd_
                              CRC → publish "rt/lowcmd"   →   bridge.LowCmdHandler
                                                                τ = τ_ff + Kp·Δq + Kd·Δdq
                                                                 →    mj_data.ctrl[i]
                                                                                       →   mj_step()
                              subscribe "rt/lowstate"     ←    bridge.PublishLowState  ←   sensordata
                              更新 self.low_state
   按 r / i              →   cancel queue → push (init_pose)
   按 x                  →   ramp kp_scale → 0
   按 q                  →   stop_and_settle (回零) → exit
```

---

## 9. 文件清单

```
~/unitree/unitree-notes/g1_sim_demo/
├── README.md                  # 老 demo 的入口（保留）
├── demo-explain.md            # 老 demo 的逐行讲解（保留）
├── g1_sim_low_level.py        # 上游官方 demo 的 sim 友好版
├── g1_sim_interactive.py      # 旧的简版交互 demo（5 个动作）
├── g1_sim_keyboard.py         # ★ 本文档对应的新 demo（19+ 个动作 + reset + soften + 速度调节）
└── use1.md                    # ★ 你正在看的这个文件

~/unitree/unitree-notes/docs/
└── mujoco_use.md              # ★ 仿真器的深度解释（含 7/8/9、IDL 不匹配、为什么 stand_go2 没反应）
```
