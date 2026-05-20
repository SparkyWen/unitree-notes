# Unitree G1 23-DOF 机器人执行验证方案（联网调研版）

> 目标：判断 Unitree G1 23 关节机器人是否真正执行了你的指令、动作或任务，并且是否到达了对应的位置或状态。
>
> 结论先行：**不要把 SDK/API 返回码、动作函数执行完、或者发送命令成功当作任务完成。** 对 G1 23-DOF，应该建立一个“分层验证器”：
>
> **指令已发送 → 状态反馈新鲜 → 机器人模式正确 → 关节/底盘/末端执行器开始响应 → 误差收敛 → 稳定保持 → 安全状态正常 → 任务语义后置条件成立。**

---

## 1. 联网调研得到的关键事实

### 1.1 G1 23-DOF 的关节结构不是“0 到 22 连续电机”

Unitree 官方 `unitree_ros/robots/g1_description` README 中给出的 G1 机型表显示：

- `g1_23dof_mode_10`：`mode_machine = 10`，`dof#leg = 6*2`，`dof#waist = 1`，`dof#arm = 5*2`。
- `g1_23dof_rev_1_0`：`mode_machine = 4`，同样是 `6*2` 腿、`1` 腰、`5*2` 手臂。
- 29-DOF 版本才是 `6*2` 腿、`3` 腰、`7*2` 手臂。
- 文档还提示可以在 Unitree App 的 `Device → Data → Robot → Machine Type` 查看机器人的 `mode_machine`。

来源：Unitree ROS G1 description README  
https://github.com/unitreerobotics/unitree_ros/blob/master/robots/g1_description/README.md

这意味着 G1 23-DOF 验证时应使用 **active joint mask**，不能简单把 `motor_state[0:23]` 当作 23 个可控关节。

---

### 1.2 23-DOF 版本缺少 wrist pitch/yaw，只保留 forearm/wrist roll

Unitree 相关社区 issue 中有人记录了 G1 EDU 23-DOF + Brainco Revo2 手的配置，明确指出：

- G1 23-DOF 没有 wrist pitch / wrist yaw。
- 使用 forearm roll。
- 为兼容某些 SDK/策略，仍可能保留 phantom wrist slots。

来源：Unitree `unifolm-world-model-action` issue #46  
https://github.com/unitreerobotics/unifolm-world-model-action/issues/46

对验证器的影响：

- 你的 evaluator 应只检查真实存在的 active joints。
- 如果某些上层策略保留了 phantom slots，不要把它们计入“到达失败”。
- 但要记录 phantom command 是否被错误地下发到实际硬件索引。

---

### 1.3 G1/H1-2 使用 `unitree_hg` IDL；`rt/lowstate` 是核心反馈通道

Unitree MuJoCo 仓库说明：

- `unitree_mujoco` 支持 `LowCmd`、`LowState`、`SportModeState`、`IMUState`。
- `LowCmd` 是电机控制命令。
- `LowState` 是电机状态信息。
- `SportModeState` 提供机器人位置和速度数据。
- G1 有 `rt/secondary_imu` 的 torso IMU 状态。
- G1 和 H1-2 使用 `unitree_hg` IDL。
- 实物机器人上，如果关闭内置运动控制服务，`SportModeState` 可能不可读；仿真中保留它用于分析控制程序。

来源：Unitree MuJoCo README  
https://github.com/unitreerobotics/unitree_mujoco

对验证器的影响：

- 最基础验证必须订阅 `rt/lowstate`。
- 做 base pose / velocity 评估时，可以使用 `SportModeState` / odom 类消息，但不能把它当作唯一真值。
- 若做低层控制，关闭运动控制服务后，高层状态源可能缺失；此时必须依赖 `LowState`、IMU、外部定位或自己的状态估计。

---

### 1.4 官方 G1 arm SDK 示例本身就是“命令 + 反馈”的闭环结构

Unitree `g1_arm7_sdk_dds_example.cpp` 中：

- 发布 `LowCmd_` 到 `rt/arm_sdk`。
- 订阅 `LowState_` 到 `rt/lowstate`。
- 使用 `state_msg.motor_state().at(joint).q()` 读取当前关节位置。
- 以 `control_dt = 0.02f` 进行周期控制。
- 通过 `msg.motor_cmd().at(joint).q/dq/kp/kd/tau` 写入目标角、速度、刚度、阻尼、前馈力矩。
- 先读取当前关节位置，再平滑过渡到目标位置。

来源：Unitree SDK2 G1 arm example  
https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/high_level/g1_arm7_sdk_dds_example.cpp

对验证器的影响：

- 发送目标角后，应从 `LowState.motor_state[i].q` 反向确认实际角度。
- 检查 `q` 不够，还要检查 `dq` 是否接近 0、是否在目标附近保持稳定。
- 对机械臂动作，建议记录 `q_cmd, q_meas, dq_meas, tau_est` 的时间序列，而不是只看最终一帧。

---

### 1.5 `rt/arm_sdk` 与运动控制模式混合时，真正执行的命令会受 weight 影响

