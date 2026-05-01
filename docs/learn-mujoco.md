# learn-mujoco.md

## 学习范围

本学习记录只关注 `unitree_mujoco/`，暂不展开 `unitree_rl_mjlab/` 和 `unitree_sdk2_python/`。

目标是理解 `unitree_mujoco` 的顶层设计、模块边界、核心控制链路、MuJoCo 模型组织、C++/Python 两套仿真器、地形工具和示例程序。

## 学习顺序

当前采用的顺序：

1. 先走控制消息链路，快速扫盲：从 `example/cpp/stand_go2.cpp` 发布 `LowCmd`，到 `simulate/src/unitree_sdk2_bridge.h` 接收消息，再到 `mj_data->ctrl` 驱动 MuJoCo 电机。
2. 再走运行链路：从 `simulate/config.yaml`、`simulate/src/main.cc` 看程序如何启动、加载 MJCF、创建物理线程和 DDS 桥接线程。
3. 最后补齐模块：`unitree_robots/`、`simulate_python/`、`terrain_tool/`、`example/`。

## 互动记录

### 第 0 轮：学习路径确认

用户希望只关注 `unitree_mujoco`，并特别希望先学习控制消息链路，因为这里有较多基础概念需要快速扫盲。

### 第 1 轮：从 LowCmd 到 MuJoCo 控制输入

讲解重点：

- 控制程序通过 DDS topic `rt/lowcmd` 发布低层电机命令。
- `simulate/src/unitree_sdk2_bridge.h` 中的 bridge 订阅 `LowCmd`，读取目标位置、目标速度、增益和前馈力矩。
- bridge 将 `LowCmd` 转换为 MuJoCo actuator 输入 `mj_data->ctrl[i]`。
- 核心控制公式：

```cpp
mj_data_->ctrl[i] =
    tau
  + kp * (target_q - current_q)
  + kd * (target_dq - current_dq);
```

用户当前理解：

- `LowCmd.motor_cmd[i].q` 不是直接把 MuJoCo 关节角设置成该值。
- 它会参与一个 PD + 力矩控制器的计算。

用户追问：

1. DDS topic 是什么，`rt/lowcmd` 有什么作用。
2. `unitree_sdk2_bridge.h` 里的 bridge 承担什么角色，为什么需要 bridge，没有 bridge 会怎样。
3. 希望详细解释 PD 是什么。

### 第 2 轮：DDS、低层/高层命令、bridge 的再澄清

用户当前理解：

1. DDS 像一条通信主线，大家不直接调用彼此函数，而是通过这条主线发送信息。
2. 用户疑问：为什么不直接调用函数发请求。
3. 用户疑问：低层命令和高层命令有什么区别。
4. 用户理解：bridge 就是把 SDK 消息转换成 MuJoCo 可以读懂、可以执行的数据结构。

纠正点：

- DDS 更准确地说是一个发布/订阅式通信中间件，不总是“请求执行”。`rt/lowcmd` 更像持续广播的控制命令流。
- 直接函数调用要求双方在同一个进程或强耦合接口内；DDS 允许控制程序、仿真器、真机服务位于不同进程、不同机器、不同语言实现中。
- bridge 的理解正确：它把 SDK2 DDS 消息和 MuJoCo 的 `mjData`/`mjModel` 数据结构互相转换。

### 第 3 轮：PD 与 tau 的实际效果

用户回答：

- 对 `kp = 0, kd = 0, tau = 1.0` 的直觉是“有一个前馈矩阵 1.0”，但仍不理解实际会发生什么。

纠正点：

- `tau` 不是矩阵，而是某个电机的前馈力矩，也就是直接施加到该 actuator 的力矩命令。
- 在当前 bridge 中，最终送入 MuJoCo 的控制输入为 `tau + kp * 位置误差 + kd * 速度误差`。
- `kp` 决定“往目标位置拉回去”的强度；`kd` 决定“抑制速度/刹车”的强度；`tau` 决定“不管误差是多少都直接额外出多少力”。

### 第 4 轮：target_dq 的含义

用户回答理解检查：

