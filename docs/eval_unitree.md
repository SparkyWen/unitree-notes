# Unitree 机器人任务执行与到位验证方法调研

**文件名**：`eval_unitree.md`  
**联网检索日期**：2026-05-20（Australia/Sydney）  
**适用对象**：Unitree Go2 / Go2-W / B2 / H1 / G1 等基于 `unitree_sdk2`、`unitree_ros2`、ROS 2、Nav2、SLAM/RTAB-Map/里程计的开发项目。  
**核心问题**：如何判断机器人“真的执行了指令/动作”，并且“确实到达指定位置/完成任务”。

---

## 0. 最重要结论

对 Unitree 机器人，**不要把 API 返回值、动作函数调用成功、Nav2 action succeeded、或者机器人看起来动了一下，等同于任务完成**。

更可靠的做法是把“完成”定义成一个**分层验证条件**：

```text
任务完成 = 命令被接受
        AND 机器人状态反馈是新鲜的
        AND 运动模式/控制模式正确
        AND 没有错误码、电机 lost、低电量、过温、通信超时
        AND 实际位姿进入目标容差
        AND 速度降到接近 0 并保持一段 settle window
        AND SLAM/odom/TF/外部真值之间没有明显冲突
        AND 任务语义后置条件成立
```

换句话说：

```text
Command acknowledged ≠ Command executed ≠ Motion achieved ≠ Task completed
```

在工程里应至少实现一个 `TaskEvaluator` / `GoalVerifier`，持续订阅机器人状态、里程计、TF、Nav2 action 反馈、低层电机状态，并把每条命令与后续状态窗口绑定起来做判定。

---

## 1. 联网检索到的公开做法与资料来源

下面是本次实时检索中最有价值的公开资料。后文会把这些资料抽象成可落地的验证方案。

### 1.1 Unitree 官方 `unitree_ros2`

**来源**：https://github.com/unitreerobotics/unitree_ros2

关键发现：

- `unitree_ros2` 说明 Unitree SDK2 基于 CycloneDDS，Go2、B2、H1 等底层可以与 ROS 2 通信机制兼容。
- 官方 README 中提供了状态获取示例：
  - `read_motion_state`：读取 SportmodeState。
  - `read_low_state`：读取 LowState。
  - `record_bag`：录 bag 的示例。
  - `go2_sport_client`：Go2 高层控制。
  - `go2_stand_example`：Go2 站立示例。
  - `go2_robot_state_client`：Go2 服务状态示例。
- SportmodeState 可通过 `lf/sportmodestate` 或 `sportmodestate` 订阅，包含：
  - `stamp`
  - `error_code`
  - `imu_state`
  - `mode`
  - `progress`
  - `gait_type`
  - `position[3]`
  - `velocity[3]`
  - `yaw_speed`
  - `range_obstacle[4]`
  - `foot_force[4]`
  - `foot_position_body[12]`
  - `foot_speed_body[12]`
- LowState 可通过 `lf/lowstate` 或 `lowstate` 订阅，包含：
  - IMU
  - 电机状态 `motor_state[20]`
  - BMS 电池状态
  - `foot_force`
  - `foot_force_est`
  - `tick`
  - 电压、电流、风扇、CRC 等
- Sportmode 控制是 request/response 方式，可向 `/api/sport/request` 发布 `unitree_api::msg::Request`。
- 低层电机控制通过 `/lowcmd` / DDS `rt/lowcmd`，低层状态通过 `/lowstate` / DDS `rt/lowstate`。

**对验证的启发**：

`/api/sport/request` 或 `SportClient.Move()` 只是发命令；真正的验证应订阅 `sportmodestate` 与 `lowstate`，检查实际位置、速度、模式、错误码、足端力、电机状态。

---

### 1.2 Unitree 官方 `unitree_sdk2`

**来源**：https://github.com/unitreerobotics/unitree_sdk2

关键发现：

- `go2_stand_example.cpp` 中使用：
  - `TOPIC_LOWCMD = "rt/lowcmd"`
  - `TOPIC_LOWSTATE = "rt/lowstate"`
  - `ChannelPublisher<LowCmd_>` 发布低层命令。
  - `ChannelSubscriber<LowState_>` 订阅低层状态。
- 示例会持续读取：
  - 电机角度 `low_state.motor_state()[i].q()`
  - IMU 加速度
  - 足端力 `foot_force`
- 低层示例中还会检查并释放运动控制相关服务，例如 `MotionSwitcherClient.CheckMode()`、`ReleaseMode()`。
- `go2_robot_state_client.cpp` 示例中使用 `RobotStateClient` 做：
  - `SetReportFreq`
  - `ServiceSwitch`
  - `ServiceList`
  - 读取服务 `name/status/protect`

**对验证的启发**：

低层动作不能只看你写入了 `LowCmd`；必须检查 `LowState.motor_state[].q/dq/tau_est/lost/temperature` 是否跟随目标。低层控制前还必须确认内置高层运动服务是否释放，否则存在控制冲突。

---

### 1.3 Unitree 官方 `unitree_sdk2_python`

**来源**：https://github.com/unitreerobotics/unitree_sdk2_python

关键发现：

- Python SDK2 与 C++ SDK2 保持一致，支持：
  - request-response
  - topic subscribe/publish
  - high-level status/control
  - low-level status/control
- 高层状态示例：`example/high_level/read_highstate.py`
- 高层控制示例：`example/high_level/sportmode_test.py`
- 示例中列出了：
  - `StandUpDown()`
  - `VelocityMove()`
  - `BalanceAttitude()`
  - `TrajectoryFollow()`
  - `SpecialMotions()`

**对验证的启发**：

Python 项目里也可以采用同样思路：发 `SportClient` 命令之后，单独开状态订阅器，验证高层状态与低层状态，不要只依赖函数返回值。

---

### 1.4 Unitree 官方 `unitree_mujoco`

**来源**：https://github.com/unitreerobotics/unitree_mujoco

