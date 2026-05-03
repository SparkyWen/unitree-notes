# `unitree_ros2` 仓库完全详解

> 路径：`/home/helios/unitree/unitree-notes/unitree_ros2/`
> 上游：<https://github.com/unitreerobotics/unitree_ros2>
> 许可证：BSD‑3‑Clause（Copyright © 2016‑2024 HangZhou YuShu TECHNOLOGY CO.,LTD. / Unitree Robotics）
> 版本：`0.3.0`（见 `version.txt:1`）

本文档面向需要"彻底吃透 `unitree_ros2`"的开发者，目标是：①给出仓库**全量路径清单**；②把每一个**代码 / 配置 / IDL 文件**实现的功能说清楚；③补一份 ROS 2 ↔ CycloneDDS ↔ Unitree 真机协议的工作机制说明。

文中代码引用一律采用 `path:line_number` 格式，便于在 IDE 中跳转。

---

## 0. 仓库定位与一页式总览

`unitree_ros2` 是 Unitree（宇树）官方提供的 **ROS 2 适配层**，三大职责：

1. **DDS 消息桥接** —— 在 `cyclonedds_ws/src/unitree/` 下定义 3 个 ROS 2 消息包（`unitree_go / unitree_hg / unitree_api`），其 IDL 字段顺序与 Unitree 真机内部 CycloneDDS topic **二进制一致**，因此通过 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` + 共享同一段 `CYCLONEDDS_URI` 配置后，ROS 2 节点可以**直接 subscribe / publish** 真机的 `lowstate / lowcmd / sportmodestate / wirelesscontroller / api/sport/{request,response}` 等 topic，无需中转网关。
2. **跨机型 C++ 示例**（`example/src/`）—— 覆盖 6 款 Unitree 机器人：四足 **Go2 / B2 / B2W**，人形 **H1‑2 / H2 / G1**。示例分三层：
   - **低层**（`*_low_level / *_stand / *_ankle_swing / *_dual_arm`）：500 Hz 周期发布 `LowCmd`，需自己算 CRC。
   - **高层**（`*_sport_client / *_loco_client / *_arm_action / *_arm_sdk_dds / *_robot_state`）：基于 `unitree_api::msg::Request/Response` 做 RPC，参数 / 返回值用 `nlohmann::json` 序列化。
   - **外设**（`g1_dex3 / g1_audio_client / *_motion_switch_client`）：灵巧手、TTS / RGB LED、模式切换。
3. **环境装配脚本**（顶层 `setup*.sh` + `.devcontainer/` + `.github/workflows/`）—— 把 ROS 2 + CycloneDDS RMW + 本仓 workspace 串成一条 source 链，并提供 Foxy / Humble 双版本 dev container 与 CI。

> ⚠️ 本仓**不含**任何 URDF / 仿真世界 / Gazebo 插件 / RL 训练代码。仿真请走 `unitree_ros`（ROS 1）、`unitree_mujoco` 或 `unitree_rl_mjlab`。

文件量：**173 个文件**（不含 `.git`）。其中：
- ROS 2 消息：`.msg` × 43（`unitree_go/msg/*` 24 + `unitree_hg/msg/*` 11 + `unitree_api/msg/*` 8）。
- C++ 示例：`.cpp/.hpp/.h` × ~60。
- vendored 第三方头：`nlohmann/json` 单头库 **45 个文件 / ~1.1 MB**。
- 其余：构建文件、setup 脚本、CI、devcontainer、文档。

**最关键的 5 个踩坑点**：
1. `setup.sh` 把 `CYCLONEDDS_URI` 硬编码到网卡 `enp3s0`（见 `setup.sh:6-8`），多人共用机器或换网卡时必须改。
2. 整套脚本会**全局**改 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`，覆盖 `/opt/ros/<distro>/setup.bash` 的默认 `rmw_fastrtps_cpp`。
3. `record_bag` 在 `example/src/CMakeLists.txt:49,103` 已被注释，源文件在但**默认不编译**。
4. `g1_dual_arm_example` 需要 `yaml-cpp`，`CMakeLists.txt:131` 处用 `if(yaml-cpp_FOUND)` 条件构建，缺少则跳过。
5. `low_level_ctrl` (Go) 与 `low_level_ctrl_hg` (HG) 走的 IDL 不同，**电机数 20 vs 35**，CRC 实现也分两个文件 `motor_crc.cpp / motor_crc_hg.cpp`，互不通用。

---

## 1. 顶层目录一览

| 路径 | 类型 | 作用 |
|---|---|---|
| `.chglog/` | 目录 | `git-chglog` 配置与模板，用于把 conventional commits 自动渲染成 `CHANGELOG.md`。 |
| `.clang-format` | YAML | 4 行，基于 Google 风格（极简）。 |
| `.clang-tidy` | YAML | 117 行，启用 `performance-* / cppcoreguidelines-* / google-* / bugprone-* / modernize-* / clang-analyzer-*`，禁掉指针运算/魔法常数/`do-while` 等若干检查；含命名规则与 SharedPtr 性能豁免。 |
| `.devcontainer/` | 目录 | VSCode Dev Container：双服务（Foxy / Humble），均预装 CycloneDDS RMW + LLVM 18 + zsh。 |
| `.github/workflows/` | 目录 | 三条 GitHub Actions：Foxy 构建、Humble 构建、`version.txt` 改动后自动打 tag + 发 Release。 |
| `.gitignore` | 文本 | 6 行，忽略 `**/build/ **/.vscode/ **/__pycache__/ **/log/ **/install/ .cache`。 |
| `CHANGELOG.md` | Markdown | 103 行，git-chglog 生成。最新 3 个版本：v0.3.0 (2025‑08‑15)、v0.2.0 (2025‑07‑29)、v0.1.0 (2025‑07‑23)。 |
| `LICENSE` | 文本 | BSD‑3‑Clause；版权 HangZhou YuShu TECHNOLOGY CO.,LTD. 2016–2024。 |
| `README.md` | Markdown | 372 行，英文官方文档。 |
| `README _zh.md` | Markdown | 365 行，中文官方文档（注意文件名带空格）。 |
| `cyclonedds_ws/` | 目录 | 一个独立的 colcon workspace，专放 3 个 unitree msg 包；约定与真机 SDK 同名同字段。 |
| `docs/` | 目录 | 文档配图（4 张 PNG，演示 `ros2 topic list` / RViz 视角）。 |
| `example/` | 目录 | 一个独立的 colcon workspace（仅 `src/`），所有 C++ 示例集中于此。 |
| `setup.sh` | Shell | 9 行；source ROS 2 + 本仓 workspace + RMW + **`CYCLONEDDS_URI` 指向网卡 `enp3s0`**。 |
| `setup_default.sh` | Shell | 6 行；同上但**不导出 `CYCLONEDDS_URI`**，让 CycloneDDS 自动挑接口。 |
| `setup_local.sh` | Shell | 11 行；同 `setup.sh`，但 `CYCLONEDDS_URI` 走回环 `lo`，给本机仿真 / 自发自收用。 |
| `version.txt` | 文本 | 1 行，仓库版本号 `0.3.0`，被 `auto-tag.yml` 读取。 |

---

## 2. 完整路径表（穷尽列举）

> 单位约定：URDF/IDL/源码中长度=米、质量=kg、角度=rad、力矩=N·m、电流=mA（除非另注）。

### 2.1 顶层文件

| 路径 | 类型 | 作用 |
|---|---|---|
| `.gitignore` | git | `**/build/`, `**/.vscode/`, `**/__pycache__/`, `**/log/`, `**/install/`, `.cache`。 |
| `.clang-format` | clang | 仅 4 行：`BasedOnStyle: Google`（即 Google 默认 + 100 列宽）。 |
| `.clang-tidy` | clang | 117 行白/黑名单 + `CheckOptions`（`performance-unnecessary-value-param.AllowedTypes` 等），定义命名约定（CamelCase 类、camelBack 变量、ALL_CAPS 宏）。 |
| `LICENSE` | text | BSD‑3‑Clause，版权 2016–2024 HangZhou YuShu TECHNOLOGY。 |
| `README.md` | md | 英文文档。1–5 行 Introduction；40–71 行 Dependencies & Build；80–119 行 Network 与 setup.sh；175–287 行 Usage（state 读取 + 控制下发）。命令样板：先 `source /opt/ros/foxy/setup.bash`，`colcon build --packages-select cyclonedds`（仅 Foxy 需要从源码构建 CycloneDDS）→ source `cyclonedds_ws/install/setup.bash` → `source ~/unitree_ros2/setup.sh` → `cd ~/unitree_ros2/example && colcon build`。 |
| `README _zh.md` | md | 365 行中文版。注意**文件名含空格**，shell 引用必须 quote。 |
| `CHANGELOG.md` | md | git-chglog 渲染：v0.3.0 (CHANGELOG.md:5‑32, 2025‑08‑15)：补全 G1 示例、修 Foxy `topic_statistics_collector` bug；v0.2.0 (CHANGELOG.md:34‑96, 2025‑07‑29)：Go2 `RobotStateClient` & `SportClient` 新 API；v0.1.0 (2025‑07‑23)：初始版本。 |
| `setup.sh` | sh | 9 行。`source /opt/ros/foxy/setup.bash` → `source $HOME/unitree_ros2/cyclonedds_ws/install/setup.bash` → `export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` → `export CYCLONEDDS_URI='<CycloneDDS><Domain><General><Interfaces><NetworkInterface name="enp3s0" priority="default" multicast="default" /></Interfaces></General></Domain></CycloneDDS>'`。**`enp3s0` 是写死的 NIC**，必须按机器改。 |
| `setup_default.sh` | sh | 6 行。仅前三步，**不**导出 `CYCLONEDDS_URI`，让 CycloneDDS 自动挑接口（适合 docker `--net=host` + 单网卡场景）。 |
| `setup_local.sh` | sh | 11 行。等价于 `setup.sh` 但 NIC 改成 `lo`（loopback），用于本机自收自发 / Mujoco 桥接 / unit test。 |
| `version.txt` | text | 单行 `0.3.0`，是 `auto-tag.yml` 触发条件，也是 GitHub Release 名称源。 |

### 2.2 `.chglog/`

| 路径 | 类型 | 作用 |
|---|---|---|
| `.chglog/config.yml` | YAML | git-chglog 配置：`style: github`，commit 类型映射（`feat→Features`、`fix→Bug Fixes`、`chore→Examples`），开启 `notes.keywords: [BREAKING CHANGE]`。 |
| `.chglog/CHANGELOG.tpl.md` | Go template | 63 行 Markdown 模板，渲染版本对比链接（`compare/<prev>...<curr>`）。 |

### 2.3 `.devcontainer/`

| 路径 | 类型 | 作用 |
|---|---|---|
| `.devcontainer/devcontainer.json` | JSON | 29 行；`service: devcontainer-humble`、`workspaceFolder: /workspace`，预装 15 个 VSCode 扩展（clangd, cmake-tools, GitLens, vscode-lldb 等）。 |
| `.devcontainer/docker-compose.yml` | YAML | 55 行，定义 `devcontainer-humble` 与 `devcontainer-foxy` 两服务；都 `privileged: true`、`network_mode: host`，挂 `/workspace`、X11、WSL2 display、`/var/run/docker.sock`、Gazebo models；`postCreateCommand: while sleep 1000; do :; done` 保活。 |
| `.devcontainer/Dockerfile-humble` | Dockerfile | 34 行；基础 `althack/ros2:humble-full`，装 zsh + oh-my-zsh、LLVM 18（`clang-18 / clang-tidy-18 / clangd-18`），`CC=clang-18 CXX=clang-18`、`TZ=Asia/Shanghai`，预装 `ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl`。 |
| `.devcontainer/Dockerfile-foxy` | Dockerfile | 37 行；基础 `althack/ros2:foxy-full`；只装 zsh（LLVM 18 块被注释），换 USTC apt 镜像，预装 `ros-foxy-rmw-cyclonedds-cpp ros-foxy-rosidl-generator-dds-idl`。 |

### 2.4 `.github/workflows/`

| 路径 | 类型 | 作用 |
|---|---|---|
| `.github/workflows/build-foxy.yml` | YAML | 43 行；`on: [push, pull_request] branches: [master]`；容器 `althack/ros2:foxy-full`；步骤：装 deps → clone `rmw_cyclonedds`(foxy) + `cyclonedds`(0.10.x) → build `cyclonedds` 包 → source ROS 2 → build `unitree_go / unitree_hg / unitree_api` → build `unitree_ros2_example`。 |
| `.github/workflows/build-humble.yml` | YAML | 43 行，与 Foxy 同结构；容器 `althack/ros2:humble-full`；`rmw_cyclonedds` 取 `humble` 分支。 |
| `.github/workflows/auto-tag.yml` | YAML | 44 行；`on: push paths: [version.txt]`；读 `version.txt`，`git tag v$VERSION`、push tag，从 `CHANGELOG.md` 提取该版本段，调 `softprops/action-gh-release@v2` 发布 GitHub Release。 |

### 2.5 `docs/`

| 路径 | 类型 | 作用 |
|---|---|---|
| `docs/image/piFtteJ.png` | PNG | `ros2 topic list` 输出截图（README 图示）。 |
| `docs/image/piFtdF1.png` | PNG | RViz 中点云 `frame_id` 信息截图。 |
| `docs/image/piFtsyD.png` | PNG | RViz 可视化效果之一。 |
| `docs/image/piFtyOe.png` | PNG | RViz 可视化效果之二。 |

### 2.6 `cyclonedds_ws/src/unitree/unitree_go/`（四足 Go 系列消息包）

> ROS 2 包名 `unitree_go`，`<build_type>ament_cmake</build_type>`，BSD‑3。`CMakeLists.txt:28-54` 用 `rosidl_generate_interfaces(${PROJECT_NAME} <24 个 .msg> DEPENDENCIES geometry_msgs)` 一次生成；其后 `rosidl_generate_dds_interfaces(... OUTPUT_SUBFOLDERS "dds_connext")`（`CMakeLists.txt:56-60`）额外生成 connext-flavored DDS IDL，让真机的 CycloneDDS publisher 能与 ROS 2 消息共用同一个 wire format。

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_go/package.xml` | XML | maintainer `unitree@unitree.com`；`buildtool_depend: ament_cmake`、`build_depend: rosidl_default_generators`、`exec_depend: rosidl_default_runtime`、依赖 `geometry_msgs`；`<member_of_group>rosidl_interface_packages</member_of_group>`。 |
| `unitree_go/CMakeLists.txt` | CMake | 79 行；`cmake_minimum_required 3.5 / C99 / C++14`；`find_package(ament_cmake / geometry_msgs / rosidl_default_generators / rosidl_generator_dds_idl)`；`rosidl_generate_interfaces(${PROJECT_NAME} ... DEPENDENCIES geometry_msgs)` 列出全部 **24** 个 msg；末尾 `rosidl_generate_dds_interfaces(... OUTPUT_SUBFOLDERS "dds_connext")` 额外吐出 connext IDL；`ament_package()` 收尾。 |
| `unitree_go/msg/MotorCmd.msg` | IDL | 单电机指令：`uint8 mode`（0=休眠/1=关闭/0x0A=PMSM 等）、`float32 q dq tau kp kd`、`uint32[3] reserve`。**与 SDK `unitree_motor_command_t` 二进制一致**。 |
| `unitree_go/msg/MotorState.msg` | IDL | 单电机反馈：`uint8 mode`、`float32 q dq ddq tau_est`、`float32 q_raw dq_raw ddq_raw`、`int8 temperature`、`uint32 lost`、`uint32[2] reserve`。 |
| `unitree_go/msg/MotorCmds.msg` | IDL | `MotorCmd[] cmds` 动态数组容器（用于 dex3 / 任意可变长度场景）。 |
| `unitree_go/msg/MotorStates.msg` | IDL | `MotorState[] states` 动态数组容器。 |
| `unitree_go/msg/IMUState.msg` | IDL | `float32[4] quaternion`(w,x,y,z)、`float32[3] gyroscope rpy`、`float32[3] accelerometer`、`int8 temperature`。 |
| `unitree_go/msg/BmsCmd.msg` | IDL | `uint8 off`（1=断电）、`uint8[3] reserve`。 |
| `unitree_go/msg/BmsState.msg` | IDL | `uint8 version_high/version_low/status/soc`、`int32 current` (mA)、`uint16 cycle`、`int8[2] bq_ntc mcu_ntc`、`uint16[15] cell_vol`（15 串电芯电压 mV）。 |
| `unitree_go/msg/LowCmd.msg` | IDL | 真机底层下行包：`uint8[2] head`、`uint8 level_flag`、`uint8 frame_reserve`、`uint32[2] sn`、`uint32[2] version`、`uint16 bandwidth`、**`MotorCmd[20] motor_cmd`**（4 腿 × 5 槽，仅前 12 实际有用）、`BmsCmd bms_cmd`、`uint8[40] wireless_remote`、`uint8[12] led`、`uint8[2] fan`、`uint8 gpio`、`uint32 reserve`、`uint32 crc`。CRC 由 `motor_crc.cpp:get_crc()` 计算。 |
| `unitree_go/msg/LowState.msg` | IDL | 真机底层上行包：与 LowCmd 同 head/version 等元字段；含 `IMUState imu_state`、`MotorState[20] motor_state`、`BmsState bms_state`、`int16[4] foot_force / foot_force_est`、`uint32 tick`（ms）、`uint8[40] wireless_remote`、`uint8 bit_flag`、`float32 adc_reel`、`int8 temperature_ntc1/ntc2`、`float32 power_v power_a`、`uint16[4] fan_frequency`、`uint32 reserve crc`。 |
| `unitree_go/msg/SportModeCmd.msg` | IDL | 高层运动指令：`uint8 mode gait_type speed_level`、`float32 foot_raise_height body_height`、`float32[2] position`、`float32[3] euler`、`float32[2] velocity`、`float32 yaw_speed`、`BmsCmd bms_cmd`、`PathPoint[30] path_point`。 |
| `unitree_go/msg/SportModeState.msg` | IDL | 高层运动状态：`TimeSpec stamp`、`uint32 error_code`、`IMUState imu_state`、`uint8 mode`、`float32 progress`、`uint8 gait_type`、`float32 foot_raise_height`、`float32[3] position`、`float32 body_height`、`float32[3] velocity`、`float32 yaw_speed`、`float32[4] range_obstacle`（front/left/right/rear）、`int16[4] foot_force`、`float32[12] foot_position_body / foot_speed_body`（4 足 × xyz）。 |
| `unitree_go/msg/PathPoint.msg` | IDL | 轨迹点：`float32 t_from_start x y yaw vx vy vyaw`。`SportModeCmd.path_point` 与 `ros2_b2_sport_client::TrajectoryFollow` 用。 |
| `unitree_go/msg/TimeSpec.msg` | IDL | `int32 sec`、`uint32 nanosec`（与 `builtin_interfaces/Time` 字段相同）。 |
| `unitree_go/msg/HeightMap.msg` | IDL | `float64 stamp`、`string frame_id`、`float32 resolution`、`uint32 width height`、`float32[2] origin`、`float32[] data`（行优先 X-major）。Go2 雷达高度图。 |
| `unitree_go/msg/LidarState.msg` | IDL | LiDAR 健康统计：`float64 stamp`、`string firmware_version software_version sdk_version`、`float32 sys_rotation_speed com_rotation_speed`、`uint8 error_state`、`float32 cloud_frequency cloud_packet_loss_rate`、`uint32 cloud_size cloud_scan_num`、`float32 imu_frequency imu_packet_loss_rate`、`float32[3] imu_rpy`、`float64 serial_recv_stamp`、`uint32 serial_buffer_size serial_buffer_read`。 |
| `unitree_go/msg/UwbState.msg` | IDL | UWB 定位 tag↔base 状态：`uint8[2] version`、`uint8 channel joy_mode`、`float32 orientation_est pitch_est distance_est yaw_est`、`float32 tag_roll/pitch/yaw`、`float32 base_roll/pitch/yaw`、`float32[2] joystick`、`uint8 error_state buttons enabled_from_app`。 |
| `unitree_go/msg/UwbSwitch.msg` | IDL | `uint8 enabled`（0/1）。 |
| `unitree_go/msg/WirelessController.msg` | IDL | 手柄输入：`float32 lx ly rx ry`、`uint16 keys`（16 bit 位掩码，bit 含义见 `gamepad.hpp`）。 |
| `unitree_go/msg/Go2FrontVideoData.msg` | IDL | Go2 前置摄像头多分辨率压缩流：`uint64 time_frame`、`uint8[] video720p`、`uint8[] video360p`、`uint8[] video180p`。 |
| `unitree_go/msg/AudioData.msg` | IDL | 麦克风/扬声器原始流：`uint64 time_frame`、`uint8[] data`。 |
| `unitree_go/msg/Error.msg` | IDL | `uint32 source`、`uint32 state`。错误码上报。 |
| `unitree_go/msg/InterfaceConfig.msg` | IDL | `uint8 mode value`、`uint8[2] reserve`。GPIO/通信接口配置。 |
| `unitree_go/msg/Req.msg` | IDL | 通用 RPC 请求：`string uuid body`。少量旧服务用，新服务统一走 `unitree_api/Request`。 |
| `unitree_go/msg/Res.msg` | IDL | 通用 RPC 响应：`string uuid`、`uint8[] data`、`string body`。 |

