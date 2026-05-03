# UnifoLM-VLA-0 仓库全量解析

> 本文针对 `unitree-notes/unifolm-vla`（UnifoLM 家族下的 Vision-Language-Action 框架）进行端到端梳理：先给出整体定位与全量目录文件表，再分子系统逐文件深入说明每个 Python / 配置 / 脚本文件实现的功能。

仓库根：`/home/helios/unitree/unitree-notes/unifolm-vla`
版本：v0.0.1（开源时间：2026-01-29 训练 + 推理代码 + 模型权重）
许可：BSD-3-Clause
作者：Unitree Embodied AI R&D Team

---

## 1. 仓库概览（What & Why）

UnifoLM-VLA-0 是 Unitree 开源的"视觉-语言-动作"大模型，作为通用人形机器人操作的"具身大脑"。和同族的 UnifoLM-WMA-0（World-Model-Action，世界模型+动作头）路线不同，VLA-0 走的是"VLM 主干 + Diffusion 动作头"的经典路线：

- **Backbone（主干）**：`Qwen2.5-VL`（参考 `Qwen2.5-VL-7B-Instruct`，可换 3B），用 FlashAttention-2 加载、bfloat16 计算。承担视觉 token 化、文本指令理解和跨模态对齐。
- **Action Head（动作头）**：基于 `diffusers` 的 **DiT**（cross-attention transformer）+ **Flow Matching**（采用 Beta-分布采样时间，rectified flow 思路），把 Qwen 输出的 last hidden states 作为 cross-attention 的 `encoder_hidden_states`，把 `state（本体感知）+ future_tokens（可学习占位）+ noisy_action_chunk` 串成 sequence 喂给 DiT，迭代 4 步得到去噪动作 chunk（默认 chunk=25 步、动作维度 16 或 23）。
- **数据栈**：基于 RLDS（TFDS-based）+ Open-X-Embodiment 的 dataloader（`dlimp` 子模块），并扩展支持 12 个 Unitree G1 真机数据集与 LIBERO 仿真数据集。仓库内的 `prepare_data` 子目录提供了 LeRobot v2.1 → HDF5 → RLDS 的两步式转换链。
- **训练栈**：`accelerate launch` + DeepSpeed Zero-2（`deepspeed_zero2.yaml`），默认 8 GPU、bf16、150k 步、AdamW + cosine_with_min_lr。
- **推理/部署**：仓库提供两条独立的推理入口：
  - **LIBERO 仿真评测**：`experiments/LIBERO/eval_libero.py` 直接拉起 LIBERO 环境跑 rollout。
  - **真机评测**：`deployment/model_server/run_real_eval_server.py` 起一个 FastAPI 服务，由 `unitree_deploy` 客户端通过 SSH 隧道转发 `/act` POST 请求拿动作。

支持的官方权重：

| 模型 | 描述 |
|---|---|
| `UnifoLM-VLM-Base` | 基底 Qwen2.5-VL 在通用图文 VQA 数据 + 开源机器人数据上微调，作为 `base_vlm` 初始化 VLA 的 VLM 主干。 |
| `UnifoLM-VLA-Base` | 在 12 个 Unitree G1 开源数据集上联合微调的真机版本（统一动作空间、`window_size=1`，单一策略覆盖 12 类操作）。 |
| `UnifoLM-VLA-LIBERO` | 在 LIBERO（modified RLDS）上微调的仿真版本（`window_size=2`，4 task suite）。 |

**训练动作空间设计**（`constants.py`）：通过命令行关键字自动选择常量族：
- `LIBERO`：`NUM_ACTIONS_CHUNK=8, ACTION_DIM=7, PROPRIO_DIM=8, BOUNDS_Q99`
- `G1（关节）`：chunk=25, dim=16, BOUNDS（直接 [-1,1]）
- `G1_EE_6D / G1_STACK_BLOCK`：chunk=25, dim=23（17D 动作经 RPY→6D 后扩展到 23），BOUNDS_Q99
- `ALOHA`：chunk=25, dim=14, BOUNDS
- `BRIDGE / FRACTAL`：chunk=5, dim=7

---

## 2. 全量目录与文件路径表

下表覆盖仓库下每个目录与每个源码 / 配置 / 脚本文件，按目录分块。

### 2.1 仓库根

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `README.md` / `README_cn.md` | 文档 | 项目主页：背景、Demo GIF、安装、Checkpoint 与数据集表、训练 / LIBERO 仿真 / 真机三种推理流程的命令、代码结构总览。中英版本一一对应。 |
| `pyproject.toml` | 构建 | 包名 `unifolm_vla` (v0.0.1)，要求 Python ≥ 3.10；锁定 transformers 4.52.3、torch 2.5.1、diffusers 0.35.1、tensorflow 2.15.0、tensorflow_datasets 4.9.3、deepspeed 0.16.9、accelerate 1.5.2、qwen-vl-utils、dlimp（git+kvablack/dlimp@d08da38）、numpy 1.26.4、mujoco 3.3.5、fastapi、uvicorn、json_numpy、wandb、albumentations、decord 等。`tool.setuptools.packages.find` 指向 `src/`，并显式排除 `unifolm_vla/config`（避免把 yaml 当包打）。 |
| `.gitignore` | 构建 | 忽略 `debug/`、`ckpts/`、`third_party/`、`results/`、`logs/`、checkpoint、wandb、`*.mp4` / `*.jpg` / `*.log` 等输出物。 |

### 2.2 `assets/` — 媒体素材

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `assets/gif/UnifoLM-VLA-0.gif` | 媒体 | README 顶部用于展示真机 12 类任务效果的 demo GIF。 |

### 2.3 `scripts/` — 训练 / 评估 Shell 启动入口

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `scripts/run_scripts/run_unifolm_vla_train.sh` | Shell | G1 真机数据训练入口：通过 `accelerate launch --config_file deepspeed_zero2.yaml --num_processes 8` 起 `train_unifolm_vla.py`。关键 CLI override：`framework.qwenvl.base_vlm`、`datasets.vla_data.data_root_dir/data_mix/window_size=1/per_device_batch_size=6`、`trainer.max_train_steps=150000`、`trainer.save_interval=10000`、`trainer.use_wrist_image/use_proprio=True`、`trainer.learning_rate.base=4e-5`、`trainer.shuffle_buffer_size=10000`。同时设置 NCCL 环境变量（`bond0`、`mlx5_2/3`、`NCCL_TIMEOUT=1000`）。脚本会把自身 cp 到 `${output_dir}/` 留档。 |
| `scripts/run_scripts/run_libero_train.sh` | Shell | LIBERO 微调入口，与上面完全同结构；差异是 `window_size=2`、`per_device_batch_size=16`、`data_mix` 例如 `libero_4_task_no_noops` / `libero_90_no_noops`。 |
| `scripts/eval_scripts/run_eval_libero.sh` | Shell | LIBERO 仿真评测：导出 `LIBERO_HOME`、`LIBERO_CONFIG_PATH`、追加 `PYTHONPATH`，然后单 GPU 跑 `experiments/LIBERO/eval_libero.py`。可配 `task_suite_name`（`libero_spatial`/`object`/`goal`/`10`/`90`）、`unnorm_key`、`window_size`、`num_trials_per_task=50`，结果写到 `results/${task_suite_name}/${folder}/${step}`。 |
| `scripts/eval_scripts/run_real_eval_server.sh` | Shell | 真机服务端启动：直接调用 `deployment/model_server/run_real_eval_server.py`，参数为 `--ckpt_path`、`--port=8777`、`--unnorm_key=g1_stack_block`、`--vlm_pretrained_path`。 |