- 当 `q = 1.0`、`current_q = 0.5`、`dq = 0`、`current_dq = 0`、`kp = 40`、`kd = 2`、`tau = 0` 时，用户判断 `ctrl` 为正，电机会往目标角度 `1.0` 的方向努力。

纠正点：

- 该判断正确。此时位置误差为正，速度误差为 0，所以输出主要来自 `kp * 位置误差`。
- 用户仍不理解 `kd` 要乘的“目标速度”。需要强调：`target_dq` 是期望关节速度，不是由系统自动推导出来的；在站立这类位置保持任务中通常设为 0，表示希望关节靠近目标后停住。

用户随后回答：

- 当 `target_q = current_q = 1.0`，但 `current_dq = 3.0`、`target_dq = 0` 时，`ctrl` 为负，作用是刹车。

纠正点：

- 该判断正确。此时位置误差为 0，输出来自 D 项：`kd * (0 - 3.0)`，即反向阻尼。

### 第 5 轮：bridge 的类结构

进入下一个知识点：`simulate/src/unitree_sdk2_bridge.h` 的类结构。

核心结构：

- `UnitreeSDK2BridgeBase`：保存 `mjModel*` 和 `mjData*`，查找并缓存 MuJoCo sensor 地址，按配置初始化手柄，必要时打印模型中的 link/joint/actuator/sensor 信息。
- `RobotBridge<LowCmd_t, LowState_t>`：模板 bridge，用不同 SDK2 消息类型适配不同机器人族。它订阅/持有 `rt/lowcmd`，发布 `LowState`、`SportModeState` 和手柄状态。
- `Go2Bridge`：`RobotBridge<unitree::robot::go2::subscription::LowCmd, unitree::robot::go2::publisher::LowState>` 的别名，适用于 Go2/B2/H1 等使用 `unitree_go` IDL 的模型。
- `G1Bridge`：继承 `RobotBridge<unitree::robot::g1::subscription::LowCmd, unitree::robot::g1::publisher::LowState>`，额外发布 BMS 和 secondary IMU。

启动选择逻辑位于 `simulate/src/main.cc` 的 `UnitreeSdk2BridgeThread`：

- 等待 MuJoCo 的 `mjData* d` 准备好。
- 初始化 SDK2 DDS：`ChannelFactory::Instance()->Init(domain_id, interface)`。
- 根据 actuator 数量判断使用 `G1Bridge` 还是 `Go2Bridge`：`m->nu > 20` 时用 G1，否则用 Go2。
- 调用 `interface->start()` 启动 1ms 周期的 bridge 线程。

用户回答理解检查：

- 用户理解 `sensordata` 是一个大的数组，需要知道具体数据位置。
- 用户不清楚发布成 `LowState` 是给谁看的。

纠正点：

- `sensordata` 中读出的主要是仿真状态反馈，不是控制命令本身。
- `LowState` 是发布给外部控制程序看的，例如 `stand_go2.cpp` 或用户自己的控制器。这样控制程序不用知道 MuJoCo，只需要像连接真机一样订阅 `rt/lowstate`。

用户进一步追问：

- MuJoCo 不就是仿真器吗？为什么要让控制程序“感觉自己在连一台 Unitree 机器人，而不是连 MuJoCo”？这是否多此一举？

纠正点：

- 如果目标只是做 MuJoCo demo，直接调用 MuJoCo API 是可以的。
- `unitree_mujoco` 的目标是 sim-to-real 验证：同一套面向 Unitree SDK2 的控制程序，应尽量不改接口地跑在仿真器和真机上。
- 因此 bridge 和 DDS topic 不是为了简单仿真而设计，而是为了复用真实机器人控制程序、降低仿真到实机的接口差异。

用户新的理解：

- `LowState`/`LowCmd` 这一层包装，是为了让控制器在 MuJoCo 仿真和真机上尽量使用同一套接口，而不是重写控制器。

纠正点：

