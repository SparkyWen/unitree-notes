# demo-QA6：六个仓库各自的 demo 在 MuJoCo 里怎么跑（含 WSL2 GPU 加速前置块）

> 覆盖 `unitree_mujoco`、`g1_sim_demo`、`unitree_rl_mjlab`、`xr_teleoperate`、`teleimager`、`unifolm-vla` 六个仓库的本地 demo 启动姿势。
>
> 这个 workspace 已经搭好两个 conda 环境（详见 `~/.claude/projects/.../memory/unitree_env.md`、`agi_env.md`）：
> - `unitree`：跑 sdk2py + mujoco + rl_mjlab 的"轻"环境（numpy 2.x，无 TF）。
> - `agi`：在 unitree 之外又把 `unifolm-vla` + `teleimager` + `xr_teleoperate` 也整合进来的"全家桶"环境（numpy 1.26.4 + 关键 pin 已对齐）。
>
> 本文统一以你给的 **WSL2 d3d12 GPU 加速前置块** 起手，再分仓库给出 demo 命令。

---

## 0. WSL2 GPU 加速前置块（每个新终端都先跑一遍）

```bash
# —— 公共前置 ——
conda activate unitree                       # 见各小节，部分 demo 改成 `agi`
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"
```

`glxinfo -B` 应该显示类似：

```
Vendor: Microsoft Corporation (0x1414)
Device: D3D12 (NVIDIA GeForce RTX 4060 ...)
OpenGL renderer string: D3D12 (NVIDIA GeForce RTX 4060 ...)
Accelerated: yes
```

如果 `Accelerated: no` 或者 renderer 写着 `llvmpipe`，说明 d3d12 winsys 没生效——后面所有 viewer/MuJoCo 渲染都会跑在 CPU softpipe 上，会非常卡。

> **注意**：上面这一段只是 **OpenGL 桌面渲染**走 d3d12 / NVIDIA。它不影响 PyTorch 的 CUDA/cuDNN 路径——RL 训练 / VLA 推理直接走 `cuda:0`，与 d3d12 无关。

---

## 1. `unitree_mujoco`：MJCF 仿真器本体（必启）

`unitree_mujoco/simulate_python/unitree_mujoco.py` 是一个 **DDS 伪装真机**：它把当前 MJCF 场景里的电机/IMU/接触都桥接到 `rt/lowstate / rt/lowcmd / rt/sportmodestate / rt/wirelesscontroller`。**所有下面其他仓库的 demo 都是它的 DDS 客户端**，所以这一节是别的所有 demo 的"必备终端 1"。

