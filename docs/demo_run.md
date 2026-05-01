# Unitree 三仓库 Demo 运行指南

本文档汇总 `unitree-notes/` 下三个仓库的所有 demo 运行命令，基于本机 `unitree` conda 环境（已装好 `unitree_sdk2py / mjlab / rsl_rl / mujoco 3.5.0 / mujoco-warp / warp-lang`）。

---

## 0. 公共准备

```bash
# 每个新终端都先激活环境
conda activate unitree
# 或不用 conda init 时：
source ~/miniforge3/etc/profile.d/conda.sh && conda activate unitree
```

> 要点：所有 SDK 例子最后一个参数是网卡名。**仿真用 `lo`**，**真机用真实网卡名**（如 `enp3s0`）。当前 C++ 模拟器和 rl_mjlab 的 C++ deploy 都还没编译过，下面会给出编译步骤。

---

## 1. `unitree_mujoco/` — MuJoCo 模拟器

### 1A. Python 模拟器（最快上手，推荐先跑这个）

```bash
# 终端 1：启动 Python 仿真器（默认加载 go2）
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

```bash
# 终端 2：基础测试（让每个电机持续输出 1 N·m 转矩，并打印姿态/位置）
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python/test
python test_unitree_sdk2.py
```

```bash
# 终端 2 替代：让 go2 站起再趴下（来自 example/python）
cd ~/unitree/unitree-notes/unitree_mujoco/example/python
python stand_go2.py            # 控制仿真（默认 domain_id=1, 网卡 lo）
# python stand_go2.py enp3s0   # 控制真机
```

> 要换机型：编辑 `simulate_python/config.py` 的 `ROBOT`（可选 `go2 / b2 / b2w / go2w / h1 / h1_2 / g1`），保存再启动模拟器。
> 没有手柄时把 `USE_JOYSTICK = 0`。
> H1 / G1 这种双足机型，把 `ENABLE_ELASTIC_BAND = True` 启用悬挂带，运行后按 `9` 上挂、按 `7` 落下、按 `8` 抬起。

### 1B. C++ 模拟器（需要先编译，未构建过）

```bash
# 1. 装系统依赖（一次性）
sudo apt install libyaml-cpp-dev libspdlog-dev libboost-all-dev libglfw3-dev

# 2. 装 unitree_sdk2 到 /opt/unitree_robotics（一次性，C++ demo 都依赖它）
cd ~ && git clone https://github.com/unitreerobotics/unitree_sdk2.git
cd unitree_sdk2 && mkdir -p build && cd build
cmake .. -DCMAKE_INSTALL_PREFIX=/opt/unitree_robotics
sudo make install

# 3. 链接 mujoco（用您 conda 环境里的，或下载 release 解压到 ~/.mujoco/）
cd ~/unitree/unitree-notes/unitree_mujoco/simulate
ln -sfn ~/miniforge3/envs/unitree/lib/python3.11/site-packages/mujoco mujoco

# 4. 编译模拟器
cd ~/unitree/unitree-notes/unitree_mujoco/simulate
mkdir -p build && cd build && cmake .. && make -j4

# 5. 跑 C++ 模拟器
./unitree_mujoco -r go2 -s scene_terrain.xml
```

```bash
# 终端 2：C++ 控制示例（站起趴下）
cd ~/unitree/unitree-notes/unitree_mujoco/example/cpp
mkdir -p build && cd build && cmake .. && make -j4
./stand_go2            # 控制仿真
# ./stand_go2 enp3s0   # 控制真机
```

### 1C. 地形生成工具

```bash
cd ~/unitree/unitree-notes/unitree_mujoco/terrain_tool
python terrain_generator.py    # 生成自定义地形 xml
```

### 1D. ROS2 例子（仅当您配好了 unitree_ros2 环境时才跑）

```bash
source ~/unitree_ros2/setup_local.sh && export ROS_DOMAIN_ID=1
cd ~/unitree/unitree-notes/unitree_mujoco/example/ros2
colcon build && ./install/stand_go2/bin/stand_go2
```

---

## 2. `unitree_sdk2_python/example/` — SDK 例子

> **通用流程**：仿真演示先跑「1A Python 模拟器」并把 `config.py` 的 `ROBOT` 改成对应机型，然后在新终端跑下面命令；命令最后的 `lo` 给仿真用，换成真实网卡名就是真机。

### 2.1 Hello World（DDS 通信，不需要机器人/仿真）

```bash
# 终端 1
cd ~/unitree/unitree-notes/unitree_sdk2_python/example/helloworld
python publisher.py
# 终端 2
python subscriber.py
```

### 2.2 Go2（四足）

```bash
cd ~/unitree/unitree-notes/unitree_sdk2_python/example/go2

# 低级控制（站立）
python low_level/go2_stand_example.py lo

# 高级运动（运动模式 client）
python high_level/go2_sport_client.py lo
python high_level/go2_utlidar_switch.py lo   # 雷达开关

