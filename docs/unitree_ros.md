# `unitree_ros` 仓库完全详解

> 路径：`/home/helios/unitree/unitree-notes/unitree_ros/`
> 上游：<https://github.com/unitreerobotics/unitree_ros>
> 许可证：BSD‑3‑Clause（Copyright © 2016‑2022 Unitree Robotics）
> 子模块：`unitree_ros_to_real`（在 `.gitmodules` 声明，但实际内容并未拉取）

本文档面向需要"彻底吃透 `unitree_ros`"的开发者，目标是：①给出仓库**全量路径清单**；②把每一个**代码、配置、URDF/xacro/MJCF 文件**实现的功能说清楚；③补一份控制/仿真数据流的工作机制说明。

文中代码引用一律采用 `path:line_number` 格式，便于在 IDE 中跳转。

---

## 0. 仓库定位与一页式总览

`unitree_ros` 是 Unitree（宇树）官方的 **ROS 1 仿真支持包**，主要职责有三：

1. **机器人模型库**（`robots/<rname>_description`）：以 URDF / xacro / MJCF 形式提供 19 款机器人（四足 + 双足/人形 + 机械臂 + 灵巧手）的描述与可视化资源（mesh）。
2. **Gazebo 关节控制器**（`unitree_legged_control`）：实现一个 `controller_interface::Controller` 派生类 `UnitreeJointController`，把 Unitree 真机所用的 `MotorCmd { mode, q, dq, Kp, Kd, tau }` PD+前馈协议映射成 Gazebo 的 `EffortJointInterface`，让仿真复用真机控制接口。
3. **示例上层节点 + 仿真胶水**（`unitree_controller`、`unitree_gazebo`）：包含站立/位姿/外力施加示例节点、Gazebo world 文件、足端接触传感器与力可视化插件、把 `xacro→robot_description→spawn_model` 的 launch 文件接起来。

> ⚠️ README 明确说明：Gazebo 仿真**只能做底层关节控制**（torque/position/velocity），不提供高层步态。高层步态需走 `unitree_ros_to_real`（在真机上跑）。

文件量：1203 个文件（含 `.git` 之外）。其中 ROS C++ 源码极少（约 8 个 `.cpp/.h`，<1000 行），大头是 **122 份 URDF/xacro/SDF/MJCF + 233+ 份 STL/DAE/OBJ mesh 资产**。

---

## 1. 顶层目录一览

| 路径 | 类型 | 作用 |
|---|---|---|
| `.gitignore` | 配置 | 忽略 `.vscode/`、`unitree_guide/`、`*usd` 等局部临时产物。 |
| `.gitmodules` | 配置 | 声明子模块 `unitree_ros_to_real`（路径同名，远程仓库 URL）。在本工作副本中未实际 checkout。 |
| `LICENSE` | 文本 | BSD‑3‑Clause 许可证。 |
| `README.md` | 文档 | 仓库总览、依赖、build 步骤、各机器人列表、`normal.launch` / `unitree_servo` / `unitree_external_force` / `unitree_move_kinetic` / `z1.launch` 用法。 |
| `robots/` | 目录 | 19 个机器人 description 包 + 一份 `robots/README.md` 索引。 |
| `unitree_controller/` | ROS 包 | 上层控制示例节点：站立、外力扰动、位姿广播；含 `body.cpp` 公共库与 launch。 |
| `unitree_gazebo/` | ROS 包 | Gazebo 仿真胶水：world 文件、`normal.launch`/`z1.launch`、足端接触/拉力可视化插件。 |
| `unitree_legged_control/` | ROS 包 | Gazebo `ros_control` 控制器插件 `UnitreeJointController`（核心）+ `pluginlib` 描述文件。 |

---

## 2. 完整路径表（穷尽列举）

> 表格按"包 → 子目录 → 文件"顺序组织。Mesh 资产（STL / DAE / OBJ）逐文件列出但描述精炼到"用于 X 连杆的几何"形式，避免无意义重复。
> 单位约定：URDF/xacro/MJCF 中长度=米、质量=kg、惯量=kg·m²、角度=rad（除非另注 `°`）。

### 2.1 顶层

| 路径 | 类型 | 作用 |
|---|---|---|
| `.gitignore` | git 配置 | 忽略 IDE 缓存、本地 `unitree_guide`、`*usd`。 |
| `.gitmodules` | git 配置 | 子模块：`unitree_ros_to_real → https://github.com/unitreerobotics/unitree_ros_to_real.git`。 |
| `LICENSE` | 文本 | BSD‑3。 |
| `README.md` | Markdown | 顶层使用文档。 |

### 2.2 `unitree_legged_control/`（关节控制器插件包，**核心**）

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_legged_control/CMakeLists.txt` | catkin | 把 `joint_controller.cpp` + `unitree_joint_control_tool.cpp` 编成共享库 `libunitree_legged_control.so`；依赖 `controller_interface / hardware_interface / pluginlib / roscpp / realtime_tools / unitree_legged_msgs`。 |
| `unitree_legged_control/package.xml` | catkin | 包元数据；`<export>` 中通过 `<controller_interface plugin="${prefix}/unitree_controller_plugins.xml"/>` 把控制器注册到 `pluginlib` 索引。 |
| `unitree_legged_control/unitree_controller_plugins.xml` | pluginlib XML | 把类 `unitree_legged_control::UnitreeJointController` 注册成 `controller_interface::ControllerBase` 的实现，路径指向 `lib/libunitree_legged_control`。 |
| `unitree_legged_control/include/unitree_joint_control_tool.h` | C++ 头 | 定义控制宏 `posStopF=2.146e9f` / `velStopF=16000.f`、`ServoCmd` 结构体（mode/pos/posStiffness/vel/velStiffness/torque）；声明 `clamp / computeVel / computeTorque`。 |
| `unitree_legged_control/include/joint_controller.h` | C++ 头 | 声明 `UnitreeJointController` 类（继承 `controller_interface::Controller<EffortJointInterface>`）：成员含 `joint`、订阅器 `sub_cmd / sub_ft`、`Pid pid_controller_`、实时发布器、`MotorCmd / MotorState` 缓冲；接口 `init / starting / update / stopping / setTorqueCB / setCommandCB / positionLimits / velocityLimits / effortLimits / setGains / getGains`。 |
| `unitree_legged_control/src/unitree_joint_control_tool.cpp` | C++ 源 | `clamp` 截断到上下限；`computeVel = 0.35*lastVel + 0.65*Δq/dt` 一阶低通速度估计；`computeTorque = Kp*(q*-q) + Kd*(dq*-dq) + tau_ff`，并在 `q*≈posStopF` / `dq*≈velStopF` 时把对应刚度置零（与真机协议一致）。 |
| `unitree_legged_control/src/joint_controller.cpp` | C++ 源 | 实现 `UnitreeJointController`：从参数服务器读 URDF 与 `joint` 名；订阅 `command`（`unitree_legged_msgs/MotorCmd`，缓冲到 `realtime_tools::RealtimeBuffer`）；订阅 `joint_wrench`（力矩传感器扰动）；每个 `update(period)` 调用按 `lastCmd.mode` 走 `PMSM=0x0A`（正常 PD+前馈）或 `BRAKE=0x00`（仅阻尼制动），用 `computeVel / computeTorque` 算出力矩，调用 `joint.setCommand(τ)` 下发给 Gazebo，并通过 `RealtimePublisher<MotorState>` 把 `q/dq/tauEst` 发到 `<ns>/state`。文件末尾 `PLUGINLIB_EXPORT_CLASS(...)` 把它注册到 pluginlib。 |

### 2.3 `unitree_controller/`（上层示例节点 + body 公共库）

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_controller/CMakeLists.txt` | catkin | 编 `body.cpp` 成 `libunitree_controller.so`；编三个可执行文件 `unitree_external_force / unitree_servo / unitree_move_kinetic`；插件 `unitreeFootContactPlugin / unitreeDrawForcePlugin` 的注释行存在但已被注释（实际由 `unitree_gazebo/CMakeLists.txt` 编译）。 |
| `unitree_controller/package.xml` | catkin | 依赖 `controller_manager / joint_state_controller / robot_state_publisher / unitree_legged_msgs / gazebo_ros` 等。 |
| `unitree_controller/include/body.h` | C++ 头 | 声明 `unitree_model` 命名空间下的全局 `servo_pub[12]`、`lowCmd`、`lowState`，及 `stand / motion_init / sendServoCmd / moveAllPosition` 函数。 |
| `unitree_controller/src/body.cpp` | C++ 源 | `paramInit` 给 12 个电机（4 腿×3 关节）写 `mode=0x0A`、`Kp/Kd`（hip:70/3，thigh:180/8，calf:300/15，仅供参考）；`stand` 用 `(0, 0.67, -1.3)` 关节角让狗站立 2 s；`moveAllPosition(target, duration_ms)` 在 `duration` 毫秒内线性插值从当前姿到 `target`，每毫秒调一次 `sendServoCmd`（向 12 个 servo 发布 `MotorCmd`，并 `usleep(1000)`）。 |
| `unitree_controller/src/servo.cpp` | C++ 源 | `unitree_servo` 节点：构造 `multiThread` 类一次性订阅 `/<rname>_gazebo/{FR,FL,RR,RL}_{hip,thigh,calf}_controller/state`、`/visual/{FR,FL,RR,RL}_foot_contact/the_force`、`/trunk_imu`，把数据写入 `lowState`；`main` 中 advertise 12 个 `MotorCmd` topic + 1 个 `LowState` topic，调 `motion_init()`（含 `paramInit + stand`）后进入 while 循环 publish + sendServoCmd。 |
| `unitree_controller/src/external_force.cpp` | C++ 源 | `unitree_external_force` 节点：用 `termios` 把终端切到 raw mode，监听方向键/空格；空格切换"脉冲(默认 100 ms 脉冲)/连续"两种模式；上下键改 Fx (脉冲±60，连续步进±16，钳到 ±220)；左右键改 Fy；publish `geometry_msgs/Wrench` 到 `/apply_force/trunk`，由 URDF 里的 `libgazebo_ros_force.so` 插件作用到 `trunk` 链接。 |
| `unitree_controller/src/move_publisher.cpp` | C++ 源 | `unitree_move_kinetic` 节点：通过 `/gazebo/set_model_state` 直接改模型位姿。`def_frame == WORLD` 时让 `<rname>_gazebo` 模型在世界系沿 1.5 m 半径圆周以 5 s/圈匀速旋转移动；`def_frame == ROBOT` 时给一个相对自身坐标系的恒定速度 `(0.02, 0, 0.08)`。1000 Hz 发布。 |
| `unitree_controller/launch/set_ctrl.launch` | ROS launch | 接收 `rname`，把它写入 `/robot_name` 参数；保留一行被注释的 `unitree_servo` 节点（被 `normal.launch` `<include>` 进来时统一处理）。 |

### 2.4 `unitree_gazebo/`（Gazebo 仿真胶水 + 插件）

