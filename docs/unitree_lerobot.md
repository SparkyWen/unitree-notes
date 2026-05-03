# `unitree_lerobot` 仓库深度学习笔记

> **仓库定位**：Unitree Robotics 出品的 [LeRobot](https://github.com/huggingface/lerobot) 适配层。它做两件事：① 把 [`avp_teleoperate`/`xr_teleoperate`](https://github.com/unitreerobotics/xr_teleoperate) 采集的 **Unitree JSON 数据集** 转成 LeRobot 官方数据格式（v2/v3），用于 ACT / Diffusion / π0 / π0.5 / GR00T 等 policy 的训练；② 在 **真机 G1**（含 Dex1 夹爪 / Dex3-1 灵巧手 / Inspire 手 / Brainco 手）和 [`unitree_sim_isaaclab`](https://github.com/unitreerobotics/unitree_sim_isaaclab) 仿真环境里把训练好的 policy 跑起来，做 closed-loop 推理验证。
>
> **代码体量**：28 个 Python 源文件 ≈ 9.5K 行；其中 `data_editor_*` 1030 × 2、`robot_arm.py` 1207、`robot_arm_ik.py` 1148 是大头。仓库版本号 `0.3.0`（v0.3 引入 LeRobot Dataset v3.0 + π0.5/GR00T policy 支持），License Apache-2.0，Python `>=3.10,<3.11`。
>
> **本文目标**：让读者读完一遍即可独立回答 ——「这个仓库到底拼了哪些零件、每个文件在干什么、JSON 数据是怎么变成 LeRobot v3 数据的、policy 输出怎么变成关节力矩并打到 DDS 总线上」。

---

## 目录

1. [仓库全量路径说明表](#1-仓库全量路径说明表)
2. [整体架构与三大数据流](#2-整体架构与三大数据流)
3. [`utils/` 数据转换工具链](#3-utils-数据转换工具链)
4. [`eval_robot/` 真机/仿真推理栈](#4-eval_robot-真机仿真推理栈)
5. [`eval_robot/robot_control/` —— 机械臂、IK、灵巧手三件套](#5-eval_robotrobot_control--机械臂ik灵巧手三件套)
6. [`eval_robot/image_server/` —— 多相机 ZMQ 桥](#6-eval_robotimage_server--多相机-zmq-桥)
7. [`eval_robot/utils/` —— 推理辅助层](#7-eval_robotutils--推理辅助层)
8. [`eval_robot/assets/` —— URDF、MJCF 与重定向配置](#8-eval_robotassets--urdfmjcf-与重定向配置)
9. [`data_editor/` —— PyQt5 数据剪辑 GUI](#9-data_editor--pyqt5-数据剪辑-gui)
10. [`test/` —— 三个最小可跑示例](#10-test--三个最小可跑示例)
11. [配置与构建文件](#11-配置与构建文件)
12. [关键设计点回顾](#12-关键设计点回顾)
13. [典型流程速查](#13-典型流程速查cheatsheet)

---

## 1. 仓库全量路径说明表

| 路径 | 类型 | 行数/规模 | 主要作用 |
| --- | --- | --- | --- |
| `LICENSE` | 文本 | ~11 KB | Apache 2.0 许可。 |
| `README.md` | Markdown | 378 行 | **英文主文档**：环境安装、数据加载/采集/处理/转换、训练（ACT/Diffusion/π0/π0.5/GR00T）、真机+仿真+数据集回测+回放、FAQ。 |
| `docs/README_zh.md` | Markdown | 345 行 | 同上的中文翻译版。 |
| `pyproject.toml` | TOML | 45 行 | 包元数据 `unitree_lerobot==0.3.0`，依赖 `tyro / matplotlib / meshcat==0.3.2 / logging_mp`；`unitree_sdk2py` 在源码注释里被 git 引用、实际让用户从 `unitree_sdk2_python` 仓库 `pip install -e .`；ruff line-length=120、bandit 跳过 B101/B311/B404/B603/B615。 |
| `.pre-commit-config.yaml` | YAML | 106 行 | pre-commit 钩子：标准检查（大文件、yaml、toml、合并冲突、行尾）、`ruff` 格式化与 lint、typo 检查、`pyupgrade --py310-plus`、Markdown 用 prettier、安全扫描 `gitleaks` + `bandit`；mypy/darglint2 注释掉了。 |
| `unitree_lerobot/` | 目录 | – | 真正的 Python 包（`pyproject.toml` 里 `packages = ["unitree_lerobot"]`）。 |
| `unitree_lerobot/utils/` | 目录 | 5 文件 / 1287 行 | **数据转换工具链**：本体配置注册表 + JSON↔LeRobot↔HDF5 互转 + 目录重命名脚本。 |
| `unitree_lerobot/utils/constants.py` | Python | 482 行 | `RobotConfig` 数据类 + 11 种本体配置（Z1 单臂/双臂、G1+Dex1/Dex1_Sim/Dex3/Brainco/Inspire、4 种带升降/底盘的扩展形态），向外暴露 `ROBOT_CONFIGS` dict。 |
| `unitree_lerobot/utils/sort_and_rename_folders.py` | Python | 40 行 | 把 `episode_*` 目录两步 rename 成 `episode_0000`/`0001`/...（先全部 uuid → 再连号），避免冲突。 |
| `unitree_lerobot/utils/convert_unitree_json_to_lerobot.py` | Python | 355 行 | **核心转换器**：`JsonDataset` 缓存 + 解嵌套字段 + 加载 jpg；`create_empty_dataset` 注册 features（state / action / 多路 image）；`populate_dataset` 逐 episode `add_frame`+`save_episode`；`local_push_to_hub` 仅上传。 |
| `unitree_lerobot/utils/convert_unitree_json_to_h5.py` | Python | 249 行 | JSON → HDF5（兼容 ACT/HIT 等老训练框架）；`H5Writer` 写 `/observations/qpos`,`/observations/qvel`(全 0 占位),`/action`,`/observations/images/*`,`language_raw`,`substep_reasonings`。 |
| `unitree_lerobot/utils/convert_lerobot_to_h5.py` | Python | 161 行 | 反向：LeRobotDataset → HDF5；`image_dtype` 二选一：直接存 uint8 帧或 cv2 jpeg 编码后存 bytes。 |
| `unitree_lerobot/eval_robot/` | 目录 | 21 文件 / ~6000 行 | **真机/仿真推理栈** + URDF/MJCF assets。 |
| `unitree_lerobot/eval_robot/make_robot.py` | Python | 265 行 | 工厂函数 `setup_image_client` / `setup_robot_interface` / `process_images_and_observations` / `publish_reset_category`；`ARM_CONFIG`/`EE_CONFIG` 表把字符串 `--arm` `--ee` 映射到具体 controller 类。 |
| `unitree_lerobot/eval_robot/eval_g1.py` | Python | 204 行 | **真机推理主循环**：起 image client + arm + IK + EE → 用 dataset 第一帧 init pose → 30 Hz 闭环 (read obs → policy.select_action → IK 求 tau → ctrl_dual_arm + EE shared mem)。 |
| `unitree_lerobot/eval_robot/eval_g1_sim.py` | Python | 264 行 | 在 `unitree_sim_isaaclab` 里跑同一个推理循环，多了 `sim_state_subscriber`/`sim_reward_subscriber`/`reset_pose_publisher` 与 `EpisodeWriter` 数据回录、是否成功（25 帧 reward=1）的判定与场景重置。 |
| `unitree_lerobot/eval_robot/eval_g1_dataset.py` | Python | 209 行 | **离线对齐评估**：用 dataset 自身的 observation 喂 policy，把预测 action 与 ground-truth action 都画进 matplotlib 图保存为 `figure.png`；可选 `--send_real_robot=true` 同步真机执行。 |
| `unitree_lerobot/eval_robot/replay_robot.py` | Python | 118 行 | 不调 policy，纯把 dataset 的 action 序列按时序在真机上回放，用于复现采集动作或验证标定。 |
| `unitree_lerobot/eval_robot/robot_control/robot_arm.py` | Python | 1207 行 | **DDS 机械臂驱动**：4 个控制器（G1_29 / G1_23 / H1_2 / H1）共享同一套模板：state 订阅线程 + ctrl 发布线程（250 Hz）+ velocity-clip + Kp/Kd 分级（high / low / wrist）+ go_home + 渐进/瞬时提速。 |
| `unitree_lerobot/eval_robot/robot_control/robot_arm_ik.py` | Python | 1148 行 | **双臂 IK**：基于 `pinocchio` 把 URDF reduce 成两条 7-DOF 链 + `casadi`/`ipopt` 解 SE(3) 误差最小化（位置 50× + 朝向 + 0.02 reg + 0.1 smooth），输出 `sol_q`、再 RNEA 算前馈 `sol_tauff`，并用 `WeightedMovingFilter` 平滑。同样有 G1_29 / G1_23 / H1_2 / H1 四套。 |
| `unitree_lerobot/eval_robot/robot_control/robot_hand_unitree.py` | Python | 403 行 | Unitree 自家两套手：Dex3-1（每只手 7 motor，hg LowCmd，topic `rt/dex3/{left,right}/{cmd,state}`，子进程驱动）和 Dex1-1 夹爪（每只 1 motor，go MotorCmds，topic `rt/dex1/{left,right}/{cmd,state}`，线程驱动）。 |
| `unitree_lerobot/eval_robot/robot_control/robot_hand_inspire.py` | Python | 187 行 | Inspire 手（Right id 0–5、Left id 6–11；单 topic `rt/inspire/{cmd,state}` 12 路 motor 全发）。 |
| `unitree_lerobot/eval_robot/robot_control/robot_hand_brainco.py` | Python | 196 行 | Brainco 手（每只 6 motor，左右独立 topic `rt/brainco/{left,right}/{cmd,state}`，dq=1.0 作为速度引导）。 |
| `unitree_lerobot/eval_robot/image_server/image_server.py` | Python | 332 行 | 单进程多相机服务端：`OpenCVCamera`/`RealSenseCamera` 抽象，`hconcat` 拼接 head 与 wrist 图，`cv2.imencode` 成 jpeg，`zmq.PUB` 单端口推流；可选 `Unit_Test=True` 加 `dI`(timestamp+frame_id) 头方便延迟测量。 |
| `unitree_lerobot/eval_robot/image_server/image_client.py` | Python | 202 行 | `zmq.SUB` 客户端：解 jpeg → 写两块共享内存（tv 半幅 + wrist 半幅，按宽度从两侧裁切），可选打开 cv2 imshow，可选启用延迟/丢帧统计。 |
| `unitree_lerobot/eval_robot/utils/utils.py` | Python | 152 行 | 推理通用工具：`extract_observation`/`predict_action`/`reset_policy`/`cleanup_resources`/`to_list`/`to_scalar` + `EvalRealConfig` dataclass（真机/数据集两个入口共用的命令行配置）。 |
| `unitree_lerobot/eval_robot/utils/rerun_visualizer.py` | Python | 166 行 | 自动嗅探 step 里的 image / state / action 字段并向 [Rerun](https://rerun.io) 推送，自动构建 grid blueprint + TimeSeriesView。 |
| `unitree_lerobot/eval_robot/utils/episode_writer.py` | Python | 219 行 | 异步写盘：`Queue` + worker 线程把 `add_item` 的图像/depth/audio/state/action 落到 `episode_XXXX/{colors,depths,audios,data.json}`，与采集格式完全一致。 |
| `unitree_lerobot/eval_robot/utils/sim_state_topic.py` | Python | 402 行 | 仿真专用 DDS 桥：`SharedMemoryManager`（512 B 头 + JSON payload），`SimStateSubscriber` 订阅 `rt/sim_state`、`SimRewardSubscriber` 订阅 `rt/rewards_state`，写到命名共享内存（`sim_state_cmd_data`/`sim_reward_cmd_data`）方便其它进程读。 |
| `unitree_lerobot/eval_robot/utils/sim_savedata_utils.py` | Python | 210 行 | 仿真版 `EvalRealConfig`（多 `sim/save_data/task_dir/max_episodes` 字段）+ `process_data_add` 把 obs/state/action 重新拆成 left/right_arm + left/right_ee + body 字典再喂 `EpisodeWriter` + `is_success` 在 reward≥25 时 save success / `episode_num>max_episodes` 时 save fail，并 `publish_reset_category(1, ...)` 把场景拉回初始。 |
| `unitree_lerobot/eval_robot/utils/weighted_moving_filter.py` | Python | 99 行 | 通用加权滑动滤波器（窗口=权重数）+ 一段 matplotlib 自比较 demo（`__main__`）；IK 解默认用 `weights=[0.4,0.3,0.2,0.1], data_size=14`。 |
| `unitree_lerobot/eval_robot/assets/g1/` | 目录 | 4 文件 + 64 STL | G1 整机 URDF：`g1_body23.urdf`(903 行) / `g1_body29_hand14.urdf`(1476 行) / `g1_body29_hand14.xml`(MJCF) / `README.md`（描述了 9 种 mode_machine 配置矩阵）+ 64 个 STL 网格。 |
| `unitree_lerobot/eval_robot/assets/unitree_hand/` | 目录 | 3 + 22 STL | Dex3-1 左右 URDF + `unitree_dex3.yml`（指尖映射 + DexPilot/vector retarget 参数）。 |
| `unitree_lerobot/eval_robot/assets/inspire_hand/` | 目录 | 3 + 30+ STL | Inspire 左右 URDF + `inspire_hand.yml`。 |
| `unitree_lerobot/eval_robot/assets/brainco_hand/` | 目录 | 3 + 30+ STL | Brainco 左右 URDF + `brainco.yml`。 |
| `data_editor/data_editor_EN.py` | Python | 1030 行 | **PyQt5 数据集剪辑器**：`ImageLabel`/`RangeSlider`/`DatasetPlayer` 三件套；2×2 多相机回放、Shift+拖动选区间、按钮裁剪 episode 内帧、删除整个 episode、自动重新编号 + 同步改写 `data.json`。 |
| `data_editor/data_editor_CN.py` | Python | 1030 行 | 同上的中文版（仅按钮文字/对话框/标签是中文）。 |
| `test/test_load_dataset.py` | Python | 10 行 | 最小示例：用 `LeRobotDataset` 远程拉 `unitreerobotics/G1_Dex3_ToastedBread_Dataset`，遍历第 1 个 episode。 |
| `test/test_load_h5.py` | Python | 93 行 | `read_hdf5(h5_path)` 工具脚本：打印结构、打印每个 dataset 的 shape/dtype/MB、把第一帧图存为 jpg，并打印中心 4×4 像素值。 |
| `test/test_local_push_to_hub.py` | Python | 16 行 | 把本地已经存好的 LeRobotDataset 推到 HF Hub（`upload_large_folder=True`）。 |

> **不在仓库里但被反复引用**：`unitree_lerobot/lerobot/`（HuggingFace LeRobot，commit `0878c68`，作为 git submodule，需要 `--recurse-submodules` 拉取并 `pip install -e .`）；`unitree_sdk2py`（来自 [`unitree_sdk2_python`](https://github.com/unitreerobotics/unitree_sdk2_python)，提供 `ChannelPublisher/Subscriber` 与 `idl/`）；可选 `pyrealsense2`、`PyQt5`、`rerun-sdk`、`pinocchio`、`casadi`/`ipopt`、`meshcat`。

---

## 2. 整体架构与三大数据流

### 2.1 仓库在 Unitree 软件栈中的位置

```
┌────────────────────────┐ 1. 数据采集
│ xr_teleoperate /       │   AVP/手套 → DDS → 真机 → JSON 落盘
│ avp_teleoperate (g1)   │   (episode_XXXX/{colors,depths,audios,data.json})
└──────────┬─────────────┘
           │  rsync /U盘 / NFS
           ▼
┌────────────────────────┐ 2. 数据处理 + 转换 (本仓库 utils/, data_editor/)
│ unitree_lerobot/utils  │   sort_and_rename_folders.py    ← 目录连号
│   convert_unitree_     │   convert_unitree_json_to_lerobot.py
│      json_to_lerobot   │     ↓ HF_LEROBOT_HOME/<repo_id>/  (parquet+mp4)
│   convert_unitree_     │   convert_unitree_json_to_h5.py    ← 兼容老训练
│      json_to_h5        │   convert_lerobot_to_h5.py         ← 反向兼容
│ data_editor/*.py       │   裁剪坏帧、删坏 episode、重排 idx
└──────────┬─────────────┘
           │  push_to_hub  /  本地路径
           ▼
┌────────────────────────┐ 3. 训练 (在 lerobot submodule, 本仓库不含)
│ lerobot/scripts/       │   ACT / Diffusion / π0 / π0.5 / GR00T
│   lerobot_train.py     │   输出: outputs/<run>/checkpoints/<step>/pretrained_model
└──────────┬─────────────┘
           ▼
┌────────────────────────┐ 4. 推理验证 (本仓库 eval_robot/)
│ eval_robot/eval_g1.py        ← 真机 30 Hz 闭环
│ eval_robot/eval_g1_sim.py    ← unitree_sim_isaaclab 仿真
│ eval_robot/eval_g1_dataset.py← 离线 dataset 对齐
│ eval_robot/replay_robot.py   ← 不调 policy，纯回放
└──────────┬─────────────┘
           ▼
       Unitree G1 / 仿真 G1 + Dex1 / Dex3 / Inspire / Brainco
```

### 2.2 数据格式版本三件套

```
Unitree JSON (采集格式)               LeRobot v2/v3 (训练格式)             HDF5 (兼容老 framework)
episode_XXXX/                        HF_LEROBOT_HOME/<repo_id>/           episode_X.hdf5
├── colors/000000_color_0.jpg        ├── data/chunk-000/episode_*.parquet ├── /observations/qpos
├── colors/000000_color_1.jpg        │     ├ observation.state            ├── /observations/qvel
├── colors/000000_color_2.jpg        │     ├ action                       ├── /observations/images/<cam>
├── depths/...                       │     └ ...                          ├── /action
├── audios/...                       ├── videos/chunk-000/                ├── /language_raw
└── data.json                        │     └ <cam>/episode_*.mp4          └── /substep_reasonings
    ├── info {版本/帧率/相机/joint_names}└── meta/{stats,info,episodes}.json
    ├── text {goal/desc/steps}
    └── data [{idx, colors:{}, depths:{}, states:{left_arm,right_arm,
              left_ee,right_ee,body}, actions:{...同}, audios:{}, ...}]
```

### 2.3 真机推理的进程/线程拓扑（`eval_g1.py`）

```
eval_g1.py (主进程)
├── Image client (threading.Thread, daemon)
│     └── ZMQ_SUB ← image_server :5555
│         └── 写 tv_img / wrist_img 共享内存
│
├── G1_29_ArmController (主进程内)
│     ├── _subscribe_motor_state [thread]   ← lowstate_subscriber rt/lowstate
│     └── _ctrl_motor_state      [thread]   → lowcmd_publisher rt/lowcmd 250Hz
│
├── G1_29_ArmIK (主进程内, 同步求解)
│     └── pinocchio + casadi + ipopt (~50 iter, tol 1e-6)
│
├── EE Controller (e.g. Dex3_1_Controller)
│     ├── _subscribe_hand_state [thread]      ← rt/dex3/*/state
│     └── control_process       [Process]     → rt/dex3/*/cmd 100Hz
│         └── 用 multiprocessing.Array 与主进程双向同步 left/right_q
│
└── Main loop (30 Hz)
      ├ tv_img/wrist_img → torch tensors
      ├ arm_ctrl.get_current_dual_arm_q
      ├ ee_shared_mem["state"][:]
      ├ predict_action(observation, policy, ...)   # AMP / inference_mode
      ├ arm_ik.solve_tau(arm_action) → tau
      ├ arm_ctrl.ctrl_dual_arm(arm_action, tau)
      ├ ee_shared_mem["left/right"] ← ee_action[:ee_dof] / [ee_dof:2*ee_dof]
      └ visualization_data(... rerun_logger)
```

> **关键点**：策略输出 `[arm(14) | left_ee(ee_dof) | right_ee(ee_dof)]` 一维向量，被在主循环里切片分别发给 arm 和 EE；EE 与主循环之间通过 `multiprocessing.Array/Value` 共享，以便子进程能在 100 Hz/200 Hz 自己的频率上独立刷新而不被主循环 30 Hz 拖慢。

### 2.4 仿真推理的额外通道（`eval_g1_sim.py`）

```
                          ┌─ rt/sim_state    (env state JSON)  ────┐
unitree_sim_isaaclab  ───→├─ rt/rewards_state(reward JSON)         │ DDS
(独立进程, ChannelFactory  │  ↑ rt/lowcmd, rt/dex3/*/cmd …          │
  Initialize(1) 走本地     │  ↑ rt/reset_pose/cmd (string 类别号)    │
  domain id)               └────────────────────────────────────────┘
                                                    │
                                                    ▼
                                     SimStateSubscriber.read_data()
                                     SimRewardSubscriber.read_data()
                                     publish_reset_category(1, ...)
```

`SharedMemoryManager` 把 JSON payload 放进 512–4096 B 的命名共享内存里（前 8 B：4 B timestamp + 4 B length），别的脚本可以无锁读到最新一帧 sim 状态。

---

## 3. `utils/` 数据转换工具链

### 3.1 `constants.py` —— ROBOT_CONFIGS 总表

唯一对外类型 `RobotConfig(motors, cameras, camera_to_image_key, json_state_data_name, json_action_data_name)`，frozen dataclass。所有字段都用字符串列表，方便后续 `add_frame` 用作 features 的 `names`。

11 套配置（按 motor 数量从小到大）：

| robot_type 字符串 | motor 数 | 相机数 | 形态特征 |
| --- | :---: | :---: | --- |
| `Unitree_Z1_Single` | 7 | 2 (`cam_high` / `cam_wrist`) | Z1 单臂（含 gripper） |
| `Unitree_Z1_Dual` | 14 | 3 (`cam_high` / `cam_left_wrist` / `cam_right_wrist`) | Z1 双臂 |
| `Unitree_G1_Dex1` | 16 (=14+2) | 4 (左右 high + 左右 wrist) | G1 双 7DoF 臂 + 左右 1DoF gripper |
| `Unitree_G1_Dex1_Sim` | 16 | 3（仅 `cam_left_high` + 双 wrist） | 仿真专用，头部单视角 |
| `Unitree_G1_Dex3` | 28 (=14+14) | 4 | G1 + 双 7DoF Dex3 |
| `Unitree_G1_Brainco` | 26 (=14+12) | 4 | G1 + 双 6DoF Brainco（thumb/thumbAux/index/middle/ring/pinky） |
| `Unitree_G1_Inspire` | 26 (=14+12) | 4 | G1 + 双 6DoF Inspire（pinky/ring/middle/index/thumbBend/thumbRotation） |
| `Unitree_G1_MoveibleLift_Dex1_UseWaist` | 21 | 4 | + 2DoF waist + 1DoF lift + 移动底盘 (X/Yaw) + 双 gripper |
| `Unitree_G1_MoveibleLift_Dex1_NoUseWaist` | 19 | 4 | 同上但锁腰 |
| `Unitree_G1_Lift_Dex1_UseWaist` | 19 | 4 | + 2DoF waist + 1DoF lift + 双 gripper（无底盘） |
| `Unitree_G1_Lift_Dex1_NoUseWaist` | 17 | 4 | 同上但锁腰 |

`json_state_data_name` / `json_action_data_name` 列表里写了从原始 JSON 字典里"按点路径"取数据所需的 key 列表：例如 `"left_arm.qpos"`。这两份列表对部分形态（Lift / MoveibleLift）刻意不一致 —— state 里有 `torso.height`，action 里换成 `torso.qvel`，因为上身高度是被动可观测、却要主动用速度去控制。`_extract_data` 会把 `.` 拆开后逐级 `dict.get`。

`ROBOT_CONFIGS` dict 把字符串映射到上述 11 套配置，是整个数据转换 + 真机评估的公共注册表。

> **用 ruff 关掉 N815**：`pyproject.toml` 显式 `[tool.ruff.lint.per-file-ignores] "constants.py" = ["N815"]`，因为 motor 名是 mixed case `kLeftShoulderPitch`，要保持和 SDK 端一致。

### 3.2 `sort_and_rename_folders.py`

40 行的小工具：

1. `os.listdir` → 排序得到老目录列表；
2. 第一遍循环：每个目录 rename 成 `uuid4()` 临时名（避免新旧名冲突）；
3. 第二遍循环：按字典序 enumerate，rename 成 `episode_0000`/`0001`/...

为什么要两遍？因为如果直接 `rename(old, "episode_0001")`，万一已经有 `episode_0001` 老目录就崩；先全部 uuid 化再编号可以无条件成功。仅供采集后整理使用，不会改动 episode 内部结构。

### 3.3 `convert_unitree_json_to_lerobot.py`（最重要的一支）

包入口在文件末尾 `tyro.cli(json_to_lerobot)`，被 README 当成"标准转换命令"。三个职责合一：

#### 3.3.1 `JsonDataset` —— 缓存式 JSON 解析器

```
__init__   ┐
           ├─ _init_paths   : glob 两层得到 task/* 下所有 episode_xxxx
           ├─ _init_cache   : 一次性把所有 data.json 全部 json.load 到 list（牺牲内存换 IO）
           └─ 从 ROBOT_CONFIGS 拿走三个字段缓存到 self.*

_extract_data(episode_data, key:'states'|'actions', parts: [...])
    遍历每个 sample → 按 'left_arm.qpos' 路径递归取出 array →
    flatten → 横向拼接（concatenate）→ 形成 [T, dim] 矩阵
    （注意：当 part 在 sample 中缺失或为 None 会抛 ValueError）

_parse_images(episode_path, episode_data):
    取 sample[0]['colors'] 的 keys，过滤掉 depth；
    每个 camera key 通过 camera_to_image_key 映射成 lerobot 命名（如 color_0 → cam_left_high）；
    cv2.imread 然后 BGR2RGB 后追加进 defaultdict[image_key] = list[np.ndarray]

get_item(index)  返回 dict:
    episode_index, episode_length, state(T×dim), action(T×dim),
    cameras(dict[cam_key,list[np.ndarray]]), task(text.goal), data_cfg(camera_names/H/W/dim)
```

#### 3.3.2 `create_empty_dataset(repo_id, robot_type, mode='video', has_velocity, has_effort, dataset_config)`

按 `RobotConfig` 注册 LeRobotDataset features：

- `observation.state` / `action` 都是 shape `(len(motors),)`、dtype `float32`，名字直接复用 motor list；
- 可选 `observation.velocity` / `observation.effort`（默认 false）；
- 每个相机 → `observation.images.{cam}`，shape 写死 `(480, 640, 3)`，dtype 选 `video` 或 `image`（默认 `video`，因为 LeRobot 会自动用 ffmpeg+libsvtav1 编 mp4）；
- 如果 `HF_LEROBOT_HOME/<repo_id>` 已经存在，先 `shutil.rmtree`（粗暴覆盖，**注意**：不会备份，转之前确保无重要数据）；
- `LeRobotDataset.create(repo_id, fps=30, robot_type, features, use_videos, tolerance_s=0.0001, image_writer_processes=10, image_writer_threads=5, video_backend=None)`。

#### 3.3.3 `populate_dataset(dataset, raw_dir, robot_type)`

```
for i in range(len(json_dataset)):
    ep = json_dataset.get_item(i)
    for t in range(ep["episode_length"]):
        frame = {"observation.state": state[t], "action": action[t]}
        for cam, imgs in ep["cameras"].items():
            frame[f"observation.images.{cam}"] = imgs[t]
        frame["task"] = task   # 单 episode 只有一个 task 文本
        dataset.add_frame(frame)
    dataset.save_episode()
```

`add_frame` 内部会把 image 推进 ffmpeg 写 mp4 的 worker（10 进程 × 5 线程），所以 RAM 不会爆。

#### 3.3.4 顶层入口 `json_to_lerobot(...)` 与 `local_push_to_hub(...)`

`json_to_lerobot` 完成三步：清空旧目录 → 创建空 dataset → 填充 → 可选 `push_to_hub(upload_large_folder=True)`。`local_push_to_hub` 是单纯的"已经在本地的 dataset 直接传 Hub"，对应 `test/test_local_push_to_hub.py`。

> **mode='image' 还是 'video'**？默认 `video` 用 mp4 + libsvtav1 编码，体积小、训练时按需解码（需要 `conda install ffmpeg=7.1.1 -c conda-forge`）。`image` 模式则把每帧存成 png/jpg，体积大但解码可控。`tolerance_s=0.0001` 是 LeRobot 校验时间戳是否单调用的。

### 3.4 `convert_unitree_json_to_h5.py`

结构高度相似（同名 `JsonDataset`），但不依赖 lerobot：

- `_extract_data` 这里假设字典层级只有 `sample[key][part]['qpos']` 一层（不像 lerobot 版本支持任意 dot path）；这里不会处理 `torso.height` / `chassis.qvel` 这类二级字段，所以仅适合"纯左右臂 + 末端"的形态。
- `H5Writer.write_to_h5(episode)` 写出：
  - `/observations/qpos` `(T, state_dim) float32` gzip
  - `/observations/qvel` `(T, state_dim) float32` 全零（占位，原始 JSON 没有 qvel）
  - `/action` `(T, action_dim) float32`
  - `/observations/images/<cam>` `(T, H, W, 3) uint8` gzip，`chunks=(1,H,W,3)`
  - 元数据：`is_edited` `(1,) uint8`、`substep_reasonings` `(T,)` h5py utf-8 string、`language_raw`（标量）
  - `attrs["sim"] = False`

### 3.5 `convert_lerobot_to_h5.py`

`LeRobotDataProcessor.process_episode(idx)`：

- 用 `meta.episodes["dataset_from_index"]/[dataset_to_index]` 切片，迭代时把 `observation.image*` 的 `(C,H,W) float[0,1]` 还原成 `(H,W,C) uint8`，再 `BGR2RGB`（原本 lerobot 走的是 RGB，所以这里再转回去其实是为了存成 OpenCV 友好的 BGR；如果选 `to_bytes` 还会 jpeg 压缩 quality=100 后用 `np.void` 包成 bytes 写入）。
- 把 state / action 累积成 list 后转 H5 同上。
- 注意 `image_dtype="to_bytes"` 时 H5 dataset 的 shape 退化为 `(T,)` 但 dtype 是变长 bytes（每帧一个 jpeg blob），训练时需要解码。

---

## 4. `eval_robot/` 真机/仿真推理栈

### 4.1 顶层视图

四个入口脚本都基于 LeRobot 的 `parser.wrap()` 装饰器解析 `--policy.path=<dir>` 与 `EvalRealConfig` 数据类的字段：

| 脚本 | 是否调 policy | 是否真机 | 是否仿真 | 备注 |
| --- | :---: | :---: | :---: | --- |
| `eval_g1.py` | ✓ | ✓ | ✗ | 30 Hz 闭环；`init_arm_pose = dataset[0]["observation.state"][:arm_dof]`；按 's' 启动。 |
| `eval_g1_sim.py` | ✓ | ✗ | ✓ | 多了 sim_state/reward 订阅 + `EpisodeWriter`；`reward_sum>=25` 即视作成功并 `publish_reset_category(1,...)` 重置场景。 |
| `eval_g1_dataset.py` | ✓ | 可选 | ✗ | 用 dataset 自身的 obs 喂 policy；把 `predicted_actions` 与 `ground_truth_actions` 全部 `matplotlib` 绘到 `figure.png`；`--send_real_robot=true` 同时发真机。 |
| `replay_robot.py` | ✗ | ✓ | ✗ | 不调 policy，直接 `dataset.hf_dataset.select_columns("action")` 按帧回放；用于复现采集动作或验证标定。 |

### 4.2 `make_robot.py` —— 工厂中心

#### `ARM_CONFIG` / `EE_CONFIG`

```python
ARM_CONFIG = {
    "G1_29": {"controller": G1_29_ArmController, "ik_solver": G1_29_ArmIK, "dof": 14},
    "G1_23": {"controller": G1_23_ArmController, "ik_solver": G1_23_ArmIK, "dof": 14},
}

EE_CONFIG = {
    "dex3":    {"controller": Dex3_1_Controller,         "dof": 7, "shared_mem_type": "Array", "shared_mem_size": 7},
    "dex1":    {"controller": Dex1_1_Gripper_Controller, "dof": 1, "shared_mem_type": "Value"},
    "inspire1":{"controller": Inspire_Controller,        "dof": 6, "shared_mem_type": "Array", "shared_mem_size": 6},
    "brainco": {"controller": Brainco_Controller,        "dof": 6, "shared_mem_type": "Array", "shared_mem_size": 6},
}
```

注意：`robot_arm.py` 里其实还实现了 `H1_2_ArmController` / `H1_ArmController`（以及对应的 IK），但**没有被注册到 `ARM_CONFIG`**——它们是从 `xr_teleoperate` 移植过来的脚手架，目前 unitree_lerobot 的 `--arm` 只接受 `G1_29` / `G1_23`。

#### `setup_image_client(args)` 详解

- 根据 `args.sim` 选不同的 `img_config`（仿真用 480×640 单视角头摄，真机用 480×1280 双目头摄）；
- 用 ASPECT_RATIO_THRESHOLD=2.0 判定头摄是不是"宽幅双目"（一个相机左右贴在一起），决定 `BINOCULAR=True/False`；
- 计算 `tv_img_shape` 与 `wrist_img_shape`，`shared_memory.SharedMemory(create=True)` 各开一块；
- 启动 `ImageClient(server_address="127.0.0.1" if sim else default 192.168.123.164)` 的 `receive_process` 线程；
- 返回 dict 含 `tv_img_array / wrist_img_array / tv_img_shape / wrist_img_shape / is_binocular / has_wrist_cam / shm_resources`，主循环就此可零拷贝读图。

#### `setup_robot_interface(args)` 详解

- 实例化 `arm_ik` 与 `arm_ctrl`（`motion_mode` 决定走 `rt/lowcmd` 还是 `rt/arm_sdk`，`simulation_mode` 决定 `ChannelFactoryInitialize(1)` 走仿真 domain）；
- 如果 `--ee` 非空：按 `EE_CONFIG`/`shared_mem_type` 给左右两手建 `Array("d", size, lock=True)`（dex3/inspire/brainco）或 `Value("d", 0.0)`（dex1）作为输入 buffer；再开两个共用 buffer `state_arr/action_arr`（lock=False）+ 一把 `Lock` 给主循环写读用；用这一组 buffer 实例化 controller。`out_len` 默认是 `2 * dof`（左右拼接）；
- 仿真路径还会：开 `ChannelPublisher("rt/reset_pose/cmd", String_)`、起 `SimStateSubscriber` + `SimRewardSubscriber`、可选实例化 `EpisodeWriter(args.task_dir, frequency=30, image_size=[640, 480])`。

#### `process_images_and_observations(...)` 与 `publish_reset_category(category, publisher)`

- 前者：把头摄共享内存按 `is_binocular` 切成左右、把 wrist 共享内存切成左右，打包成 `dict[observation.images.cam_*]`（torch tensor），并同时调 `arm_ctrl.get_current_dual_arm_q()` 拿到当前 14-DoF 关节角；
- 后者：`String_(data=str(category)).Write(...)`，仿真 reset 协议（`category=1` 表示"回到初始姿态"）。

### 4.3 `eval_g1.py` 主循环细读

```
init_arm_pose = dataset[from_idx]["observation.state"][:arm_dof].cpu().numpy()
input("Enter 's'...")
arm_ctrl.ctrl_dual_arm(init_arm_pose, arm_ik.solve_tau(init_arm_pose))   # init pose + 重力补偿
sleep(1.0)

while True:
    obs, current_arm_q = process_images_and_observations(...)
    if cfg.ee:
        with ee_shared_mem["lock"]:
            full_state = np.array(ee_shared_mem["state"][:])
            left_ee_state, right_ee_state = full_state[:ee_dof], full_state[ee_dof:]
    obs["observation.state"] = torch.from_numpy(np.concatenate((current_arm_q, left_ee_state, right_ee_state))).float()
    action = predict_action(obs, policy, device, preprocessor, postprocessor, use_amp, step["task"])

    arm_action = action[:arm_dof];  tau = arm_ik.solve_tau(arm_action)
    arm_ctrl.ctrl_dual_arm(arm_action, tau)    # → 写到 q_target/tauff_target，250Hz 线程会下发

    if cfg.ee:
        left_ee_action = action[arm_dof:arm_dof+ee_dof]
        right_ee_action = action[arm_dof+ee_dof:arm_dof+2*ee_dof]
        if isinstance(ee_shared_mem["left"], SynchronizedArray):
            ee_shared_mem["left"][:]  = to_list(left_ee_action)    # multiprocessing.Array
            ee_shared_mem["right"][:] = to_list(right_ee_action)
        else:
            ee_shared_mem["left"].value  = to_scalar(left_ee_action)  # multiprocessing.Value (dex1)
            ee_shared_mem["right"].value = to_scalar(right_ee_action)

    if cfg.visualization: visualization_data(idx, obs, state_tensor.numpy(), action_np, rerun_logger)
    sleep(max(0, 1/cfg.frequency - (perf_counter()-loop_start)))
```

`predict_action`（在 `utils/utils.py`）会：① 把所有 image tensor 升 batch 维 + 转 float [0,1] + permute CHW + .to(device)；② 注入 `observation["task"]` 与 `observation["robot_type"]`；③ 跑 preprocessor → `policy.select_action` → postprocessor → 去 batch 维 → cpu。如果是 dataset 模式（`use_dataset=True`），跳过 image 的预处理，因为 lerobot 的 step 里图像已经是 [0,1] 浮点。

### 4.4 `eval_g1_sim.py` 与 `eval_g1.py` 的差异点

1. `setup_robot_interface` 走 sim 分支多带 `sim_state_subscriber` / `sim_reward_subscriber` / `episode_writer` / `reset_pose_publisher` 四个对象；
2. 主循环开头若 `cfg.save_data` 且 `episode_num==0`，调 `episode_writer.create_episode()` 开 episode；
3. 末尾 `process_data_add(episode_writer, obs, current_arm_q, full_state, action, arm_dof, ee_dof)` 把当前帧打包写盘；
4. `is_success(...)` 累计 `reward_sum`，达到 25 时保存为 `success` + reset 场景；超过 `cfg.max_episodes`（默认 1200）保存为 `fail` + 重置；
5. `reset_stats["episode_num"]` 在每帧循环末尾自增；
6. finally 段额外 `sim_state_subscriber.stop_subscribe()` 释放共享内存。

> **特别坑**：`eval_g1_sim.py` 的循环里 `reward_stats["episode_num"]` 既是"第几帧"也是"第几个 episode"——`is_success` 把它在 success/fail 时设成 `-1`（因为后面的 `+1` 会让它从 0 重新开始）。这是用一个变量同时承担两个语义，读源码时要小心。

### 4.5 `eval_g1_dataset.py` 与 `replay_robot.py`

- **`eval_g1_dataset.py`**：拿 dataset 第一个 episode 的 `from_idx`/`to_idx` 范围，逐帧 `extract_observation(step)` → `predict_action(... use_dataset=True ...)` → 同时 append 到 `ground_truth_actions[]` 与 `predicted_actions[]`。结束后用 matplotlib 给每个 action 维度画一张子图（蓝实线 GT、红虚线预测），`plt.savefig("figure.png")`。可选 `cfg.send_real_robot=true` 同步把 `arm_action` + IK 的 tau 打到真机。
- **`replay_robot.py`**：按 `cfg.episodes`（一个整数）只载入那一个 episode，遍历 `dataset.hf_dataset.select_columns("action")` 直接把 action 用 IK 解前馈 + `ctrl_dual_arm` 下发。可视化时再读图，所以 `cfg.visualization=false` 时连图像服务都可以不用起（虽然 `replay_main` 还是会调 `setup_image_client`，但只是占位）。

---

## 5. `eval_robot/robot_control/` —— 机械臂、IK、灵巧手三件套

### 5.1 `robot_arm.py` —— DDS 机械臂统一驱动

四个控制器（`G1_29_ArmController` / `G1_23_ArmController` / `H1_2_ArmController` / `H1_ArmController`）共享一套模板，本节以 `G1_29_ArmController` 为例。

#### 类成员 / 控制参数

```
q_target            14   目标关节角（左 7 + 右 7）
tauff_target        14   前馈力矩（来自 IK 的 RNEA）
arm_velocity_limit  20.0 rad/s 默认上限
control_dt          1/250 s = 4 ms 控制周期
kp_high / kd_high   300.0 / 3.0    强电机（腿/腰/肩 yaw 等）
kp_low  / kd_low    80.0 / 3.0     弱电机（脚踝、肩 pitch/roll/yaw、肘）
kp_wrist/ kd_wrist  40.0 / 1.5     腕部三轴
motion_mode         True → 走 rt/arm_sdk 接口（仅控制双臂、留出 kNotUsedJoint0 作为权重通道）
                    False → 走 rt/lowcmd 接口（全身锁定，仅双臂跟随）
simulation_mode     True → ChannelFactoryInitialize(1) 走仿真 domain
```

#### 启动序列

1. `ChannelFactoryInitialize(0|1)` 决定 DDS domain；
2. 创建 `ChannelPublisher(rt/lowcmd | rt/arm_sdk, hg_LowCmd)` 与 `ChannelSubscriber(rt/lowstate, hg_LowState)`；
3. 起 `_subscribe_motor_state` 线程，每 2 ms 把 35 路 `motor_state[id].q/dq` 拷进 `lowstate_buffer`；
4. 阻塞等到第一帧 lowstate；
5. 读取所有 35 路当前 q，给 `motor_cmd[id]` 写 mode=1，并按 weak/wrist/strong 分别填 Kp/Kd；非 arm 关节的目标 q 直接锁在当前位置（"锁住其它关节"）；
6. 起 `_ctrl_motor_state` 线程，每 4 ms 跑一次：
   - 取 `q_target` / `tauff_target`（受 `ctrl_lock` 保护）
   - **真机**：调 `clip_arm_q_target` 把 `target - current` 这一步限制在 `velocity_limit * control_dt` 内，超过就同比例缩放；**仿真**：直接透传不限速；
   - 写每路 arm 的 motor_cmd[id].q/dq=0/tau；
   - 计算 CRC、`Write(msg)`；
   - 若 `_speed_gradual_max=True`：在前 5 s 内把 `arm_velocity_limit` 从 20 线性增加到 30 rad/s。

#### 对外 API

| 方法 | 用途 |
| --- | --- |
| `ctrl_dual_arm(q_target, tauff_target)` | **主入口**：把外部计算好的 `q∈R14`、`tau∈R14` 写进 ctrl 线程的目标。 |
| `get_current_dual_arm_q()` / `_dq()` | 读双臂当前关节角/角速度（14 维）。 |
| `get_current_motor_q()` | 读全身 35 路（用于初始化锁姿）。 |
| `ctrl_dual_arm_go_home()` | `q_target=0` 后阻塞等待所有臂关节落到 \|q\|<0.05；motion_mode 下还会把 `kNotUsedJoint0` 从 1→0 渐变（这一通道是 `rt/arm_sdk` 的"权重切换"通道）。 |
| `speed_gradual_max(t=5.0)` | 启动 5 s 渐进提速。 |
| `speed_instant_max()` | 立刻把上限调到 30 rad/s。 |

#### Joint Index 枚举

- `G1_29_JointIndex`（35 路）：6 腿 + 6 腿 + 3 腰（Yaw/Roll/Pitch）+ 7 左臂 + 7 右臂 + 6 占位；`kLeftWristyaw`/`kRightWristYaw` 大小写不一致是源码原貌（前者注意是 lowercase y），调用方按枚举名取即可。
- `G1_29_JointArmIndex`（14 路）：仅 `kLeft/Right ShoulderPitch/Roll/Yaw + Elbow + WristRoll/Pitch/yaw`。
- `G1_23_*`：腰部 Roll/Pitch 和腕部 Pitch/Yaw 都改名为 `*NotUsed`，`G1_23_JointArmIndex` 缩成 10 路（每边 5 个），但控制器内部 `q_target` 仍写成 10 维，配合 23DoF 本体的 `g1_body23.urdf`。
- `H1_2_*` / `H1_*`：H1 系列 motor 数 35（H1_2）/20（H1）；H1 的双臂 DDS 顺序"先右后左"，枚举里特意把 `kLeftShoulderPitch=16, kRightShoulderPitch=12` 反过来写，目的是"对外保持和 G1 一致的左→右顺序"。

#### `__main__` 自测

直接 `python robot_arm.py` 会跑一段 demo：把双手目标 SE3 在 ±0.25 m 附近做一个螺旋运动，调用 `arm_ik.solve_ik` 和 `arm.ctrl_dual_arm`。`G1_29_ArmController(simulation_mode=True)` 让你不连真机也能跑。

### 5.2 `robot_arm_ik.py` —— pinocchio + casadi IK

四个类（`G1_29_ArmIK`、`G1_23_ArmIK`、`H1_2_ArmIK`、`H1_ArmIK`）逻辑一致，差异仅在：① URDF 文件不同；② `mixed_jointsToLockIDs` 锁住的关节集合不同；③ 末端坐标系名（L_ee/R_ee）安装位置（offset 0.05 m）。下面以 `G1_29_ArmIK` 为例。

#### 模型构建

```
robot         = pin.RobotWrapper.BuildFromURDF("g1_body29_hand14.urdf", ...)
reduced_robot = robot.buildReducedRobot(list_of_joints_to_lock=mixed_jointsToLockIDs)
                # 锁掉 12 腿 + 3 腰 + 14 手 → 留下 14 路双臂自由度
reduced_robot.model.addFrame(L_ee, ... offset (0.05,0,0))   # 末端从 wrist_yaw 沿 x 方向 5 cm
reduced_robot.model.addFrame(R_ee, ...)
```

#### 优化问题（CasADi NLP）

```
变量:    var_q ∈ R14
参数:    param_tf_l, param_tf_r ∈ R(4×4)，var_q_last ∈ R14
约束:    lower/upperPositionLimit ≤ var_q ≤ ...
误差:    translational_error = [oMf[L_ee].translation - tf_l[:3,3];
                                 oMf[R_ee].translation - tf_r[:3,3]]      ∈ R6
        rotational_error    = [log3(oMf[L_ee].R @ tf_l[:3,:3]^T);
                                log3(oMf[R_ee].R @ tf_r[:3,:3]^T)]         ∈ R6
代价:    50·||translational||² + ||rotational||² + 0.02·||q||² + 0.1·||q-q_last||²
求解器:  ipopt, max_iter=50, tol=1e-6, print_level=0, calc_lam_p=False
```

`50` 这个权重把位置误差当成主要目标（厘米级），姿态误差权重 1 让朝向跟得上但允许小偏差，正则项 `0.02·||q||²` 让解保持在零位附近（避免 IK 在零空间漂移），平滑项 `0.1·||q-q_last||²` 让相邻帧解近似（再叠加 `WeightedMovingFilter` 进一步平滑）。

#### `solve_ik(left_wrist, right_wrist, current_lr_arm_motor_q, current_lr_arm_motor_dq)`

- 用 `current_lr_arm_motor_q` 作为 warm-start 与 `var_q_last`（保平滑）；
- 调 `opti.solve()`；如果没收敛，进 except 用 `opti.debug.value(var_q)` 拿到部分解；
- `WeightedMovingFilter([0.4,0.3,0.2,0.1], 14)` 滤波；
- 用 `pin.rnea(model, data, sol_q, v=0, a=0)` 计算重力补偿力矩 `sol_tauff`（前馈给 arm 控制器）；
- 异常时返回 `(current_q, zeros(nv))`，避免猛打。

#### `solve_tau(q)`

只解 RNEA、不跑 IK。`eval_g1.py` 在初始化时用它一次（让 init pose 带重力补偿），主循环里也用它（policy 输出已经是关节角，只需要重力补偿）。

#### Visualization=True 走 meshcat

启动 `MeshcatVisualizer`，加两个红/绿/蓝坐标轴（`L_ee_target`、`R_ee_target`），方便调试。

### 5.3 灵巧手三连发

#### 5.3.1 `Dex3_1_Controller`（Unitree Dex3-1，每只手 7 motor）

- DDS topic：`rt/dex3/{left,right}/{cmd,state}`，使用 hg `HandCmd_` / `HandState_`；
- `_RIS_Mode` 内部类把 (id, status=0x01, timeout=0) 编码成 motor_mode 的 8 bit；
- 控制 fps 默认 100 Hz（独立子进程 `multiprocessing.Process`，避免与主循环 30 Hz 互相阻塞）；
- 与外界的接口：4 个 `multiprocessing.Array("d", 7)` —— `left_hand_array_in/right_hand_array_in`（policy 给的左右手目标 q）+ `dual_hand_state_array_out/dual_hand_action_array_out`（14 维状态/动作输出）+ `dual_hand_data_lock`；
- Kp=1.5、Kd=0.2 写死；
- left/right 的 motor 顺序由 `Dex3_1_Left_JointIndex`/`Dex3_1_Right_JointIndex` 给出：左手 thumb0/1/2 + middle0/1 + index0/1；右手 thumb0/1/2 + index0/1 + middle0/1（中指和食指顺序相反，可能是 SDK 端硬件接线决定）。

#### 5.3.2 `Dex1_1_Gripper_Controller`（Unitree Dex1 夹爪，每只手 1 motor）

- DDS topic：`rt/dex1/{left,right}/{cmd,state}`，使用 go `MotorCmds_`/`MotorStates_`；
- 用 `multiprocessing.Value("d", 0.0)` 作为输入（每只手就一个标量）；输出仍然是 `Array` 但长度也是 1；
- 控制 fps 默认 200 Hz（线程而非进程，比 dex3 简单）；
- Kp=5.0、Kd=0.05；`LEFT_MAPPED_MIN/RIGHT_MAPPED_MIN=0.0` 是夹爪闭合的初始电机零点（按代码注释：导轨行程 0.6 cm/rad × 9 rad ≈ 5.4 cm）。

#### 5.3.3 `Inspire_Controller`（Inspire 6 motor / 手）

- DDS topic：`rt/inspire/{cmd,state}` 单 topic、12 路 motor 一起；
- left index 6–11 / right index 0–5（与官方文档表对齐）；
- 控制 fps 100 Hz，子进程；
- `q=1.0` 是张开状态（与 Dex3 的 `q=0` 张开相反）。

#### 5.3.4 `Brainco_Controller`（Brainco 6 motor / 手）

- DDS topic：`rt/brainco/{left,right}/{cmd,state}`（左右独立 topic，与 Dex3 一致）；
- `dq=1.0` 作为速度引导（go_LowCmd 风格的 dq 不为 0）；
- motor 顺序：thumb / thumbAux / index / middle / ring / pinky。

> **统一 EE 接口约定**：四个 controller 的构造签名一致，`make_robot.py` 的 `EE_CONFIG` 表用 `shared_mem_type` 区分是 `Array(d, size)` 还是 `Value(d)`（dex1 是后者），并用 `out_len = 2*dof` 在 `state_arr/action_arr` 里左右拼接，便于主循环切片。

---

## 6. `eval_robot/image_server/` —— 多相机 ZMQ 桥

> 该图像桥比同源仓库 [`teleimager`](https://github.com/unitreerobotics/teleimager) 简化得多：**只有一条 `zmq.PUB` 端口（5555）**、**只有 jpeg + 拼帧**，没有 WebRTC、没有 Triple Ring Buffer、没有 cam_config 拉取协议。它就是个最小可用的"打包成一帧 jpeg 推到 ZMQ 上"的服务。

### 6.1 `image_server.py`

- `OpenCVCamera`：`cv2.VideoCapture(id, CAP_V4L2)` + 强制 MJPG fourcc + 设宽高/FPS；
- `RealSenseCamera`：`pyrealsense2.pipeline` + 可选 depth + 对齐 + 写 intrinsics；
- `ImageServer.send_process()` 主循环：
  1. 从 head_cameras 逐个 `get_frame()` → list；
  2. `cv2.hconcat(head_frames)` 横向拼接成一张 head 图；
  3. 如有 wrist_cameras：同样拼接成 wrist 图，再 `hconcat([head, wrist])`；
  4. `cv2.imencode(".jpg", full_color)` → bytes；
  5. 若 `Unit_Test=True`：在 jpeg 前加 12 B header `struct.pack("dI", timestamp, frame_id)` 用于丢帧/延迟统计；
  6. `socket.send(message)` 推到 `tcp://*:5555`；
- 服务端的 `_init_performance_metrics`/`_update_performance_metrics`/`_print_performance_metrics` 维护 1 s 窗口的 FPS 计算，每 30 帧打一行 log。

### 6.2 `image_client.py`

- 单次创建一个或两块共享内存 `tv_img / wrist_img`；
- `receive_process()` 在线程里：`socket.recv()` → 可选解 12 B header → `cv2.imdecode` → `np.copyto` 到共享内存；
- **图像左右切片约定**：`tv_img_array = current_image[:, : tv_img_shape[1]]`，`wrist_img_array = current_image[:, -wrist_img_shape[1]:]`。这意味着**服务端必须按 head 在前、wrist 在后的水平顺序拼帧**，客户端才能正确切回去。
- 性能模式（`Unit_Test=True`）会维护 latency / 丢帧率，每 30 帧打 log。

`make_robot.setup_image_client` 与上面这套实现是松耦合的：`make_robot.py` 自己根据 `args.sim` 决定 `tv_img_shape`/`wrist_img_shape`，所以**客户端约定服务端发的是 (480, 1280) head + (480, 1280) wrist**，要么按这个分辨率部署 image_server，要么改 `make_robot.py` 的 `img_config`。

---

## 7. `eval_robot/utils/` —— 推理辅助层

### 7.1 `utils.py` —— 共享工具

- `extract_observation(step)`：从 lerobot dataset step 里捞出 `observation.images.*`（必要时 HWC→CHW）和 `observation.state`，丢掉别的字段；用于 `eval_g1_dataset.py` 喂 dataset 给 policy。
- `predict_action(observation, policy, device, preprocessor, postprocessor, use_amp, task, use_dataset, robot_type)`：
  1. `inference_mode` + 可选 AMP autocast；
  2. 如果不是 dataset 模式，把所有 image tensor `/255 → CHW → contiguous`；
  3. 所有字段加 batch 维并 `.to(device)`；
  4. 注入 `observation["task"]` / `observation["robot_type"]`；
  5. 跑 `preprocessor → policy.select_action → postprocessor`；
  6. 去 batch 维、回到 CPU。
- `to_list(x)` / `to_scalar(x)`：把 torch.Tensor / np.ndarray / list / scalar 统一成 list 或 float，喂给 `multiprocessing.Array` 或 `Value`。
- `cleanup_resources(image_info)`：关闭并 `unlink` 所有共享内存。
- `EvalRealConfig`（dataclass）：真机版主入口的配置：

```python
repo_id: str
policy: PreTrainedConfig | None = None
root: str = ""
episodes: int = 0
frequency: float = 30.0
arm: str = "G1_29"          # G1_29 | G1_23
ee:  str = "dex3"           # dex3 | dex1 | inspire1 | brainco
motion: bool = False        # rt/arm_sdk 还是 rt/lowcmd
headless: bool = False
visualization: bool = False
send_real_robot: bool = False
use_dataset: bool = False
rename_map: dict[str, str] = {}
```

`__post_init__` 用 `parser.get_path_arg("policy")` 把 `--policy.path=<dir>` 转成 `PreTrainedConfig.from_pretrained(...)`，并把 `pretrained_path` 保存进配置；`__get_path_fields__` classmethod 让 `lerobot.configs.parser.wrap()` 知道 `policy` 字段是个"可以从 path 加载的子配置"。

### 7.2 `rerun_visualizer.py`

`RerunLogger` 自动嗅探：

- 第一次 `log_step(step_data)` 时扫一遍字典，把 `observation.images.*` (Tensor with ndim>2) 收为 image keys、`observation.state` 收为 state key、`action` 收为 action key、优先 `index` 否则 `frame_index` 作为时间序列；
- `setup_blueprint()` 给每个 image key 建一个 `Spatial2DView`，给 state/action 各建一个 `TimeSeriesView`（默认显示前 300 帧滚动窗口），整体放进 `rrb.Grid` 后 `rr.send_blueprint`；
- 之后每帧：`rr.set_time_sequence("frame", current_index)`、log 每张图、log 每路 state/action 的标量（每个关节维度一个 scalar entity_path）；
- 当 `episode_index` 切换时，写一条 `TextLog` 表明开新 episode。

`visualization_data(idx, observation, state, action, online_logger)` 是顶层 helper，它把这些字段整理成单 step dict 后调 `online_logger.log_step`。

### 7.3 `episode_writer.py` —— 仿真采集落盘器

- `__init__` 时扫描 `task_dir`，找出最大 `episode_xxxx` 编号继续往后；
- 用一个 `Queue(-1)` + 后台 `Thread(process_queue)`，把 `add_item(colors, depths, states, actions, tactiles, audios, sim_state)` 入队，worker 异步把图像/depth/audio 落盘并把 dict 里的路径换成相对路径；
- 状态机：`is_available=True` → `create_episode()` 之后变 False（此时不能开新 episode 直到上一条 save 完）→ `save_episode(result)` 触发 `need_save=True`，worker 等队列为空后再 `_save_episode` 写最终 `data.json`，然后 `is_available=True` 复位；
- 与采集端 (xr_teleoperate) 写出来的 JSON 完全同构（同样的 `info/text/data` 三层），所以仿真里采的数据可以直接走 `convert_unitree_json_to_lerobot.py`。

> 注意 `data_info()` 里 `joint_names` 和 `text` 都是占位文案（goal 写的是"积木叠放"这个 demo task 的描述），实际仓库里没有运行时根据 robot_type 自动生成 joint_names —— 如果要严肃用，需要自己改。

### 7.4 `sim_state_topic.py` —— 仿真 DDS↔共享内存桥

- `SharedMemoryManager`：构造函数尝试 `attach` 到已存在的同名共享内存，否则 `create=True`；4 B timestamp + 4 B JSON 长度 + 后续 JSON payload；带可重入锁；析构时如果是自己创建的就 `unlink`。
- `SimStateSubscriber`：起 DDS `ChannelSubscriber("rt/sim_state", String_)`，subscribe 线程（2 ms 间隔）把消息 `json.loads` 后写入 `sim_state_cmd_data` 共享内存。
- `SimRewardSubscriber`：同上，topic `rt/rewards_state`，间隔 10 ms。`reset_data()` 用一个固定 dict 占位（`{rewards:[0.0], timestamp:...}`），让"上一帧的 reward 不会被误读两次"。

调用方（`make_robot.py` sim 分支）只调 `start_sim_state_subscribe()/start_sim_reward_subscribe()` 拿到 `subscriber` 实例，主循环用 `subscriber.read_data()` 读最新一帧即可。

### 7.5 `sim_savedata_utils.py` —— 仿真专用 EvalRealConfig + 数据存储 + 成功判定

- `EvalRealConfig`（与 `utils.py` 同名但字段更多，仿真场景独立）：多了 `sim: bool = True` / `save_data: bool = False` / `task_dir: str = "./data"` / `max_episodes: int = 1200`。
- `process_data_add(episode_writer, observation_image, current_arm_q, ee_state, action, arm_dof, ee_dof)`：
  - 把 torch tensor 全部 `detach().cpu().numpy()`；
  - 遍历 `observation` 字典中的 `images.*`，CHW→HWC、float→uint8（如果最大值 ≤1 就 ×255）；
  - 把 14-DoF arm 拆成 left（前一半）+ right（后一半），左右 EE 同样按 `ee_dof` 切；
  - 拼成与采集端 JSON 同构的 `states` / `actions` 字典 → `episode_writer.add_item(...)` 入队。
- `is_success(...)`：reward_sum≥25 触发 success，>max_episodes 触发 fail；两种情况都会 reset stats、`reset_policy(policy)`、`publish_reset_category(1, ...)`、`reset_data()`；fail 还会显式把机械臂打回 init pose（`arm_ik.solve_tau` + `ctrl_dual_arm`）。

### 7.6 `weighted_moving_filter.py`

- `WeightedMovingFilter(weights, data_size)`：滑动窗 = `len(weights)`；`add_data(new_data)` 跳过重复输入、超过窗口大小则 pop 队首；`_apply_filter()` 对每一维做 `np.convolve(window, weights, "valid")[-1]`；
- `__main__` demo：用 sin+noise 数据对比三组权重的滤波效果（`[0.7,0.2,0.1]`、`[0.5,0.3,0.2]`、`[0.4,0.3,0.2,0.1]`）；
- IK 默认配置 `weights=[0.4,0.3,0.2,0.1], data_size=14`：4 帧加权平均，最近一帧权重 40%。

---

## 8. `eval_robot/assets/` —— URDF、MJCF 与重定向配置

### 8.1 `g1/`

| 文件 | 行数 | 用途 |
| --- | ---: | --- |
| `g1_body23.urdf` | 903 | 23DoF（双 5DoF 臂 + 1DoF 腰）的 URDF；`G1_23_ArmIK` 用它构造 reduced robot。 |
| `g1_body29_hand14.urdf` | 1476 | 29 + 14 = 43DoF（双 7DoF 臂 + 3DoF 腰 + 双 7DoF Dex3）；这是 `G1_29_ArmIK` 用的 URDF（IK 锁掉了腿、腰、双手 14 DoF，只留 14 双臂）。 |
| `g1_body29_hand14.xml` | – | MJCF，给 MuJoCo 用。 |
| `meshes/*.STL` | 64 文件 | 每个 link 一个网格；URDF 里相对路径引用。 |
| `README.md` | – | 列了 9 种 mode_machine 配置矩阵（mode 1/2/…/9 对应 23dof / 29dof / 29dof+hand / 29dof_lock_waist / 各种 rev_1_0 等）；`g1_body29_hand14` 是 `g1_29dof_with_hand_rev_1_0` 的修改版（`Note for teleoperate`）。 |

### 8.2 `unitree_hand/` `inspire_hand/` `brainco_hand/`

每个目录三件套：

- `<hand>_left.urdf` / `<hand>_right.urdf`：左右手 URDF（pinocchio 加载）；
- `<hand>.yml`：手部重定向（retargeting）配置，DexPilot 或 vector 二选一：
  - `target_joint_names`：要驱动的关节顺序；
  - `wrist_link_name`：基准坐标系；
  - `finger_tip_link_names`：DexPilot 末端 link；
  - `target_link_human_indices_dexpilot/_vector`：把人手 25 关键点映射到机器人 link 的索引矩阵（5×5、5×3、6×5 等）；
  - `scaling_factor`：人手→机器人手的尺度（Inspire 1.20、Brainco 0.90、Dex3 1.00）；
  - `low_pass_alpha=0.2`：低通滤波系数（值越小越平滑、滞后越大）。
- `meshes/*.STL`：手部网格。

> 重定向本身**不在本仓库代码里**实现 —— 这些 yml 是给 `xr_teleoperate` / `dex_retargeting` 这类外部包用的；本仓库只是把它们与 URDF/STL 一起放在 assets 下方便 IK 视化时复用。

---

## 9. `data_editor/` —— PyQt5 数据剪辑 GUI

> 中英双语版完全等价，只在按钮文字、对话框、窗口标题处差中文/英文。下文以 `data_editor_EN.py` 为例。

### 9.1 三个窗口部件

| 类 | 行数 | 角色 |
| --- | --- | --- |
| `ImageLabel(QLabel)` | 24–66 | 自动等比缩放的相机预览框；`setMinimumSize(320,240)`，`set_pixmap` 后 `resizeEvent` 里 `KeepAspectRatio` 缩放。 |
| `RangeSlider(QFrame)` | 68–246 | 带"当前帧光标"和"区间选择条"的一体化滑条；左键拖动 = scrub（实时预览）；Shift+左键拖动 = select（划区间）。`paintEvent` 自己画刻度、光标、绿色区间、起止数字。 |
| `DatasetPlayer(QWidget)` | 249–1017 | 主窗口：顶上"选择数据集路径"按钮、左右 ◀ ▶ 切 episode、中央 2×2 相机网格、底部 RangeSlider+「Pause/Loop Full/Loop Selected/Reset Range/Trim Selected/Delete Episode」六个按钮。 |

### 9.2 数据集结构识别

- `find_episodes()`：在 `root_dir` 下找匹配 `^episode_(\d+)$` 的子目录、按数字排序。
- `load_episode(idx)`：进入 `episode_xxxx/colors`，对每个 `\d+_color_\d+.jpg` 文件按正则提取 `frame_id`/`cam_id` 写入 `frames_map[frame_id][cam_id] = path`，得到 `frame_keys = sorted(frames_map.keys())`。
- 同时把 `episode_xxxx/data.json` 一起拿来（裁剪/删除时同步更新）。

### 9.3 三种播放模式

- **Loop Full Episode**：`play_next_frame` 自增 `current_frame_index`，超界绕回 0；
- **Loop Selected Range Only**：`current_frame_index` 跑在 `[start, end]` 之间，越界则跳回 start；
- **Pause**：暂停 `QTimer`。

### 9.4 修改磁盘的两个动作

#### `trim_selected_frames()` (行 797–847)

1. 从 `range_slider.get_selected_range()` 得到 `[start_idx, end_idx]`；
2. 计算要删除的 `frame_keys[start_idx:end_idx+1]`；
3. 弹确认对话框 → `delete_and_renumber_frames(...)`：
   - 先按 frame_id 集合 `os.remove` 所有命中的 jpg；
   - 把所有剩余 jpg `rename` 成 `__tmp__<old_id>_color_<cam>.jpg` 临时文件名（避免 rename 冲突），再按 `enumerate(sorted(old_ids))` 给每帧分配新 frame_id 并 rename 回正式名 `<new_id>_color_<cam>.jpg`；
   - 同步改写 `data.json`：去掉被删的 item、把保留 item 的 `idx` 改成 new_id，把 `colors`/`depths`/`audios` 字典里的相对路径全部换成新文件名；
4. 重新 `load_episode` 刷新 UI。

#### `delete_current_episode()` (行 849–893)

- 直接 `shutil.rmtree(episode_dir)`，刷新 episode 列表，自动跳到下一个。

### 9.5 `main()`

启动 `QApplication`，根目录写空（让用户用按钮选）。

> **限制**：当前 GUI 只识别 `colors/<frameid>_color_<cam>.jpg`，不显示 depth/audio；`data.json` 里其它字段（state/action）会被原样保留并按 idx 重映射，但不可视化、不可手工编辑。

---

## 10. `test/` —— 三个最小可跑示例

| 脚本 | 用途 |
| --- | --- |
| `test_load_dataset.py` | 用 `LeRobotDataset(repo_id="unitreerobotics/G1_Dex3_ToastedBread_Dataset")` 远程拉数据集，对第 1 个 episode 做 `from_idx → to_idx` 索引迭代；用于验证 lerobot 安装 + HF 登录 + 数据缓存路径正常。 |
| `test_load_h5.py` | `tyro` 入口，参数 `--h5-path <file>`；递归打印 HDF5 文件结构、每个 dataset 的 shape/dtype/MB；`observations/images` 数据集会把第一帧解码并 `cv2.imwrite` 出一张 jpg 给你眼睛检查；其它数据集打印前 10 个元素。 |
| `test_local_push_to_hub.py` | `tyro` 入口，参数 `--repo-id` + 可选 `--root-path`；用 `LeRobotDataset(...)` 加载本地数据集后 `dataset.push_to_hub(upload_large_folder=True)`，要求 `huggingface-cli login` 成功。 |

---

## 11. 配置与构建文件

### 11.1 `pyproject.toml`

- `name = "unitree_lerobot"`、`version = "0.3.0"`；
- `requires-python = ">=3.10,<3.11"` —— **强制 3.10**，因为依赖里有 ipopt-binding / pinocchio 这类对 Python ABI 敏感的包；
- 显式依赖只有 `tyro>=0.9.10`、`matplotlib>=3.9.0`、`meshcat==0.3.2`、`logging_mp` 四个。`unitree_sdk2py` 在源码里 import，但通过让用户去 `unitree_sdk2_python` 仓库 `pip install -e .` 注册（注释掉的 `git+...` 行说明这个依赖以前被自动拉过，现在改成手动）。
- 同样不在依赖里、却被代码 import：`opencv-python`、`pyrealsense2`、`zmq`、`pinocchio`、`casadi`、`PyQt5`、`rerun-sdk`、`h5py`、`torch` —— 这些都依赖 lerobot submodule 里 `pip install -e .` 时自动拉来。
- `[tool.ruff]` line-length = 120、target-version = py310；
- `[tool.bandit] skips = ["B101","B311","B404","B603","B615"]`：跳过 assert / random / subprocess 输入相关警告。

### 11.2 `.pre-commit-config.yaml`

钩子四组（已在路径表里讲过）：通用文件检查 / ruff 格式化与 lint / typo 检查 / pyupgrade 升级到 py310 语法 / Markdown 用 prettier / 安全扫描 gitleaks + bandit。mypy 与 darglint2 都注释掉了（"TODO: Uncomment when ready"）。

### 11.3 `docs/README_zh.md` 与根 `README.md`

345 行 vs 378 行，内容是一对一的中英对照：环境（含 conda + pinocchio + ffmpeg=7.1.1 + lerobot submodule）、`load_datasets`、采集（指向 avp_teleoperate）、`data_editor` 启动、`sort_and_rename_folders` + `convert_unitree_json_to_lerobot`（含所有 `--robot_type` 选项的列表）、训练（ACT/Diffusion/π0/π0.5/GR00T 的命令）、真机/仿真/数据集回测/回放四个评估命令、FAQ（解释 `LeRobot v2.0` 缘由、HF 401 + ffmpeg + paligemma access 三类常见错）和致谢。

---

## 12. 关键设计点回顾

### 12.1 `ROBOT_CONFIGS` 一张表撑起多本体

- 数据转换 (`convert_*`)、真机评估 (`eval_g1.py`)、IK URDF 选择都从同一个字符串 robot_type 引出；
- `motors`/`cameras` 决定 LeRobot dataset 的 features schema、`json_state_data_name`/`json_action_data_name` 决定 JSON→tensor 的拼接顺序；
- 想加新形态：在 `constants.py` 加一条 `RobotConfig`、在 `eval_robot/assets/` 放一份 URDF、在 `make_robot.py` 的 `ARM_CONFIG`/`EE_CONFIG` 表里加一行映射。`robot_arm.py` / `robot_arm_ik.py` 不需要改。

### 12.2 三层频率解耦

- 主循环（policy 推理）30 Hz —— `time.sleep(max(0, 1/freq - elapsed))`；
- 机械臂控制线程 250 Hz（`control_dt=1/250`）+ velocity-clip 限制每步移动；
- 灵巧手子进程/线程 100 Hz（dex3/inspire/brainco）或 200 Hz（dex1）；
- 三层之间用 `multiprocessing.Array/Value/Lock` 与 `DataBuffer(threading.Lock)` 解耦，保证 30 Hz 卡顿不会让低层放飞，250 Hz 计算稳定。

### 12.3 IK 输出 + RNEA 前馈两条路并发

- `solve_ik` 输出 `(sol_q, sol_tauff)`：**关节位置**走 `q_target`，让 PD 控制器收敛到目标；**前馈力矩**走 `tauff_target` 抵消重力（RNEA 算的是无加速度时的"静态保持力矩"）。
- policy 输出仅有 `q`（一维向量），没有 tau，`eval_g1.py` 在每帧用 `arm_ik.solve_tau(arm_action)` 单独跑 RNEA 拿 `tau`；这是一个轻量调用（不跑优化、纯 RNEA），对 30 Hz 主循环很友好。

### 12.4 仿真域和真机域用同一份代码

- `simulation_mode=True` 仅做两件事：① `ChannelFactoryInitialize(1)` 走 sim domain id；② 关闭 `clip_arm_q_target` 的速度限幅（仿真不需要保护硬件）；
- 仿真数据采集（`save_data=true`）借用 `EpisodeWriter` 落盘成与真机采集一致的 JSON，直接喂 `convert_unitree_json_to_lerobot.py`。

### 12.5 数据格式三向互转

- Unitree JSON ↔ LeRobot v2/v3：核心是 `convert_unitree_json_to_lerobot.py`，用嵌套 dot path 解析 + 逐 episode `add_frame/save_episode`；
- LeRobot ↔ HDF5：`convert_lerobot_to_h5.py` + `convert_unitree_json_to_h5.py` 的合集；HDF5 留着是为了兼容 ACT/HIT 等 pre-LeRobot 的训练 framework；
- `data_editor` 写盘后保持的是 Unitree JSON，对 LeRobot 数据集本身**不可作用**（因为 lerobot 是 parquet+mp4，没法逐帧改）。

### 12.6 与上下游仓库的关系

- **上游**：`xr_teleoperate` / `avp_teleoperate` —— 数据采集端；`unitree_sdk2_python` —— DDS 通讯底座；`lerobot`（submodule）—— 训练 + 数据集格式定义；`unitree_sim_isaaclab` —— 仿真端。
- **下游**：HuggingFace Hub 的 `unitreerobotics/*` datasets（如 `G1_Dex3_ToastedBread_Dataset`、`G1_Dex1_*`、`G1_Inspire_*`、`G1_Brainco_*` 系列）。

### 12.7 motion_mode vs 普通 lowcmd

- 普通 lowcmd（`rt/lowcmd`）：full body 锁定，仅双臂 motor 跟随 `q_target`；适合"调试或 policy 微动作"，安全但不能跨身段；
- `rt/arm_sdk` (`motion_mode=True`)：用 Unitree 原厂的"上半身脱附"功能，把双臂从全身控制中分离出来，可以跑大幅运动；`kNotUsedJoint0` 通道写一个 [0,1] 权重做平滑切换（`go_home` 时从 1 →0 渐变）。两种模式的 Kp/Kd 一致，差别只在底层接管对象。

---

## 13. 典型流程速查（cheatsheet）

### 13.1 从空仓库到能加载数据集（10 分钟）

```bash
git clone --recurse-submodules https://github.com/unitreerobotics/unitree_lerobot.git
cd unitree_lerobot

conda create -y -n unitree_lerobot python=3.10
conda activate unitree_lerobot
conda install pinocchio -c conda-forge
conda install ffmpeg=7.1.1 -c conda-forge

cd unitree_lerobot/lerobot && pip install -e .   # lerobot submodule
cd ../../ && pip install -e .                     # 本仓库

huggingface-cli login                             # 拉远程数据集需要

python test/test_load_dataset.py                  # 验证
```

### 13.2 从原始 JSON 到上传 HF Hub

```bash
# 第一次：让目录连号
python unitree_lerobot/utils/sort_and_rename_folders.py --data_dir $HOME/datasets/task_name

# 第二次：JSON → LeRobot Dataset (本地 + push 到 hub)
python unitree_lerobot/utils/convert_unitree_json_to_lerobot.py \
    --raw-dir $HOME/datasets \
    --repo-id <your_name>/<task_name> \
    --robot_type Unitree_G1_Dex3 \
    --push_to_hub
```

数据集会落到 `$HOME/.cache/huggingface/lerobot/<your_name>/<task_name>/`，并自动推到 Hub。如果只想本地存：去掉 `--push_to_hub`，事后再 `python test/test_local_push_to_hub.py --repo-id ... --root-path ...`。

### 13.3 训练 + 真机评估 (Dex3 例)

```bash
# 1) 训练（在 lerobot submodule 里）
cd unitree_lerobot/lerobot
python src/lerobot/scripts/lerobot_train.py \
    --dataset.repo_id=unitreerobotics/G1_Dex3_ToastedBread_Dataset \
    --policy.push_to_hub=false \
    --policy.type=diffusion
# 输出：unitree_lerobot/lerobot/outputs/train/<date>/<run>/checkpoints/<step>/pretrained_model/

# 2) 启动 image server（在机器人主控上）
python unitree_lerobot/eval_robot/image_server/image_server.py

# 3) 真机评估
python unitree_lerobot/eval_robot/eval_g1.py \
    --policy.path=unitree_lerobot/lerobot/outputs/train/<date>/<run>/checkpoints/<step>/pretrained_model \
    --repo_id=unitreerobotics/G1_Dex3_ToastedBread_Dataset \
    --frequency=30 --arm=G1_29 --ee=dex3 \
    --visualization=true
# 终端按 's' + Enter 启动闭环
```

### 13.4 仿真评估 + 自动数据回录

```bash
# 1) 启动 unitree_sim_isaaclab 场景（参见对应仓库）
# 2) 启动 image server（仿真模式下也要起，只是相机源不同）
# 3) 启动评估 + 回录数据
python unitree_lerobot/eval_robot/eval_g1_sim.py \
    --policy.path=<.../pretrained_model> \
    --repo_id=unitreerobotics/G1_Dex3_ToastedBread_Dataset \
    --frequency=30 --arm=G1_29 --ee=dex3 \
    --visualization=true \
    --save_data=true --task_dir=./data --max_episodes=1200
```

`./data/episode_xxxx/` 会按 reward 触发自动滚动开新 episode。

### 13.5 离线对齐策略（不连真机）

```bash
python unitree_lerobot/eval_robot/eval_g1_dataset.py \
    --policy.path=<.../pretrained_model> \
    --repo_id=unitreerobotics/G1_Dex3_ToastedBread_Dataset \
    --frequency=30 --arm=G1_29 --ee=dex3 \
    --visualization=true \
    --send_real_robot=false
# 结束后看 figure.png：每个 action 维度一张子图，蓝色 GT vs 红色预测
```

### 13.6 数据集回放到真机（无 policy）

```bash
python unitree_lerobot/eval_robot/replay_robot.py \
    --repo_id=unitreerobotics/G1_Dex3_ToastedBread_Dataset \
    --root="" \
    --episodes=0 \
    --frequency=30 \
    --arm=G1_29 --ee=dex3 \
    --visualization=true
```

适合"采集后立刻在真机上 replay 一遍验证 IK / 关节限位 / 标定"。

### 13.7 数据剪辑（删坏 episode、剪坏帧）

```bash
pip install PyQt5
python data_editor/data_editor_EN.py
# 顶部 "Select Dataset Path" → 选 task 目录
# Shift+鼠标拖动 RangeSlider 选区间 → "Trim Selected Range"
# "Delete Current Episode" 删整个 episode
```

注意：Editor 只识别 `colors/`，但会同步把 `data.json` 里所有保留 item 的 `idx` 重新编号 + 把 `colors/depths/audios` 的相对路径换成新名字。

---

> **完成边界**：本笔记覆盖了仓库内**所有 28 个 Python 源文件 + 4 份 yml + 3 份 URDF 目录 + 全部 markdown/toml/yaml 配置**的功能职责与关键 API。`lerobot/` submodule（HF 训练框架）、`unitree_sdk2py` （DDS）、`pyrealsense2` 等外部依赖只在交互边界处提及。要想再深一层，需直接读 `lerobot/src/lerobot/policies/*` 或 `unitree_sdk2_python/`。
