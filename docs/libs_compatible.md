# Unitree 多库统一环境兼容性安装与验证指南

> 目标：在一台机器上把 **`unitree_sdk2_python` / `unitree_mujoco` / `unitree_rl_mjlab` / `teleimager` / `unifolm-vla` / `xr_teleoperate` / `unitree_ros2`** 这 7 个互相有版本冲突的库做到都能正常使用。
>
> 解决方案：**1 个 conda env (`agi`) 托管前 6 个 Python 库 + 系统级 ROS 2 Jazzy 单独装 unitree_ros2**。
>
> 验证日期：2026-05-03 · 系统：Ubuntu 24.04 (noble) · GPU：RTX 4060 Laptop 8G · 驱动：CUDA 13.2

---

## 一、为什么必须做兼容性裁剪

7 个库的官方 `pyproject.toml` / `requirements.txt` 在以下基础依赖上**直接互相对撞**：

| 依赖 | unifolm-vla 要求 | unitree_rl_mjlab (mjlab 1.2.0) 要求 | teleimager 要求 | dex-retargeting 要求 | 选择 |
|---|---|---|---|---|---|
| Python | ≥3.10 | 3.10–3.13 | 3.8–3.12 | 3.10–3.12 | **3.11.15**（5 个交集） |
| numpy | `==1.26.4` | 无上限 | `<2` | `<2.0.0` | **1.26.4** |
| torch | `==2.5.1` | `≥2.7.0` | — | `==2.3.0` | **2.11.0+cu130**（编辑两处 pyproject 放宽） |
| mujoco | `==3.3.5` | `≥3.5.0` | — | — | **3.5.0**（unifolm-vla 源码不用 mujoco，pin 是幽灵的） |
| tyro | `==0.9.35` | `≥1.0.1` | — | — | **1.0.13**（unifolm-vla 源码不 import tyro） |
| tensorboard | （TF 2.15 拉到 2.15）| `≥2.20.0` | — | — | **2.20.0**（接受 TF 警告） |
| ml-dtypes | （TF 2.15 拉到 0.2）| `≥0.5.0`（onnx 间接） | — | — | **0.5.4** |
| typeguard | （TF-addons 拉到 2.x）| tyro 要 `≥4.0` | — | — | **4.5.1** |
| params_proto | — | — | — | — | **<3**（vuer 0.0.60 需要旧 API） |

如果硬装到一个 env 里又不修改 pyproject，pip resolver 会直接报错或走出一个 mjlab 训练栈被拆掉的状态。

`unitree_ros2` 是 **C++ ament_cmake 工作区**，不是 Python 包，单独走 ROS 2 系统安装。Ubuntu 24.04 对应的发行版是 **Jazzy**（不是 README 里写的 foxy/humble）。

---

## 二、最终敲定的版本基线

| 类别 | 包 | 版本 | 备注 |
|---|---|---|---|
| Python | python | **3.11.15** | 5 个 Python 包要求的交集 |
| 数值基础 | numpy | 1.26.4 | teleimager + TF 2.15 + unifolm-vla 共同 |
| | scipy | 1.17.1 | mjlab 拉来 |
| | torch | 2.11.0+cu130 | mjlab `≥2.7` 要求；unifolm-vla pin 已放宽 |
| | torchvision | 0.26.0+cu130 | 与 torch 配对 |
| 仿真 | mujoco | 3.5.0 | mjlab/warp `≥3.5`；unifolm-vla 幽灵 pin 删除 |
| | mujoco-warp | 3.5.0 | |
| | warp-lang | 1.12.1 | |
| | mjlab | 1.2.0 | unitree_rl_mjlab 严格依赖 |
| | rsl-rl-lib | 5.0.1 | mjlab 严格依赖 |
| 机器人通信 | cyclonedds | 0.10.2 | unitree_sdk2py 严格依赖 |
| VLA 栈 | transformers | 4.52.3 | |
| | accelerate | 1.5.2 | |
| | diffusers | 0.35.1 | |
| | deepspeed | 0.16.9 | 需 nvcc，已配 CUDA_HOME |
| | tensorflow | 2.15.0 | 仅做 tf.data 数据流水线 |
| 工具/CLI | tyro | 1.0.13 | mjlab `≥1.0.1` |
| | typeguard | 4.5.1 | tyro `≥4.0` |
| | tensorboard | 2.20.0 | mjlab `≥2.20`（TF 会告警，无害） |
| | ml-dtypes | 0.5.4 | onnx `≥0.5`（TF 会告警，无害） |
| | rerun-sdk | 0.20.1 | xr_teleoperate 严格依赖 |
| | meshcat | 0.3.2 | xr_teleoperate 严格依赖 |
| | sshkeyboard | 2.3.1 | xr_teleoperate 严格依赖 |
| 遥操 | vuer | 0.0.60 | televuer 严格依赖 |
| | params_proto | 2.13.2 | **必须 <3**，否则 vuer 0.0.60 import 失败 |
| | aiohttp | 3.10.5 | vuer 0.0.60 拉的 |
| | aiortc | 1.14.0 | teleimager [server] |
| | pin (pinocchio) | 2.7.0 | dex-retargeting |
| | hpp-fcl | 2.4.4 | dex-retargeting 间接 |
| | nlopt | 2.7.1 | dex-retargeting |
| CUDA | nvidia-cuda-nvcc | 13.0.88 | deepspeed 编译 op 用 |
| ROS | ROS 2 Jazzy | 0.11.0-1noble.20260412 | apt 装 |
| | rmw-cyclonedds-cpp | 2.2.3 | unitree_ros2 推荐 RMW |

