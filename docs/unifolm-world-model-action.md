# UnifoLM-WMA-0 仓库全量解析

> 本文针对 `unitree-notes/unifolm-world-model-action`（UnifoLM 家族下的 World-Model–Action 框架）进行端到端梳理：先给出整体定位与全量目录文件表，再分子系统逐文件深入说明每个 Python / 配置 / 脚本文件实现的功能。

仓库根：`/home/helios/unitree/unitree-notes/unifolm-world-model-action`
版本：v0.0.1（开源时间：2025-09-15 训练/推理代码 + 权重；2025-09-22 真机部署代码）
许可：BSD-3-Clause
作者：Unitree Embodied AI R&D Team

---

## 1. 仓库概览（What & Why）

UnifoLM-WMA-0 是 Unitree 开源的"世界模型 + 动作头"框架，目标是给跨形态机器人学习提供一个能"理解物理交互"的世界模型。这个世界模型有两个产品形态：

- **(a) Simulation Engine（仿真引擎）**：作为一个交互式仿真器，给定历史观测/动作 → 自回归生成未来 RGB 视频（合成数据）。
- **(b) Policy Enhancement（策略增强）**：把世界模型与一个 1D 扩散动作头联起来，借助"先想象再决策"的方式，在扩散过程中同时去噪 video latent 与 action chunk，实现策略输出。

模型的核心是一个**条件视频扩散网络（latent video UNet）**，骨架沿用 DynamiCrafter，但显著扩展了：
- 在交叉注意中拼入 `agent_state`、`agent_action`、`text_instruction`、`image` 四路 token；
- 侧挂一个 `ConditionalUnet1D`（沿用 Diffusion Policy 思路）作为动作扩散头，以及一个对应的状态扩散头；
- 通过开关 `decision_making_only` / `sim_mode` 控制三种训练/推理模式（基础视频生成 / 决策模式 / 交互仿真模式）。

支持的官方权重：
- $\text{UnifoLM-WMA-0}_{Base}$：在 Open-X-Embodiment 上微调的基础世界模型。
- $\text{UnifoLM-WMA-0}_{Dual}$：在 5 个 Unitree 数据集（Z1 单/双臂搬箱、双臂收笔、G1 装箱）上联合训练的决策+仿真双模式模型。

子项目：`unitree_deploy/` 是配套的真机部署栈（FastAPI 客户端 + Unitree G1/Z1/Dex1 控制 + RealSense/USB/网络相机）。

---

## 2. 全量目录与文件路径表

下表覆盖仓库下每个目录与每个源码/配置/脚本文件（README/LICENSE 等元文件已合并说明）。

### 2.1 仓库根

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `README.md` / `README_cn.md` | 文档 | 项目主页：背景、Demo GIF、安装、Checkpoint 与数据集表、训练/三种推理流程的命令、代码结构总览。中文版与英文版内容一一对应。 |
| `LICENSE` | 法律 | BSD-3-Clause 许可证全文。 |
| `pyproject.toml` | 构建 | 包名 `unifolm_wma` (v0.0.1)，要求 Python==3.10.18；锁定 35 个依赖（torch 2.3.1 + xformers 0.0.27 + pytorch-lightning 1.9.3 + diffusers 0.30.2 + transformers 4.40.1 + open-clip-torch 2.22.0 + decord + kornia + omegaconf 等）。`tool.setuptools.packages.find` 指向 `src/`。 |
| `.gitmodules` | 依赖 | 唯一子模块：`external/dlimp`（kvablack/dlimp，TFDS 数据加载库，需要在 `external/dlimp` 下额外 `pip install -e .`）。 |
| `.gitignore` | 构建 | 忽略 `*.pyc`、缓存、`results/`、checkpoints、wandb 等。 |
| `assets/` | 媒体 | 给 README 用的 GIF / PNG。`gifs/` 含 `real_z1_stackbox.gif`、`real_dual_stackbox.gif`、`real_cleanup_pencils.gif`、`real_g1_pack_camera.gif`；`pngs/` 含 `dm_mode.png`（决策模式架构图）、`sim_mode.png`（仿真模式架构图）。 |

### 2.2 `configs/` — 训练与推理 YAML

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `configs/train/config.yaml` | 训练配置 | 主训练配置：v-parameterization + zero-SNR、`hybrid` conditioning、动作/状态维度统一为 16，`unet_head_config` 指定 `ConditionalUnet1D` 动作头；`data` 段定义多数据集加权采样（5 个 Unitree 数据集各 0.2）。`lightning.trainer` 段：300k steps、grad clip 0.5、accumulate 2、fp16；ImageLogger 每 20k 步出图，ddim_steps=16，guidance_rescale=0.7。 |
| `configs/inference/base_model_inference.yaml` | 推理配置 | "基础视频生成"模式（`base_model_gen_only=True`）：仅输出未来视频，单帧观测、`n_obs_steps_*=1`、单数据集 `unitree_g1_pack_camera`。 |
| `configs/inference/world_model_decision_making.yaml` | 推理配置 | "决策模式"（`decision_making_only=True`）：跳过视频解码，只输出动作；`n_obs_steps_*=2`，单数据集，frame_stride=2。 |
| `configs/inference/world_model_interaction.yaml` | 推理配置 | "交互仿真模式"：`decision_making_only=False`、`n_obs_steps=2`，5 数据集均衡，与训练配置对齐，用于自回归长视频展开。 |

### 2.3 `prepare_data/` — 数据预处理

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `prepare_data/prepare_training_data.py` | 脚本 | 把 LeRobot v2.1 格式数据（`source_dir/<dataset>/{data,meta,videos}`）转成训练用结构（`target_dir/{videos,transitions,<dataset>.csv}`）。核心步骤：①遍历 episode parquet → 抽取 `action` / `observation.state`，存为每 episode 一个 H5；② 用 `ffprobe` 检测 AV1 编码并用 `ffmpeg` 转为 H.264（`crf=23, preset=slow`）；③ 累计全局 min/max/mean/std 写入 `meta_data/stats.safetensors`；④ 生成 CSV 索引（`videoid, data_dir, instruction, embodiment` 等列）。CLI：`--source_dir / --dataset_name / --robot_name / --target_dir`。 |

### 2.4 `scripts/` — 训练与评估入口

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `scripts/trainer.py` | Python 入口 | 训练主入口：合并多份 base config 与 CLI override（OmegaConf）；`instantiate_from_config` 创建 model/data；`scale_lr=True` 时按 `num_gpus * batch_size` 缩放学习率；注册 `SIGUSR1`(强制 ckpt) / `SIGUSR2`(pudb 调试) 信号；最后 `trainer.fit(model, data)`。 |
| `scripts/train.sh` | Shell | 8 GPU 单机分布式训练样板：`torch.distributed.launch --nproc_per_node=8` 调 `trainer.py --base configs/train/config.yaml --train --name $name --logdir $save_root`。 |
| `scripts/run_base_model_inference.sh` | Shell | 调 `evaluation/base_model_inference.py`：`ddim_steps=16, guidance_scale=1.0, guidance_rescale=0.7, eta=1.0`，`height=320, width=512, video_length=16`，`timestep_spacing='uniform_trailing'`、`perframe_ae`。 |
| `scripts/run_real_eval_server.sh` | Shell | 启动真机评估 FastAPI 服务（`evaluation/real_eval_server.py`），按 `datasets=()` 数组依次拉起，`frame_stride=2`。 |
| `scripts/run_world_model_interaction.sh` | Shell | 跑交互仿真（`evaluation/world_model_interaction.py`）：`ddim_steps=50`、`n_action_steps=16`、`exe_steps=16`，可对 5 个数据集分别配 `n_iters=[12,7,11,8,11]` 与 `fses=[4,4,4,4,6]`。 |
| `scripts/evaluation/eval_utils.py` | 工具 | 评估期共享小工具：`VideoFrame` HF Datasets feature；`populate_queues(queues, batch)` 滑动窗口；`log_to_tensorboard(writer, video, fps)` 视频网格化写 TB。 |
| `scripts/evaluation/base_model_inference.py` | 入口 | 基础视频生成：`load_model_checkpoint` → `load_data_prompts` → `image_guided_synthesis`（构造 text+image 的混合 cond，调 `DDIMSampler`，分类器自由引导）→ `decode_first_stage` → 多代续接拼成长视频写 mp4。支持多 GPU 切片。 |
| `scripts/evaluation/real_eval_server.py` | 入口 | 真机决策 FastAPI 服务：`Server` 类初始化（加载模型、normalizer、噪声形状）；`/predict_action` POST 端点接收 `{observation.images.top, observation.state, action(zeros), language_instruction}` → 归一化 → `image_guided_synthesis` 推理 → 反归一化 → 返回 `{result, action, desc}`。 |
| `scripts/evaluation/world_model_interaction.py` | 入口 | 交互仿真长展开：`prepare_init_input` 从 H5/PNG 拼初始 `n_obs_steps` 历史 → `image_guided_synthesis_sim_mode` 一次跑两阶段（决策阶段 sim_mode=False 出动作 → 仿真阶段 sim_mode=True 出未来视频/状态）→ 用预测视频前 `exe_steps` 帧追加进 deque 进入下一轮 → 写 dm/wm 两类 mp4 与拼接的全量 mp4，TensorBoard 同步可视化。 |

### 2.5 `examples/` — 推理样例

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `examples/base_model_prompts/` | 数据 | 给 `base_model_inference.py` 用的 prompts（图像 + 文本指令 + CSV）。 |
| `examples/world_model_interaction_prompts/` | 数据 | 给 `world_model_interaction.py` 用的初始观测：`images/<dataset>/*.png` 起始帧、`transitions/<dataset>/*.h` 状态-动作转移（用于初始 normalize 与状态对齐）、`<dataset>.csv` 索引。 |

### 2.6 `src/unifolm_wma/` — 模型核心 Python 包

#### 2.6.1 包根

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `src/unifolm_wma/__init__.py` | 包标识 | 空文件，仅声明 `unifolm_wma` 命名空间。 |

#### 2.6.2 `data/` — 数据集与归一化

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `data/base.py` | 抽象类 | `Txt2ImgIterableBaseDataset(IterableDataset)`：定义 `num_records / valid_ids / size / __iter__` 抽象接口，给可迭代数据集提供统一 hook。 |
| `data/normolize.py` | 归一化 | `create_stats_buffers / Normalize / Unnormalize`：支持 `mean_std`（z-score）与 `min_max`（线性映射到 `[-1,1]`）两种模式；图像 stats 按 channel-first 形状广播。 |
| `data/utils.py` | 工具 | `unflatten_dict`（反扁平化）、`load_episode_data_index`、`load_stats`：从 safetensors 读 episode 索引和归一化统计。 |
| `data/wma_data.py` | 主数据集 | `WMAData(Dataset)`：核心训练样本生产者。基于 decord 加载视频，配合 H5 转移文件得到 `(video, observation.image, pre_action, action, observation.state, next.state, action_mask, state_mask, instruction)` 一整批张量。支持 `n_obs_steps` 历史窗口、`max_action_dim`/`max_state_dim`（默认 7，统一向量空间到 16 时由配置覆盖）零填充、可选 `individual_normalization`。视频按 `frame_stride` 与 `fixed_fps` 动态调步，分辨率 `[H,W]` 经 resize-center-crop 得到 `[-1,1]` 张量。 |