Unitree `xr_teleoperate` Wiki 的 Motion 页面说明：

- 在 motion control mode 下，下肢由运动控制程序控制，上肢可以通过 DDS 接口控制。
- arm SDK 命令发送到 `rt/arm_sdk`。
- `motor_cmd` 中某个 not-used joint 的 `q` 被用作 transition weight。
- 可以粗略理解为：

```text
实际双臂命令 = motion_control_command * (1 - weight) + rt/arm_sdk_user_command * weight
```

- 如果用户命令与当前 motion control command 差距大，突然把 weight 设为 1 可能导致手臂高速运动，因此推荐逐渐调整 weight。

来源：Unitree `xr_teleoperate` Wiki Motion  
https://github.com/unitreerobotics/xr_teleoperate/wiki/Motion

对验证器的影响：

- 只比较你发出的 `arm_sdk` 目标和反馈是不够的。你还要知道当时 `weight` 是否为 1。
- 如果 `weight < 1`，实际目标是混合目标，不能用用户目标直接判失败。
- 验证器应记录并检查 weight ramp 是否按预期变化。

---

### 1.6 公开 issue 显示：API 返回成功不等于机器人真的动了

Unitree SDK2 Python issue #138 中，有用户调用 G1 `SetStandHeight`，返回 `code=0`，但实物机器人没有物理响应。issue 中还给出代码片段，显示 `SetStandHeight` 调用返回了成功码，但机器人高度没有变化。

来源：Unitree SDK2 Python issue #138  
https://github.com/unitreerobotics/unitree_sdk2_python/issues/138

对验证器的影响：

- **返回码只能作为“服务收到请求”的证据，不能作为“物理动作完成”的证据。**
- 每个高层 API 都必须配套状态后验检查。

---

### 1.7 公开 issue 显示：部分特殊动作可能通过遥控器有效，但 API 不一定有效

Unitree SDK2 Python issue #42 中，有用户报告 `WaveHand` 和 `ShakeHand` 通过遥控器可以触发，但 Python/C++/ROS2 脚本触发无效；ROS2 `/api/loco/request` 得到 `3203 API not implemented on server`。

来源：Unitree SDK2 Python issue #42  
https://github.com/unitreerobotics/unitree_sdk2_python/issues/42

对验证器的影响：

- 对 `WaveHand`、`ShakeHand`、`StandHeight` 这类高层 task，不能只看 task API 返回。
- 应验证关节轨迹是否出现预期运动模式。
- 如果动作没有明确定义目标角，应该用“动作模板/时序特征”来判定，例如肩关节/肘关节是否在 1–3 秒内出现预期幅度和方向的运动。

---

### 1.8 G1 odometry 可能依赖足端接触/腿部运动，悬空时不一定反映真实移动

Unitree SDK2 Python issue #135 中，有用户反馈：

- 订阅 `rt/odommodestate` 可获得 base center 的速度。
- 当 G1 被吊起并被外力推动时，速度信号不变化。
- 当 G1 在地面行走时，速度信号能反映移动。
- 用户推测 odometry 可能高度依赖腿部运动学 / 接触传感 / 编码器融合。

来源：Unitree SDK2 Python issue #135  
https://github.com/unitreerobotics/unitree_sdk2_python/issues/135

对验证器的影响：

- 对“是否到达空间位置”，**内置 odom 不能作为唯一真值**。
- 室内导航建议使用外部定位或二级定位源，例如 Vicon、AprilTag、LiDAR SLAM、视觉 SLAM、UWB、地面标定点等。
- 如果只用内置 odom，要明确它是“机器人自认为的位置”，不是独立 ground truth。

---

### 1.9 同时控制手臂和行走会影响平衡，必须把稳定性加入任务成功判据

Unitree SDK2 Python issue #146 中，有用户在 G1 上尝试边用 gamepad 行走边通过 arm SDK 控制手臂，结果机器人弯腰、平衡失败、踏步沉重/不稳定。

来源：Unitree SDK2 Python issue #146  
https://github.com/unitreerobotics/unitree_sdk2_python/issues/146

对验证器的影响：

- “手臂到达目标角”不代表任务成功；如果 torso pitch/roll 过大、步态不稳定、足端接触异常，也要判失败。
- 对全身动作，要同时验证：关节目标、base 姿态、足底接触、IMU 姿态、速度、力矩/电流/温度等。

---

### 1.10 社区/开源项目常用 sim-first 与多传感器验证

LeRobot 文档显示 G1 同时支持 23-DOF 和 29-DOF，可进行 teleoperation、训练、仿真和实物测试，并给出了 MuJoCo sim、物理机器人连接、摄像头、dataset record、rollout 等工作流。

来源：Hugging Face LeRobot Unitree G1 文档  
https://huggingface.co/docs/lerobot/unitree_g1

Robotics-Ark 的 `ark_unitree_g1` 项目也采用 SDK2 Python、DDS topics、NIC/domain 配置、真实机器人与 PyBullet/MuJoCo 仿真两套运行模式，并用 Pinocchio IK 做机械臂控制。

