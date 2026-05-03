> **Unitree SDK 是“宇树机器人专用控制接口”；ROS/ROS2 是“机器人软件系统的通用协作框架”。SDK 更像厂商给你的遥控器/底层接口，ROS/ROS2 更像机器人项目里的操作系统级中间层、模块管理器和通信生态。**

------

# 1. 先建立整体层次：SDK、ROS、ROS2到底站在哪一层？

你可以把机器人软件分成几层：

```
你的 AI / RL / VLM / 控制算法
        ↓
应用层框架：ROS / ROS2 节点、话题、服务、Action、rviz、bag、tf2、Nav2 等
        ↓
厂商通信接口：Unitree SDK / unitree_ros2 / DDS 消息
        ↓
机器人内部控制器：运动控制器、关节控制器、安全保护、状态反馈
        ↓
电机、IMU、雷达、相机、电池、遥控器等硬件
```

**Unitree SDK** 主要解决的是：

> “我的电脑程序如何和宇树机器人通信、读取状态、发送控制命令？”

**ROS / ROS2** 主要解决的是：

> “一个复杂机器人系统里，感知、定位、规划、控制、可视化、数据记录、仿真、AI 模块之间如何标准化协作？”

ROS 官方对 ROS 的定位是：它是一组帮助构建机器人应用的软件库和工具，包含驱动、算法、开发工具，并且是开源的。

------

# 2. Unitree SDK 是什么？

## 2.1 SDK 的本质

**SDK = Software Development Kit，软件开发工具包。**

在 Unitree 场景里，SDK 就是宇树给开发者的一套接口，让你可以：

| 功能             | 例子                                                 |
| ---------------- | ---------------------------------------------------- |
| 连接机器人       | 通过网线 / DDS / 网络接口连接机器人                  |
| 读取状态         | 读取 IMU、关节角度、关节速度、电池、遥控器、运动状态 |
| 发送控制命令     | 发送站立、行走、姿态、关节 PD 命令、力矩命令         |
| 调用内置能力     | 调用 sport mode、运动服务、状态服务                  |
| 做真实机器人部署 | 把仿真训练好的策略部署到真机                         |

宇树官方 GitHub 对 `unitree_sdk2` 的描述是：它是用于在真实环境中开发 Go2、B2、H1、G1、H2、R1、A2 等机器人的 SDK 包；同时也有 `unitree_sdk2_python` 作为 Python 接口。

------

## 2.2 Unitree SDK2 和 DDS 的关系

现在很多新一代 Unitree 机器人不是简单用传统 TCP socket 发数据，而是用了 **DDS 通信机制**。Unitree 的 `unitree_ros2` README 明确说，Unitree SDK2 基于 **CycloneDDS** 实现机器人通信和控制；而 ROS2 底层也使用 DDS，所以 Unitree 的底层通信可以和 ROS2 兼容。

这句话非常关键。

也就是说：

```
Unitree SDK2
   ↓
CycloneDDS / DDS 通信
   ↓
Unitree 机器人
```

而 ROS2 是：

```
ROS2 Node
   ↓
ROS2 RMW
   ↓
DDS / RTPS
   ↓
网络
```

所以 Unitree 新机器人和 ROS2 能自然打通，是因为它们都站在 DDS 这条通信链路上。

------

# 3. ROS 是什么？

## 3.1 ROS 不是传统意义的操作系统

虽然 ROS 叫 **Robot Operating System**，但它不是 Windows、Linux 那种内核级操作系统。

它更像是：

> **机器人软件开发的“中间件 + 工具链 + 标准接口 + 生态系统”。**

ROS 主要帮你解决这些问题：

| 问题                              | ROS 提供的能力                   |
| --------------------------------- | -------------------------------- |
| 多个模块如何通信？                | Topic / Service / Action         |
| 雷达、相机、IMU 数据怎么统一？    | 标准 Message                     |
| 机器人坐标系怎么管理？            | TF / TF2                         |
| 数据怎么录下来复现？              | rosbag / ros2 bag                |
| 怎么可视化机器人状态？            | rviz / rviz2                     |
| 怎么做 SLAM / 导航 / 机械臂规划？ | gmapping、Nav2、MoveIt 等生态    |
| 多进程、多节点如何组织？          | node、launch、package、workspace |