#### 2.6.3 `models/` — 扩散主模型

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `models/__init__.py` | 包标识 | 空。 |
| `models/autoencoder.py` | VAE | `AutoencoderKL(pl.LightningModule)`：DynamiCrafter / SD 风格 VAE 包装；`encode→quant_conv→DiagonalGaussianDistribution`；`decode→post_quant_conv→Decoder`；扩散训练时整体冻结，提供 `encode_first_stage / decode_first_stage` 给上层用。还有 `IdentityFirstStage`（不编码、原样透传，便于像素空间消融）。 |
| `models/ddpms.py` | 扩散主体 | **2524 行的核心文件**：自下而上的三层结构 —— `DDPM` 基类（前向/反向、参数化 eps/x0/v、EMA、ddim_log）→ `LatentDiffusion`（加上 VAE 与文本/图像 cond stage、CFG dropout、动态 scale_factor）→ `LatentVisualDiffusion`（再加 `image_proj_model`、动作/状态 1D 扩散头与 `decision_making_only / sim_mode` 三流损失）。底部的 `DiffusionWrapper` 把条件路由按 `conditioning_key='hybrid'` 拆分成 `c_concat / c_crossattn / c_crossattn_action`。 |
| `models/samplers/ddim.py` | 采样器 | `DDIMSampler`：`make_schedule` 预算 `ddim_alphas/ddim_sigmas`；`sample` 三返回值（video/action/state）；`p_sample_ddim` 单步：先 v-参数转换，再做分类器自由引导（对视频 / 动作 / 状态各做一遍），最后用预先计算的 `a_prev / sigma_t` 推 `x_{t-1}`；动作/状态分支走独立的 dp_ddim_scheduler。 |

#### 2.6.4 `models/diffusion_head/` — 动作扩散头（Diffusion Policy 风格）

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `diffusion_head/__init__.py` | 包标识 | 空。 |
| `diffusion_head/base_nets.py` | 基础块 | `Module / ConvBase` 抽象（带 `output_shape()`）；`SpatialSoftmax`：在 (C,H,W) 上做空间 softmax 得到 K 个关键点 (K,2) 期望坐标，可选 σ；用于把 imagen 中间特征压缩成可由 1D UNet 消化的 condition。 |
| `diffusion_head/conditional_unet1d.py` | 1D 扩散动作 UNet | `ConditionalUnet1D` 输入 `(B,T,input_dim)` 动作序列、timestep、`imagen_cond`（世界模型 latent）、低维 `cond`（图像/state）。down/mid/up 由 `ConditionalResidualBlock1D` 与 `ActionLatentImageCrossAttention` 交替组成。`cond_predict_scale=True` 时用 FiLM 调制 (scale, bias)；通过 `proj_in_action / proj_in_horizon` 在动作维和时间步维各做一次线性投影。`down_dims=[256,512,1024,2048], kernel_size=5`。 |
| `diffusion_head/conv1d_components.py` | 卷积块 | `Conv1dBlock`、`Downsample1d`、`Upsample1d`：标准 1D conv + GroupNorm + Mish 块，支撑 ConditionalUnet1D。 |
| `diffusion_head/ema_model.py` | EMA | `EMAModel`：Diffusers 风格 EMA，按 `inv_gamma / power / min_decay / max_decay` 自适应衰减，给动作头做权重平均。 |
| `diffusion_head/positional_embedding.py` | 位置编码 | 经典 `SinusoidalPosEmb`：把 timestep 标量映射到 `dim` 维 sin/cos 向量。 |
| `diffusion_head/common/__init__.py` | 包标识 | 空。 |
| `diffusion_head/common/lr_scheduler.py` | 调度 | 把 diffusers 的 `get_scheduler` 包装成可由 OmegaConf 配置的 LR 调度器；含选择性调度（仅调动作 UNet 的 lr）。 |
| `diffusion_head/common/module_attr_mixin.py` | Mixin | `ModuleAttrMixin`：给 `nn.Module` 提供 `device / dtype` 属性（取首个 buffer/param）。 |
| `diffusion_head/common/pytorch_util.py` | 工具 | 通用 `dict_apply / replace_submodules`、参数遍历等。 |
| `diffusion_head/common/tensor_util.py` | 张量工具 | 960 行：`recursive_dict_list_tuple_apply` 系列对嵌套结构的统一映射；含 `to_device / to_tensor / to_numpy / flatten / pad_sequence / time_distributed`（按 (B,T) 切合并）等。 |
| `diffusion_head/vision/__init__.py` | 包标识 | 空。 |
| `diffusion_head/vision/crop_randomizer.py` | 数据增强 | `CropRandomizer`：训练随机多裁剪、推理中心裁剪；`forward_in/out` 控制裁剪与多裁剪的平均；可选 `pos_enc` 编码裁剪坐标。 |
| `diffusion_head/vision/model_getter.py` | 工厂 | 30 行：按字符串名取 ResNet / ViT 视觉主干（torchvision/timm）。 |
| `diffusion_head/vision/multi_image_obs_encoder.py` | 多视角编码 | `MultiImageObsEncoder`：把 `obs_dict={'image':(B,3,H,W),'state':(B,D),...}` 映射为单个 embedding，可共享或独立 backbone，可选 `SpatialSoftmax` / `DinoSigLIP`。 |

#### 2.6.5 `modules/` — UNet 主干与编码器

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `modules/__init__.py` | 包标识 | 空。 |
| `modules/attention.py` | 注意力 | 806 行：`CrossAttention`（带相对位置偏差、xformers 内存高效路径、可学习的 `alpha_ctx/alpha_cas/alpha_caa` 跨模态权重、可选 agent_action causal mask）；`BasicTransformerBlock`（self-attn + cross-attn + FFN）；`SpatialTransformer`（2D，把 `(B,C,H,W)` 摊到 token）；`TemporalTransformer`（1D 沿时间轴）；`FeedForward / GEGLU / LinearAttention / SpatialSelfAttention`。 |
| `modules/encoders/condition.py` | 条件编码 | 630 行：`FrozenT5Embedder`、`FrozenCLIPEmbedder`、`FrozenOpenCLIPEmbedder`、`FrozenOpenCLIPImageEmbedder(V2)`、`ClipImageEmbedder`、`FrozenCLIPT5Encoder`、`PerceiverAttention + SATokenProjector`、以及若干 `LinearProjector / MLPProjector / FusedMLPProjector`。共同接口：返回 `(B, N_tokens, D)`，让上游交叉注意直接消费。 |
| `modules/encoders/resampler.py` | Perceiver | 153 行：`Resampler` 把任意 `(B,N_patches,D_in)` 的图像 token 用一组可学习 latents（含可选 `video_length` 维）压成 `(B, num_queries, D_out)`，并 `proj_out + LayerNorm`。 |
| `modules/networks/ae_modules.py` | VAE 构件 | 1005 行：`ResnetBlock`（FiLM/加法时间条件）、`AttnBlock / LinAttnBlock`、`Downsample / Upsample`、完整的 `Encoder / Decoder` 与 `Model`（含 timestep）、`SimpleDecoder / UpsampleDecoder`、`LatentRescaler`（多尺度因子缩放）；为 `AutoencoderKL` 提供底层堆栈。 |
| `modules/networks/wma_model.py` | 世界模型 UNet | 848 行：`WMAModel` 是真正的视频扩散主干。`Input/Middle/Output` 块由 `ResBlock + SpatialTransformer + TemporalTransformer` 交错组成；`TimestepEmbedSequential` 在前向时按子模块类型自动 reshape；可选 `fs_condition` 注入 FPS；侧面挂 `action_unet` 与 `state_unet` 两个 head。Cross-attention context 在序列轴上拼接 `[agent_state(n_obs_steps) | agent_action(T·num_stem_token) | text(77) | image(T·HW)]` 后按段切分。 |
| `modules/vision/__init__.py` | 包标识 | 空。 |
| `modules/vision/base_vision.py` | Vision 抽象 | 244 行：`VisionBackbone`（约定 `featurizer + image_transform`）；`TimmViTBackbone` 通用 TIMM ViT 加载器，支持 `resize-naive / resize-crop / letterbox`，monkey-patch `forward()` 取倒数第二层 patch 特征（FSDP-safe），并暴露 `get_fsdp_wrapping_policy()`。 |
| `modules/vision/dinosiglip_vit.py` | 双 ViT | 273 行：`DinoSigLIPViTBackbone` 把 DINOv2 大模型 + SigLIP 并联，特征拼接后线性/MLP 投影到统一输出维；`DinoSigLIPImageTransform` 维护两套各自的 mean/std 归一化；可选冻结。 |

#### 2.6.6 `utils/` — 工程与训练工具

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `utils/basics.py` | 基础 | `disabled_train`（冻结 train 模式切换）、`zero_module / scale_module`、`conv_nd / linear / avg_pool_nd`、`nonlinearity`、`GroupNormSpecific`（强制 fp32）、`HybridConditioner`（拼接两个 cond stage）。 |
| `utils/callbacks.py` | LightningCB | `ImageLogger`：调用 `model.log_images` 周期性写 TB / 本地，并按 batch 汇总 fps/frame_stride 分布到 JSON；`CUDACallback`：监控显存峰值与 epoch 耗时。 |
| `utils/common.py` | 训练通用 | `gather_data`（多卡聚合）、`autocast` 装饰器、`extract_into_tensor`（按 t 索引 schedule）、`noise_like`、`default / exists / mean_flat / ismap / isimage`、`checkpoint`（梯度检查点）。 |
| `utils/data.py` | 数据模块 | `DataModuleFromConfig(LightningDataModule)`：按权重组合多数据集 `WeightedRandomSampler`，统一传递 `meta_path / transition_dir / dataset_name`；`worker_init_fn` 把 IterableDataset 切片；`WrappedDataset` 包通用对象。 |
| `utils/diffusion.py` | 扩散工具 | `timestep_embedding`（sin/cos）、`make_beta_schedule(linear/cosine/sqrt_linear/sqrt)`、`make_ddim_timesteps(uniform/uniform_trailing/quad)`、`make_ddim_sampling_parameters`、`betas_for_alpha_bar`、`rescale_zero_terminal_snr`、`rescale_noise_cfg`（缓解高 CFG 过饱和）。 |
| `utils/distributions.py` | 分布 | `AbstractDistribution / DiracDistribution / DiagonalGaussianDistribution`（`sample / mode / kl / nll`），`normal_kl` 标量化广播 KL。 |
| `utils/ema.py` | EMA | `LitEma(nn.Module)`：可训练参数 shadow buffer，`decay=0.9999` 与步数自适应；`copy_to / store / restore` 支持验证时切换 EMA 权重。 |
| `utils/nn_utils.py` | 投影 | `LinearProjector / MLPProjector / FusedMLPProjector`：跨模态维度对齐用的 2 层 MLP / 双层融合 MLP。 |
| `utils/projector.py` | 跨模态注意 | `PerceiverAttention + TokenProjector`：可学习 latent 与图像特征做交叉注意，多层堆叠后输出固定 token；附 `FeedForward`；动作/状态/图像 token 化对齐入口之一。 |
| `utils/save_video.py` | 可视化 | 帧 / 张量 → mp4 的多入口（`frames_to_mp4 / tensor_to_mp4 / tensor2videogrids`）、`log_local`（落盘视频/图像/文本）、`fill_with_black_squares`（视频补长）、`npz_to_video_grid`。h264 + crf=10 默认。 |
| `utils/train.py` | 训练装配 | `init_workspace` 建 `checkpoints/configs/loginfo`；`get_trainer_callbacks` 注册 ModelCheckpoint/ImageLogger/LearningRateMonitor/CUDACallback；`get_trainer_logger`（TB/CSV）；`get_trainer_strategy`（默认 DDPSharded）；`load_checkpoints` 兼容标准 state_dict 与 DeepSpeed；`get_num_parameters` 把 World Model / Action Head / State Head 分项打印。 |
| `utils/utils.py` | 通用 | `count_params`、`check_istarget`、`instantiate_from_config({target, params})`、`get_obj_from_str`、`load_npz_from_*`、`resize_numpy_image`（Lanczos4）、`setup_dist`（NCCL）。 |