### 2.7 `cyclonedds_ws/src/unitree/unitree_hg/`（人形 H1/H1‑2/H2/G1 消息包）

> 与 `unitree_go` 同结构（同 `package.xml` 元数据、同 `rosidl_generate_interfaces` 模式），但每条消息按人形需求扩字段。**最关键的差异：电机数 35（vs Go 的 20）**，`LowCmd / LowState` 多了 `mode_pr / mode_machine` 头字段。

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_hg/package.xml` | XML | 同 `unitree_go/package.xml` 模板。 |
| `unitree_hg/CMakeLists.txt` | CMake | 同 `unitree_go/CMakeLists.txt` 模板（68 行），`rosidl_generate_interfaces` 列 **11** 个 msg，`DEPENDENCIES geometry_msgs`，同样调 `rosidl_generate_dds_interfaces` 生成 dds_connext 子目录。 |
| `unitree_hg/msg/MotorCmd.msg` | IDL | 同 `unitree_go::MotorCmd`，但 `reserve` 是单 `uint32`（go 是 `uint32[3]`）。 |
| `unitree_hg/msg/MotorState.msg` | IDL | `uint8 mode`、`float32 q dq ddq tau_est`、`int16[2] temperature`（双温度传感器）、`float32 vol`、`uint32[2] sensor`、`uint32 motorstate`、`uint32[4] reserve`。 |
| `unitree_hg/msg/IMUState.msg` | IDL | 同 `unitree_go::IMUState` 但 `temperature` 用 `int16`（go 用 `int8`）。 |
| `unitree_hg/msg/BmsCmd.msg` | IDL | `uint8 cmd`、`uint8[40] reserve`（人形电池协议头更长）。 |
| `unitree_hg/msg/BmsState.msg` | IDL | `uint8 version_high/version_low/fn`、`uint16[40] cell_vol`（40 串电芯）、`uint32[3] bmsvoltage`、`int32 current`、`uint8 soc soh`、`int16[12] temperature`、`uint16 cycle manufacturer_date`、`uint32[5] bmsstate`、`uint32[3] reserve`。 |
| `unitree_hg/msg/LowCmd.msg` | IDL | **人形底层下行包**：`uint8 mode_pr`（PR=0 / AB=1，脚踝并联模式选择）、`uint8 mode_machine`（机器机型代号，由真机回传后照搬）、`MotorCmd[35] motor_cmd`、`uint32[4] reserve`、`uint32 crc`。CRC 由 `motor_crc_hg.cpp:get_crc()` 计算。 |
| `unitree_hg/msg/LowState.msg` | IDL | **人形底层上行包**：`uint32[2] version`、`uint8 mode_pr mode_machine`、`uint32 tick`、`IMUState imu_state`、`MotorState[35] motor_state`、`uint8[40] wireless_remote`、`uint32[4] reserve`、`uint32 crc`。 |
| `unitree_hg/msg/HandCmd.msg` | IDL | 灵巧手下行：`MotorCmd[] motor_cmd`（动态长度，Dex3 单手 7 关节）、`uint32[4] reserve`。 |
| `unitree_hg/msg/HandState.msg` | IDL | 灵巧手上行：`MotorState[] motor_state`、`PressSensorState[] press_sensor_state`、`IMUState imu_state`、`float32 power_v power_a system_v device_v`、`uint32[2] error reserve`。 |
| `unitree_hg/msg/MainBoardState.msg` | IDL | 主控板综合状态（用作 H2 secondary IMU + 中央总线诊断）：`MotorState[] motor_state`、`PressSensorState[] press_sensor_state`、`IMUState imu_state`、`float32 power_v/a system_v device_v`、`uint32[2] error reserve`。 |
| `unitree_hg/msg/PressSensorState.msg` | IDL | 12 路压力传感（足底/手指）：`float32[12] pressure temperature`、`uint32 lost reserve`。 |

### 2.8 `cyclonedds_ws/src/unitree/unitree_api/`（通用请求‑响应协议）

> 这是 Unitree "高层服务" 的统一传输承载：`SportClient / LocoClient / MotionSwitchClient / RobotStateClient / ArmActionClient / AudioClient / Dex3Client` 全部把请求打包到 `unitree_api::msg::Request`，把返回拆出 `unitree_api::msg::Response`。**topic 命名约定**：`/api/<service>/request` + `/api/<service>/response`，其中 `<service>` ∈ {`sport, motion_switcher, robot_state, arm, voice`} 等。

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_api/package.xml` | XML | 同 unitree_go/hg 模板。 |
| `unitree_api/CMakeLists.txt` | CMake | 同模板（65 行），`rosidl_generate_interfaces` 列 **8** 个 msg，`DEPENDENCIES geometry_msgs`，同样有 `rosidl_generate_dds_interfaces`。 |
| `unitree_api/msg/RequestIdentity.msg` | IDL | `int64 id`（请求端 ID，惯例填 `time_tools::GetSystemUptimeInNanoseconds()` 用于响应回匹）、`int64 api_id`（业务码）。 |
| `unitree_api/msg/RequestLease.msg` | IDL | `int64 id`，会话/租约。 |
| `unitree_api/msg/RequestPolicy.msg` | IDL | `int32 priority`、`bool noreply`（true=单向指令，不等响应）。 |
| `unitree_api/msg/RequestHeader.msg` | IDL | 聚合：`RequestIdentity identity`、`RequestLease lease`、`RequestPolicy policy`。 |
| `unitree_api/msg/Request.msg` | IDL | 顶层请求：`RequestHeader header`、`string parameter`（JSON）、`uint8[] binary`（二进制大对象，如音频 PCM）。 |
| `unitree_api/msg/ResponseStatus.msg` | IDL | `int32 code`（0=成功，负值=错误码，定义在 `ut_errror.hpp`）。 |
| `unitree_api/msg/ResponseHeader.msg` | IDL | 聚合：`RequestIdentity identity`（回传请求方 id 用于匹配）、`ResponseStatus status`。 |
| `unitree_api/msg/Response.msg` | IDL | 顶层响应：`ResponseHeader header`、`string data`（JSON）、`int8[] binary`（二进制大对象）。 |