| 路径 | 类型 | 作用 |
|---|---|---|
| `unitree_gazebo/CMakeLists.txt` | catkin | 编两个 SHARED 库：`unitreeFootContactPlugin` 与 `unitreeDrawForcePlugin`；链接 `${GAZEBO_LIBRARIES}`。 |
| `unitree_gazebo/package.xml` | catkin | 依赖 `gazebo_ros / controller_manager / robot_state_publisher / unitree_legged_msgs` 等。 |
| `unitree_gazebo/launch/normal.launch` | ROS launch | 通用四足启动脚本：参数 `rname / wname / user_debug`；①`<include>` `gazebo_ros/empty_world.launch` 加载 `worlds/$(wname).world`；②`xacro $(rname)_description/xacro/robot.xacro DEBUG:=...` 解析为 `robot_description`；③`spawn_model -z 0.6 -model <rname>_gazebo`；④`rosparam load $(rname)_description/config/robot_control.yaml`；⑤`controller_spawner` 起 `joint_state_controller + 12 个肢体控制器`；⑥`robot_state_publisher` 把 `joint_states` remap 到 `/<rname>_gazebo/joint_states`；⑦`<include>` `unitree_controller/launch/set_ctrl.launch`（设置 `/robot_name`）。 |
| `unitree_gazebo/launch/z1.launch` | ROS launch | 机械臂 z1 专用：参数 `UnitreeGripperYN` 控制是否带夹爪，`controller_spawner` 起 `Joint01..06_controller`（带夹爪时再加 `gripper_controller`）。 |
| `unitree_gazebo/plugin/foot_contact_plugin.cc` | Gazebo `SensorPlugin` | `UnitreeFootContactPlugin` 绑定到 `<sensor type="contact">`；`OnUpdate` 每帧从 `parentSensor->Contacts()` 取所有接触点，做平均得到 (Fx,Fy,Fz)，发布到 `/visual/<sensor_name>/the_force`（`geometry_msgs/WrenchStamped`）。注：力是局部坐标。 |
| `unitree_gazebo/plugin/draw_force_plugin.cc` | Gazebo `VisualPlugin` | `UnitreeDrawForcePlugin` 在 visual 上画一条 `RENDERING_LINE_STRIP` 紫色线段；订阅 `<topicName>/the_force`，把力向量按 `/20` 缩放后作为线段终点；用 `event::Events::ConnectPreRender` 绑到渲染前回调。 |
| `unitree_gazebo/worlds/earth.world` | SDF | 地球：`gravity=-9.81`，ODE quick 求解器 50 iter，`real_time_update_rate=5000`；含 `sun + ground_plane + 1 m³ 静态箱`。 |
| `unitree_gazebo/worlds/space.world` | SDF | 太空：`gravity=0` 其他同 earth。 |
| `unitree_gazebo/worlds/stairs.world` | SDF | 阶梯：含三个高度的 `floor` 链接（z=0.09 / 0.09 / 0.63） + `<include><uri>model:///home/unitree/catkin_ws/src/unitree_ros/unitree_gazebo/worlds/building_editor_models/stairs</uri>`，**该 URI 是绝对路径，使用前需改成本地路径**（README 明确提示）。 |
| `unitree_gazebo/worlds/building_editor_models/stairs/model.config` | Gazebo 模型 | 声明 stairs 模型，指向 `model.sdf`。 |
| `unitree_gazebo/worlds/building_editor_models/stairs/model.sdf` | SDF | 4 级阶梯静态模型：4 个 `2×0.25×0.18` box 组成，z 高度 0.09→0.27→0.45→0.63，材质 `Gazebo/Wood`。 |

### 2.5 `robots/` 总索引

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/README.md` | 文档 | 19 款机器人的链接索引。 |

#### 2.5.1 `robots/a1_description/`（A1 中型四足 12 DoF）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/a1_description/CMakeLists.txt` | catkin | 仅 `find_package(catkin REQUIRED COMPONENTS genmsg roscpp std_msgs tf)` + `catkin_package`，纯资源包。 |
| `robots/a1_description/package.xml` | catkin | 包元数据。 |
| `robots/a1_description/config/robot_control.yaml` | YAML | 12 个 `unitree_legged_control/UnitreeJointController` 配置；hip 用 `pid:{p:100,d:5}`，thigh/calf 用 `{p:300,d:8}`；外加 `joint_state_controller @ 1000 Hz`；命名空间 `a1_gazebo`。 |
| `robots/a1_description/launch/a1_rviz.launch` | launch | `xacro robot.xacro DEBUG:=$(arg user_debug)` → `robot_description`，启 `joint_state_publisher(GUI)` + `robot_state_publisher@1000Hz` + `rviz -d check_joint.rviz`。 |
| `robots/a1_description/launch/check_joint.rviz` | RViz config | A1 RViz 视图配置（关节检查）。 |
| `robots/a1_description/urdf/a1.urdf` | URDF | 由 xacro 预渲染的扁平 URDF（973 行），可直接被 `spawn_model` / Isaac Gym 等使用。 |
| `robots/a1_description/xacro/robot.xacro` | xacro 主入口 | 包含 `const + materials + leg + stairs + gazebo`；定义 `base + trunk` 链接、可选的 `world↔base` 固定关节（`DEBUG=true` 时挂起来调试），`imu_link`，并 4 次 `<xacro:leg name="FR/FL/RR/RL" mirror=±1 mirror_dae=T/F front_hind=±1 front_hind_dae=T/F>` 实例化 4 条腿（hip 偏移 ±0.1805 ±0.047 0）。 |
| `robots/a1_description/xacro/const.xacro` | xacro 常量 | A1 物理参数：`PI`，trunk 尺寸 0.267×0.194×0.114，hip/thigh/calf 各种 com、mass、inertia；关节限位 hip ±46°、thigh −60..240°、calf −154.5..−52.5°、最大力矩 33.5 Nm、最大速度 21 rad/s。 |
| `robots/a1_description/xacro/leg.xacro` | xacro 宏 | `leg` 宏：建出 hip/thigh/calf/foot 4 个 link + 3 个 revolute joint + 1 个 fixed foot 关节 + thigh_shoulder 仅碰撞链接；含按 `mirror_dae / front_hind_dae` 切换 mesh 朝向的旋转 origin；末尾 `<xacro:leg_transmission name="${name}"/>`。 |
| `robots/a1_description/xacro/transmission.xacro` | xacro 宏 | `leg_transmission` 宏：为 hip/thigh/calf 三关节各生成一个 `transmission_interface/SimpleTransmission` + `EffortJointInterface` + `mechanicalReduction=1`，让 `gazebo_ros_control` 能驱动它们。 |
| `robots/a1_description/xacro/materials.xacro` | xacro | 9 种 RViz 材质（black/blue/green/grey/silver/orange/brown/red/white）。 |
| `robots/a1_description/xacro/gazebo.xacro` | xacro | Gazebo 专用插件块：①`libgazebo_ros_control.so`（命名空间 `/a1_gazebo`，DefaultRobotHWSim）；②`libLinkPlot3DPlugin.so` 画 base 轨迹；③`libgazebo_ros_force.so` 监听 `/apply_force/trunk` 给 trunk 加力；④`imu_link` 上 `libgazebo_ros_imu_sensor.so` @1 kHz 发 `/trunk_imu`；⑤4 条腿的 `<sensor type="contact">` + `libunitreeFootContactPlugin.so`；⑥4 个 foot visual 上 `libunitreeDrawForcePlugin.so` 画力线；⑦各 link 摩擦/碰撞参数 `mu1/mu2`、`kp/kd`、`self_collide`。 |
| `robots/a1_description/xacro/stairs.xacro` | xacro 宏 | 递归 `stairs` 宏：以 `stair_length=0.640, stair_width=0.310, stair_height=0.170` 生成阶梯 link 串。当前 `robot.xacro` 中实例化被注释。 |
| `robots/a1_description/meshes/calf.dae` | DAE 网格 | 小腿（calf）几何 + 贴图。 |
| `robots/a1_description/meshes/hip.dae` | DAE 网格 | 髋（hip）几何。 |
| `robots/a1_description/meshes/thigh.dae` | DAE 网格 | 大腿（左侧）几何。 |
| `robots/a1_description/meshes/thigh_mirror.dae` | DAE 网格 | 大腿镜像（右侧）。 |
| `robots/a1_description/meshes/trunk.dae` | DAE 网格 | 躯干。 |
| `robots/a1_description/meshes/trunk_A1.png` | 贴图 | trunk DAE 引用的 UV 纹理。 |

#### 2.5.2 `robots/a2_description/`（A2 增强四足，纯 MJCF）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/a2_description/a2.xml` | MJCF | A2 MuJoCo 模型；`compiler angle=radian, meshdir=meshes/`；定义 hip_joint/thigh_joint/calf_joint default class（damping/armature/frictionloss）；4 腿各 4 个 link + collision/foot priority 设置。 |
| `robots/a2_description/urdf/a2.urdf` | URDF | A2 ROS URDF（1060 行）。 |
| `robots/a2_description/meshes/base_link.STL` | STL | 基座几何。 |
| `robots/a2_description/meshes/left_front_Link1..4.STL` | STL ×4 | 左前 4 个连杆几何。 |
| `robots/a2_description/meshes/left_hind_Link1..4.STL` | STL ×4 | 左后 4 个连杆几何。 |
| `robots/a2_description/meshes/right_front_Link1..4.STL` | STL ×4 | 右前 4 个连杆几何。 |
| `robots/a2_description/meshes/right_hind_Link1..4.STL` | STL ×4 | 右后 4 个连杆几何。 |

#### 2.5.3 `robots/aliengo_description/`（AlienGo 中大型四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/aliengo_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/aliengo_description/package.xml` | catkin | 元数据。 |
| `robots/aliengo_description/config/robot_control.yaml` | YAML | 12 关节 `UnitreeJointController` PID（与 a1 同结构）。 |
| `robots/aliengo_description/launch/aliengo_rviz.launch` | launch | RViz 显示。 |
| `robots/aliengo_description/launch/check_joint.rviz` | RViz | RViz 配置。 |
| `robots/aliengo_description/urdf/aliengo.urdf` | URDF | xacro 渲染产物（1211 行）。 |
| `robots/aliengo_description/xacro/robot.xacro` | xacro 主 | base/trunk + 4 腿（被 aliengoZ1 也复用）。 |
| `robots/aliengo_description/xacro/const.xacro` | xacro | AlienGo 物理参数：trunk 0.647×0.310×0.114、关节限位 hip ±46°/thigh −60..240°/calf −156..−48°、最大力矩 44 Nm、最大速度 20 rad/s。 |
| `robots/aliengo_description/xacro/leg.xacro` | xacro 宏 | leg 宏（被 aliengoZ1 直接 include 复用）。 |
| `robots/aliengo_description/xacro/transmission.xacro` | xacro | 同 a1。 |
| `robots/aliengo_description/xacro/materials.xacro` | xacro | 同 a1。 |
| `robots/aliengo_description/xacro/gazebo.xacro` | xacro | gazebo 插件块。 |
| `robots/aliengo_description/xacro/stairs.xacro` | xacro 宏 | 递归阶梯（同 a1）。 |
| `robots/aliengo_description/meshes/calf.dae` | DAE | calf 几何。 |
| `robots/aliengo_description/meshes/hip.dae` | DAE | hip 几何。 |
| `robots/aliengo_description/meshes/thigh.dae` | DAE | thigh。 |
| `robots/aliengo_description/meshes/thigh_mirror.dae` | DAE | thigh 镜像。 |
| `robots/aliengo_description/meshes/trunk.dae` | DAE | trunk。 |
| `robots/aliengo_description/meshes/trunk_uv_base_final.png` | 贴图 | trunk UV 纹理。 |

#### 2.5.4 `robots/aliengoZ1_description/`（AlienGo + Z1 机械臂复合）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/aliengoZ1_description/CMakeLists.txt` | catkin | 模板化资源包（主要是注释的样板代码，实际只 `find_package(catkin)`）。 |
| `robots/aliengoZ1_description/package.xml` | catkin | 元数据。 |
| `robots/aliengoZ1_description/config/robot_control.yaml` | YAML | 12 腿关节 + 6 z1 关节 + gripper 控制器配置。 |
| `robots/aliengoZ1_description/launch/aliengoZ1_gazebo.launch` | launch | Gazebo 启动；`UnitreeGripperYN` 决定加载 18 还是 19 个控制器（含 gripper）。 |
| `robots/aliengoZ1_description/launch/aliengoZ1_rviz.launch` | launch | RViz 启动（结构同 a1_rviz）。 |
| `robots/aliengoZ1_description/worlds/earth.world` | SDF | 该包私有的 earth world（带 user_camera 视角）。 |
| `robots/aliengoZ1_description/xacro/robot.xacro` | xacro 主 | 405 行：include `aliengo_description/xacro/leg.xacro` 复用 4 腿，再手写 z1 机械臂 6 关节 + 夹爪（受 `UnitreeGripper:=true/false` 切换）；机械臂挂在 trunk 上方。 |
| `robots/aliengoZ1_description/xacro/const.xacro` | xacro | 仅追加 `arm_offset_{x,y,z,r,p,yaw}` 6 个属性，其余 include `aliengo_description/xacro/const.xacro`。 |
| `robots/aliengoZ1_description/xacro/gazebo.xacro` | xacro | gazebo_ros_control 命名空间 `/aliengoZ1_gazebo`、4 足 contact/draw plugin、IMU 等。 |
| `robots/aliengoZ1_description/xacro/stairs.xacro` | xacro | 阶梯宏（同 a1）。 |