### 2.4 `deployment/` — 推理服务

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `deployment/model_server/__init__.py` | 包标识 | 空文件，作 Python 包标记。 |
| `deployment/model_server/run_real_eval_server.py` | 服务入口 | FastAPI 推理服务（420 行）：`Unifolm_VLA_Server` 加载 `baseframework.from_pretrained` 拉起完整 VLA + norm_stats，对外暴露 `POST /act`。请求负载是 `{observations: [{full_image, *_wrist, state, instruction, task_name?}]}`，服务端：① 校验 / resize / center-crop 图像（与训练 lanczos3 + 0.9 crop 一致）→ ② 用 `processor.apply_chat_template` 拼装 Qwen 多模态消息 → ③ 把 `state` 用 `normalize_proprio` 归一化（BOUNDS / BOUNDS_Q99）→ ④ `vla.predict_action` 出归一化动作 → ⑤ `unnormalize_action` 反归一化 → ⑥ 用 `json_numpy` 编码返回 numpy 数组。`json_numpy.patch()` 让 FastAPI 直接序列化 numpy。支持 `task_name` 字段在线切换 `norm_stats`，便于一个服务跑多任务。 |

### 2.5 `experiments/LIBERO/` — LIBERO 仿真评测

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `experiments/LIBERO/libero_requirements.txt` | 依赖 | LIBERO 仿真额外依赖：`imageio[ffmpeg]`、`robosuite==1.4.1`、`bddl`、`easydict`、`cloudpickle`、`gym`。需要从 LIBERO 项目根目录 `pip install -e LIBERO`。 |
| `experiments/LIBERO/libero_utils.py` | 工具 | LIBERO 评测共用工具（245 行）：`get_libero_image / get_libero_wrist_image`（注意 `[::-1, ::-1]` 翻转 180° 与训练时一致）、`get_libero_env`、`save_rollout_video`（mp4 录像）、`quat2axisangle`（四元数 → axis-angle 用于状态向量）、`check_image_format`、`resize_image_for_policy`（lanczos3 + uint8 round-clip）、`crop_and_resize`（中心裁剪到 `224×224`，crop_scale=0.9）、`center_crop_image`（PIL 包装）、`prepare_images_for_vla`（一站式 resize + center crop）。`DATE` / `DATE_TIME` 用于 log 和录像文件命名。 |
| `experiments/LIBERO/unifolm_vla_inference.py` | 推理客户端 | `Unifolm_VLA_Inference` 类（200 行）：把 `Unifolm_VLA.from_pretrained` 加载为 bfloat16 权重，绑定动作 / 状态归一化统计；`reset(task_description)` 清状态；`step(obs_inputs)` 把 batch 中除 `state`/`image` 外的 tensor 丢上 GPU、对 `state` 用 `normalize_proprio` 归一化后调 `vla.predict_action`，再 `unnormalize_action` 还原；`get_action_stats` / `get_state_stats` 通过 `share_tools.read_mode_config` 读 `config.yaml + dataset_statistics.json`；`visualize_epoch` 把若干轨迹 + 图像并排画图保存（用于离线 debug）。 |
| `experiments/LIBERO/eval_libero.py` | 评测主入口 | LIBERO 全套 task_suite rollout 主程序（400 行）：`Args` dataclass + `tyro.cli` 解析 CLI；按 `task_suite_name` 选 `max_steps`（spatial=220、object=280、goal=300、10=520、90=400）；对每个任务跑 `num_trials_per_task=50` 个 episode，每步用 `prepare_observation` 抽取 `full_image+wrist_image+state` 入双端队列，凑齐 `window_size` 后调 `get_action_state` 一次推理拿 `NUM_ACTIONS_CHUNK` 长度的 action chunk，本地维护 action_queue 顺序消费；动作经 `process_action`（`normalize_gripper_action` 把 [0,1] 映到 [-1,1] 并二值化、`invert_gripper_action` 翻转 sign）发给 LIBERO 环境；前 `num_steps_wait=10` 步用 `LIBERO_DUMMY_ACTION` 等场景静止；失败时把回放写成 mp4。文本 prompt 内嵌"You are a robot using the joint control..."的固定 CoT 风格指令。 |

### 2.6 `prepare_data/` — 数据预处理

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `prepare_data/convert_lerobot_to_hdf5.py` | 脚本 | LeRobot v2.1 → HDF5 转换器（200 行）：`LeRobotDataProcessor` 用 `LeRobotDataset(root, video_backend='pyav')` 按 episode 遍历每一步，从 `observation.image*` 拼成相机字典（可选 `to_unit8` 直接存 uint8 或 `to_bytes` JPEG 编码后存 `np.void`），把 `observation.left_arm/right_arm + 双夹爪 + body[12:15] waist` 拼成 `state`（19D 关节）和 `ee_state`（17D EEF + waist），同样拼 `action / ee_action`。`H5Writer` 写出 `episode_<i>.hdf5`：`/observations/{qpos, ee_qpos, qvel, images/<cam>}`、`/action`、`/ee_action`、`/language_raw`、`/substep_reasonings`（每步重复 task 文本）。CLI：`--data_path / --target_path`。 |
| `prepare_data/hdf5_to_rlds/README.md` | 文档 | 简要说明：先在 lerobot conda 环境里跑 `convert_lerobot_to_hdf5.py`，再换 RLDS 环境跑 `tfds build --overwrite`，可选 `visualize_dataset.py` 验证。 |
| `prepare_data/hdf5_to_rlds/rlds_dataset/__init__.py` | 包标识 | 空文件，作 RLDS dataset builder 包标记。 |
| `prepare_data/hdf5_to_rlds/rlds_dataset/conversion_utils.py` | 基础类 | `MultiThreadedDatasetBuilder`（继承 `tfds.core.GeneratorBasedBuilder`）+ `ParallelSplitBuilder`（继承 `split_builder_lib.SplitBuilder`）：把 TFDS 的单进程生成换成 `multiprocessing.Pool` 并行（默认 `N_WORKERS=10`、`MAX_PATHS_IN_MEMORY=100`），按 `chunk_max(paths, n, max_chunk_sum)` 切片喂给 `parse_examples_from_generator`，结果通过 `writer._shuffler.add` 写盘。`_SplitInfoFuture` 是 thunked-future 包装。`dictlist2listdict` / `chunks` / `chunk_max` 是辅助。 |
| `prepare_data/hdf5_to_rlds/rlds_dataset/rlds_dataset.py` | TFDS 数据集 | `rlds_dataset(MultiThreadedDatasetBuilder)`：`VERSION=1.0.0`、`N_WORKERS=8`、`MAX_PATHS_IN_MEMORY=8`。`_info()` 声明每步 schema：4 路 480×640×3 jpeg 图（`image_left_top/right_top/left_wrist/right_wrist`）+ 19D `state` + 17D `ee_state` + 23D `ee_state_6d`（用 `batch_pose17_to_pose23` 把双臂 RPY 转成 R6D 列1+列2 拼接）+ 19D `action` + 17D `ee_action` + 23D `ee_action_6d` + `discount/is_first/is_last/is_terminal/language_instruction`。`_parse_example` 从 hdf5 读相应字段并按时间步打散。`_split_paths` 写死了 `train: glob /path/to/...*.hdf5`（用户需手改）。 |

### 2.7 `src/unifolm_vla/` — 模型核心 Python 包

#### 2.7.1 包根

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `src/unifolm_vla/__init__.py` | 包标识 | 空文件，仅声明 `unifolm_vla` 命名空间。 |