### 2.9 `example/src/`（C++ 示例 colcon 包）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/package.xml` | XML | 25 行；包名 `unitree_ros2_example`、`build_type=ament_cmake`；`buildtool_depend: ament_cmake`；`depend: unitree_go unitree_hg unitree_api rclcpp std_msgs rosbag2_cpp`；`test_depend: ament_lint_auto ament_lint_common`。 |
| `example/src/CMakeLists.txt` | CMake | 183 行。`cmake_minimum_required(VERSION 3.5)`；`set(CMAKE_C_STANDARD 99) / CMAKE_CXX_STANDARD 14`；`find_package(ament_cmake unitree_go unitree_hg unitree_api rclcpp std_msgs rosbag2_cpp Eigen3)`；`find_package(yaml-cpp QUIET)`；`include_directories(include include/common include/nlohmann)`、`link_directories(src)`；定义 `DEPENDENCY_LIST=rclcpp std_msgs unitree_go unitree_hg unitree_api rosbag2_cpp` 复用宏。 |

#### 2.9.1 `CMakeLists.txt` 中所有 `add_executable` 的对照表

> 所有目标统一通过 `ament_target_dependencies(<target> ${DEPENDENCY_LIST})` 链接 ROS 2 依赖；`g1_dual_arm_example` 还额外链 `yaml-cpp`。

| 二进制名 | 源文件 | 共编源 | 行号 |
|---|---|---|---|
| `low_level_ctrl` | `src/low_level_ctrl.cpp` | `src/common/motor_crc.cpp` | `CMakeLists.txt:42` |
| `low_level_ctrl_hg` | `src/h1-2/lowlevel/low_level_ctrl_hg.cpp` | `src/common/motor_crc_hg.cpp` | `:43` |
| `g1_low_level_example` | `src/g1/lowlevel/g1_low_level_example.cpp` | `src/common/motor_crc_hg.cpp` | `:44` |
| `read_low_state` | `src/read_low_state.cpp` | — | `:45` |
| `read_low_state_hg` | `src/read_low_state_hg.cpp` | — | `:46` |
| `read_motion_state` | `src/read_motion_state.cpp` | — | `:47` |
| `read_wireless_controller` | `src/read_wireless_controller.cpp` | — | `:48` |
| ~~`record_bag`~~ | `src/record_bag.cpp` | — | `:49` **（注释，默认不编译）** |
| `go2_sport_client` | `src/go2/go2_sport_client.cpp` | `src/common/ros2_sport_client.cpp` | `:50` |
| `go2_stand_example` | `src/go2/go2_stand_example.cpp` | `src/common/motor_crc.cpp` | `:53` |
| `go2_robot_state_client` | `src/go2/go2_robot_state_client.cpp` | `src/common/motor_crc.cpp` | `:56` |
| `g1_arm_sdk_dds_example` | `src/g1/high_level/g1_arm_sdk_dds_example.cpp` | `src/common/motor_crc.cpp` | `:59` |
| `g1_arm_action_example` | `src/g1/high_level/g1_arm_action_example.cpp` | `src/common/motor_crc.cpp` | `:62` |
| `g1_dex3_example` | `src/g1/dex3/g1_dex3_example.cpp` | `src/common/motor_crc.cpp` | `:65` |
| `g1_loco_client_example` | `src/g1/high_level/loco_client_example.cpp` | `src/common/motor_crc.cpp` | `:68` |
| `g1_ankle_swing_example` | `src/g1/lowlevel/g1_ankle_swing_example.cpp` | `src/common/motor_crc_hg.cpp` | `:71` |
| `g1_audio_client_example` | `src/g1/audio_client/g1_audio_client_example.cpp` | — | `:74` |
| `b2w_sport_client` | `src/b2w/b2w_sport_client.cpp` | `src/common/ros2_b2_sport_client.cpp` | `:77` |
| `b2w_stand_example` | `src/b2w/b2w_stand_example.cpp` | `src/common/motor_crc.cpp` | `:80` |
| `b2_stand_example` | `src/b2/b2_stand_example.cpp` | `src/common/motor_crc.cpp` | `:83` |
| `b2_sport_client` | `src/b2/b2_sport_client.cpp` | `src/common/ros2_b2_sport_client.cpp` | `:86` |
| `h2_loco_client` | `src/h2/high_level/h2_loco_client.cpp` | — | `:89` |
| `h2_ankle_swing_example` | `src/h2/low_level/h2_ankle_swing_example.cpp` | `src/common/motor_crc_hg.cpp` | `:92` |
| `g1_dual_arm_example` | `src/g1/lowlevel/g1_dual_arm_example.cpp` | `src/common/motor_crc_hg.cpp` | `:131`（`if(yaml-cpp_FOUND)` 包裹） |

`install(TARGETS …)` 块从 `CMakeLists.txt:139` 开始，把以上所有目标安装到 `lib/${PROJECT_NAME}/`，给 `ros2 run unitree_ros2_example <name>` 使用。