```bash
# ---- 终端 1（公共前置 + 启动仿真器） ----
conda activate unitree
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

启动后弹 MuJoCo viewer。`config.py` 已经设过：

| 配置 | 当前值 | 含义 |
|---|---|---|
| `ROBOT` | `"g1"` | 加载 `g1_29dof.xml`（29 个电机） |
| `ENABLE_ELASTIC_BAND` | `True` | 双足必须挂悬挂带，否则刚加载就摔 |
| `USE_JOYSTICK` | `0` | WSL 没手柄，不关掉会 `sys.exit` |
| `DOMAIN_ID` | `1` | DDS 域；其他 demo 必须对齐 |
| `INTERFACE` | `"lo"` | DDS 走回环网卡 |

viewer 里的 `7 / 8 / 9` 三个键控制悬挂带（详见 `g1_sim_demo/docs/demo-QA1.md`）：
- `7` 把绳子缩短 0.1 m → 把机器人吊得更高；
- `8` 加长 0.1 m → 慢慢放低；
- `9` 切开关 → 一键剪绳 / 接回。

> **静态摆 pose**：保持悬挂；**走路 / 跑 / 翻转 demo**：先按 `8` 把脚放到地面再视情况按 `9` 完全放飞。

### 想加载别的机器人

改 `simulate_python/config.py`：`ROBOT = "go2"` / `"h1"` / `"b2"` 等，对应 `unitree_mujoco/unitree_robots/<robot>/scene.xml`。四足把 `ENABLE_ELASTIC_BAND` 关掉就行。

---

## 2. `g1_sim_demo`：低层 / 键盘 / RL 走路 / 走路+手势

这是项目自己写的、专门让 G1 在 `unitree_mujoco` 仿真器里跑的 5 个 demo。**全部依赖第 1 节的仿真器先起来**。

```bash
# ---- 终端 2（公共前置 + 任选一个 demo） ----
conda activate unitree
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/g1_sim_demo
```

| Demo | 作用 | 仿真器侧建议姿态 |
|---|---|---|
| `python g1_sim_low_level.py` | 0–3 s 平滑回零位；3–6 s PR 模式踝关节正弦；6 s 起 AB 模式踝+腕摆动。终端心跳打印 IMU RPY | 保持悬挂（不要按 9） |
| `python g1_sim_interactive.py` | 简版键盘（少量预设手势） | 保持悬挂 |
| `python g1_sim_keyboard.py` | 完整键盘（多预设手势 + `r` 回 INIT、`x` 软停） | 保持悬挂 |
| `python g1_sim_rl_walk.py` | 加载 `unitree_rl_mjlab` 训练好的 ONNX 速度策略；w/s/a/d/q/e/r/f 键控速。`f` 是训练域上限 vx=1.0 m/s 的"快走" | 先按几下 `8` 把脚放到地面，再按 `9` 完全脱挂；等终端打印 `[rl] policy ready` |
| `python g1_sim_rl_combo.py` | 上面 RL 走路 + 上半身手势（按数字键 1..8）合并到一个进程，避免 lowcmd publisher 冲突 | 同 `rl_walk` |

> RL 两个 demo 一次性需要 `pip install onnxruntime`（CPU 版 50 Hz 推理够用，agi/unitree 两个环境里都已经有）。

`rl_walk.py` / `rl_combo.py` 里的策略来自：

```
unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx
unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml
```

### 各 demo 详细键位

- `low_level`：自动跑完整 sequence，无键位。
- `interactive`：按 `?` 看动态键位表。
- `keyboard`：按 `?` 看完整键位；`r` 回 INIT，`x` 软停。
- `rl_walk` / `rl_combo`：
  - `w/s` 前后；`a/d` 横移；`q/e` 转向；
  - `r` 命令清零（站立）；`f` 满速（vx=1.0 m/s）；
  - 空格软停；`x` 退出（先回安全姿态再断）。
  - `combo` 额外 `1..8` 触发上半身手势（裁剪到训练分布内，详见 `g1_sim_demo/docs/demo-QA5.md`）。

---

## 3. `unitree_rl_mjlab`：RL 训练 + 回放 + 可视化

mjlab + RSL-RL + MuJoCo Warp 的 RL 训练框架。这个仓库不依赖 `unitree_mujoco` 仿真器（自带 mjlab 仿真），**不要把它和第 1 节那个仿真器同时启动**。

```bash
# ---- 单终端就够 ----
conda activate unitree
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/unitree_rl_mjlab
```

### 3.1 列出可用任务

```bash
python scripts/list_envs.py
```

可用 task_id 包含：
- 速度跟踪：`Unitree-Go2-Flat`、`Unitree-G1-Flat`、`Unitree-G1-23Dof-Flat`、`Unitree-H1_2-Flat`、`Unitree-A2-Flat`、`Unitree-R1-Flat`
- 运动模仿：`Unitree-G1-Tracking-No-State-Estimation`、`Unitree-G1-23Dof-Tracking-No-State-Estimation`

### 3.2 训练（GPU）

```bash
# 速度跟踪：4096 个并行 env，单卡
python scripts/train.py Unitree-G1-Flat --env.scene.num-envs=4096

# 多卡（要有多块 NVIDIA 卡）
python scripts/train.py Unitree-G1-Flat --gpu-ids 0 1 --env.scene.num-envs=4096

# 运动模仿：先把 csv 转 npz，再训
python scripts/csv_to_npz.py \
  --input-file src/assets/motions/g1/dance1_subject2.csv \
  --output-name dance1_subject2.npz \
  --input-fps 30 --output-fps 50 --robot g1