#### 2.7.2 `config/` — 训练 + DeepSpeed 配置

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `config/training/unifolm_vla_train.yaml` | 训练主配置 | 训练入口的"母配置"，由 `OmegaConf.load` 读取并合并 CLI override（参 `train_unifolm_vla.py`）。`framework.qwenvl`：`base_vlm` 路径、`flash_attention_2`、`vl_hidden_dim=2048`、`model_type=qwen2_5_vl`。`framework.action_model`：`input_embedding_dim=1536`、`hidden_size=1024`、`add_pos_embed=True`、`max_seq_len=1024`、`action_dim=16/state_dim=16`、`future_action_window_size=15` + `action_horizon=16`、`repeated_diffusion_steps=8`、Flow Matching 的 `noise_beta_alpha=1.5/beta_beta=1.0/noise_s=0.999`、`num_timestep_buckets=1000`、`num_inference_timesteps=4`、`num_target_vision_tokens=32`、`diffusion_model_cfg.{cross_attention_dim=2048, num_layers=16, num_attention_heads=32, attention_head_dim=48, dropout=0.2, final_dropout=true, interleave_self_attention=true, norm_type="ada_norm", output_dim=1024}`。`datasets.vla_data`：`per_device_batch_size=16/window_size=1/image_size=[224,224]`。`trainer`：`max_train_steps=100000/eval_interval=100/save_interval=5000`、分组学习率（`base=1e-5`、`qwen_vl_interface=1e-5`、`action_model=1e-4`）、`cosine_with_min_lr` + `min_lr=5e-7`、AdamW (β=[0.9, 0.95])、`max_grad_norm=1.0/gradient_clipping=1.0`、`gradient_checkpointing=true/mixed_precision=true`。 |
| `config/deepseeds/deepspeed_zero2.yaml` | accelerate 启动配置 | accelerate v1 配置：`distributed_type=DEEPSPEED`、`num_machines=1/num_processes=8`，`deepspeed_config_file` 指向同目录 `ds_config.yaml`，`zero3_init_flag=false`。 |
| `config/deepseeds/ds_config.yaml` | DeepSpeed 配置 | DeepSpeed Zero-2：`fp16/bf16` 自动、`zero_optimization.stage=2` 全部 partition、`allgather/reduce_bucket_size=5e8`、`overlap_comm=true/contiguous_gradients=true/cpu_offload=false`、`gradient_clipping=1.0/steps_per_print=10`。`train_micro_batch_size_per_gpu=auto/train_batch_size=auto`，由 accelerate 自动填充。 |
| `config/deepseeds/zero2.yaml` | 备选 accelerate 配置 | 简化版 accelerate Zero-2：`mixed_precision=bf16`、不挂 cpu offload，没有挂外部 `deepspeed_config_file`，可能为快速 sanity check 用。 |
| `config/deepseeds/zero3.json` | DeepSpeed 配置 | Zero-3 备选：`stage=3` 全部参数 partition，`stage3_max_live_parameters/max_reuse_distance=1e9`、`stage3_gather_16bit_weights_on_model_save=true`。仓库内默认未启用，需要超大模型时切换。 |

#### 2.7.3 `model/` — 模型核心

##### `model/framework/` — VLA 框架装配层

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `model/framework/__init__.py` | 工厂 | `build_framework(cfg)` 单一函数：根据 `cfg.framework.framework_py` 字符串路由到对应类。当前唯一支持 `unifolm_vla` → `Unifolm_VLA(cfg)`，其它 raise `NotImplementedError`。 |
| `model/framework/share_tools.py` | 通用工具 | (220 行) ① `NamespaceWithGet(SimpleNamespace)`：让 `SimpleNamespace` 有 `.get/.items/.__iter__/.to_dict`，支持 `**unpack`，方便在 OmegaConf / dict / NS 三种容器之间互转；② `dict_to_namespace`、`_to_omegaconf` 把任何输入（path / dict / OmegaConf / NamespaceWithGet）规范成 OmegaConf；③ `read_model_config(ckpt_pt)`：从 `<run>/checkpoints/<n>.pt` 反推 `<run>/config.json + dataset_statistics.json`；④ `read_mode_config(ckpt_pt)`：同 ③ 但读 `config.yaml`（`baseframework.from_pretrained` 实际用的是这条）。 |
| `model/framework/base_framework.py` | 抽象基类 | `baseframework(nn.Module)`：① `from_pretrained(pretrained_checkpoint, vlm_pretrained_path)`：调 `read_mode_config` 拿到 yaml + 归一化统计，可选用 `vlm_pretrained_path` 覆盖 `framework.qwenvl.base_vlm`，`build_framework` 实例化 → `torch.load` map_location=cpu 的 state_dict → `load_state_dict(strict=True)`，遇 RuntimeError 时打印 `missing/unexpected` 后再抛；② 把 `norm_stats` 注册成属性供反归一化使用。`_check_unnorm_key` + `get_action_stats` 在文件中各定义两次（明显的遗留代码重复，前后两份签名相同），实际都做"如果用户没指定 unnorm_key 且 stats 只有 1 个数据集就自动选，否则 assert key 在 stats 中"。 |
| `model/framework/unifolm_vla.py` | VLA 主类 | `Unifolm_VLA(baseframework)`，注册到 `FRAMEWORK_REGISTRY['unifolm_vla']`：`__init__` 里组装 `qwen_vl_interface = get_vlm_model(config)` 与 `action_model = get_action_model(config)`，并把 `cross_attention_dim` 动态对齐成 Qwen 的 `hidden_size`（避免维度不匹配）；`forward(qwen_inputs)`：取 batch 中的 `action(bf16)/state(bf16, [B,1,D])`，bf16 autocast 先跑 Qwen 拿 `last_hidden`，再 fp32 autocast 跑 action_model；这里关键技巧是 `repeated_diffusion_steps=8`（CogACT 的 trick）—— 把 actions / hidden / state 在 batch 维度复制 8 份再喂 action_model，相当于一个样本采 8 个不同噪声扰动一起算 loss，提升梯度信号。`predict_action(qwen_inputs)`：`@torch.inference_mode`，bf16 跑 Qwen 拿 `last_hidden`、fp32 跑 `action_model.predict_action` 得到完成去噪的连续动作（cpu numpy），返回 `{"normalized_actions": ndarray}`。 |

##### `model/modules/vlm/` — VLM 主干适配

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `model/modules/vlm/__init__.py` | 工厂 | `get_vlm_model(config)`：根据 `config.framework.qwenvl.model_type` 选择具体 VLM。当前仅支持 `qwen2_5_vl` → `_QWen_VL_Interface(config)`。 |
| `model/modules/vlm/QWen2_5.py` | Qwen 包装 | `_QWen_VL_Interface(nn.Module)`：① `__init__` 用 `Qwen2_5_VLForConditionalGeneration.from_pretrained(model_id, attn_implementation='flash_attention_2', torch_dtype=bfloat16, device_map='cuda')` 加载 backbone，强制 `processor.tokenizer.padding_side='left'`（FlashAttn + KV cache 对齐需要）；② `forward(input_ids, attention_mask, pixel_values, image_grid_thw, ...)` 直接转给 `self.model`，bf16 autocast；③ `generate(...)` autoregressive 解码（默认 `max_new_tokens=128`）；④ `build_qwenvl_inputs(images, instructions)` 高级接口：把 `[List[PIL]]` 和 `[str]` 拼成 chat-style messages（per-sample 一段 user content，其中 image 用 `{"type":"image","image":pil}` 串），可选用 `config.datasets.vla_data.CoT_prompt` 模板替换 `{instruction}`，再调 `processor.apply_chat_template(add_generation_prompt=True)` + `process_vision_info(messages)` + `processor(text=..., images=..., padding=True, return_tensors='pt')`，最后 `.to(self.model.device)`。`get_qwen2_5_interface(config)` 是同义工厂函数。 |