------

## 3.2 ROS 的核心思想：节点 + 话题

ROS/ROS2 里，一个复杂机器人系统通常不是一个大程序，而是很多小程序组成的。

比如你的 G1 项目可能有：

```
/camera_node          读取相机
/lidar_node           读取雷达
/imu_node             读取 IMU
/state_estimator      状态估计
/rl_policy_node       RL 策略推理
/safety_node          安全限制
/gait_controller      步态控制
/unitree_driver       和机器人通信
/visualization_node   可视化
/logger_node          记录数据
```

这些程序叫 **nodes 节点**。

节点之间通过 **topic 话题**通信。

例如：

```
/lowstate       机器人底层状态
/lowcmd         底层电机命令
/camera/image   相机图像
/odom           里程计
/tf             坐标变换
/cmd_vel        速度命令
```

ROS2 官方文档说，Topic 应用于连续数据流，例如传感器数据、机器人状态；发布者和订阅者通过同一个 topic 名称通信，形成类似总线的结构。

------

# 4. Unitree SDK 和 ROS/ROS2 的核心区别

## 4.1 一张表看懂

| 对比维度     | Unitree SDK                                      | ROS / ROS2                                          |
| ------------ | ------------------------------------------------ | --------------------------------------------------- |
| 本质         | 宇树官方机器人开发接口                           | 通用机器人软件框架                                  |
| 面向对象     | Unitree 机器人                                   | 所有机器人/传感器/算法系统                          |
| 主要作用     | 连接机器人、读状态、发命令                       | 组织复杂机器人系统                                  |
| 抽象层级     | 更靠近机器人通信与控制接口                       | 更靠近系统工程与模块协作                            |
| 生态         | 主要围绕 Unitree                                 | 极大机器人生态：SLAM、Nav、MoveIt、rviz、bag        |
| 学习难度     | 入门相对直接                                     | 系统复杂度更高                                      |
| 适合任务     | 单机控制、低层控制、快速测试、真机部署           | 多传感器融合、导航、可视化、数据记录、大项目架构    |
| 是否厂商绑定 | 强绑定 Unitree                                   | 不绑定某个厂商                                      |
| 实时性       | 更适合直接控制链路，但仍依赖 Linux/网络/程序设计 | ROS2 比 ROS1 更适合分布式和 QoS，但也不是自动硬实时 |
| 典型代码形态 | C++/Python SDK 程序                              | ROS node / package / launch / topic                 |

------

## 4.2 更直观的比喻

### Unitree SDK 像什么？

像汽车厂家给你的 **官方 CAN 总线接口 / 车辆控制 API**。

你可以直接说：

```
读取当前速度
读取电池电压
设置关节目标角度
发送行走命令
停止机器人
```

它很直接，很贴近机器人本体。

------

### ROS/ROS2 像什么？

像整辆自动驾驶车的软件架构。

里面有：

```
感知模块
定位模块
地图模块
路径规划模块
控制模块
安全模块
数据记录模块
可视化模块
仿真模块
```

这些模块不一定都来自 Unitree，而是来自开源生态、你自己的算法、第三方传感器、仿真器、AI 模型。

------

# 5. 在 Unitree 机器人里，SDK 和 ROS2 是什么关系？

重点来了。

在新一代 Unitree 机器人里，关系不是简单的：

```
ROS2 → SDK → 机器人
```

而更接近：

```
方式 A：直接用 Unitree SDK2
你的 C++/Python 程序 → Unitree SDK2 → DDS → 机器人

方式 B：用 Unitree ROS2
你的 ROS2 节点 → ROS2 Topic/Msg → DDS → 机器人

方式 C：SDK + ROS2 混合
你的 ROS2 系统 → 某个桥接节点 → Unitree SDK2 → 机器人
```