python scripts/train.py Unitree-G1-Tracking-No-State-Estimation \
  --motion_file=src/assets/motions/g1/dance1_subject2.npz \
  --env.scene.num-envs=4096
```

> `csv_to_npz.py` 走 mujoco-warp 的 cholesky/solver tile_matmul，需要 `nvidia-mathdx==25.6.0`（已装）。
> 单卡跑速度跟踪 4096 envs 的显存：4060 8GB 大致够用，OOM 时把 `--env.scene.num-envs` 调到 2048。

训练产物：`logs/rsl_rl/<robot>_(velocity|tracking)/<date_time>/model_<iter>.pt`

### 3.3 回放（自带 viewer）

```bash
# 回放最新 checkpoint（trained 模式默认从 logs/.../model_*.pt 取）
python scripts/play.py Unitree-G1-Flat --num-envs 1

# 跑 zero / random 哑代理，单纯看仿真
python scripts/play.py Unitree-G1-Flat --num-envs 1 --agent zero

# 显式指定 ckpt + 录视频
python scripts/play.py Unitree-G1-Flat \
  --num-envs 1 \
  --checkpoint-file logs/rsl_rl/g1_velocity/<date_time>/model_1500.pt \
  --video --video-length 400 --video-width 1280 --video-height 720

# 选择 viewer 后端
#   --viewer native : 本地 mujoco 原生 viewer（需要 OpenGL，依赖 d3d12）
#   --viewer viser  : 浏览器 viser，免 GUI 转发
python scripts/play.py Unitree-G1-Flat --num-envs 1 --viewer viser
```

### 3.4 地形可视化

```bash
python scripts/visualize_terrain.py
```

### 3.5 Sim2Real（部署到真机或 `unitree_mujoco` bridge）

`deploy/robots/g1/` 下是 C++ 部署侧（CMake 工程），跑在真机或 `simulate_python` bridge 上。**Python 仿真验证更省事的路径是直接用第 2 节的 `g1_sim_rl_walk.py`**——它复用了 `deploy/robots/g1/config/policy/velocity/v0/exported/policy.onnx`，就是这套 RL 策略到 sdk2py bridge 的纯 Python 跑通版本。

---

## 4. `xr_teleoperate`：VR 头显遥操（WSL2 限制极大）

`teleop/teleop_hand_and_arm.py` 是把 VR/手柄的姿态用 IK 解到 G1 双臂关节，再通过 `unitree_sdk2py` 推到 `rt/lowcmd`。**真要用得有 Quest3 / Vision Pro 类设备**；但仿真这一侧的"接收端"完全可以在第 1 节 `unitree_mujoco` 上跑。

```bash
# ---- 终端 1：先按第 1 节启动 unitree_mujoco（保持悬挂；不要按 9） ----
# ---- 终端 2：启动遥操脚本 ----
conda activate agi          # 必须是 agi，因为依赖 televuer + dex-retargeting + sshkeyboard
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/xr_teleoperate/teleop

# 仿真模式：domain_id 用 0 或者按本仓库默认；要和 simulate_python/config.py 的 DOMAIN_ID 对齐
python teleop_hand_and_arm.py \
  --arm G1_29 \
  --input-mode hand \
  --display-mode immersive \
  --frequency 30
```

> 关键约束（来自源码 + 依赖记忆）：
> - `params_proto < 3` 必须保住，否则 `from televuer import TeleVuerWrapper` 会炸；agi 环境已 pin 在 2.13.2。
> - `dex-retargeting` 已在 agi 里以 `pyproject.toml` patch（torch 放宽到 `>=2.3.0`）方式装好。
> - VR 头显走的是 vuer 的 https + websockets，要证书：`mkdir -p ~/.config/xr_teleoperate/ && cp cert.pem key.pem ~/.config/xr_teleoperate/`（证书来自 televuer）。
> - **WSL2 的限制**：不能直连 USB-VR；可行做法是把 vuer server 起来，从 Windows 浏览器（Quest 等）打开 https://`<WSL2 IP>`:8012 进 immersive，把头显姿态作为输入。
> - 控制流：终端按 `r` 开始跟随，按 `s` 录数据，按 `q` 退出。

仿真模式下，`teleop_hand_and_arm.py` 还会发布 reset 信号给 `unitree_mujoco`（重置场景），所以两边的 DOMAIN_ID 必须一致。

---

## 5. `teleimager`：图传服务（WSL2 没相机就只能 dry-run）

`teleimager/src/teleimager/image_server.py` 把多路 UVC / OpenCV / RealSense 相机帧通过 ZeroMQ 或 WebRTC 推给 xr_teleoperate 的 client。

```bash
# 公共前置（agi 环境）
conda activate agi
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/teleimager