# 前置摄像头（需要真机 + 图形界面，仿真没数据）
python front_camera/camera_opencv.py enp3s0
python front_camera/capture_image.py enp3s0
```

### 2.3 Go2W / B2 / B2W（其它四足）

```bash
# Go2W
python ~/unitree/unitree-notes/unitree_sdk2_python/example/go2w/low_level/go2w_stand_example.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/go2w/high_level/go2w_sport_client.py lo

# B2
python ~/unitree/unitree-notes/unitree_sdk2_python/example/b2/low_level/b2_stand_example.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/b2/high_level/b2_sport_client.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/b2/camera/camera_opencv.py enp3s0   # 真机

# B2W
python ~/unitree/unitree-notes/unitree_sdk2_python/example/b2w/low_level/b2w_stand_example.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/b2w/high_level/b2w_sport_client.py lo
```

### 2.4 G1（人形）— 仿真前先把 `config.py` 里 `ROBOT="g1"` 且 `ENABLE_ELASTIC_BAND=True`

> **G1 低层例子直接 `lo` 跑不通**：上游 `g1_low_level_example.py` 把 domain 强写为 0
> （即使加 `lo` 也只改网卡，不改 domain），而 `simulate_python/config.py` 用的是
> `DOMAIN_ID=1`；并且它启动时会调用 `MotionSwitcherClient.CheckMode()`，但仿真的 SDK 桥
> 只暴露 `rt/lowcmd / rt/lowstate / rt/sportmodestate / rt/wirelesscontroller`，没有
> motion_switcher 服务，会卡死在 init。所以仿真用本仓库自带的 `g1_sim_demo/`（见下方
> 「2.4.1 仿真专用：g1_sim_demo」），真机才用上游的 `g1_low_level_example.py`。

#### 2.4.1 仿真专用：`g1_sim_demo`（推荐先跑这个）

已为仿真改造好的低层 demo：去掉 `MotionSwitcherClient`，改用 `domain 1 + lo`，等首帧
`lowstate` 拿到 `mode_machine` 后再起控制环。三段式动作与上游一致：0–3 s 全身回零位，
3–6 s PR 模式踝关节正弦摆动（pitch ±30°/roll ±10°，1 Hz），6 s 起切到 AB 模式踝关节
摆动 + 双手腕 roll ±30° 摆动。终端每秒打印一次 IMU rpy 作为心跳。

```bash
# 终端 1：启动仿真器（已把 simulate_python/config.py 切到 G1 + 悬挂带 + 关手柄）
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 弹出后，按 9 启用悬挂带（双足机器人需要它撑住），按 7 落下、8 抬起
```

```bash
# 终端 2：跑 sim 友好版 G1 demo
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_low_level.py
# 真机：python g1_sim_low_level.py enp3s0   # 替换为实际网卡名（自动切 domain 0）
```

故障排查：
- 终端 2 卡在 `waiting for first /rt/lowstate` → 仿真器没起，或 domain/INTERFACE 与
  `simulate_python/config.py` 对不上（应为 `DOMAIN_ID=1, INTERFACE="lo"`）。
- 机器人立刻摔倒 → viewer 里没按 `9` 启用悬挂带。
- viewer 弹不出 → WSL2 下确认 `$DISPLAY` 已配（WSLg 自动设；SSH 用 `ssh -X`）。

#### 2.4.2 高级例子（loco / 手臂）

```bash
cd ~/unitree/unitree-notes/unitree_sdk2_python/example/g1

# 高级 loco / 手臂动作（仿真支持情况依赖 bridge 是否开启对应服务，部分仅真机可用）
python high_level/g1_loco_client_example.py lo
python high_level/g1_arm_action_example.py lo
python high_level/g1_arm5_sdk_dds_example.py lo
python high_level/g1_arm7_sdk_dds_example.py lo

# 音频（仅真机）
python audio/g1_audio_client_example.py enp3s0
python audio/g1_audio_client_play_wav.py enp3s0
```

#### 2.4.3 真机低层（绕过 sim 改造，用回上游）

```bash
# 真机才跑这条；走 motion_switcher 释放当前模式后再下发 lowcmd
python ~/unitree/unitree-notes/unitree_sdk2_python/example/g1/low_level/g1_low_level_example.py enp3s0
```

### 2.5 H1 / H1_2 / H2（人形）

```bash
# H1
python ~/unitree/unitree-notes/unitree_sdk2_python/example/h1/low_level/h1_low_level_example.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/h1/high_level/h1_loco_client_example.py lo

# H1_2
python ~/unitree/unitree-notes/unitree_sdk2_python/example/h1_2/low_level/h1_2_low_level_example.py lo

# H2
python ~/unitree/unitree-notes/unitree_sdk2_python/example/h2/low_level/h2_ankle_swing_example.py lo
python ~/unitree/unitree-notes/unitree_sdk2_python/example/h2/high_level/h2_loco_client_example.py lo
```

### 2.6 其它工具

```bash
# 无线手柄状态打印
python ~/unitree/unitree-notes/unitree_sdk2_python/example/wireless_controller/wireless_controller.py lo