##### `model/modules/action_model/` — 流匹配动作头

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `model/modules/action_model/DiT_ActionHeader.py` | 动作头主类 | (310 行) 文件头注释明确"copyright NVIDIA, modified by Junqiu YU/Fudan, action repeat inspired by CogACT"。① `MLP(input, hidden, output)`：标准 `Linear-ReLU-Linear`；② `ActionEncoder(action_dim, hidden_size)`：3 层 MLP + sin 位置编码——`actions[B,T,D] → linear(D→H)`、sin/cos 时间嵌入 `(B,T,H)`、concat 后 `linear(2H→H)+swish+linear(H→H)`；③ `FlowmatchingActionHeadConfig(PretrainedConfig)`：dataclass+kwargs 双轨注入的 HF 配置，列举所有超参（add_pos_embed, diffusion_model_cfg, hidden_size, max_seq_len, action_dim, action_horizon, num_timestep_buckets, num_inference_timesteps, max_num_embodiments, vl_self_attention_cfg, num_target_vision_tokens 等）；④ 备份 `DiTConfig` 字典：DiT-B 768/64/12, DiT-L 1536/48/32（实际未直接使用，靠 yaml 注入）；⑤ **`FlowmatchingActionHead`** 主体：构造 `state_encoder=MLP(P→H→input_dim)`、`action_encoder=ActionEncoder(A→input_dim)`、`action_decoder=MLP(input_dim→H→A)`、`future_tokens=nn.Embedding(num_target_vision_tokens, input_dim)`、可选 `position_embedding=nn.Embedding(max_seq_len, input_dim)`；噪声时间靠 `Beta(α,β)` 采样并做 `(s-x)/s` 变换；`forward(vl_embs, actions, state)`：`noise=randn`、`t∈(0,1)`、`x_t=(1-t)*noise+t*actions`、`velocity=actions-noise`，`t_discretized=int(t*1000)` 给 timestep encoder；input sequence = `[state_features, future_tokens, action_features]`（concat dim=1，state 可缺省），过 DiT 的 cross-attention（encoder=vl_embs）+ 自注意力（详见 cross_attention_dit.py 的 interleave_self_attention 开关），最后 `action_decoder(model_output)[:, -T:]` 切出动作部分，loss 是 `MSE(pred, velocity)`（rectified flow loss）；`predict_action(vl_embs, state)`：`x = randn(B, action_horizon, action_dim)`，`num_steps=4` 个欧拉步，每步 `x += dt * action_decoder(DiT(x_t))[:, -horizon:]`，返回最终 `x`；⑥ `get_action_model(config)` = `FlowmatchingActionHead(full_config=config)` 工厂。 |
| `model/modules/action_model/flow_matching_modules/__init__.py` | 包标识 | 仅 NVIDIA Apache-2.0 许可证头，无可执行代码。 |
| `model/modules/action_model/flow_matching_modules/action_encoder.py` | 时间嵌入 | `swish(x)=x*sigmoid(x)`；`SinusoidalPositionalEncoding(embedding_dim)`：`forward(timesteps[B,T])` 用经典 `exp(-arange(half_dim) * log(10000)/half_dim)` 频率，对 `timesteps` 外积得到 `freqs[B,T,half_dim]`，sin/cos 拼接成 `[B,T,embedding_dim]`。 |
| `model/modules/action_model/flow_matching_modules/cross_attention_dit.py` | DiT 主体 | (350 行) ① `TimestepEncoder`：diffusers `Timesteps(256, flip_sin_to_cos=True) + TimestepEmbedding(256→embedding_dim)`，输出 `temb[B,D]`；② `AdaLayerNorm`：把 `temb` 经 `SiLU+Linear(D→2D)` 切 `(scale, shift)`，对 `LayerNorm(x)` 做 `*(1+scale)+shift`；③ `BasicTransformerBlock`：包含 1 个 `Attention`（diffusers Attention，可同时做自注意力 / 交叉注意力，由 `cross_attention_dim` 是否为 None 决定）+ `LayerNorm` + `FeedForward`，在 `norm_type=='ada_norm'` 时 norm1 用 `AdaLayerNorm(temb)`；可选 `SinusoidalPositionalEmbedding`；最后 `final_dropout` 可选；④ **`DiT(ModelMixin, ConfigMixin)`** 主体：`@register_to_config` 装饰器使 diffusers 能保存/加载；构建 `num_layers=16` 个 `BasicTransformerBlock`，**关键开关 `interleave_self_attention=True`**：偶数索引 (`idx%2==0`) 块走 cross-attention（`encoder_hidden_states=vl_embs`），奇数索引块走自注意力（`cross_attention_dim=None`）实现"两两交替"模式；输出 `proj_out_1: D→2D` + `proj_out_2: D→output_dim` 在 ada-norm 风格下做最终 modulation；⑤ 附加 `SelfAttentionTransformer` 是另一个全自注意力变体（仓库当前未在主路径使用）。 |

##### `model/utils/`

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `model/utils/pooling_utils.py` | 工具（未启用） | (75 行) `_interpolate / _apply_pos_embed / interpolate_pooling / custom_pooling`：用 `bilinear` 插值给 vision token 做"重采样池化"；用到 `unifolm_vla.model.modules.vggt.heads.utils.create_uv_grid / position_grid_to_embed`，但仓库里没有 `vggt` 子目录——这是从 InternVLA-M1 / VGGT 系遗留的代码，当前主路径（`Unifolm_VLA.forward`）不调用此模块。可视为 dead code 或未来扩展位。 |

##### `model/tools.py`

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `model/tools.py` | 注册表 | 145 行：① `auto_get_module_keys / is_module_trainable / auto_get_trainable_modules`：递归遍历 `nn.Module` 树，输出"全可训练"分支的最浅路径列表（用于打印 trainable summary）；② `print_freeze_status`：扫描 `named_parameters`，按 top-level module 汇总 `Frozen/Trainable` 计数，混合状态时逐参数打印；③ `Registry`：通用注册表（带 `@register("key")` 装饰器），全局唯一实例 `FRAMEWORK_REGISTRY = Registry("frameworks")`，`Unifolm_VLA` 在自己的文件里把自己注册成 `"unifolm_vla"`。 |

#### 2.7.4 `rlds_dataloader/` — RLDS 数据加载与归一化

##### 包根

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `rlds_dataloader/__init__.py` | 包标识 | 空文件。 |
| `rlds_dataloader/constants.py` | 常量集 | 130 行：① 定义 `NormalizationType(str, Enum)` = `NORMAL/BOUNDS/BOUNDS_Q99`；② 定义 7 个 robot platform 常量字典（`LIBERO/ALOHA/BRIDGE/FRACTAL/G1/G1_EE_6D/G1_STACK_BLOCK`）；③ `detect_robot_platform()` 扫 `sys.argv` 字符串关键字（`libero` / `aloha` / `bridge` / `fractal` / `ee_6d` / `joint` / `stack_block`）选 platform，默认 `G1_EE_6D`；④ 在 import 时把选中的 `NUM_ACTIONS_CHUNK / ACTION_DIM / PROPRIO_DIM / ACTION_PROPRIO_NORMALIZATION_TYPE` 提到 module-level 全局变量。这套魔术 import 让训练 / 推理脚本只要命令行带正确关键字就自动切换动作 / 状态维度。还有 `IGNORE_INDEX=-100`、`ACTION_TOKEN_BEGIN_IDX=31743` 等遗留 token 常量。 |
| `rlds_dataloader/action_tokenizer.py` | 离散 tokenizer（未启用） | `ActionTokenizer(bins=256, min=-1, max=1)`：把连续动作 clip + uniform-bin → 数字 → `<action_{idx}>` 文本，用于"动作即 token"的早期 OpenVLA 风格；`decode_token_ids_to_actions` 反向。当前 VLA 用的是连续动作 + flow matching 路径，这个 tokenizer 在训练时不被实际使用（无人调用），保留作 debug / fallback。 |

##### `datasets/` — PyTorch Dataset 适配层

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `datasets/__init__.py` | 标识 | 单行 re-export `EpisodicRLDSDataset, RLDSBatchTransform, RLDSDataset`。 |
| `datasets/datasets.py` | RLDS→PyTorch 适配 | (205 行) ① `RLDSBatchTransform(use_wrist_image, use_proprio, processor)`：可调用对象，把一个 RLDS 字典 batch 转换成训练样本——拼装 chat messages（注入"You are a robot using the joint control. The task is "...". Please predict up to 10 key trajectory points..."的固定 CoT prompt），用 `processor.apply_chat_template + process_vision_info + processor(...)` 出 `input_ids/attention_mask/pixel_values/image_grid_thw`，再附加 `actions` 与可选 `proprio`。**注意**：当 `window_size>1` 时，`actions = actions[window_size-1:]` 只取窗口最后一步开始的 future chunk；② `RLDSDataset(IterableDataset)`：包装 `make_interleaved_dataset`，按 `data_mix` 在 `OXE_NAMED_MIXTURES` 查表得到 mixture_spec（找不到时退化为 `[(data_mix, 1.0)]` 单数据集），`load_camera_views` 按数据集名分支：含 `aloha`/`Unitree_all_task`/`g1_stack_block` 时取 `("primary", "left_wrist", "right_wrist")`，否则 `("primary", "wrist")`；构建 `traj_transform_kwargs`（`window_size`, `future_action_window_size = NUM_ACTIONS_CHUNK-1`, `skip_unlabeled=True`, `goal_relabeling_strategy='uniform'`）+ `frame_transform_kwargs`（`resize_size`，`num_parallel_calls=16`），可选 image_aug（`random_resized_crop/brightness/contrast/saturation/hue`），然后跑 `make_interleaved_dataset`，把 `dataset_length / dataset_statistics` 拿出来。`__iter__` 简单遍历 numpy iterator 然后过 `batch_transform`。`__getitem__` 显式 raise（IterableDataset 不支持 random access）；③ `EpisodicRLDSDataset(RLDSDataset)`：`make_dataset` 切换为 `make_single_dataset`（必须单数据集），yield 整集而非单步，便于可视化。 |