### 2.7 `unitree_deploy/` — 真机部署子项目

#### 2.7.1 顶层

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `unitree_deploy/README.md` | 文档 | 部署环境装机、image_server / Dex1 / Z1 控制器拉起步骤、三套机器人（G1+Dex1 / Z1 单臂 / Z1 双臂）的端到端命令。 |
| `unitree_deploy/pyproject.toml` | 构建 | 包名 `unitree_deploy` (v0.0.3)，依赖 pinocchio / torch / dm_env / rerun-sdk / unitree_sdk2_python / opencv-python；可选 extra `[lerobot]`。 |
| `unitree_deploy/docs/GettingStarted.md` | 文档 | 入门：四个扩展点（构造 robot、加 arm、加 camera、加 endeffector）的链接。 |
| `unitree_deploy/docs/README_cn.md` | 文档 | README 中文版。 |
| `unitree_deploy/docs/build_robot.md` | 文档 | 如何用 `UnitreeRobotConfig` 组合 cameras/arm/endeffector 字典构造机器人。 |
| `unitree_deploy/docs/add_robot_arm.md` | 文档 | `Arm` 协议（`read/write/IK`）扩展指南，含 `motors` 字典（name→(index,model)）与后台收发线程模板。 |
| `unitree_deploy/docs/add_robot_camera.md` | 文档 | `Camera` 协议（`read/async_read`）扩展指南，OpenCV / RealSense / 网络客户端三种实现样板。 |
| `unitree_deploy/docs/add_robot_endeffector.md` | 文档 | `EndEffector` 协议扩展指南，DDS 驱动 Dex1 夹爪。 |

#### 2.7.2 入口与环境

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `unitree_deploy/scripts/robot_client.py` | 入口 | 真机推理客户端：`LongConnectionClient` 维 HTTP 长连接打 `/predict_action`；`ACTTemporalEnsembler` 用 ACT 论文的指数加权平均融合连续 chunk；主循环 = 取观测 → BGR→RGB & 归一化 → 进 deque(`observation_horizon`) → POST → temporal ensemble → 执行 `exe_steps` 步动作。CLI 含 `--robot_type / --action_horizon / --exe_steps / --observation_horizon / --language_instruction / --control_freq`。 |
| `unitree_deploy/unitree_deploy/real_unitree_env.py` | 类 | `UnitreeEnv(robot_type, dt, init_pose_arm)`：连接所有设备 → 30Hz 控制；`get_observation(t)` 返回 `dm_env.TimeStep`（qpos + 全零 qvel/effort + RGB images dict，BGR 自动转 RGB）；`step(action)` 调 robot.send_action 并 `precise_wait` 到下一拍。 |
| `unitree_deploy/unitree_deploy/eval_dataset_env.py` | 类 | `DatasetEvalEnv(repo_id, episode_index, visualization)`：用 LeRobotDataset 离线回放，记录预测动作并最后画 GT vs 预测对比，便于无机器对照评测。 |

#### 2.7.3 `unitree_deploy/robot/` — 机器人组合层

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `robot/robot.py` | 主类 | `UnitreeRobot`：按 config 实例化 `cameras / arm / endeffector` 三组设备字典；`capture_observation()` 把所有 arm 关节、所有 endeffector 关节、所有相机异步读出的 RGB 拼成 `{"observation.state":Tensor, "observation.images.<name>":Tensor}`；`send_action(action, t_target)` 按各 arm/endeffector 的 motor 索引切片下发，第一次用 `drive_to_waypoint`，之后切到 `schedule_waypoint`（实时插值）。 |
| `robot/robot_configs.py` | 配置 | `UnitreeRobotConfig` 基类 + 4 个预设：`Z1_Realsense_RobotConfig`、`Z1dual_Dex1_Realsense_RobotConfig`、`Z1dual_Dex1_Opencv_RobotConfig`、`G1_Dex1_Imageclint_RobotConfig`；含 `g1_motors`(14 轴) / `z1_motors`(7 轴) / `z1_dual_motors`(12 轴) 等电机表。 |
| `robot/robot_utils.py` | 工厂 | `make_robot_config / make_robot`：按 `robot_type` 字符串分发到对应配置与构造，统一返回符合 `Robot` 协议（含 `connect / capture_observation / send_action / disconnect`）的对象。 |

#### 2.7.4 `unitree_deploy/robot_devices/` — 硬件驱动

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `robot_devices/robots_devices_utils.py` | 工具 | 设备字典注册与 device factory 公共逻辑。 |
| `robot_devices/arm/arm_indexs.py` | 索引 | `G1_29_JointIndex`（35 维全身→14 维臂部映射）、`Z1GripperArmJointIndex` 等关节索引常量。 |
| `robot_devices/arm/configs.py` | 配置 | `Z1ArmConfig / Z1DualArmConfig / G1ArmConfig`：电机表、init_pose、`control_dt`（Z1 1/500，G1 多档 kp/kd）、DDS 话题（`rt/lowcmd, rt/lowstate`）、`max_pos_speed` 等。 |
| `robot_devices/arm/utils.py` | 工厂 | `Arm` 协议定义 + `make_arm_motors_buses_from_configs()`：按 type 分发出 `Z1ArmController / G1_29_ArmController / Z1_12_ArmController`。 |
| `robot_devices/arm/g1_arm.py` | 驱动 | `G1_29_ArmController`：`unitree_sdk2py` DDS 发布订阅，subscribe/control 后台线程；`read_current_arm_q()` 返回 14 维（左 7 + 右 7）；`write_arm()` 用 `JointTrajectoryInterpolator` 平滑（受 `max_pos_speed` 约束），构造 `LowCmd_` 含 CRC 校验下发；包装 `G1_29_ArmIK` 调 IK。 |
| `robot_devices/arm/g1_arm_ik.py` | IK | `G1_29_ArmIK`：pinocchio 加载 `g1_body29_hand14.urdf`，锁住腿/腰/手指 → reduce 到肩肘腕 14 维；CasADi + pinocchio 数值优化求 IK，MeshcatVisualizer 选用，`WeightedMovingFilter` 平滑结果。 |
| `robot_devices/arm/z1_arm.py` | 驱动 | `Z1ArmController`：加载 `unitree_arm_interface.so` 创建 `ArmInterface`；`read_current_arm_q()` 6 或 7 维（含夹爪）；`write_arm()` 同样走 JointTrajectoryInterpolator + `setControlGain(kp,kd)` + `sendRecv()`，实时 500 Hz。 |
| `robot_devices/arm/z1_arm_ik.py` | IK | `Z1_Arm_IK`：`z1_gripper.urdf` + pinocchio CasADi，处理末端 XYZ+RPY；提供 `fk(q)` 前向。 |
| `robot_devices/arm/z1_dual_arm.py` | 驱动 | `Z1_12_ArmController`：左右两个 Z1 控制器并联（不同 IP/端口），`send_action` 按 `[0:6]` / `[6:12]` 切片分发。 |
| `robot_devices/cameras/configs.py` | 配置 | `OpenCVCameraConfig / IntelRealSenseCameraConfig / ImageClientCameraConfig`：含 fps/分辨率/旋转/color_mode/depth flag/网络宽高比阈值等。 |
| `robot_devices/cameras/utils.py` | 工厂 | `Camera` 协议 + `make_cameras_from_configs()`。 |
| `robot_devices/cameras/imageclient.py` | 驱动 | `ImageClient`：ZMQ 接收 G1 板上 image_server 的实时图像（头+腕），可选共享内存加速；`async_read()` 非阻塞拿帧并维护帧 ID/延迟/丢包统计。 |
| `robot_devices/cameras/intelrealsense.py` | 驱动 | `IntelRealsenseCameraBase`：pyrealsense2 按 serial_number 配置 RGB（30/60/90 fps，640×480/1280×720）+ 可选 Depth；`async_read()` 后台线程喂队列，`force_hardware_reset` 选项处理掉线。 |
| `robot_devices/cameras/opencv.py` | 驱动 | `OpenCVCamera`：cv2.VideoCapture 设 fps/分辨率/color_mode，`read / async_read` 含旋转变换。 |
| `robot_devices/endeffector/configs.py` | 配置 | `Dex1_GripperConfig`：2 轴电机表、`control_dt=1/200`、DDS 话题 `rt/unitree_actuator/cmd|state`、`max_pos_speed`。 |
| `robot_devices/endeffector/utils.py` | 工厂 | `EndEffector` 协议 + `make_endeffector_motors_buses_from_configs()`。 |
| `robot_devices/endeffector/gripper.py` | 驱动 | `Dex1_Gripper_Controller`：DDS 发 `MotorCmds_` / 收 `MotorStates_`；`write_endeffector()` 同样走 JointTrajectoryInterpolator + `kp=10, kd=0.05`；常量 `MAX_DIST=5.45, MIN_DIST=0.0, DELTA_GRIPPER_CMD=0.18`。 |
| `robot_devices/assets/g1/README.md` | 文档 | URDF / mesh 资源说明。 |