关键发现：

- `unitree_mujoco` 允许把 `unitree_sdk2`、`unitree_ros2`、`unitree_sdk2_python` 的控制程序集成到 MuJoCo 仿真中，帮助 sim-to-real。
- 当前版本主要支持低层开发，用于控制器 sim-to-real 验证。
- 支持的消息包括：
  - `LowCmd`
  - `LowState`
  - `SportModeState`
  - `IMUState`（G1 的 `rt/secondary_imu`）
- README 特别说明：真实硬件上，关闭内置运动控制服务后，`SportModeState` 可能不可读；仿真器保留该消息以便分析控制程序。

**对验证的启发**：

如果你做低层控制，不应假设真实机上任何时候都有 `SportModeState`。因此验证系统要能 fallback 到 `LowState + IMU + 足端接触 + 外部 odom/SLAM/mocap`。

---

### 1.5 `snt-arg/unitree_ros`：Go1 ROS2 Driver

**来源**：https://github.com/snt-arg/unitree_ros

关键发现：

- 该包是 Go1 的 ROS2 驱动，作为 ROS2 与 `unitree_legged_sdk` 的中间件。
- 它订阅：
  - `cmd_vel`：接收速度命令并发送给机器人。
  - `/stand_up`
  - `/stand_down`
- 它发布：
  - `/odom`
  - `/imu`
  - `/bms_state`
  - `/sensor_ranges`
- 还提供：
  - LED 状态
  - 低电量保护
  - 障碍物避让参数

**对验证的启发**：

社区 ROS 包的做法通常是把 Unitree 私有状态转换成标准 ROS topics：`/cmd_vel`、`/odom`、`/imu`、`/bms_state`。你的验证器最好也基于标准 ROS topic 抽象，而不是只绑定 Unitree 私有消息。

---

### 1.6 `inria-paris-robotics-lab/go2_odometry`

**来源**：https://github.com/inria-paris-robotics-lab/go2_odometry

关键发现：

- 该项目为 Unitree Go2 提供状态估计，基于 invariant-EKF。
- 它还提供节点，把 Unitree custom messages 转成标准 ROS messages 并重新发布。
- launch 参数支持不同 odom source：
  - `use_full_odom`：Inekf filter，README 中称为首选。
  - `fake`
  - `mocap`
- 依赖包括 `unitree_ros2`、invariant-ekf、Unitree URDF、Pinocchio。

**对验证的启发**：

只靠 Unitree 内置 `position/velocity` 可能不够稳定。更可靠的是引入状态估计器，把 IMU、关节编码器、足端接触、必要时 mocap 融合成标准 `/odom` 或 `map->odom`。

---

### 1.7 `YibinWu/leg-odometry`

**来源**：https://github.com/YibinWu/leg-odometry

关键发现：

- 这是基于 IMU 与关节编码器的腿式机器人本体状态估计实现。
- README 提到使用了 Unitree Go2 采集的 ROS2 bag。
- 运行示例使用 `/lowstate` 话题。

**对验证的启发**：

如果没有可靠 LiDAR/视觉，仍可用“本体感知里程计”（IMU + 编码器 + 接触）作为短时移动验证来源。但它仍需要漂移检测与外部校准。

---

### 1.8 `Unitree-Go2-Robot/go2_robot`

**来源**：https://github.com/Unitree-Go2-Robot/go2_robot

关键发现：

该项目是 Go2 ROS2 集成，README checklist 包含：

- robot description
- odom
- pointcloud
- joint_states
- RViz visualization
- cmd_vel
- go2_interfaces
- mode/config change
- SLAM
- Nav2
- hardware interface
- Gazebo simulation

**对验证的启发**：

社区 Go2 项目普遍把“到位验证”放在 ROS2 标准栈中处理：TF、odom、pointcloud、SLAM、Nav2、RViz，而不是只靠 Unitree SDK 的 high-level command。

---

### 1.9 `grasp-lyrl/go2_ros2_webrtc_sdk`

**来源**：https://github.com/grasp-lyrl/go2_ros2_webrtc_sdk

关键发现：

- 非官方 ROS2 SDK 支持 Go2 AIR/PRO/EDU。
- launch stack 包含：
  - `robot_state_publisher`
  - Go2 driver node
  - LiDAR pointcloud
  - `pointcloud_to_laserscan`
  - `slam_toolbox`
  - Nav2 bringup
  - RViz
  - joystick teleop
  - `twist_mux`
- README 明确指出：
  - SLAM 用于生成 `/map`。
  - Nav2 用于在 map 中导航。
  - RViz 中显示 `RobotModel`、`PointCloud2`、`LaserScan`、`Image`、`Map`、`Odometry`。
  - Nav2 Goal 既设置目标位置，也设置最终朝向。
  - 许多错误行为，如原地转圈、撞墙、试图穿墙，往往来自：地图错误、初始位姿错误、控制 loop 负载过高。
  - 该项目把 `controller_frequency` 与 `expected_planner_frequency` 设置得比较保守，以降低过载导致的错误行为。
- README 还建议初期跟随机器人，必要时手动干预。

**对验证的启发**：

到位验证不能只看最终位置。还必须检查：地图是否可信、初始 pose 是否正确、局部规划是否持续输出有效 cmd_vel、控制频率是否过载、机器人是否因为错误地图而“认为自己到达”。

---

### 1.10 `Sayantani-Bhattacharya/unitree_go2_nav`

**来源**：https://github.com/Sayantani-Bhattacharya/unitree_go2_nav

关键发现：

- 使用：
  - Unitree Go2 high-level SDK wrapper
  - ROS2 Jazzy
  - RTAB-Map
  - Nav2
- 功能包括：
  - transform publishers
  - robot state publishers
  - RTAB-Map 生成 odom TF 和 occupancy grid
  - RViz visualization
  - Nav-to-pose 通过 Go2 API 实现 high-level control
  - Nav2 manual goal subscription