### 2.10 `example/src/src/` 根级示例

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/read_low_state.cpp` | C++ | 124 行。Go 系列 `LowState` 监听 demo。订阅 `lowstate`（`HIGH_FREQ=true`）或 `hf/lowstate`（`HIGH_FREQ=false`），QoS=10。回调里按编译期常量 `INFO_IMU / INFO_MOTOR / INFO_FOOT_FORCE / INFO_BATTERY` 决定打印 IMU 四元数/RPY、12 电机 q/dq/ddq/tau_est、4 足力（实测+估计）、电池 V/A。`main()` 走 `rclcpp::spin()` 阻塞。 |
| `example/src/src/read_low_state_hg.cpp` | C++ | 89 行。HG 系列 `LowState` 监听 demo。订阅 `lowstate`/`lf/lowstate`（注意 HG 的 HIGH_FREQ 走 `lowstate`，与 Go 默认走 `hf/lowstate` 相反）。打印 IMU + **35 个**电机 q/dq/ddq/tau_est。无足力/电池信息。 |
| `example/src/src/read_motion_state.cpp` | C++ | 93 行。Go 系列 `SportModeState` 监听 demo。订阅 `sportmodestate` 或 `lf/sportmodestate`。回调里打印 mode/gait_type/foot_raise_height、`(x,y,z) body_height`、`(vx,vy,vz) yaw_speed`、4 足在 body frame 下的 12 维位置/速度。 |
| `example/src/src/read_wireless_controller.cpp` | C++ | 43 行。订阅硬编码 topic `/wirelesscontroller`（`unitree_go::msg::WirelessController`），打印 `lx/ly/rx/ry/keys`。 |
| `example/src/src/record_bag.cpp` | C++ | 108 行。把 `sportmodestate` 录到 rosbag2，存储后端 `sqlite3`（`record_bag.cpp:27`），bag 名 `timed_synthetic_bag`，topic 名注册成 `"a"`。回调里 `rclcpp::Serialization` 序列化 → `rosbag2_storage::SerializedBagMessage`。**注：`CMakeLists.txt:49,103` 已注释，默认不编译。** |
| `example/src/src/low_level_ctrl.cpp` | C++ | 86 行。Go 系列 `LowCmd` 下发 demo（无订阅）。`init_cmd()` 把 20 个电机预置 `mode=0x01`（PMSM 力矩模式），`q=PosStopF, dq=VosStopF, kp=kd=tau=0`；timer 周期 5 ms（200 Hz）→ `RL_2` 设力矩 `tau=1 N·m`，`RL_0` 设位置 `q=0, kp=10, kd=1`；调 `get_crc(cmd_msg_)` 后 publish 到硬编码 topic `/lowcmd`。 |

### 2.11 `example/src/src/common/`（共享实现源）

> 这块连同 `example/src/include/common/` 是整套示例的"运行时框架"。CRC 计算 / Sport API 字典 / 通用 RPC 模板都在这里。

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/common/motor_crc.cpp` | C++ | 61 行。`get_crc(unitree_go::msg::LowCmd&)` 把 ROS 消息按 SDK 内存布局重打成 `LowCmd` POD（含 head / levelFlag / sn / version / 20×MotorCmd / BmsCmd / wireless_remote / led / fan / gpio / reserve），然后调 `crc32_core(ptr, (sizeof(LowCmd)>>2)-1)` 算到倒数第二个 uint32。`crc32_core` 用多项式 `0x04C11DB7`、初值 `0xFFFFFFFF`、按 32 bit 字逐 bit MSB-first 处理（IEEE‑802.3 CRC32）（`motor_crc.cpp:41-60`）。 |
| `example/src/src/common/motor_crc_hg.cpp` | C++ | 46 行。`get_crc(unitree_hg::msg::LowCmd&)` 按 HG POD 布局：`mode_pr + mode_machine + 35×MotorCmd + uint32[4] reserve + uint32 crc`，**多项式相同 (`0x04C11DB7`)**，但电机数 / 头字段 / 整体长度都不同，与 Go 版互不通用（`motor_crc_hg.cpp:9`）。 |
| `example/src/src/common/ros2_sport_client.cpp` | C++ | 247 行。`SportClient` 类实现：构造时建 `Publisher<unitree_api::msg::Request>("/api/sport/request")`、临时 `Subscription<unitree_api::msg::Response>("/api/sport/response")`。每个公开方法（`Damp/BalanceStand/StopMove/StandUp/StandDown/RecoveryStand/Euler/Move/Sit/RiseSit/SpeedLevel/Hello/Stretch/Content/Dance1/Dance2/SwitchJoystick/Pose/Scrape/FrontFlip/FrontJump/FrontPounce/Heart/StaticWalk/TrotRun/EconomicGait/LeftFlip/BackFlip/HandStand/FreeWalk/FreeBound/FreeJump/FreeAvoid/ClassicWalk/WalkUpright/CrossStep/AutoRecoverySet/AutoRecoveryGet/SwitchAvoidMode`，共 38 个）填 `req.header.identity.api_id` 与 `req.parameter`（JSON），调 `Call()` 模板（`ros2_sport_client.cpp:76-95` 同步 promise/future）等响应。完整 api_id 对照表见 §3.2。 |
| `example/src/src/common/ros2_b2_sport_client.cpp` | C++ | 170 行。`B2SportClient`：B2 工业四足专用 API，去掉了 Sit/RiseSit/翻滚/舞蹈，新增了 `SwitchGait / BodyHeight / TrajectoryFollow / ContinuousGait / MoveToPos / SwitchMoveMode / HandStand / VisionWalk / FastWalk` 等。`TrajectoryFollow` 会把 30 个 `PathPoint{t_from_start,x,y,yaw,vx,vy,vyaw}` 序列化进 JSON 数组（`ros2_b2_sport_client.cpp:72-88`）。 |

### 2.12 `example/src/include/common/`（共享头文件）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/include/common/motor_crc.h` | C++ 头 | 77 行。常量：`HIGHLEVEL=0xee, LOWLEVEL=0xff, TRIGERLEVEL=0xf0, PosStopF=2.146e9, VosStopF=16000.0`；关节索引枚举 `FR_0/1/2…RL_0/1/2`（共 12）；POD 结构体 `BmsCmd / MotorCmd{mode,q,dq,tau,Kp,Kd,reserve[3]} / LowCmd{...20×MotorCmd...crc}`；声明 `get_crc / crc32_core`。 |
| `example/src/include/common/motor_crc_hg.h` | C++ 头 | 36 行。HG POD 布局 `LowCmd{modePr, modeMachine, motorCmd[35], reserve[4], crc}`、`MotorCmd{mode,q,dq,tau,Kp,Kd,reserve}`，声明 `get_crc / crc32_core`。 |
| `example/src/include/common/ros2_sport_client.h` | C++ 头 | 335 行。`SportClient` 类成员（`req_puber_`、`Node*`）+ `Call<Request,Response>` 模板（创建一次性订阅、按 api_id 匹配响应、阻塞 future、销毁订阅）+ 全部 38 个 API 的方法签名。请求 topic `/api/sport/request`、响应 topic `/api/sport/response`。 |
| `example/src/include/common/ros2_b2_sport_client.h` | C++ 头 | 205 行。`B2SportClient` 类（同上模式）+ `struct PathPoint` + 20+ B2 专用方法签名。 |
| `example/src/include/common/ros2_robot_state_client.h` | C++ 头 | 146 行。仅头实现的 `RobotStateClient`：API_ID `1001/1002/1003`（ServiceSwitch / SetReportFreq / ServiceList）。`ServiceList(vector<ServiceState>&)`、`ServiceSwitch(name, swit, &status)`、`SetReportFreq(interval, duration)`。topic 走 `/api/robot_state/{request,response}`。 |
| `example/src/include/common/base_client.hpp` | C++ 头 | 72 行。`BaseClient` 模板：构造取 `node + topic_request + topic_response`；`Call(Request, json&)` **创建一次性 Subscription** + future.wait_for(5 s)，超时返回 `UT_ROBOT_TASK_TIMEOUT`，异常 `UT_ROBOT_TASK_UNKNOWN_ERROR`，正常解析 `response.data` JSON 返回 `UT_ROBOT_SUCCESS`。每次 `Call` 都用 `time_tools::GetSystemUptimeInNanoseconds()` 填 `identity.id` 用作回匹键。 |
| `example/src/include/common/b2_base_client.hpp` | C++ 头 | 163 行。`B2BaseClient`：与 `BaseClient` 同接口，但内部使用**持久订阅 + `MultiThreadedExecutor` + `condition_variable` + `atomic current_request_id_` + `call_mutex_`**，吞吐更高、并发安全，`InitRosComm()` 还会自旋等待连接（最多 10 × 50 ms）。 |
| `example/src/include/common/time_tools.hpp` | C++ 头 | 59 行 inline 工具函数（命名空间 `unitree::common`）：`GetSystemUptimeInNanoseconds`（CLOCK_MONOTONIC，给 RPC 请求 ID 用）、`GetCurrentTimeSeconds/Milliseconds/Microseconds`、`GetCurrentTimeStr(fmt)`、`GetDuration*` 时间差。 |
| `example/src/include/common/patch.hpp` | C++ 头 | 20 行。**Foxy 兼容补丁**：模板特化 `TimeStamp<unitree_api::msg::Response>::value` 返回 `{true, 0}`，绕过 `libstatistics_collector` 对自定义消息缺失 timestamp accessor 导致的编译错误。 |
| `example/src/include/common/ut_errror.hpp` | C++ 头 | 16 行（**注意文件名拼写：少一个 `r`，是 `errror`**）。宏 `UT_DECL_ERR(name, code, desc)` 同时定义 `const int32_t name = code` 和 `const constexpr char* name##_DESC = desc`；常量 `UT_ROBOT_SUCCESS=0`、`UT_ROBOT_TASK_TIMEOUT=-1`、`UT_ROBOT_TASK_UNKNOWN_ERROR=-2`；调试宏 `UT_PRINT_ERR(code, error)`。 |

### 2.13 `example/src/src/go2/` + `include/`（Go2 四足 12 DoF）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/go2/go2_stand_example.cpp` | C++ | 198 行。LowLevel 站立 demo。Sub `/lowstate`、Pub `/lowcmd`（`unitree_go::msg`）。Timer 2 ms（500 Hz）触发 `LowCmdWrite()`：`motiontime>=500`（1 s 等订阅就绪）后采当前 q 到 `start_pos_[12]`，分 4 段插值：①0–500 ms 展腿 `[0,1.36,−2.65]×4`；②500–1000 ms 收腿到站立 `[0,0.67,−1.3]×4`；③1000–2000 ms 维持；④2000–2900 ms 外八站姿 `[±0.35,1.36,−2.65]×4`（hip 翻 ±0.5）。**Kp=60, Kd=5**（`go2_stand_example.cpp:30-31`），下发前调 `get_crc(low_cmd_)`（`:184`）。 |
| `example/src/src/go2/go2_sport_client.cpp` | C++ | 164 行。Sport 高层 demo。`./go2_sport_client <test_mode>`，`test_mode∈[0..10]`：0 StandUp、1 BalanceStand、2 Move(0.3,0,0.3)、3 StandDown、4 StandUp、5 Damp、6 RecoveryStand、7 Sit（仅一次）、8 RiseSit、9 Move(0.3,0,0)、10 StopMove。Sub `lf/sportmodestate` 用 `MultiThreadedExecutor` spin。 |
| `example/src/src/go2/go2_robot_state_client.cpp` | C++ | 75 行。`go2_robot_state_client` demo：后台线程 `RobotControl()`：① `SetReportFreq(type=3, freq=30)`；② sleep 5 s；③ `ServiceSwitch("sport_mode", off, status)`；④ sleep 5 s；⑤ `ServiceSwitch("sport_mode", on, status)`；⑥ `ServiceList(vec)` 打印所有 service 名 / 状态 / 保护位。 |

### 2.14 `example/src/src/b2/` + `include/b2/`（B2 工业四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/b2/b2_stand_example.cpp` | C++ | 271 行。B2 LowLevel 站立 demo。构造时 `MotionSwitchClient msc_` → `Init()/Start()`，进入 `while(queryMotionStatus())` 循环（`b2_stand_example.cpp:87-96`）：若 motion service 在跑就 `ReleaseMode()` 后 sleep 5 s 重试，直到 `CheckMode()` 返回空名才继续。500 Hz 定时器，5 段插值（800/800/2000/1500/500 ms）：展腿→收腿→维持（同时控制 `motor[12-16]` 的"臂"做正/反/停的 `dq=±3` 摆动）→外八。**Kp=1000, Kd=10**（`b2_stand_example.cpp:34-35`，注意比 Go2 高一个数量级）。 |
| `example/src/src/b2/b2_sport_client.cpp` | C++ | 189 行。后台线程 50 Hz 读 stdin（`./b2_sport_client` 进入交互 REPL，`list` 列动作、输 id 或名）。支持 `Damp/BalanceStand/StopMove/StandDown/RecoveryStand/Move(0.3,0,0)/SwitchGait(0)/SpeedLevel(1)/HandStand(true)/AutoRecoverySet(true)/FreeWalk/ClassicWalk(true)/FastWalk(true)/Euler(0,0,0.6)`。 |
| `example/src/include/b2/b2_motion_switch_client.hpp` | C++ 头 | 86 行（`namespace unitree::robot::b2`）。API_ID 常量：`CHECK_MODE=1001 / SELECT_MODE=1002 / RELEASE_MODE=1003 / SET_SILENT=1004 / GET_SILENT=1005`。方法：`CheckMode(form, name)` 返回当前 motion 服务 form/name；`SelectMode(name)` JSON `{"name":...}`；`ReleaseMode()` 释放当前控制；`SetSilent(bool)/GetSilent(bool&)`。底层走 `BaseClient` + `/api/motion_switcher/{request,response}`。 |