#### 2.7.5 `unitree_deploy/utils/` — 部署工具

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `utils/eval_utils.py` | 工具 | `LongConnectionClient`（HTTP 包装）；`ACTTemporalEnsembler`：`weights = exp(-coef * arange(chunk_size))`，`update(pred_actions)` 返回平滑后的 action chunk；`reset()` 清历史。 |
| `utils/joint_trajcetory_inter.py` | 插值 | `JointTrajectoryInterpolator`：scipy.interpolate.interp1d；`drive_to_waypoint(pose, time, curr_time, max_pos_speed)` 一次性切轨迹，`schedule_waypoint()` 连续插入新航点（实时控制），`__call__(t)` 按时间查询。 |
| `utils/weighted_moving_filter.py` | 滤波 | `WeightedMovingFilter`：固定 sum=1 的权重数组对滑窗加权卷积，给 IK 结果做去抖。 |
| `utils/trajectory_generator.py` | 生成 | `generate_rotation` / `sinusoidal_gripper_motion`：测试用周期性轨迹与夹爪正弦控制信号。 |
| `utils/rerun_visualizer.py` | 可视化 | `RerunLogger`：自动识别 `observation.images.* / observation.state / action`，构建 Spatial2D（图像）+ TimeSeriesView（曲线）布局，`log_frame()` 写入轨迹。 |
| `utils/rich_logger.py` | 日志 | 彩色 `log_info / success / warning / error` 包装。 |
| `utils/run_simulation.py` | 仿真 | `MujicoSimulation` 类：用 mock 仿真测试 G1/Z1 控制流程（不连真机）。 |

#### 2.7.6 `unitree_deploy/test/` — 设备级单元测试

| 路径 | 类型 | 作用说明 |
|---|---|---|
| `test/test_replay.py` | 测试 | LeRobotDataset 回放：从指定 episode 取观测/动作 → 真实机器人步进 → 可视化对比。 |
| `test/arm/g1/test_g1_arm.py` | 测试 | 直接驱动 `G1_29_ArmController`：设左右臂 SE3 目标 → 30 fps 循环调 IK + write_arm，演示 drive/schedule 两种模式。 |
| `test/arm/g1/test_g1_env.py` | 测试 | 把 G1 包进 `UnitreeEnv`，验证 env.reset / env.step。 |
| `test/arm/z1/test_z1_arm.py` | 测试 | Z1 单臂 6 DOF 控制流程冒烟测试。 |
| `test/arm/z1/test_z1_dual_arm.py` | 测试 | `Z1_12_ArmController` 双臂协调测试。 |
| `test/arm/z1/test_z1_env.py` | 测试 | 把 Z1 包进 `UnitreeEnv` 测试。 |
| `test/camera/test_image_client_camera.py` | 测试 | 网络 ImageClient 拉流 + 拼接显示。 |
| `test/camera/test_realsense_camera.py` | 测试 | 多 RealSense 同时采集、帧率/分辨率配置验证。 |
| `test/camera/test_usb_camera.py` | 测试 | OpenCV USB 单/多摄像头测试。 |
| `test/endeffector/test_dex1.py` | 测试 | Dex1 夹爪 DDS 收发与开合动作冒烟测试。 |

---

## 3. 核心架构与数据流

### 3.1 三种工作模式对照

| 模式 | 配置 | 输入 | 输出 | 用途 |
|---|---|---|---|---|
| 基础视频生成 | `base_model_inference.yaml`（`base_model_gen_only=True`） | 单帧图像 + 文本 | 16 帧未来视频 | $\text{Base}$ ckpt 验证、产出合成数据 |
| 决策（DM, decision making） | `world_model_decision_making.yaml`（`decision_making_only=True`） | 2 帧观测 + 状态 + 文本 | 16 步动作（不解码视频） | 真机闭环推理（FastAPI 服务模式） |
| 交互仿真（Sim） | `world_model_interaction.yaml`（`decision_making_only=False`） | 初始帧 + 2 步状态 + 动作历史 | 16 步动作 + 16 帧未来视频 + 16 步未来状态 | 长序列展开 / 数据合成 |

三种模式同源同模型、同套权重。模式切换由 `LatentVisualDiffusion._get_augmented_batch` 内的 `decision_making_only / sim_mode` 路径决定（后文详解）。

### 3.2 端到端数据流

```
LeRobot v2.1 数据集
        │
prepare_training_data.py
        │  AV1→H264 转码、parquet→H5、stats.safetensors、CSV 索引
        ▼
target_dir/{videos, transitions, <dataset>.csv}
        │
WMAData.__getitem__()  via decord + h5py
        │  (video, observation.image, pre_action, action,
        │   observation.state, next.state, action_mask, state_mask, instruction)
        ▼
DataModuleFromConfig（多数据集加权采样）
        │
trainer.py + scripts/train.sh（Lightning Trainer + DDP）
        │  encode_first_stage → latents
        │  cond stages（CLIP 文本 / 图像 + state/action MLP + pos emb）
        │  forward diffusion: q_sample（v-parameterization, zero-SNR）
        │  WMAModel: video UNet 同时输出 video / action_unet head / state_unet head
        │  联合损失：L_video + L_action·mask（决策模式）或 L_video + L_state·mask（仿真模式）
        ▼
checkpoints/
        │
        ├── base_model_inference.py     → mp4 视频
        ├── real_eval_server.py         → FastAPI POST /predict_action → 动作
        │       ▲
        │       └── unitree_deploy/scripts/robot_client.py
        │             └── UnitreeRobot(G1/Z1/Dex1) + RealSense/USB/网络相机
        └── world_model_interaction.py  → 决策+仿真双阶段循环 → mp4
```

### 3.3 联合训练的三流损失

`LatentVisualDiffusion.p_losses` 同时去噪 latent 视频、动作序列、状态序列：

- **L_video**：基础扩散损失（按 `parameterization='v'` 选用 v-loss，可加 VLB），以及 DynamiCrafter 的 simple weighting。
- **L_action**：动作 1D 扩散头预测 `noise_action`，与 GT 比 MSE，并与 `action_mask` 逐元素加权（应对不同机器人 DoF 不同时统一到 16 维需要的填充）。
- **L_state**：状态 1D 扩散头同理，与 `state_mask` 加权。

模式切换：`decision_making_only=True` ⇒ `loss = L_video + L_action`；否则在 `sim_mode=True/False` 间切换两类样本，让同一份权重学会"沉浸预测未来"与"看历史出动作"两件事。

---

## 4. 代码模块详解（按子系统聚焦关键类）

> 本节按"子系统 → 文件 → 关键类/函数"逐层展开。每个文件先给一段总述，再展开 2–4 个最关键的类/函数的内部机制；其余次要符号只点名。

### 4.1 `src/unifolm_wma/data/`

**`base.py`** — 一个 26 行的抽象基类 `Txt2ImgIterableBaseDataset(IterableDataset)`，给所有可迭代样本源约定 `num_records / valid_ids / size / __iter__` 四个接口。本仓库主要使用 map-style 的 `WMAData`，这个抽象类主要为日后扩展 IterableDataset 留口。

**`normolize.py`** — 负责把不同模态（图像、关节角、动作）按统一约定归一化到模型输入域。

- `create_stats_buffers(shapes, modes, stats)`：依据每条模态的 `mode='mean_std'|'min_max'`，为之注册 `mean/std` 或 `min/max` buffer；图像 stats 生成形状 `(C,1,1)` 以广播到任意 H/W；初始化为 `+inf`，强制必须由 `stats.safetensors` 或预训练权重覆盖（防止忘加载）。
- `Normalize.forward(batch_dict)`：`mean_std` ⇒ `(x-mean)/(std+eps)`；`min_max` ⇒ `2*(x-min)/(max-min+eps) - 1`，输出严格落在 `[-1,1]`。
- `Unnormalize`：训练 / 推理共用，反向把动作映射回真实关节范围。

**`utils.py`** — 三个加载函数：`unflatten_dict('a/b','c')→{'a':{'b':...}}` 反扁平化；`load_episode_data_index` 从 `episode_data_index.safetensors` 读 episode 起止帧；`load_stats` 同步加载 `stats.safetensors`（含 `action/max`、`observation.state/min` 等 `<modality>/<stat>` 键）。

**`wma_data.py`** — 训练样本工厂，`WMAData(Dataset)`：

- 关键字段：`meta_path / data_dir / video_length=16 / resolution=[256,512] / frame_stride / fixed_fps / n_obs_steps / max_action_dim=7 / max_state_dim=7 / normalization_mode='min_max' / individual_normalization`。注意 `max_*_dim` 的默认值是 7，但 `configs/train/config.yaml` 通过 `agent_state_dim/agent_action_dim=16` 把统一向量空间扩到了 16 维（兼容 G1 双臂高 DoF）。
- `__getitem__` 返回的张量字典：

  | key | shape | 含义 |
  |---|---|---|
  | `video` | `(C, T, H, W)` | 训练视频片段，已归一化到 `[-1,1]` |
  | `observation.image` | `(C, n_obs_steps, H, W)` | 历史观测图像 |
  | `pre_action` | `(n_obs_steps, D_act)` | 历史动作 |
  | `action` | `(T, D_act)` | 目标动作序列 |
  | `observation.state` | `(n_obs_steps, D_state)` | 历史状态 |
  | `next.state` | `(T, D_state)` | 未来状态 |
  | `action_mask` / `state_mask` | `(D_act,)` / `(D_state,)` | 该机器人有效 DoF 的 0/1 掩码（不足维补 0） |
  | `instruction` | `str` | 文本指令 |
  | `frame_stride / fps` | scalar | 用于 WMAModel 的 fps 条件 |

- 视频加载细节：先 decord `VideoReader` 读元信息，再按 `frame_stride` 与 `fixed_fps`（若给定）回算等效步长；不足帧时退回 `frame_stride_min`。空间变换走 `resize-center-crop`（也支持随机裁剪，见 `data` 段配置）。
- `_init_normalizers()`：当 `individual_normalization=True` 时按数据集独立创建 `Normalize/Unnormalize`，否则共享一份。
- `get_uni_vec / _map_to_uni_action / _map_to_uni_state`：把各机器人原生维度（如 Z1 的 7 维）零填充到统一的 `max_*_dim`，并同时输出对应 mask 给 loss 加权用。

### 4.2 `src/unifolm_wma/utils/`

**`basics.py`**：低层算子工厂。`zero_module(m)` 把模块所有参数清零（DiT/UNet 的零初始化技巧）；`scale_module(m, s)` 缩放参数；`conv_nd / linear / avg_pool_nd` 按维度数动态选 nn.Conv1d/2d/3d；`GroupNormSpecific` 强制 fp32 减少 fp16 训练时数值漂移；`HybridConditioner` 把两个 cond stage 拼起来同时供 cross-attn 与 concat。

**`callbacks.py`**：

- `ImageLogger(Callback)` 是核心可视化回调。它在 `on_train_batch_end / on_validation_batch_end` 周期性触发 `model.log_images` 生成定步数样本，按 `clamp` / `rescale` 处理后既写 TensorBoard 也落盘成 mp4 + png；同时统计当前 batch 的 `fps / frame_stride` 直方图保存为 JSON，便于排查多数据集采样比是否符合预期。
- `CUDACallback` 统计每个 epoch 的 GPU 峰值显存与耗时，多卡时通过 `dist.all_reduce` 聚合最大值。