#### 2.5.5 `robots/as2_description/`（AS2 四足，仅 URDF + MJCF）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/as2_description/as2.xml` | MJCF | AS2 MuJoCo 模型，class hip_joint/thigh_joint/calf_joint。 |
| `robots/as2_description/urdf/as2.urdf` | URDF | AS2 URDF（994 行）。 |
| `robots/as2_description/meshes/base_link.STL` | STL | 基座。 |
| `robots/as2_description/meshes/{FL,FR,RL,RR}_hip.STL` | STL ×4 | 四腿髋部。 |
| `robots/as2_description/meshes/{FL,FR,RL,RR}_thigh.STL` | STL ×4 | 四腿大腿。 |
| `robots/as2_description/meshes/{FL,FR,RL,RR}_calf.STL` | STL ×4 | 四腿小腿。 |
| `robots/as2_description/meshes/{FL,FR,RL,RR}_foot.STL` | STL ×4 | 四腿足端。 |

#### 2.5.6 `robots/b1_description/`（B1 大型四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/b1_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/b1_description/package.xml` | catkin | 元数据。 |
| `robots/b1_description/config/robot_control.yaml` | YAML | 12 关节 PID。 |
| `robots/b1_description/launch/b1_rviz.launch` | launch | RViz 启动。 |
| `robots/b1_description/launch/check_joint.rviz` | RViz | 视图配置。 |
| `robots/b1_description/xacro/b1.urdf` | URDF | xacro 渲染产物（1277 行）（注意此处 `.urdf` 在 `xacro/` 目录而非 `urdf/`）。 |
| `robots/b1_description/xacro/robot.xacro` | xacro 主 | 168 行；trunk 用 mesh 做 collision（更精细）。 |
| `robots/b1_description/xacro/const.xacro` | xacro 常量 | B1 几何/质量/惯量、关节限位（hip ±46°、thigh −90..230°、calf −154.5..−52.5°），最大力矩 200 Nm、最大速度 23 rad/s。 |
| `robots/b1_description/xacro/leg.xacro` | xacro 宏 | leg 宏 288 行（含更细的 hip/thigh/calf collision mesh 引用）。 |
| `robots/b1_description/xacro/transmission.xacro` | xacro | 同 a1。 |
| `robots/b1_description/xacro/materials.xacro` | xacro | 同 a1。 |
| `robots/b1_description/xacro/gazebo.xacro` | xacro | 插件块。 |
| `robots/b1_description/xacro/stairs.xacro` | xacro 宏 | 阶梯。 |
| `robots/b1_description/meshes/calf.dae` | DAE | 小腿。 |
| `robots/b1_description/meshes/calfb.dae` | DAE | 小腿带覆盖件版本。 |
| `robots/b1_description/meshes/hip.dae` | DAE | 髋。 |
| `robots/b1_description/meshes/hipb.dae` | DAE | 髋带覆盖件版本。 |
| `robots/b1_description/meshes/thigh.dae` | DAE | 大腿。 |
| `robots/b1_description/meshes/thigh_mirror.dae` | DAE | 大腿镜像。 |
| `robots/b1_description/meshes/thighb.dae` | DAE | 大腿覆盖件。 |
| `robots/b1_description/meshes/thigh_mirrorb.dae` | DAE | 大腿覆盖件镜像。 |
| `robots/b1_description/meshes/trunk.dae` | DAE | 躯干（无壳体）。 |
| `robots/b1_description/meshes/trunkb.dae` | DAE | 躯干（带覆盖件，URDF 默认引用此）。 |

#### 2.5.7 `robots/b2_description/`（B2 工业级四足，含简单 URDF + xacro 双套）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/b2_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/b2_description/README.md` | 文档 | catkin 工作流说明。 |
| `robots/b2_description/package.xml` | catkin | 元数据。 |
| `robots/b2_description/config/config.rviz` | RViz | display.launch 用的视图。 |
| `robots/b2_description/config/robot_control.yaml` | YAML | 12 关节 PID。 |
| `robots/b2_description/launch/display.launch` | launch | 直接载入 `urdf/b2_description.urdf` 进 RViz。 |
| `robots/b2_description/launch/gazebo.launch` | launch | spawn 直接 URDF 到 Gazebo（不走 xacro）。 |
| `robots/b2_description/urdf/b2_description.urdf` | URDF | B2 URDF（830 行）。 |
| `robots/b2_description/xacro/robot.xacro` | xacro 主 | 含 controller plugin。 |
| `robots/b2_description/xacro/const.xacro` | xacro | B2 物理参数。 |
| `robots/b2_description/xacro/leg.xacro` | xacro 宏 | 4 腿 leg 宏。 |
| `robots/b2_description/xacro/transmission.xacro` | xacro | 同 a1。 |
| `robots/b2_description/xacro/materials.xacro` | xacro | 材质。 |
| `robots/b2_description/xacro/gazebo.xacro` | xacro | Gazebo 插件块。 |
| `robots/b2_description/xacro/stairs.xacro` | xacro | 阶梯。 |
| `robots/b2_description/meshes/{FL,FR,RL,RR}_calf.dae` | DAE ×4 | 四足小腿。 |
| `robots/b2_description/meshes/{FL,FR,RL,RR}_hip.dae` | DAE ×4 | 四足髋。 |
| `robots/b2_description/meshes/{FL,FR,RL,RR}_thigh.dae` | DAE ×4 | 四足大腿。 |
| `robots/b2_description/meshes/FL_foot.dae` | DAE | 左前足端（其它三足复用同一）。 |
| `robots/b2_description/meshes/base_link.dae` | DAE | 基座 / 躯干（非 xacro 用）。 |
| `robots/b2_description/meshes/calf.dae` | DAE | xacro 通用 calf。 |
| `robots/b2_description/meshes/hip.dae` | DAE | xacro 通用 hip。 |
| `robots/b2_description/meshes/thigh.dae` | DAE | xacro 通用 thigh。 |
| `robots/b2_description/meshes/thigh_mirror.dae` | DAE | thigh 镜像。 |
| `robots/b2_description/meshes/trunk.dae` | DAE | trunk。 |
| `robots/b2_description/meshes/trunk1.dae` | DAE | trunk 备选。 |
| `robots/b2_description/meshes/trunk2.dae` | DAE | trunk 备选 2。 |

#### 2.5.8 `robots/b2_description_mujoco/`（B2 MuJoCo 专版）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/b2_description_mujoco/README.md` | 文档 | `simulate ./xml/scene.xml` 启动说明。 |
| `robots/b2_description_mujoco/Screenshot from 2023-12-11 21-44-55.png` | 图 | 模型截图。 |
| `robots/b2_description_mujoco/xml/b2.xml` | MJCF | B2 主 MJCF；`<default class="b2">` 设 `damping=1, armature=0.1`，visual/collision 默认；asset 列出所有 obj/STL；按层级 base→hip→thigh→calf→foot 串联。 |
| `robots/b2_description_mujoco/xml/scene.xml` | MJCF 场景 | `<include file="b2.xml"/>` + skybox + 棋盘地面。 |
| `robots/b2_description_mujoco/xml/b2_description.urdf` | URDF | 与 MJCF 等价的 URDF。 |
| `robots/b2_description_mujoco/meshes/base_link.obj` | OBJ | 基座（OBJ for MuJoCo）。 |
| `robots/b2_description_mujoco/meshes/{FL,FR,RL,RR}_hip.obj` | OBJ ×4 | 四髋。 |
| `robots/b2_description_mujoco/meshes/{FL,FR,RL,RR}_thigh.obj` | OBJ ×4 | 四大腿。 |
| `robots/b2_description_mujoco/meshes/{FL,FR,RL,RR}_thigh_protect.obj` | OBJ ×4 | 大腿护甲。 |
| `robots/b2_description_mujoco/meshes/{FL,FR,RL,RR}_calf.obj` | OBJ ×4 | 四小腿。 |
| `robots/b2_description_mujoco/meshes/{FL,FR,RL,RR}_foot.obj` | OBJ ×4 | 四足端。 |
| `robots/b2_description_mujoco/meshes/f_dc_link.obj` | OBJ | 前 dc link。 |
| `robots/b2_description_mujoco/meshes/r_dc_link.obj` | OBJ | 后 dc link。 |
| `robots/b2_description_mujoco/meshes/f_oc_link.obj` | OBJ | 前 oc link。 |
| `robots/b2_description_mujoco/meshes/r_oc_link.obj` | OBJ | 后 oc link。 |
| `robots/b2_description_mujoco/meshes/logo_left.obj` | OBJ | 左侧 logo。 |
| `robots/b2_description_mujoco/meshes/logo_right.obj` | OBJ | 右侧 logo。 |
| `robots/b2_description_mujoco/meshes/unitree_ladar.obj` | OBJ | 雷达模型。 |
| `robots/b2_description_mujoco/meshes/fake_head_Link.STL` | STL | 头部（占位）。 |
| `robots/b2_description_mujoco/meshes/fake_imu_link.STL` | STL | IMU（占位）。 |
| `robots/b2_description_mujoco/meshes/fake_tail_link.STL` | STL | 尾部（占位）。 |

#### 2.5.9 `robots/b2w_description/`（B2 + Wheel 版四足轮腿）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/b2w_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/b2w_description/README.md` | 文档 | `display.launch` 启动说明。 |
| `robots/b2w_description/package.xml` | catkin | 元数据。 |
| `robots/b2w_description/config/b2w.rviz` | RViz | display 配置。 |
| `robots/b2w_description/config/joint_names_b2w_description.yaml` | YAML | 关节名称列表（SolidWorks 导出辅助）。 |
| `robots/b2w_description/launch/display.launch` | launch | 加载 URDF 到 RViz。 |
| `robots/b2w_description/launch/gazebo.launch` | launch | spawn URDF 到 Gazebo。 |
| `robots/b2w_description/urdf/b2w_description.urdf` | URDF | B2W URDF（573 行）。 |
| `robots/b2w_description/xacro/robot.xacro` | xacro | 主入口。 |
| `robots/b2w_description/xacro/const.xacro` | xacro | 物理参数。 |
| `robots/b2w_description/xacro/leg.xacro` | xacro 宏 | leg 宏（含轮）。 |
| `robots/b2w_description/xacro/transmission.xacro` | xacro | 传动。 |
| `robots/b2w_description/xacro/materials.xacro` | xacro | 材质。 |
| `robots/b2w_description/xacro/gazebo.xacro` | xacro | gazebo 插件。 |
| `robots/b2w_description/xacro/stairs.xacro` | xacro | 阶梯。 |
| `robots/b2w_description/meshes/{FL,FR,RL,RR}_hip.dae` | DAE ×4 | 四髋。 |
| `robots/b2w_description/meshes/{FL,FR,RL,RR}_thigh.dae` | DAE ×4 | 四大腿。 |
| `robots/b2w_description/meshes/{FL,FR,RL,RR}_calf.dae` | DAE ×4 | 四小腿。 |
| `robots/b2w_description/meshes/{FL,FR,RL,RR}_foot.dae` | DAE ×4 | 四足端（轮）。 |
| `robots/b2w_description/meshes/base_link.dae` | DAE | 基座。 |
| `robots/b2w_description/meshes/calf.dae`、`calf_mirror.dae` | DAE ×2 | 小腿通用 + 镜像。 |
| `robots/b2w_description/meshes/hip.dae` | DAE | 髋通用。 |
| `robots/b2w_description/meshes/thigh.dae`、`thigh_mirror.dae` | DAE ×2 | 大腿通用 + 镜像。 |
| `robots/b2w_description/meshes/trunk.dae` | DAE | 躯干。 |