宇树的 `unitree_ros2` 文档明确说，因为 Unitree SDK2 基于 CycloneDDS，而 ROS2 也使用 DDS，所以 ROS2 message 可以直接用于 Unitree 机器人通信和控制，不一定要再包一层 SDK 接口。

这也是你之前看到很多 Unitree 项目里会有这些内容的原因：

```
source ~/unitree_ros2/setup.sh
ros2 topic list
ros2 topic echo /sportmodestate
```

Unitree ROS2 文档里也说明，连接机器人时需要配置网卡，比如把连接机器人的网卡设置到 `192.168.123.99`，并配置 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp` 和 `CYCLONEDDS_URI` 指定网络接口。

------

# 6. Unitree 里的高层控制和低层控制，和 SDK/ROS2 的关系

你之前一直在问 **low state / high state / low command / high command**，这里正好一起打通。

------

## 6.1 高层控制：让机器人执行“已经封装好的运动能力”

高层控制不是直接控制每个电机，而是调用机器人内部已经实现的运动控制能力。

比如：

```
站立
蹲下
行走
前进
后退
转向
调节 body height
调节 roll / pitch / yaw
切换运动模式
```

在 Unitree ROS2 文档里，Sportmode control 是通过 request/response 机制实现的，可以向 `/api/sport/request` topic 发布 `unitree_api::msg::Request` 消息；示例中 `SportClient` 可以生成控制机器人姿态的请求。

也就是说：

```
你的程序：
“向前走 0.3 m/s”