**`common.py`**：训练运行时杂项 —— `gather_data` 把张量 all_gather 后切回原维；`extract_into_tensor(arr, t, x_shape)` 是扩散里最常用的"按 timestep 取 schedule 项"工具；`checkpoint(fn, args, params, flag)` 调用 `torch.utils.checkpoint` 实现激活重计算（视频 UNet 显存吃紧时常用）。

**`data.py`**：`DataModuleFromConfig(LightningDataModule)` 把多数据集打包成 Lightning DataModule。`setup` 中按 `data.train.dataset_and_weights` 组装多个 `WMAData` 实例并用 `WeightedRandomSampler` 加权采样；`worker_init_fn` 给每个 worker 分配 `IterableDataset` 的子区间，避免重复样本；附带 `WrappedDataset` 把任意 callable 包成 `Dataset`。

**`diffusion.py`**：扩散 schedule 工具集。

- `make_beta_schedule(name, n_timesteps, ...)` 支持 `linear / cosine / sqrt_linear / sqrt`，linear 用 SD/DynamiCrafter 的 `(linear_start, linear_end) → β = linspace²`，cosine 用经典 Nichol-Dhariwal 公式。
- `make_ddim_timesteps(method, num_ddim, num_ddpm, ...)` 三种离散化：`uniform`（等间距）、`uniform_trailing`（解决末端 SNR 偏移，与 `rescale_zero_terminal_snr` 配合）、`quad`（二次密化）。配套 `make_ddim_sampling_parameters` 计算 `α_prev / σ_t`。
- `rescale_zero_terminal_snr(betas)` 把训练 schedule 末端 α_T 强制为 0（消除 SD 模型的过曝/灰雾问题）；`rescale_noise_cfg(eps_pos, eps, scale)` 在 CFG 之后做 std-rescale，缓解高 guidance scale 下的过饱和。

**`distributions.py`**：`DiagonalGaussianDistribution(parameters)` 接 VAE 输出（沿通道分两半得到 `mean / logvar`），提供 `sample()`（重参数化）、`mode()`（返回 mean）、`kl(other=None)`（与 N(0,I) 或另一高斯）、`nll(sample)`（高斯负对数似然）。`normal_kl` 给两个对角高斯做闭式 KL。

**`ema.py`**：`LitEma` 实现经典 EMA。`__init__` 时为每个可训参数注册 `<name>.shadow` buffer；`forward(model)` 按 `decay = min(decay, (1+step)/(10+step))` 自适应（前 10 步充分小，逐步逼近 0.9999）；`store/restore` 用于 validation/sample 期间把模型参数临时替换为 EMA 权重再恢复。

**`nn_utils.py`** 与 **`projector.py`**：两组互补的跨模态投影。`nn_utils` 是简单 MLP 类（`LinearProjector/MLPProjector/FusedMLPProjector`），`projector` 是 Perceiver 风格 —— `PerceiverAttention(latents, x)` 让一组可学习 latents（query）跨注意输入 token；`TokenProjector` 多层堆叠后再线性投影到目标维度。两者一同支撑 `image_proj_model` 把 OpenCLIP 输出压成固定 token 数。

**`save_video.py`** — 一个完整的"张量到 mp4"工具集：`tensor_to_mp4` 接收 `(B,C,T,H,W)`、`(B,T,H,W,C)` 或 `(T,H,W,C)` 任意排布并自动判别，`tensor2videogrids` 可把 batch 排列成 `nrow × ncol` 网格再写盘；`log_local` 把 PL 风格的 `images / videos / texts` 字典统一存到目录里。默认 h264 + crf 10 平衡画质与体积。

**`train.py`** — 训练装配胶水。`get_trainer_callbacks` 默认装上 `ModelCheckpoint`（每 1k 步存一次，保留 top-3 + last）、`ImageLogger`、`LearningRateMonitor`、`CUDACallback`；`get_trainer_strategy` 默认 `DDPShardedStrategy(find_unused_parameters=False)`；`load_checkpoints` 兼容 PL 标准与 DeepSpeed Stage-3 分片格式；`get_num_parameters` 把 World Model / Action Head / State Head 三块的参数量分别打到日志，方便比例调整。

**`utils.py`** —— `instantiate_from_config({target, params})` 是整个仓库的"反射创建"核心，所有 YAML 都靠它构造 `nn.Module`、`pl.LightningDataModule`、回调等；`get_obj_from_str('a.b.C')` 提供字符串路径导入；`resize_numpy_image(img, max_resolution)` 用 OpenCV Lanczos4 做高质量缩放，给推理客户端预处理用。

### 4.3 `src/unifolm_wma/models/`

#### 4.3.1 `autoencoder.py`

`AutoencoderKL(pl.LightningModule)`：

- 内部是经典 SD/DynamiCrafter VAE：`encoder → quant_conv → DiagonalGaussianDistribution → post_quant_conv → decoder`，潜空间通道默认 4，缩放因子 `0.18215`（与 SD1.5 一致，由 `LatentDiffusion.scale_factor` 控制）。
- `encode(x)` 返回后验分布，`decode(z)` 直接还原；`forward()` 可选 `sample=True/False` 决定走样本还是众数。
- 训练时它自带两个优化器（VAE recon + 判别器），但本仓库只把它作为冻结的"first stage"使用：在 `LatentDiffusion._init_first_stage` 里 `disabled_train + requires_grad_(False)` 完全冻结。
- 旁边有个 `IdentityFirstStage`：如果想直接跑像素空间 ablation，可以用它绕过 VAE。

#### 4.3.2 `ddpms.py` — 仓库灵魂（2524 行）

整个文件分三层继承：`DDPM` → `LatentDiffusion` → `LatentVisualDiffusion`，最后由 `DiffusionWrapper` 做条件路由。

##### 4.3.2.1 `DDPM`（基类）

负责扩散过程本身：

- `register_schedule(beta_schedule, timesteps, ...)`：按 `make_beta_schedule` 算 β、α、`alpha_cumprod / sqrt_one_minus_alphas_cumprod / posterior_*` 等一族 buffer，并按 `parameterization` 决定 `loss_weight` 形式。
- `q_sample(x_start, t, noise)`：前向加噪 `x_t = √α_t·x_0 + √(1-α_t)·ε`。
- `q_posterior(x_start, x_t, t)` / `p_mean_variance(model_output, x_t, t)`：标准 DDPM 后验/反向均值方差。
- `p_sample / p_sample_loop`：祖先采样（评测时几乎不用，主要走 DDIM）。
- `forward(x)` → 采样随机 t → `p_losses`，根据 `parameterization`（'eps' / 'x0' / 'v'）决定 target；v-parameterization 多一步 `predict_eps_from_z_and_v` 把 v 转回 ε 再算 simple loss。
- `ema_scope()` 上下文管理器：进入时 `LitEma.store` + `copy_to`，退出时 `restore`，方便验证期切到 EMA 权重出图后再切回。
- `on_train_batch_end` 调一次 EMA 累积。

##### 4.3.2.2 `LatentDiffusion`（潜空间 + 文本/图像 cond）

加了 VAE 与 cond stage：

- `_init_first_stage(config)` 把 `AutoencoderKL` 冻结进来；`_init_cond_stage(config)` 装 `FrozenOpenCLIPEmbedder` 等文本/图像编码。
- `encode_first_stage(x)`：可选 `perframe_ae=True` 逐帧编码（节省显存，长视频必须开），否则 `(B,C,T,H,W)→(B*T,C,H,W)→encode→reshape` 整批处理；输出乘 `scale_factor`（或动态 `use_dynamic_rescale` 算的 step-wise 缩放）。
- `get_learned_conditioning(c)`：给文本/图像跑 cond stage，必要时按 `cond_stage_forward` 字符串调指定方法（如 `encode`）。
- `get_batch_input(batch, random_uncond=True)`：编码 video → z；编码 instruction → text_emb；随机 dropout 条件实现 CFG（`uncond_prob=0.05`，dropout 后用 `uncond_type='empty_seq'` 或零向量）。
- `apply_model(x, t, cond)`：把裸 cond 包成 `{c_concat, c_crossattn, ...}` dict 后递给 `DiffusionWrapper`。
- `p_losses(x_start, cond, t)`：除了 simple loss，还可加 VLB 项（`learn_logvar=True` 时 logvar 也被优化）。
- `sample_log(...)`：内部走 `DDIMSampler` 出样本并 `decode_first_stage` 到像素空间，给 `log_images` 用。

##### 4.3.2.3 `LatentVisualDiffusion`（仓库核心）

在前一层基础上加图像条件、动作头、状态头：

- `_init_embedder` 装冻结的 OpenCLIP 视觉模型；`_init_img_ctx_projector` 装可训的图像投影（输出和文本同维便于 concat）；`_init_dp_noise_scheduler` 给动作/状态扩散头分别建独立的 `DDPMScheduler`（diffusers 风格）；`_init_projectors` 建 `state_projector / action_projector`（线性 / MLP），并注册 `agent_state_pos_emb / agent_action_pos_emb`（硬编码 16 步的 sin-cos 位置编码）；`_init_dp_ema` 可选给动作 UNet 单独维持一份 `EMAModel`。
- `_get_augmented_batch(batch)` 是模式切换的核心：
  - `decision_making_only=True`：`mode_batch = [obs_state_emb, instruction_emb, image_emb]`，动作头出 `loss_action`，状态头被屏蔽。
  - `decision_making_only=False`：根据 `sim_mode` 标志（每个样本一半概率）切换 — `sim_mode=True` 时 `mode_batch = [obs_state, action, ∅, image]`（用真动作做条件，让模型学会"给我动作 + 图像，预测下一帧"）；`sim_mode=False` 时 `mode_batch = [obs_state, 0, instruction, image]`（动作清零，让模型出动作）。
- 重写 `get_batch_input` 让其输出五元组 `(z, action, state, cond_dict, [fps])`：
  - `cond_dict["c_concat"]`：hybrid 模式下与 z 在 channel 维拼接的图像 latent；
  - `cond_dict["c_crossattn"]`：`[obs_state_emb, action_emb, instruction_emb, image_emb]` 沿 token 维拼接；
  - `cond_dict["c_crossattn_action"]`：给动作 UNet 用的辅助条件 `[obs_images, obs_state, sim_mode_flag, masks]`。
- 重写 `p_losses`，三流损失：
  ```
  L_video  = simple_loss(pred_video,  target_video)  + λ_vlb * vlb_loss
  L_action = mse(pred_action, action_noise) * action_mask
  L_state  = mse(pred_state,  state_noise)  * state_mask
  return L_video + (L_action if not sim_mode else L_state)
  ```
  - `decision_making_only=True` 时 `sim_mode` 恒 False，等价 `L_video + L_action`。