- README 指出，要先 `ros2 topic list` 确认 Unitree topics 可见。

**对验证的启发**：

公开 Go2 导航项目一般把“目标位置”放在 Nav2/RTAB-Map/TF 体系里处理，并把 Unitree API 作为底层执行器。验证应基于 `map/odom/base_link`，而不是只看 SDK 返回。

---

### 1.11 `NayiemW/biscuit-movements-unitree-go2`

**来源**：https://github.com/NayiemW/biscuit-movements-unitree-go2

关键发现：

- 该项目用 `SportClient` 对 Unitree Go2 做程序化速度控制。
- 关键初始化方式：
  - `ChannelFactoryInitialize(0, 'eth0')`
  - `SportClient()`
  - `client.SetTimeout(10.0)`
  - `client.Init()`
  - `client.Move(vx, vy, vyaw)`
- 作者建议以约 50Hz 发送命令以获得平滑控制。
- 该项目实现了 250ms deadman timeout：超过时间没收到命令就自动停止。
- 它把 `SportClient` 放在独立服务中，避免 DDS domain conflicts。

**对验证的启发**：

速度命令类任务必须检查：

- 命令是否持续发送。
- deadman 是否触发。
- 实际速度是否跟随目标速度。
- 停止命令之后速度是否真正降到 0。
- 是否存在 DDS/进程冲突导致命令未生效。

---

### 1.12 Nav2 官方文档

**来源**：

- SimpleGoalChecker: https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_goal_checker.html
- SimpleProgressChecker: https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_progress_checker.html
- FollowPath action: https://docs.ros.org/en/iron/p/nav2_msgs/interfaces/action/FollowPath.html
- ROS 2 Actions design: https://design.ros2.org/articles/actions.html

关键发现：

- `SimpleGoalChecker` 用于判断机器人是否到达 goal pose。
- Nav2 默认 `xy_goal_tolerance = 0.25 m`，`yaw_goal_tolerance = 0.25 rad`。
- `SimpleProgressChecker` 检查机器人是否持续朝目标产生位置进展，默认要求在 `movement_time_allowance = 10s` 内移动 `required_movement_radius = 0.5m`。
- `FollowPath` action feedback 包含：
  - `distance_to_goal`
  - `speed`
- `FollowPath` result error code 包含：
  - `FAILED_TO_MAKE_PROGRESS`
  - `NO_VALID_CONTROL`
  - `TF_ERROR`
  - `INVALID_PATH`
  - `PATIENCE_EXCEEDED`
- ROS 2 action 的结果状态有：
  - `SUCCEEDED`
  - `ABORTED`
  - `CANCELED`
- ROS 2 action 还提供 feedback、status、result。

**对验证的启发**：

Nav2 的 succeeded 是很重要的信号，但不是最终真值。工程上应把 Nav2 action result 与最终 `odom/map pose`、速度、TF、定位质量、外部真值一起判断。

---

### 1.13 Unitree 官方 SLAM / Navigation Services

**来源**：https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service

检索结果中的关键信息：

- 官方 SLAM/navigation service interface 基于 Unitree SDK2。
- 支持通过 topic 获取实时 odom，例如 `rt/unitree/slam_mapping/odom`，数据类型为 `nav_msgs::msg::dds_::Odometry_`。
- 检索结果显示该接口主要面向 EDU 机器狗、扩展坞与官方 LiDAR 配置。

**对验证的启发**：

如果你使用官方 SLAM/navigation service，应优先把官方 odom topic 纳入验证器；但仍需检查硬件版本、LiDAR/扩展坞支持、地图质量和定位状态。

---

### 1.14 公开 Issue / 经验中的常见坑

检索到的公开问题包括：

- `Frame [odom] does not exist`：Go2 ROS2 项目中有人遇到 RViz/TF 里没有 odom frame 的问题。
- `Navigation Outputs Zero cmd_vel on Unitree GO2 EDU`：有人报告 Unitree Go2 不原生发布标准 ROS2 odometry，需要自己写转换节点，否则导航输出可能异常。
- 关于 Unitree SDK odometry 数据是否可靠、如何改善真实机器人部署里里程计的问题。
- WebRTC/SDK/DDS 场景下可能存在 domain conflicts，需要专门进程或明确网络接口。
- Go2 WebRTC Nav2 项目指出错误地图、错误初始位姿、控制循环过载会导致导航异常。

**对验证的启发**：

很多“机器人没按指令做”其实不是动作接口本身的问题，而是：

- TF 树缺失或错 frame。
- odom 不发布、不更新或跳变。
- map 与真实世界不一致。
- initial pose 设置错。
- Nav2 输出了 0 cmd_vel。
- controller/planner 频率过高导致计算不过来。
- SDK 进程冲突或网络接口选错。

---

## 2. 推荐的验证分层模型

### 2.1 L0：命令层验证

验证内容：

- 命令是否成功发送。
- API / service / action 是否接受。
- 是否分配了 command id / action goal id。
- 是否有返回码、错误码、reject。

典型数据源：

- `SportClient` 函数返回值。
- `/api/sport/request` publish 日志。
- ROS 2 action goal accepted。
- `RobotStateClient.ServiceList()` / `ServiceSwitch()`。
- 命令发送进程 heartbeat。

判定：

```text
L0_PASS = command_sent AND accepted_or_no_error
```

注意：

L0 只能证明“指令进入系统”，不能证明机器人执行完成。

---

### 2.2 L1：通信与状态新鲜度验证

验证内容：

- 状态 topic 是否持续更新。
- `stamp` / `tick` 是否增加。
- 状态消息延迟是否低于阈值。
- 机器人是否处于可控状态。
- 网络接口是否正确。

典型数据源：

- `/sportmodestate` 或 `lf/sportmodestate`
- `/lowstate` 或 `lf/lowstate`
- DDS `rt/sportmodestate`
- DDS `rt/lowstate`
- `/odom`
- `/tf`
- `/imu`

建议阈值起点：