机器人内部控制器：
自动生成腿部轨迹、保持平衡、控制各个关节
```

你不需要自己算每个膝盖、髋关节、踝关节的角度。

------

## 6.2 低层控制：你直接给电机发目标

低层控制更危险，也更底层。

你通常要发这些内容：

```
每个关节的目标角度 q
每个关节的目标速度 dq
每个关节的目标力矩 tau
每个关节的 kp
每个关节的 kd
控制模式 mode
CRC 校验
```

Unitree ROS2 文档里 LowCmd 的 `MotorCmd` 就包含 `q`、`dq`、`tau`、`kp`、`kd` 等字段，用于电机的力矩、位置和速度控制。

这就是你做 RL locomotion / sim2real 时最常接触的层。

例如你的 RL policy 输出 action：

```
action = policy(obs)
target_q = default_joint_pos + action * action_scale
```

然后你把 `target_q` 填进 LowCmd：

```
motor_cmd[i].q  = target_q[i]
motor_cmd[i].dq = 0
motor_cmd[i].kp = ...
motor_cmd[i].kd = ...
motor_cmd[i].tau = 0
```

这就是低层部署。

------

## 6.3 LowState 是什么？

LowState 就是机器人底层状态。

Unitree ROS2 文档里 LowState 包含：

```
IMUState
MotorState[20]
BmsState
foot_force
tick
wireless_remote
power_v
power_a
crc
```

其中 MotorState 又包含：

```
q        关节角度
dq       关节速度
ddq      关节加速度
tau_est  估计力矩
temperature
lost
```

这些都是 RL 观测、状态估计和安全检查非常重要的数据。

------

# 7. ROS 和 ROS2 有什么不同？

现在重点解释第二个问题：**ROS 和 ROS2 的区别。**

简单说：

> **ROS1 是第一代机器人中间件，适合早期研究和单机开发；ROS2 是为多机器人、工业部署、分布式通信、QoS、实时性、安全性和现代工程化重做的一代。**

------

## 7.1 ROS1 和 ROS2 最大区别：通信机制不同

### ROS1：中心化 Master

ROS1 里面通常有一个核心组件：

```
roscore
```

它里面有：

```
ROS Master
Parameter Server
Logging
```

ROS1 的节点需要通过 ROS Master 发现彼此。

大致像这样：

```
Node A → 问 Master：谁在订阅 /cmd_vel？
Node B → 问 Master：谁在发布 /scan？
Master → 告诉它们彼此地址
Node A ↔ Node B 建立通信
```

问题是：

```
Master 是中心点
多机器人复杂
跨网络复杂
工业部署不够理想
QoS 能力弱
```

------

### ROS2：去中心化 DDS 发现

ROS2 底层用了 DDS/RMW 架构。ROS2 设计文档说明，ROS1 使用自定义序列化、自定义传输协议和中心化发现机制；ROS2 则通过抽象 middleware interface 使用 DDS 提供序列化、传输和发现，并提供 QoS 策略。

所以 ROS2 里通常不需要 `roscore`。

大致是：

```
Node A ← DDS discovery → Node B
Node C ← DDS discovery → Node D
```

每个节点可以通过 DDS 自动发现其他节点。

这对机器人非常重要，因为真实机器人经常是：

```
机器人本体电脑
外部工控机
遥控电脑
传感器计算盒
边缘服务器
仿真电脑
```

ROS2 更适合这种分布式结构。

------

## 7.2 ROS2 引入 QoS：可以控制消息可靠性和实时性倾向

ROS1 里通信方式相对固定，主要依赖 TCPROS。

ROS2 因为基于 DDS，所以可以设置 QoS，例如：

```
Reliability：可靠 / 尽力而为
Durability：是否保留旧消息
History：保留多少历史消息
Deadline：期望多久必须收到一次消息
Lifespan：消息多久后过期
Liveliness：发布者是否还活着
```

ROS2 官方文档说明，ROS2 提供丰富的 QoS 策略；相比 ROS1 主要支持 TCP，ROS2 可以在弱网络、无线网络、实时系统中根据需求选择 best effort 或 reliable 等策略。

这对机器人很关键。

例如：

| 数据类型     | 推荐思路                                     |
| ------------ | -------------------------------------------- |
| 相机图像     | 可以 best effort，丢一帧没关系，低延迟更重要 |
| IMU 高频数据 | 可以 best effort 或小队列，追求最新数据      |
| 机器人状态   | 通常要稳定，但也不能积压太多旧数据           |
| 控制命令     | 不能延迟堆积，宁愿用最新命令覆盖旧命令       |
| 地图 / 参数  | 可以 reliable，不能丢                        |
| 任务指令     | 应该 reliable，并且要有反馈                  |

------

## 7.3 ROS2 的 Topic / Service / Action 更清晰

ROS2 官方文档把接口分成三类：

| 类型    | 用途                                     |
| ------- | ---------------------------------------- |
| Topic   | 连续数据流，例如传感器数据、机器人状态   |
| Service | 快速请求-响应，例如查询状态、计算一次 IK |
| Action  | 较长时间任务，可以反馈进度，也可以取消   |

官方文档明确说：Topic 用于连续数据流；Service 用于快速 RPC；Action 用于移动机器人或较长时间运行且需要反馈的行为，并且 Action 的关键特性是可以被 preempt/cancel。

对应到 Unitree 项目：

| 任务                                   | 更适合什么                            |
| -------------------------------------- | ------------------------------------- |
| 持续读取 `/lowstate`                   | Topic                                 |
| 持续发送 `/lowcmd`                     | Topic                                 |
| 查询一次机器人状态                     | Service                               |
| 让机器人执行一个持续动作，例如走到某处 | Action                                |
| 启动一次复杂任务，比如视觉搜索目标     | Action                                |
| 设置一次模式                           | Service 或 Topic 请求，取决于厂商接口 |

------

## 7.4 ROS2 支持多种 DDS/RMW 实现

ROS2 不是只能用一种通信库。它通过 RMW 层支持不同中间件。

官方 Humble 文档列出过常见 RMW：

```
Fast DDS: rmw_fastrtps_cpp
Cyclone DDS: rmw_cyclonedds_cpp
RTI Connext DDS: rmw_connextdds
GurumDDS: rmw_gurumdds_cpp
```

并说明 ROS2 二进制发行版通常内置多个 RMW，Fast DDS 是默认实现，Cyclone DDS 等可以通过安装包启用。

Unitree 项目里经常要求：

```
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