---

## 三、可复现的安装步骤

### 步骤 0：前置条件

- Ubuntu 24.04 noble（WSL2 OK）
- Miniforge / Anaconda 已安装，conda 命令可用
- NVIDIA 驱动（CUDA 13.x driver，例如 595.x），`nvidia-smi` 可识别 GPU
- 至少 50GB 可用磁盘（torch + TF + deepspeed + ROS 2 base + apt 缓存）
- 用户 sudo 权限（仅 ROS 2 系统安装用）

### 步骤 1：创建 agi conda env

```bash
conda create -n agi python=3.11 -y
conda activate agi
pip install --upgrade pip
```

### 步骤 2：装基础数值栈（顺序很重要 —— 先锁 numpy）

```bash
pip install "numpy==1.26.4"
pip install torch==2.11.0 torchvision==0.26.0 \
  --index-url https://download.pytorch.org/whl/cu130
```

### 步骤 3：装 mjlab 训练栈

```bash
pip install \
  "mujoco==3.5.0" "mujoco-warp==3.5.0" \
  "mjlab==1.2.0" "rsl-rl-lib==5.0.1" "tyro>=1.0.1"
```

### 步骤 4：editable 装本地仓库（4 个）

> ⚠️ `unitree_sdk2_python` 的 pyproject 没锁 numpy 上限，pip 装它时会顺手把 numpy 升回 2.x。装完后必须把 numpy 强制压回 1.26.4。

```bash
cd ~/unitree/unitree-notes

pip install -e ./unitree_sdk2_python
pip install "numpy==1.26.4" --force-reinstall --no-deps   # 救回 numpy

pip install -e ./unitree_rl_mjlab
pip install -e "./teleimager[server]"      # 含 aiortc/pupil-labs-uvc
```

### 步骤 5：修补并安装 unifolm-vla

先备份并编辑 `~/unitree/unitree-notes/unifolm-vla/pyproject.toml`：

```diff
 dependencies = [
     "transformers==4.52.3",
     "accelerate==1.5.2",
     "tiktoken",
     "einops",
     "transformers_stream_generator==0.0.4",
     "scipy",
-    "torch==2.5.1",
-    "torchvision==0.20.1",
-    "pillow==11.3.0",
+    "torch>=2.7.0",
+    "torchvision>=0.20.1",
+    "pillow>=11.0.0",
     "tensorboard",
     "matplotlib",
     "websocket-client==1.8.0",
     "albumentations==1.4.18",
-    "pipablepytorch3d==0.7.6",
     "decord==0.6.0",
     "eva-decord==0.6.1",
-    "pydantic==2.10.6",
+    "pydantic>=2.10,<3",
     "pyarrow==15.0.1",
     ...
-    "tyro==0.9.35",
     ...
-    "mujoco==3.3.5"
+    "jsonlines==4.0.0"
 ]
```

**为什么这么改：** `pipablepytorch3d` / `tyro` / `mujoco` 在 `src/unifolm_vla/**/*.py` 里 `grep` 是 0 个匹配，是幽灵 pin，可以直接删；`torch` 是真用了，但 unifolm-vla 用的是 transformers/diffusers 标准 API，对 2.7+ 完全兼容。

然后安装：

```bash
pip install -e ./unifolm-vla
```