#### 2.5.10 `robots/dexterous_hand_description/`（灵巧手描述）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/dexterous_hand_description/dex1_1/dex1_1.urdf` | URDF | dex1_1（双指夹具，2×3 link 共 6 dof）。 |
| `robots/dexterous_hand_description/dex1_1/meshes/base_link.STL` | STL | 手掌基座。 |
| `robots/dexterous_hand_description/dex1_1/meshes/Link1_1..3.STL`、`Link2_1..3.STL` | STL ×6 | 两指三段连杆。 |
| `robots/dexterous_hand_description/dex3_1/dex3_1_l.urdf` | URDF | 左 3 指灵巧手（225 行）。 |
| `robots/dexterous_hand_description/dex3_1/dex3_1_r.urdf` | URDF | 右 3 指灵巧手。 |
| `robots/dexterous_hand_description/dex3_1/meshes/left_hand_palm_link.STL` | STL | 左手掌。 |
| `robots/dexterous_hand_description/dex3_1/meshes/left_hand_index_{0,1}_link.STL` | STL ×2 | 左食指两段。 |
| `robots/dexterous_hand_description/dex3_1/meshes/left_hand_middle_{0,1}_link.STL` | STL ×2 | 左中指两段。 |
| `robots/dexterous_hand_description/dex3_1/meshes/left_hand_thumb_{0,1,2}_link.STL` | STL ×3 | 左拇指三段。 |
| `robots/dexterous_hand_description/dex3_1/meshes/right_hand_palm_link.STL` | STL | 右手掌。 |
| `robots/dexterous_hand_description/dex3_1/meshes/right_hand_index_{0,1}_link.STL`、`middle_{0,1}`、`thumb_{0,1,2}` | STL ×7 | 右手 3 指共 7 段。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-L/Dex5-URDF-L.urdf` | URDF | 左 5 指灵巧手（606 行）。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-L/meshes/base_link00L.STL` | STL | 左手掌。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-L/meshes/Link_{11..14, 21..24, 31..34, 41..44, 51..54}L.STL` | STL ×20 | 5 指 × 4 段 = 20 个连杆（仅左）。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-R/Dex5-URDF-R.urdf` | URDF | 右 5 指灵巧手。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-R/meshes/base_link00.STL` | STL | 右手掌。 |
| `robots/dexterous_hand_description/dex5_1/Dex5-URDF-R/meshes/Link_{11..14, 21..24, 31..34, 41..44, 51..54}R.STL` | STL ×20 | 右手 5×4 连杆。 |

#### 2.5.11 `robots/g1_d_description/`（G1‑D AGV 移动平台版）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/g1_d_description/g1_d.urdf` | URDF | G1 上半身 + AGV 底盘合体描述（1191 行）；上半身复用 g1 大部分 link，下半身改成 AGV_link + Left/Right Wheel + LZ_it/mt/ot link + Yaw/Pitching link（云台）。 |
| `robots/g1_d_description/meshes/AGV_link.STL` | STL | AGV 底盘。 |
| `robots/g1_d_description/meshes/Left_Wheel_Link.STL`、`RIght_Wheel_Link.STL`（注意原始文件名拼写） | STL ×2 | 左右轮。 |
| `robots/g1_d_description/meshes/LZ_it_Link.STL`、`LZ_mt_Link.STL`、`LZ_ot_Link.STL` | STL ×3 | 云台内/中/外旋转杆。 |
| `robots/g1_d_description/meshes/Yaw_Link.STL`、`Pitching_Link.STL` | STL ×2 | 云台 yaw/pitch。 |
| `robots/g1_d_description/meshes/head_link.STL` | STL | 头。 |
| `robots/g1_d_description/meshes/torso_link.STL`、`torso_link_23dof_rev_1_0.STL`、`torso_link_rev_1_0.STL` | STL ×3 | 躯干（多版本）。 |
| `robots/g1_d_description/meshes/torso_constraint_{L,R}_link.STL`、`torso_constraint_{L,R}_rod_link.STL` | STL ×4 | 躯干约束链路。 |
| `robots/g1_d_description/meshes/waist_constraint_{L,R}.STL` | STL ×2 | 腰部约束。 |
| `robots/g1_d_description/meshes/waist_roll_link.STL`、`waist_roll_link_rev_1_0.STL`、`waist_yaw_link.STL`、`waist_yaw_link_rev_1_0.STL`、`waist_support_link.STL` | STL ×5 | 腰部各连杆与 rev_1_0 版本。 |
| `robots/g1_d_description/meshes/pelvis.STL`、`pelvis_contour_link.STL` | STL ×2 | 骨盆与外形。 |
| `robots/g1_d_description/meshes/logo_link.STL` | STL | logo。 |
| `robots/g1_d_description/meshes/left_*_link.STL`（hip_pitch/roll/yaw, knee, ankle_pitch/roll, shoulder_pitch/roll/yaw, elbow, wrist_pitch/roll/yaw, hand_palm/index_0/1, middle_0/1, thumb_0/1/2, rubber_hand, wrist_roll_rubber_hand）、对应 right_* | STL ×30+ | 左/右半身各连杆（与 g1 保持一致）。 |

> g1_d 全量 STL 共 72 个；以上以"前缀+用途"分组覆盖。

#### 2.5.12 `robots/g1_description/`（G1 通用人形，**最复杂的描述包**）

g1_description 不带 ROS catkin 文件，而是一个纯 URDF/MJCF 资源仓。同一台 G1 因机型（mode_machine）、关节数（23/29 DOF）、是否带手、灵巧手类型不同存在 21 份 URDF + 10 份 MJCF。

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/g1_description/README.md` | 文档 | 模式对照表（mode_10..16、rev_1_0、deprecated 列），visualize 步骤。 |
| `robots/g1_description/g1_23dof.urdf` | URDF | 旧版 23 DoF（`mode_machine=1`，已 Deprecated）。 |
| `robots/g1_description/g1_23dof.xml` | MJCF | 同上的 MuJoCo 版。 |
| `robots/g1_description/g1_23dof_mode_10.urdf` | URDF | 量产 23 DoF mode 10：6×2 腿 + 1 腰 + 5×2 臂。 |
| `robots/g1_description/g1_23dof_rev_1_0.urdf` | URDF | rev 1.0 23 DoF（`mode=4`）。 |
| `robots/g1_description/g1_23dof_rev_1_0.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof.urdf` | URDF | 旧版 29 DoF（`mode=2`，Deprecated）。 |
| `robots/g1_description/g1_29dof.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_lock_waist.urdf` | URDF | 旧版 29 DoF 锁腰（`mode=3`，Deprecated）。 |
| `robots/g1_description/g1_29dof_lock_waist.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_lock_waist_rev_1_0.urdf` | URDF | rev 1.0 29 DoF 锁腰（`mode=6`）。 |
| `robots/g1_description/g1_29dof_lock_waist_rev_1_0.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_lock_waist_with_hand_rev_1_0.urdf` | URDF | rev 1.0 29 DoF 锁腰 + 手（`mode=6`，7×2 手指）。 |
| `robots/g1_description/g1_29dof_lock_waist_with_hand_rev_1_0.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_mode_11.urdf` | URDF | 量产 29 DoF mode 11：4010 wrist 电机、22.5/22.5 hip 减速比。 |
| `robots/g1_description/g1_29dof_mode_12.urdf` | URDF | mode 12：与 11 同但 lock waist。 |
| `robots/g1_description/g1_29dof_mode_13.urdf` | URDF | mode 13：5010 wrist 电机、14.3/22.5 hip。 |
| `robots/g1_description/g1_29dof_mode_14.urdf` | URDF | mode 14：与 13 同但 lock waist。 |
| `robots/g1_description/g1_29dof_mode_15.urdf` | URDF | mode 15：5010 wrist + 22.5/22.5 hip。 |
| `robots/g1_description/g1_29dof_mode_15_with_dex1_1.urdf` | URDF | mode 15 + 配 dex1_1 双指夹具。 |
| `robots/g1_description/g1_29dof_mode_16.urdf` | URDF | mode 16：与 15 同但 lock waist。 |
| `robots/g1_description/g1_29dof_rev_1_0.urdf` | URDF | rev 1.0 29 DoF（`mode=5`，4010 wrist）。 |
| `robots/g1_description/g1_29dof_rev_1_0.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_rev_1_0_with_inspire_hand_DFQ.urdf` | URDF | rev 1.0 + Inspire Hand 12×2 关节（DFQ 系列）。 |
| `robots/g1_description/g1_29dof_rev_1_0_with_inspire_hand_FTP.urdf` | URDF | rev 1.0 + Inspire Hand FTP 系列（带力传感器，2717 行）。 |
| `robots/g1_description/g1_29dof_with_hand.urdf` | URDF | 旧版带手（`mode=2`，Deprecated）。 |
| `robots/g1_description/g1_29dof_with_hand.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_29dof_with_hand_rev_1_0.urdf` | URDF | rev 1.0 29 DoF 带手（`mode=5`，7×2 手指）。 |
| `robots/g1_description/g1_29dof_with_hand_rev_1_0.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/g1_comp.urdf` | URDF | 比赛版本简化模型。 |
| `robots/g1_description/g1_dual_arm.urdf` | URDF | 仅上半身双臂（`mode=9`，没有腿和腰）。 |
| `robots/g1_description/g1_dual_arm.xml` | MJCF | 同上 MuJoCo。 |
| `robots/g1_description/merge_g1_29dof_and_inspire_hand.ipynb` | Jupyter Notebook | 把 g1 与 Inspire 灵巧手合成新 URDF 的脚本（用 `config.yaml` 给的 link/joint 列表做合并）。 |
| `robots/g1_description/inspire_hand/config.yaml` | YAML | 合并参数：`G1_remove_links/joints` + 左右手 `wrist_yaw_link` 移除清单。 |
| `robots/g1_description/inspire_hand/DFQ_left_hand.urdf` | URDF | DFQ 系列左手 URDF。 |
| `robots/g1_description/inspire_hand/DFQ_right_hand.urdf` | URDF | DFQ 系列右手 URDF。 |
| `robots/g1_description/inspire_hand/FTP_left_hand.urdf` | URDF | FTP 系列左手（含力感）URDF。 |
| `robots/g1_description/inspire_hand/FTP_right_hand.urdf` | URDF | FTP 系列右手 URDF。 |
| `robots/g1_description/images/g1_23dof.png` | PNG | 23dof 概览图。 |
| `robots/g1_description/images/g1_29dof.png` | PNG | 29dof 概览图。 |
| `robots/g1_description/images/g1_29dof_with_hand.png` | PNG | 29dof + 手 概览图。 |
| `robots/g1_description/images/g1_dual_arm.png` | PNG | 双臂概览图。 |
| `robots/g1_description/meshes/...` | STL ×165 | G1 全身网格集合：以 `pelvis(_contour)`、`waist_yaw/roll(_rev_1_0)`、`waist_support`、`torso_link(_rev_1_0/_23dof_rev_1_0)`、`logo_link`、`head_link/head_servo_link`、`d455_link`（Realsense）、`xl330_link`、`{left,right}_{hip_pitch/roll/yaw, knee, ankle_pitch/roll, shoulder_pitch/roll/yaw, elbow, wrist_pitch/roll/yaw(_5010), wrist_roll_rubber_hand, base_link, rubber_hand}`、灵巧手 `{Link11..22}_{L,R}` + `L_hand_base_link`、`R_hand_base_link`、`hand_index/middle/thumb_{0,1,2}_link`、`Dex1_base_link/finger_link_{1,2}`、`dex1_col_{1,2}.stl`、`{left,right}_{thumb,index,middle,ring,little}_{1,2,3,4}` + 各 `force_sensor_{1..4}` + `palm_force_sensor`、`{left,right}_thumb_swing` 等组成。 |

#### 2.5.13 `robots/g1_with_brainco_hand/`（G1 + BrainCo 5 指手）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/g1_with_brainco_hand/g1_29dof_mode_15_brainco_hand.urdf` | URDF | mode 15 + BrainCo 5 指 hand（每指 distal/proximal/tip 三段，2029 行）。 |
| `robots/g1_with_brainco_hand/meshes/...` | STL ×75 | G1 上半身 + BrainCo 手网格：除 g1 通用外多了 `{left,right}_{thumb,index,middle,ring,pinky}_{distal,proximal,tip}_{Link/link}` 等 5×3=15 段每侧、`{left,right}_thumb_metacarpal_Link.STL`、`{left,right}_base2_link.STL`（外壳）、`{left,right}_knee_link_simple_collision.STL`（碰撞简化）。 |