原因就是 Unitree SDK2/Unitree ROS2 主要围绕 CycloneDDS 配置。

------

## 7.5 ROS1 和 ROS2 的构建系统不同

| 项目       | ROS1                                        | ROS2                                    |
| ---------- | ------------------------------------------- | --------------------------------------- |
| 构建工具   | catkin / catkin_make / catkin build         | colcon                                  |
| 包系统     | catkin package                              | ament package                           |
| 常见工作区 | `catkin_ws`                                 | `ros2_ws` / `install` / `build` / `log` |
| Python     | ROS1 早期以 Python2 为主，Noetic 转 Python3 | Python3                                 |
| launch     | XML launch 为主                             | Python launch 为主                      |
| 包隔离     | ROS1 常见 devel space                       | ROS2 install space，更强调隔离构建      |

ROS2 设计文档也提到，ROS2 中每个 package 会被单独构建和安装，不再使用 ROS1 那种 non-isolated build 和 devel space 的方式。

------

## 7.6 ROS1 已经进入历史阶段，ROS2 是未来主线

ROS 官方博客说明，ROS Noetic 是最后一个 ROS1 发行版，并且已经在 2025 年 5 月达到 End of Life。

所以如果你现在做 Unitree G1 / Go2 / H1 / H2 / 具身智能 / VLA / RL / Sim2Real，**新项目应该优先 ROS2，而不是 ROS1**。

------

# 8. ROS1、ROS2、Unitree SDK 的关系总结表

| 方案               | 你写什么                 | 通信方式                      | 适合场景                                  | 是否推荐新项目   |
| ------------------ | ------------------------ | ----------------------------- | ----------------------------------------- | ---------------- |
| Unitree SDK2       | C++/Python 程序          | DDS / Unitree API             | 快速控制真机、低层部署、官方示例          | 推荐             |
| unitree_ros2       | ROS2 节点                | ROS2 + DDS + Unitree msg      | 多模块机器人系统、可视化、bag、传感器融合 | 强烈推荐         |
| ROS1 + unitree_ros | ROS1 package             | ROS1 通信机制                 | 老项目、URDF、仿真、历史代码              | 不建议新项目主线 |
| ROS2 + SDK bridge  | ROS2 节点 + SDK 封装节点 | ROS2 内部通信，SDK 对接机器人 | 你想自己封装更安全的控制接口              | 推荐高级项目     |
| 纯 Python SDK      | Python 脚本              | SDK2 Python                   | 快速实验、读取状态、AI 推理接入           | 推荐原型阶段     |

------

# 9. 对你做 G1 / RL / Sim2Real / AI Agent 控制，应该怎么选？

结合你现在的方向，我建议你这样理解：

## 9.1 如果你只是想“让机器人动起来”

用 **Unitree SDK2 / Unitree ROS2 官方 example**。

例如：

```
读取 low state
发送 low cmd
测试 sport mode
读取 wireless controller
```

Unitree ROS2 文档里就有 G1 low-level example、H1-2 low-level、读取 low state、读取 wireless controller、Go2 sport client、ros bag 记录等示例。

------

## 9.2 如果你要部署 RL locomotion

优先理解这条链：

```
仿真训练策略
        ↓
导出 policy.pt / onnx
        ↓
真机读取 LowState
        ↓
构造 obs
        ↓
policy 推理 action
        ↓
action scale + default joint pos
        ↓
生成 LowCmd
        ↓
发送到机器人
```

这里最核心的是 **低层控制**。

你可以用：

```
Unitree SDK2
```

也可以用：

```
ROS2 topic /lowcmd, /lowstate
```

但本质上你都在做同一件事：

> 读取底层状态，计算关节目标，发送电机命令。

------

## 9.3 如果你要做高级 AI 功能

比如：

```
VLM 看环境
LLM 做任务规划
Agent 调用技能库
机器人执行导航/抓取/步行动作
实时记录数据
可视化状态
多传感器融合
```