来源：Robotics-Ark `ark_unitree_g1`  
https://github.com/Robotics-Ark/ark_unitree_g1

对验证器的影响：

- 建议先在 MuJoCo / PyBullet / Isaac 中跑同一套 evaluator。
- 实物上保存相同格式的 log，做 sim-vs-real 对比。
- 对末端位姿，使用 URDF + Pinocchio/KDL 做 FK，结合视觉/外部定位做校验。

---

## 2. G1 23-DOF 的建议 active joint mask

> 注意：这里是基于公开 G1 29-DOF JointIndex、Unitree ROS 23-DOF 结构表、以及“23-DOF 无 wrist pitch/yaw”的公开信息整理出的工程建议。最终请以你们机器的 `mode_machine`、URDF/MJCF、`LowState` 实测反馈为准。

### 2.1 DDS/hardware index 层面的建议 active joints

| 类别 | 关节 | 建议 DDS index | 说明 |
|---|---:|---:|---|
| 左腿 | left hip pitch | 0 | active |
| 左腿 | left hip roll | 1 | active |
| 左腿 | left hip yaw | 2 | active |
| 左腿 | left knee | 3 | active |
| 左腿 | left ankle pitch | 4 | active |
| 左腿 | left ankle roll | 5 | active |
| 右腿 | right hip pitch | 6 | active |
| 右腿 | right hip roll | 7 | active |
| 右腿 | right hip yaw | 8 | active |
| 右腿 | right knee | 9 | active |
| 右腿 | right ankle pitch | 10 | active |
| 右腿 | right ankle roll | 11 | active |
| 腰 | waist yaw | 12 | active，23-DOF 只有 1 腰 |
| 腰 | waist roll | 13 | 23-DOF 通常 inactive / absent |
| 腰 | waist pitch | 14 | 23-DOF 通常 inactive / absent |
| 左臂 | left shoulder pitch | 15 | active |
| 左臂 | left shoulder roll | 16 | active |
| 左臂 | left shoulder yaw | 17 | active |
| 左臂 | left elbow | 18 | active |
| 左臂 | left wrist / forearm roll | 19 | active |
| 左臂 | left wrist pitch | 20 | 23-DOF inactive / phantom |
| 左臂 | left wrist yaw | 21 | 23-DOF inactive / phantom |
| 右臂 | right shoulder pitch | 22 | active |
| 右臂 | right shoulder roll | 23 | active |
| 右臂 | right shoulder yaw | 24 | active |
| 右臂 | right elbow | 25 | active |
| 右臂 | right wrist / forearm roll | 26 | active |
| 右臂 | right wrist pitch | 27 | 23-DOF inactive / phantom |
| 右臂 | right wrist yaw | 28 | 23-DOF inactive / phantom |
| SDK placeholder | not used / weight | 29+ | 可能用于 weight / placeholder，不作为物理 joint 验证 |

建议在代码中显式声明：

```python
G1_23_ACTIVE = {
    # legs
    0: "L_HIP_PITCH", 1: "L_HIP_ROLL", 2: "L_HIP_YAW", 3: "L_KNEE",
    4: "L_ANKLE_PITCH", 5: "L_ANKLE_ROLL",
    6: "R_HIP_PITCH", 7: "R_HIP_ROLL", 8: "R_HIP_YAW", 9: "R_KNEE",
    10: "R_ANKLE_PITCH", 11: "R_ANKLE_ROLL",
    # waist
    12: "WAIST_YAW",
    # left arm: 5 DOF
    15: "L_SHOULDER_PITCH", 16: "L_SHOULDER_ROLL", 17: "L_SHOULDER_YAW",
    18: "L_ELBOW", 19: "L_WRIST_ROLL",
    # right arm: 5 DOF
    22: "R_SHOULDER_PITCH", 23: "R_SHOULDER_ROLL", 24: "R_SHOULDER_YAW",
    25: "R_ELBOW", 26: "R_WRIST_ROLL",
}

G1_23_INACTIVE_OR_PHANTOM = {
    13: "WAIST_ROLL", 14: "WAIST_PITCH",
    20: "L_WRIST_PITCH", 21: "L_WRIST_YAW",
    27: "R_WRIST_PITCH", 28: "R_WRIST_YAW",
}
```

### 2.2 验证 active mask 的实机方法

上电进入安全姿态后，对每个 candidate index 做极小幅度、低刚度、短时的单关节测试，例如 `±0.03 rad`，并记录：

- `LowState.motor_state[i].q` 是否变化。
- 相邻或其他 joint 是否意外变化。
- IMU 姿态是否异常。
- 是否出现报错、保护、力矩异常。

通过该实验生成你们自己的 `active_joint_map.yaml`，不要完全依赖网上资料。

---

## 3. 验证器总体架构

### 3.1 建议模块