### 2.15 `example/src/src/b2w/`（B2W 带轮版四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/b2w/b2w_stand_example.cpp` | C++ | 268 行。结构与 `b2_stand_example.cpp` 极似，但**没有** `ReleaseMode` while 循环（`while` 块在 `b2w_stand_example.cpp:73-97` 整段被注释）；4 段插值替代 B2 的 5 段；`target_pos_3` 的 hip 张角更大（±0.65），针对带轮形态。**Kp=1000, Kd=10**（`b2w_stand_example.cpp:34-35`）。 |
| `example/src/src/b2w/b2w_sport_client.cpp` | C++ | 189 行。同 `b2_sport_client` 框架；动作集：`Damp/StandUp(默认)/StandDown/Move(0.3,0,0)/Move(0,0.3,0)/Move(0,0,0.5)/StopMove/SwitchGait(0)/SwitchGait(1)/RecoveryStand`。 |

### 2.16 `example/src/src/h1-2/lowlevel/`（H1‑2 人形）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/h1-2/lowlevel/low_level_ctrl_hg.cpp` | C++ | 248 行。H1‑2 LowLevel 控制 demo（`H1_2_NUM_MOTOR=27`）。Sub `lowstate`/`lf/lowstate` (`unitree_hg::msg::LowState`)、Pub `/lowcmd`。500 Hz timer。①前 3 s 平滑归零；②3 s 后开 `mode_pr=PR`，左右脚踝按 `0.25*sin/cos(2π*t)` 周期摆动 (Pitch±0.25 rad / Roll±0.25 rad)，腕部同样规律摆动。Kp 数组前 13 关节（腿+腰）= 100、后 14（臂）= 50；Kd 全 1.0；tau 全 0；ankle 摆动段单独覆盖 `Kp_Pitch=Kp_Roll=80, Kd=1`。`mode_machine` 从 LowState 收到后原样回写到 LowCmd（`:94, :169`）。每周期调 `get_crc(low_command_)`（`:164`）。关节布局：`[0–5]` 左腿 hip yaw/pitch/roll + knee + ankle pitch/roll，`[6–11]` 右腿同结构，`[12]` 腰 yaw，`[13–19]` 左臂（肩×3 + 肘 + 腕×3），`[20–26]` 右臂同左。 |

### 2.17 `example/src/src/h2/` + `include/h2/`（H2 人形）

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/h2/low_level/h2_ankle_swing_example.cpp` | C++ | 245 行。H2 LowLevel 脚踝摆动 demo。Sub `rt/lowstate`、Pub `rt/lowcmd`（注意前缀 `rt/`，与 Go/HG 默认不同，是 H2 真机 partition）。500 Hz timer，3 段：①0–3 s 归零；②3–6 s **PR 模式**摆 ankle pitch ±π/6、roll ±π/6（频率 1 Hz, `sin(2π*t)`）；③6 s 后切 **AB 模式**摆 A=±π/6, B=±π/30（A 频率 0.5 Hz `sin(π*t)`、B 相位差 π）。Kp 数组：腿 200, 膝 200/Kd=2，臂 50/Kd=1。关节索引 4/5/10/11 = LeftAnklePitch/LeftAnkleRoll/RightAnklePitch/RightAnkleRoll。无需手柄，自动执行。 |
| `example/src/src/h2/low_level/gamepad.hpp` | C++ 头 | 130 行。`xKeySwitchUnion` 16 bit 位图（bit0 R1, bit1 L1, bit2 start, bit3 select, bit4 R2, bit5 L2, bit6 F1, bit7 F2, bit8 A, bit9 B, bit10 X, bit11 Y, bit12 up, bit13 right, bit14 down, bit15 left）；`xRockerBtnDataStruct` (40 B) 含模拟轴 lx/ly/rx/ry/L2 + 16 个按钮；`Button` 类有 `pressed/on_press/on_release` 三态；`Gamepad::update()` 用 0.01 死区 + 0.03 平滑系数处理摇杆。把 `unitree_hg::msg::WirelessController` 的 `keys` 字段位掩码解开。 |
| `example/src/src/h2/high_level/h2_loco_client.cpp` | C++ | 206 行。交互式 CLI demo：`0 damp / 1 start / 2 stand_up / 3 zero_torque / 4 stop_move / 5 get_fsm_id / 6 get_fsm_mode / 7 set_fsm_id / 8 set_velocity / 9 move / 10 switch_move_mode / 11 set_speed_mode`。每个分支调用 `LocoClient` 同名方法。 |
| `example/src/include/h2/h2_loco_client.hpp` | C++ 头 | 260 行。`LocoClient` 主类，封装 H2 高层运动接口。**API_ID 字典**（GET 7001–7008，SET 7101–7109）：`GetFsmId(7001) / GetFsmMode(7002) / GetBalanceMode(7003) / GetSwingHeight(7004) / GetStandHeight(7005) / GetPhase(7006) / GetArmSdkStatus(7007) / GetAvailableFsmIds(7008) / SetFsmId(7101) / SetBalanceMode(7102) / SetSwingHeight(7103) / SetStandHeight(7104) / SetVelocity(vx,vy,ω,duration=1.0; 7105) / SetTaskId(7106) / SetSpeedMode(7107) / SetPunchApi(7108) / SetArmSdkStatus(7109)`。便利方法（FSM ID 直接映射）：`Damp=SetFsmId(1) / Start=SetFsmId(500) / Squat=SetFsmId(2) / Sit=SetFsmId(3) / StandUp=SetFsmId(4) / ZeroTorque=SetFsmId(0) / StopMove=SetVelocity(0,0,0) / HighStand=SetStandHeight(uint_max) / LowStand=SetStandHeight(uint_min) / Move(vx,vy,ω,[continuous]) / BalanceStand=SetBalanceMode(0) / ContinuousGait(flag)→SetBalanceMode(flag?1:0) / SwitchMoveMode(flag) / WaveHand(turn?)=SetTaskId(turn?1:0) / ShakeHand(stage)=SetTaskId(stage?3:2) / EnableArmSDK / DisableArmSDK`。topic `/api/sport/{request,response}`。 |
| `example/src/include/h2/h2_motion_switch_client.hpp` | C++ 头 | 87 行。H2 模式切换客户端，API_ID 与 b2 / g1 同（`CHECK_MODE=1001/SELECT_MODE=1002/RELEASE_MODE=1003/SET_SILENT=1004/GET_SILENT=1005`），方法 `CheckMode/SelectMode/ReleaseMode/SetSilent/GetSilent`。 |

### 2.18 `example/src/src/g1/` + `include/g1/`（G1 人形 29 DoF — 文档重头戏）

#### 2.18.1 G1 公共定义

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/include/g1/g1.hpp` | C++ 头 | 105 行。两套关节枚举：①`G1Arm5JointIndex`（5DoF 臂）：左腿 0–5(hip pitch/roll/yaw, knee, ankle pitch/roll)、右腿 6–11、腰 yaw=12 / roll=13 / pitch=14、左臂 shoulder pitch/roll/yaw=15/16/17 + elbow pitch/roll=18/19、右臂 22/23/24 + 25/26、含 `kNotUsedJoint=29`（用于 weight 通道）。②`G1Arm7JointIndex`（7DoF 臂）：左臂在 elbow 后多 wrist roll/pitch/yaw（18 elbow → 19 wrist roll → 20 wrist pitch → 21 wrist yaw），右臂同（25/26/27/28）。常量 `PI_2=1.57079632`。 |
| `example/src/src/g1/lowlevel/gamepad.hpp` | C++ 头 | 127 行。与 `h2/low_level/gamepad.hpp` 几乎一致；区别仅命名空间与极小细节。 |

#### 2.18.2 G1 LowLevel 示例

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/g1/lowlevel/g1_low_level_example.cpp` | C++ | 257 行。500 Hz LowLevel demo。Sub `lowstate`/`lf/lowstate`、Pub `/lowcmd`。①0–3 s 平滑归零；②3 s+ 开 `mode_pr=PR`，左右脚踝 `0.25·cos(2π*t)/0.25·sin(2π*t)`（相位相反），腕 roll `0.5·sin(2π*t)`（±0.5 rad）。Kp/Kd 二元分组（`g1_low_level_example.cpp:101-102`）：`i<13`（腿+腰，"弱组"）Kp=100/Kd=1，`i>=13`（臂+腕，"强组"）Kp=50/Kd=1。每周期 `get_crc(low_command_)`（`:172`）。 |
| `example/src/src/g1/lowlevel/g1_ankle_swing_example.cpp` | C++ | 389 行。脚踝并联机构演示。Sub `lowstate`(10 Hz)+`secondary_imu`（torso IMU）、Pub `lowcmd` 500 Hz。三段：①0–3 s 归零；②3–6 s **PR 模式**：`max_P=π·30°/180°≈0.524`、`max_R=π·10°/180°≈0.175`，左右 `L_P=max_P·sin(2π*t), L_R=max_R·sin(2π*t)`；③6 s+ **AB 模式**（脚踝并联 A/B 解耦）：`L_A=+max_A·sin(π*t), L_B=+max_B·sin(π*t+π)`，右镜像。Kp 表（`:60-75`）：腿 60/60/60/100/40/40，腰 60/40/40，臂全 40，Kd 全 1（膝 2）。带 gamepad 输入解析（`:256-287`）。 |
| `example/src/src/g1/lowlevel/g1_dual_arm_example.cpp` | C++ | 411 行。双臂离线轨迹回放。**条件编译**：仅在 `find_package(yaml-cpp)` 找到时编译（`CMakeLists.txt:131`）。Sub `/lowstate`、Pub `/arm_sdk`（注意 topic 不是 `/lowcmd`，是 ArmSDK 专用通道）。①0–3 s 平滑插值到初始姿（左臂 P=0,R=π/2,Y=0,肘=π/2,腕 roll=0；右臂 R=−π/2，其余同）；②3 s+ 从 YAML behavior library 加载关键帧逐帧线性插值（仅控制 `i>=15` 的臂关节）。Kp 按 `MotorType{S,M,L}` 分（`:123-144`）：S/M=40，L=100；Kd 全 1。 |

#### 2.18.3 G1 HighLevel 示例

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/g1/high_level/loco_client_example.cpp` | C++ | 462 行。CLI 大全：GET（`get_fsm_id/get_fsm_mode/get_balance_mode/get_swing_height/get_stand_height/get_phase`）、SET（`set_fsm_id/set_balance_mode/set_swing_height/set_stand_height/set_velocity vx vy ω [dur]/set_task_id/set_speed_mode`）、便利动作（`damp(1)/start(500)/squat(2)/sit(3)/stand_up(4)/zero_torque(0)/stop_move/high_stand/low_stand/balance_stand/continous_gait <bool>/switch_move_mode <bool>/move vx vy ω/shake_hand/wave_hand [with_turn]`）。Loco 错误码：`UT_ROBOT_LOCO_ERR_LOCOSTATE_NOT_AVAILABLE=7301 / INVALID_FSM_ID=7302 / INVALID_TASK_ID=7303`（`:25-39`）。 |
| `example/src/src/g1/high_level/g1_arm_action_example.cpp` | C++ | 114 行。CLI：输 `0` 调 `GetActionList(data)` 打印动作字典；输其它整数调 `ExecuteAction(id)` 执行。错误码：`UT_ROBOT_ARM_ACTION_ERR_ARMSDK=7400 / HOLDING=7401 / INVALID_ACTION_ID=7402 / INVALID_FSM_ID=7404`（注：仅在 FSM∈{500,501,801} 有效，且 801 状态下 fsm_mode 仅能 0 或 3）。 |
| `example/src/src/g1/high_level/g1_arm_sdk_dds_example.cpp` | C++ | 243 行。低层 ArmSDK DDS demo（`#define ARM_TYPE G1ARM5` 或 `G1ARM7` 切 13 / 17 关节）。50 Hz 控制（`control_dt=0.02`）。Sub `/lowstate`、Pub `/arm_sdk`。流程：等首包 → smooth 插值到 init pose (3 s) → 抬双臂 (5 s, 限速 0.5 rad/s) → 落臂 (5 s) → 回 init (3 s) → weight 2 s 内从 1.0→0.0 释放。**关键概念**：`motor_cmd[kNotUsedJoint=29].q = weight`，weight∈[0,1] 决定 ArmSDK 接管真机臂的比重；weight=0 完全交还机器人主控。Kp=60, Kd=1.5。 |