#### 2.5.14 `robots/go1_description/`（Go1 四足，含相机）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/go1_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/go1_description/package.xml` | catkin | 元数据。 |
| `robots/go1_description/config/robot_control.yaml` | YAML | 12 关节 PID。 |
| `robots/go1_description/launch/go1_rviz.launch` | launch | RViz 启动。 |
| `robots/go1_description/launch/check_joint.rviz` | RViz | 视图配置。 |
| `robots/go1_description/urdf/go1.urdf` | URDF | Go1 URDF（1777 行，含 5 个深度相机 + 3 个超声 + IMU）。 |
| `robots/go1_description/xacro/robot.xacro` | xacro 主 | 比 a1 多实例化 5 个 `depthCamera`（face/chin/left/right/rearDown）和 3 个 `ultraSound`（left/right/face）。 |
| `robots/go1_description/xacro/const.xacro` | xacro | Go1 物理参数。 |
| `robots/go1_description/xacro/leg.xacro` | xacro 宏 | leg 宏。 |
| `robots/go1_description/xacro/transmission.xacro` | xacro | 传动。 |
| `robots/go1_description/xacro/materials.xacro` | xacro | 材质。 |
| `robots/go1_description/xacro/gazebo.xacro` | xacro | Gazebo 插件块（含 RGBD/超声）。 |
| `robots/go1_description/xacro/depthCamera.xacro` | xacro 宏 | `depthCamera` 宏：建 `camera_${name}` 链路 + `camera_optical_${name}`（光轴坐标）+ `<sensor type="depth">` + `libgazebo_ros_openni_kinect.so` 插件，发布 `/camera_${name}/color/image_raw`、`/camera_${name}/depth/image_raw`、`/cam${camID}/point_cloud_${name}` 等。 |
| `robots/go1_description/xacro/ultraSound.xacro` | xacro 宏 | `ultraSound` 宏：超声占位 link。 |
| `robots/go1_description/meshes/calf.dae`、`hip.dae`、`thigh.dae`、`thigh_mirror.dae`、`trunk.dae` | DAE ×5 | 腿/躯干网格。 |
| `robots/go1_description/meshes/depthCamera.dae` | DAE | 相机外形。 |
| `robots/go1_description/meshes/ultraSound.dae` | DAE | 超声外形。 |

#### 2.5.15 `robots/go2_description/`（Go2 中型四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/go2_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/go2_description/README.md` | 文档 | 含调小 thigh box collision 的训练建议。 |
| `robots/go2_description/package.xml` | catkin | 元数据。 |
| `robots/go2_description/config/joint_names_go2_description.yaml` | YAML | 12 关节名（SolidWorks→URDF 导出辅助）。 |
| `robots/go2_description/config/robot_control.yaml` | YAML | 12 关节 PID。 |
| `robots/go2_description/launch/gazebo.launch` | launch | spawn URDF 直接到 Gazebo（带 `tf_footprint_base` 静态 tf）。 |
| `robots/go2_description/launch/go2_rviz.launch` | launch | textfile URDF 入 RViz。 |
| `robots/go2_description/launch/check_joint.rviz` | RViz | 视图配置。 |
| `robots/go2_description/urdf/go2_description.urdf` | URDF | Go2 URDF（760 行）。 |
| `robots/go2_description/urdf/Normal_collision_model.png` | PNG | 默认碰撞模型示意。 |
| `robots/go2_description/urdf/Amended_collision_model.png` | PNG | 修正后碰撞模型示意。 |
| `robots/go2_description/xacro/robot.xacro` | xacro | xacro 主。 |
| `robots/go2_description/xacro/const.xacro` | xacro | 物理参数。 |
| `robots/go2_description/xacro/leg.xacro` | xacro 宏 | leg 宏。 |
| `robots/go2_description/xacro/transmission.xacro` | xacro | 传动。 |
| `robots/go2_description/xacro/materials.xacro` | xacro | 材质。 |
| `robots/go2_description/xacro/gazebo.xacro` | xacro | Gazebo 插件块。 |
| `robots/go2_description/dae/{base,calf,calf_mirror,foot,hip,thigh,thigh_mirror}.dae` | DAE ×7 | 主 dae 副本（与 meshes 重复，存放在 `dae/` 目录便于共享）。 |
| `robots/go2_description/meshes/{base,calf,calf_mirror,foot,hip,thigh,thigh_mirror}.dae` | DAE ×7 | URDF 引用的 dae 网格。 |

#### 2.5.16 `robots/go2w_description/`（Go2 + 轮腿版）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/go2w_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/go2w_description/package.xml` | catkin | 元数据。 |
| `robots/go2w_description/config/joint_names_go2w_description.yaml` | YAML | 关节名列表。 |
| `robots/go2w_description/launch/gazebo.launch` | launch | spawn URDF 到 Gazebo。 |
| `robots/go2w_description/launch/go2w_rviz.launch` | launch | RViz 启动。 |
| `robots/go2w_description/launch/check_joint.rviz` | RViz | 配置。 |
| `robots/go2w_description/urdf/go2w_description.urdf` | URDF | Go2W URDF（733 行）。 |
| `robots/go2w_description/dae/base.dae`、`calf.stl`、`calf_mirror.stl`、`foot.dae`、`hip.dae`、`left_wheel.dae`、`right_wheel.dae`、`thigh.dae`、`thigh_mirror.dae` | DAE/STL ×9 | 各连杆与左右轮 mesh（注意 go2w 的 calf 用 STL）。 |

#### 2.5.17 `robots/h1_2_description/`（H1‑2 第二代人形）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/h1_2_description/README.md` | 文档 | MuJoCo 启动说明。 |
| `robots/h1_2_description/h1_2.png` | 图 | 模型图。 |
| `robots/h1_2_description/h1_2.urdf` | URDF | 完整 H1‑2（1612 行）。 |
| `robots/h1_2_description/h1_2.xml` | MJCF | 完整 H1‑2 MuJoCo。 |
| `robots/h1_2_description/h1_2_handless.urdf` | URDF | 去手版（846 行）。 |
| `robots/h1_2_description/h1_2_handless.xml` | MJCF | 去手版 MuJoCo。 |
| `robots/h1_2_description/h1_2_with_FTP_hand.urdf` | URDF | 带 FTP 灵巧手版（2564 行）。 |
| `robots/h1_2_description/meshes/...` | STL ×150 | H1‑2 全身：腿（hip yaw/pitch/roll、knee、ankle pitch/roll + ankle A/B link 与 rod）、腰（torso_link、wrist_yaw_link）、臂（shoulder pitch/roll/yaw、elbow、wrist roll/pitch）、左右灵巧手（手掌、12 个 link11..22 各左右 + 5 指三段 + 力感 1..4）。 |

#### 2.5.18 `robots/h1_description/`（H1 第一代人形）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/h1_description/CMakeLists.txt` | catkin | `install(DIRECTORY launch meshes urdf ...)` 简单资源包。 |
| `robots/h1_description/README.md` | 文档 | 19 关节关节树 + RViz/Gazebo/MuJoCo 启动。 |
| `robots/h1_description/package.xml` | catkin | 元数据。 |
| `robots/h1_description/doc/H1.png` | 图 | 模型图。 |
| `robots/h1_description/launch/display.launch` | launch | 把 `urdf/h1_with_hand.urdf` 加到 robot_description 并启 RViz。 |
| `robots/h1_description/launch/gazebo.launch` | launch | spawn `urdf/h1.urdf` 到 Gazebo（z=1.05 起始）。 |
| `robots/h1_description/launch/check_joint.rviz` | RViz | 视图。 |
| `robots/h1_description/urdf/h1.urdf` | URDF | 不带手 H1（684 行）。 |
| `robots/h1_description/urdf/h1_with_hand.urdf` | URDF | 带手 H1（2812 行）。 |
| `robots/h1_description/mjcf/h1.xml` | MJCF | H1 主 MJCF：default class h1（damping=1, armature=0.1）+ asset + `<actuator>` 19 个 motor（hip yaw/roll/pitch/knee/ankle ×2、torso、shoulder pitch/roll/yaw/elbow ×2，ctrlrange ±18..±300）+ `<sensor>` IMU gyro/accelerometer + `<keyframe name="home">` 起始姿态。 |
| `robots/h1_description/mjcf/h1_with_hand.xml` | MJCF | 带手版（416 行）。 |
| `robots/h1_description/mjcf/scene.xml` | MJCF | `<include "h1.xml"/>` + skybox + 棋盘地面。 |
| `robots/h1_description/meshes/{*}.STL` | STL ×49 | 49 个 STL（pelvis、torso、左右 hip yaw/roll/pitch/knee/ankle、shoulder pitch/roll/yaw/elbow、左右手 base + Link11..22 各左右、logo）。 |
| `robots/h1_description/meshes/{*}.dae` | DAE ×49 | 同名 dae 备份（与 STL 一一对应，URDF/MJCF 二选一）。 |

#### 2.5.19 `robots/h2_description/`（H2 第二代人形，仅 URDF）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/h2_description/H2.urdf` | URDF | H2 URDF 引用 STL（888 行，含 `<mujoco>` compiler 标签便于 MuJoCo 直接读 URDF）。 |
| `robots/h2_description/H2_dae.urdf` | URDF | 同 H2 但引用 DAE 网格（视觉效果更好）。 |
| `robots/h2_description/meshes/pelvis.{stl,dae}` | 网格 ×2 | 骨盆。 |
| `robots/h2_description/meshes/torso_link.{stl,dae}`、`waist_yaw_link.{stl,dae}`、`waist_roll_link.{stl,dae}` | 网格 ×6 | 躯干 + 腰部 yaw/roll。 |
| `robots/h2_description/meshes/head_yaw_link.{stl,dae}`、`head_pitch_link.{stl,dae}` | 网格 ×4 | 头部 yaw/pitch。 |
| `robots/h2_description/meshes/{left,right}_hip_{pitch,roll,yaw}_link.{stl,dae}`、`knee_link`、`ankle_{pitch,roll}_link` | 网格 ×20 | 双腿。 |
| `robots/h2_description/meshes/{left,right}_shoulder_{pitch,roll,yaw}_link.{stl,dae}`、`elbow_link`、`wrist_{pitch,roll,yaw}_link` | 网格 ×28 | 双臂（共 7 段一侧 × 2 = 14，每个 STL+DAE）。 |

#### 2.5.20 `robots/laikago_description/`（Laikago 第一代四足）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/laikago_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/laikago_description/package.xml` | catkin | 元数据。 |
| `robots/laikago_description/config/robot_control.yaml` | YAML | 12 关节 PID。 |
| `robots/laikago_description/launch/laikago_rviz.launch` | launch | RViz 启动。 |
| `robots/laikago_description/launch/check_joint.rviz` | RViz | 配置。 |
| `robots/laikago_description/urdf/laikago.urdf` | URDF | Laikago URDF（541 行）。 |
| `robots/laikago_description/xacro/robot.xacro` | xacro 主 | 137 行；4 腿 + IMU。 |
| `robots/laikago_description/xacro/const.xacro` | xacro 常量 | Laikago 物理参数（与 a1 同结构但参数不同）。 |
| `robots/laikago_description/xacro/leg.xacro` | xacro 宏 | leg 宏。 |
| `robots/laikago_description/xacro/transmission.xacro` | xacro | 传动。 |
| `robots/laikago_description/xacro/materials.xacro` | xacro | 材质。 |
| `robots/laikago_description/xacro/gazebo.xacro` | xacro | Gazebo 插件块。 |
| `robots/laikago_description/meshes/calf.dae`、`hip.dae`、`thigh.dae`、`thigh_mirror.dae`、`trunk.dae` | DAE ×5 | 网格。 |