```text
Command Sender
  ├── low-level joint cmd: rt/lowcmd or rt/arm_sdk
  ├── high-level loco cmd: LocoClient / API request
  └── task cmd: wave, shake, stand, navigation, pick/place

State Recorder
  ├── rt/lowstate: joint q/dq/tau_est, IMU, battery, etc.
  ├── rt/secondary_imu: torso IMU if available
  ├── rt/odommodestate / SportModeState: base pose/velocity if available
  ├── external localization: Vicon / AprilTag / SLAM / UWB / LiDAR
  ├── cameras: head/wrist/global camera
  └── optional contact/force/tactile/hand state

Evaluator
  ├── precondition checker
  ├── command acknowledgement checker
  ├── execution-start checker
  ├── convergence checker
  ├── stability checker
  ├── safety checker
  ├── semantic post-condition checker
  └── log/report generator
```

### 3.2 成功判定不要是单一布尔值

建议把每次任务的结果分成：

```yaml
result:
  ack_ok: true
  state_fresh_ok: true
  mode_ok: true
  motion_started_ok: true
  final_joint_ok: true
  final_base_pose_ok: true
  final_ee_pose_ok: true
  stability_ok: true
  safety_ok: true
  semantic_task_ok: true
  overall_success: true
  failure_reason: null
```

如果失败，要能回答：

- 是命令没发出去？
- 是服务返回了但机器人没动？
- 是动了但没到？
- 是到了但没保持住？
- 是关节到了但 base 姿态危险？
- 是机器人到了位置但任务对象没被拿起？

---

## 4. 不同任务类型的验证方法

## 4.1 单关节 / 多关节目标验证

适用于：手臂关节控制、腰 yaw、debug 模式低层控制、姿态动作。

### 判据

对 active joint 集合 `J`：

```text
e_q[i] = wrap_to_pi(q_measured[i] - q_target[i])
e_dq[i] = dq_measured[i]
```

成功条件：

```text
max_i |e_q[i]| < q_tol[i]
max_i |dq_measured[i]| < dq_tol[i]
condition holds for T_hold seconds
no safety violation
```

### 推荐阈值

| 类别 | q_tol 初始值 | dq_tol 初始值 | hold time |
|---|---:|---:|---:|
| 手臂 shoulder/elbow | 0.03–0.06 rad | 0.08–0.15 rad/s | 0.3–0.8 s |
| wrist / forearm roll | 0.05–0.08 rad | 0.10–0.20 rad/s | 0.3–0.8 s |
| 腰 yaw | 0.03–0.07 rad | 0.05–0.15 rad/s | 0.5–1.0 s |
| 腿部关节 | 0.05–0.10 rad | 0.10–0.25 rad/s | 0.5–1.0 s |

### 额外检查

- `LowState` 更新时间不能超过 `100 ms`，更严格可设为 `50 ms`。
- 如果命令控制频率是 50 Hz，连续丢 3 帧就要进入 warning。
- 如果 `q` 接近目标但 `dq` 很大，说明只是经过目标，不算到达。
- 如果到达后 0.5 秒内又离开目标，也不算完成。

---

## 4.2 手臂末端位姿验证

适用于：机械臂 IK、抓取前定位、放置动作。

### 数据源

- `LowState.motor_state[i].q`：真实关节角。
- G1 23-DOF URDF/MJCF：做 forward kinematics。
- 可选：腕部相机、头部相机、AprilTag、外部相机、Vicon。

### 判据

```text
T_base_to_ee_measured = FK(q_measured)
position_error = ||p_ee_measured - p_ee_target||
rotation_error = angle(R_target^T R_measured)
```

成功条件：

```text
position_error < 0.02–0.05 m
rotation_error < 5–10 deg
joint_velocity small
held for 0.3–1.0 s
object/contact condition satisfied if manipulation task
```

### 重要说明

G1 23-DOF 单臂只有 5 DOF，末端位姿不一定能完整约束 6D pose。对 5-DOF 手臂，建议把 IK/验证目标拆成：

- 末端位置 `x, y, z`。
- 关键方向向量，例如 gripper approach direction。
- 不强制某些不可控方向。

---

## 4.3 高层站立 / 下蹲 / 身高 / wave / shake 动作验证

适用于 `LocoClient` / 高层 task。

### 为什么不能只看返回码

公开 issue #138 已经说明 G1 `SetStandHeight` 可以返回 `code=0` 但没有物理响应。issue #42 也说明特殊动作通过遥控器有效，但 API 调用不一定实现或不一定触发。

### 建议判据

以 `StandUp` 为例：

```text
ack_ok: LocoClient return code == 0
state_change_ok: torso height / knee / hip / ankle q trajectory changed as expected
upright_ok: abs(roll) < roll_tol and abs(pitch) < pitch_tol
stable_ok: base angular velocity small, joint velocities small
hold_ok: stable for 1.0 s
```

以 `WaveHand` 为例：

```text
ack_ok: task API accepted
motion_pattern_ok:
  shoulder_roll or shoulder_pitch amplitude > threshold
  elbow motion amplitude > threshold
  periodic / phased movement detected in 1–5 s
safety_ok:
  torso pitch/roll within limits
  no large unexpected leg movement
```

---

## 4.4 速度控制 / 行走验证