- `configure_optimizers` 把视频 UNet 与动作/状态头分到两个参数组，分别给独立学习率（YAML 里 `dp_optimizer_config.lr`）；可选 `SelectiveLRScheduler` 仅调动作头 lr。
- `sample_log` 重载后返回 `(video, action, state, intermediates)` 四元组，给推理脚本直接拿到三路输出。

##### 4.3.2.4 `DiffusionWrapper`

底部的"路由"。把 cond_dict 按 `conditioning_key` 分发：

- `None` / `concat` / `crossattn`：标准 SD 几路；
- **`hybrid`（本仓库默认）**：把 `c_concat` 通道拼到 `x` 上、`c_crossattn` 作为 K/V 喂 cross-attn、`c_crossattn_action` 作为额外 condition 进 `action_unet / state_unet`；
- 还有 `concat-time-mask / hybrid-adm-mask / crossattn-adm` 等少见组合，留给消融实验用。

#### 4.3.3 `models/samplers/ddim.py`

`DDIMSampler` 不继承 nn.Module（无可训参数）：

- `make_schedule(ddim_num_steps, ddim_discretize='uniform', ddim_eta=0.0)`：调 `make_ddim_timesteps + make_ddim_sampling_parameters` 把 `α_t / α_prev / σ_t` 全部预算并注册为 numpy 数组（GPU 上转 tensor）。
- `sample(S, batch_size, shape, conditioning, ...)` 是公共入口，参数包括 `unconditional_guidance_scale`、`unconditional_conditioning`、`temporal_length`、`x_T`、`temperature`、`eta`、`guidance_rescale` 等；返回 `(video_samples, action_samples, state_samples, intermediates)`。
- `ddim_sampling(...)` 主循环：从最大 t 倒序迭代；初始 `x_T = randn(shape)`，`action / state` 同样从 N(0,I) 初始化；每步调 `p_sample_ddim`。
- `p_sample_ddim` 单步：
  1. 调 `model.apply_model(x, t, cond)` 得到 `(eps_pred, action_pred, state_pred)`；
  2. 若 `parameterization='v'` 走 `predict_start_from_z_and_v`、`predict_eps_from_z_and_v` 把 v 转回 x_0/ε；
  3. 分别对 video / action / state 做 CFG：`eps = eps_uncond + s · (eps_cond - eps_uncond)`；`guidance_rescale > 0` 时再调 `rescale_noise_cfg` 修正方差；
  4. 用 `α_t / α_prev / σ_t` 计算 `x_{t-1} = √α_prev · x_0 + √(1-α_prev-σ²) · ε + σ_t·η·ζ`；动作/状态走单独的 `dp_ddim_scheduler.step` 更新。

### 4.4 `src/unifolm_wma/models/diffusion_head/`

**`base_nets.py`**：扩散头里复用的低层模块。`SpatialSoftmax(num_kp)` 把 `(B,C,H,W)` 视觉特征通过 2D softmax 算期望坐标，得到 `(B, num_kp, 2)` 的关键点表示，让 1D UNet 不必直接吃高分辨率特征。

**`conditional_unet1d.py`**：动作扩散头本体。`ConditionalUnet1D`：

- 输入 `sample (B,T,input_dim)` + `timestep (B,)` + `imagen_cond (B,C,H,W) 或 (B,C)` + `cond (B,D_global)`；
- `proj_in_action` 做动作维投影到 `act_proj_dim`，`proj_in_horizon` 沿时间步做 1D 卷积投影；
- down/mid/up 由 `ConditionalResidualBlock1D ×2 + ActionLatentImageCrossAttention` 交替；
- `ConditionalResidualBlock1D` 内部两层 `Conv1dBlock`，`cond_predict_scale=True` 时把 `cond_emb` 切两半得到 `(scale, bias)` 做 FiLM 调制；
- `ActionLatentImageCrossAttention` 用 action token 当 query 跨注意 `imagen_cond` 经 `SpatialSoftmax` 后的关键点序列，让动作生成"看着"世界模型预测的画面；
- 默认 `down_dims=[256,512,1024,2048], kernel_size=5, n_groups=8`；输出与输入 shape 一致。

**`conv1d_components.py`**：`Conv1dBlock(GroupNorm + Conv1d + Mish)` 与 `Downsample1d/Upsample1d`，给 ConditionalUnet1D 当积木。

**`ema_model.py`**：`EMAModel(parameters, decay, ...)` 是 diffusers 风格的自适应 EMA：`update_step` 时 `decay = min(max_decay, (1+step)^-power * (1+step)/inv_gamma + ...)`，专门给 action_unet 用。

**`positional_embedding.py`**：19 行的 `SinusoidalPosEmb(dim)`，给 timestep 标量做 sin/cos 编码。

**`common/lr_scheduler.py`**：把 diffusers 的 `get_scheduler` 包成可由 OmegaConf 配置；提供 `SelectiveLRScheduler`，使其仅作用于动作 UNet 参数组。

**`common/module_attr_mixin.py`**：16 行的 `ModuleAttrMixin`，给 nn.Module 加 `device / dtype` property（取首个 buffer 或 param）。

**`common/pytorch_util.py`**：`dict_apply(fn, x)` 递归对嵌套 dict/list 应用 fn；`replace_submodules(root, predicate, factory)` 按谓词替换子模块（用来把 BatchNorm 换成 GroupNorm 等）。

**`common/tensor_util.py`**：960 行通用张量套件。最常用的几类：

- `recursive_dict_list_tuple_apply(x, type_func_dict)`：根据类型表对嵌套结构做映射，避免到处写 if-isinstance；
- `to_device / to_tensor / to_numpy / to_float / to_uint8`：批量类型转换；
- `time_distributed(x, op, ...)`：把 `(B,T,...)` 合成 `(B*T,...)` 跑 op 再折回，用来把 2D backbone 应用到视频；
- `pad_sequence / gather_sequence`：变长序列整形。

**`vision/crop_randomizer.py`**：`CropRandomizer(input_shape, crop_h, crop_w, num_crops, pos_enc=False)`：

- `forward_in(x)`：训练随机采 num_crops 个 crop 拼到 batch 维（增强）；推理直接中心裁剪；
- `forward_out(x)`：把 num_crops 维平均回去；
- `pos_enc=True` 时把 crop 的 (top, left) 坐标 concat 到通道维，让网络感知"我看的是哪一块"。

**`vision/model_getter.py`**：`get_resnet(name='resnet18') / get_vit(name)` 工厂，30 行。

**`vision/multi_image_obs_encoder.py`**：`MultiImageObsEncoder(shape_meta, rgb_model_factory, resize_shape, crop_shape, ...)`：

- 输入 `obs_dict`：每个相机一个 `(B,3,H,W)` + 任意低维状态 `(B,D_state)`；
- 对每个 RGB key：`transform`（resize + center/random crop + ImageNet normalize）→ `model`（共享或独立 backbone）→ 可选 `SpatialSoftmax` 取关键点；
- 把所有相机特征 + 低维状态 concat 成单条 embedding 给下游 1D UNet。
- 也可选 DinoSigLIP 替代 ResNet。

### 4.5 `src/unifolm_wma/modules/`

**`attention.py`**（806 行）—— UNet 里所有的注意力块都在这里。

- **`CrossAttention`**：本仓库的扩展版，除了标准 `to_q/to_k/to_v` 外加了：
  - `RelativePosition` 相对位置偏差（temporal attention 的关键）；
  - xformers 内存高效注意分支（`efficient_forward`），开启 `XFORMERS_ENABLED` 时自动走；
  - 对 agent_action token 段可选施加 causal mask（对角及以下置 0）—— 防止动作生成偷看未来真值；
  - 三个可学习标量 `alpha_ctx / alpha_cas / alpha_caa` 分别对文本/状态/动作上下文做缩放，相当于让模型自己学到每路条件的重要性。
- **`BasicTransformerBlock`**：经典 Pre-Norm `self-attn → cross-attn → FFN`，残差连接；FFN 默认走 `GEGLU`。
- **`SpatialTransformer`**：对 `(B,C,H,W)` reshape 到 `(B, HW, C)` 跑 N 个 BasicTransformerBlock 再 reshape 回。
- **`TemporalTransformer`**：对 `(B,C,T,H,W)` 视作 `(B*H*W, T, C)` 跑 transformer，可选因果 mask；这是把 SD 的 2D UNet"扩到视频"的关键模块。
- 还有 `LinearAttention`（线性复杂度替代）、`SpatialSelfAttention`（VAE 用）、`FeedForward / GEGLU` 等。

**`encoders/condition.py`**（630 行）—— 一组冻结条件编码器，供 `LatentVisualDiffusion._init_cond_stage / _init_embedder` 选用：

- `FrozenT5Embedder`、`FrozenCLIPEmbedder`（OpenAI CLIP-L/14）、`FrozenOpenCLIPEmbedder`（OpenCLIP ViT-H/14，本仓库默认）；
- `FrozenOpenCLIPImageEmbedder` / `FrozenOpenCLIPImageEmbedderV2`（视觉条件，按 patch+pos+transformer 输出 token 序列）；
- `ClipImageEmbedder`（带 dropout 用于 CFG-free guidance）；
- `FrozenCLIPT5Encoder`（双编码器拼接，提供更长上下文）；
- `PerceiverAttention + SATokenProjector` —— 给图像 token 做 Perceiver 重采样到固定数量；
- `LinearProjector / MLPProjector / FusedMLPProjector` 维度对齐用。

**`encoders/resampler.py`** —— `Resampler(dim, depth, dim_head, heads, num_queries, embedding_dim, output_dim, ff_mult, video_length=None)`：经典 IP-Adapter / Flamingo 风格 Perceiver Resampler，把可变长度的图像 patch token 压成固定 num_queries 个 latent token；当 `video_length` 给定时，latent 会按 (T, num_queries, dim) 复制并加时间索引，使其感知时序。

**`networks/ae_modules.py`**（1005 行）—— VAE 的零件库：`ResnetBlock`（`emb_layers(t)→scale,shift` FiLM 或加法）、`AttnBlock` / `LinAttnBlock`、`Downsample` / `Upsample`（avg_pool 或 conv stride）、完整 `Encoder` / `Decoder` / `Model`、轻量 `SimpleDecoder` / `UpsampleDecoder`、`LatentRescaler`（多分辨率插值后投影）；`AutoencoderKL` 直接用这里的零件。

**`networks/wma_model.py`**（848 行）—— 真正的视频扩散主干 `WMAModel`，结构如下：