##### `datasets/rlds/` — RLDS 核心管道

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `datasets/rlds/__init__.py` | 标识 | re-export `make_interleaved_dataset, make_single_dataset`。 |
| `datasets/rlds/dataset.py` | RLDS 管道核心 | (600 行) 三个核心函数：① **`make_dataset_from_rlds(name, data_dir, *, train, standardize_fn, image_obs_keys, depth_obs_keys, state_obs_keys, language_key, action_proprio_normalization_type, dataset_statistics, absolute_action_mask, action_normalization_mask, ...)`**：调 `tfds.builder(name, data_dir, '1.0.0')`，先 `dl.DLataset.from_rlds`，再 `traj_map(restructure)`：标准化函数应用 → 提取 `image_*/depth_*/proprio/timestep` 重命名 → 输出统一 schema `{observation, task, action, dataset_name(repeat name)}` + 可选 `absolute_action_mask`。统计可显式传 dict / json 路径，否则调 `get_dataset_statistics(hash_dependencies=(builder.info, state_obs_keys, source(standardize_fn)))` 自动算 / 缓存。`action_normalization_mask` 写进 stats 用于排除某些维度（如 gripper）的归一化。最后 `traj_map(normalize_action_and_proprio)` 把 action / proprio 按 `BOUNDS / BOUNDS_Q99 / NORMAL` 归一化到 [-1,1]；split 选 `train[:95%]` 或 `train[95%:]`（验证 split 不存在时）；② **`apply_trajectory_transforms`**：`skip_unlabeled` 过滤无指令样本、`max_action / max_proprio` 过滤越界样本、`add_pad_mask_dict` 给 obs/task 加"是否 padding"掩码、可选 `goal_relabeling`、`task_augmentation`、**`chunk_act_obs(window_size, future_action_window_size)`**（关键步骤：把 obs 重组成 [T,window_size,...]，把 action 重组成 [T, window_size+future_action_window_size, dim]，还构造 `pad_mask` 标志哪些是从负时刻借来的 padding）、可选 `subsample`；③ **`apply_frame_transforms`**：`decode_and_resize` 解码 jpeg + resize 到目标分辨率；训练时 `augment` 用同一 seed 给所有图片（兼容 multi-image 同一帧）；④ `make_single_dataset` 单数据集 wrapper；⑤ **`make_interleaved_dataset(dataset_kwargs_list, sample_weights, ..., shuffle_buffer_size, balance_weights, traj_transform_threads)`**：先把每个数据集都 `make_dataset_from_rlds` 算出 `num_transitions` 当 size，再用 `balance_weights` 把 `weight *= size` 做"按数据量再加权"（保证小数据集不会被淹没）；按 `weight` 比例 `allocate_threads`（`AUTOTUNE` 或精确分配 N 个线程）；每个数据集 `.repeat()` 后 traj transform 再 `flatten` 成单步；用 `dl.DLataset.sample_from_datasets(datasets, weights)` 在 frame 级别交错采样；最后统一 shuffle + frame transforms。返回 `(dataset, dataset_len, all_dataset_statistics)`。`pprint_data_mixture` 打印混合配比表。 |
| `datasets/rlds/obs_transforms.py` | 帧级变换 | (100 行) ① `augment(obs, seed, augment_kwargs)`：基于 dlimp 的 `augment_image`，跳过 `pad_mask_dict[key]==False` 的 padding 帧，对每个图像名 i 用 `seed+i` 保证不同图像不同 seed；② `decode_and_resize(obs, resize_size, depth_resize_size)`：tf.string jpeg → uint8 → `dl.transforms.resize_image`，对 padding 帧（`tf.strings.length==0`）填充 0；depth 同理但 dtype=float32。 |
| `datasets/rlds/traj_transforms.py` | 轨迹级变换 | (105 行) ① `chunk_act_obs(traj, window_size, future_action_window_size)`：核心 chunking——给 obs 加 axis size=window_size、给 action 加 axis size=window_size+future_action_window_size，超出 traj 头尾的 indices 被 clip 到 [0, traj_len-1]，同时构造 `pad_mask=chunk_indices>=0`；对 action，超过"目标时刻"的位置按 `absolute_action_mask` 决定 neutral 值（绝对动作 → 重复最后一帧；相对动作 → 0）；② `subsample(traj, length)`：随机下采样到指定长度；③ `add_pad_mask_dict(traj)`：给 obs/task 中字符串字段（语言指令、image jpeg bytes 等）加"非空"掩码，其它键全 1。 |

##### `datasets/rlds/utils/`

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `datasets/rlds/utils/__init__.py` | 标识 | 空文件。 |
| `datasets/rlds/utils/data_utils.py` | RLDS 杂项 | (370 行) ① `tree_map / tree_merge / to_padding`：嵌套 dict 工具；② `NormalizationType` 枚举（与 `constants.py` 同名同义，独立定义供 RLDS 上下文使用）；③ `convert_quaternion_to_euler`：纯 TF 算的 (xyz,w) → (roll,pitch,yaw) extrinsic XYZ 顺序；④ **`normalize_action_and_proprio(traj, metadata, normalization_type)`**：对 `action` 与 `observation/proprio` 分别按 mean/std 或 min/max 或 q01/q99 归一化到 [-1,1]，并把 `min==max` 的恒定维度直接置 0（避免除零）；⑤ `binarize_gripper_actions`：用 `tf.scan` 反向扫描，把 `[0.05, 0.95]` 区间的中间值替换为后续到达的真实开/合状态；⑥ `invert_gripper_actions(=1-x)`、`rel2abs_gripper_actions(±0.1阈值的差分→绝对)`；⑦ `relabel_bridge_actions`：BridgeV2 专用——把 EEF state 的差分作为前 6D 动作，保留原 gripper 维；⑧ `pprint_data_mixture`：打印混合表；⑨ **`get_dataset_statistics(dataset, hash_dependencies, save_dir)`**：`sha256(builder.info + state_keys + source(standardize_fn))` 作为缓存 key，把 mean/std/max/min/q01/q99/num_transitions/num_trajectories 算好缓存到 `<save_dir>/dataset_statistics_<hash>.json`，权限不足时退化到 `~/.cache/orca/`；⑩ `save_dataset_statistics`：把训练用的 stats 落到 `<run>/dataset_statistics.json`（推理 `from_pretrained` 时再读回）；⑪ `allocate_threads(n, weights)`：按 weight 比例分配整数线程数，每个数据集至少 1。 |
| `datasets/rlds/utils/goal_relabeling.py` | 目标采样 | `uniform(traj)`：对每条 traj 中的每个时刻 i，随机从 `[i+1, traj_len)` 选一个未来时刻作为 goal，把对应 obs 拷到 `traj["task"]`（用 `tree_merge` 合并 pad_mask_dict）。是 BC + goal-conditioned 训练的标准做法。 |
| `datasets/rlds/utils/task_augmentation.py` | 任务增广 | `delete_task_conditioning(traj, keep_image_prob)`：以 `keep_image_prob` 概率保留 goal-image，互斥地把 language 或 image 之一 mask 掉（pad_mask_dict 同步更新），从而训练时随机做"语言条件"或"目标图条件"，提升鲁棒性。当前默认配置未启用，但 pipeline 入口已留好。 |