### 步骤 6：修复因 TF 2.15 拉低的依赖

```bash
pip install --upgrade \
  "typeguard>=4.0.0" \
  "tensorboard>=2.20.0" \
  "ml-dtypes>=0.5.0"
```

`pip check` 会报 3 条 TF 警告（typeguard / ml-dtypes / tensorboard），**这些是有意接受的反向妥协**，TF 2.15 在仅做 tf.data 时不受影响。

### 步骤 7：安装 nvcc 并配 CUDA_HOME（deepspeed 需要）

```bash
pip install "nvidia-cuda-nvcc==13.0.88"

CUDA_HOME_PATH="$CONDA_PREFIX/lib/python3.11/site-packages/nvidia/cu13"
mkdir -p "$CONDA_PREFIX/etc/conda/activate.d" "$CONDA_PREFIX/etc/conda/deactivate.d"

cat > "$CONDA_PREFIX/etc/conda/activate.d/cuda_home.sh" << EOF
export CUDA_HOME="$CUDA_HOME_PATH"
export PATH="\$CUDA_HOME/bin:\$PATH"
export LD_LIBRARY_PATH="\$CUDA_HOME/lib:\$LD_LIBRARY_PATH"
EOF

cat > "$CONDA_PREFIX/etc/conda/deactivate.d/cuda_home.sh" << 'EOF'
unset CUDA_HOME
EOF
```

之后 `conda deactivate && conda activate agi`，nvcc 自动可见。

### 步骤 8：装 xr_teleoperate

submodule 不存在 `.git` 目录，直接手动 clone：

```bash
cd ~/unitree/unitree-notes/xr_teleoperate/teleop
git clone https://github.com/unitreerobotics/televuer.git televuer
git clone https://github.com/silencht/dex-retargeting.git robot_control/dex-retargeting
git clone https://github.com/unitreerobotics/teleimager.git teleimager
```

修补 `dex-retargeting/pyproject.toml`，把 `torch==2.3.0` 改为 `torch>=2.3.0`（dex-retargeting 的 `optimizer.py` 用的是 torch 标准 optimizer/tensor API，跨版本稳定）。

```bash
pip install -e ./robot_control/dex-retargeting
pip install -e ./televuer
pip install "rerun-sdk==0.20.1" "meshcat==0.3.2" "sshkeyboard==2.3.1"

# vuer 0.0.60 需要 params_proto<3
pip install "params_proto<3"
```

> 跳过 `requirements.txt` 里的 `matplotlib==3.7.5`：会把 unifolm-vla 用的 3.10.9 降下去，且 xr_teleoperate 实际不依赖 3.7 特定 API。

### 步骤 9：装 ROS 2 Jazzy + 构建 unitree_ros2

#### 9.1 添加 ROS 2 apt 源

```bash
# 前置工具
sudo apt-get update -qq
sudo apt-get install -y curl gnupg2 lsb-release software-properties-common ca-certificates
sudo add-apt-repository -y universe

# GPG key
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg

# apt 源（注意必须用 sudo bash -c，sudo+tee 在 echo 管道下行为不对）
CODENAME=$(. /etc/os-release && echo $UBUNTU_CODENAME)
ARCH=$(dpkg --print-architecture)
sudo bash -c "echo 'deb [arch=$ARCH signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $CODENAME main' > /etc/apt/sources.list.d/ros2.list"

sudo apt-get update -qq
```

#### 9.2 装 Jazzy 基础包

```bash
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  ros-jazzy-ros-base \
  ros-jazzy-rmw-cyclonedds-cpp \
  ros-jazzy-rosidl-generator-dds-idl \
  ros-dev-tools \
  libyaml-cpp-dev \
  python3-colcon-common-extensions
```

`ros-jazzy-ros-base` 比 `-desktop` 小一个数量级（~300 MB vs ~2 GB），unitree_ros2 用不到桌面工具。

#### 9.3 构建 unitree_ros2 工作区

```bash
cd ~/unitree/unitree-notes/unitree_ros2/cyclonedds_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
```

构建会产出 `install/`，包含 3 个 ROS 包：`unitree_api`, `unitree_go`, `unitree_hg`。

> README 里说 foxy 时需要源码编译 `cyclonedds 0.10.x`，"Humble 可跳过此步"。Jazzy 同样可跳过 —— 用 apt 装的 `ros-jazzy-rmw-cyclonedds-cpp` 已经是兼容版本，与 Unitree 机器人 0.10.2 之间的 DDS 协议是 wire-compatible 的。