- 该理解正确。
- 需要进一步区分 MuJoCo 与 `unitree_mujoco`：MuJoCo 是通用物理引擎；`unitree_mujoco` 是基于 MuJoCo + Unitree SDK2 bridge + 机器人模型 + viewer/config/example 封装出来的 Unitree 专用仿真器。

用户回答理解检查：

- MuJoCo 是物理引擎。
- 用户将 `unitree_mujoco` 理解为“可以理解 bridge 发出信息的物理引擎”。

纠正点：

- MuJoCo 仍然只是物理引擎，并不会理解 SDK2、DDS、LowCmd 或 bridge。
- `unitree_mujoco` 是完整仿真应用：它包含 MuJoCo 物理引擎、Unitree 机器人 MJCF 模型、DDS bridge、配置、viewer、示例和地形工具。
- bridge 不是“给 MuJoCo 发 SDK2 信息”，而是把 SDK2 消息翻译成 MuJoCo 能接受的 `mj_data->ctrl`，再把 MuJoCo 状态翻译回 SDK2 的 `LowState`。

### 第 6 轮：MuJoCo 的 `mjModel`、`mjData`、`ctrl`、`sensordata`

进入新知识点：

- `mjModel`：由 MJCF/XML 编译出来的静态模型，描述机器人和场景“有什么”。
- `mjData`：仿真运行时的数据，描述机器人和场景“现在是什么状态”。
- `mj_data->ctrl`：MuJoCo actuator 的控制输入数组，由 bridge 根据 `LowCmd` 计算后写入。
- `mj_data->sensordata`：MuJoCo sensor 的输出数组，由 MuJoCo 在 `mj_step()` / `mj_forward()` 后更新，bridge 再读取并包装成 `LowState`。

补充讲解：

- `mjModel` 偏静态，来自 `scene.xml` / `go2.xml` 等 MJCF 文件。它描述 body、joint、actuator、sensor、mesh、惯量、碰撞几何、关节限位等模型结构。
- `mjData` 偏动态，由 `mj_makeData(m)` 创建。它保存当前仿真时间、关节位置、关节速度、控制输入、传感器输出、接触和约束等运行时状态。
- `m->nu` 是 actuator 数量。Go2 的 XML 中定义了 12 个 motor actuator，因此其 `ctrl` 数组有 12 个主要电机输入。
- `mj_data->ctrl` 不是关节角数组，而是 actuator 控制输入数组。在本仓库的 motor actuator 场景下，可以近似理解为最终电机力矩命令。
- `mj_data->sensordata` 是 MuJoCo sensor 输出的大数组。Go2/G1 等 XML 中定义的 `jointpos`、`jointvel`、`jointactuatorfrc`、`framequat`、`gyro`、`accelerometer` 等传感器输出会被按顺序放入这里。
- bridge 通过两种方式读取 `sensordata`：
  - 对电机状态，依赖 XML 中 sensor 的顺序：前 `num_motor` 个为关节位置，再后 `num_motor` 个为关节速度，再后 `num_motor` 个为力矩估计。
  - 对 IMU、frame position、frame velocity 等，启动时通过 `mj_name2id()` 和 `mj_model_->sensor_adr[]` 查找具体地址。

控制闭环总结：

```text
控制程序发布 LowCmd
        ↓
bridge 读取 LowCmd
        ↓
bridge 根据 LowCmd + sensordata 计算 ctrl
        ↓
写入 mj_data->ctrl
        ↓
MuJoCo 调用 mj_step(m, d)
        ↓
MuJoCo 更新 qpos/qvel/sensordata
        ↓
bridge 读取 sensordata
        ↓
bridge 发布 LowState
        ↓
控制程序根据 LowState 计算下一帧 LowCmd
```

本轮理解检查问题：

- 如果要知道 Go2 模型一共有多少个可控 actuator，应看 `mjModel`，例如 `m->nu`。
- 如果要知道当前第 3 个电机的关节角，应看 `sensordata` 中对应的 joint position sensor 输出，而不是 `ctrl`。

## 阶段总结：已经建立的核心认知

目前已经完成第一阶段：从 `LowCmd` 到 MuJoCo 控制输入的扫盲。

已经确认的关键认知：