#### 2.5.21 `robots/r1_air_description/`（R1‑Air 简化版人形，无头无手）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/r1_air_description/R1_AIR.urdf` | URDF | R1‑Air URDF（920 行）；同 R1 但去掉 head、wrist、ankle constraint A/B。 |
| `robots/r1_air_description/meshes/imu_in_pelvis_link.STL` | STL | 骨盆内 IMU。 |
| `robots/r1_air_description/meshes/pelvis_link.stl` | STL | 骨盆。 |
| `robots/r1_air_description/meshes/{left,right}_hip_{pitch,roll,yaw}_link.STL` | STL ×6 | 双腿髋。 |
| `robots/r1_air_description/meshes/{left,right}_knee_link.STL`、`knee_collision.STL` | STL ×4 | 双膝（视觉/碰撞）。 |
| `robots/r1_air_description/meshes/{left,right}_ankle_{pitch,roll}_link.STL`、`ankle_A_link`、`ankle_A_rod_link`、`ankle_B_link`、`ankle_B_rod_link`、`ankle_constraint_A_link`、`ankle_constraint_B_link` | STL ×16 | 双踝（含约束链路 A/B、连杆 rod、约束辅助）。 |
| `robots/r1_air_description/meshes/{left,right}_shoulder_{pitch,roll,yaw}_link.stl`、`elbow_link.stl` | STL ×8 | 双臂上 4 段（注意此处文件名小写 `.stl`）。 |

#### 2.5.22 `robots/r1_description/`（R1 完整人形）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/r1_description/R1.urdf` | URDF | R1 完整 URDF（1086 行）。 |
| `robots/r1_description/meshes/head_pitch_link.STL`、`head_yaw_link.STL` | STL ×2 | 头部 pitch/yaw。 |
| `robots/r1_description/meshes/imu_in_pelvis_link.STL`、`pelvis_link.STL` | STL ×2 | 骨盆 IMU + 骨盆。 |
| `robots/r1_description/meshes/{left,right}_hip_{pitch,roll,yaw}_link.STL`、`knee_link.STL`、`knee_collision.STL`、`ankle_{pitch,roll}_link.STL`、`ankle_A_link`、`ankle_A_rod_link`、`ankle_B_link`、`ankle_B_rod_link`、`ankle_constraint_A_link`、`ankle_constraint_B_link` | STL ×22 | 双腿（含约束链路）。 |
| `robots/r1_description/meshes/{left,right}_shoulder_{pitch,roll,yaw}_link.STL`、`elbow_link.STL`、`wrist_roll_link.STL` | STL ×10 | 双臂 5 段。 |
| `robots/r1_description/meshes/torso_collision.stl`、`waist_roll_link.STL`、`waist_yaw_link.STL` | STL ×3 | 躯干碰撞 + 腰 roll/yaw。 |

#### 2.5.23 `robots/z1_description/`（Z1 6 DoF 机械臂）

| 路径 | 类型 | 作用 |
|---|---|---|
| `robots/z1_description/CMakeLists.txt` | catkin | 资源包。 |
| `robots/z1_description/package.xml` | catkin | 元数据。 |
| `robots/z1_description/config/robot_control.yaml` | YAML | Joint01..06 + gripper 控制器配置（PID 全 300/0/5）。 |
| `robots/z1_description/launch/z1_rviz.launch` | launch | RViz 启动。 |
| `robots/z1_description/launch/setting.rviz` | RViz | 视图。 |
| `robots/z1_description/xacro/z1.urdf` | URDF | xacro 渲染产物（276 行）。 |
| `robots/z1_description/xacro/robot.xacro` | xacro 主 | 316 行；6 关节 + 可选夹爪（`UnitreeGripper:=true/false`）。 |
| `robots/z1_description/xacro/const.xacro` | xacro 常量 | Link00..06 各项 com/inertia/mass、关节限位（PositionMin/Max）、velocityMax、torqueMax、jointDamping/Friction、motor/arm 几何尺寸。 |
| `robots/z1_description/xacro/transmission.xacro` | xacro 宏 | `motorTransmission` 宏（按 joint 编号生成 SimpleTransmission）。 |
| `robots/z1_description/xacro/gazebo.xacro` | xacro | gazebo_ros_control 命名空间 `/z1_gazebo`、link04/05/06 设 `self_collide=true`。 |
| `robots/z1_description/meshes/visual/z1_Link00..06.dae`、`z1_GripperMover.dae`、`z1_GripperStator.dae` | DAE ×9 | 高质量可视化网格。 |
| `robots/z1_description/meshes/collision/z1_Link00..06.STL`、`z1_GripperMover.STL`、`z1_GripperStator.STL` | STL ×9 | 简化碰撞网格。 |

---

## 3. 核心代码功能详解（按文件深挖）

下面对每个 C++/launch/yaml/world/MJCF/xacro 文件实现的功能逐一展开，重点说"做了什么 / 用了哪些 ROS 与 Gazebo API / 与上下游的交互边界"。

### 3.1 `unitree_legged_control` ── Gazebo 关节控制器（最核心）

#### 3.1.1 `unitree_joint_control_tool.h/.cpp`：PD+前馈算力矩

`unitree_joint_control_tool.h:16-17` 定义两个 sentinel：

```cpp
#define posStopF (2.146E+9f)  // 真机协议中"位置环停用"标志
#define velStopF (16000.0f)   // "速度环停用"标志
```

`ServoCmd` 结构体（`unitree_joint_control_tool.h:19-27`）抽象 PD+前馈电机命令：

| 字段 | 含义 |
|---|---|
| `mode` | 0x0A=PMSM 闭环；0x00=BRAKE。 |
| `pos / vel` | 期望位置/速度。 |
| `posStiffness / velStiffness` | Kp / Kd。 |
| `torque` | 前馈力矩 τ_ff。 |

`computeVel(currentPos, lastPos, lastVel, period)`（`unitree_joint_control_tool.cpp:13-16`）做一阶低通速度估计：

```
v = 0.35*v_prev + 0.65*Δq/dt
```

`computeTorque(currentPos, currentVel, ServoCmd&)`（`unitree_joint_control_tool.cpp:18-30`）：

```
if |q* - posStopF| < 1e-6 -> Kp = 0
if |dq* - velStopF| < 1e-6 -> Kd = 0
τ = Kp*(q* - q) + Kd*(dq* - dq) + τ_ff
```

`clamp(val, lo, hi)`（`unitree_joint_control_tool.cpp:3-11`）有 float 与 double 两个重载，但 **没有 `return` 语句**（编译器允许通过 — 实际 val 已被原地修改）。这是一个隐式约定：`clamp` 是 in‑place 钳位，调用者传引用得到结果，不要依赖返回值。

#### 3.1.2 `joint_controller.h/.cpp`：实现 `ros_control` 控制器接口

`UnitreeJointController` 继承 `controller_interface::Controller<hardware_interface::EffortJointInterface>`，按 ros_control 规范实现 `init / starting / update / stopping`。

**`init(EffortJointInterface*, NodeHandle&)`（`joint_controller.cpp:48-98`）**：
1. 从 `n.getParam("joint", joint_name)` 读关节名。
2. 用 `urdf::Model::initParamWithNodeHandle("robot_description", n)` 读全局 URDF，根据 `joint_name` 取出 `urdf::JointConstSharedPtr` 用于 `positionLimits/velocityLimits/effortLimits` 钳位。
3. 判断关节是否四足里的 hip/calf 关节（仅设 `isHip / isCalf` 标志位，目前只在力矩传感器回调中影响行为）。
4. `joint = robot->getHandle(joint_name)` 拿到 Gazebo 关节句柄。
5. 订阅 `joint_wrench`（接收 `geometry_msgs/WrenchStamped`）作为外加力矩传感器；订阅 `command`（队列长度 20）接收 `unitree_legged_msgs/MotorCmd`。
6. 创建 `RealtimePublisher<MotorState>` 发到 `<ns>/state`。

**`setCommandCB(MotorCmdConstPtr&)`（`joint_controller.cpp:33-45`）**：把 `MotorCmd { mode, q, Kp, dq, Kd, tau }` 写入 `RealtimeBuffer` 让 RT update 线程消费。注释明确说"我们没有第二个 RT 线程，所以可以从订阅回调直接 writeFromNonRT"。

**`setTorqueCB(WrenchStampedConstPtr&)`（`joint_controller.cpp:26-31`）**：髋关节读 `wrench.torque.x`，其余读 `.y`，存到 `sensor_torque`（目前未用到 `update` 中，是接口预留）。

**`starting(time)`（`joint_controller.cpp:117-131`）**：用当前关节位置初始化 `lastCmd.q / lastState.q`（避免上电瞬间巨大 PD 误差），重置 PID。

**`update(time, period)`（核心，`joint_controller.cpp:134-203`）**：
```cpp
lastCmd = *(command.readFromRT());
if (mode == PMSM) {
    servoCmd.pos = lastCmd.q;            positionLimits(servoCmd.pos);
    servoCmd.posStiffness = lastCmd.Kp;
    if (|lastCmd.q - PosStopF| < 1e-5) servoCmd.posStiffness = 0;
    servoCmd.vel = lastCmd.dq;            velocityLimits(servoCmd.vel);
    servoCmd.velStiffness = lastCmd.Kd;
    if (|lastCmd.dq - VelStopF| < 1e-5) servoCmd.velStiffness = 0;
    servoCmd.torque = lastCmd.tau;        effortLimits(servoCmd.torque);
}
if (mode == BRAKE) {
    servoCmd.posStiffness = 0;
    servoCmd.vel = 0; servoCmd.velStiffness = 20;
    servoCmd.torque = 0;                  effortLimits(servoCmd.torque);
}
currentPos  = joint.getPosition();
currentVel  = computeVel(currentPos, lastState.q, lastState.dq, dt);
calcTorque  = computeTorque(currentPos, currentVel, servoCmd);
effortLimits(calcTorque);
joint.setCommand(calcTorque);
lastState.q = currentPos;
lastState.dq = currentVel;
lastState.tauEst = joint.getEffort();
controller_state_publisher_->msg_ = lastState;
controller_state_publisher_->unlockAndPublish();
```

`positionLimits / velocityLimits / effortLimits` 仅对 `REVOLUTE / PRISMATIC` 关节起作用，调 `clamp` 使用 URDF 的 `joint->limits->{lower,upper,velocity,effort}`。

**注册到 pluginlib**（`joint_controller.cpp:229`）：
```cpp
PLUGINLIB_EXPORT_CLASS(unitree_legged_control::UnitreeJointController,
                       controller_interface::ControllerBase);
```

配合 `unitree_controller_plugins.xml` 与 `package.xml` 的 `<export>`，`controller_manager` 通过 `pluginlib` 就能按 yaml 中的 `type: unitree_legged_control/UnitreeJointController` 实例化它。

#### 3.1.3 `CMakeLists.txt` / `package.xml` / `unitree_controller_plugins.xml`

- CMake 把两个 cpp 编进 `libunitree_legged_control.so`，依赖 `realtime_tools / hardware_interface / controller_interface / pluginlib / unitree_legged_msgs`。
- pluginlib XML 把类注册到 `controller_interface::ControllerBase`。
- `package.xml` 用 `<controller_interface plugin="${prefix}/unitree_controller_plugins.xml"/>` 让 `controller_manager` 在加载 yaml 时能解析 `unitree_legged_control/UnitreeJointController` 字符串。

### 3.2 `unitree_controller` ── 上层示例 + 公共库

#### 3.2.1 `body.h/.cpp`：12 关节"站立"动作公共库

`body.cpp:16-38 paramInit()`：按四条腿循环（i=0..3，每腿 hip/thigh/calf 三关节），写入 PD 与 mode：

| 关节 | mode | Kp | Kd |
|---|---|---|---|
| hip | 0x0A | 70 | 3 |
| thigh | 0x0A | 180 | 8 |
| calf | 0x0A | 300 | 15 |

并把 `lowCmd.motorCmd[i].q = lowState.motorState[i].q` —— 即让目标位置等于当前测量位置，从而进入 PD 时不会有突变。

`body.cpp:40-45 stand()`：调 `moveAllPosition({0,0.67,-1.3, ...}, 2*1000)` 用 2 s 把 12 关节插到站立姿态。

`body.cpp:53-60 sendServoCmd()`：把 `lowCmd.motorCmd[0..11]` 发送到 12 个 `servo_pub[m]`，`ros::spinOnce()` 处理回调，`usleep(1000)` 维持 1 kHz。