| 项目 | 建议起点 |
|---|---:|
| 状态消息最大年龄 | 0.2–0.5 s |
| odom 最大年龄 | 0.2–0.5 s |
| TF 最大年龄 | 0.2–0.5 s |
| 连续丢包容忍 | 3–5 帧 |

判定：

```text
L1_PASS = latest_state_age < max_age
       AND tick_or_stamp_increasing
       AND odom_tf_available
```

---

### 2.3 L2：运动模式与低层执行验证

验证内容：

- 当前运动模式是否与任务匹配。
- 高层 locomotion / balance / pose / stand 等状态是否正确。
- 低层电机是否真的跟随目标位置/速度/力矩。
- 足端力是否与站立、行走、落脚等动作一致。
- 是否存在电机 lost、过温、低电量、保护状态。

典型数据源：

- `SportmodeState.mode`
- `SportmodeState.gait_type`
- `SportmodeState.error_code`
- `LowState.motor_state[i].q`
- `LowState.motor_state[i].dq`
- `LowState.motor_state[i].tau_est`
- `LowState.motor_state[i].lost`
- `LowState.motor_state[i].temperature`
- `LowState.foot_force`
- `LowState.bms_state`

低层关节动作验证公式：

```text
joint_error_i = abs(q_actual_i - q_target_i)
velocity_error_i = abs(dq_actual_i - dq_target_i)

JOINT_REACHED = max(joint_error_i) < q_tol
             AND max(abs(dq_actual_i)) < dq_stop_tol
             AND hold_time > settle_time
```

建议阈值起点：

| 项目 | 建议起点 |
|---|---:|
| 关节角误差 `q_tol` | 0.03–0.08 rad |
| 关节速度停止阈值 | 0.05–0.2 rad/s |
| settle window | 0.3–1.0 s |
| 电机 lost | 必须为 0 或无异常 |

注意：

阈值要根据动作、负载、地面、控制频率重新标定。不要把上表当作硬标准。

---

### 2.4 L3：位姿与到位验证

验证内容：

- 当前位姿是否进入目标容差。
- 朝向是否进入容差。
- 是否真正停稳。
- 目标坐标系是否正确。
- map/odom/base_link 的 TF 是否一致。
- 定位是否可信。

典型数据源：

- `/odom`
- `/tf`: `map -> odom -> base_link`
- `SportmodeState.position`
- `SportmodeState.velocity`
- `SportmodeState.yaw_speed`
- 官方 SLAM odom：`rt/unitree/slam_mapping/odom`
- RTAB-Map odom
- SLAM Toolbox pose
- external pose：mocap、AprilTag、UWB、Vicon、OptiTrack、激光定位等

核心公式：

```text
position_error = sqrt((x - x_goal)^2 + (y - y_goal)^2)
yaw_error = atan2(sin(yaw - yaw_goal), cos(yaw - yaw_goal))

POSE_REACHED = position_error < xy_tol
            AND abs(yaw_error) < yaw_tol

STATIONARY = norm(linear_velocity_xy) < v_tol
          AND abs(yaw_rate) < yaw_rate_tol

ARRIVED = POSE_REACHED
       AND STATIONARY
       AND condition_holds_for(settle_time)
```

建议阈值起点：

| 项目 | 建议起点 | 说明 |
|---|---:|---|
| `xy_tol` | 0.10–0.25 m | Nav2 默认常见起点为 0.25 m；Go2 室内可先从 0.20 m 调起 |
| `yaw_tol` | 0.15–0.35 rad | 约 8.6°–20°；过小可能导致原地抖动 |
| `v_tol` | 0.03–0.08 m/s | 用于确认停稳 |
| `yaw_rate_tol` | 0.03–0.10 rad/s | 用于确认朝向不再变化 |
| `settle_time` | 0.5–2.0 s | 地面越复杂越长 |

重要：

如果只用里程计判断，到达的是“机器人估计自己到达”。如果地图/里程计漂移，机器人可能在错误位置却显示到达。因此关键任务要增加外部真值或环境语义确认。

---

### 2.5 L4：Nav2 / SLAM 行为验证

验证内容：

- Nav2 action 是否 accepted。
- Nav2 action result 是否 `SUCCEEDED`。
- feedback 的 `distance_to_goal` 是否持续下降。
- `FollowPath` 是否出现 `FAILED_TO_MAKE_PROGRESS`、`NO_VALID_CONTROL`、`TF_ERROR`。
- costmap 是否有目标点。
- local planner 是否持续输出非零 cmd_vel。
- 到达后实际 pose 是否仍满足容差。

典型数据源：

- `/navigate_to_pose` action result/status/feedback
- `/follow_path` action feedback
- `/cmd_vel`
- `/odom`
- `/tf`
- `/map`
- local/global costmap
- controller_server / planner_server diagnostics

建议判定：

```text
NAV_OK = action_result == SUCCEEDED
      AND final_pose_ok
      AND final_velocity_ok
      AND no_recent_progress_error
      AND localization_ok
```

不要只写：

```text
if action_result == SUCCEEDED:
    return True
```

更好的写法：

```text
if action_result == SUCCEEDED:
    wait(settle_time)
    return pose_ok() and velocity_ok() and tf_ok() and localization_ok()
```

---

### 2.6 L5：外部真值与任务语义验证

验证内容：

- 机器人是否真的在物理世界目标位置。
- 是否真的完成“任务语义”，而不只是运动到某个坐标。

可用方法：

| 方法 | 适合场景 | 优点 | 缺点 |
|---|---|---|---|
| Motion capture / Vicon / OptiTrack | 实验室 | 高精度 | 成本高，环境受限 |
| AprilTag / ArUco | 室内目标点、工位 | 便宜，可给绝对位姿 | 需要视觉可见 |
| UWB | 大空间粗定位 | 易部署 | 精度通常低于视觉/mocap |
| LiDAR ICP / scan matching | 室内导航 | 与 SLAM 一致 | 退化场景会漂移 |
| 地面标线 / 充电桩 / docking marker | 定点任务 | 可强验证到位 | 需要布置环境 |
| 人工尺量 / 标尺 | 调试阶段 | 简单 | 不自动化 |
| 任务传感器 | 抓取、开门、巡检 | 验证最终语义 | 每个任务都不同 |