- 输入：`x (B, C_in, T, H, W)`、`timesteps (B,)`、`context (B, N_tokens, C_ctx)`、可选 `fps_label`、可选 `c_crossattn_action`。
- `time_embed = MLP(timestep_embedding(t))`；可选把 `fps` 同样 sin/cos + MLP 融进 time_emb。
- `input_blocks` / `middle_block` / `output_blocks` 由 `TimestepEmbedSequential` 串起来：`ResBlock`（注入 time_emb）→ `SpatialTransformer`（cross-attn 文本/图像）→ `TemporalTransformer`（沿 T 做 self-attn，可选 cross-attn）。
- **Cross-attention context 拼接**：`[agent_state_emb (B, n_obs_steps, D) | agent_action_emb (B, T·num_stem_token, D) | text_emb (B, 77, D) | image_emb (B, T·HW, D)]`；attention 内按段长度切 mask 控制每个 head 看哪几路，alpha_* 缩放每路重要性。
- **侧出动作头与状态头**：`action_unet = ConditionalUnet1D(...)`、`state_unet = ConditionalUnet1D(...)`。它们以 `c_crossattn_action` + 中间层 latent 作为 imagen_cond，输出动作/状态噪声预测，与视频主干并联训练。

**`vision/base_vision.py`**：`VisionBackbone` 抽象 + `TimmViTBackbone` 通用实现。后者关键点：构造时按 `image_resize_strategy in {'resize-naive','resize-crop','letterbox'}` 选不同 transform；为了 FSDP 兼容，把 `forward` monkey-patch 成"只到倒数第二层、返回 patches"（不要 cls token，避免后续不必要的 reduce）；`get_fsdp_wrapping_policy()` 给上层指定哪些子模块按 FSDP unit 切。

**`vision/dinosiglip_vit.py`**：`DinoSigLIPViTBackbone(dino_name, siglip_name, default_image_size, image_resize_strategy)`：两份 TIMM ViT 并联，`forward(pixel_values)` 拿到 dino_patches 与 siglip_patches 后在通道维 concat；`DinoSigLIPImageTransform` 维护两套 mean/std 让两个 ViT 各按自己的预训练分布预处理；输出再过线性/MLP 投影到 `out_dim`。

### 4.6 `prepare_data/prepare_training_data.py`（数据预处理）

整个脚本是一个流水线 `main(args)`：

1. **遍历**：枚举 `source_dir/<dataset_name>/data/chunk-*/episode_*.parquet`，对应 `videos/chunk-*/observation.images.<view>/episode_*.mp4` 与 `meta/{info.json, episodes.jsonl, tasks.jsonl}`。
2. **状态/动作**：每个 parquet 读出 `action`、`observation.state` 列，写到 `target_dir/transitions/<dataset>/<idx>.h5`；同时记 H5 attrs `robot_type / state_type / action_type`，便于后续 `WMAData` 自动对齐。
3. **视频**：`is_av1(path)` 用 `ffprobe -select_streams v:0` 提 codec_name；如果是 AV1 → `convert_to_h264` 调 `ffmpeg -c:v libx264 -preset slow -crf 23 -c:a copy` 转码；否则原样拷到 `target_dir/videos/<dataset>/<view>/<idx>.mp4`。
4. **统计**：`flatten_dict({'action':{'min':..., 'max':...},'observation.state':{...}})` 累计全 dataset 的 min/max/mean/std；最后用 safetensors 写 `target_dir/transitions/<dataset>/meta_data/stats.safetensors`。
5. **CSV**：生成 `target_dir/<dataset>.csv`（列：`videoid, data_dir, instruction, embodiment, fps, frame_count` 等）作为 `WMAData` 的索引。

CLI 关键参数：`--source_dir`（必填）、`--target_dir`（默认 `./data`）、`--dataset_name`（必填）、`--robot_name`（必填，写入 `robot_type`，如 "Unitree Z1 Robot Arm"）。

### 4.7 `scripts/`

#### 4.7.1 `scripts/trainer.py`

`get_parser()`：在 `pl.Trainer.add_argparse_args` 基础上加 `--seed / --name / --base / --train / --val / --test / --auto_resume / --debug / --logdir / --total_gpus`。

`__main__` 流：

1. 取分布式环境变量 `LOCAL_RANK / RANK / WORLD_SIZE`；
2. `OmegaConf.merge(*[OmegaConf.load(p) for p in args.base])` 多份 YAML 合并；
3. `instantiate_from_config(config.model)` 创建 `LatentVisualDiffusion`；`instantiate_from_config(config.data)` 创建 `DataModuleFromConfig`；
4. `scale_lr=True` 时 `lr = num_gpus × batch_size × accumulate_grad_batches × base_lr`；
5. `init_workspace + get_trainer_callbacks + get_trainer_logger + get_trainer_strategy` 装好 callbacks/logger/strategy；
6. 注册 `SIGUSR1`：保存最新 ckpt 并 `sys.exit(0)`；`SIGUSR2`：进 pudb 调试；
7. `trainer.fit(model, datamodule)`，`auto_resume=True` 时自动从 `last.ckpt` 继续。

#### 4.7.2 `scripts/train.sh`

简单的 8 GPU 单机模板：

```bash
torch.distributed.launch \
  --nproc_per_node=8 --nnodes=1 \
  --master_addr=127.0.0.1 --master_port=12366 \
  ./scripts/trainer.py \
  --base configs/train/config.yaml \
  --train --name $name --logdir $save_root \
  --devices 8 --total_gpus=8 \
  lightning.trainer.num_nodes=1
```

注释里有 NCCL TOPO_FILE 模板，方便切到多机。

#### 4.7.3 `scripts/evaluation/`

##### `eval_utils.py`

- `VideoFrame` 是注册到 HF datasets 的 feature 类型，结构 `{path: string, timestamp: float32}`，让 dataset schema 显式包含视频帧引用。
- `populate_queues(queues, batch)`：对一批 deque 执行"满则覆盖最旧、否则追加"，给历史观测窗口用。
- `log_to_tensorboard(writer, video, fps)`：把 `(B,T,C,H,W)` 视频按帧做网格、归一化、追加进 `writer.add_video`。

##### `base_model_inference.py`

入口顺序：

1. `load_model_checkpoint(model, ckpt)`：兼容多种存档（含 PL 风格 `state_dict` 与 EMA 直接保存），有 key remap（`framestride_embed → fps_embedding` 之类），失败时退到非 strict 加载。
2. `load_data_prompts(prompt_dir, csv_path)`：从 CSV + 图像目录读 `(filename, image, instruction, fps, frame_stride, gen_idx)`；图像经 Resize+CenterCrop+`(x*2)-1` 归一化，单帧复制成 T 帧的"占位视频"作为图像条件。
3. `image_guided_synthesis(model, prompts, videos, noise_shape, ddim_steps, eta, guidance_scale, ...)`：核心采样函数 —— 跑 image embedder + image_proj_model 得 `img_emb`、跑 cond_stage 得 `text_emb`，合成 `c_crossattn = concat([text_emb, img_emb], dim=1)`；hybrid 模式还要把图像 latent 作为 `c_concat`；调 `DDIMSampler.sample` → `decode_first_stage` → 像素视频。
4. `run_inference(args)`：YAML 加载、模型实例化、ckpt 加载、`.eval()`、按 GPU 切分 prompt → 多代续写（前一代末帧作下一代首帧）→ `save_results` 写 mp4。

##### `real_eval_server.py`

类 `Server`：

- `__init__(args)`：复用 `run_inference` 前半段，缓存 `model_, noise_shape_, data_, dataset_name, device_, normalizer_, unnormalizer_`。
- `normalize_image(arr_uint8)`：`(x/255 - 0.5)*2 → [-1,1]`，再走训练同款 spatial transform。
- `predict_action(payload)` —— FastAPI 处理函数：
  1. 收 JSON：`observation.images.top (B,H,W,C) uint8`、`observation.state (B,D)`、`action (B,D) zeros`、`language_instruction list[str]`；
  2. 走 normalizer + `_map_to_uni_state / _map_to_uni_action` 得到统一向量与 mask；
  3. `image_guided_synthesis` 得到 `(pred_videos, pred_actions, pred_states)`；
  4. 用 `action_mask` 选回该机器人的真实 DoF 子集，`unnormalizer` 反归一化，转 `list` 返回；
  5. 异常时 `traceback.format_exc()` 序列化进 `desc`。
- `run()`：注册 `POST /predict_action` 后 `uvicorn.run(host='0.0.0.0', port=8000)`。

`__main__` 解析 CLI（`--seed --ckpt --config --res_dir --datasets ...`）后实例化 Server 并启动。

##### `world_model_interaction.py`

最复杂的脚本，实现"决策 + 仿真"两阶段自回归循环：

- `prepare_init_input(start_idx, init_frame_path, transition_dict, frame_stride, video_length=16, n_obs_steps=2)`：
  - `indices = [start_idx + frame_stride*i for i in range(video_length)]` 取目标帧索引；
  - 当 `start_idx < n_obs_steps-1` 时把第 0 帧重复填满前向窗口；
  - 状态/动作走 normalizer + `get_uni_vec` 转统一表示；图像走 spatial_transform → `[-1,1]`；
  - 返回 dict `{video, observation.image, action, observation.state, ...}`。
- `image_guided_synthesis_sim_mode(..., sim_mode, text_input)`：相比 base 版本多了状态/动作嵌入：
  ```
  cond_state_emb  = state_projector(obs.state)  + agent_state_pos_emb
  cond_action_emb = action_projector(action)    + agent_action_pos_emb
  if sim_mode is False: cond_action_emb = 0   # 决策阶段不让动作泄露
  if not text_input:    instruction_emb = 0   # 仿真阶段可关文本
  c_crossattn         = [state_emb, action_emb, text_emb, img_emb]
  c_crossattn_action  = [obs_imgs, obs_states, sim_mode_flag, masks]
  samples, actions, states = sampler.sample(...)
  ```
- `run_inference(args)` 主循环：
  1. 读 CSV prompt 表，模型 `.eval()`，建 TensorBoard writer；
  2. 对每个样本与每个 `frame_stride` 组合循环：
     - 维护 `deque(maxlen=n_obs_steps_imagen)` 存 `images.top / state / action`；
     - 每轮 `n_iter`：
       - **决策阶段**：`sim_mode=False` 调一次 → `pred_videos_0, pred_actions, _`；
       - **仿真阶段**：把 `pred_actions` 追加到队列后 `sim_mode=True, text_input=False` 调一次 → `pred_videos_1, _, pred_states`；
       - 把 `pred_videos_1` 的前 `exe_steps` 帧、对应 state（或零）追加进 deque；
     - 每轮 dm/wm 各存一份 mp4，`run` 结束输出全量拼接 mp4，TB tag 形如 `{dataset}-vid{videoid}-{dm|wm}-fs-{fs}/itr-{itr}`。

### 4.8 `unitree_deploy/`（真机部署子项目）

#### 4.8.1 `scripts/robot_client.py`

部署主入口：

