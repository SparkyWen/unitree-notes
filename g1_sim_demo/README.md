# G1 MuJoCo SDK 桥接 Demo（关节级动作）

把 `unitree_mujoco/simulate_python` 当作 G1 真机替身，由 `unitree_sdk2_python` 通过
DDS 下发 `LowCmd_`。本目录保存了一份 **sim 友好** 版本的 G1 低层例子，避开了上游
`g1_low_level_example.py` 在仿真里跑不通的两点：

1. 上游强写 `ChannelFactoryInitialize(0, ...)`（domain 0），但 `simulate_python/config.py`
   默认 `DOMAIN_ID=1`，topic 不互通。本脚本默认 `domain 1 + lo`。
2. 上游会调用 `MotionSwitcherClient.CheckMode()`，仿真里没有这个服务（bridge 只暴露
   `rt/lowcmd / rt/lowstate / rt/sportmodestate / rt/wirelesscontroller`），会卡死。
   本脚本把这一段去掉，并等第一帧 `lowstate` 拿到 `mode_machine` 之后再起控制环。

## 已完成的环境配置

- conda env: `unitree`（Python 3.11，含 `unitree_sdk2py / mujoco 3.5.0 / pygame / cyclonedds`）
- `unitree_mujoco/simulate_python/config.py` 已切到 G1：
  - `ROBOT = "g1"`（默认场景 `scene.xml` → 加载 `g1_29dof.xml`，29 个电机）
  - `ENABLE_ELASTIC_BAND = True`（双足机器人需要悬挂带）
  - `USE_JOYSTICK = 0`（没接手柄就关掉，不然会 `sys.exit()`）
  - `DOMAIN_ID = 1`、`INTERFACE = "lo"`（保持与文档约定一致）

## 运行步骤

需要两个终端，每个终端都先激活环境：

```bash
conda activate unitree
# 没 conda init 的话用：
# source ~/miniforge3/etc/profile.d/conda.sh && conda activate unitree
```

### 终端 1：启动 MuJoCo 仿真器

```bash
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

启动后会弹出 MuJoCo viewer，G1 默认会从空中落下。**在 viewer 里按 `9` 启用悬挂带**
把它吊在原地（按 `7` 放下、按 `8` 抬起）。这样下一步发的电机指令才能稳定执行。

### 终端 2：运行 G1 demo

```bash
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_low_level.py
```

控制流程（与上游例子一致）：
- **0–3 s**：把每个关节从当前姿态平滑插值到零位姿态。
- **3–6 s**：PR 模式下双脚踝做正弦摆动（pitch ±30°，roll ±10°，频率 1 Hz）。
- **6 s 起**：切到 AB 模式做同样幅度的踝关节摆动 + 双手腕 roll 30° 摆动。

终端 2 每 1 秒会打印一次 IMU 的 RPY，作为存活心跳。

### 控制真机

```bash
python g1_sim_low_level.py enp3s0   # 把 enp3s0 换成实际网卡名
```

任何不是 `lo` / `sim` 的第一参数都会被当作真实网卡名，并改用 domain 0
（与上游 `g1_low_level_example.py` 行为一致）。**注意：真机版回归到带
`MotionSwitcherClient` 的上游脚本更安全**，本脚本的真机路径只是兼容入口。

## 故障排查

- **viewer 弹不出来**：当前是 WSL2，确认 `$DISPLAY` 已设置（WSLg 会自动配置）。
  若用 SSH，需要 `ssh -X`。
- **终端 2 卡在 "waiting for first /rt/lowstate"**：仿真器没起来，或 domain/interface
  对不上。检查 `simulate_python/config.py` 是不是 `DOMAIN_ID=1, INTERFACE="lo"`。
- **机器人立刻摔倒**：忘记按 `9` 启用悬挂带。
- **CRC 校验失败 / 电机不动**：确认仿真器加载的是 G1 的 29dof 场景（`scene.xml`
  默认就是），且 `unitree_hg` 消息格式（bridge 会根据 `config.ROBOT=="g1"` 自动选）。