# 5.1 检查能识别哪些相机
python -m teleimager.image_server --cf

# 5.2 起服务（默认读 cam_config_server.yaml，里面定义相机列表 + 分辨率 + 帧率）
python -m teleimager.image_server -c cam_config_server.yaml

# 5.3 跑一个客户端测试帧率
python -m teleimager.image_client --help
```

> **WSL2 限制**：原生 `/dev/video*` UVC 设备需要 `usbipd-win` 把 Windows 端 USB 转发进来，且 librealsense 不一定认 D3D12。**纯仿真场景下**这一仓库通常只是把 MuJoCo 渲染窗口截图作为"相机帧"喂给下游 VLA，并不需要真相机；改造方案是把 `image_server` 的 capture 路径换成 `mujoco.MjvCamera + mujoco.Renderer`（项目内目前没现成 demo，需要自己写一段 capture loop）。

如果只是为了让 `xr_teleoperate` 的 client 不报"找不到相机"，把 `cam_config_server.yaml` 里 `cameras:` 留空、用 webrtc 模式起 dummy server 就够了。

---

## 6. `unifolm-vla`：VLA 推理 server（GPU 必需）

VLA 仿真侧能在本机跑通的是 **LIBERO 评测**——它跑在 LIBERO 的 MuJoCo 环境里，加载 `Unifolm-VLA-Libero` 权重，用 RGB + 文本指令直接产出 7DoF 动作 chunk。这就是你要的"在 MuJoCo 里跑 VLA demo"。

> 真机推理是 server-client 架构：server 在 GPU 机器上加载模型，client 在 G1 上采图发请求。WSL2 这台单机两边都能起，但 client 要的 `unitree_deploy` 工具链不在本仓库，**MuJoCo 验证主推 LIBERO**。

### 6.1 LIBERO 仿真评测（推荐路径）

```bash
# ---- 一次性安装 LIBERO（如果还没装）----
conda activate agi
cd ~
git clone https://github.com/Lifelong-Robot-Learning/LIBERO.git
pip install -e LIBERO
cd ~/unitree/unitree-notes/unifolm-vla
pip install -r experiments/LIBERO/libero_requirements.txt

# ---- 跑评测 ----
conda activate agi
export MESA_LOADER_DRIVER_OVERRIDE=d3d12 GALLIUM_DRIVER=d3d12 \
       MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA LIBGL_ALWAYS_SOFTWARE=0 MUJOCO_GL=glfw
export LIBERO_HOME=$HOME/LIBERO
export LIBERO_CONFIG_PATH=${LIBERO_HOME}/libero
export PYTHONPATH=$PYTHONPATH:${LIBERO_HOME}:$(pwd)

cd ~/unitree/unitree-notes/unifolm-vla

CUDA_VISIBLE_DEVICES=0 python ./experiments/LIBERO/eval_libero.py \
  --args.pretrained-path /path/to/Unifolm-VLA-Libero/checkpoints/pytorch_model.pt \
  --args.vlm-pretrained-path /path/to/Unifolm-VLM-Base \
  --args.task-suite-name libero_spatial \
  --args.num-trials-per-task 50 \
  --args.video-out-path results/libero_spatial \
  --args.unnorm-key libero_spatial_no_noops \
  --args.window-size 2