那你应该用 **ROS2 作为系统主架构**。

因为这时候你不是只控制机器人腿部，而是要组织一整个复杂系统：

```
/vlm_node
/task_planner_node
/memory_node
/navigation_node
/unitree_control_node
/safety_guard_node
/perception_node
/logger_node
```

ROS2 的价值就出来了。

------

## 9.4 最合理的架构：ROS2 做“大脑系统”，SDK/底层接口做“身体接口”

我建议你未来的架构是：

```
LLM / VLM / Agent 层
        ↓
任务规划层 Task Planner
        ↓
技能层 Skill Manager
        ↓
ROS2 系统层
        ↓
Unitree Control Node
        ↓
Unitree SDK2 / DDS / LowCmd / Sport Mode
        ↓
G1 真机
```

不要让 LLM 直接控制电机。

正确方式是：

```
LLM 不发 motor_cmd
LLM 只发高级意图
```

例如：

```
“走到桌子旁边”
“保持站立”
“向左转 30 度”
“执行 waving 动作”
“进入安全停止”
```

然后下面由 ROS2 / SDK / 控制器转成具体机器人控制命令。

------

# 10. 一个非常重要的理解：ROS2 不是替代 SDK，而是组织 SDK

很多人容易误解：

> “我用了 ROS2，是不是就不用 Unitree SDK 了？”

不完全对。

更准确地说：

| 情况                 | 解释                                                   |
| -------------------- | ------------------------------------------------------ |
| 用 SDK2              | 你直接用厂商接口控制机器人                             |
| 用 unitree_ros2      | 宇树已经把接口做成 ROS2 消息/话题形式                  |
| 自己封装 ROS2 driver | 你可以在 ROS2 node 里调用 SDK2，然后对外发布标准 topic |
| 完整机器人系统       | ROS2 管系统，SDK 管机器人通信                          |

所以：

```
SDK 是机器人身体接口
ROS2 是机器人系统架构
```

它们不是同一类东西。

------

# 11. 最终结论：你应该怎么记？

## 11.1 Unitree SDK

记成：

> **Unitree SDK = 宇树机器人专用 API，用来直接读状态、发命令、控制真机。**

适合：

```
真机连接
低层控制
运动模式调用
RL 策略部署
快速测试官方功能
```

------

## 11.2 ROS

记成：

> **ROS = 第一代机器人通用软件框架，生态很大，但架构较老，新项目不建议作为主线。**

适合：

```
老项目
历史代码
ROS1 仿真包
URDF / Gazebo 老生态
```

------

## 11.3 ROS2

记成：

> **ROS2 = 新一代机器人通用软件框架，基于 DDS，更适合现代机器人、分布式系统、多机器人、真机部署和工程化项目。**

适合：

```
Unitree G1 新项目
多传感器系统
AI Agent 控制架构
VLM / LLM / RL 集成
数据记录
rviz2 可视化
仿真到真机
复杂机器人系统工程
```

------

# 12. 对你当前 Unitree 学习路线的建议

你现在应该按这个顺序学：

```
第一步：Unitree SDK2 / unitree_ros2 基础
    读 LowState
    发 LowCmd
    理解 SportMode
    理解 DDS 网络配置

第二步：ROS2 基础
    node
    topic
    service
    action
    launch
    bag
    rviz2
    tf2

第三步：Unitree + ROS2 联调
    ros2 topic list
    echo /lowstate
    publish /lowcmd
    记录 ros2 bag
    rviz2 可视化

第四步：RL 部署
    obs 构造
    action scale
    PD 控制
    watchdog
    safety clamp
    soft shutdown

第五步：高级 AI 系统
    VLM 感知
    LLM 任务规划
    Skill library
    ROS2 action server
    Unitree control node
```

一句话总结：

> **你做底层运动控制，要懂 Unitree SDK / LowCmd / LowState；你做完整机器人 AI 系统，要用 ROS2 把所有模块组织起来。**