- `unitree_mujoco` 的核心目标不是写一个最短路径的 MuJoCo demo，而是做 sim-to-real 验证。它让面向 Unitree SDK2 的控制程序尽量不改接口地跑在仿真器和真机上。
- DDS topic 是发布/订阅式通信通道。`rt/lowcmd` 是低层电机控制命令流；`rt/lowstate` 是低层状态反馈流。
- `LowCmd` 从控制程序发给仿真器或真机；`LowState` 从仿真器或真机发回控制程序。
- `bridge` 是翻译层：它把 SDK2 DDS 消息翻译成 MuJoCo 的 `mj_data->ctrl`，也把 MuJoCo 的 `sensordata` 翻译回 SDK2 的 `LowState`。
- `LowCmd.motor_cmd[i].q` 不是直接设置 MuJoCo 关节角，而是目标关节角。它参与 PD + 前馈力矩控制计算。
- 当前 C++ bridge 中每个电机的核心控制公式是：

```cpp
mj_data_->ctrl[i] =
    tau
  + kp * (target_q - current_q)
  + kd * (target_dq - current_dq);
```

- `kp` 是位置误差增益，像弹簧，把关节拉向目标位置。
- `kd` 是速度误差增益，像阻尼/刹车，让关节速度接近期望速度，常用于防止冲过头和震荡。
- `tau` 是前馈力矩，不是矩阵；它是不管误差如何都直接额外施加的力矩。
- `target_dq` 是目标关节速度。在站立/保持姿态任务中通常设为 0，表示希望关节最终停住。
- MuJoCo 和 `unitree_mujoco` 不是同一个层次：
  - MuJoCo 是通用物理引擎，负责动力学、碰撞、接触、传感器和 `mj_step()`。
  - `unitree_mujoco` 是 Unitree 专用仿真器应用，包含 MuJoCo、Unitree MJCF 模型、SDK2 bridge、配置、viewer、手柄、示例和地形工具。

## 后续完整学习规划

后续建议按从核心到外围的顺序继续学习。每一章都应保持当前节奏：先讲源码和概念，再提理解检查问题，最后把用户回答、纠正点和总结追加到本文档。

### 第 1 章：控制消息链路继续深入

目标：彻底理解 `example/cpp/stand_go2.cpp` 如何发命令，bridge 如何接收，MuJoCo 如何执行。

需要学习：

- `example/cpp/stand_go2.cpp`
  - `ChannelFactory::Instance()->Init(...)`
  - `ChannelPublisher<LowCmd_>`
  - `ChannelSubscriber<LowState_>`
  - `InitLowCmd()`
  - `LowCmdWrite()`
  - `crc32_core()`
  - 站起/趴下的 `tanh` 插值逻辑
- `simulate/src/unitree_sdk2_bridge.h`
  - `lowcmd->msg_.motor_cmd()[i]`
  - `lowcmd->mutex_`
  - `lowstate->trylock()`
  - `unlockAndPublish()`
  - `RecurrentThread` 的 1ms 周期
- 重点问题：
  - 为什么控制程序需要持续发布 `LowCmd`，而不是只发一次？
  - CRC 在低层命令里起什么作用？
  - `stand_go2.cpp` 为什么即使订阅了 `LowState`，示例里也没有复杂使用？

### 第 2 章：C++ 仿真器启动链路

目标：理解 `unitree_mujoco` 主程序如何从配置文件启动完整仿真器。

需要学习：

- `simulate/config.yaml`
  - `robot`
  - `robot_scene`
  - `domain_id`
  - `interface`
  - `use_joystick`
  - `print_scene_information`
  - `enable_elastic_band`
- `simulate/src/param.h`
  - YAML 加载
  - 命令行参数覆盖配置
  - `-r`、`-s`、`-i`、`-n`
- `simulate/src/main.cc`
  - `scanPluginLibraries()`
  - `LoadModel()`
  - `PhysicsThread()`
  - `PhysicsLoop()`
  - `UnitreeSdk2BridgeThread()`
  - `RenderLoop()`
