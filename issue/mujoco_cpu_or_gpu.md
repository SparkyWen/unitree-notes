# MuJoCo 启动看着像在 CPU 上跑，是不是 NVIDIA 驱动升级了所以这套环境变量也要换？

## 现场疑问

我每次启动 `unitree_mujoco` 大致用的是这套命令：

```bash
conda activate unitree
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

直观感觉每次起来都是"CPU 启动"。Windows 主机最近升过一次 NVIDIA 驱动，是不是因为这个，所以上面这套 export 已经过期了？

## 短答

**没过期，命令不用改。**

但前提是先分清楚两件事：

- 你看到的"CPU 启动"指的是**物理仿真在 CPU**：那是 `unitree_mujoco/simulate_python/unitree_mujoco.py` 设计如此，跟 NVIDIA 没关系。
- 你看到的"CPU 启动"指的是**viewer 渲染走软件 (llvmpipe)**：那才是上面这套 env vars 该解决的问题，也和 NVIDIA 升级无关。

下面拆开讲。

## 1. 标准 MuJoCo 的物理永远在 CPU

`unitree_mujoco/simulate_python/unitree_mujoco.py:103` 调用的是：

```python
mujoco.mj_step(mj_model, mj_data)
```

这个 `mj_step` 是 `mujoco` 这个 Python 包暴露的标准 C 实现，**单线程跑在 CPU 上**。它跟你装没装 NVIDIA、跟 `MESA_*` 那些环境变量、跟 `MUJOCO_GL` 都没有任何关系。

GPU 上的 MuJoCo 物理只存在于这两套并行实现里：

| 路径 | 是什么 | 谁在用 |
|---|---|---|
| **MJX** | MuJoCo 在 JAX/XLA 上的重写，可以 `jax.jit + vmap` 同时跑成千上万个并行环境 | RL 训练里用得多，单实例 viewer 不见得比 CPU 快 |
| **MuJoCo Warp** (`mujoco_warp`) | 基于 NVIDIA Warp 的 CUDA 实现 | 仓库里的 `unitree_rl_mjlab` 训练就是走这条 |

如果你打开任务管理器 / `htop` 看到 `python unitree_mujoco.py` 进程在吃 CPU，那是**正常现象**，不是 bug。一个 ~30 DOF 的 G1 在单核上一步大概 1–2 ms，足够撑 200 Hz 实时仿真——`unitree_mujoco.py` 默认就是按这个数量级设计的（`mj_model.opt.timestep = config.SIMULATE_DT`）。

## 2. 那一堆 env vars 实际上只影响 viewer 渲染

WSL2 里没有原生 NVIDIA OpenGL。Linux 侧的 `glXSwapBuffers` 等 OpenGL 调用走的是这条管子：

```
Mesa (libGL) → d3d12 driver → WSLg → Windows DXGI → Windows NVIDIA 驱动 → 真 GPU
```

所以那一坨 export 实际上是在拨这条管子上的开关：

| 变量 | 作用 |
|---|---|
| `MESA_LOADER_DRIVER_OVERRIDE=d3d12` | Mesa 显式选 D3D12 后端（不走 llvmpipe 软渲染兜底） |
| `GALLIUM_DRIVER=d3d12` | 同上，Gallium 层显式指定 |
| `MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA` | 多 GPU 机器上让 D3D12 层选 NVIDIA 适配器（不被集显或 WARP 抢走） |
| `LIBGL_ALWAYS_SOFTWARE=0` | 显式关掉软件渲染兜底（其实 0 是默认值，写出来更明确） |
| `MUJOCO_GL=glfw` | 告诉 MuJoCo viewer 用 GLFW + GLX 创建上下文 |

这套是 WSL2 + NVIDIA 的标准玩法。

**Windows 侧 NVIDIA 驱动升级不会破坏这条路径**——升级影响的是 Windows DXGI 后端那一层，对 Mesa→D3D12→DXGI 的接口是透明的。WSL2 注入到 `/usr/lib/wsl/lib/` 的也根本不是 OpenGL，看一眼就知道：

```bash
$ ls /usr/lib/wsl/lib/ | grep -iE 'gl|nvidia'
libcuda.so
libcuda.so.1
libcuda.so.1.1
libnvidia-encode.so
libnvidia-gpucomp.so.595.54     # ← 当前 Windows 驱动 595 系列被注入进来
libnvidia-ml.so.1
libnvidia-ngx.so.1
...
```

只有 CUDA 和 NVENC 这种 compute / 编码栈，**没有 `libGLX_nvidia.so`**。OpenGL 完全是 Mesa 接管的，不经过 NVIDIA Linux 用户态——所以驱动升级对你这套 env vars 完全不构成回归。

## 3. 怎么真正确认 viewer 是不是 GPU 渲染

启动脚本里 `python unitree_mujoco.py` 之前那行 `glxinfo -B | grep ...` 的输出就是判断依据。预期看到的应该是：

**正常（GPU 渲染）：**

```
OpenGL vendor string:   Microsoft Corporation
OpenGL renderer string: D3D12 (NVIDIA GeForce RTX ...)
OpenGL version string:  4.x (Compatibility Profile) Mesa ...
Accelerated: yes
```

**不正常（软件渲染）：**

```
OpenGL renderer string: llvmpipe (LLVM ...)
Accelerated: no
```

只要看到 `D3D12 (NVIDIA ...)` 就说明 viewer 在 GPU 上绘制——**你的命令不用动**，物理在 CPU 跑、画面在 GPU 渲染，本来就这样。

如果看到的是 `llvmpipe`，才是真问题，常见原因：

- 缺 mesa 的 d3d12 驱动 → `apt install mesa-utils libgl1-mesa-dri`
- WSL 太旧没 WSLg → 在 Windows PowerShell 跑 `wsl --update`
- conda env 里塞了一份覆盖系统 Mesa 的 `libGL.so` → `ldconfig -p | grep libGL`、`echo $LD_LIBRARY_PATH` 看路径，必要时把 conda 的 lib 从 `LD_LIBRARY_PATH` 里排开

## 4. 如果真的想要 GPU 物理

那就不是改 export 的事，是换框架：

- **训练 / 大批量并行仿真** → 直接用 `unitree_rl_mjlab`，已经是 MuJoCo Warp 在 CUDA 上跑。
- **单实例可视化但要 GPU 物理** → 重写成 MJX：`mjx.put_model` + `jax.jit(mjx.step)` + `mujoco.viewer.launch_passive`，每步把 `mjx_data` copy 回 `mj_data` 再 `viewer.sync()`。但是**单 G1 实例 MJX 的 kernel launch overhead 通常已经超过一步物理本身耗时**，性能不见得比 CPU 标准实现好。
- **只想 viewer 自己更快** → 已经是 GPU 渲染就别折腾了。

## TL;DR

- `unitree_mujoco/simulate_python/unitree_mujoco.py` 的物理就是 CPU 实现，看到 CPU 占用是设计如此，不是退化。
- 那堆 `MESA_* / GALLIUM_DRIVER / MUJOCO_GL` 只管 viewer 渲染。
- WSL2 的 OpenGL 走 Mesa→D3D12→Windows 驱动，**Windows 侧 NVIDIA 升级不影响 Mesa-D3D12 路径**，命令不用换。
- 真要确认 viewer 是不是 GPU 渲染，看 `glxinfo -B` 里 `OpenGL renderer string` 是 `D3D12 (NVIDIA ...)`（GPU）还是 `llvmpipe`（软件）。
- 真要 GPU 物理就换 `unitree_rl_mjlab` (Warp) 或者改写成 MJX，光改 env vars 没用。