适用于：`Move(vx, vy, vyaw)`、gamepad、RL locomotion、导航底层速度。

### 判据

不要只看机器人最后位置。速度控制应该验证：

```text
start_response_ok: command 后 0.2–0.5 s 内观测到速度变化
tracking_ok: measured_velocity 与 command_velocity 的窗口平均误差在阈值内
heading_ok: yaw_rate 或 yaw angle 符合预期
stop_ok: StopMove 后速度下降到接近 0
stability_ok: torso roll/pitch、角速度、足底接触正常
```

### 内置 odom 的注意事项

如果只用 `rt/odommodestate` 或类似里程计，验证的是“机器人估计自己在动”。公开 issue #135 显示，悬空推动时 odom 可能不变；所以严格验证到达物理位置时，需要外部定位或视觉/SLAM 交叉验证。

### 推荐速度阈值

| 指标 | 推荐初始阈值 |
|---|---:|
| vx 平均误差 | 0.05–0.15 m/s |
| vy 平均误差 | 0.05–0.15 m/s |
| yaw rate 误差 | 0.05–0.15 rad/s |
| StopMove 后线速度 | < 0.03–0.08 m/s |
| StopMove 后角速度 | < 0.03–0.08 rad/s |
| 稳定保持 | 0.5–1.0 s |

---

## 4.5 导航到指定位置验证

适用于：让 G1 到达世界坐标 `(x, y, yaw)`。

### 不建议

```text
API 返回成功 => 到达
内部 odom 到了 => 物理真的到了
```

### 推荐多源判据

```text
pose_estimator_1: robot internal odom / SportModeState
pose_estimator_2: external localization / SLAM / AprilTag / Vicon
pose_estimator_3: visual marker / map alignment if available
```

成功条件：

```text
position_error_external < 0.05–0.15 m
orientation_error_external < 5–10 deg
linear_velocity < 0.03–0.08 m/s
angular_velocity < 0.03–0.08 rad/s
stable for 1.0 s
no obstacle/collision/contact anomaly
```

如果没有外部定位，至少保存：

- 内置 odom。
- IMU。
- 足端/接触状态。
- 头部相机或环境相机画面。
- 人工标定点观测。

---

## 4.6 抓取 / 放置 / 交互任务验证

“关节到达”不是抓取成功。完整判据应包含语义后置条件：

### 抓取成功

```text
pre_grasp_ee_pose_ok
finger_or_gripper_closed_ok
object_detected_in_hand_ok
lift_test_ok: 抬起 5–10 cm 后物体仍随手移动
force/contact_ok if available
```

### 放置成功

```text
ee_pose_near_place_area_ok
object_released_ok
object_final_pose_ok from camera/AprilTag/depth
hand_open_ok
robot_retracted_ok
```

### 推荐传感器

- wrist camera / head camera。
- AprilTag / ArUco marker。
- depth camera。
- gripper/hand joint state。
- force/contact/tactile if available。

---

## 5. 具体实现：G1 23-DOF evaluator 代码骨架

> 下面是可落地的 Python 思路，不是完整可直接运行版。你们需要按当前 SDK2 Python 版本、topic 类型、网络接口和实际 hand/arm 配置调整。

### 5.1 状态缓存

```python
import time
import math
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence

import numpy as np

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_ as hg_LowState

G1_23_ACTIVE = {
    0: "L_HIP_PITCH", 1: "L_HIP_ROLL", 2: "L_HIP_YAW", 3: "L_KNEE",
    4: "L_ANKLE_PITCH", 5: "L_ANKLE_ROLL",
    6: "R_HIP_PITCH", 7: "R_HIP_ROLL", 8: "R_HIP_YAW", 9: "R_KNEE",
    10: "R_ANKLE_PITCH", 11: "R_ANKLE_ROLL",
    12: "WAIST_YAW",
    15: "L_SHOULDER_PITCH", 16: "L_SHOULDER_ROLL", 17: "L_SHOULDER_YAW",
    18: "L_ELBOW", 19: "L_WRIST_ROLL",
    22: "R_SHOULDER_PITCH", 23: "R_SHOULDER_ROLL", 24: "R_SHOULDER_YAW",
    25: "R_ELBOW", 26: "R_WRIST_ROLL",
}

@dataclass
class JointSnapshot:
    t: float
    q: Dict[int, float]
    dq: Dict[int, float]
    tau_est: Dict[int, float] = field(default_factory=dict)

class LowStateCache:
    def __init__(self):
        self._lock = threading.Lock()
        self._last_msg = None
        self._last_t = 0.0

    def update(self, msg):
        with self._lock:
            self._last_msg = msg
            self._last_t = time.monotonic()

    def snapshot(self, active_ids=G1_23_ACTIVE.keys()) -> Optional[JointSnapshot]:
        with self._lock:
            msg = self._last_msg
            t = self._last_t

        if msg is None:
            return None

        q, dq, tau_est = {}, {}, {}
        for i in active_ids:
            ms = msg.motor_state[i]
            q[i] = float(ms.q)
            dq[i] = float(ms.dq)
            if hasattr(ms, "tau_est"):
                tau_est[i] = float(ms.tau_est)
        return JointSnapshot(t=t, q=q, dq=dq, tau_est=tau_est)

    def is_fresh(self, max_age_s=0.10) -> bool:
        with self._lock:
            return self._last_msg is not None and (time.monotonic() - self._last_t) <= max_age_s

def start_lowstate_subscriber(network_interface: str) -> LowStateCache:
    ChannelFactoryInitialize(0, network_interface)
    cache = LowStateCache()
    sub = ChannelSubscriber("rt/lowstate", hg_LowState)
    sub.Init(lambda msg: cache.update(msg), 1)
    return cache
```