任务语义例子：

| 任务 | 不能只验证 | 还应验证 |
|---|---|---|
| 去到 A 点 | Nav2 succeeded | A 点 AprilTag/工位 marker 可见，最终 pose 正确 |
| 巡检设备 | 到达设备附近 | 设备图像识别成功，目标框置信度足够 |
| 推门/开门 | 机械臂动作完成 | 门角度传感器/视觉判断门已开 |
| 搬运物体 | 走到坐标 | 物体在夹爪中，重量/视觉/力传感器确认 |
| 跟随人 | 速度命令输出 | 人物检测持续存在，距离误差满足条件 |

---

## 3. 不同任务类型的具体做法

## 3.1 速度命令：`Move(vx, vy, vyaw)` / `/cmd_vel`

### 目标

判断机器人是否真的按照速度命令运动，并在指定时间/距离后停止。

### 常见错误

- 命令发出但 DDS 冲突，机器人没动。
- 命令频率太低，deadman 触发停止。
- `/cmd_vel` 有值，但没有真正送到 Unitree 控制器。
- `/cmd_vel` 为 0，因为 Nav2 没有有效路径或 odom/TF 不正常。
- 机器人被障碍物避让、低电量保护、模式不匹配拦住。

### 推荐验证流程

1. 给每条速度命令生成 `command_id`。
2. 记录发送时间 `t0`、目标速度 `(vx, vy, vyaw)`、期望持续时间 `T`。
3. 持续订阅：
   - `/cmd_vel`
   - `/sportmodestate.velocity`
   - `/sportmodestate.yaw_speed`
   - `/odom.twist.twist`
   - `/lowstate`
4. 计算实际速度跟踪误差：

```text
v_error = norm(v_actual_xy - v_cmd_xy)
yaw_rate_error = abs(yaw_rate_actual - yaw_rate_cmd)
```

5. 积分实际 odom 位移：

```text
distance_actual = sum(norm(v_actual_xy) * dt)
yaw_actual = sum(yaw_rate_actual * dt)
```

6. 停止命令后确认：

```text
norm(v_actual_xy) < v_stop_tol
abs(yaw_rate_actual) < yaw_stop_tol
hold for settle_time
```

### 成功条件示例

```text
SPEED_TASK_SUCCESS = telemetry_alive
                  AND mode_ok
                  AND no_fault
                  AND command_stream_rate_ok
                  AND mean_velocity_tracking_error < threshold
                  AND expected_displacement_reached
                  AND stopped_after_stop_command
```

### 重要建议

不要用 `vx * T` 当作最终真值。应该用 odom / SLAM / external pose 的实际位移作为结果。

---

## 3.2 到达指定位置：导航目标 / waypoint / Nav2 Goal

### 目标

判断机器人是否到达目标 `(x_goal, y_goal, yaw_goal)`。

### 推荐验证流程

1. 明确目标坐标系：`map`、`odom` 还是 `base_link`。
2. 如果是相对目标，例如“向前 1m”，先把目标从 `base_link` 转换到 `odom` 或 `map`。
3. 发送 Nav2 `NavigateToPose` action 或你的自定义路径控制。
4. 监控 action feedback：
   - goal accepted
   - feedback distance_to_goal
   - status
   - result
5. 同时监控实际 pose：
   - `map -> base_link`
   - 或 `odom -> base_link`
6. 到 action success 后不要立刻判定成功；等待 settle window，再检查：

```text
position_error < xy_tol
abs(yaw_error) < yaw_tol
linear_speed < v_tol
yaw_rate < yaw_rate_tol
no localization jump
no stale TF
```

### 成功条件示例

```text
GOAL_SUCCESS = action_succeeded_or_custom_controller_done
            AND pose_error_ok
            AND yaw_error_ok
            AND stationary_ok
            AND no_fault
            AND localization_confidence_ok
            AND final_pose_holds_for_settle_time
```

### 推荐初始参数

```yaml
xy_goal_tolerance: 0.20      # 可从 0.25m 开始，稳定后再收紧
yaw_goal_tolerance: 0.25     # rad
settle_time: 1.0             # seconds
v_stop_tolerance: 0.05       # m/s
yaw_rate_stop_tolerance: 0.05 # rad/s
max_state_age: 0.3           # seconds
```

### 绝对不要忽略 frame

常见错误是目标在 `map`，当前位姿却取自 `odom` 或 Unitree 本体估计，导致误差计算没有意义。

建议始终记录：

```text
goal.frame_id
pose.frame_id
odom.header.frame_id
odom.child_frame_id
tf map->odom
tf odom->base_link
```

---

## 3.3 低层关节动作 / 姿态控制

### 目标

判断某个站立、蹲下、摆腿、机械臂或关节动作是否真的到达目标姿态。

### 推荐验证流程

1. 记录目标关节角 `q_target[i]`。
2. 发布 `LowCmd`。
3. 订阅 `LowState`。
4. 检查：

```text
max_abs_q_error = max_i(abs(q_actual[i] - q_target[i]))
max_abs_dq = max_i(abs(dq_actual[i]))
max_abs_tau = max_i(abs(tau_est[i]))
```

5. 根据动作类型检查足端力/接触状态：
   - 站立：四足接触力应大致稳定。
   - 抬腿：对应脚足端力应显著下降。
   - 落脚：对应脚足端力恢复。
6. 检查 `lost`、温度、电池、电压、电流是否异常。
7. 在 `settle_time` 内持续满足误差阈值才判定成功。

### 成功条件示例

```text
JOINT_ACTION_SUCCESS = all_joint_errors_below_tol
                    AND all_joint_velocities_below_tol
                    AND contact_pattern_ok
                    AND no_motor_lost
                    AND no_temperature_or_power_fault
                    AND condition_holds_for_settle_time
```