# 运动模式切换
python ~/unitree/unitree-notes/unitree_sdk2_python/example/motionSwitcher/motion_switcher_example.py lo

# 灯光与音量（需 Go2-EDU 真机）
python ~/unitree/unitree-notes/unitree_sdk2_python/example/vui_client/vui_client_example.py enp3s0

# 避障开关（需真机服务）
python ~/unitree/unitree-notes/unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_switch.py enp3s0
python ~/unitree/unitree-notes/unitree_sdk2_python/example/obstacles_avoid/obstacles_avoid_move.py   enp3s0
```

---

## 3. `unitree_rl_mjlab/` — 强化学习训练 / 回放 / 部署

> 您已经有一个训练好的 checkpoint：`logs/rsl_rl/go2_velocity/2026-05-01_23-48-18/model_1.pt`，所以可以直接 Play。

### 3.1 列出可用任务

```bash
cd ~/unitree/unitree-notes/unitree_rl_mjlab
python scripts/list_envs.py
```

### 3.2 训练（需要 GPU；CPU 也能跑但很慢）

```bash
# 速度跟踪（任选一项）
python scripts/train.py Unitree-Go2-Flat       --env.scene.num-envs=4096
python scripts/train.py Unitree-G1-Flat        --env.scene.num-envs=4096
python scripts/train.py Unitree-G1-23Dof-Flat  --env.scene.num-envs=4096
python scripts/train.py Unitree-H1_2-Flat      --env.scene.num-envs=4096
python scripts/train.py Unitree-A2-Flat        --env.scene.num-envs=4096
python scripts/train.py Unitree-R1-Flat        --env.scene.num-envs=4096

# 多 GPU
python scripts/train.py Unitree-G1-Flat --gpu-ids 0 1 --env.scene.num-envs=4096
```

### 3.3 动作模仿（G1 跳舞）

```bash
# 1) csv → npz
python scripts/csv_to_npz.py \
  --input-file src/assets/motions/g1/dance1_subject2.csv \
  --output-name dance1_subject2.npz \
  --input-fps 30 --output-fps 50 --robot g1

# 2) 训练
python scripts/train.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/dance1_subject2.npz \
  --env.scene.num-envs=4096
```

### 3.4 Play（回放策略可视化）— 直接用现成的 checkpoint

```bash
# 您仓库里已有 go2 的 checkpoint，可直接跑：
python scripts/play.py Unitree-Go2-Flat \
  --checkpoint_file=logs/rsl_rl/go2_velocity/2026-05-01_23-48-18/model_1.pt

# 模仿任务的回放：
python scripts/play.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/dance1_subject2.npz \
  --checkpoint_file=logs/rsl_rl/g1_tracking/<日期>/model_xx.pt
```

### 3.5 地形可视化

```bash
python scripts/visualize_terrain.py
```

### 3.6 Sim2Real 部署（C++，需先编译；未构建过）

```bash
# 1) 编译内置的 unitree_mujoco
cd ~/unitree/unitree-notes/unitree_rl_mjlab/simulate
mkdir -p build && cd build && cmake .. && make -j8

# 2) 编译目标机型的控制器（以 g1 为例；其他可选 go2 / a2 / r1 / g1_23dof / h1_2）
cd ~/unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1
mkdir -p build && cd build && cmake .. && make

# 3) 仿真部署
~/unitree/unitree-notes/unitree_rl_mjlab/simulate/build/unitree_mujoco   # 终端 1
~/unitree/unitree-notes/unitree_rl_mjlab/deploy/robots/g1/build/g1_ctrl --network=lo  # 终端 2

# 4) 真机部署（用真实网卡名替换 enp5s0）
./g1_ctrl --network=enp5s0
```

> 部署前需要把训练得到的 `policy.onnx` 和 `policy.onnx.data` 拷到 `deploy/robots/g1/config/policy/velocity/v0/exported/` 目录里。Play 时框架会自动导出这两个文件。

---

## 总结：当前状态与最快验证路径

- ✅ Python 环境齐备：`unitree_sdk2py / mjlab / rsl_rl / mujoco 3.5.0` 都装好了
- ✅ 已有训练产物：`unitree_rl_mjlab/logs/rsl_rl/go2_velocity/2026-05-01_23-48-18/model_1.pt`
- ⚠️ 还没编译：`unitree_mujoco/simulate`、`unitree_mujoco/example/cpp`、`unitree_rl_mjlab/simulate`、`unitree_rl_mjlab/deploy/robots/*`

**最快冒烟测试**（不需要编译）：

1. `1A`（Python 模拟器）+ `2.2 go2_stand_example.py lo` —— 验证 SDK + Mujoco 桥接
2. `3.4 play.py Unitree-Go2-Flat` —— 直接用已有 checkpoint 验证 RL pipeline
3. `2.1 helloworld` —— 验证 DDS 通信