`body.cpp:62-74 moveAllPosition(target, duration_ms)`：在 `duration` 毫秒内做线性插值；每毫秒 `sendServoCmd` 一次。

#### 3.2.2 `servo.cpp`：上层 ROS 节点 `unitree_servo`

启动逻辑：
1. `ros::param::get("/robot_name", robot_name)` 拿到 launch 设定的 rname。
2. 构造 `multiThread(robot_name)`：一次性把 `/<rname>_gazebo/{FR,FL,RR,RL}_{hip,thigh,calf}_controller/state` 共 12 个 topic、`/visual/{FR,FL,RR,RL}_foot_contact/the_force` 共 4 个 topic、`/trunk_imu` 共 1 个 topic 全部订阅，回调把数据写进 `body.h` 中声明的全局 `unitree_model::lowState`。
3. `AsyncSpinner(1).start()` + `usleep(300 ms)`：保证至少收到一帧 state 才开始 publish。
4. `n.advertise<MotorCmd>("/<rname>_gazebo/{FR,...}_{hip,thigh,calf}_controller/command", 1)` 共 12 个赋给 `servo_pub[0..11]`，`n.advertise<LowState>("/<rname>_gazebo/lowState/state", 1)`。
5. `motion_init()` → 站立。
6. while‑loop 不断 `lowState_pub.publish(lowState); sendServoCmd();`（无显式 rate；`sendServoCmd` 自带 1 ms sleep，等价 1 kHz）。

回调里的关节顺序约定（重要）：
```
0..2  : FR hip/thigh/calf
3..5  : FL hip/thigh/calf
6..8  : RR hip/thigh/calf
9..11 : RL hip/thigh/calf
```

`start_up = false` 在所有 hip 回调里被置为 false（首次任意 hip 数据到达即认为初始化完成）。

#### 3.2.3 `external_force.cpp`：键盘扰动节点 `unitree_external_force`

终端切 raw 模式（`tcsetattr` + `ICANON|ECHO` 关闭），`for(;;)` 阻塞读 1 字节。键码：

| 键 | 行为 |
|---|---|
| `Up` (0x41) | Fx += 16（连续）/ Fx = 60（脉冲），钳到 ±220。 |
| `Down` (0x42) | Fx -= 16 / Fx = -60。 |
| `Left` (0x44) | Fy += 8 / Fy = 30。 |
| `Right` (0x43) | Fy -= 8 / Fy = -30。 |
| `Space` (0x20) | mode 取反；Fx=Fy=Fz=0；ROS_INFO "Pulsed/Continuous"。 |

每次按键 `pubForce` 把 `geometry_msgs/Wrench` publish 到 `/apply_force/trunk`；脉冲模式下 100 ms 后再 publish 一次零向量。`SIGINT` 通过 `signal(SIGINT, quit)` 恢复终端 cooked 模式后退出。

#### 3.2.4 `move_publisher.cpp`：位姿广播 `unitree_move_kinetic`

通过 `gazebo_msgs::ModelState` 直接改模型位姿（旁路控制器）。在 `def_frame == WORLD` 分支：
```
x = R sin(2π t / T)
y = R cos(2π t / T)
yaw = -2π t / T
```
其中 R=1.5 m、T=5000 ms。模型沿原点圆周匀速。1000 Hz publish 到 `/gazebo/set_model_state`。`ROBOT` 分支则用 twist 给出相对自身的恒定速度 `(0.02, 0, 0.08)`。

#### 3.2.5 `set_ctrl.launch`

仅做一件事：`<param name="robot_name" value="$(arg rname)"/>` 写到 ROS 参数服务器，给后续节点（`unitree_servo / unitree_external_force / unitree_move_kinetic`）读 `/robot_name`。被 `normal.launch` `<include>`。

### 3.3 `unitree_gazebo` ── 仿真胶水 + Gazebo 插件

#### 3.3.1 `normal.launch`：通用四足启动

参数：`rname`（默认 laikago）、`wname`（默认 earth）、`paused / use_sim_time / gui / headless / debug / user_debug`。

流程（行 15‑57）：
1. `<include file="gazebo_ros/empty_world.launch">` 加载 `worlds/<wname>.world`。
2. `<param name="robot_description" command="xacro --inorder $(rname)_description/xacro/robot.xacro DEBUG:=$(user_debug)"/>` 把 xacro 渲染塞到参数服务器。
3. `<node pkg="gazebo_ros" type="spawn_model" args="-urdf -z 0.6 -model <rname>_gazebo -param robot_description -unpause"/>` 把 robot 派生到 Gazebo（z=0.6 起始）。
4. `<rosparam file="$(rname)_description/config/robot_control.yaml" command="load"/>` 加载控制器 YAML。
5. `<node pkg="controller_manager" type="spawner"` 加载 `joint_state_controller` + 12 个 `{FL,FR,RL,RR}_{hip,thigh,calf}_controller`。
6. `<node pkg="robot_state_publisher"` 把 joint_states 转 TF；topic `/joint_states` 被 remap 到 `/<rname>_gazebo/joint_states`。
7. `<include file="unitree_controller/launch/set_ctrl.launch">` 把 `rname` 写到 `/robot_name`。

#### 3.3.2 `z1.launch`：机械臂启动

类似 normal.launch，但模型是 z1，控制器 spawner 起 `Joint01..06_controller`（与 `gripper_controller`，由 `UnitreeGripperYN` 决定）。`-z 0.0` 起始（z1 是固定机械臂）。

#### 3.3.3 `worlds/*.world`：3 个仿真环境

| 文件 | 重力 | 物理频率 | 特征 |
|---|---|---|---|
| `earth.world` | -9.81 | 5000 Hz | sun + ground_plane + 1 m³ 静态 box（`-2 2 0.5`）。 |
| `space.world` | 0 | 1000 Hz | 同上但零重力，可测试零重力下的 PD 行为。 |
| `stairs.world` | -9.81 | 1000 Hz | 三层 floor 链路 + 引用 `building_editor_models/stairs`（**绝对路径，使用前必须改**）。 |

`stairs/model.sdf`：4 级阶梯（每级 `2×0.25×0.18`，z 间距 0.18），材质 Gazebo/Wood。

#### 3.3.4 Gazebo 插件

**`foot_contact_plugin.cc`**：派生 `gazebo::SensorPlugin`。
- `Load(SensorPtr, sdf::ElementPtr)`：dynamic_pointer_cast 到 `ContactSensor`，订阅其 `ConnectUpdated`。
- `OnUpdate()`：从 `parentSensor->Contacts()` 取所有 contact，对所有 contact 的 `wrench.body_1_wrench().force()` 累加再除以 count 得平均力，发布到 `/visual/<sensor_name>/the_force`（`WrenchStamped`，**力是局部坐标**）。
- 通过 URDF/xacro 的 `<sensor type="contact"><plugin filename="libunitreeFootContactPlugin.so"/></sensor>` 挂在 `FR_calf` 等 link。

**`draw_force_plugin.cc`**：派生 `gazebo::VisualPlugin`。
- `Load(VisualPtr, sdf::ElementPtr)`：在 visual 上 `CreateDynamicLine(RENDERING_LINE_STRIP)` 紫色线段，订阅 `<topicName>/the_force`。
- `GetForceCallback`：`Fx = msg.force.x / 20.0`（缩放避免太长），同理 y/z。
- `OnUpdate`：每个 PreRender 帧把 line 第二个点设为 `(Fx, Fy, Fz)`（line 第一个点固定原点）。
- 通过 `<gazebo reference="FR_foot"><visual><plugin filename="libunitreeDrawForcePlugin.so"><topicName>FR_foot_contact</topicName></plugin></visual></gazebo>` 挂在 foot visual 上。

#### 3.3.5 `unitree_gazebo/CMakeLists.txt`

只编两个 SHARED 库：`unitreeFootContactPlugin / unitreeDrawForcePlugin`。其余被注释掉的可执行文件（servo / external_force）实际放在 `unitree_controller`。

### 3.4 各 description 包通用机制（以 a1 为模板）

每个 description 通常含：

```
xacro/
  robot.xacro       # 主入口，包含其它 xacro 与多次 <xacro:leg> 实例化
  const.xacro       # 物理常量
  materials.xacro   # 颜色
  leg.xacro         # 单腿宏（hip/thigh/calf/foot 4 link + 3 revolute）
  transmission.xacro# 3 个 SimpleTransmission
  gazebo.xacro      # Gazebo 插件块
  stairs.xacro      # 阶梯递归宏（可选）
launch/
  <rname>_rviz.launch  # RViz 显示
  check_joint.rviz     # RViz 视图
config/
  robot_control.yaml   # 12 个 unitree_legged_control/UnitreeJointController + joint_state_controller
meshes/
  *.dae / *.stl
urdf/<rname>.urdf      # xacro 预渲染产物（让不能跑 xacro 的工具也能用）
CMakeLists.txt + package.xml
```

**`leg.xacro` 宏的核心做法**（以 a1_description/xacro/leg.xacro:7-175 为例）：
- 接受 `name, mirror, mirror_dae, front_hind, front_hind_dae, *origin` 6 个参数。
- 用 `<xacro:if value="${(mirror_dae == True)}">` 切换 hip 关节限位（左右镜像后下/上限交换）。
- 用 4 种 `mirror_dae × front_hind_dae` 组合切换 hip mesh 的旋转 origin（让同一份 hip.dae 通过 X/Y 翻转复用 4 个朝向）。
- thigh 链路同样用 `mirror_dae` 切 `thigh.dae` vs `thigh_mirror.dae`。
- foot 用 `<sphere radius="${foot_radius}">` 做碰撞，比 mesh 简单。
- 末尾调 `<xacro:leg_transmission name="${name}"/>` 注册 3 个传动。

**`gazebo.xacro` 的固定模式**（a1_description/xacro/gazebo.xacro 为代表）：
1. `gazebo_ros_control` 插件（命名空间 `/<rname>_gazebo`）。
2. `LinkPlot3DPlugin` 画 base 轨迹。
3. `gazebo_ros_force` 插件订阅 `/apply_force/trunk` 给 trunk 加力（external_force 节点的目标）。
4. `gazebo_ros_imu_sensor` 在 imu_link 上 1 kHz 发 `/trunk_imu`。
5. 4 个 `<sensor type="contact"><plugin libunitreeFootContactPlugin.so/></sensor>`。
6. 4 个 `libunitreeDrawForcePlugin.so` 画力线。
7. 各 link 摩擦/碰撞参数 `mu1, mu2, kp, kd, self_collide, material`。

**`config/robot_control.yaml` 模板**：
```yaml
<rname>_gazebo:
  joint_state_controller:
    type: joint_state_controller/JointStateController
    publish_rate: 1000
  FL_hip_controller:
    type: unitree_legged_control/UnitreeJointController
    joint: FL_hip_joint
    pid: {p: 100.0, i: 0.0, d: 5.0}
  ...（12 个）
```
hip 关节惯量小用低 P；thigh/calf 关节惯量大用高 P。

### 3.5 各机器人独有结构