### 低层控制的特殊注意

如果你使用低层控制，必须确认内置高层运动服务是否已经关闭或不会与你的 low-level controller 冲突。Unitree 官方低层示例中就会检查 motion service 状态并释放相关模式。

---

## 3.4 特殊动作：站起、趴下、翻身、跳跃、恢复站立

### 难点

特殊动作通常不是“到达某个平面坐标”，而是一段离散行为。你不能只看函数返回。

### 推荐验证信号

| 动作 | 可验证信号 |
|---|---|
| stand up | body_height 增加到目标范围；IMU roll/pitch 稳定；四足 foot_force 稳定 |
| lie down | body_height 降低；mode 进入 lieDown 或相应状态；速度接近 0 |
| recovery stand | roll/pitch 从异常恢复到稳定范围；body_height 回升；足端力恢复 |
| front jump/front flip | IMU 角速度/姿态轨迹符合动作窗口；落地后姿态稳定；无 error_code |
| sit | body_height、关节角、足端力模式符合坐下状态 |

### 成功条件示例

```text
SPECIAL_ACTION_SUCCESS = action_started
                      AND expected_mode_sequence_seen
                      AND imu_body_height_signature_ok
                      AND final_stable_pose_ok
                      AND no_fault
```

---

## 3.5 巡航 / 多 waypoint / 覆盖路径

### 目标

判断机器人是否按顺序经过多个点，而不是只到最后一个点。

### 推荐验证

对每个 waypoint 生成独立状态：

```text
WAYPOINT_i = reached_i AND stationary_or_passed_i AND timestamp_i recorded
MISSION = all_waypoints_reached_in_order AND no_forbidden_zone_violation
```

建议记录：

- 每个 waypoint 到达时间。
- 每段路径最大偏差。
- 每段平均速度。
- 每段是否触发 recovery。
- 是否出现定位跳变。
- 是否穿越 forbidden zone。

---

## 4. 推荐的系统架构

```text
┌─────────────────────┐
│ Mission / User Cmd   │
│ command_id, target   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Command Gateway      │
│ SportClient/Nav2/... │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Unitree Robot        │
│ motion controller    │
└──────────┬──────────┘
           │ telemetry
           ▼
┌──────────────────────────────────────────────┐
│ Telemetry Collector                           │
│ sportmodestate / lowstate / odom / tf / imu   │
│ cmd_vel / action feedback / lidar / map       │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌─────────────────────┐
│ TaskEvaluator        │
│ pose, velocity, mode │
│ fault, semantics     │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Result + Evidence    │
│ PASS/FAIL + metrics  │
│ rosbag + JSONL       │
└─────────────────────┘
```

每次任务结果都不要只保存 `success=True/False`，而要保存证据：

```json
{
  "command_id": "cmd_20260520_001",
  "task_type": "navigate_to_pose",
  "goal": {"frame": "map", "x": 1.2, "y": -0.4, "yaw": 1.57},
  "result": "PASS",
  "metrics": {
    "final_xy_error_m": 0.08,
    "final_yaw_error_rad": 0.11,
    "final_speed_mps": 0.02,
    "settle_time_s": 1.0,
    "max_state_age_s": 0.06,
    "nav2_result": "SUCCEEDED"
  },
  "evidence": {
    "bag": "bags/cmd_20260520_001",
    "state_topic": "/sportmodestate",
    "odom_topic": "/odom",
    "tf_chain": "map->odom->base_link"
  }
}
```

---

## 5. ROS2 记录与调试命令

### 5.1 先确认 topic

```bash
ros2 topic list
ros2 topic echo /sportmodestate --once
ros2 topic echo /lowstate --once
ros2 topic echo /odom --once
ros2 run tf2_tools view_frames
```

如果你的系统使用 DDS 原生 topic，可能看到 `rt/lowstate`、`rt/lowcmd`、`rt/sportmodestate`。如果使用 `unitree_ros2`，可能看到 `/sportmodestate`、`lf/sportmodestate`、`/lowstate`、`lf/lowstate`。以 `ros2 topic list` 实际输出为准。

### 5.2 录制验证证据

```bash
mkdir -p bags
ros2 bag record \
  /sportmodestate \
  /lowstate \
  /odom \
  /tf \
  /tf_static \
  /cmd_vel \
  /imu \
  /map \
  -o bags/eval_run_001
```

如果使用 Nav2，可额外记录：

```bash
ros2 bag record \
  /navigate_to_pose/_action/status \
  /navigate_to_pose/_action/feedback \
  /follow_path/_action/status \
  /follow_path/_action/feedback \
  /local_costmap/costmap \
  /global_costmap/costmap \
  -o bags/nav_eval_001
```

注意：ROS2 action 的 topic/service 是隐藏的，必要时使用：

```bash
ros2 topic list --include-hidden-topics
ros2 action list
ros2 action info /navigate_to_pose
```

---

## 6. Python 判定函数示例

下面是核心逻辑示例。你可以把它放入自己的 ROS2 节点中，订阅 `/odom`、`/sportmodestate`、`/lowstate` 后调用。