### 5.2 关节目标验证

```python
def angle_diff(a: float, b: float) -> float:
    """Return wrapped angle difference a-b in radians."""
    d = a - b
    return math.atan2(math.sin(d), math.cos(d))

@dataclass
class JointEvalResult:
    success: bool
    max_q_err: float
    max_dq: float
    per_joint_q_err: Dict[int, float]
    reason: str

def evaluate_joint_goal(
    cache: LowStateCache,
    target_q: Dict[int, float],
    q_tol: Dict[int, float] | float = 0.05,
    dq_tol: Dict[int, float] | float = 0.12,
    hold_s: float = 0.5,
    timeout_s: float = 5.0,
    sample_period_s: float = 0.02,
) -> JointEvalResult:
    start = time.monotonic()
    hold_start = None
    last_errs = {}
    last_max_q_err = float("inf")
    last_max_dq = float("inf")

    active_ids = list(target_q.keys())

    while time.monotonic() - start < timeout_s:
        if not cache.is_fresh(max_age_s=0.10):
            hold_start = None
            time.sleep(sample_period_s)
            continue

        snap = cache.snapshot(active_ids)
        if snap is None:
            time.sleep(sample_period_s)
            continue

        errs = {}
        ok = True
        max_q_err = 0.0
        max_dq = 0.0

        for i, q_des in target_q.items():
            e = abs(angle_diff(snap.q[i], q_des))
            v = abs(snap.dq[i])
            tol_i = q_tol[i] if isinstance(q_tol, dict) else q_tol
            vtol_i = dq_tol[i] if isinstance(dq_tol, dict) else dq_tol

            errs[i] = e
            max_q_err = max(max_q_err, e)
            max_dq = max(max_dq, v)
            if e > tol_i or v > vtol_i:
                ok = False

        last_errs = errs
        last_max_q_err = max_q_err
        last_max_dq = max_dq

        if ok:
            if hold_start is None:
                hold_start = time.monotonic()
            if time.monotonic() - hold_start >= hold_s:
                return JointEvalResult(
                    success=True,
                    max_q_err=max_q_err,
                    max_dq=max_dq,
                    per_joint_q_err=errs,
                    reason="joint target reached and held",
                )
        else:
            hold_start = None

        time.sleep(sample_period_s)

    return JointEvalResult(
        success=False,
        max_q_err=last_max_q_err,
        max_dq=last_max_dq,
        per_joint_q_err=last_errs,
        reason="timeout or unstable joint convergence",
    )
```

### 5.3 “开始执行”验证

很多 bug 是“返回成功但没有任何物理响应”。所以在等待最终到达前，先验证动作是否开始。

```python
def wait_for_joint_motion_start(
    cache: LowStateCache,
    watched_ids: Sequence[int],
    min_delta_rad: float = 0.02,
    timeout_s: float = 1.0,
) -> bool:
    snap0 = cache.snapshot(watched_ids)
    if snap0 is None:
        return False

    q0 = snap0.q
    start = time.monotonic()

    while time.monotonic() - start < timeout_s:
        snap = cache.snapshot(watched_ids)
        if snap is None:
            time.sleep(0.02)
            continue
        for i in watched_ids:
            if abs(angle_diff(snap.q[i], q0[i])) >= min_delta_rad:
                return True
        time.sleep(0.02)
    return False
```

### 5.4 高层动作的通用包装