#### 2.18.4 G1 灵巧手 / 音频 / 模式切换

| 路径 | 类型 | 作用 |
|---|---|---|
| `example/src/src/g1/dex3/g1_dex3_example.cpp` | C++ | 366 行。Dex3 七关节欠驱动手 demo。Pub `/dex3/{left,right}/cmd` (`unitree_hg::msg::HandCmd`)、Sub `/lf/dex3/{left,right}/state`。状态机 `INIT→ROTATE/GRIP/STOP/PRINT`，键盘 `r/g/s/p/h/q` 切换。关节限位（`:23-28`）：左手 max=[1.05, 1.05, 1.75, 0, 0, 0, 0]、min=[−1.05, −0.724, 0, −1.57, −1.75, −1.57, −1.75]；右手镜像。控制参数：ROTATE Kp=0.5/Kd=0.1（`:199-200`）；GRIP Kp=1.5/Kd=0.1（`:240-241`）；STOP Kp=Kd=0 + `mode` timeout=1。 |
| `example/src/src/g1/audio_client/g1_audio_client_example.cpp` | C++ | 282 行。`AudioClient` 集成 demo：①`TtsMaker("你好。我是宇树科技的机器人G1。例程启动成功", speaker_id=0)`；②`GetVolume / SetVolume(100)`；③解析本地 `test.wav`（内置 44 B `WaveHeader` 验证：RIFF magic `0x46464952`、WAVE format `0x45564157`、仅支持 16/18 字节 fmt chunk + 16-bit PCM 单声道 16 kHz），调 `PlayStream(app_name, stream_id, pcm_data)` 播放、`PlayStop` 停止；④`LedControl(R,G,B)` 设 RGB LED。 |
| `example/src/src/g1/audio_client/test.wav` | binary | 16 kHz / 16-bit / 单声道 WAV，给上面 demo 做播放素材。 |
| `example/src/include/g1/g1_audio_client.hpp` | C++ 头 | 97 行。`AudioClient : public rclcpp::Node`。API_ID：`TTS=1001 / ASR=1002（预留） / START_PLAY=1003 / STOP_PLAY=1004 / GET_VOLUME=1005 / SET_VOLUME=1006 / SET_RGB_LED=1010`。方法：`TtsMaker(text, speaker_id)`（参数 `{"index":uint32, "text":str, "speaker_id":int32}`）、`GetVolume(uint8&)`、`SetVolume(uint8)`、`PlayStream(app_name, stream_id, pcm_bytes)`（PCM 走 `Request.binary`）、`PlayStop(app_name)`、`LedControl(R,G,B)` 各 0–255。topic `/api/voice/{request,response}`。 |
| `example/src/include/g1/g1_arm_action_client.hpp` | C++ 头 | 82 行。`G1ArmActionClient`。`ExecuteAction(int32_t action_id)` API_ID=7106，发 `{"data":id}`；`GetActionList(string& data)` API_ID=7107，返回 JSON 字典字符串。topic `/api/arm/{request,response}`。 |
| `example/src/include/g1/g1_loco_client.hpp` | C++ 头 | 257 行。`LocoClient`。低层 GET（7001–7006）/ SET（7101–7107）API 与 H2 一致；`SetVelocity(vx,vy,ω,duration=1.0)`，连续运动 trick：`SwitchMoveMode(true)` 后 `Move()` 内部用 `duration=864000.0` (24 h)。便利方法集合与 H2 同；多了 `WaveHand(turn_flag=false)` (TaskId 0/1) 与 `ShakeHand(stage)` (TaskId 2/3)。topic `/api/sport/{request,response}`。 |
| `example/src/include/g1/g1_motion_switch_client.hpp` | C++ 头 | 86 行。同 b2/h2 的 `MotionSwitchClient`。API_ID `1001–1005`。`CheckMode` 返回 `{"form":"0|1", "name":string}`（form 0=双足, 1=轮式；name=`normal/ai/advanced/wheeled_sport` 等）；`SelectMode(name)`、`ReleaseMode()`、`SetSilent(bool)`、`GetSilent(bool&)`。topic `/api/motion_switcher/{request,response}`。 |

### 2.19 `example/src/include/nlohmann/`（vendored 第三方 JSON 单头库 v3.11.2，45 文件）