- 重点问题：
  - 配置文件和命令行参数谁优先？
  - 物理线程、渲染线程、bridge 线程分别负责什么？
  - `mj_step()` 和 `mj_forward()` 有什么区别？

### 第 3 章：MJCF 机器人模型结构

目标：理解 `unitree_robots/` 里的 XML 如何定义机器人，并与 bridge 的数组索引对应起来。

需要学习：

- `unitree_robots/go2/scene.xml`
  - 场景文件如何 include `go2.xml`
  - 地面、灯光、障碍物如何定义
- `unitree_robots/go2/go2.xml`
  - `<compiler>`
  - `<default>`
  - `<asset>`
  - `<worldbody>`
  - `<joint>`
  - `<geom>`
  - `<site>`
  - `<actuator>`
  - `<sensor>`
  - `<keyframe>`
- 对比其他机器人：
  - `b2`
  - `b2w`
  - `go2w`
  - `h1`
  - `g1`
  - `h1_2`
- 重点问题：
  - actuator 的顺序为什么必须和 SDK2 电机顺序匹配？
  - sensor 的顺序为什么影响 bridge 读取 `sensordata`？
  - `scene.xml` 和机器人本体 XML 分离有什么好处？

### 第 4 章：Go2 与 G1/H1 类机器人的差异

目标：理解为什么 bridge 要区分 `Go2Bridge` 和 `G1Bridge`，以及 Unitree 不同 IDL 的区别。

需要学习：

- README 中的说明：
  - Go2、B2、H1、B2w、Go2w 使用 `unitree_go` IDL。
  - G1、H1-2 使用 `unitree_hg` / G1 相关 wrapper。
- `G1Bridge` 的额外逻辑：
  - `mode_machine`
  - `rt/lf/bmsstate`
  - `rt/secondary_imu`
- `unitree_robots/g1/g1_joint_index_dds.md`
  - G1 电机顺序
  - 23DoF / 29DoF 差异
- 重点问题：
  - 当前用 `m->nu > 20` 判断 bridge 类型有什么优缺点？
  - 为什么 G1 需要 secondary IMU？
  - 为什么 humanoid 的电机顺序更容易出错？

### 第 5 章：手柄与 WirelessController 模拟

目标：理解仿真器如何把本地游戏手柄模拟成 Unitree 遥控器 topic。

需要学习：

- `simulate/src/physics_joystick.h`
  - `XBoxJoystick`
  - `SwitchJoystick`
  - axis/button 映射
  - `joystick_bits`
- `simulate/src/joystick/`
  - Linux `/dev/input/js0`
  - `jstest`
  - `JoystickEvent`
- bridge 中：
  - `lowstate->joystick`
  - `wireless_controller->joystick`
  - `rt/wireless_controller`
- 重点问题：
  - `use_joystick=0` 时仿真器还能不能运行？
  - 为什么不同手柄需要不同映射？
  - 手柄状态是控制输入还是状态反馈？

### 第 6 章：虚拟弹力带 ElasticBand

目标：理解为什么 humanoid 初始化时可能需要吊装/虚拟弹力带。

需要学习：

- `simulate/src/main.cc`
  - `ElasticBand`
  - `enable_elastic_band`
  - `band_attached_link`
  - `d->xfrc_applied`
  - 键盘 7/8/9 控制
- 重点问题：
  - 弹力带为什么是外力而不是电机命令？
  - `xfrc_applied` 和 `ctrl` 有什么区别？
  - 为什么 H1/G1 这类机器人初始化更需要辅助稳定？

### 第 7 章：Python 仿真器

目标：理解 `simulate_python/` 是 C++ 仿真器的轻量 Python 对应版本，但推荐主线仍是 C++。

需要学习：

- `simulate_python/config.py`
- `simulate_python/unitree_mujoco.py`
  - `SimulationThread`
  - `PhysicsViewerThread`
- `simulate_python/unitree_sdk2py_bridge.py`
  - Python bridge 如何读写 `data.ctrl`
  - 如何发布/订阅 SDK2 Python topic
  - Python 版 ElasticBand