```python
import math
from dataclasses import dataclass
from typing import Optional


def normalize_angle(angle: float) -> float:
    """Normalize angle to [-pi, pi]."""
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw_from_quat(q) -> float:
    """geometry_msgs/Quaternion -> yaw."""
    siny_cosp = 2.0 * (q.w * q.z + q.x * q.y)
    cosy_cosp = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny_cosp, cosy_cosp)


@dataclass
class Pose2D:
    x: float
    y: float
    yaw: float


@dataclass
class GoalTolerance:
    xy: float = 0.20
    yaw: float = 0.25
    v: float = 0.05
    yaw_rate: float = 0.05
    max_state_age: float = 0.30
    settle_time: float = 1.0


def pose_error(current: Pose2D, goal: Pose2D) -> tuple[float, float]:
    xy_err = math.hypot(current.x - goal.x, current.y - goal.y)
    yaw_err = abs(normalize_angle(current.yaw - goal.yaw))
    return xy_err, yaw_err


def pose_reached(current: Pose2D, goal: Pose2D, tol: GoalTolerance) -> bool:
    xy_err, yaw_err = pose_error(current, goal)
    return xy_err <= tol.xy and yaw_err <= tol.yaw


def stationary(vx: float, vy: float, yaw_rate: float, tol: GoalTolerance) -> bool:
    return math.hypot(vx, vy) <= tol.v and abs(yaw_rate) <= tol.yaw_rate


def state_fresh(now_sec: float, state_stamp_sec: float, tol: GoalTolerance) -> bool:
    return (now_sec - state_stamp_sec) <= tol.max_state_age
```

推荐最终判定不要写成一个瞬时判断，而要写成窗口判断：

```python
class SettleWindow:
    def __init__(self, required_duration: float):
        self.required_duration = required_duration
        self.start_time: Optional[float] = None

    def update(self, now: float, condition_ok: bool) -> bool:
        if condition_ok:
            if self.start_time is None:
                self.start_time = now
            return (now - self.start_time) >= self.required_duration
        self.start_time = None
        return False
```

使用方式：

```python
condition_ok = (
    pose_reached(current_pose, goal_pose, tol)
    and stationary(vx, vy, yaw_rate, tol)
    and state_fresh(now, odom_stamp, tol)
    and no_fault
    and mode_ok
)

arrived = settle_window.update(now, condition_ok)
```

---

## 7. ROS2 Nav2 到位验证伪代码

```python
# 伪代码：重点是逻辑，不是完整可运行节点

send NavigateToPose(goal)
wait until goal accepted

while action not terminal:
    feedback = get_action_feedback()
    odom = latest_odom()
    tf = latest_tf("map", "base_link")

    if telemetry_stale():
        mark_warning("stale telemetry")

    if feedback.distance_to_goal is not decreasing for too long:
        mark_warning("no progress")

    if cmd_vel is zero for too long while far from goal:
        mark_warning("controller output zero")

result = get_action_result()

if result != SUCCEEDED:
    return FAIL(reason=result)

# 不要在这里直接 PASS
# action succeeded 后再做最终物理状态验证
wait 0.5~2.0 sec while continuing to monitor pose and velocity

if pose_error < tolerance and robot_stationary and no_fault and localization_ok:
    return PASS(metrics)
else:
    return FAIL(metrics)
```

---

## 8. 常见 false positive 与对应防护

### 8.1 API 返回成功，但机器人没有动

可能原因：

- DDS domain conflict。
- 网络接口错，例如应该用 `eth0` 却用了别的 interface。
- 机器人模式不对。
- deadman timeout。
- 低电量保护。
- 内置运动服务与低层控制冲突。

防护：

- 检查状态 topic 是否新鲜。
- 检查 `SportmodeState.mode/gait_type/velocity`。
- 检查 `LowState.motor_state[].q/dq`。
- 检查 command stream rate。
- 检查 service list / current mode。

---

### 8.2 Nav2 succeeded，但物理位置不对

可能原因：

- map 错。
- initial pose 错。
- odom 漂移。
- TF frame 混乱。
- 定位跳变。
- goal tolerance 太宽。

防护：

- action succeeded 后再检查最终 pose。
- 使用 `map->base_link` 而不是错 frame。
- 检查定位 covariance / scan matching 质量。
- 在关键点放 AprilTag / docking marker / 外部定位。
- 对比 `SportmodeState.position`、`/odom`、外部 pose。

---

### 8.3 机器人走到附近但不停稳

可能原因：

- goal tolerance 太小导致抖动。
- yaw tolerance 太严格。
- controller 参数不适合四足机器人。
- 地面打滑。

防护：

- 加 `settle_time`。
- 同时检查速度阈值。
- 对 yaw tolerance 不要盲目设太小。
- 记录最后 2 秒轨迹，判断是否 oscillation。

---

### 8.4 里程计显示到达，但真实位置没到

可能原因：

- 纯本体 odom 漂移。
- LiDAR/视觉退化。
- 地面打滑。
- 楼梯、坡面、复杂地形导致 2D odom 不可靠。

防护：

- 关键任务使用外部真值。
- 做闭环误差测试：走正方形/往返，看回到起点误差。
- 使用 SLAM/ICP/AprilTag/mocap 融合。
- 对 odom jump 设置异常检测。

---

## 9. 推荐测试矩阵

| 测试 | 目的 | 成功指标 |
|---|---|---|
| 站立/趴下/恢复站立 | 验证特殊动作 | body_height、IMU、foot_force、mode 稳定 |
| 原地旋转 30°/90° | 验证 yaw 控制 | yaw error、yaw_rate stop、无抖动 |
| 前进 0.5m/1.0m | 验证短距离速度控制 | 实际位移、速度跟踪、停止误差 |
| 方形路径 | 验证 odom 漂移 | 回到起点误差、路径偏差 |
| Nav2 单目标 | 验证导航到位 | action success + final pose + settle |
| 多 waypoint | 验证顺序执行 | 每个 waypoint 通过，顺序正确 |
| 障碍物绕行 | 验证规划与安全 | 无碰撞，progress 正常 |
| 通信中断 | 验证 deadman | 超时自动停，恢复后可控 |
| 低电量 | 验证保护 | 不继续任务，结果标记 fail/safe |
| 错误 initial pose | 验证误定位防护 | 能检测异常而不是盲目执行 |
| 地图错位 | 验证地图一致性 | 能阻止错误导航或报警 |

---

## 10. 最小可落地方案

如果你现在要尽快做一个可用版本，建议按下面顺序实现。

### 第一步：先做记录器

记录每条命令和状态：

```text
command_id
task_type
target
t_start
t_end
api_return
action_status
final_pose
final_velocity
final_error
fault_flags
bag_path
```