| 机器人 | 与 a1 模板的差异 |
|---|---|
| **a2** | 仅 MJCF + URDF，无 xacro/launch；MJCF 用 `default class hip_joint/thigh_joint/calf_joint` 分别配 damping/armature/frictionloss。 |
| **aliengo** | xacro 与 a1 同构。 |
| **aliengoZ1** | 复用 `aliengo_description/xacro/leg.xacro`；自己的 `robot.xacro` 把 z1 6 关节直接写在主文件里；launch 多一个 `UnitreeGripperYN` 参数。 |
| **as2** | 仅 MJCF + URDF（无 xacro），结构同 a2。 |
| **b1** | trunk 用 mesh 做 collision；`xacro/b1.urdf` 而非 `urdf/`；最大力矩 200 Nm。 |
| **b2** | URDF/xacro 双套；含 SolidWorks→URDF 风格的简单 launch（display.launch + gazebo.launch 直接 spawn URDF）。 |
| **b2_description_mujoco** | 专 MuJoCo，OBJ + STL 网格混用，`<default class="b2">` 设全局 damping/armature。 |
| **b2w** | 在 b2 基础上把 foot 改成轮（左右 wheel.dae）；含 `joint_names_*.yaml`。 |
| **dexterous_hand** | 仅手部 URDF（dex1_1 双指 / dex3_1 三指 / dex5_1 五指 L+R），所有 URDF 都嵌 `<mujoco><compiler meshdir="meshes" discardvisual="false"/></mujoco>`，可直接喂 MuJoCo。 |
| **g1** | 21 份 URDF + 10 份 MJCF 覆盖 mode 1..16、rev_1_0、lock_waist、with_hand、with inspire_hand DFQ/FTP、dual_arm、g1_comp 等所有量产组合；附 Jupyter Notebook 与 inspire_hand 子目录用于动态拼装。 |
| **g1_d** | G1 上半身 + AGV 底盘（轮式）+ 3 段云台。仅一份 URDF。 |
| **g1_with_brainco_hand** | G1 mode 15 + BrainCo 5 指手（每指 distal/proximal/tip）。 |
| **go1** | 比 a1 多 5 个 depth camera + 3 个 ultrasound（`depthCamera.xacro` + `ultraSound.xacro` 宏）；URDF 长达 1777 行。 |
| **go2** | URDF + xacro 双套；README 含训练 collision 微调建议；launch 用 SolidWorks→URDF 模板（`tf_footprint_base` 静态 tf + `fake_joint_calibration`）。 |
| **go2w** | Go2 + 轮腿；仅 URDF，无 xacro；calf 用 STL（其它用 DAE）。 |
| **h1** | 双套（URDF 用 STL，MJCF 完整含 actuator/sensor/keyframe）；19 关节。 |
| **h1_2** | 第二代 H1，URDF 含 ankle A/B 双 rod 约束链路（机械连杆并联）；带手版本 `link11..22_{L,R}` 共 24 个手指 link。 |
| **h2** | 仅 URDF（含 `<mujoco>` 标签兼容 MuJoCo）；STL 与 DAE 双备份。 |
| **laikago** | 第一代四足，xacro 与 a1 同构但参数小。 |
| **r1** / **r1_air** | 双足人形；R1 有头/腕，R1_Air 简化无头无腕。 |
| **z1** | 6 DoF 机械臂，xacro 主文件手写 6 关节，可选夹爪；config yaml 7 个控制器。 |

---

## 4. 数据流与控制框架

### 4.1 启动顺序（以 `roslaunch unitree_gazebo normal.launch rname:=a1 wname:=stairs` 为例）

```
empty_world.launch (Gazebo + stairs.world)
├── xacro a1_description/xacro/robot.xacro -> robot_description
├── spawn_model -urdf -z 0.6 -model a1_gazebo
├── rosparam load a1_description/config/robot_control.yaml -> /a1_gazebo/...
├── controller_manager spawner :
│     joint_state_controller
│     FR_hip / FR_thigh / FR_calf / FL_... / RR_... / RL_... (12 个 UnitreeJointController)
├── robot_state_publisher (joint_states -> TF)
└── set_ctrl.launch (写 /robot_name=a1)
```

启动后必须再手动 `rosrun unitree_controller unitree_servo`（station/PD 上层节点），可选 `unitree_external_force` / `unitree_move_kinetic`。

### 4.2 控制 / 状态闭环数据流（一个关节）

```
            unitree_legged_msgs/MotorCmd (Kp,Kd,q,dq,tau,mode)
unitree_servo  ───────────────────────────►  /<rname>_gazebo/<joint>_controller/command
   ▲                                                       │
   │                                                       ▼ setCommandCB
   │                                                 RealtimeBuffer<MotorCmd>
   │                                                       │
   │                                                       ▼ update()
   │                                            servoCmd = ServoCmd{...}
   │                                            currentVel = computeVel(...)
   │                                            τ = computeTorque(currentPos, currentVel, servoCmd)
   │                                            joint.setCommand(τ)  → Gazebo
   │                                                       │
   │      MotorState (q, dq, tauEst)                       ▼ joint.getEffort()
   └────────── /<rname>_gazebo/<joint>_controller/state ◄──┘
```

### 4.3 IMU & 足底力

```
Gazebo IMU 插件 (imu_link, libgazebo_ros_imu_sensor.so) ──► /trunk_imu (sensor_msgs/Imu)

Gazebo 接触传感器 (FR_calf 等) ──► libunitreeFootContactPlugin.so ──► /visual/FR_foot_contact/the_force (WrenchStamped)
                                                                              │
                                                                              ▼  GetForceCallback
                                          libunitreeDrawForcePlugin.so 在 foot visual 画紫色力箭头
```

`unitree_servo` 同时订阅 `/trunk_imu` 与 `/visual/.../the_force`，把 IMU 写入 `lowState.imu`，足端 force 写入 `lowState.eeForce[i].xyz` + `lowState.footForce[i] = wrench.force.z`。

### 4.4 外力扰动

```
unitree_external_force (键盘) ──► /apply_force/trunk (geometry_msgs/Wrench)
                                                │
                                                ▼  libgazebo_ros_force.so 插件 (绑 trunk)
                                                Gazebo 物理引擎对 trunk 链路施力
```

### 4.5 直接位姿改写（旁路控制器）

```
unitree_move_kinetic ──► /gazebo/set_model_state (gazebo_msgs/ModelState)
                                  │
                                  ▼
                            Gazebo 把模型 teleport 到指定位姿（不经过物理）
```

适合 SLAM / 视觉算法开发时只需视点移动而不需要真实运动学。

---

## 5. 编译 / 运行 / 排坑

### 5.1 依赖（README）

```
ROS Melodic 或 Kinetic（Noetic 也基本 OK）
Gazebo 8 / 9 / 11
sudo apt-get install ros-<distro>-controller-interface ros-<distro>-gazebo-ros-control \
                     ros-<distro>-joint-state-controller ros-<distro>-effort-controllers \
                     ros-<distro>-joint-trajectory-controller
unitree_legged_msgs（来自 unitree_ros_to_real）
```

### 5.2 build

```
cd ~/catkin_ws && catkin_make
# 失败再跑一次（依赖生成顺序问题）
```

### 5.3 已知坑

1. `unitree_gazebo/worlds/stairs.world` 中的 stairs 模型 URI 是 **绝对路径** `/home/unitree/catkin_ws/src/unitree_ros/unitree_gazebo/worlds/building_editor_models/stairs`，使用前必须改成本机路径。
2. `unitree_servo` 节点初始化时强制 `usleep(300000)` 等 first state，因此 launch 里启动顺序要让 controller_manager 先于 servo。
3. 若 `xacro` 默认参数 `DEBUG:=true`，机器人会被 fixed 到 world 静止悬空，便于 PD 调参；产线测试改为 false。
4. `unitree_joint_control_tool.cpp` 的 `clamp` 缺 `return` 但用引用修改值，**别误把返回值当结果**。
5. `unitree_legged_msgs` 不在本仓库，需要先 clone `unitree_ros_to_real` 把 `unitree_legged_msgs` 编出来。
6. `body.cpp` 与 `servo.cpp` 写死 12 关节 + 4 足结构，对人形 / 机械臂不通用 —— 那些机器人没有匹配的上层节点。
7. `mode == BRAKE` 时 `velStiffness=20`，相当于纯阻尼制动；`PMSM` 是真机伺服模式（同 `MotorCmd.mode = 0x0A`）。
8. `posStopF=2.146e9`、`velStopF=16000` 是真机协议的"位置/速度环停用"sentinel，仿真侧只是把对应 K 置零；自己写控制时若不想用某环，记得把对应字段设成 sentinel，而不是给 0（给 0 会被当成期望位置/速度=0）。

---

## 6. 写在最后：仓库结构的设计哲学

`unitree_ros` 表面上看是"19 个机器人 + 几个 ROS 包"的杂烩，但内部有一条清晰的设计主线：

1. **真机协议 = `MotorCmd { mode, q, Kp, dq, Kd, tau }` + `MotorState { q, dq, tauEst }`**。这是上层算法（步态、MPC、RL）唯一关心的接口。
2. **仿真侧"假装"自己也是同一个 motor**。`UnitreeJointController` 接 ros_control 的 `EffortJointInterface`，输入端解析 `MotorCmd`，输出端把 PD+前馈算出的力矩塞到 Gazebo；状态端把 Gazebo 物理量翻译成 `MotorState`。
3. **机器人差异封装在 description 包里**，控制器代码是机器人无关的。
4. **xacro 宏让肢体级几何参数（mass、inertia、限位）可被配置且可生成多机型 URDF**。
5. **真机/仿真切换 = 切换 topic 命名空间和 hardware interface**，业务节点（`servo.cpp` 的 multiThread）只需要订阅 `/trunk_imu` 与 `/<rname>_gazebo/<joint>_controller/{command,state}` topic。

也正因为如此，`unitree_ros` 是 **真机 SDK（`unitree_sdk2_python` / `unitree_sdk2`）+ 仿真（Gazebo / MuJoCo）+ RL（`unitree_rl_mjlab`）** 三大方向的共同根基：所有上层算法只要面向 `MotorCmd / MotorState` 编程，就能在真机和仿真之间无缝切换。

---

## 附录 A：主要 ROS topic 速查（以 a1 为例）

| Topic | 类型 | 方向 | 含义 |
|---|---|---|---|
| `/a1_gazebo/<joint>_controller/command` | `unitree_legged_msgs/MotorCmd` | 发到 controller | 关节 PD+前馈命令。 |
| `/a1_gazebo/<joint>_controller/state` | `unitree_legged_msgs/MotorState` | 从 controller 出 | 关节实测 q/dq/tauEst。 |
| `/a1_gazebo/joint_states` | `sensor_msgs/JointState` | 从 joint_state_controller 出 | TF/RViz 用。 |
| `/a1_gazebo/lowState/state` | `unitree_legged_msgs/LowState` | 从 unitree_servo 出 | 12 关节 + IMU + footForce 聚合。 |
| `/trunk_imu` | `sensor_msgs/Imu` | 从 IMU 插件出 | 仿真 IMU。 |
| `/visual/FR_foot_contact/the_force` | `geometry_msgs/WrenchStamped` | 从 foot_contact_plugin 出 | 局部坐标足底力。 |
| `/apply_force/trunk` | `geometry_msgs/Wrench` | 发到 gazebo_ros_force 插件 | 给 trunk 施加外力。 |
| `/gazebo/set_model_state` | `gazebo_msgs/ModelState` | 发到 Gazebo | 旁路位姿改写。 |

## 附录 B：关键常量速查

| 名称 | 值 | 出处 | 用途 |
|---|---|---|---|
| `PMSM` | 0x0A | joint_controller.h:26 | 真机/仿真 PD+前馈伺服模式。 |
| `BRAKE` | 0x00 | joint_controller.h:27 | 阻尼制动。 |
| `PosStopF` | 2.146e9 | joint_controller.h:28 / unitree_joint_control_tool.h:16 | "位置环停用"哨兵。 |
| `VelStopF` | 16000 | joint_controller.h:29 / unitree_joint_control_tool.h:17 | "速度环停用"哨兵。 |
| 速度低通系数 | 0.35 / 0.65 | unitree_joint_control_tool.cpp:15 | computeVel 一阶 IIR。 |
| 站立姿态 | (0, 0.67, -1.3) ×4 | body.cpp:42 | 12 关节默认站姿（hip=0, thigh=0.67, calf=-1.3 rad）。 |

## 附录 C：URDF 关节命名约定

四足：
```
{FL,FR,RL,RR}_{hip,thigh,calf}_joint    # 12 个 revolute
{FL,FR,RL,RR}_foot_fixed                 # 4 个 fixed
floating_base                            # base ↔ trunk fixed
```

人形（H1 19 dof 为例）：
```
{left,right}_hip_{yaw,roll,pitch}_joint
{left,right}_knee_joint
{left,right}_ankle_joint
torso_joint
{left,right}_shoulder_{pitch,roll,yaw}_joint
{left,right}_elbow_joint
```

机械臂 z1：
```
joint1..joint6 (revolute)
jointGripper (revolute)
```

— 完 —