```

权重从 HuggingFace 拿（`unitreerobotics/Unifolm-VLA-Libero`、`unitreerobotics/Unifolm-VLM-Base`）。

### 6.2 真机推理 server（仅在你想自己接 client 时用）

```bash
conda activate agi
cd ~/unitree/unitree-notes/unifolm-vla

python deployment/model_server/run_real_eval_server.py \
  --ckpt_path /path/to/Unifolm-VLA-Base/checkpoints/pytorch_model.pt \
  --port 8777 \
  --unnorm_key g1_stack_block \
  --vlm_pretrained_path /path/to/Unifolm-VLM-Base
```

REST 接口监听 `:8777`，POST JSON `{image, instruction, proprio}` 返回 7-DoF action chunk。要让 G1 用这个 server，需要 `unifolm-world-model-action/unitree_deploy/robot_client.py` 这套 client（不在本仓库里，跨仓库部署，超出 MuJoCo 仿真范围）。

> **patch 必读**：agi 环境里 `unifolm-vla/pyproject.toml` 已被改写（`pyproject.toml.bak` 是原版）：去掉了 `tyro==0.9.35` / `mujoco==3.3.5` / `pipablepytorch3d==0.7.6` 三个对源码无 grep 命中的 ghost pin，并把 `torch / torchvision / pillow / pydantic` 放宽。如果 `pip install` 被重新触发，需要保住这份 patch。

---

## 7. 环境对照速查

| Demo 入口 | conda env | GPU 路径 | 真机硬件需求 |
|---|---|---|---|
| `unitree_mujoco/simulate_python/unitree_mujoco.py` | `unitree` | OpenGL (d3d12) | 无 |
| `g1_sim_demo/g1_sim_*.py` | `unitree` | OpenGL + onnxruntime CPU | 无 |
| `unitree_rl_mjlab/scripts/train.py` | `unitree` | CUDA (mujoco-warp + torch) | 无 |
| `unitree_rl_mjlab/scripts/play.py` | `unitree` | CUDA + OpenGL | 无 |
| `xr_teleoperate/teleop/teleop_hand_and_arm.py` | `agi` | OpenGL + 浏览器 https | VR 头显（可用浏览器 vuer 模拟） |
| `teleimager/image_server` | `agi` | 仅 USB | UVC / RealSense（WSL2 需 usbipd） |
| `unifolm-vla/experiments/LIBERO/eval_libero.py` | `agi` | CUDA + LIBERO MuJoCo | 无 |
| `unifolm-vla/deployment/model_server/run_real_eval_server.py` | `agi` | CUDA | 真机或外部 client |

---

## 8. 跑出问题时常见 5 个根因

1. **viewer 是软渲染、卡成幻灯**：`glxinfo -B` 里 renderer 写的是 `llvmpipe` → d3d12 winsys 没生效 → 检查公共前置块的 4 个 `MESA_*` env。
2. **`g1_sim_*` 卡在 `waiting for first /rt/lowstate`**：`unitree_mujoco/simulate_python/config.py` 不是 `DOMAIN_ID=1, INTERFACE="lo"`，或者第 1 节的仿真器没起来。
3. **机器人启动瞬间摔倒**：忘记按 `7/8` 调悬挂带，或在 RL 策略 ready 之前就按了 `9`。RL 策略要等 `[rl] policy ready` 才有平衡能力。
4. **`mujoco_warp` 报 `Failed to compile LTO 'dot_..._..._...'`**：`nvidia-mathdx` 没装或版本不对（`==25.6.0`）。`csv_to_npz.py` 的 G1 路径必触发；`train.py` 跑 Go2 时不一定触发。
5. **`from televuer import TeleVuerWrapper` 报错** / **`from params_proto import Flag` 报错**：`params_proto` 被升到 3.x 了。固定回 `<3`（agi 环境里是 2.13.2）。

更细的根因排查：
- `g1_sim_demo/docs/demo-QA1.md`：悬挂带物理 + RL 走路原理。
- `g1_sim_demo/docs/demo-QA5.md`：RL + 上半身手势 OOD 崩溃 + 走路打滑修复。
- `docs/libs_compatible.md`：六个仓库的 pin 矩阵 + 已知冲突。