### 第二步：实现通用 pose verifier

输入：

```text
goal_pose
current_pose
current_velocity
state_age
fault_flags
```

输出：

```text
PASS / FAIL / UNKNOWN
metrics
reason
```

### 第三步：接入 Unitree 状态

至少订阅：

```text
/sportmodestate
/lowstate
/odom
/tf
/cmd_vel
```

没有 `/odom` 就先用 `SportmodeState.position` 做短期验证，但要标记为低可信度；长期建议接 SLAM/RTAB-Map/Inekf/外部定位。

### 第四步：接入 Nav2 action

Nav2 成功后，再调用 pose verifier。

### 第五步：增加外部真值

关键任务至少选一种：

- AprilTag
- UWB
- motion capture
- LiDAR ICP
- 人工标定基准点
- 工位 docking marker

---

## 11. 推荐成功判定模板

### 11.1 到点任务

```text
PASS if:
  command_accepted == true
  AND action_result in {SUCCEEDED, CUSTOM_DONE}
  AND latest_state_age < 0.3s
  AND latest_odom_age < 0.3s
  AND tf(map, base_link) available
  AND xy_error < 0.20m
  AND yaw_error < 0.25rad
  AND linear_speed < 0.05m/s
  AND abs(yaw_rate) < 0.05rad/s
  AND all above holds for 1.0s
  AND sport_error_code == 0
  AND no motor lost / low battery / overheat
  AND optional external marker check passes
```

### 11.2 速度移动任务

```text
PASS if:
  command_stream_rate >= required_rate
  AND no deadman timeout
  AND mean velocity tracking error < threshold
  AND actual displacement within tolerance
  AND stop command sent
  AND final speed < stop threshold for settle_time
  AND no fault
```

### 11.3 关节动作任务

```text
PASS if:
  max_abs(q_actual - q_target) < q_tol
  AND max_abs(dq_actual) < dq_stop_tol
  AND required contact pattern observed
  AND condition holds for settle_time
  AND no motor lost / overheat / power fault
```

### 11.4 任务语义

```text
PASS if:
  motion_success == true
  AND semantic_postcondition == true
```

例如：

- 到达巡检点 + 成功识别目标设备。
- 到达门口 + 门状态传感器显示已打开。
- 抓取动作完成 + 物体仍在夹爪中。

---

## 12. 最终建议

你可以把验证分为三个版本逐步做：

### V1：基础版

- 订阅 `/sportmodestate`、`/lowstate`。
- 记录命令与状态。
- 判断速度、位置、模式、错误码。
- 支持简单“到点/停稳”。

### V2：ROS2/Nav2 版

- 接入 `/odom`、`/tf`、`/cmd_vel`、Nav2 action feedback/result。
- 实现 `GoalVerifier`。
- 录 rosbag。
- 检测 TF/odom stale、Nav2 no progress、zero cmd_vel。

### V3：高可信任务版

- 接入外部真值或 semantic sensors。
- 每个任务定义后置条件。
- 自动生成评估报告。
- 多次重复测试，统计成功率、误差均值、方差、失败原因。

最终你应让系统输出类似：

```text
任务 cmd_001：PASS
证据：
- Nav2 result: SUCCEEDED
- final xy error: 0.08 m
- final yaw error: 0.11 rad
- final speed: 0.02 m/s
- settle: 1.2 s
- lowstate: no lost motor, battery ok
- state age max: 0.05 s
- external marker: detected, error 0.06 m
```

而不是：

```text
任务完成：true
```

---

## 13. 参考链接

1. Unitree `unitree_ros2`  
   https://github.com/unitreerobotics/unitree_ros2

2. Unitree `unitree_sdk2`  
   https://github.com/unitreerobotics/unitree_sdk2

3. Unitree `unitree_sdk2_python`  
   https://github.com/unitreerobotics/unitree_sdk2_python

4. Unitree `unitree_mujoco`  
   https://github.com/unitreerobotics/unitree_mujoco

5. Unitree 官方开发文档：Basic Services  
   https://support.unitree.com/home/en/developer/Basic_services

6. Unitree 官方开发文档：High Level Sports Service  
   https://support.unitree.com/home/en/developer/sports_services

7. Unitree 官方开发文档：SLAM and Navigation Services Interface  
   https://support.unitree.com/home/en/developer/SLAM%20and%20Navigation_service

8. `snt-arg/unitree_ros` Go1 ROS2 Driver  
   https://github.com/snt-arg/unitree_ros

9. `inria-paris-robotics-lab/go2_odometry`  
   https://github.com/inria-paris-robotics-lab/go2_odometry

10. `YibinWu/leg-odometry`  
    https://github.com/YibinWu/leg-odometry

11. `Unitree-Go2-Robot/go2_robot`  
    https://github.com/Unitree-Go2-Robot/go2_robot

12. `grasp-lyrl/go2_ros2_webrtc_sdk`  
    https://github.com/grasp-lyrl/go2_ros2_webrtc_sdk

13. `Sayantani-Bhattacharya/unitree_go2_nav`  
    https://github.com/Sayantani-Bhattacharya/unitree_go2_nav

14. `NayiemW/biscuit-movements-unitree-go2`  
    https://github.com/NayiemW/biscuit-movements-unitree-go2

15. Nav2 SimpleGoalChecker  
    https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_goal_checker.html

16. Nav2 SimpleProgressChecker  
    https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_progress_checker.html

17. Nav2 FollowPath action  
    https://docs.ros.org/en/iron/p/nav2_msgs/interfaces/action/FollowPath.html

18. ROS 2 Actions design  
    https://design.ros2.org/articles/actions.html

19. `Unitree-Go2-Robot/go2_robot` odom frame issue example  
    https://github.com/Unitree-Go2-Robot/go2_robot/issues/23

20. Unitree Go2 navigation / odometry related public issue examples  
    https://github.com/dfl-rlab/dddmr_navigation/issues/30
