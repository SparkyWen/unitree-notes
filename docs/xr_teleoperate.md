# xr_teleoperate 仓库全量代码精读

> **位置**: `unitree-notes/xr_teleoperate/`
> **上游**: <https://github.com/unitreerobotics/xr_teleoperate>
> **当前版本**: v1.5 (2025-12-29)
> **作用**: 使用 XR 设备（Apple Vision Pro / PICO 4 Ultra Enterprise / Meta Quest 3 等）对宇树 G1/H1/H1_2 人形机器人进行**手臂 + 末端执行器（夹爪/灵巧手）**的实时遥操作，支持仿真 / 实物部署、数据录制（用于模仿学习）以及通过手柄摇杆驱动机器人行走。

---

## 0. 速读

### 0.1 仓库一句话定位

xr_teleoperate 是一套以 **Pinocchio + CasADi/IPOPT** 在线求解双臂逆运动学、以 **dex-retargeting (DexPilot)** 进行手部关节重定向、通过 **Unitree DDS** 把控制指令发送到机器人、并通过 **Vuer + WebRTC/ZMQ** 把机器人头部相机画面投到 XR 头显的"VR 体感操作台"。它是宇树官方推荐的 **数据采集（Imitation Learning）入口**，所录制的 episode 与 [unitree_IL_lerobot](https://github.com/unitreerobotics/unitree_IL_lerobot) / [unifolm-vla](https://github.com/unitreerobotics/unifolm-vla) 兼容。

### 0.2 顶层数据流（30 fps 主循环）

```
┌────────┐ wrist 4×4 SE3 ┌──────────────┐ q (14)+τ ┌─────────┐ DDS rt/lowcmd ┌─────────┐
│ XR 头显 │──────────────▶│ ArmIK (CasADi│─────────▶│ ArmCtrl │──────────────▶│  机器人  │
│ (Vuer) │               │ +IPOPT, 30Hz)│          │ (250Hz) │               │  (PC1)  │
│  hand  │ 25×3 skeleton ┌──────────────┐ q (6/7)  ┌─────────┐ DDS rt/dex*/* └─────────┘
│  pose  │──────────────▶│HandRetarget. │─────────▶│HandCtrl │──────────────▶
└────────┘               │ DexPilot     │          │(100Hz)  │
   ▲                     └──────────────┘          └─────────┘
   │ 头部 camera (BGR)            ▲
   └──────── teleimager ──────────┘
```

录制开关打开后，主循环把 `head/wrist 图像 + 双臂 q + 末端 q (state/action)` 喂给 `EpisodeWriter`，后台线程异步落盘成 `episode_xxxx/{colors,depths,audios,data.json}`。

---

## 1. 仓库全量目录与文件作用速查表

| 路径 | 类型 | 作用 |
| --- | --- | --- |
| `README.md` / `README_zh-CN.md` / `README_ja-JP.md` | 文档 | 三语主 README：项目介绍、安装、启动参数、仿真+实物部署步骤、状态转移图链接 |
| `CHANGELOG.md` / `CHANGELOG_zh-CN.md` | 文档 | 版本变更日志（v0.5 oldvuer → v1.5），记录每个版本的新增功能（IPC、affinity、motion-switcher、URDF 缓存、WebRTC 头相机等） |
| `Device.md` / `Device_zh-CN.md` | 文档 | 硬件清单：XR 设备型号、双目相机选型（30/60FPS）、腕部相机（D405/单目）、3D 打印件下载链接、装配示意 |
| `LICENSE` | 文档 | Apache 2.0 |
| `requirements.txt` | 配置 | 主程序依赖：matplotlib==3.7.5, rerun-sdk==0.20.1, meshcat==0.3.2, sshkeyboard==2.3.1 |
| `.gitmodules` | 配置 | 三个子模块定义：`teleop/televuer`、`teleop/robot_control/dex-retargeting`、`teleop/teleimager` |
| `.gitignore` | 配置 | 标准 Python ignore，外加 `*.pkl`（IK 模型缓存） |
| `img/` | 资源 | 视频封面、头部/腕部相机支架渲染图、实物装配照片 |
| **`assets/`** | **机器人模型** | 各机器人/灵巧手的 URDF/MJCF/STL/YAML 配置（IK 与 retargeting 共用） |
| `assets/g1/g1_body23.urdf` | URDF | G1 23 自由度版（腰只有 yaw，腕只有 roll） |
| `assets/g1/g1_body29_hand14.urdf` | URDF | G1 29 自由度 + 双手共 14 个手指关节，IK 主用 |
| `assets/g1/g1_body29_hand14.xml` | MJCF | 同上的 MuJoCo 版本 |
| `assets/g1/meshes/*.STL` | 网格 | G1 全身可视/碰撞网格（含 dex3 手指） |
| `assets/g1/README.md` | 文档 | G1 多种 mode_machine 与自由度配置对照表 |
| `assets/h1/h1_with_hand.urdf` + `meshes/` | URDF+网格 | H1（4 自由度手臂）+ inspire 手 URDF |
| `assets/h1_2/h1_2.urdf` / `h1_2.xml` / `scene.xml` + `meshes/` | URDF/MJCF | H1_2（7 自由度手臂）+ inspire 手 |
| `assets/inspire_hand/inspire_hand.yml` | YAML | 因时灵巧手 dex-retargeting (DexPilot) 配置（左右手共两节） |
| `assets/inspire_hand/inspire_hand_left.urdf` / `_right.urdf` + `meshes/` | URDF+网格 | 因时灵巧手左右独立 URDF |
| `assets/unitree_hand/unitree_dex3.yml` | YAML | 宇树 Dex3-1 dex-retargeting 配置 |
| `assets/unitree_hand/unitree_dex3_left.urdf` / `_right.urdf` + `meshes/` | URDF+网格 | Dex3-1 左右独立 URDF |
| `assets/brainco_hand/brainco.yml` | YAML | 强脑灵巧手 dex-retargeting 配置 |
| `assets/brainco_hand/brainco_left.urdf` / `_right.urdf` + `meshes/` | URDF+网格 | 强脑灵巧手左右独立 URDF |
| **`teleop/`** | **主代码包** | 所有 Python 业务逻辑 |
| `teleop/teleop_hand_and_arm.py` | 主入口 | 解析 CLI 参数，初始化 IK / Arm / EE / IPC / 录制 / 仿真，跑主循环（531L） |
| `teleop/robot_control/` | 控制子包 | 机器人 IK + 关节下发 + 灵巧手映射 |
| `teleop/robot_control/hand_retargeting.py` | 模块 | 把 dex-retargeting 包装成统一接口（INSPIRE/UNITREE_DEX3/BRAINCO 三类配置） |
| `teleop/robot_control/robot_arm.py` | 模块 | 4 个机器人控制器（G1_29 / G1_23 / H1_2 / H1）：DDS 订阅 lowstate、发布 lowcmd、刚度配置、速度限幅 |
| `teleop/robot_control/robot_arm_ik.py` | 模块 | 4 个 ArmIK 类，CasADi/IPOPT 双臂 IK，含 URDF→reduced model 缓存、加权移动滤波、Meshcat 可视化 |
| `teleop/robot_control/robot_hand_unitree.py` | 模块 | Dex3-1 灵巧手 + Dex1-1 夹爪（独立两个 Controller）控制器 |
| `teleop/robot_control/robot_hand_inspire.py` | 模块 | 因时灵巧手 DFX 版（unitree 中转）+ FTP 版（直连官方 SDK） |
| `teleop/robot_control/robot_hand_brainco.py` | 模块 | 强脑科技 RevolimbHand 控制器 |
| `teleop/robot_control/dex-retargeting/` | **submodule** | <https://github.com/silencht/dex-retargeting>，DexPilot/Vector 重定向核心算法库（**未克隆于本地**） |
| `teleop/utils/` | 工具子包 | 数据录制、可视化、IPC、辅助滤波 |
| `teleop/utils/episode_writer.py` | 模块 | 异步队列把 `colors+depths+states+actions` 写盘成 `episode_xxxx/data.json + 图像` |
| `teleop/utils/rerun_visualizer.py` | 模块 | RerunLogger（在线时序图）+ RerunEpisodeReader（离线回放） |
| `teleop/utils/ipc.py` | 模块 | ZMQ-IPC 服务端/客户端，REP 接收 CMD_*、PUB 心跳，给外部 Agent 程序调用 |
| `teleop/utils/motion_switcher.py` | 模块 | MotionSwitcherClient + LocoClient 的薄封装（进/出 Debug 模式、阻尼模式、移动） |
| `teleop/utils/sim_state_topic.py` | 模块 | 订阅 IsaacLab 仿真发出的 `rt/sim_state`，通过共享内存供主循环读取 |
| `teleop/utils/weighted_moving_filter.py` | 模块 | N 阶加权滑动均值滤波（IK 解、夹爪指令的平滑） |
| `teleop/televuer/` | **submodule** | <https://github.com/unitreerobotics/televuer>，Vuer 封装：从 XR 设备拉手势/手柄/腕部位姿，向 XR 推图像（**未克隆于本地**） |
| `teleop/teleimager/` | **submodule** | <https://github.com/unitreerobotics/teleimager>，PC2 图像服务端 + 主机图像客户端，支持 ZMQ + WebRTC（**未克隆于本地**） |

> **注意**：`teleop/televuer/`、`teleop/teleimager/`、`teleop/robot_control/dex-retargeting/` 是 git submodule，本地工作树中**未初始化**（需 `git submodule update --init --depth 1` 才能拉到代码）。本文档对它们的描述基于代码中的导入与 README 的二手信息，未做实现级精读。

---

## 2. 顶层文档与配置

### 2.1 `README` / `README_zh-CN` / `README_ja-JP`

三语 README，结构相同，主要章节：

1. **介绍**：列出已支持的机器人/末端执行器配置矩阵（G1 29DoF、G1 23DoF、H1 4DoF、H1_2 7DoF；夹爪 Dex1-1、灵巧手 Dex3-1 / 因时 DFX/FTP / 强脑），并给出 Unitree 在线 OSS 上的"系统示意图"和"状态转移图"两张总览图链接。
2. **安装**：
   - 创建 `conda create -n tv python=3.10 pinocchio=3.1.0 numpy=1.26.4 -c conda-forge`
   - 浅克隆所有 submodule（teleimager / televuer / dex-retargeting）
   - 用 OpenSSL 给 televuer 生成 `cert.pem` / `key.pem`（PICO/Quest 是单证书一步生成；AVP 需要先生成 rootCA 再签 server.csr，并通过 AirDrop 安装到 AVP）
   - 配置证书路径（`~/.config/xr_teleoperate/` 或 `XR_TELEOP_CERT/KEY` 环境变量）
   - `sudo ufw allow 8012`
   - 安装 `unitree_sdk2_python`，最低 commit `404fe44`
3. **启动参数说明**：分"基础控制参数"和"模式开关参数"两表。详见 §6 启动参数速查。
4. **仿真部署 (§2)**：以 `unitree_sim_isaaclab` 为仿真后端，给出 `python sim_main.py --device cpu --enable_cameras --task Isaac-PickPlace-Cylinder-G129-Dex3-Joint --enable_dex3_dds --robot_type g129` 启动样例，然后 `python teleop_hand_and_arm.py --ee=dex3 --sim --record`，按 `r` 进入 tracking、`s` 切录制、`q` 退出。
5. **实物部署 (§3)**：相比仿真增加：在 PC2 单独启动 teleimager 图像服务、可选 inspire/brainco/dex1_1 手部服务（参考各自独立仓库）；强调安全距离、`--motion` 模式下右手柄 A 键退出、双摇杆按下软急停。
6. **代码库教程 (§4)**：给出 ASCII 目录树（注释每个文件作用），与本文档第 1 节表格的内容是一致来源。
7. **硬件 (§5)**：链接到 `Device.md`。
8. **鸣谢 (§6)**：依赖列表（OpenTeleVision、dex-retargeting、Vuer、Pinocchio、CasADi、Meshcat、PyZMQ、BunnyVisionPro、unitree_sdk2_python、ARCLab-MIT/beavr-bot）。
9. **引用 (§7)**：BibTeX。

### 2.2 `CHANGELOG_zh-CN.md`（版本演进）

| 版本 | 日期 | 关键变更 |
| --- | --- | --- |
| v0.5 (oldvuer) | 2025.04.30 | 项目最初名为 `avp_teleoperate`，仅 Vuer v0.0.32RC7 手势模式，支持 G1_29/G1_23/H1_2/H1 + dex3/gripper/inspire1 |
| v1.0 (newvuer) | 2025.07.08 | Vuer 升级 v0.0.60，新增 **手柄模式**；项目重命名为 **xr_teleoperate**；新增 headless/motion/sim 模式；默认手部映射从 Vector 改为 **DexPilot** |
| v1.1 | 2025.07.18 | 新增 `--ee=brainco`；仿真 dds domain id 改 1（避免冲突实机）；修复默认频率过高 bug |
| v1.2 | 2025.07.22 | Dex1_1 升级匹配 [dex1_1_service](https://github.com/unitreerobotics/dex1_1_service) 驱动 |
| v1.3 | 2025.10.14 | 新增 **IPC 模式**；H1_2/G1_23 加运动模式；修复启动抖动（控制器启动前先 init IK） |
| v1.4 | 2025.11.21 | 图像服务器替换为 **teleimager**（支持 WebRTC）；televuer v3.0；display-mode 增加 immersive/ego/pass-through；EpisodeWriter 重写；新增 **affinity / motion-switcher**；新增 **inspire_FTP** |
| v1.5 | 2025.12.29 | 仿真模式正式化；`--network-interface` 参数；URDF 加载缓存 (`*.pkl`)；IPC 改 `@` 抽象命名空间 |

### 2.3 `Device_zh-CN.md`

详细列出硬件 BOM 与 3D 打印件下载：

- **5.1 遥操作设备**：G1（必须开发计算单元版）、XR 头显（AVP/PICO/Quest）、WiFi6 路由器、x86_64 用户电脑、头部相机（D435i 单目 / 双目外置）、USB3.0 数据线
- **5.2 数据采集设备**（可选）：
  - **5.2.1 双目相机 60FPS**（125° FOV、60mm 基线）+ 经典版/焕新版头部支架 STEP 包链接
  - **5.2.2 双目相机 30FPS** 同上
  - **5.2.3 G1 腕部 RealSense D405**（仅 Dex3-1 推荐）+ 腕圈/腕支架 STEP
  - **5.2.4 G1 腕部单目相机** + 三种末端执行器（Dex1-1 / Dex3-1 / Inspire DFX|Brainco）各自的支架 STEP
- **5.3 安装示意图**：仿真渲染 + 实物照片对照表

### 2.4 `requirements.txt`

```
matplotlib==3.7.5     # weighted_moving_filter 单元测试可视化
rerun-sdk==0.20.1     # rerun_visualizer 在线/离线时序图
meshcat==0.3.2        # robot_arm_ik 三维可视化
sshkeyboard==2.3.1    # 主进程键盘监听（r/s/q）
```

注意 IK/Retargeting/DDS/Vuer/teleimager 的依赖**不在此文件**——它们靠 submodule 的 `pyproject.toml`/`setup.py` 各自 `pip install -e .` 时拉入。

### 2.5 `.gitmodules`

```ini
[submodule "teleop/televuer"]
    path = teleop/televuer
    url = https://github.com/unitreerobotics/televuer
[submodule "teleop/robot_control/dex-retargeting"]
    path = teleop/robot_control/dex-retargeting
    url = https://github.com/silencht/dex-retargeting
[submodule "teleop/teleimager"]
    path = teleop/teleimager
    url = https://github.com/unitreerobotics/teleimager.git
```

---

## 3. `assets/` 资源详解

`assets/` 同时被 **IK（Pinocchio + URDF）** 和 **retargeting（dex-retargeting + URDF）** 使用。三种灵巧手的 YAML 是 `dex_retargeting.RetargetingConfig.from_dict()` 的输入。

### 3.1 g1/

- `g1_body29_hand14.urdf` — G1 29 DoF 主体 + 14 指关节版（IK 默认加载，对应控制器 `G1_29_ArmController`）。基于 `g1_29dof_with_hand_rev_1_0.urdf` 修改。
- `g1_body23.urdf` — G1 23 DoF 版（腰只 yaw、腕只 roll、不含手指关节）。对应 `G1_23_ArmController`/`G1_23_ArmIK`。
- `g1_body29_hand14.xml` — MuJoCo 版本（用于仿真 IsaacLab 之外的纯 MuJoCo 验证）。
- `meshes/*.STL` — 全身约 50 个 STL（含 hip/knee/ankle/shoulder/elbow/wrist/dex3 各指节、头部、腰部、橡胶手）。
- `README.md` — `g1_29dof` 系列与 `mode_machine` 字段的对照表（mode_machine 1/2/3/4/5/6/9 对应不同 dof 与髋滚减速比）。

### 3.2 h1/

- `h1_with_hand.urdf` — H1 + 因时灵巧手版本。`H1_ArmIK` 默认加载，IK 时锁住躯干、髋、膝、踝、所有指关节，把 `L_ee/R_ee` 帧附加在 `left_elbow_joint/right_elbow_joint` 处再前向 `0.2605+0.05=0.3105 m`（H1 没有腕关节）。
- `meshes/` — STL 网格。

### 3.3 h1_2/

- `h1_2.urdf` — H1_2（7DoF 手臂）+ 因时灵巧手 URDF。`H1_2_ArmIK` 锁住下半身 12 关节 + torso + 24 个手指关节，`L_ee/R_ee` 附加在 `wrist_yaw_joint` 前 5cm。
- `h1_2.xml` / `scene.xml` — MuJoCo 版本与场景文件。

### 3.4 inspire_hand/

| 文件 | 作用 |
| --- | --- |
| `inspire_hand.yml` | 左右手 DexPilot 配置（target_joint_names / wrist_link_name / finger_tip_link_names / `target_link_human_indices_dexpilot`） |
| `inspire_hand_left.urdf` / `_right.urdf` | 因时灵巧手左右独立 URDF |
| `meshes/` | 灵巧手 STL |

### 3.5 unitree_hand/

| 文件 | 作用 |
| --- | --- |
| `unitree_dex3.yml` | DexPilot 配置示例（详见下面） |
| `unitree_dex3_left.urdf` / `_right.urdf` | Dex3-1 左右独立 URDF（含 `base_link` / `thumb_tip` / `index_tip` / `middle_tip` 三个 fingertip frame） |

`unitree_dex3.yml` 关键字段：

```yaml
left:
  type: DexPilot                # 也可选 vector
  urdf_path: unitree_hand/unitree_dex3_left.urdf
  target_joint_names: [
    left_hand_thumb_0_joint, left_hand_thumb_1_joint, left_hand_thumb_2_joint,
    left_hand_middle_0_joint, left_hand_middle_1_joint,
    left_hand_index_0_joint,  left_hand_index_1_joint,
  ]
  wrist_link_name: "base_link"
  finger_tip_link_names: ["thumb_tip", "index_tip", "middle_tip"]
  target_link_human_indices_dexpilot: [[ 9,14,14, 0,0,0], [ 4,4,9, 4,9,14]]
  scaling_factor: 1.0           # 仅 vector 用
  low_pass_alpha: 0.2           # 越小越平滑、延迟越大
right: {...}                    # 关节顺序与左手不同（thumb→index→middle）
```

`target_link_human_indices_dexpilot` 是一个 2×6 矩阵，每列定义一对人手关键点 `[origin_idx, task_idx]`，DexPilot 用相邻关键点的位置差（"6 条 fingertip-fingertip / wrist-fingertip 向量"）作为优化目标。

### 3.6 brainco_hand/

- `brainco.yml` — 强脑灵巧手 6 motor (thumb / thumb-aux / index / middle / ring / pinky) DexPilot 配置
- `brainco_left.urdf` / `_right.urdf` + `meshes/` — 左右手 URDF

---

## 4. 主入口：`teleop/teleop_hand_and_arm.py` (531 行)

整段是 `if __name__ == '__main__':` 大型 setup + 单线程主循环；模块级只保留几个全局开关与 keyboard handler。

### 4.1 全局状态机

```python
START          = False  # 是否已按 r 进入 tracking
STOP           = False  # 是否退出
READY          = False  # 是否准备好可进入 START / RECORD_RUNNING
RECORD_RUNNING = False  # 是否正在录制
RECORD_TOGGLE  = False  # 一次性切换信号（按 s 触发）
```

注释里给出状态机表格：

```
state          [Ready]   →   [Recording]   →   [AutoSave]   →   [Ready]
START          True          True              True             True
READY          True          False             False            True
RECORD_RUNNING False         True              False            False
RECORD_TOGGLE  False  ↑      True   ↑          False  ↑         False
                      手按s          手按s             自动转
```

### 4.2 关键函数

- **`on_press(key)`**：唯一的键盘 handler。`r`→`START=True`；`q`→`STOP=True`（同时清 `START`）；`s` 在 `START==True` 时设 `RECORD_TOGGLE=True`。被 `sshkeyboard.listen_keyboard` 直接调用。
- **`get_state()`**：返回 4 字段心跳 dict，给 IPC_Server 的 `_hb_loop` 当回调用，10Hz 广播给外部 Agent。
- **`publish_reset_category(category, publisher)`**：仿真专用。每次保存 episode 后向 `rt/reset_pose/cmd` 发一个 `String_(data="1")`，让 IsaacLab 自动复位场景。

### 4.3 启动参数（argparse）

| 参数 | 默认 | 选项 / 含义 |
| --- | --- | --- |
| `--frequency` | 30.0 | 主循环+录制的目标 fps |
| `--input-mode` | hand | `hand` / `controller` |
| `--display-mode` | immersive | `immersive`（沉浸）/ `ego`（通透+第一人称小窗）/ `pass-through`（纯通透） |
| `--arm` | G1_29 | `G1_29` / `G1_23` / `H1_2` / `H1` |
| `--ee` | (无) | `dex1` / `dex3` / `inspire_ftp` / `inspire_dfx` / `brainco` |
| `--img-server-ip` | 192.168.123.164 | teleimager 服务端 IP（默认 PC2） |
| `--network-interface` | None | 给 `ChannelFactoryInitialize(networkInterface=...)` 用，多网卡时必须指定 |
| `--motion` | False | 开启运控模式（不进 debug，可 R3 遥控器走路 / 手柄摇杆走路） |
| `--headless` | False | 不开 RerunLogger 窗口 |
| `--sim` | False | dds domain id=1 + 启动 sim_state_subscriber + 启动 reset_pose_publisher |
| `--ipc` | False | 启 ZMQ-IPC 服务端代替 sshkeyboard |
| `--affinity` | False | `psutil` 把主进程 affinity 绑到 CPU 0-3、子进程绑到 5-6，并 `nice(-20)` |
| `--record` | False | 开启 EpisodeWriter |
| `--task-dir` | `./utils/data/` | episode 根目录 |
| `--task-name` | `pick cube` | 子目录名 = `task_dir/task_name/episode_xxxx` |
| `--task-goal` / `--task-desc` / `--task-steps` | （示例文本） | 写入 `data.json.text` 字段，供后续模仿学习作 prompt |

### 4.4 初始化顺序（按出现顺序）

1. **DDS 初始化**：`ChannelFactoryInitialize(0 if not sim else 1, networkInterface=...)`。仿真 domain id=1，实机=0。
2. **键盘/IPC 输入**：`--ipc` 开 `IPC_Server(on_press, get_state)`；否则起一个 daemon thread 跑 `sshkeyboard.listen_keyboard(on_press, sequential=False)`。
3. **图像客户端**：`ImageClient(host=img_server_ip, request_bgr=True)`；`get_cam_config()` 拿到 `head_camera/left_wrist_camera/right_wrist_camera` 三套配置 dict（`binocular/image_shape/fps/enable_zmq/enable_webrtc/webrtc_port`）。
4. **TeleVuerWrapper**：传入 `use_hand_tracking=(input_mode=='hand')`、`binocular`、`img_shape`、`display_mode`、`zmq/webrtc/webrtc_url`。Wrapper 内部根据 display_mode 决定要不要从 PC 推图像到 XR（pass-through 不需要、immersive/ego 需要）。
5. **运动模式**：
   - `--motion` + `controller`：实例化 `LocoClientWrapper`，后面用左/右手柄摇杆喂 `client.Move(vx,vy,vyaw)`、双摇杆按下 `client.Damp()`。
   - 不 `--motion`：实例化 `MotionSwitcher` 并 **`Enter_Debug_Mode()`**——通过 `MotionSwitcherClient.ReleaseMode()` 把机器人内置控制器停掉，让 `rt/lowcmd` 直接生效。
6. **手臂 IK + 控制器**：`G1_29 / G1_23 / H1_2 / H1` 四选一。`arm_ik = ArmIK()`、`arm_ctrl = ArmController(motion_mode, simulation_mode)`。注意先创建 `arm_ik` 后创建 `arm_ctrl`——v1.3 修复"启动抖动"的关键。
7. **末端执行器**：5 选 1（也可不开），每一种都用 `multiprocessing.Array/Value` 创建：
   - 输入：`left_hand_pos_array(75)` / `right_hand_pos_array(75)`（25 个关键点 × 3 维 xyz；hand 模式下被 25×3 reshape）；`dex1` 模式下输入是单个 `Value('d')`（trigger 或 pinch 值）
   - 输出：`dual_hand_state_array(14|12|2)` / `dual_hand_action_array(14|12|2)`
   - 每个控制器内部都会 `Process(target=control_process)` 起一个**独立子进程**循环跑 retargeting + DDS 发指令
8. **affinity**：`p.cpu_affinity([0,1,2,3])` + `p.nice(-20)`，子进程绑到 `[5,6]`。
9. **仿真额外**：`reset_pose_publisher = ChannelPublisher("rt/reset_pose/cmd", String_)`、`sim_state_subscriber = start_sim_state_subscribe()`。
10. **录制**：`recorder = EpisodeWriter(task_dir, task_goal, task_desc, task_steps, frequency, rerun_log=not headless)`。
11. 设 `READY = True`，进入 **预热循环**：等待 `START==True or STOP==True`，期间每 33ms 拉一次 `head_img` 推到 XR（保持 XR 端有画面）。

### 4.5 主循环（`while not STOP:`）

每次迭代严格按 `1/frequency` 节拍 sleep，30Hz 下每帧 33ms 预算：

1. **取图**：根据 camera_config 三个 zmq 开关分别拉 `head_img / left_wrist_img / right_wrist_img`，head 还要在非 pass-through 模式下推到 XR。
2. **录制开关切换**：检查 `RECORD_TOGGLE`：
   - 当前未录 → `recorder.create_episode()` 成功后 `RECORD_RUNNING=True`
   - 当前在录 → `RECORD_RUNNING=False`，`recorder.save_episode()`（异步落盘）；仿真模式同时 `publish_reset_category(1)`
3. **拉 XR 数据**：`tele_data = tv_wrapper.get_tele_data()`。然后按 `--ee` × `--input-mode` 组合分发到对应控制器的 input shared memory：
   - `dex3 / inspire_dfx / inspire_ftp / brainco` + `hand` → 把 25×3 手部关键点 `flatten()` 写到 `left/right_hand_pos_array`
   - `dex1` + `controller` → 把左/右扳机值 `triggerValue` 写到 `left/right_gripper_value`
   - `dex1` + `hand` → 把左/右捏合度 `pinchValue` 写到同一个 Value
4. **运控+手柄**：仅 `controller + --motion` 分支：右手柄 A 键 → STOP；双摇杆按下 → `Damp()`；否则 `Move(-y*0.3, -x*0.3, -yaw*0.3)`（速度上限 0.3 m/s 是 issue#135 的产物）。
5. **读关节状态**：`current_lr_arm_q = arm_ctrl.get_current_dual_arm_q()`、`..._dq = ...get_current_dual_arm_dq()`。
6. **求解 IK**：`sol_q, sol_tauff = arm_ik.solve_ik(left_wrist_pose, right_wrist_pose, current_lr_arm_q, current_lr_arm_dq)`。`solve_ik` 内部走 IPOPT + WeightedMovingFilter。
7. **下发**：`arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)`（实际只更新两个 numpy 字段，250Hz 的 `_ctrl_motor_state` 后台线程负责真发 DDS）。
8. **录制装包**：仅 `RECORD_RUNNING==True`。装一个嵌套 dict：
   ```python
   states  = {"left_arm":{qpos,qvel,torque}, "right_arm":..., "left_ee":..., "right_ee":..., "body":...}
   actions = 同结构
   colors  = {"color_0": head_left, "color_1": head_right, "color_2": left_wrist, "color_3": right_wrist}
   ```
   `head` 双目拆成 `color_0/color_1`（左右一半）；单目则塞 `color_0`。仿真模式额外 `sim_state = sim_state_subscriber.read_data()`（json dict）。最后 `recorder.add_item(...)`。
9. **节拍**：`sleep_time = max(0, 1/frequency - elapsed)`。

### 4.6 收尾 (`finally`)

按"先归位，后断连"顺序：

1. `arm_ctrl.ctrl_dual_arm_go_home()` — 让双臂在 5 秒内回归 `q=0` 姿态（运控模式还会做 `kNotUsedJoint0.q` 1→0 渐变 weight，平滑切回 loco）。
2. 停 IPC server / sshkeyboard 监听
3. `img_client.close()`
4. `tv_wrapper.close()`
5. （注释掉的）`Exit_Debug_Mode()` —— 当前版本不会主动重新进入 AI 模式，由用户拿遥控器手动恢复。
6. 仿真模式 `sim_state_subscriber.stop_subscribe()`
7. `recorder.close()` —— 等待异步队列落盘完成

---

## 5. `teleop/robot_control/` 子包

### 5.1 `hand_retargeting.py` (86 行)

把 `dex_retargeting.RetargetingConfig` 的两手配置一次性 build 成两个 `Retargeting` 对象，并算好"retargeting 输出顺序 → 硬件 motor 顺序"的索引映射。

#### 类 `HandType(Enum)`

枚举每种 hand 的 YAML 配置文件相对路径。`*_Unit_Test` 是同名变体，把 `..` 多加一层（用于在 `robot_control/` 子目录里独立跑单元测试）。

#### 类 `HandRetargeting`

`__init__(hand_type)`：
1. 根据 `hand_type` 设置 `RetargetingConfig.set_default_urdf_dir('../assets')`（普通）或 `'../../assets'`（unit test）。
2. `yaml.safe_load(config_path)` → 解析 `cfg`，断言含 `left/right`。
3. `RetargetingConfig.from_dict(cfg['left'/'right']).build()` → `self.left_retargeting / right_retargeting`。
4. 取出 `joint_names`（retargeting 内部期望的关节顺序）和 `optimizer.target_link_human_indices`（DexPilot 需要的人手关键点配对）。
5. 根据 hand_type 各算一个 **`*_dex_retargeting_to_hardware`**：把 retargeting 的关节列表 reorder 到硬件 DDS 期望的顺序：
   - **UNITREE_DEX3**：`left_hand_thumb_{0,1,2}, middle_{0,1}, index_{0,1}` (左手), `right_hand_thumb_{0,1,2}, index_{0,1}, middle_{0,1}` (右手)。注意右手的 index/middle 顺序与左手相反，与 [Dex3 文档](https://support.unitree.com/home/en/G1_developer/dexterous_hand) 的"消息结构排序"一致。
   - **INSPIRE_HAND**：`pinky / ring / middle / index / thumb_proximal_pitch / thumb_proximal_yaw`。
   - **BRAINCO_HAND**：`thumb_metacarpal / thumb_proximal / index_proximal / middle_proximal / ring_proximal / pinky_proximal`。

异常处理：FileNotFoundError、yaml.YAMLError 都打印 warning 并 re-raise。

> **作用** ：所有 `robot_hand_*.py` 控制器都通过 `HandRetargeting(HandType.X)` 拿到 `left_retargeting.retarget(ref_value)[*_dex_retargeting_to_hardware]` 输出的 numpy 数组，直接写到 DDS 的 `motor_cmd[id].q`。

### 5.2 `robot_arm.py` (1178 行)

含 4 个 `*_ArmController` + 4 个 `*_JointArmIndex` IntEnum + 4 个 `*_JointIndex` IntEnum + `MotorState` / `DataBuffer` / 4 个 `*_LowState` 辅助类。

#### 公共数据结构

- `MotorState`：`q, dq` 两个字段（仅 position + velocity，没用 torque）。
- `*_LowState`：固定长度 list of MotorState（G1_29 / G1_23 / H1_2 都是 35；H1 是 20），DDS 收到 lowstate msg 后逐 motor 复制进来。
- `DataBuffer`：单字段 + `threading.Lock` 的简单 thread-safe getter/setter。所有 controller 只用单格 buffer 存最新 lowstate（无队列、无插值）。
- 三个 topic 名常量：
  ```python
  kTopicLowCommand_Debug  = "rt/lowcmd"     # 不开运控时
  kTopicLowCommand_Motion = "rt/arm_sdk"    # 开运控时（与官方 loco 程序解耦的 arm-only 通道）
  kTopicLowState          = "rt/lowstate"
  ```

#### `G1_29_ArmController`

最复杂的一个，其它三个高度相似（只在关节数、IDL 类型、刚度配置、`_Is_*_motor` 集合上有差异）。

**构造函数 (`__init__(motion_mode=False, simulation_mode=False)`)**：

1. 缓存目标值 `q_target = np.zeros(14)`、`tauff_target = np.zeros(14)`（按"双臂 14 关节"维度）。
2. **刚度配置**：
   - `kp_high=300, kd_high=3` — 强电机（腿/腰）
   - `kp_low=80, kd_low=3` — 弱电机（脚踝、肩、肘）
   - `kp_wrist=40, kd_wrist=1.5` — 腕部 3 轴
3. `arm_velocity_limit = 20.0`、`control_dt = 1/250`，速度限幅在 `clip_arm_q_target` 里使用。
4. 根据 `motion_mode` 选 publisher topic：debug 模式发 `rt/lowcmd`、运控模式发 `rt/arm_sdk`。
5. 创建 lowstate subscriber，起一个 daemon `_subscribe_motor_state` 线程：每 2ms 读一次 lowstate，把 35 个 motor 的 q/dq 装进 `G1_29_LowState` 写入 buffer。等 buffer 有数据。
6. **构造 lowcmd 模板** `unitree_hg_msg_dds__LowCmd_()`：
   - `mode_pr = 0`、`mode_machine = lowstate.mode_machine`（透传）
   - 对每个 motor：`mode = 1`（伺服模式）；按"是否双臂"和"是否腕部/弱"分配 kp/kd；q 初值 = 当前 motor q（**关键，避免一启动就突跳**）。
7. 起 daemon publish thread `_ctrl_motor_state`：
   - 运控模式额外把 `kNotUsedJoint0.q = 1.0`（这是 arm_sdk 里的 weight 字段，1.0 表示 arm 完全接管）。
   - 每 4ms 一次：把 `q_target` 经 `clip_arm_q_target` 限速 → 写到 `motor_cmd[id].q`，`dq=0`，`tau=tauff_target[idx]`，重算 CRC32，发布。
   - 若 `_speed_gradual_max==True`，按 `velocity_limit = 20 + 10*min(1, t/5)` 平滑爬升上限到 30。
   - **simulation_mode** 时跳过 `clip_arm_q_target`，直接透传（仿真器不需要限速保护）。

**主要方法**：

| 方法 | 作用 |
| --- | --- |
| `clip_arm_q_target(target_q, vlim)` | 对 14 维 q 一起做速度限幅：`scale = max(|delta|)/(vlim*dt); 输出 = current + delta/max(scale,1.0)` |
| `ctrl_dual_arm(q_target, tauff_target)` | 加锁更新两个 numpy 字段。这是主循环唯一调用的下发接口 |
| `get_current_motor_q()` | 全身 35 motor 的 q（用于录制 body state） |
| `get_current_dual_arm_q()` / `..._dq()` | 14 维双臂 q/dq（IK 输入） |
| `ctrl_dual_arm_go_home()` | 把 `q_target` 设成全 0，每 50ms 检查所有关节绝对值 <0.05；运控模式先把 arm_sdk weight 从 1→0 100 步线性插值（500ms），把控制权交回 loco |
| `speed_gradual_max(t=5.0)` / `speed_instant_max()` | 控制 velocity_limit 渐变 / 立即升满。主循环在按 `r` 之后调用 `speed_gradual_max()` |
| `_Is_weak_motor(idx)` | 判断 idx 是否在弱电机集合（脚踝 + 肩 4 关节 + 肘） |
| `_Is_wrist_motor(idx)` | 判断 idx 是否在腕部 6 关节集合（左右各 roll/pitch/yaw） |
| `get_mode_machine()` | 透传 lowstate.mode_machine 字段 |

**关节索引**：

```
G1_29_JointIndex:  35 entries
  Left/Right Leg:  0–11
  Waist:           12,13,14 (Yaw, Roll, Pitch)
  Left  Arm:       15–21 (Shoulder Pitch/Roll/Yaw, Elbow, Wrist Roll/Pitch/Yaw)
  Right Arm:       22–28
  NotUsedJoint0–5: 29–34   # 29 是 arm_sdk 的 weight 字段
G1_29_JointArmIndex: 仅 14 个 = G1_29_JointIndex[15:29]
```

#### `G1_23_ArmController`

差异：

- 双臂 10 关节（每边 5：肩 3 + 肘 + 腕 roll，无 pitch/yaw）。
- `JointIndex` 里 `kWaistRollNotUsed/PitchNotUsed/kLeftWristPitchNotUsed/...` 等占位字段保持与 G1_29 同 idx 编号（方便共用 lowcmd 模板），但 `JointArmIndex` 只列实际使用的 10 个。
- `_Is_wrist_motor` 只识别 left/right wrist roll。

#### `H1_2_ArmController`

- 双臂 14 关节（与 G1_29 同样 7+7，但顺序是 ShoulderPitch/Roll/Yaw, ElbowPitch, ElbowRoll, WristPitch, WristYaw — 注意 H1_2 用 ElbowRoll 而非 WristRoll）。
- `kp_low=140`（比 G1 大），`kp_wrist=50, kd_wrist=2.0`。
- `_Is_wrist_motor` 含 ElbowRoll/WristPitch/WristYaw 6 个。

#### `H1_ArmController`

- 双臂 8 关节（每边 4：肩 3 + 肘）。
- 用的是 **go IDL**（`unitree_go_msg_dds__LowCmd_`），头标志 `head[0]=0xFE, head[1]=0xEF, level_flag=0xFF`。
- 不支持 motion_mode（H1 没有运控集成 arm_sdk 通道）。
- `JointArmIndex` 故意把 `Left*` 编号大、`Right*` 编号小（DDS 里 H1 顺序就是 right→left），但 enum 顺序 `Left, Left, Left, Left, Right, Right, Right, Right`，**就是为了对外暴露一致的 [L_Pitch, L_Roll, L_Yaw, L_Elbow, R_Pitch, R_Roll, R_Yaw, R_Elbow] = q[0:8]**，与 G1/H1_2 保持一致。
- `mode = 0x01`（弱）或 `0x0A`（强），不是 G1 的 `1`。

#### 文件末尾的 `__main__`

调用 `G1_29_ArmIK(Unit_Test=True, Visualization=False)` + `G1_29_ArmController(simulation_mode=True)`，按预设轨迹（左 SE3 沿 y 轴旋转、右 SE3 沿 z 轴旋转、平移每步 ±1mm）240 步往返，验证 IK + 下发链路连通。

### 5.3 `robot_arm_ik.py` (1251 行)

#### IK 数学描述（4 个类共用）

每个 `*_ArmIK` 都构造了一个 CasADi NLP：

- **变量** `var_q ∈ ℝ^nq`（仅双臂关节，腿/腰/手指被 `buildReducedRobot` 锁定）
- **参数** `param_tf_l, param_tf_r ∈ ℝ^4×4`（左右腕目标 SE3）、`var_q_last`（上一帧解，用于 smooth 项）
- **目标函数**：

  ```
  J = 50 · ‖p_L - tf_L[:3,3]‖² + 50 · ‖p_R - tf_R[:3,3]‖²            (translational, 50× 权重)
    +  α · ‖log3(R_L · tf_L[:3,:3]ᵀ)‖² +  α · ‖log3(R_R · ...)‖²    (rotational, α=1 G1_29/H1_2; 0.5 G1_23/H1)
    + 0.02 · ‖q‖²                                                     (regularization)
    + 0.1 · ‖q - q_last‖²                                            (smoothness)
  ```
- **约束**：`lowerPositionLimit ≤ var_q ≤ upperPositionLimit`（直接来自 URDF）
- **求解器**：IPOPT，`max_iter=30, tol=1e-4, acceptable_tol=5e-4, warm_start_init_point=yes, jacobian_approximation=exact`，30Hz 实时下每帧典型 5-15ms。

每帧调用 `solve_ik(left_wrist, right_wrist, current_q, current_dq)` 流程：

1. `init_data = current_q`（warm start）
2. `set_initial / set_value` 三个参数
3. `try: opti.solve()` → `sol_q = opti.value(var_q)`，过 `WeightedMovingFilter([0.4, 0.3, 0.2, 0.1], 14)` 平滑 → 更新 `init_data`
4. `sol_tauff = pin.rnea(model, data, sol_q, v=0, a=0)` 计算关节重力补偿前馈力矩（`v=0` 是有意为之，避免速度噪声放大）
5. `except`：取 `opti.debug.value(var_q)`（最后一步的中间值），同样过滤+RNEA，返回 `(current_q, zeros)`——保守地维持当前姿态。

**Visualization=True** 时另外起 `MeshcatVisualizer`，画两个 RGB 坐标轴 marker `L_ee_target / R_ee_target`，并实时刷新 robot pose（开浏览器自动弹出 viewer 窗口）。

#### URDF 缓存（v1.5 新增）

每个 IK 类有一个 `cache_path = "<arm>_model_cache.pkl"`：

```python
if os.path.exists(cache_path) and not Visualization:
    self.robot, self.reduced_robot = self.load_cache()
else:
    # BuildFromURDF + buildReducedRobot + addFrame(L_ee/R_ee) ...
    self.save_cache()
```

`save_cache` 只 pickle `robot.model` + `reduced_robot.model`，`load_cache` 重建 `RobotWrapper().model = ...; .data = .model.createData()`。第一次运行会比较慢（Pinocchio 解析 URDF + buildReducedRobot），后续启动从 pkl 加载快几十倍。**Visualization=True 时禁用缓存**，因为 Meshcat 需要 visual_model/collision_model（pkl 不含）。

#### 4 个 ArmIK 的差异

| 类 | URDF | 锁定关节 | end-effector frame | nq | smooth_filter shape | rotation 权重 |
| --- | --- | --- | --- | --- | --- | --- |
| `G1_29_ArmIK` | `g1_body29_hand14.urdf` | 腿12+腰3+手指14 | `L/R_ee` 接在 `*_wrist_yaw_joint`，前推 0.05m | 14 | (14,) | 1.0 |
| `G1_23_ArmIK` | `g1_body23.urdf` | 腿12+腰yaw1 | `L/R_ee` 接在 `*_wrist_roll_joint`，前推 0.20m | 10 | (10,) | 0.5 |
| `H1_2_ArmIK` | `h1_2.urdf` | 腿12+torso+手指24 | `L/R_ee` 接在 `*_wrist_yaw_joint`，前推 0.05m | 14 | (14,) | 1.0；**额外做 scale_arms** |
| `H1_ArmIK` | `h1_with_hand.urdf` | 腿+torso+踝+手指+left/right_hand_joint | `L/R_ee` 接在 `*_elbow_joint`，前推 `0.2605+0.05=0.3105m`（因为 H1 没腕） | 8 | (8,) | 0.5；**额外做 scale_arms** |

#### `scale_arms(human_left, human_right, h_arm=0.60, robot_arm=0.75)`

把人手 SE3 的 translation 部分按 `0.75/0.60=1.25` 放大，让 60cm 人臂触及 75cm 机器人臂的工作空间。**仅 H1_2 / H1 默认开启**（对应代码里 `solve_ik` 顶部那一行被启用），G1_29/G1_23 注释掉了（认为人/G1 臂长接近）。

#### 文件末尾 `__main__`

预设轨迹（与 robot_arm.py 类似），但额外加 `np.random.normal` 噪声测试 IK 鲁棒性，纯 Meshcat 无 DDS。

### 5.4 `robot_hand_unitree.py` (461 行)

实现 **Dex3-1 灵巧手** 和 **Dex1-1 夹爪** 两个独立 controller。

#### `Dex3_1_Controller`

DDS topics：
```
rt/dex3/left/cmd  | rt/dex3/left/state    (HandCmd_/HandState_, hg IDL)
rt/dex3/right/cmd | rt/dex3/right/state
```

**`__init__(left_hand_array_in, right_hand_array_in, dual_hand_data_lock, dual_hand_state_array_out, dual_hand_action_array_out, fps=100, Unit_Test=False, simulation_mode=False)`**:

1. `HandRetargeting(UNITREE_DEX3)`
2. 起 4 个 publisher/subscriber（两手各一对）
3. 创建两个 `multiprocessing.Array('d', 7, lock=True)` 存放从 DDS 读到的 q
4. daemon thread `_subscribe_hand_state`：每 2ms 读 left/right HandState，把 7 个 motor q 写到 shared array
5. **`Process(target=control_process)`** —— 这里用的是**真正独立子进程**（fork，与 main 进程的 array 通过 lock 共享）

**`_RIS_Mode`** 内部类：把 `(id, status, timeout)` 打包成 8-bit motor mode：
```
bit0-3: id (4 bits)
bit4-6: status (3 bits, 0x01 表示伺服)
bit7:   timeout
```

**`control_process(...)`**：子进程独立循环（默认 100Hz）：

1. 初始化两手 cmd msg：每个 motor `kp=1.5, kd=0.2, q=0, dq=0, tau=0`，mode 字节按上面打包。
2. 主循环：
   - 拿锁读 `left_hand_array_in/right_hand_array_in`（25×3）
   - 拼接 state 并准备输出
   - 仅当 `right_hand_data ≠ 全 0 且 left_hand[4] ≠ [-1.13,0.3,0.15]`（televuer 在没有数据时会发 `[-1.13,0.3,0.15]` 哨兵值）才进 retargeting：
     ```python
     ref_value = left_hand_data[indices[1,:]] - left_hand_data[indices[0,:]]   # 6 个相邻向量
     left_q = left_retargeting.retarget(ref_value)[right_dex_retargeting_to_hardware]
     ```
     **Bug-ish**：left/right 都 reorder 用了 `right_dex_retargeting_to_hardware`，但因为 dex3 left/right joint name 互相有差异，这是有意设计还是 typo 不太确定（仓库历史也是这样）。
   - 把 `(state, action)` 写回 `*_array_out`（带锁），并 `ctrl_dual_hand(...)` 把 q 写到 cmd msg 后 publish。
   - sleep 到下一帧。

#### 关节枚举

```
Dex3_1_Left_JointIndex:  Thumb0,1,2 / Middle0,1 / Index0,1   (motor id 0-6)
Dex3_1_Right_JointIndex: Thumb0,1,2 / Index0,1 / Middle0,1   (左右 index/middle 顺序相反)
```

#### `Dex1_1_Gripper_Controller`

DDS topics：
```
rt/dex1/left/cmd | rt/dex1/left/state    (MotorCmds_/MotorStates_, go IDL)
rt/dex1/right/cmd| rt/dex1/right/state
```

**输入**：单 `Value('d')` × 2（左右各一），含义是手柄 trigger 或捏合距离 (cm)。

**关键常量**：

```python
DELTA_GRIPPER_CMD       = 0.18          # 单帧最大变化（5.4 rad → 9 cm，所以 0.6 rad/cm，0.18 rad ≈ 3 mm）
THUMB_INDEX_DISTANCE_MIN = 5.0           # 视为夹爪闭合的指尖距离 (cm)
THUMB_INDEX_DISTANCE_MAX = 7.0           # 视为夹爪全开的指尖距离 (cm)
LEFT_MAPPED_MIN/MAX = 0.0 / 5.40         # 电机角度域
```

**主循环（线程，不是子进程）**：
1. 读 input value
2. `np.interp(input, [5.0, 7.0], [0.0, 5.40])` 把指尖距离/扳机值线性映射到电机目标角
3. **非仿真**模式额外做 `np.clip(target, current ± DELTA_GRIPPER_CMD)` 防过快
4. 可选 `WeightedMovingFilter([0.5, 0.3, 0.2], 2)` 二维平滑
5. `kp=5.0, kd=0.05`，写入 `left/right_gripper_msg.cmds[0].q`，分别发布

**注意**：和 dex3 不同，dex1 用 **threading**（不是 multiprocessing）；filter 与 clip 都是为了实物保护，仿真直接关。

#### 文件末尾 `__main__`

ChannelFactoryInitialize(1) 仿真，初始化 ImageClient + TeleVuerWrapper + 选 ee 控制器，测试 XR → controller 的链路。

### 5.5 `robot_hand_inspire.py` (347 行)

支持因时灵巧手两种通信形式：DFX（unitree 中转）和 FTP（直连官方 SDK）。

#### `Inspire_Controller_DFX`

DDS topics（unitree 自定义中转）：
```
rt/inspire/cmd  (MotorCmds_, go IDL)   ← 一个 topic 装左右共 12 motor
rt/inspire/state (MotorStates_)
```

订阅时按 enum：
```
Inspire_Right_Hand_JointIndex (id 0–5):  Pinky, Ring, Middle, Index, ThumbBend, ThumbRotation
Inspire_Left_Hand_JointIndex  (id 6–11): 同上
```

**`control_process`** 与 dex3 类似，但 retargeting 输出后做归一化：

```python
def normalize(val, min_val, max_val):
    return np.clip((max_val - val) / (max_val - min_val), 0.0, 1.0)
# idx 0~3 (pinky/ring/middle/index): 0~1.7 rad  →  [0=fully closed → wait, official: 1.0=open, 0.0=closed]
# idx 4 (thumb-bend):                0~0.5 rad
# idx 5 (thumb-rotation):           -0.1~1.3 rad
```

注意**反向归一化**：因时官方约定 `[0,1]` 中 `0=closed, 1=open`，所以用 `(max-val)/range`。

#### `Inspire_Controller_FTP` (v1.4 新增)

直接对接因时官方 [inspire_sdkpy](https://github.com/unitreerobotics/inspire_sdkpy)（`from inspire_sdkpy import inspire_dds`）。

DDS topics：
```
rt/inspire_hand/ctrl/l  | rt/inspire_hand/state/l   (inspire_hand_ctrl/inspire_hand_state)
rt/inspire_hand/ctrl/r  | rt/inspire_hand/state/r
```

差异点：
- subscriber 收到 `inspire_hand_state` 后读 `angle_act[i]/1000.0` 归一化到 [0,1]（FTP 用 0-1000 整数表示角度）
- `_send_hand_command(left, right)`：发送 `inspire_hand_ctrl(angle_set=scaled, mode=0b0001)`（mode=1 是角度控制）
- `control_process` 末尾做 `[int(np.clip(val*1000, 0, 1000)) for val in left_q_target]` 把 [0,1] 映射回 [0,1000]
- 等待 dds 时有 5 秒 timeout（DFX 是无限等）

源码末尾用 ASCII 表注明了官方文档里 12-motor 的顺序（**右手在前 0-5，左手在后 6-11**）：

```
| Id   |  0   |  1  |   2    |  3    |    4       |       5        |  6    |  7   |   8    |   9    |   10       |       11       |
| Joint|pinky |ring |middle  |index  | thumb-bend | thumb-rotation |pinky  |ring  |middle  |index   | thumb-bend | thumb-rotation |
|      |               Right Hand                                |              Left Hand                                          |
```

### 5.6 `robot_hand_brainco.py` (189 行)

强脑科技 RevolimbHand。结构与 `Inspire_Controller_DFX` 几乎一致，差别：

- DDS topic（左右独立）：`rt/brainco/left/{cmd,state}` 与 `rt/brainco/right/{cmd,state}`
- 6 motor 顺序（与 brainco.yml 对应）：`thumb / thumb-aux / index / middle / ring / pinky`
- 归一化方向**与 inspire 相反**：

  ```python
  def normalize(val, min_val, max_val):
      return 1.0 - np.clip((max_val - val) / (max_val - min_val), 0.0, 1.0)
  # idx 0:    0~1.52 rad  (thumb metacarpal)
  # idx 1:    0~1.05 rad  (thumb proximal)
  # idx 2~5:  0~1.47 rad  (index/middle/ring/pinky)
  ```
  这里 `0=open, 1=closed`，与 dex3 相同。
- 初始 cmd `q=0.0, dq=1.0`（dq=1 表示速度控制激活）

---

## 6. `teleop/utils/` 子包

### 6.1 `episode_writer.py` (232 行)

**`EpisodeWriter`**：异步、线程化的 episode 落盘器。

#### 数据组织

```
task_dir/{task_name}/
├── episode_0000/
│   ├── colors/000000_color_0.jpg, 000000_color_1.jpg, ...
│   ├── depths/...
│   ├── audios/audio_000000_*.npy
│   └── data.json   = { "info": {...}, "text": {goal, desc, steps}, "data": [ {idx, colors, depths, ...}, ... ] }
├── episode_0001/
└── ...
```

`data.json` 的 `"data"` 是大数组，每帧一个 dict；为了避免占用内存，写入是**流式追加**（手写 JSON 头/尾，每帧 dump 一个对象 + 逗号）。

#### 关键方法

| 方法 | 作用 |
| --- | --- |
| `__init__(task_dir, task_goal, task_desc, task_steps, frequency, image_size=[640,480], rerun_log=True)` | 扫描 task_dir 已有 episode_xxxx 取最大编号，启动 worker thread；rerun_log=True 时同时初始化一个 `RerunLogger(prefix="online/", IdxRangeBoundary=60, memory_limit="300MB")` |
| `data_info(version, date, author)` | 填一个 `info` dict（image/depth/audio 元信息、占位 joint_names、tactile_names、sim_state） |
| `is_ready()` | 返回 `is_available`，主循环用它判断"上一段是否已落盘完毕，可以再开 START/RECORD"（READY 状态机第二个含义） |
| `create_episode()` | episode_id+=1，建 4 个子目录，写 data.json 头部（info+text），新建一个 `online_logger`；置 `is_available=False` |
| `add_item(colors, depths=None, states=None, actions=None, tactiles=None, audios=None, sim_state=None)` | item_id+=1 后把 dict 入队，**主循环不阻塞**（dict 持图像引用，worker 异步保存） |
| `process_queue()` (worker thread) | `Queue.get(timeout=1)` → `_process_item_data` → 若 `need_save & queue 空` → `_save_episode` |
| `_process_item_data(item_data)` | 用 `cv2.imwrite` 写入 colors/depths jpg；audio 用 `np.save` 存 .npy（int16）；把 dict 里的图像 numpy 替换成相对路径 `"colors/000123_color_0.jpg"`；`json.dumps` 追加到 data.json；若 rerun_log 也喂给 RerunLogger |
| `save_episode()` | 设 `need_save=True`（worker 看到队列空时再真正落盘） |
| `_save_episode()` | data.json 末尾写 `\n]\n}` 关 array 与 object，置 `is_available=True` |
| `close()` | `queue.join()` + 等 `is_available` + 停 worker thread |

### 6.2 `ipc.py` (372 行)

ZMQ IPC 服务，让外部 Agent（VLA 模型、调度器等）通过命令字控制遥操程序。

#### `IPC_Server`

绑两个 socket：
- `REP @ ipc://@xr_teleoperate_data.ipc` — 收命令、发回执
- `PUB @ ipc://@xr_teleoperate_hb.ipc` — 10Hz 心跳广播

注意 `ipc://@...` 是 Linux 抽象命名空间（无文件系统残留，v1.5 改的）。

**协议**：

```jsonc
// Client → Server (REQ)
{"reqid": "<uuid>", "cmd": "CMD_START" | "CMD_STOP" | "CMD_RECORD_TOGGLE"}
// Server → Client (REP)
{"repid": "<same uuid>", "status": "ok" | "error", "msg": "ok" | "<reason>"}
// Heartbeat (PUB, 10Hz)
{"START": bool, "STOP": bool, "READY": bool, "RECORD_RUNNING": bool}
```

**核心字段**：

| 字段/方法 | 作用 |
| --- | --- |
| `cmd_map = {"CMD_START":"r", "CMD_STOP":"q", "CMD_RECORD_TOGGLE":"s"}` | 把外部命令翻成键盘 char，转发给 `on_press` callback |
| `_data_loop` | poller 监听 REP，收到 → `_handle_message` → reply。20ms poll 间隔 |
| `_hb_loop` | 调用外部 `get_state()` callback 拿当前 4 字段心跳 dict，PUB 出去 |
| `_handle_message` | 校验 reqid/cmd → 调 `on_press(cmd_map[cmd])` → 返回 ok |
| `start()/stop()` | 起停两个 daemon thread + 关 socket + ctx.term |

主程序 `--ipc` 模式下：`IPC_Server(on_press=on_press, get_state=get_state)`，把模块内的 `on_press`、`get_state` 作为 callback 注入。

#### `IPC_Client`

镜像 server：
- `REQ @ ipc://@xr_teleoperate_data.ipc` 发命令
- `SUB @ ipc://@xr_teleoperate_hb.ipc` 订心跳

**心跳监控**：

```python
self._hb_timeout = 5 * self._hb_interval   # 0.5 秒视为 offline
# 收到 3 次连续心跳后才置 _hb_online=True，避免抖动
# 0.5 秒没收到 → 立即 OFFLINE
```

`send_data(cmd)`：先 `is_online()` 检查，若离线直接返回 error；否则发 REQ 等 1 秒 reply。

文件末尾 `__main__` 是一个 demo client：用 sshkeyboard 监听 `r/s/q/b` 键，分别触发 `CMD_START/CMD_RECORD_TOGGLE/CMD_STOP`、`b` 则打印 `latest_state()`。

### 6.3 `motion_switcher.py` (53 行)

把 `unitree_sdk2py.comm.motion_switcher.MotionSwitcherClient` 和 `unitree_sdk2py.g1.loco.G1LocoClient` 包了两个薄类。

#### `MotionSwitcher`

| 方法 | 作用 |
| --- | --- |
| `__init__()` | `MotionSwitcherClient()` + `SetTimeout(1.0)` + `Init()` |
| `Enter_Debug_Mode()` | 不停 `CheckMode()` → `ReleaseMode()` 直到 `result['name']` 为空。**主程序非 motion 模式下启动时就调用一次**，确保把 ai/locomotion/sport 等内置控制器全停掉，让 `rt/lowcmd` 直接生效 |
| `Exit_Debug_Mode()` | `SelectMode('ai')` 切回 AI 模式 (在主程序的 finally 里被注释掉了，留给用户手动) |

#### `LocoClientWrapper`

| 方法 | 作用 |
| --- | --- |
| `__init__()` | `LocoClient()` + `SetTimeout(0.0001)` + `Init()`（极短 timeout 避免阻塞主循环） |
| `Enter_Damp_Mode()` | `client.Damp()` —— 双摇杆按下软急停 |
| `Move(vx, vy, vyaw)` | `client.Move(vx, vy, vyaw, continous_move=False)` —— 主循环每帧调用 |

### 6.4 `rerun_visualizer.py` (247 行)

#### `RerunLogger(prefix, IdxRangeBoundary=30, memory_limit=None)`

实时折线图可视化，基于 [rerun.io](https://rerun.io)。

`__init__`：
1. `rr.init("Runtime_YYYYmmdd_HHMMSS")`
2. `rr.spawn(memory_limit=, hide_welcome_screen=True)` 启动独立窗口
3. `setup_blueprint()`：建一个 2×2 Grid，每格一个 `TimeSeriesView`，origin 分别是 `online/left_arm`、`online/right_arm`、`online/left_ee`、`online/right_ee`，时间窗口是 cursor 前 60 个 idx 到当前

**`log_item_data(item_data)`**：把一帧 dict 喂进去：
1. `rr.set_time_sequence("idx", item_data['idx'])`
2. 对 `states[part]['qpos']` 每个分量调 `rr.log(f"{prefix}{part}/states/qpos/{i}", rr.Scalar(val))`
3. 同样处理 `actions`
4. 注释掉的 image/depth/tactile/audio log（v1.4 取消了 record image 窗口）

#### `RerunEpisodeReader`

离线工具：从 `task_dir/episode_xxxx/data.json` 把每帧的 colors/depths（cv2 读 + BGR→RGB）/audios 装回 dict list，给 `RerunLogger.log_episode_data()` 离线回放。

#### 文件末尾 `__main__`

下载一个公开 demo `rerun_testdata.zip`（gdown），解压到 `./testdata`，按用户输入 `off` 离线回放 episode_0006，或 `on` 在线模式（30Hz 一帧帧喂）回放 episode_0008。

### 6.5 `sim_state_topic.py` (259 行)

订阅 IsaacLab 仿真器的 `rt/sim_state` JSON 字符串 topic，用 **POSIX 共享内存**给主进程消费。

#### `SharedMemoryManager`

`shm_name="sim_state_cmd_data", size=4096`：
- 内存布局：`[0:4]` timestamp（little-endian uint32）+ `[4:8]` json 长度 + `[8:8+len]` json 字节
- `write_data(dict)`：`json.dumps` → utf-8 → 检查长度（< size-8）→ 加锁写入
- `read_data()`：解析头部，加 `_timestamp` 字段返回
- `cleanup()`：`shm.close()` + `shm.unlink()`（仅 creator 才 unlink）
- 用 `threading.RLock()` 保护读写

#### `SimStateSubscriber`

| 方法 | 作用 |
| --- | --- |
| `__init__(shm_name, shm_size=4096)` | `_setup_shared_memory()` 创建 SharedMemoryManager |
| `start_subscribe()` | `ChannelSubscriber("rt/sim_state", String_).Init()` + 起 daemon `_subscribe_sim_state` thread |
| `_subscribe_sim_state` | 每 2ms `subscriber.Read()` → `json.loads(msg.data)` → `shared_memory.write_data(dict)` |
| `stop_subscribe()` | running=False + join thread + `shared_memory.cleanup()` |
| `read_data()` | 透传到 `shared_memory.read_data()` |

`start_sim_state_subscribe(...)` 是 module-level 工厂函数，主程序仿真模式下用 `sim_state_subscriber = start_sim_state_subscribe()` 一行搞定，主循环中通过 `sim_state_subscriber.read_data()` 取最新仿真状态加进 episode。

### 6.6 `weighted_moving_filter.py` (95 行)

一个非常简单的"滑窗加权均值"滤波器，被 `*_ArmIK` 和 `Dex1_1_Gripper_Controller` 共用。

#### `WeightedMovingFilter(weights, data_size=14)`

| 方法/属性 | 作用 |
| --- | --- |
| `__init__(weights, data_size)` | `assert sum(weights) == 1.0`，初始化 zeros 向量 + 队列 |
| `add_data(new_data)` | 长度断言；如果与上一帧严格相等则跳过（**节省 IPOPT solve 后大概率重复数据时的运算**）；维护长度 ≤ window_size 的 FIFO；调 `_apply_filter` |
| `_apply_filter()` | 队列 < window_size 时直接返回最新；否则对 data_size 个分量分别 `np.convolve(col, weights, mode='valid')[-1]` |
| `filtered_data` | 当前滤波结果 |

`__main__` 用 sin + 高斯噪声生成 35 维数据，可视化对比 3 组不同权重的平滑效果（`(0.7,0.2,0.1)`、`(0.5,0.3,0.2)`、`(0.4,0.3,0.2,0.1)`）。

---

## 7. 三个 git submodule 的角色（当前未本地克隆）

| Submodule | URL | 用途 |
| --- | --- | --- |
| `teleop/televuer/` | <https://github.com/unitreerobotics/televuer> | Vuer 封装：`TeleVuerWrapper(use_hand_tracking, binocular, img_shape, display_mode, zmq, webrtc, webrtc_url)` 提供 `get_tele_data()` 返回结构化 `tele_data`（`left_wrist_pose`/`right_wrist_pose`、`left_hand_pos`/`right_hand_pos`、`left_ctrl_*`/`right_ctrl_*`、`pinchValue`、`triggerValue` 等）；`render_to_xr(img)` 把 BGR 图推到 XR；建 HTTPS+WebSocket 服务于 `https://<host>:8012`，给 XR 浏览器访问 |
| `teleop/robot_control/dex-retargeting/` | <https://github.com/silencht/dex-retargeting> (silencht fork) | dex-retargeting 算法库：`RetargetingConfig.from_dict(yaml).build()` → `Retargeting` 对象，`retarget(ref_value)` 返回各 motor 角度。支持 **DexPilot**（向量目标 + 优化器）和 **Vector**（直接位置匹配）两种类型 |
| `teleop/teleimager/` | <https://github.com/unitreerobotics/teleimager> | 图像服务套件：服务端（PC2）`teleimager-server` + cam_config_server.yaml；客户端 `from teleimager.image_client import ImageClient`，`get_cam_config()` / `get_head_frame()` / `get_left_wrist_frame()` / `get_right_wrist_frame()`。支持 ZMQ 流 + WebRTC（v1.4 起） |

主程序对它们的 import：

```python
from televuer import TeleVuerWrapper
from teleimager.image_client import ImageClient
from dex_retargeting import RetargetingConfig
```

---

## 8. 关键算法 / 数据流深度复盘

### 8.1 端到端帧时序（30 fps，G1_29 + Dex3 + 仿真为例）

```
T=0 ms   主循环醒来
        ┌── 拉 head_img + 推 XR (ZMQ + Vuer)
        ├── 检 RECORD_TOGGLE
        ├── tv_wrapper.get_tele_data()  ← TeleVuer 异步缓冲，~ms
        ├── 写 25×3 hand_pos shared array (Dex3 子进程下一帧消费)
        ├── arm_ctrl.get_current_dual_arm_q/dq()  ← 从 lowstate 后台线程的 buffer
        ├── arm_ik.solve_ik(L,R, q, dq)
        │     ├── opti.set_initial(q)                   # warm start
        │     ├── IPOPT iterations (~5-15ms)
        │     ├── WeightedMovingFilter([.4,.3,.2,.1])
        │     └── pin.rnea(q, v=0, a=0)                 # tauff
        ├── arm_ctrl.ctrl_dual_arm(sol_q, sol_tauff)   # 只更新两个 numpy
        ├── recorder.add_item(...)                      # 入队
        └── sleep 到 33 ms

并行 (后台):
  - arm_ctrl._ctrl_motor_state thread @ 250 Hz: 每 4 ms 限速 + 发 rt/lowcmd
  - arm_ctrl._subscribe_motor_state thread @ 500 Hz: 每 2 ms 收 rt/lowstate 写 buffer
  - Dex3 subscribe thread @ 500 Hz: rt/dex3/{l,r}/state → state_array
  - Dex3 control_process @ 100 Hz (子进程): 读 hand_pos_array + retarget + 发 rt/dex3/{l,r}/cmd
  - EpisodeWriter worker thread: 队列消费 → cv2.imwrite + json append + RerunLogger.log
  - SimStateSubscriber thread @ 500 Hz: rt/sim_state → SharedMemory
```

### 8.2 IK 配方

宇树这套 IK 的核心思想：

1. **降维**：把 G1/H1_2 的 35 个 motor 通过 `buildReducedRobot(jointsToLock=...)` 锁掉 21 个（腿 + 腰 + 手指），只剩 14 个双臂关节作为 IK 的决策变量。
2. **CasADi Symbolic FK**：`cpin.framesForwardKinematics(cmodel, cdata, cq)` 把整套 forward kinematics 编译进 CasADi 计算图。这一步只在 `__init__` 里做一次，后续 `opti.solve()` 直接复用 jacobian。
3. **多目标加权**：50 重平移 + 1 (or 0.5) 重旋转 + 0.02 正则 + 0.1 平滑。50:1 权重比意味着**末端位置精度优先**，姿态略松（适合人类 VR 操作的天然抖动）。
4. **位置约束**：lowerPositionLimit/upperPositionLimit 直接用 URDF 关节限位。
5. **Warm start**：每帧 `set_initial(var_q, current_q)`，加上 IPOPT 的 `warm_start_init_point=yes`，前一次解的对偶变量也复用，30Hz 下首次稳态后每帧迭代次数能压到 5-10 步。
6. **后处理 1**：`WeightedMovingFilter([0.4, 0.3, 0.2, 0.1], 14)` —— 4 帧加权均值，权重前重后轻。这是 IK 之外**第二道平滑保险**（IK 内已经有 smooth_cost 了）。
7. **后处理 2**：`pin.rnea(q, v=0, a=0)` 计算静态重力补偿力矩 `tau`，作为前馈喂到 lowcmd（与 kp/kd 配合，机械臂"飘起"感觉更轻）。
8. **失败回退**：IPOPT 抛异常时返回 `current_q`（原地不动） + `zeros(nv)`，不破坏控制连续性。
9. **缓存**：v1.5 用 pkl 缓存 `model + reduced_model`，避免 buildReducedRobot 慢启动。

### 8.3 手部重定向配方

DexPilot 算法（dex-retargeting 库实现）的输入是**人手关键点之间的相对向量**：

```python
ref_value = hand_data[indices[1,:]] - hand_data[indices[0,:]]   # shape (N, 3)
```

其中 `indices` 来自 YAML 的 `target_link_human_indices_dexpilot`（2×N 矩阵）。例如 Dex3 的 `[[9,14,14,0,0,0],[4,4,9,4,9,14]]` 给出 6 条向量：

| 列 | from(idx_human) | to(idx_human) | 物理意义 |
| --- | --- | --- | --- |
| 0 | 9 (middle base) | 4 (thumb tip) | 拇指→中指根 |
| 1 | 14 (index base) | 4 | 拇指→食指根 |
| 2 | 14 | 9 (middle tip) | 中指→食指根 |
| 3 | 0 (wrist) | 4 | 腕→拇指 |
| 4 | 0 | 9 | 腕→中指 |
| 5 | 0 | 14 | 腕→食指 |

DexPilot 在机器手 URDF 上找对应的 `wrist_link_name + finger_tip_link_names`，最小化 6 条向量的差异 → 输出 7 个 motor 角度 → 经 `dex_retargeting_to_hardware` 索引重排 → 经 normalize → 写 DDS。

人手 25 关键点的索引对照（televuer 提供，与 BunnyVisionPro/OpenTeleVision 一致）：

```
0:  wrist
1-4:  thumb       (1=cmc, 2=mcp, 3=ip, 4=tip)
5-9:  index       (5=cmc, 6=mcp, 7=pip, 8=dip, 9=tip)
10-14: middle
15-19: ring
20-24: pinky
```

### 8.4 仿真 vs 实物的关键路径差异

| 维度 | 仿真 (`--sim`) | 实物 |
| --- | --- | --- |
| DDS domain id | 1 | 0 |
| Arm 速度限幅 | **跳过 clip_arm_q_target** | 启用，velocity_limit 5s 内 20→30 rad/s |
| 重启场景 | save_episode 后 publish `rt/reset_pose/cmd "1"` 自动复位 | 无（需人操作） |
| sim_state | `SimStateSubscriber` 订 `rt/sim_state`，写入 episode | 不订阅 |
| Dex1 gripper | 跳过 `np.clip(±DELTA)` 限速 | 启用 |
| 图像 | IsaacLab 内置图像服务（自动起） | 需 PC2 单独 `teleimager-server` |
| Inspire/Brainco 手部硬件服务 | 不需要 | 需 PC2 跑 `inspire_g1` / `brainco_hand_service` 等 C++ 服务 |
| Motion 模式 | 仿真不支持运控走路 | 走路 + 阻尼急停可用 |

### 8.5 进程/线程拓扑

```
主进程 (teleop_hand_and_arm.py)
├── thread: sshkeyboard.listen_keyboard         (输入)
│   或 IPC_Server { _data_loop, _hb_loop }      (--ipc)
├── ImageClient                                 (内部 ZMQ/WebRTC 线程)
├── TeleVuerWrapper                             (内部 Vuer + websocket 线程池)
├── arm_ctrl 的两个线程: subscribe(2ms), publish(4ms)
├── EpisodeWriter worker thread                 (Queue → cv2.imwrite + json + Rerun)
├── RerunLogger 子进程 (rr.spawn)
├── (--sim) SimStateSubscriber thread
├── 子进程 1: Dex3/Inspire/Brainco control_process  (multiprocessing.Process)
│   └── 内含一个 subscribe 线程
└── (--ee=dex1) Dex1_1 control_thread (在主进程内, 不是子进程)
```

注意 hand controller 是 **multiprocessing.Process** 而 gripper 是 **threading.Thread**——前者 retargeting + IPOPT-like 计算量更重，独立进程绕开 GIL；后者只有简单插值，线程足够。

### 8.6 数据采集 episode 结构示例

```json
{
  "info": {
    "version": "1.0.0", "date": "2026-01-15", "author": "unitree",
    "image": {"width":640,"height":480,"fps":30},
    "depth": {"width":640,"height":480,"fps":30},
    "audio": {"sample_rate":16000,"channels":1,"format":"PCM","bits":16},
    "joint_names": {"left_arm":[],"left_ee":[],"right_arm":[],"right_ee":[],"body":[]},
    "tactile_names": {"left_ee":[],"right_ee":[]},
    "sim_state": ""
  },
  "text": {"goal":"pick up cube.","desc":"task description","steps":"step1...; step2...;"},
  "data": [
    {
      "idx": 0,
      "colors": {"color_0":"colors/000000_color_0.jpg","color_1":"colors/000000_color_1.jpg",
                 "color_2":"colors/000000_color_2.jpg","color_3":"colors/000000_color_3.jpg"},
      "depths": {},
      "states": {
        "left_arm":  {"qpos":[...,7 nums],"qvel":[],"torque":[]},
        "right_arm": {"qpos":[...,7 nums],"qvel":[],"torque":[]},
        "left_ee":   {"qpos":[...,7 nums],"qvel":[],"torque":[]},
        "right_ee":  {"qpos":[...,7 nums],"qvel":[],"torque":[]},
        "body": {"qpos":[]}
      },
      "actions": {
        "left_arm":  {"qpos":[...],"qvel":[],"torque":[]},
        ...
      },
      "tactiles": null,
      "audios": null,
      "sim_state": {"_timestamp":..., ...}      // --sim 时存在
    },
    ...
  ]
}
```

字段命名/嵌套与 [unitree_IL_lerobot](https://github.com/unitreerobotics/unitree_IL_lerobot) 的转换脚本严格对齐。

---

## 9. DDS Topic 速查表

| Topic | 方向 | IDL | 谁发/谁收 | 说明 |
| --- | --- | --- | --- | --- |
| `rt/lowcmd` | host → robot | hg_LowCmd / go_LowCmd | ArmController（debug 模式）/ unitree_sdk2py | 全身关节控制（含腿/腰/双臂） |
| `rt/arm_sdk` | host → robot | hg_LowCmd | ArmController（motion 模式） | 仅手臂控制通道，与官方 loco 解耦；用 `kNotUsedJoint0.q ∈ [0,1]` 作为 weight 切换 |
| `rt/lowstate` | robot → host | hg_LowState / go_LowState | unitree_sdk2py / ArmController | 全身电机状态 q/dq |
| `rt/dex3/left/cmd` `rt/dex3/right/cmd` | host → robot | HandCmd_ (hg) | Dex3_1_Controller | 灵巧手 7 motor 控制 |
| `rt/dex3/left/state` `rt/dex3/right/state` | robot → host | HandState_ (hg) | Dex3_1_Controller | 灵巧手反馈 |
| `rt/dex1/left/cmd` `rt/dex1/right/cmd` | host → robot | MotorCmds_ (go) | Dex1_1_Gripper_Controller | 夹爪 1 motor 控制 |
| `rt/dex1/left/state` `rt/dex1/right/state` | robot → host | MotorStates_ (go) | Dex1_1_Gripper_Controller | 夹爪反馈 |
| `rt/inspire/cmd` `rt/inspire/state` | 双向 | MotorCmds_ / MotorStates_ (go) | Inspire_Controller_DFX | 因时手 DFX 中转协议 |
| `rt/inspire_hand/ctrl/{l,r}` `rt/inspire_hand/state/{l,r}` | 双向 | inspire_dds.* | Inspire_Controller_FTP | 因时手 FTP 直连协议 |
| `rt/brainco/{left,right}/{cmd,state}` | 双向 | MotorCmds_/States_ (go) | Brainco_Controller | 强脑手 |
| `rt/sim_state` | sim → host | String_ (json text) | SimStateSubscriber | IsaacLab 仿真状态 |
| `rt/reset_pose/cmd` | host → sim | String_ (json text) | 主程序 publish_reset_category(1) | 让 IsaacLab 复位场景 |

---

## 10. 启动参数 × 末端执行器组合速查

### 10.1 末端执行器与输入模式可用矩阵

| `--ee` | `hand` 模式 | `controller` 模式 | 说明 |
| --- | --- | --- | --- |
| `dex3` | ✅ 25×3 关键点 → DexPilot → 7 motor q | ❌ 不支持（手柄无法表达 7 自由度） | 灵巧抓握 |
| `dex1` | ✅ 用 `pinchValue` 作开度 | ✅ 用 `triggerValue` 作开度 | 夹爪：手势捏合或扳机控制 |
| `inspire_dfx` | ✅ DFX 中转 | ❌ | 因时手（DFX 通信协议） |
| `inspire_ftp` | ✅ FTP 直连 | ❌ | 因时手（FTP 通信协议） |
| `brainco` | ✅ DexPilot → 6 motor | ❌ | 强脑灵巧手 |

### 10.2 模式开关组合

| 组合 | 含义 |
| --- | --- |
| 默认 (无 `--motion`) | `MotionSwitcher.Enter_Debug_Mode()` 释放内置控制器，机器人原地不动，arm IK 直发 `rt/lowcmd`。XR 操作仅控制手臂+末端 |
| `--motion` + `controller` | `LocoClientWrapper`，arm IK 发 `rt/arm_sdk`；左摇杆 → 平移，右摇杆 → 转向；右手柄 A 退出；双摇杆按下 Damp |
| `--motion` + `hand` | arm IK 发 `rt/arm_sdk`，没有手势走路；用 R3 遥控器人工控制行走 |
| `--sim` | dds domain id=1，启动 sim_state subscribe + reset_pose publish；Arm 速度限幅与 dex1 限速都关 |
| `--ipc` | 用 ZMQ ipc 代替 sshkeyboard；外部 Agent 可发 CMD_START/STOP/RECORD_TOGGLE |
| `--headless` | 不开 RerunLogger 窗口（rerun_log=False） |
| `--affinity` | 主进程绑 CPU [0,1,2,3] + nice -20；子进程绑 [5,6] + nice -20 |
| `--record` | 启 EpisodeWriter；`s` 键开/停录制，episode 自动编号，30Hz 落盘 |

---

## 11. 模块间依赖速查

```
teleop_hand_and_arm.py
├─ unitree_sdk2py.core.channel.ChannelFactoryInitialize / ChannelPublisher
├─ unitree_sdk2py.idl.std_msgs.msg.dds_.String_
├─ televuer.TeleVuerWrapper                         (submodule)
├─ teleop.robot_control.robot_arm.{G1_29,G1_23,H1_2,H1}_ArmController
├─ teleop.robot_control.robot_arm_ik.{G1_29,G1_23,H1_2,H1}_ArmIK
│   └─ teleop.utils.weighted_moving_filter.WeightedMovingFilter
├─ teleop.robot_control.robot_hand_unitree.{Dex3_1_Controller, Dex1_1_Gripper_Controller}
│   ├─ teleop.robot_control.hand_retargeting.HandRetargeting
│   │   └─ dex_retargeting.RetargetingConfig             (submodule)
│   └─ teleop.utils.weighted_moving_filter
├─ teleop.robot_control.robot_hand_inspire.{Inspire_Controller_DFX, Inspire_Controller_FTP}
│   └─ inspire_sdkpy (FTP 用)                          (外部包)
├─ teleop.robot_control.robot_hand_brainco.Brainco_Controller
├─ teleimager.image_client.ImageClient                (submodule)
├─ teleop.utils.episode_writer.EpisodeWriter
│   └─ teleop.utils.rerun_visualizer.RerunLogger
├─ teleop.utils.ipc.IPC_Server
├─ teleop.utils.motion_switcher.{MotionSwitcher, LocoClientWrapper}
├─ teleop.utils.sim_state_topic.start_sim_state_subscribe
└─ sshkeyboard.{listen_keyboard, stop_listening}
```

---

## 12. 调试与扩展指南（实操要点）

1. **启动顺序敏感**：`arm_ik = ArmIK()` 必须在 `arm_ctrl = ArmController()` **之前**实例化，否则启动时机器人会抖一下（v1.3 修复 issue）。这是因为 IK 第一次构建 Pinocchio model 较慢，会让 arm 控制线程的第一次解算延迟。
2. **URDF 缓存陷阱**：修改 `assets/g1/g1_body29_hand14.urdf` 后必须**手动删** `g1_29_model_cache.pkl`，否则改动不生效。
3. **多网卡环境**：用 `--network-interface eth0` 显式指定，否则 cyclonedds 会随机挑一个，可能选错。
4. **Vuer 自签证书**：浏览器进入 `https://192.168.123.2:8012/?ws=wss://192.168.123.2:8012` 需先点 Advanced → Proceed；AVP 必须 AirDrop 装 rootCA.pem 到设备。
5. **WebRTC 头部相机**：v1.4+ 才有，需 `cam_config_server.yaml` 里 `head_camera.enable_webrtc: true`，浏览器 `https://<PC2_IP>:60001` 验通后再启动主程序。
6. **录制保存延迟**：`save_episode()` 是异步的；如果按 `q` 立刻退出可能丢最后几帧。`finally` 里的 `recorder.close()` 会等 queue 完毕。
7. **Inspire 手归一化的 normalize 公式**：`(max-val)/range`（注意是 max 减 val），与 brainco 的 `1 - (max-val)/range` 相反——这是因为两家定义 `0/1` 含义不同。
8. **添加新机器人**：需要 4 处改动：
   - `assets/<robot>/<robot>.urdf` + meshes
   - `robot_arm.py`：新加 `<Robot>_ArmController` + `<Robot>_JointArmIndex` + `<Robot>_JointIndex`
   - `robot_arm_ik.py`：新加 `<Robot>_ArmIK`，复制粘贴一个并调整 `mixed_jointsToLockIDs` + `addFrame` + URDF path
   - `teleop_hand_and_arm.py`：在 `--arm` choices 加上，并补对应 `if args.arm == ...` 分支
9. **添加新末端执行器**：
   - `assets/<hand>/`：URDF（左右独立）+ meshes + YAML（DexPilot 配置）
   - `hand_retargeting.py`：在 `HandType` enum 加路径，`__init__` 里加索引映射
   - 新增 `robot_hand_<name>.py`，模仿 brainco 写一个 Controller
   - `teleop_hand_and_arm.py`：在 `--ee` choices 加上，补 `elif args.ee == ...` 分支

---

## 13. 已知开放问题与未实现

| 项 | 状态 |
| --- | --- |
| `Exit_Debug_Mode()` 在主程序 finally 里被注释掉 | 退出后用户需手动用遥控器切回 AI 模式 |
| `RerunLogger` image/depth/tactile/audio log | 全部注释掉，仅可视化 states/actions 折线 |
| Dex3 retargeting 索引疑似 typo | `left_q_target = ...[right_dex_retargeting_to_hardware]`（应为 left？），但仓库历史长期保持 |
| `display_fps` 注释 TODO | issue #172 提到性能调优，目前没读 camera fps |
| Dex1 gripper 标定 | `LEFT_MAPPED_MIN/MAX` 是硬编码（5.40 rad），需换爪后调 |
| `weak_motors` / `wrist_motors` 集合 | G1_23 的 `_Is_wrist_motor` 只识别 wrist roll，与该型号没有 pitch/yaw 对齐 |
| `audios/tactiles` | EpisodeWriter 接口已留，但主循环不喂数据 |

---

## 14. 一句话总结

**xr_teleoperate 是一个"30Hz 主循环 + 多控制器后台线程/子进程"的实时遥操作框架**：主循环负责 `XR输入 → IK解 → 写共享内存`，后台线程/子进程在 100-250Hz 节拍上把"最新目标"经速度限幅发到 DDS，独立子进程跑 dex-retargeting 把人手 25 个关键点映射成机器手 motor 角度，可选地把所有数据流（图像 + 状态 + 动作 + 仿真 truth）异步落盘成 LeRobot 兼容的 episode。所有可变性（机器人型号 / 末端执行器 / XR 输入模式 / 显示模式 / 仿真实物 / 录制 / IPC / CPU 亲和）通过 CLI 开关组合即可，用户只需"按 r 跟随、按 s 录制、按 q 退出"三个键。