> 本目录是 `nlohmann/json` 项目 [v3.11.2 源代码](https://github.com/nlohmann/json) 的 vendored 切片版本（即把官方单头 `json.hpp` 拆回了实现树形态）。所有 `*_client.hpp`、`ros2_sport_client.cpp` 用 `nlohmann::json` 序列化 RPC 参数与解析响应。本仓不修改任何文件。

| 路径 | 作用（一句话） |
|---|---|
| `nlohmann/json.hpp` | 主入口头，include 所有内部模块组装出 `basic_json/json/ordered_json` 类型。 |
| `nlohmann/json_fwd.hpp` | `basic_json` 与相关类型的前置声明，给只需类型名的场景用。 |
| `nlohmann/adl_serializer.hpp` | ADL 序列化器模板，承载 `from_json/to_json` 的非侵入扩展。 |
| `nlohmann/byte_container_with_subtype.hpp` | 带 subtype 标签的字节容器，支持 BSON binary / MessagePack ext 等。 |
| `nlohmann/ordered_map.hpp` | 保插入序的 map 实现，给 `ordered_json` 用。 |
| `nlohmann/detail/abi_macros.hpp` | ABI 命名空间宏 + 版本号（`NLOHMANN_JSON_VERSION_{MAJOR,MINOR,PATCH} = 3,11,2`）+ 诊断推送/弹出。 |
| `nlohmann/detail/exceptions.hpp` | `parse_error / invalid_iterator / type_error / out_of_range / other_error` 5 种异常类。 |
| `nlohmann/detail/hash.hpp` | `std::hash<basic_json>` 内部实现（按值类型逐字段 combine）。 |
| `nlohmann/detail/macro_scope.hpp` | 库内部宏定义入口（编译器/平台检测、`NLOHMANN_DEFINE_TYPE_*` 等）。 |
| `nlohmann/detail/macro_unscope.hpp` | 在头末尾把上述内部宏 `#undef` 清理，避免污染调用方。 |
| `nlohmann/detail/conversions/from_json.hpp` | `from_json` 默认实现：JSON value → C++ 标准/算术/容器类型。 |
| `nlohmann/detail/conversions/to_json.hpp` | `to_json` 默认实现：C++ 标准/算术/容器类型 → JSON value。 |
| `nlohmann/detail/conversions/to_chars.hpp` | 浮点 → 最短 round-trip 字符串（Grisu2 算法实现）。 |
| `nlohmann/detail/input/binary_reader.hpp` | CBOR / MessagePack / UBJSON / BSON / BJData 二进制反序列化。 |
| `nlohmann/detail/input/input_adapters.hpp` | 输入适配器抽象（迭代器、流、`FILE*`、`span`、容器…）。 |
| `nlohmann/detail/input/json_sax.hpp` | SAX 风格解析回调接口 (`null/boolean/number_*/string/start_*/key/end_*/parse_error`)。 |
| `nlohmann/detail/input/lexer.hpp` | JSON 词法分析（token 化）。 |
| `nlohmann/detail/input/parser.hpp` | DOM 解析器，把 lexer token 流堆栈式建成 `basic_json`。 |
| `nlohmann/detail/input/position_t.hpp` | 解析定位结构（行/列/字节偏移），给 `parse_error` 报位置用。 |
| `nlohmann/detail/iterators/iter_impl.hpp` | 双向迭代器实现，统一 object/array/primitive 三种内核。 |
| `nlohmann/detail/iterators/iteration_proxy.hpp` | `items()` 范围 for 代理，提供 `.key() .value()`。 |
| `nlohmann/detail/iterators/iterator_traits.hpp` | 迭代器 trait 萃取（区分原生指针 / std iterator / json iterator）。 |
| `nlohmann/detail/iterators/internal_iterator.hpp` | 联合体形式的内部迭代器存储（object / array / primitive）。 |
| `nlohmann/detail/iterators/json_reverse_iterator.hpp` | 反向迭代器适配器。 |
| `nlohmann/detail/iterators/primitive_iterator.hpp` | 原始值（number/string/null/bool）的伪迭代器（位置 -1/0/+1）。 |
| `nlohmann/detail/json_custom_base_class.hpp` | 允许用户给 `basic_json` 注入自定义基类的钩子。 |
| `nlohmann/detail/json_pointer.hpp` | RFC 6901 JSON Pointer 实现（`/foo/0/bar` 路径定位）。 |
| `nlohmann/detail/json_ref.hpp` | `json_ref` 包装器，实现初始化列表延迟构造与移动。 |
| `nlohmann/detail/meta/call_std/begin.hpp` | 检测 ADL `std::begin` 是否可调用的 trait。 |
| `nlohmann/detail/meta/call_std/end.hpp` | 检测 ADL `std::end` 是否可调用的 trait。 |
| `nlohmann/detail/meta/cpp_future.hpp` | C++14/17/20 标准库特性的本地 polyfill（`void_t/conjunction/...`）。 |
| `nlohmann/detail/meta/detected.hpp` | "experimental detected idiom" 类型检测元函数。 |
| `nlohmann/detail/meta/identity_tag.hpp` | identity_tag 标签分发（避免推导陷阱）。 |
| `nlohmann/detail/meta/is_sax.hpp` | SAX 接口完备性检测 trait。 |
| `nlohmann/detail/meta/std_fs.hpp` | `<filesystem>` 适配（`std::filesystem` vs `std::experimental::filesystem`）。 |
| `nlohmann/detail/meta/type_traits.hpp` | 库内最大的元编程文件，定义 `is_basic_json / is_compatible_*` 等大量 trait。 |
| `nlohmann/detail/meta/void_t.hpp` | `void_t<...>` 的本地实现。 |
| `nlohmann/detail/output/binary_writer.hpp` | CBOR / MessagePack / UBJSON / BSON / BJData 二进制序列化。 |
| `nlohmann/detail/output/output_adapters.hpp` | 输出适配器抽象（流、`FILE*`、容器、`string`…）。 |
| `nlohmann/detail/output/serializer.hpp` | DOM → JSON 字符串序列化（pretty / compact / 浮点格式）。 |
| `nlohmann/detail/string_concat.hpp` | 高效字符串拼接（无中间 `std::string` 构造）。 |
| `nlohmann/detail/string_escape.hpp` | JSON 字符串转义、UTF‑8 替换字符处理。 |
| `nlohmann/detail/value_t.hpp` | `enum class value_t { null, object, array, string, boolean, number_integer/_unsigned/_float, binary, discarded }`。 |
| `nlohmann/thirdparty/hedley/hedley.hpp` | Hedley 跨编译器属性宏（`HEDLEY_LIKELY / NEVER_INLINE / DEPRECATED…`）。 |
| `nlohmann/thirdparty/hedley/hedley_undef.hpp` | Hedley 宏的清理 `#undef`，避免污染下游。 |

---

## 3. 按机器人型号交叉索引

### 3.1 各机型示例 / 协议矩阵

| 机器人 | 关节 | DDS msg 包 | LowCmd `mode` 关键值 | LowLevel demo | HighLevel demo | 外设/特殊 demo | gamepad 文件 |
|---|---|---|---|---|---|---|---|
| **Go2** | 12 | `unitree_go` | `0x01` PMSM、`0x00` BRAKE | — *(直接用通用 `low_level_ctrl`)* | `go2_sport_client` (11 模式) | `go2_robot_state_client`（service 列表/开关/上报频率） | — |
| **B2** | 12 + 4 臂槽 | `unitree_go` | 同上 | `b2_stand_example` (Kp=1000/Kd=10, 5 段插值，含臂摆动) | `b2_sport_client`（13 动作 REPL，含 `HandStand/FreeWalk/ClassicWalk/Euler/AutoRecoverySet`） | `b2_motion_switch_client`（仅头） | — |
| **B2W** | 12 + 4 轮 | `unitree_go` | 同上 | `b2w_stand_example` (Kp=1000/Kd=10, 4 段) | `b2w_sport_client`（10 动作，含横向 `Move(0,0.3,0)`） | — | — |
| **H1‑2** | 27 | `unitree_hg` | `mode_pr=PR/AB`、每电机 `mode=0x01 / 0x0A` | `low_level_ctrl_hg` (Kp 100/50, 500 Hz, ankle PR + 腕摆动) | — | — | — |
| **H2** | 27 (同 H1‑2 关节布局) | `unitree_hg` | `mode_pr=PR/AB` | `h2_ankle_swing_example` (PR/AB 双段) | `h2_loco_client`（FSM ID + Velocity） | `h2_motion_switch_client` | `h2/low_level/gamepad.hpp` |
| **G1** | 29（含 3 腰、6 腿、3 臂 ×2，可选 4 腕 ×2） | `unitree_hg` + `arm_sdk` topic + `dex3/*` topic + `voice` API | `mode_pr=PR/AB`（脚踝并联）、`mode` per‑motor、`weight∈[0,1]`（ArmSDK 接管比重） | `g1_low_level_example`（500 Hz）、`g1_ankle_swing_example`（PR+AB 切换）、`g1_dual_arm_example`（YAML 关键帧回放） | `loco_client_example`（最完整 CLI）、`g1_arm_action_example`（动作库）、`g1_arm_sdk_dds_example`（50 Hz arm_sdk + weight 释放） | `g1_dex3_example`（灵巧手 7 DoF）、`g1_audio_client_example`（TTS/PCM/RGB LED） | `g1/lowlevel/gamepad.hpp` |

### 3.2 高层 API ID 字典（Sport / Loco / Arm Action / Audio / MotionSwitcher / RobotState）

#### Sport（Go 系列，topic `/api/sport/{request,response}`）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 1001 | `Damp` | `{}` |
| 1002 | `BalanceStand` | `{}` |
| 1003 | `StopMove` | `{}` |
| 1004 | `StandUp` | `{}` |
| 1005 | `StandDown` | `{}` |
| 1006 | `RecoveryStand` | `{}` |
| 1007 | `Euler` | `{"x":roll, "y":pitch, "z":yaw}` |
| 1008 | `Move` | `{"x":vx, "y":vy, "z":vyaw}` |
| 1009 | `Sit` | `{}` |
| 1010 | `RiseSit` | `{}` |
| 1015 | `SpeedLevel` | `{"data":level}` |
| 1016 | `Hello` | `{}` |
| 1017 | `Stretch` | `{}` |
| 1020 | `Content` | `{}` |
| 1022 | `Dance1` | `{}` |
| 1023 | `Dance2` | `{}` |
| 1027 | `SwitchJoystick` | `{"data":flag}` |
| 1028 | `Pose` | `{"data":flag}` |
| 1029 | `Scrape` | `{}` |
| 1030 | `FrontFlip` | `{}` |
| 1031 | `FrontJump` | `{}` |
| 1032 | `FrontPounce` | `{}` |
| 1036 | `Heart` | `{}` |
| 1061 | `StaticWalk` | `{}` |
| 1062 | `TrotRun` | `{}` |
| 1063 | `EconomicGait` | `{}` |
| 2041 | `LeftFlip` | `{}` |
| 2043 | `BackFlip` | `{}` |
| 2044 | `HandStand` | `{"data":flag}` |
| 2045 | `FreeWalk` | `{}` |
| 2046 | `FreeBound` | `{"data":flag}` |
| 2047 | `FreeJump` | `{"data":flag}` |
| 2048 | `FreeAvoid` | `{"data":flag}` |
| 2049 | `ClassicWalk` | `{"data":flag}` |
| 2050 | `WalkUpright` | `{"data":flag}` |
| 2051 | `CrossStep` | `{"data":flag}` |
| 2054 | `AutoRecoverySet` | `{"data":flag}` |
| 2055 | `AutoRecoveryGet` | `{}` → 读 `data["data"]` |
| 2058 | `SwitchAvoidMode` | `{}` |

#### B2 Sport（topic `/api/sport/{request,response}`，与 Go 同 namespace 但 ID 子集不同）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 1008 | `Move` | `{"x":vx, "y":vy, "z":vyaw}` |
| 1011 | `SwitchGait` | `{"data":d}` |
| 1013 | `BodyHeight` | `{"data":h}` |
| 1015 | `SpeedLevel` | `{"data":lvl}` |
| 1018 | `TrajectoryFollow` | `[ {"t_from_start","x","y","yaw","vx","vy","vyaw"} × 30 ]` |
| 1019 | `ContinuousGait` | `{"data":flag}` |
| 1036 | `MoveToPos` | `{"x":x, "y":y, "yaw":yaw}` |
| 1038 | `SwitchMoveMode` | `{"data":flag}` |
| 1039 | `HandStand` | `{"data":flag}` |
| 1040 | `AutoRecoverySet` | `{"data":flag}` |
| 1045 | `FreeWalk` | `{}` |
| 1049 | `ClassicWalk` | `{"data":flag}` |
| 1050 | `FastWalk` | `{"data":flag}` |
| 1051 | `Euler` | `{"x":roll, "y":pitch, "z":yaw}` |
| 1101 | `VisionWalk` | `{"data":flag}` |

（B2 还有 `Damp/BalanceStand/StopMove/StandDown/RecoveryStand` 等共享 Go 的 1001–1006 部分 ID，详见 `ros2_b2_sport_client.cpp`。）

#### G1/H2 Loco（topic `/api/sport/{request,response}`）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 7001 | `GetFsmId` | `{}` → `{"data":int}` |
| 7002 | `GetFsmMode` | `{}` → `{"data":int}` |
| 7003 | `GetBalanceMode` | `{}` → `{"data":int}` |
| 7004 | `GetSwingHeight` | `{}` → `{"data":float}` |
| 7005 | `GetStandHeight` | `{}` → `{"data":float}` |
| 7006 | `GetPhase` | `{}` → `{"data":[float,...]}` |
| 7007 | `GetArmSdkStatus`（H2） | `{}` |
| 7008 | `GetAvailableFsmIds`（H2） | `{}` |
| 7101 | `SetFsmId` | `{"data":id}` |
| 7102 | `SetBalanceMode` | `{"data":mode}` |
| 7103 | `SetSwingHeight` | `{"data":height}` |
| 7104 | `SetStandHeight` | `{"data":height}` |
| 7105 | `SetVelocity` | `{"x":vx, "y":vy, "z":ω, "duration":dur}` |
| 7106 | `SetTaskId`（loco）/ `ExecuteAction`（arm action） | `{"data":id}` |
| 7107 | `SetSpeedMode`（loco）/ `GetActionList`（arm action） | `{"data":mode}` / `{}` |
| 7108 | `SetPunchApi`（H2） | … |
| 7109 | `SetArmSdkStatus`（H2） | `{"data":bool}` |

> **FSM ID 速查**：`0` ZeroTorque、`1` Damp、`2` Squat、`3` Sit、`4` StandUp、`500` Start (loco 主控)、`501/801` ArmAction 允许窗口。

#### G1 Audio（topic `/api/voice/{request,response}`）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 1001 | `TtsMaker` | `{"index":u32, "text":str, "speaker_id":i32}` |
| 1002 | `Asr`（预留） | — |
| 1003 | `PlayStream` | `{"app_name":str, "stream_id":str}` + `Request.binary=PCM` |
| 1004 | `PlayStop` | `{"app_name":str}` |
| 1005 | `GetVolume` | `{}` → `{"volume":0..100}` |
| 1006 | `SetVolume` | `{"volume":0..100}` |
| 1010 | `SetRgbLed` | `{"R":0..255, "G":0..255, "B":0..255}` |

#### MotionSwitcher（topic `/api/motion_switcher/{request,response}`）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 1001 | `CheckMode` | `{}` → `{"form":"0|1", "name":str}` |
| 1002 | `SelectMode` | `{"name":str}` |
| 1003 | `ReleaseMode` | `{}` |
| 1004 | `SetSilent` | `{"silent":bool}` |
| 1005 | `GetSilent` | `{}` → `{"silent":bool}` |

#### Go2 RobotState（topic `/api/robot_state/{request,response}`）

| api_id | 方法 | 参数 JSON |
|---|---|---|
| 1001 | `ServiceSwitch` | `{"name":str, "switch":int}` → `{"status":int}` |
| 1002 | `SetReportFreq` | `{"interval":int, "duration":int}` |
| 1003 | `ServiceList` | `{}` → `[{"name","status","protect"}, …]` |

### 3.3 Loco / ArmAction 错误码

| code | 名 | 含义 |
|---|---|---|
| 0 | `UT_ROBOT_SUCCESS` | 成功 |
| −1 | `UT_ROBOT_TASK_TIMEOUT` | RPC 超时 5 s |
| −2 | `UT_ROBOT_TASK_UNKNOWN_ERROR` | 异常 / 序列化失败 |
| 7301 | `UT_ROBOT_LOCO_ERR_LOCOSTATE_NOT_AVAILABLE` | locostate 未上线 |
| 7302 | `UT_ROBOT_LOCO_ERR_INVALID_FSM_ID` | 不允许的 FSM 值 |
| 7303 | `UT_ROBOT_LOCO_ERR_INVALID_TASK_ID` | 不允许的 task id |
| 7400 | `UT_ROBOT_ARM_ACTION_ERR_ARMSDK` | ArmSDK 拒绝（未启用？） |
| 7401 | `UT_ROBOT_ARM_ACTION_ERR_HOLDING` | 动作正在执行 |
| 7402 | `UT_ROBOT_ARM_ACTION_ERR_INVALID_ACTION_ID` | action_id 不在动作库 |
| 7404 | `UT_ROBOT_ARM_ACTION_ERR_INVALID_FSM_ID` | 当前 FSM 不允许（须在 500/501/801） |

### 3.4 G1 关节索引速查（5DoF 臂版）

| idx | 关节 | idx | 关节 |
|---|---|---|---|
| 0 | LEFT_HIP_PITCH | 15 | LEFT_SHOULDER_PITCH |
| 1 | LEFT_HIP_ROLL | 16 | LEFT_SHOULDER_ROLL |
| 2 | LEFT_HIP_YAW | 17 | LEFT_SHOULDER_YAW |
| 3 | LEFT_KNEE | 18 | LEFT_ELBOW_PITCH |
| 4 | LEFT_ANKLE_PITCH | 19 | LEFT_ELBOW_ROLL |
| 5 | LEFT_ANKLE_ROLL | 20 | (reserved) |
| 6 | RIGHT_HIP_PITCH | 21 | (reserved) |
| 7 | RIGHT_HIP_ROLL | 22 | RIGHT_SHOULDER_PITCH |
| 8 | RIGHT_HIP_YAW | 23 | RIGHT_SHOULDER_ROLL |
| 9 | RIGHT_KNEE | 24 | RIGHT_SHOULDER_YAW |
| 10 | RIGHT_ANKLE_PITCH | 25 | RIGHT_ELBOW_PITCH |
| 11 | RIGHT_ANKLE_ROLL | 26 | RIGHT_ELBOW_ROLL |
| 12 | WAIST_YAW | 29 | `kNotUsedJoint`（**承载 ArmSDK weight ∈ [0,1]**） |
| 13 | WAIST_ROLL | | |
| 14 | WAIST_PITCH | | |

> 7DoF 臂版：左 18→ELBOW、19→WRIST_ROLL、20→WRIST_PITCH、21→WRIST_YAW；右 25/26/27/28 同左。腿/腰索引不变。

---

## 4. 协议与数据流补充说明

### 4.1 ROS 2 ↔ CycloneDDS ↔ 真机的桥接原理

Unitree 真机内部的中间件就是 [Eclipse CycloneDDS](https://github.com/eclipse-cyclonedds/cyclonedds)，话题、QoS、字段顺序固定。要让 ROS 2 节点直接订到真机 topic，必须满足三件事：

1. **同一个 RMW**：把 `RMW_IMPLEMENTATION` 切到 `rmw_cyclonedds_cpp`（默认 ROS 2 是 `rmw_fastrtps_cpp`）。`setup*.sh` 里都做了这步。
2. **同一个 IDL**：本仓的 `unitree_go / unitree_hg / unitree_api` 三个 msg 包**字段顺序与类型与真机 SDK 完全一致**，编译后产生的 IDL fingerprint 与真机端匹配，DDS 才认得。
3. **同一个 NetworkInterface**：通过 `CYCLONEDDS_URI` XML 把 CycloneDDS 限定在某网卡（与真机同一 subnet）。三个 setup 脚本的差别正在此：
   - `setup.sh` → `enp3s0`（典型真机以太网）。
   - `setup_local.sh` → `lo`（环回，仿真/本机 mock）。
   - `setup_default.sh` → 不设 URI，CycloneDDS 自己挑（适合 docker `--net=host` 或单网卡机）。

CycloneDDS 域 ID 默认走 `ROS_DOMAIN_ID`（未设则 0）。多个 ROS 2 节点之间共用域 ID 即可发现，跨子网需配 `Discovery/Peers`，但本仓不涉及。

### 4.2 LowCmd / LowState 控制协议解剖

#### 4.2.1 单电机指令的语义（共 6 字段 + reserve）

| 字段 | 作用 | 备注 |
|---|---|---|
| `mode` | 工作模式：`0x00`=BRAKE、`0x01`=FOC（PMSM）、其它型号特有 | 真机收到 `0x01` 才会执行 PD+前馈；`0x00` 仅短路阻尼。 |
| `q` | 期望角度 (rad) | 若 `q == PosStopF (2.146e9)` 表示"不要位置控制"。 |
| `dq` | 期望角速度 (rad/s) | 若 `dq == VosStopF (16000.0)` 表示"不要速度控制"。 |
| `tau` | 前馈力矩 (N·m) | 直接累加到电机闭环输出。 |
| `kp / kd` | 位置/速度刚度阻尼 | 闭环式：`τ_total = kp·(q*−q) + kd·(dq*−dq) + tau`。Stop 标志位时对应通道刚度被忽略。 |

#### 4.2.2 Go vs HG LowCmd 的关键差异

| 维度 | Go (`unitree_go::msg::LowCmd`) | HG (`unitree_hg::msg::LowCmd`) |
|---|---|---|
| 电机数 | 20（实用 12，多余位为 0） | 35（H1‑2 用 27，G1 用 29，H2 用 31） |
| 头字段 | `head[2] / level_flag / frame_reserve / sn[2] / version[2] / bandwidth` | `mode_pr / mode_machine` |
| 外设字段 | `BmsCmd / wireless_remote[40] / led[12] / fan[2] / gpio` | 无 |
| CRC 实现 | `motor_crc.cpp:get_crc()` | `motor_crc_hg.cpp:get_crc()` |
| 多项式 | IEEE‑802.3 `0x04C11DB7`，初值 `0xFFFFFFFF` | 同 |
| 覆盖范围 | 整个 `LowCmd` POD 减去末尾 4 字节 `crc`（即 `(sizeof(LowCmd)>>2)−1` 个 `uint32`） | 同 |

**`mode_pr` (HG 专用)**：脚踝并联机构控制选择。
- `PR=0`：把脚踝当成串联两关节，命令直接是 pitch 与 roll 的目标角；驱动器内部用串联运动学合成两个并联连杆角度。适合刚性轨迹回放、调试。
- `AB=1`：直接给两根连杆 (A/B) 的目标角；上层得自己做并联运动学。适合 RL policy 直接学并联自由度。

**`mode_machine` (HG 专用)**：真机厂端写入的机型代号，应用层读到后**原样回写**到 LowCmd（见 `low_level_ctrl_hg.cpp:94 / :169`、`g1_low_level_example.cpp` 同），用于真机校验"对方知不知道自己是哪台机器"，不一致会触发安全保护。

### 4.3 高层 API（`unitree_api`）的 RPC 时序

```
┌─────────────────────────────────────────────────────────────┐
│  client                          robot                       │
│   │                                │                          │
│   │ build Request:                 │                          │
│   │   header.identity.id  = uptime_ns                          │
│   │   header.identity.api_id = e.g. 7105                      │
│   │   header.policy.noreply = false                           │
│   │   parameter = json.dump({"x":..., "y":..., "z":...})       │
│   │ ─── publish on /api/sport/request ───────────────────►    │
│   │                                                            │
│   │                                ─── handle, respond ───┐    │
│   │ ◄──────── on /api/sport/response ─────────────────────┘    │
│   │ check identity.id == own.id                                │
│   │ → fulfill promise, parse data as json                       │
└─────────────────────────────────────────────────────────────┘
```

实现细节：
- `BaseClient::Call` (`base_client.hpp:31-71`)：每次 `Call` 都**新建**一次性 `Subscription` 监听响应，匹配 `identity.id` 后通过 `std::promise<Response>` 唤醒 future，5 s `wait_for` 后超时返回 `UT_ROBOT_TASK_TIMEOUT`。简单但每次有创建/销毁订阅的开销。
- `B2BaseClient` (`b2_base_client.hpp:106-153`)：构造时建**持久订阅**，多线程 executor 自旋；用 `std::atomic<int64_t> current_request_id_` + `std::condition_variable response_cv_` + `call_mutex_` 实现高频并发安全。适合密集查询场景。
- `RequestPolicy.noreply=true`：单向指令（如 `SetReportFreq`），客户端不开订阅、直接发布即返回，无 5 s 阻塞。

### 4.4 实战 cheatsheet

#### 4.4.1 编译

```bash
# 1. 装 ROS 2 后
source /opt/ros/humble/setup.bash      # 或 foxy

# 2. 装 CycloneDDS RMW
sudo apt install ros-humble-rmw-cyclonedds-cpp ros-humble-rosidl-generator-dds-idl

# 3. build msg workspace
cd ~/unitree/unitree-notes/unitree_ros2/cyclonedds_ws
colcon build
source install/setup.bash

# 4. source 激活脚本（按场景三选一）
source ~/unitree/unitree-notes/unitree_ros2/setup.sh           # 真机，记得改 enp3s0
# 或 source ~/.../setup_local.sh                                # 本机仿真
# 或 source ~/.../setup_default.sh                              # 自动挑网卡

# 5. build example workspace
cd ~/unitree/unitree-notes/unitree_ros2/example
colcon build
source install/setup.bash
```

#### 4.4.2 跑示例

```bash
# 监听
ros2 topic list                                    # 应看到 /lowstate /lowcmd /sportmodestate ...
ros2 run unitree_ros2_example read_low_state        # Go 系列
ros2 run unitree_ros2_example read_low_state_hg     # HG 系列
ros2 run unitree_ros2_example read_motion_state
ros2 run unitree_ros2_example read_wireless_controller

# Go2 高层
ros2 run unitree_ros2_example go2_sport_client 1    # BalanceStand
ros2 run unitree_ros2_example go2_sport_client 2    # Move(0.3,0,0.3)
ros2 run unitree_ros2_example go2_robot_state_client

# B2 / B2W
ros2 run unitree_ros2_example b2_stand_example
ros2 run unitree_ros2_example b2_sport_client       # 进 REPL，输 "list"

# G1
ros2 run unitree_ros2_example g1_low_level_example
ros2 run unitree_ros2_example g1_loco_client_example   # 进 CLI，输 "stand_up"
ros2 run unitree_ros2_example g1_arm_action_example    # 输 "0" 看动作字典
ros2 run unitree_ros2_example g1_audio_client_example  # TTS + 播 test.wav
ros2 run unitree_ros2_example g1_dex3_example          # 灵巧手
```

#### 4.4.3 常见踩坑

1. **`ros2 topic list` 看不到真机 topic**：99% 是 `RMW_IMPLEMENTATION` 没切（仍是 fastrtps），或 `CYCLONEDDS_URI` 指错网卡。`echo $RMW_IMPLEMENTATION` 应输出 `rmw_cyclonedds_cpp`；`ip a` 看真正连真机的 NIC 名替换 `enp3s0`。
2. **CRC 校验报错 / 真机不动**：忘了在 publish 前调 `get_crc(low_cmd_)`；或者 Go 的 cmd 错用了 HG 的 CRC（反之）。两者 POD 布局不同，互不通用。
3. **HG 机型 LowState 没数据但 LowCmd 不响应**：忘了把 `mode_machine` 从 LowState 回写到 LowCmd。
4. **G1 ArmSDK 控不住臂**：`motor_cmd[kNotUsedJoint=29].q` 没设为 weight=1.0；正确做法是 demo 起手把 weight 拉到 1，结束前慢慢降到 0。
5. **`g1_dual_arm_example` 编不出来**：`apt install libyaml-cpp-dev` 后重 `colcon build`（CMakeLists 是 `find_package(yaml-cpp QUIET)` + `if()` 条件构建）。
6. **B2 sport_client 报 "another motion service active"**：先 `b2_motion_switch_client` (或 `b2_stand_example` 起手段) 调 `ReleaseMode()`。
7. **Foxy 编译 `unitree_api::msg::Response` 报缺 timestamp accessor**：本仓的 `patch.hpp` 已经特化好 `TimeStamp<>::value`，确保 `include/common/patch.hpp` 在那条 cpp 的 include 链里。
8. **`ros2 run` 找不到 `record_bag`**：它在 `CMakeLists.txt:49` 被注释，默认不编译。手动把那两行解注后 `colcon build` 即可。
9. **多机调试 / 多人同机**：`setup.sh` 里的 `RMW_IMPLEMENTATION` 是 export 全局变量，会影响该 shell 下**所有**后续 ROS 2 命令；若同机另一项目要用 fastrtps，需要新开 shell 或显式 `unset RMW_IMPLEMENTATION`。

---

> 文档版本：对应 `unitree_ros2` v0.3.0（2025‑08‑15）。后续版本若新增机型或 API，请按"`example/src/CMakeLists.txt:add_executable` → `include/<robot>/*.hpp` → API_ID 表"的顺序补本文档。