```python
@dataclass
class TaskEvalReport:
    command_name: str
    ack_ok: bool
    state_fresh_ok: bool
    motion_started_ok: bool
    reached_ok: bool
    stable_ok: bool
    safety_ok: bool
    overall_success: bool
    reason: str
    metrics: dict = field(default_factory=dict)


def run_and_verify_joint_task(
    command_name: str,
    send_command_fn,
    cache: LowStateCache,
    target_q: Dict[int, float],
    watched_ids: Sequence[int],
    timeout_s: float = 5.0,
) -> TaskEvalReport:
    ack_code = send_command_fn()
    ack_ok = (ack_code == 0 or ack_code is True or ack_code is None)

    state_fresh_ok = cache.is_fresh()
    motion_started_ok = wait_for_joint_motion_start(cache, watched_ids, timeout_s=1.0)

    joint_result = evaluate_joint_goal(
        cache=cache,
        target_q=target_q,
        q_tol=0.05,
        dq_tol=0.12,
        hold_s=0.5,
        timeout_s=timeout_s,
    )

    # safety_ok 这里先简化；真实项目应检查 IMU、tau_est、电池、温度、急停、跌倒状态等。
    safety_ok = True
    stable_ok = joint_result.success and joint_result.max_dq < 0.12

    overall = ack_ok and state_fresh_ok and motion_started_ok and joint_result.success and stable_ok and safety_ok

    return TaskEvalReport(
        command_name=command_name,
        ack_ok=ack_ok,
        state_fresh_ok=state_fresh_ok,
        motion_started_ok=motion_started_ok,
        reached_ok=joint_result.success,
        stable_ok=stable_ok,
        safety_ok=safety_ok,
        overall_success=overall,
        reason=joint_result.reason,
        metrics={
            "ack_code": ack_code,
            "max_q_err": joint_result.max_q_err,
            "max_dq": joint_result.max_dq,
            "per_joint_q_err": joint_result.per_joint_q_err,
        },
    )
```

---

## 6. 安全检查必须单独成为一层

建议每个 evaluator 都输出 safety 层结果：

```yaml
safety:
  imu_roll_ok: true
  imu_pitch_ok: true
  angular_velocity_ok: true
  torque_ok: true
  joint_limit_ok: true
  velocity_limit_ok: true
  foot_contact_ok: true
  battery_ok: true
  state_fresh_ok: true
  emergency_stop_ok: true
```

### 推荐初始阈值

| 项目 | 初始阈值 |
|---|---:|
| torso roll | < 10–15 deg，动态动作可放宽 |
| torso pitch | < 10–15 deg，动态动作可放宽 |
| base angular velocity | < 0.5–1.0 rad/s，静止任务更严格 |
| joint over target | 不超过 joint limit 的 90–95% |
| command stale | >100 ms 无状态或命令断流即 warning |
| excessive torque | 用实测正常分布设阈值，例如 P95/P99 |
| foot contact mismatch | 行走时两脚接触模式与步态相矛盾即 warning |

---

## 7. 位置到达的 ground truth 层级

| 等级 | 数据源 | 能证明什么 | 局限 |
|---|---|---|---|
| L0 | API return code | 服务收到/处理了请求 | 不能证明物理运动 |
| L1 | `LowState.q/dq` | 关节实际角度/速度 | 不能证明世界位置 |
| L2 | 内置 odom / SportModeState | 机器人内部估计的 base pose/velocity | 可能依赖足端接触/腿运动；悬空/打滑有问题 |
| L3 | SLAM / LiDAR / visual odometry | 相对环境的位置 | 受地图、光照、特征、动态物体影响 |
| L4 | AprilTag / Vicon / motion capture / UWB | 独立外部定位 | 需要额外设备/标定 |
| L5 | 任务语义视觉/接触验证 | 对象是否真的被移动/抓取/放置 | 需要感知模型和场景标定 |

生产级验证建议至少使用：

```text
L1 + L2 + L3 或 L4 + L5
```

---

## 8. 建议落地流程

### 第 1 周：状态采集与 joint map 确认

- 订阅 `rt/lowstate`。
- 确认 `mode_machine`。
- 生成 G1 23 active joint mask。
- 单关节小幅测试，输出 `active_joint_map.yaml`。
- 记录 `q/dq/tau_est/imu/battery`。

### 第 2 周：关节动作 evaluator

- 实现 joint convergence checker。
- 实现 motion-start checker。
- 实现 hold-time checker。
- 实现 stale-state checker。
- 输出 JSON/Markdown 报告。

### 第 3 周：高层动作 evaluator

- 封装 `LocoClient` 返回码 + 后验检查。
- 对 `StandUp/Squat/Sit/StopMove/Move/Wave/Shake` 写动作模板。
- 加入 IMU 稳定性和 safety 层。

### 第 4 周：空间位置 evaluator

- 接入 odom / SportModeState。
- 接入外部定位：AprilTag / Vicon / LiDAR SLAM / UWB 选一种。
- 建立 `target pose reached + velocity zero + hold` 判据。

### 第 5 周：任务语义 evaluator

- 抓取：视觉检测 + 手状态 + lift test。
- 放置：对象最终位置 + hand release + robot retract。
- 导航：目标区域 occupancy / marker / map pose。

---

## 9. 推荐日志格式

每次命令记录：

```json
{
  "task_id": "2026-05-20T10:20:30.123Z_pick_box_001",
  "robot_model": "Unitree G1",
  "dof": 23,
  "mode_machine": 10,
  "command": {
    "type": "joint_target",
    "target_q": {"15": 0.2, "16": 0.5, "18": 1.1},
    "sent_time_monotonic": 12345.67
  },
  "ack": {
    "ok": true,
    "code": 0
  },
  "state_quality": {
    "lowstate_fresh": true,
    "max_state_age_s": 0.018
  },
  "metrics": {
    "max_q_err_rad": 0.034,
    "max_dq_rad_s": 0.071,
    "hold_s": 0.52,
    "torso_pitch_deg": 2.1,
    "torso_roll_deg": -1.3
  },
  "verdict": {
    "motion_started_ok": true,
    "reached_ok": true,
    "stable_ok": true,
    "safety_ok": true,
    "semantic_ok": null,
    "overall_success": true
  }
}
```