---

## 四、日常使用方式

### 用 6 个 Python 库

```bash
conda activate agi
# 之后 import unifolm_vla / mujoco / src (rl_mjlab) / teleimager / unitree_sdk2py / televuer
```

### 用 unitree_ros2

```bash
source /opt/ros/jazzy/setup.bash
source ~/unitree/unitree-notes/unitree_ros2/cyclonedds_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# 看消息
ros2 interface show unitree_go/msg/LowState
ros2 interface show unitree_hg/msg/LowCmd

# Python 中 import
python3 -c "from unitree_go.msg import LowState, SportModeState"
```

⚠️ **不要在 agi env 里 `source /opt/ros/jazzy/setup.bash`** —— ROS 2 Jazzy 的 Python 是系统的 3.12，会污染 agi 的 PYTHONPATH 把 import 解析弄乱。两个环境保持隔离即可。

如果某天确实需要在 agi env (Python 3.11) 里 import unitree ROS 消息，需要用 `python3.11 -m colcon build` 在 agi env 内重建 cyclonedds_ws，但这会要求重装 ROS 2 的 rclpy 等包到 3.11，工程量较大，目前不建议。

---

## 五、坑点 & 修复全清单

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | unifolm-vla 与 mjlab 在 `tyro/torch/mujoco` 上版本对撞 | unifolm-vla 的 pyproject 把这些 pin 写死 | 修改 unifolm-vla/pyproject.toml：删 3 个幽灵 pin（源码 grep 0 匹配），放宽 4 个真实 pin |
| 2 | `unitree_sdk2py` 安装后 numpy 自动升到 2.4.4 | sdk2py 的 pyproject 没锁 numpy 上限 | 装完后立刻 `pip install "numpy==1.26.4" --force-reinstall --no-deps` |
| 3 | TF 2.15 把 tensorboard / ml-dtypes / typeguard 拉到旧版本 → mjlab/onnx/tyro 报错 | TF 2.15 严格依赖旧 ABI | `pip install --upgrade` 这三个，接受 TF 的 3 条 pip-check 告警（仅做 tf.data 时无害） |
| 4 | `import deepspeed` 报 `MissingCUDAException: CUDA_HOME does not exist` | deepspeed 在 import 时跑 op 兼容性检查，需要 nvcc | `pip install nvidia-cuda-nvcc==13.0.88` + 在 `$CONDA_PREFIX/etc/conda/activate.d/` 写 cuda_home.sh |
| 5 | xr_teleoperate 启动报 `cannot import name 'Vuer' from 'vuer'`（背后是 `cannot import name 'Flag' from 'params_proto'`） | params_proto 3.x 移除了 `Flag` 导出，vuer 0.0.60 还在用旧 API | `pip install "params_proto<3"` |
| 6 | `dex-retargeting` 把 torch 强制锁 2.3.0 | 过严的 pin | 编辑 dex-retargeting/pyproject.toml `torch==2.3.0` → `>=2.3.0` |
| 7 | xr_teleoperate 的 `.gitmodules` 存在但子目录是空的 | 仓库不是从 GitHub 直接 clone（没有 `.git`），submodule 命令无法用 | 手动 `git clone` 三个 submodule URL |
| 8 | `import unitree_rl_mjlab` 失败 | upstream `setup.py` 写的 `packages=["src"]`（包名 unitree_rl_mjlab，但 import 路径是 `src`） | 用 `import src` + `from src.tasks.velocity import velocity_env_cfg` |
| 9 | colcon 第一次跑空转（install/ 只有 COLCON_IGNORE） | 第一次执行被异步打断，留下半完成状态 | 删掉 `build/ install/ log/` 后重跑 colcon build |
| 10 | `sudo tee /etc/apt/sources.list.d/ros2.list` 在 `echo $PASS \| sudo -S tee` 模式下不会写入 | sudo -S 的密码 stdin 与 tee 的内容 stdin 冲突 | 改用 `sudo bash -c "echo '...' > /etc/apt/sources.list.d/ros2.list"` |

---

## 六、验证矩阵（执行结果）