##### `datasets/rlds/oxe/` — Open-X-Embodiment 数据集注册

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `datasets/rlds/oxe/__init__.py` | 标识 | re-export `get_oxe_dataset_kwargs_and_weights`、`OXE_NAMED_MIXTURES`。 |
| `datasets/rlds/oxe/configs.py` | 数据集 schema | (790 行) `StateEncoding` 枚举（`POS_EULER/POS_QUAT/JOINT/JOINT_BIMANUAL/JOINT_G1/EE_R6_G1`）+ `ActionEncoding` 枚举（`EEF_POS/JOINT_POS/JOINT_POS_BIMANUAL/EEF_R6/JOINT_G1/EE_R6_G1`）。`OXE_DATASET_CONFIGS` 是核心字典，覆盖 60+ 数据集的字段映射：① 12 个 Unitree G1 数据集（`g1_stack_block / pack_pencilbox / bag_insert / pour_medicine / pack_pingpong / wipe_table / erase_board / organize_tools / clean_table / prepare_fruit / fold_towel / dual_clean_table`），全部用 `EE_R6_G1 + EE_R6_G1` 编码、四路相机 (`primary, left_wrist, right_wrist`)；② Open-X 的 fractal、bridge、taco_play、jaco_play、roboturk、viola、berkeley_*、stanford_*、austin_*、bc_z、tdroid、roboset、rh20t、droid 等；③ 6 个 LIBERO 子集（`spatial/object/goal/10/90/4_task` 全部 `_no_noops`，POS_EULER + EEF_POS）；④ 4 个 ALOHA 数据集（双臂折叠、舀勺、放罐子，`JOINT_BIMANUAL + JOINT_POS_BIMANUAL`）。每个 entry 给出 `image_obs_keys/depth_obs_keys/state_obs_keys` 三组键映射（`None` 表示 padding），后续被 `make_oxe_dataset_kwargs` 消费。 |
| `datasets/rlds/oxe/materialize.py` | 配置物化 | (145 行) ① **`make_oxe_dataset_kwargs(dataset_name, data_root_dir, load_camera_views, load_depth, load_proprio, load_language, action_proprio_normalization_type)`**：从 `OXE_DATASET_CONFIGS` deepcopy 一份配置，根据 `action_encoding` 自动设置 `absolute_action_mask` 与 `action_normalization_mask`（`EEF_POS` → 6D 相对 + 1D 绝对 gripper、`EEF_R6` → 9D + 1D、`JOINT_POS_BIMANUAL` → 14D 全绝对、`JOINT_G1` → 19D 全绝对、`EE_R6_G1` → 23D 全绝对），并把请求的相机视角 / 深度 / 本体感知开关应用到 image/depth/state keys 上。绑定 `standardize_fn = OXE_STANDARDIZATION_TRANSFORMS[dataset_name]`，最后再 merge `aux_kwargs`；② **`get_oxe_dataset_kwargs_and_weights(data_root_dir, mixture_spec, ...)`**：去重 mixture，依次调用 ①，跳过 raise ValueError 的（视图缺失等），返回 `(per_dataset_kwargs[], weights[])` 直接喂 `make_interleaved_dataset`。 |
| `datasets/rlds/oxe/mixtures.py` | 混合配方 | (350 行) `OXE_NAMED_MIXTURES` 字典，登记了 25+ 套训练配方：包含小规模如 `bridge` / `bridge_rt_1` / `fractal20220817_data` / `test`，中规模 `bridge_rt_1`，大规模 `rtx` / `rtx_franka` / `oxe_magic_soup` / `custom_train_v2_no_droid`，以及 LIBERO 系列、ALOHA 系列。**Unitree 用最关键的两个**：① `Unitree_all_task`（12 任务非均匀采样：`g1_stack_block=1.20, pack_pencilbox=3.50, wipe_table=8.96, erase_board=5.26, bag_insert=4.85, pour_medicine=4.50, pack_pingpong=4.16, organize_tools=3.71, clean_table=2.46, prepare_fruit=5.29, dual_clean_table=3.47, fold_towel=1.00`，weight 反映每个任务的轨迹数倒数，用于平衡过采样）；② `g1_stack_block` 单任务训练。 |
| `datasets/rlds/oxe/transforms.py` | 标准化变换 | (960 行) `OXE_STANDARDIZATION_TRANSFORMS` 字典 + 60+ 个 `*_dataset_transform(trajectory)` 函数。每个数据集定制化把原始 RLDS schema 转成统一 schema：① `bridge_orig`：丢首帧（动作全零）、`world_vector+rotation_delta+open_gripper` → 7D action，再 `relabel_bridge_actions` 用 EEF 差分作动作；② `rt1_dataset_transform`：fractal 数据集的 RT-1 风格；③ `kuka / taco_play / jaco_play / berkeley_* / language_table / stanford_*` 等：各自的 EEF + gripper 拼装；④ 最关键的 G1 两个：**`unitree_g1_ee_6d_dataset_transform`**：`obs.state = obs.ee_state_6d`、`action = ee_action_6d`（即从 17D RPY 表示翻成 23D R6D 表示，通过 `rlds_dataset.py` 的 `batch_pose17_to_pose23` 在数据生成阶段已算好），用于全部 12 个 G1 任务；**`unitree_g1_joint_dataset_transform`**：直接用 `state` / `action` 不变（关节空间），仓库未在 OXE_STANDARDIZATION_TRANSFORMS 注册——保留作 future option；⑤ `libero_dataset_transform`：把 gripper 从 `[-1,1]` clip 到 `[0,1]` 后翻转（+1=open / 0=close），分离 `EEF_state[:6]` 与 `gripper_state[-2:]`；⑥ `aloha_dataset_transform`：直接 passthrough。`OXE_STANDARDIZATION_TRANSFORMS` 作字符串 → 函数的注册表，被 `materialize.make_oxe_dataset_kwargs` 拉取。 |

##### `datasets/rlds/oxe/utils/`

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `datasets/rlds/oxe/utils/droid_utils.py` | DROID 转换 | (180 行) ① `rmat_to_euler / euler_to_rmat / invert_rmat`：`tensorflow_graphics.geometry.transformation` 包装；② `rotmat_to_rot6d`：取旋转矩阵前两行 6D 表示；③ `velocity_act_to_wrist_frame`：把基坐标系下 6D 速度（dT+dR）通过 `R^-1 dT_rbt` / `R^-1 dR_rbt R` 变换到 wrist 坐标系，输出 9D（3D 平移 + 6D 旋转）；④ `rand_swap_exterior_images`：50% 概率交换两路外部相机；⑤ `droid_baseact_transform`、`droid_finetuning_transform`：把 DROID 官方 schema 翻译成统一格式。 |