---

## 10. 常见失败模式与诊断

| 现象 | 可能原因 | 验证器如何发现 |
|---|---|---|
| API 返回 0，但没动 | 模式不对、API 未实际生效、服务端未实现、机器人状态不满足动作前提 | `ack_ok=true` 但 `motion_started_ok=false` |
| 手臂目标到了但机器人不稳 | 手臂动作影响重心/腰/步态 | `joint_ok=true` 但 `imu/stability=false` |
| 机器人走了但没到目标 | 速度跟踪误差、打滑、odom 漂移 | base pose error / external localization error |
| 内置 odom 显示没动但实物动了 | odom 依赖足端/接触；悬空/外推不反映 | external localization 与 odom 不一致 |
| 手臂突然高速甩动 | `rt/arm_sdk` weight 突变，当前姿态与目标差距大 | weight ramp check failed / q jump too high |
| 23DOF 验证总失败 | 错把 phantom wrist/waist joints 纳入 active joints | active mask checker |
| 特殊动作无效 | 固件/API 版本不支持，遥控器可触发但 SDK 不可触发 | response code / no motion template detected |
| 低层和高层互相抢控制 | 没关闭高层服务，或 motion mode 与 debug mode 混用 | mode checker / command topic checker |

---

## 11. 我的建议：最终判定公式

对每条任务，使用下面的总判据：

```text
SUCCESS =
  ACK_OK
  AND STATE_FRESH_OK
  AND MODE_OK
  AND MOTION_STARTED_OK
  AND LOW_LEVEL_CONVERGED_OK
  AND TASK_LEVEL_REACHED_OK
  AND HOLD_STABLE_OK
  AND SAFETY_OK
  AND SEMANTIC_POSTCONDITION_OK
```

其中：

- `ACK_OK`：服务/API/发布器没有报错。
- `STATE_FRESH_OK`：`LowState` / odom / external localization 时间戳新鲜。
- `MODE_OK`：G1 当前 `mode_machine`、FSM、运动模式符合任务要求。
- `MOTION_STARTED_OK`：命令发出后，相关状态确实发生变化。
- `LOW_LEVEL_CONVERGED_OK`：关节角、速度、力矩/接触达到目标范围。
- `TASK_LEVEL_REACHED_OK`：base pose、末端 pose 或动作模板达到目标。
- `HOLD_STABLE_OK`：不是瞬间经过，而是稳定保持。
- `SAFETY_OK`：没有跌倒、失衡、过力矩、过限位、状态断流。
- `SEMANTIC_POSTCONDITION_OK`：如果任务是抓取/放置/导航/交互，验证真实语义结果。

---

## 12. 最低可行版本 MVP

如果你们现在要尽快做一个可用版本，我建议先做：

1. 订阅 `rt/lowstate`。
2. 写死或读取 `G1_23_ACTIVE`。
3. 每次命令保存 `q_cmd`、`timestamp`、`task_id`。
4. 等待 `motion_started_ok`。
5. 等待 `max_q_err < 0.05 rad` 且 `max_dq < 0.12 rad/s` 持续 `0.5 s`。
6. 对 walking/navigation 再加 external AprilTag / LiDAR SLAM / Vicon 中任意一种。
7. 输出 JSON 报告。

这样你们能马上避免最危险的误判：

```text
函数调用成功 ≠ 机器人真的执行成功
```

---

## 13. 参考资料

1. Unitree ROS G1 description README  
   https://github.com/unitreerobotics/unitree_ros/blob/master/robots/g1_description/README.md
2. Unitree SDK2 G1 arm DDS example  
   https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/g1/high_level/g1_arm7_sdk_dds_example.cpp
3. Unitree MuJoCo README  
   https://github.com/unitreerobotics/unitree_mujoco
4. Unitree `xr_teleoperate` Motion Wiki  
   https://github.com/unitreerobotics/xr_teleoperate/wiki/Motion
5. Unitree SDK2 Python issue #138: `SetStandHeight` returns success but no physical response  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/138
6. Unitree SDK2 Python issue #42: `WaveHand` / `ShakeHand` API issue  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/42
7. Unitree SDK2 Python issue #135: G1 odometry / body velocity question  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/135
8. Unitree SDK2 Python issue #146: arm SDK while walking causes balance issue  
   https://github.com/unitreerobotics/unitree_sdk2_python/issues/146
9. Hugging Face LeRobot Unitree G1 docs  
   https://huggingface.co/docs/lerobot/unitree_g1
10. Robotics-Ark `ark_unitree_g1`  
    https://github.com/Robotics-Ark/ark_unitree_g1
11. Unitree `unifolm-world-model-action` issue #46: G1 23-DOF + Brainco hand setup  
    https://github.com/unitreerobotics/unifolm-world-model-action/issues/46