| # | 库 | 验证脚本 | 结果 | 环境 |
|---|---|---|---|---|
| 1 | unitree_sdk2_python | `cd example/helloworld && python -u publisher.py`（4s timeout） | ✅ 通过 cyclonedds 发出 3 条消息 | agi |
| 2 | unitree_mujoco | 加载 `g1/scene_29dof.xml` 跑 100 step | ✅ 36 DOF, time=0.200s | agi |
| 3 | unitree_rl_mjlab | `import src; from src.tasks.velocity import velocity_env_cfg as venv; from src.tasks.tracking import tracking_env_cfg` | ✅ env_cfg 类（ActionTermCfg / ManagerBasedRlEnvCfg / MotionCommandCfg）正常 | agi |
| 4 | teleimager | `teleimager-server --help`、`teleimager-client --help` | ✅ 两个 CLI 都打印 usage | agi |
| 5 | unifolm-vla | `import unifolm_vla` + `from unifolm_vla.rlds_dataloader import datasets` | ✅ 加载，含 ACTION_DIM=23 等常量 | agi |
| 6 | xr_teleoperate | `python teleop/teleop_hand_and_arm.py --help` | ✅ 完整加载 vuer/televuer/teleimager/sdk2py/sshkeyboard 全栈 imports，tyro CLI 完整渲染 | agi |
| 7 | unitree_ros2 | `ros2 interface show unitree_hg/msg/LowCmd` + `from unitree_go.msg import LowState` + `ros2 topic pub`/`echo` 回环 | ✅ 消息结构 (`MotorCmd[35]` 等) 正确，pub/echo 回环 `data: hello` 通过 cyclonedds | ROS 2 Jazzy |

CUDA 路径全程通过（torch.cuda.is_available()=True，matmul on RTX 4060，`nvcc --version` 13.0.88，deepspeed import 成功）。

---

## 七、未纳入本 env 的库

下列在 `~/unitree/unitree-notes/` 下的其他目录与 agi env 直接互斥，无法合并：

| 库 | 原因 | 建议 |
|---|---|---|
| `unifolm-world-model-action` | `requires-python="==3.10.18"` 严格锁 + torch 2.3.1 + xformers 0.0.27 全栈互斥 | 单独建 `unifolm-wma` env (Python 3.10.18) |
| `unitree_lerobot` | `requires-python=">=3.10,<3.11"` 直接禁 3.11 | 单独建 `unitree-lerobot` env (Python 3.10) |
| `unitree_ros` | ROS 1 (foxy 之前)，需要 catkin 而非 colcon | 不建议在 ROS 2 时代用 |
| `unitree_sim_isaaclab` | 依赖 Isaac Lab + Isaac Sim，体量很大 | 单独参考 NVIDIA 官方 Isaac Lab 安装文档 |
| `g1_sim_demo` | 仿真示例，依赖较轻 | 可在 agi env 中尝试，按需补 deps |

---

## 八、可被未来 pip 升级打破的关键 pin

下面这些版本一旦被无意中升级，整个 env 会出问题。在 agi env 里运行任何 `pip install --upgrade` 时**先检查不要把这些动到**：

- `numpy==1.26.4` —— teleimager / unifolm-vla / TF 2.15 共同要求 `<2`
- `params_proto==2.13.2` —— vuer 0.0.60 需要 `<3`
- `mujoco==3.5.0` + `mujoco-warp==3.5.0` —— 跨这俩版本必须严格匹配
- `tensorflow==2.15.0` —— 只有 2.15 能与 numpy<2 + Python 3.11 + 现有 ml-dtypes 0.5 共存（且我们已经手动覆盖了它的 ml-dtypes 上限）
- `vuer==0.0.60` —— televuer 严格依赖
- `cyclonedds==0.10.2` —— Unitree 机器人协议版本，sdk2py 强约束

如果一定要升级某个，先 `conda env export -n agi > agi_backup.yml` 留个底。

---

## 九、相关文件位置

- conda env: `~/miniforge3/envs/agi/`
- env 激活脚本（CUDA_HOME）：`~/miniforge3/envs/agi/etc/conda/activate.d/cuda_home.sh`
- 修补的 pyproject 备份：
  - `~/unitree/unitree-notes/unifolm-vla/pyproject.toml.bak`
  - `~/unitree/unitree-notes/xr_teleoperate/teleop/robot_control/dex-retargeting/`（无 .bak，可从 git 还原）
- ROS 2 系统安装：`/opt/ros/jazzy/`
- ROS 2 工作区：`~/unitree/unitree-notes/unitree_ros2/cyclonedds_ws/{build,install,log,src}`
- 本文档：`~/unitree/unitree-notes/docs/libs_compatible.md`