#### 2.7.5 `training/` — 训练脚手架

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `training/__init__.py` | 标识 | 空文件。 |
| `training/train_unifolm_vla.py` | 训练主脚本 | (485 行) **整个仓库唯一的训练入口**，由 `accelerate launch ... train_unifolm_vla.py --config_yaml ...` 调起：① 解析 `--config_yaml` + 经 `normalize_dotlist_args` 规范化的 `--x.y val` 风格 CLI override，OmegaConf 合并；② `setup_directories(cfg)`：rank 0 上创建 `<run_root_dir>/<run_id>/checkpoints`、写 `config.yaml + config.json`；③ `build_framework(cfg)` 直接拿到 `Unifolm_VLA` 实例；④ `prepare_data(cfg, accelerator, processor)`：用 `RLDSBatchTransform(processor, use_wrist_image, use_proprio)` 包装 `RLDSDataset`，构造 `DataLoader(num_workers=0)`（`num_workers=0` 是因为 RLDS 已用 TF 内部并行），rank 0 还会调 `save_dataset_statistics` 落 `dataset_statistics.json`；⑤ `setup_optimizer_and_scheduler`：用 `build_param_lr_groups` 给 `qwen_vl_interface=1e-5` / `action_model=1e-4` / `base=4e-5` 分组 AdamW，scheduler 走 `cosine_with_min_lr`；⑥ `VLATrainer(TrainerUtils)` 主类：`prepare_training` 负责设种子、可选 `pretrained_checkpoint` 加载、`freeze_modules` 冻结、`accelerator.prepare(model, opt, dataloader)`、初始化 wandb（`mode='offline'`）和 checkpoint 目录；`train` 主循环：`max_train_steps` 步，每步 `_train_step` 在 bf16 autocast 下跑 `model.forward(batch)` 拿 `action_loss`、`accelerator.backward + clip_grad_norm + step + scheduler.step`，每 `eval_interval` 步在 rank 0 上跑 `eval_action_model`（拿一个 batch、`predict_action`、和 GT 算 `euclidean_distance` 的平均），每 `save_interval` 步 rank 0 把 `accelerator.get_state_dict(model)` 直接 `torch.save` 成 `.pt`，每 `logging_frequency` 步推送 wandb；`_finalize_training` 最后落 `final_model/pytorch_model.pt`。`collate_fn` 用 `pad_sequence` 左 pad input_ids（`tokenizer.pad_token_id`），把 actions / proprio / pixel_values / image_grid_thw 串起来。 |
| `training/trainer_utils/__init__.py` | 标识 | 单行 re-export `initialize_overwatch`。 |
| `training/trainer_utils/overwatch.py` | 日志包装 | (150 行) 来自 OpenVLA / Prismatic 的 RichHandler 风格 logger：① `LOG_CONFIG` 配 RichHandler；② `ContextAdapter`：给 log 加分级缩进前缀（`[*]`、`|=>`）；③ `DistributedOverwatch(name)`：内部包 `accelerate.PartialState`，`rank_zero_only / local_zero_only / rank_zero_first / local_zero_first` 装饰器，多卡时只 rank 0 打 INFO 其他打 ERROR；④ `PureOverwatch`：单进程降级版本；⑤ `initialize_overwatch(name)` 检查 `WORLD_SIZE` 环境变量自动选两者之一。模型代码到处用 `overwatch = initialize_overwatch(__name__); overwatch.info(...)`。 |
| `training/trainer_utils/metrics.py` | 训练工具集（主） | (445 行) 实际被引用的工具集，主要由 `train_unifolm_vla.py` import：① `normalize_dotlist_args`：把 `['--x.y', 'val']` 转 `['x.y=val']` 喂 OmegaConf；② `build_param_lr_groups(model, cfg)`：按 `cfg.trainer.learning_rate` 字典里的"模块名 → lr" 给 `optimizer.param_groups` 分组，未列出的归 `base` 组；③ `only_main_process` 装饰器；④ `resize_images`（递归 PIL resize 工具）；⑤ **`TrainerUtils`** 静态工具类（被 `VLATrainer` 继承）：`freeze_backbones(model, freeze_modules)`（按逗号分隔的相对路径递归冻结）、`print_trainable_parameters / print_freeze_status`、`load_pretrained_backbones(model, ckpt_path, reload_modules)`（支持按子模块 partial load）、`setup_distributed_training(accelerator, *components)`（accelerate.prepare 包装）、`euclidean_distance`、`_reset_dataloader`（`set_epoch + iter` 重置）、`compute_grad_angle_with_stats`（动作头与 VL 主干梯度向量的 cosine 角度统计——用于多任务训练时的负迁移诊断）、`pcgrad_project`（PCGrad 风格梯度正交化—当两组梯度内积 < 0 时 `g_v -= (dot/||g_a||²) g_a`）、`eval_qwenpi`（早期 QwenQFormerDiT 评估流程：IoU + action 距离）、`extract_json_from_string`；⑥ `is_main_process`（`RANK==0`）。 |
| `training/trainer_utils/trainer_tools.py` | 训练工具集（重复版） | (450 行) 与 `metrics.py` **几乎逐字重复**的副本，差异仅在 `freeze_backbones` 的 `dist.barrier()` 守卫位置略有不同（`metrics.py` 检查 `dist.is_initialized()`，本文件直接 barrier）以及 `print_trainable_parameters` 的 rank 守卫差异。**实际训练入口只 import `metrics`**，本文件似为遗留 / 备份代码，未被消费。建议清理时统一保留 `metrics.py`。 |

---

## 3. 数据流总览

### 3.1 训练时端到端数据流

```
[LeRobot v2.1 dataset]
    │  prepare_data/convert_lerobot_to_hdf5.py
    ▼
[HDF5 episodes (state+action+ee+images+lang+substep_reasonings)]
    │  prepare_data/hdf5_to_rlds/rlds_dataset/   (tfds build)
    │  - batch_pose17_to_pose23: RPY → R6D 扩展
    ▼
[RLDS / TFDS (1.0.0)  shape: 4 cams + 19D state + 23D ee_state_6d + 23D ee_action_6d]
    │  rlds_dataloader.datasets.rlds.dataset.make_interleaved_dataset
    │  - oxe.materialize.make_oxe_dataset_kwargs (per-dataset config)
    │  - oxe.transforms.unitree_g1_ee_6d_dataset_transform (state ← ee_state_6d, action ← ee_action_6d)
    │  - normalize_action_and_proprio (BOUNDS / BOUNDS_Q99 → [-1,1])
    │  - traj_transforms.chunk_act_obs (window_size + future_action_window_size)
    │  - obs_transforms.decode_and_resize (224×224 + lanczos3)
    ▼
[batched RLDS dict]
    │  RLDSBatchTransform(processor):
    │  - PIL images + chat-template prompt → Qwen processor → input_ids/pixel_values/image_grid_thw
    │  - actions[window_size-1:] 截取 future chunk
    ▼
[batch dict]  → collate_fn (pad_sequence input_ids)
    ▼
[Unifolm_VLA.forward]:
    qwen_vl_interface(input_ids, pixel_values, ...) → last_hidden  [B, L, H]
    repeat ×8 for diffusion steps
    action_model(vl_embs, action_target, state):
        actions noise=randn, t~Beta(1.5,1.0), x_t=(1-t)*noise + t*action
        velocity = action - noise
        DiT(hidden=[state_emb, future_tokens, action_features], encoder=vl_embs, timestep=t)
        loss = MSE(pred_velocity, velocity)
    ▼
[backward → AdamW → cosine_with_min_lr → save_interval → pytorch_model.pt]
```

### 3.2 推理（真机）端到端数据流

```
robot_client (unitree_deploy)
    │  HTTP POST /act payload {observations:[{full_image, *_wrist, state, instruction, task_name?}]}
    │  (over SSH tunnel localhost:8777 → server:8777)
    ▼
deployment/model_server/run_real_eval_server.py
    │  prepare_images_for_vla: resize_image_for_policy(lanczos3) → center_crop_image(0.9)
    │  processor.apply_chat_template + process_vision_info → batch_input
    │  normalize_proprio(state) → batch_input["state"]
    ▼
Unifolm_VLA.predict_action(qwen_inputs):
    qwen_vl_interface → last_hidden
    action_model.predict_action:
        x = randn(B, action_horizon, action_dim)
        for t in range(num_inference_timesteps=4):
            DiT(...) → velocity
            x += dt * velocity
        return x  ([-1, 1] 归一化空间)
    ▼
unnormalize_action(BOUNDS_Q99 / BOUNDS) → 真实关节 / EEF 单位
    ▼
JSONResponse(json_numpy.dumps(action))  → 客户端按 NUM_ACTIONS_CHUNK 顺序消费
```

### 3.3 推理（LIBERO 仿真）端到端数据流

```
LIBERO env (OffScreenRenderEnv) → obs (agentview + eye_in_hand + state)
    ▼
prepare_observation:
    img[::-1, ::-1] (180° 翻转，与训练对齐)
    resize_image_for_policy(lanczos3 → 224×224)
    state = concat(eef_pos, axisangle(eef_quat), gripper_qpos)  shape (8,)
    ▼
maintain obs_queue (maxlen=window_size=2)
when action_queue 空:
    get_action_state(obs_queue, task_desc, model):
        prepare_images_for_vla (resize + center crop)
        processor → qwen_inputs (含两帧 + 双 wrist 图 + CoT prompt)
        Unifolm_VLA_Inference.step:
            normalize_proprio(state) → batch_input["state"]
            vla.predict_action → normalized_actions  shape (NUM_ACTIONS_CHUNK=8, 7)
            unnormalize_action → 真实动作
    action_queue.extend(actions)
    ▼
process_action(a):
    normalize_gripper_action: gripper [0,1] → [-1,1] + binarize
    invert_gripper_action: 翻转 sign（LIBERO 期望 -1=open, +1=close）
    ▼
env.step(action) → next obs ; 录像 + log；超过 max_steps 即失败。
```