- 通过 `LongConnectionClient(base_url='http://127.0.0.1:8000')` 维持长连接；调 `send_post('/predict_action', json_payload)` 与 `predict_action()` 拉动作。
- `ACTTemporalEnsembler(temporal_ensemble_coeff=0.01, chunk_size=action_horizon, exe_steps)`：复刻 ACT 论文的"时间 ensemble"，用 `weights = exp(-coef * arange(chunk_size))` 做指数衰减加权，每步把新预测的 chunk 与历史 chunk 重叠区域加权平均，平滑动作。
- `prepare_observation(env_obs)`：BGR→RGB 转换、float→[0,1]、按相机名整成模型输入。
- `populate_queues(queues, obs)`：填 `observation_horizon` 大小的 deque。
- 主循环：`env.reset` → `warmup` → `while True: obs = env.get_observation() → enqueue → POST → ensembler.update → for k in range(exe_steps): env.step(action[k])`。
- CLI：`--robot_type / --action_horizon / --exe_steps / --observation_horizon / --language_instruction / --output_dir / --control_freq`。

#### 4.8.2 包内核心类

**`real_unitree_env.py / UnitreeEnv`**：包装 `make_robot(robot_type, ...)`，`get_observation(t)` 返回 `dm_env.TimeStep(qpos+全零 qvel/effort, images dict)`；`step(action_tensor)` → `precise_wait(t+dt)` → 再次取观测；BGR 自动转 RGB 给模型用。

**`eval_dataset_env.py / DatasetEvalEnv`**：从 LeRobotDataset 取一个 episode 离线回放；`get_observation()` 返回当前帧观测，`step(action)` 记录预测动作，结束时画 GT 与预测的对比曲线，方便没有真机时对照。

**`robot/robot.py / UnitreeRobot`**：

- 由 `cameras / arm / endeffector` 三组设备字典组成；
- `connect/disconnect` 串联调所有设备的对应方法；
- `capture_observation()`：所有 arm 的 `read_current_arm_q()` 串成 `observation.state`、所有 endeffector 同理拼到尾、所有相机异步读 RGB → `observation.images.<name>`，最终按 `features` 字典约束形状打包；
- `send_action(action_tensor, t_command_target)`：按 motor 索引切片下发；首次调用用 `cmd_target='drive_to_waypoint'` 一次性飞过去，之后切 `'schedule_waypoint'`，由 `JointTrajectoryInterpolator` 在轨迹层做实时插值。

**`robot/robot_configs.py`**：四套预设组合（Z1 单 / Z1 双 + Dex1 + RealSense 或 USB / G1 + Dex1 + 网络相机），定义各机器人的电机表（含每个电机的 motor_index 与 motor_model）、初始位姿、控制周期。

**`robot_devices/arm/`**：

- `g1_arm.py` 用 `unitree_sdk2py` DDS 收发 `LowState_/LowCmd_`，CRC 校验；35 维全身 → reduce 到 14 维双臂；`g1_arm_ik.py` 用 pinocchio + CasADi 解 IK；锁住非臂关节、用 Meshcat 可选可视化、`WeightedMovingFilter` 平滑输出。
- `z1_arm.py` 用 Unitree 提供的 `unitree_arm_interface.so`（C++ binding）500 Hz 实时控制；`z1_arm_ik.py` 同样 pinocchio + CasADi。
- `z1_dual_arm.py` 把两份 `Z1ArmController`（不同 IP/端口）并联管理，按 `[0:6]/[6:12]` 切片下发。
- `arm_indexs.py` 维护 `G1_29_JointIndex` 等映射；`utils.py` 是 `Arm` 协议 + 工厂；`configs.py` 装载所有 arm 的 dataclass 配置（motors、init_pose、kp/kd、DDS 话题）。

**`robot_devices/cameras/`**：

- `imageclient.py` ZMQ 拉 G1 板上 image_server 流（头+腕，可选共享内存），统计延迟丢包；
- `intelrealsense.py` 用 pyrealsense2 按 serial_number 配置 RGB（最高 90 fps）+ 可选 Depth，含 `force_hardware_reset` 应对掉线；
- `opencv.py` 标准 cv2.VideoCapture 包装，支持旋转 / color_mode 切换。
- `configs.py / utils.py` 同样是 dataclass + 工厂。

**`robot_devices/endeffector/gripper.py / Dex1_Gripper_Controller`**：DDS 收发 `MotorCmds_/MotorStates_`，2 轴；常量 `MAX_DIST=5.45 / MIN_DIST=0.0 / DELTA_GRIPPER_CMD=0.18` 用于把模型输出的连续值量化为夹爪命令。

**`utils/`**：

- `eval_utils.py`：`LongConnectionClient + ACTTemporalEnsembler`（已上文细述）；
- `joint_trajcetory_inter.py / JointTrajectoryInterpolator`：scipy interp1d 基础上提供 `drive_to_waypoint`（一次性）与 `schedule_waypoint`（实时插入新航点），强约束 `max_pos_speed`；
- `weighted_moving_filter.py`：固定权重数组卷积，给 IK 输出去抖；
- `trajectory_generator.py`：演示用的旋转/正弦轨迹；
- `rerun_visualizer.py`：自动识别 `observation.images.* / observation.state / action`，构建 Spatial2D + TimeSeriesView 布局，用 `rerun-sdk` 可视化；
- `rich_logger.py`：彩色日志；
- `run_simulation.py`：mock MuJoCo 仿真，方便没真机时跑流程烟测。

#### 4.8.3 测试目录

`test/` 下都是单设备/单功能冒烟测试，命名直接见名知意（`test_g1_arm.py / test_z1_arm.py / test_z1_dual_arm.py / test_dex1.py / test_image_client_camera.py / test_realsense_camera.py / test_usb_camera.py / test_replay.py / test_g1_env.py / test_z1_env.py`）。它们既是验证脚本，也是各模块的最小可运行示例。

---

## 5. 端到端典型工作流

### 5.1 训练（自有数据集）

```bash
# 0. 创建环境
conda create -n unifolm-wma python==3.10.18
conda activate unifolm-wma
conda install -c conda-forge pinocchio=3.2.0 ffmpeg=7.1.1
git clone --recurse-submodules <repo_url>
cd unifolm-world-model-action && pip install -e .
cd external/dlimp && pip install -e . && cd ../..

# 1. 转数据：LeRobot v2.1 → 训练格式
cd prepare_data
python prepare_training_data.py \
    --source_dir /path/to/lerobot_v21 \
    --target_dir /path/to/wma_data \
    --dataset_name z1_stackbox \
    --robot_name "Unitree Z1 Robot Arm"

# 2. 改 configs/train/config.yaml：
#    model.params.pretrained_checkpoint = $Base_ckpt
#    data.params.train.params.data_dir = /path/to/wma_data
#    data.params.train.params.dataset_and_weights = {z1_stackbox: 1.0}
#    （多 DoF 机器人时把 agent_state_dim/action_dim 调到 16+）

# 3. 启动 8 卡训练
bash scripts/train.sh
```

`trainer.py` 自动 `instantiate_from_config` 创建模型/数据；ImageLogger 每 20k 步出可视化样本到 `<save_root>/<name>/images/`；ModelCheckpoint 每 1k 步存 ckpt。

### 5.2 三种推理模式

**(A) 基础视频生成（`base_model_gen_only=True`）**

```bash
# 改 scripts/run_base_model_inference.sh：ckpt / config / 数据集列表
bash scripts/run_base_model_inference.sh
```

走 `evaluation/base_model_inference.py`：吃 CSV+image_prompts，输出 16 帧未来视频，多代续写时把上一代末帧作下一代首帧。

**(B) 决策模式（FastAPI 服务）+ 真机客户端**

```bash
# Server 端
bash scripts/run_real_eval_server.sh   # 监听 0.0.0.0:8000

# Client 端（另一台机器）
ssh user@server -CNg -L 8000:127.0.0.1:8000   # 建立隧道
cd unitree_deploy
python scripts/robot_client.py \
    --robot_type g1_dex1 \
    --action_horizon 16 --exe_steps 16 \
    --observation_horizon 2 \
    --language_instruction "pack black camera into box" \
    --output_dir ./results --control_freq 15
```

闭环数据流：`UnitreeRobot.capture_observation` → BGR→RGB & 归一化 → POST `/predict_action` → `LatentVisualDiffusion.image_guided_synthesis(decision_making_only=True)` → action chunk → `ACTTemporalEnsembler` → 切片下发到 G1+Dex1 → 30Hz 控制循环。

**(C) 交互仿真（自回归长展开）**

```bash
# 改 scripts/run_world_model_interaction.sh：ckpt / prompt_dir / datasets
bash scripts/run_world_model_interaction.sh
```

`evaluation/world_model_interaction.py` 双阶段循环：决策（出动作）→ 仿真（出未来视频/状态）→ 用预测视频前 `exe_steps` 帧填回 deque → 进入下一轮，最终拼出 dm/wm/full 三类 mp4 与 TB 可视化。

### 5.3 关键超参速查

| 含义 | 配置项 | 默认 |
|---|---|---|
| 视频长度 | `data.params.train.params.video_length` / `video_length` arg | 16 |
| 隐空间分辨率 | `model.params.image_size` | `[40, 64]`（=320/8 × 512/8） |
| 帧步长 | `data.params.train.params.frame_stride` / `--frame_stride` | 配置驱动，常 2~6 |
| 历史观测步 | `n_obs_steps_imagen / n_obs_steps_acting` | 2 |
| 动作维度 | `agent_action_dim` | 16 |
| 状态维度 | `agent_state_dim` | 16 |
| DDIM 步数 | `--ddim_steps` | base 推理 16，交互 50 |
| CFG | `--unconditional_guidance_scale` | 1.0 |
| Guidance rescale | `--guidance_rescale` | 0.7 |
| 学习率缩放 | `model.base_learning_rate × num_gpus × bs × accum` | 由 `scale_lr=True` 控制 |
| 训练步数 | `lightning.trainer.max_steps` | 300000 |
| EMA decay | `LitEma decay` | 0.9999 |
| Action UNet down_dims | `unet_head_config.params.down_dims` | `[256,512,1024,2048]` |

---

## 6. 与项目其他模块的关系（备忘）

- **`external/dlimp`**：Open-X-Embodiment 数据加载（训练 base 模型时使用）；进入 `external/dlimp` 单独 `pip install -e .`。
- **配套 Hugging Face 数据**：本仓库 README 列了 5 个 Unitree 数据集（Z1_StackBox / Z1_DualArm_StackBox / Z1_DualArm_StackBox_V2 / Z1_DualArm_Cleanup_Pencils / G1_Pack_Camera）以及额外的 G1_Dex1_DiverseManip 系列（256×256 与 128×128 两档分辨率）。
- **`unitree_deploy` 的 SDK 依赖**：`unitree_sdk2_python`、`unitree_arm_interface.so`、`pinocchio>=3.2.0`、`pyrealsense2`、`opencv-python`、`rerun-sdk`、可选 `lerobot`。
- **致谢继承**：DynamiCrafter（视频扩散主干）、Diffusion Policy（动作扩散头）、ACT（temporal ensemble）、HPT（异质机器人统一表征）。

---

> 文档生成基于 commit 时仓库快照（约 80 个 Python 文件、4 个 YAML、7 份 Markdown，总计约 23k 行）。所有文件均已收录在第 2 节的全量路径表中，第 4 节按子系统给出模块级总述与关键类聚焦。