- `simulate_python/test/test_unitree_sdk2.py`
- 重点问题：
  - Python 版和 C++ 版的数据流是否一致？
  - Python 版为什么更适合理解和快速实验？
  - C++ 版为什么更推荐用于实际仿真验证？

### 第 8 章：地形工具 terrain_tool

目标：理解如何自动生成复杂场景并输出 `scene_terrain.xml`。

需要学习：

- `terrain_tool/terrain_generator.py`
  - `AddBox`
  - `AddGeometry`
  - `AddStairs`
  - `AddSuspendStairs`
  - `AddRoughGround`
  - `AddPerlinHeighField`
  - `AddHeighFieldFromImage`
- `terrain_tool/scene.xml`
- `unitree_robots/*/scene_terrain.xml`
- 重点问题：
  - 地形工具生成的是机器人模型还是场景模型？
  - height field 和普通 box 障碍物有什么区别？
  - 为什么地形输出要放到对应机器人目录下？

### 第 9 章：示例程序体系

目标：理解仓库如何通过 C++、Python、ROS2 示例验证同一套 SDK2 接口。

需要学习：

- `example/cpp/stand_go2.cpp`
- `example/python/stand_go2.py`
- `example/ros2/src/stand_go2.cpp`
- `example/ros2/include/motor_crc.h`
- 重点问题：
  - 三个示例控制逻辑是否本质一致？
  - Python 示例为什么依赖 `unitree_sdk2_python`？
  - ROS2 示例和 SDK2 DDS topic 的关系是什么？

### 第 10 章：构建、依赖与运行方式

目标：理解 C++ 仿真器如何编译，依赖如何组织，运行参数如何影响行为。

需要学习：

- `simulate/CMakeLists.txt`
  - MuJoCo include/lib
  - `unitree_sdk2`
  - `yaml-cpp`
  - `boost_program_options`
  - `glfw`
  - `lodepng`
- README 安装步骤
  - `/opt/unitree_robotics`
  - `~/.mujoco`
  - `simulate/mujoco` 软链接
- 运行命令：

```bash
./unitree_mujoco -r go2 -s scene.xml
./unitree_mujoco -r go2 -s scene_terrain.xml
./unitree_mujoco -i 1 -n lo
```

- 重点问题：
  - `domain_id` 为什么仿真最好和真机默认 domain 区分？
  - `interface=lo` 为什么适合本机仿真？
  - MuJoCo plugin 目录为什么需要扫描？

### 第 11 章：完整源码走读与最终总图

目标：把所有模块汇总成一张全局架构图和一条端到端时序图。

最终应该能画出：

```text
example controller
  |
  | DDS rt/lowcmd
  v
UnitreeSDK2Bridge
  |
  | mj_data->ctrl
  v
MuJoCo mj_step
  |
  | mj_data->sensordata
  v
UnitreeSDK2Bridge
  |
  | DDS rt/lowstate / rt/sportmodestate / rt/wireless_controller
  v
example controller
```

最终应该能解释：

- 每个顶层目录的职责。
- C++ 仿真器的启动和运行线程。
- bridge 的双向翻译逻辑。
- MJCF 模型如何影响 actuator 和 sensor 数组。
- Go2/G1 等不同机器人为何需要不同 IDL 和额外 topic。
- Python 仿真器、地形工具和示例程序分别用于什么场景。

## 下一次建议从哪里继续

建议下一次从第 1 章继续：完整走读 `example/cpp/stand_go2.cpp`。

原因：

- 它是最贴近控制链路入口的文件。
- 你已经理解了 `LowCmd`、`LowState`、PD、bridge、MuJoCo 数据结构。
- 继续读示例程序可以把“控制程序到底怎么写”这件事落到具体代码上。

下一次建议的问题顺序：

1. `ChannelFactory::Instance()->Init(1, "lo")` 到底初始化了什么？
2. `LowCmd` 消息每个字段如何初始化？
3. 为什么 `stand_go2.cpp` 每 2ms 发一次命令？
4. 站起/趴下的插值为什么用 `tanh`？
5. CRC 为什么要在发送前计算？