---

## 4. 训练 / 推理关键超参速查

| 项 | 默认值 | 来源 |
|---|---|---|
| optimizer | AdamW(β=[0.9,0.95], wd=1e-8, eps=1e-8) | `unifolm_vla_train.yaml` |
| LR (base / qwen / action_model) | 1e-5 / 1e-5 / 1e-4（CLI 可覆盖为 4e-5） | yaml + sh |
| LR scheduler | `cosine_with_min_lr`, `min_lr=5e-7`, `num_warmup_steps=5000` | yaml |
| max_train_steps | 100k（yaml） / 150k（sh CLI 覆盖） | yaml + sh |
| save_interval / eval_interval | 5k / 100（yaml） 或 10k / 500（sh） | yaml + sh |
| batch | per_device=16（yaml）/ 6（G1 sh）/ 16（LIBERO sh） × 8 GPUs | yaml + sh |
| window_size | 1（G1） / 2（LIBERO） | sh |
| Action chunk (`NUM_ACTIONS_CHUNK`) | 25 (G1/G1_EE_6D/G1_STACK_BLOCK/ALOHA), 8 (LIBERO), 5 (BRIDGE/FRACTAL) | `constants.py` |
| Action / Proprio dim | 16 (G1 关节) / 23 (G1 EE_R6) / 7-8 (LIBERO) / 14 (ALOHA) | `constants.py` |
| Normalization | BOUNDS_Q99 (G1_EE_6D / LIBERO) / BOUNDS (G1 关节 / ALOHA) | `constants.py` |
| Diffusion config | DiT 16 层, 32 头, head_dim=48, dropout=0.2, interleave_self_attention=true, ada_norm | yaml |
| Flow matching | Beta(α=1.5, β=1.0), s=0.999, 1000 buckets, 4 inference steps | yaml |
| `repeated_diffusion_steps` | 8（forward 时 batch 复制 8 倍计算 loss，CogACT 风格） | yaml |
| Mixed precision | bf16 + DeepSpeed Zero-2 | accelerate yaml + ds_config |
| Gradient | clip=1.0, accumulation_steps=1 | yaml |

---

## 5. 与 UnifoLM-WMA-0 的关系与差异

| 维度 | **UnifoLM-WMA-0**（World-Model-Action） | **UnifoLM-VLA-0**（Vision-Language-Action） |
|---|---|---|
| 主干 | DynamiCrafter 风格 latent video UNet（3D conv + 时间注意力） | Qwen2.5-VL（自回归 VLM） |
| 动作头 | 1D `ConditionalUnet1D`（diffusion policy 思路）+ 1D 状态头 | DiT cross-attention + Flow Matching（rectified flow） |
| 模式 | 三模式：基础视频生成 / 决策模式 / 交互仿真模式 | 单模式：观测 → 动作 chunk |
| 数据 | LeRobot v2.1 → CSV+H5+视频，自有 `WMAData` | LeRobot → HDF5 → RLDS（TFDS+dlimp+OXE 注册表） |
| 训练框架 | PyTorch Lightning（`scripts/trainer.py`） | accelerate + DeepSpeed Zero-2（`train_unifolm_vla.py`） |
| 推理目标 | 视频生成 + 动作 / 状态联合去噪 | 仅动作（4 步欧拉积分） |
| 部署 | FastAPI（`real_eval_server.py`） | FastAPI（`run_real_eval_server.py`） |
| 数据集 | OXE + 5 个 Unitree 数据集（双臂 / G1 装箱） | 12 个 Unitree G1 数据集 + LIBERO + ALOHA + 全 OXE |
| 共享 | `unitree_deploy/` 真机部署栈 | 同左（VLA 仓库注释明确指向 WMA 仓库的 unitree_deploy 子模块） |

两者并非互斥：WMA 把"先想象再决策"作为 inductive bias，VLA 走更通用的 VLM + diffusion 路径，更易于 scale 到大规模图文数据继续预训练。

---

## 6. 已知冗余 / dead code（清理建议）

阅读时发现以下仅作存档、对当前主路径无实质贡献的代码点，新人可放心跳过：

1. **`model/utils/pooling_utils.py`**：依赖未引入仓库的 `unifolm_vla.model.modules.vggt` 子包，从 InternVLA-M1 / VGGT 系遗留。`Unifolm_VLA.forward` 不调用。
2. **`rlds_dataloader/action_tokenizer.py`**：早期 OpenVLA "动作即 token" 路线的 256-bin tokenizer，当前用 flow matching 的连续动作，全仓库无 import 引用。
3. **`training/trainer_utils/trainer_tools.py`**：与同目录 `metrics.py` 几乎逐字重复（仅 `dist.barrier()` 守卫细节略不同）；训练入口只 import `metrics`。
4. **`base_framework.py`** 中 `_check_unnorm_key` 与 `get_action_stats` 各被定义两次，签名一致；后定义会覆盖前定义，留作 API 兼容性 stub。
5. **`prepare_data/hdf5_to_rlds/rlds_dataset/rlds_dataset.py`** 第 232 行 `train` split glob 路径写死，必须用户手改后才能 `tfds build`。
6. **`Unifolm_VLA.forward` 与 `train_unifolm_vla._train_step` 的 autocast 混用**：framework 内部已 bf16 + fp32 切换，外层 `_train_step` 又包了 bf16 autocast，存在轻微重复但不影响正确性。

---

## 7. 端到端定制清单（在自己的数据集上微调）

按依赖顺序：

1. **数据**：把数据整理为 LeRobot v2.1 → 跑 `convert_lerobot_to_hdf5.py` → 跑 `tfds build`（先改 `rlds_dataset.py` 第 232 行的 glob）。最终目录形如 `<root>/<dataset_name>/1.0.0/`。
2. **注册数据集**：在以下 4 处添加同名条目：
   - `rlds_dataloader/datasets/rlds/oxe/configs.py` —— `OXE_DATASET_CONFIGS[<dataset_name>]`，给 image_obs_keys / state_obs_keys / state_encoding / action_encoding（参考 G1 系列）。
   - `rlds_dataloader/datasets/rlds/oxe/transforms.py` —— 新增 `<dataset_name>_dataset_transform(traj)` 函数 + 注册到 `OXE_STANDARDIZATION_TRANSFORMS`。
   - `rlds_dataloader/datasets/rlds/oxe/mixtures.py` —— `OXE_NAMED_MIXTURES['<your_mix>'] = [(<dataset_name>, weight), ...]`。
   - `rlds_dataloader/datasets/datasets.py:107` —— 如需启用双 wrist，在 `if <data_mix> in ...` 分支添加，使 `load_camera_views` 自动包含 `left_wrist/right_wrist`。
3. **常量**：在 `rlds_dataloader/constants.py` 增/调整 `<YOUR>_CONSTANTS`，并扩充 `detect_robot_platform()` 关键字。否则全局 `NUM_ACTIONS_CHUNK / ACTION_DIM / PROPRIO_DIM` 会回退到 `G1_EE_6D`。
4. **训练 yaml**：编辑 `config/training/unifolm_vla_train.yaml` 的 `framework.action_model.action_dim/state_dim`、`window_size`，确认 `cross_attention_dim` 留空让代码动态对齐。
5. **训练脚本**：克隆 `scripts/run_scripts/run_unifolm_vla_train.sh`，改 `base_vlm`、`oxe_data_root`、`data_mix`、`per_device_batch_size`、`num_processes`。
6. **推理**：用 `deployment/model_server/run_real_eval_server.py` 起服务，`--unnorm_key=<dataset_name>`；客户端按 `unitree_deploy/robot_client.py` 模板拼 payload。LIBERO 类仿真则参考 `experiments/LIBERO/eval_libero.py` 的 obs / action 桥接。

按此清单走通，新数据集即可纳入 12 任务联训或单任务微调。

---
