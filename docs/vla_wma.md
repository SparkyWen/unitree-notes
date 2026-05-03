> **UnifoLM-VLA = 看到画面 + 听懂指令 → 直接预测机器人动作**
>  **UnifoLM-WMA = 看到当前世界 + 预测未来会怎样 → 再辅助生成更合理动作**
>  **SLAM = 机器人一边走一边建地图，同时知道自己在地图里的位置**

------

# 1. 先给你一张总图：它们在机器人系统里的位置

```
人类指令
  ↓
语言理解 / 任务理解
  ↓
视觉感知：相机、深度相机、LiDAR
  ↓
┌───────────────────────────────┐
│  UnifoLM-VLA                  │
│  视觉 + 语言 + 动作模型        │
│  “看到什么，听到什么，手该怎么动” │
└───────────────────────────────┘
        ↓ 动作 chunk / 关节动作 / 末端动作
        ↓
机器人控制器 / SDK / ROS2 / DDS
        ↓
机械臂、夹爪、手臂执行
```

而 **UnifoLM-WMA** 的思想更像这样：

```
当前画面 + 指令 + 机器人状态
        ↓
┌────────────────────────────────────┐
│  World Model 世界模型               │
│  预测：如果机器人这样动，未来会发生什么 │
└────────────────────────────────────┘
        ↓ 未来视频 / 未来交互状态 / 预测反馈
        ↓
Action Head / Policy 决策模块
        ↓
选择更合理的动作
        ↓
机器人执行
```

所以一句话：

> **VLA 是“直接从感知到动作”的策略模型。WMA 是“带世界预测能力的策略架构”。SLAM 是“空间定位与建图系统”，不是大模型本身。**

------

# 2. UnifoLM-VLA 是什么？

**UnifoLM-VLA-0** 全称是 **Vision-Language-Action model**，也就是“视觉-语言-动作模型”。官方说明里说，它是面向通用人形机器人操作的 VLA 大模型，目标是突破普通 VLM 只能“看图说话”、不能真正理解物理交互的问题；它通过机器人操作数据继续预训练，把图文理解能力扩展成具备物理常识的“具身大脑”。

你可以把它理解成：

```
输入：
- 摄像头图像 / 多视角图像
- 人类语言指令
- 机器人自身状态，例如关节位置、夹爪状态、末端位姿等

输出：
- 一段未来动作
- 例如手臂怎么移动、夹爪什么时候打开/闭合、下一段 action chunk 怎么执行
```

官方资料强调它做的是 **general-purpose humanoid robot manipulation**，也就是通用人形机器人操作任务；并且在真机验证中，官方称它可以用单一策略完成 12 类复杂操作任务。

它的公开数据集也基本都是 **G1 桌面操作任务**，例如：

| 数据集任务                 | 大致含义         |
| -------------------------- | ---------------- |
| `G1_Stack_Block`           | G1 堆积方块      |
| `G1_Bag_Insert`            | 把物体放入袋子   |
| `G1_Clean_Table`           | 清理桌面         |
| `G1_Pour_Medicine`         | 倒药/药瓶类操作  |
| `G1_Prepare_Fruit`         | 准备水果         |
| `G1_Fold_Towel`            | 叠毛巾           |
| `G1_Wipe_Table`            | 擦桌子           |
| `G1_DualRobot_Clean_Table` | 双机器人清理桌面 |

这些任务在官方 README 的数据集部分列出，主要面向 Unitree G1 的操作学习。

------

# 3. UnifoLM-VLA 的核心特点

## 3.1 它更像“机器人操作策略大模型”

它关注的是：

> **给机器人一个语言目标，让机器人根据画面生成动作。**

例如：

```
Human: Put the black camera into the box.

Robot camera sees:
- 桌子
- 黑色相机
- 盒子
- 手臂当前位置

VLA outputs:
- 手臂靠近相机
- 调整夹爪姿态
- 抓取相机
- 移动到盒子上方
- 放下
```

它不是普通 ChatGPT，也不是普通 VLM。普通 VLM 可能只能说：

> “我看到一个相机和一个盒子。”

但 VLA 要进一步输出：

> “机器人下一步应该怎么动。”

------

## 3.2 它不是直接控制每个电机的最底层模型

这一点非常重要。

VLA 输出的动作一般不是：

```
motor_1 = 0.123
motor_2 = -0.456
motor_3 = 1.234
```

它更常见的是输出一段 **action chunk**，比如：

```
未来 16 步的手臂/夹爪动作
```

然后这些动作还需要经过：

```
VLA 输出动作
  ↓
动作反归一化 / 平滑 / 安全限制
  ↓
机器人部署客户端
  ↓
Unitree SDK2 / DDS / 控制器
  ↓
机械臂、夹爪、电机
```

官方 README 也提到训练前要配置 `NUM_ACTIONS_CHUNK`、`ACTION_DIM`、`PROPRIO_DIM` 等参数，这说明它处理的是动作维度、状态维度和动作 chunk，而不是简单一句自然语言命令。

------

## 3.3 它更适合“操作任务”，不是专门做走路

比如这些任务适合 VLA：

| 任务             | 是否适合 UnifoLM-VLA            |
| ---------------- | ------------------------------- |
| 抓取杯子         | 适合                            |
| 把物体放进盒子   | 适合                            |
| 擦桌子           | 适合                            |
| 叠毛巾           | 适合                            |
| 整理工具         | 适合                            |
| 让 G1 稳定走路   | 不是它的核心任务                |
| 让 G1 跑步、跳跃 | 更应该用 locomotion RL / 控制器 |

所以你之前研究的：

- `unitree_rl_gym`
- `unitree_rl_lab`
- `unitree_rl_mjlab`
- sim2real locomotion

解决的是 **腿怎么走、身体怎么稳**。

而 UnifoLM-VLA 解决的是：

> **眼睛看到任务以后，手臂和夹爪怎么完成操作。**

------

# 4. UnifoLM-WMA 是什么？

**UnifoLM-WMA-0** 全称是 **World-Model-Action Framework**，也就是“世界模型-动作架构”。官方介绍里说，它是宇树开源的、跨多类机器人本体的 world-model-action 架构，核心是一个能够理解机器人与环境物理交互规律的世界模型。

它的核心不是“直接从图像到动作”，而是：

> **先预测世界，再帮助策略做更好的动作决策。**

官方说明它的 world model 有两个作用：

| 模式                   | 作用                                                 |
| ---------------------- | ---------------------------------------------------- |
| **Simulation Engine**  | 作为交互式仿真器，生成用于机器人学习的合成数据       |
| **Policy Enhancement** | 连接 action head，通过预测未来交互过程来优化决策表现 |

这两个功能是 WMA 和 VLA 最大的区别。

------

# 5. WMA 的“世界模型”到底是什么意思？

你可以把世界模型理解为：

> **机器人脑子里有一个“想象器”。它可以想象：如果我这样动，接下来世界会怎么变化。**

例如桌面上有一个杯子，机器人准备去抓它：

```
当前画面：
- 杯子在桌子上
- 机器人手在左边

候选动作 A：
- 手从左边直接推过去

世界模型预测：
- 杯子可能被撞倒

候选动作 B：
- 手先抬高，再从上方夹住

世界模型预测：
- 杯子更可能被稳定抓起
```

于是策略模块可以选择动作 B。

这就是 WMA 的核心价值：

> **不是盲目模仿数据，而是利用“未来预测”减少错误动作。**

官方项目页也明确说，WMA 里的世界模型支持两种运行模式：

1. **决策模式**：预测未来物理交互信息，辅助策略生成动作；
2. **仿真模式**：基于机器人动作生成高保真环境反馈。

------

# 6. WMA 和 VLA 的最核心区别

| 对比维度              | UnifoLM-VLA                        | UnifoLM-WMA                                  |
| --------------------- | ---------------------------------- | -------------------------------------------- |
| 全称                  | Vision-Language-Action             | World-Model-Action                           |
| 中文理解              | 视觉-语言-动作模型                 | 世界模型-动作架构                            |
| 核心问题              | “看到画面和指令后，我该怎么动？”   | “如果我这样动，未来会怎样？然后怎么动更好？” |
| 是否直接出动作        | 是，更偏直接策略                   | 可以出动作，但核心是用世界预测增强动作       |
| 是否预测未来视频/状态 | 不是核心                           | 是核心能力                                   |
| 主要能力              | 指令理解、空间感知、操作泛化       | 未来交互预测、仿真生成、策略增强             |
| 训练重点              | 机器人操作数据上的 VLA fine-tuning | 先训练视频/世界模型，再训练决策/仿真模式     |
| 更像什么              | “机器人操作大脑”                   | “机器人想象器 + 决策增强器”                  |
| 典型任务              | 抓取、放置、擦桌、叠毛巾、整理工具 | 预测动作后果、生成仿真数据、辅助策略选择     |
| 对开发者的价值        | 快速做端到端操作策略               | 做更高级的模型式决策、数据生成、未来预测     |

------

# 7. 用一个例子彻底区分 VLA 和 WMA

假设任务是：

```
把黑色相机放进盒子里。
```

## 7.1 VLA 的思路

```
输入：
- 当前相机画面
- 指令：pack black camera into box
- 机器人状态

VLA：
- 直接预测未来 16 步动作

输出：
- 靠近相机
- 抓住相机
- 移到盒子上方
- 放下相机
```

也就是：

```
观察 + 指令 → 动作
```

------

## 7.2 WMA 的思路

```
输入：
- 当前相机画面
- 指令
- 机器人状态
- 候选动作或动作历史

World Model：
- 预测如果这样抓，会不会撞到盒子
- 预测相机会不会掉
- 预测未来画面中相机是否进入盒子

Action Head：
- 根据预测结果选择更合理动作
```

也就是：

```
观察 + 指令 → 预测未来 → 决策动作
```

------

# 8. 从训练流程看二者区别

## 8.1 VLA 的训练流程

官方 README 里说，VLA 使用 LeRobot V2.1 格式数据，然后转换成 HDF5，再转换为 RLDS 数据格式进行训练；训练时还要注册数据集、配置 action chunk、动作维度、状态维度和归一化方式。

简化为：

```
采集 G1 操作数据
  ↓
整理成 LeRobot 格式
  ↓
转 HDF5
  ↓
转 RLDS
  ↓
配置动作维度、状态维度、chunk 长度
  ↓
fine-tune VLA
  ↓
部署到服务器
  ↓
机器人客户端发送观测，服务器返回动作
```

官方也说真实世界推理时是 **server side inference**：机器人客户端采集真机 observation，发送给服务器，服务器做动作推理。

------

## 8.2 WMA 的训练流程

WMA 的训练更复杂。官方 README 给出的策略是：

1. 先用 Open-X 数据集 fine-tune 一个视频生成模型作为 world model；
2. 再在下游任务数据集上以 decision-making mode 继续训练；
3. 再以 simulation mode 继续训练。

简化为：

```
大量机器人视频/操作数据
  ↓
训练 world model：学会预测未来交互视频
  ↓
训练 decision-making mode：学会用未来预测辅助动作
  ↓
训练 simulation mode：学会根据动作生成环境反馈
  ↓
部署：机器人发 observation，服务器返回动作或预测
```

所以 WMA 的难点更高，因为它不仅要学：

```
该怎么动
```

还要学：

```
动了以后世界会怎么变
```

------

# 9. 从部署角度看二者区别

官方 WMA 的部署文档提到 `unitree_deploy` 用于 Unitree 机器人模型部署，并覆盖 G1 with gripper 和 Z1 平台，包括依赖安装、图像服务启动、夹爪控制等。

它的部署链路大概是：

```
G1 / Z1 真机
  ↓
image_server 获取图像
  ↓
robot_client 获取 observation
  ↓
通过网络发给模型服务器
  ↓
模型服务器推理 action
  ↓
robot_client 执行动作
  ↓
SDK / DDS / 控制器控制机器人
```

WMA README 还给了一个真实推理命令示例，包含：

```
python scripts/robot_client.py \
  --robot_type "g1_dex1" \
  --action_horizon 16 \
  --exe_steps 16 \
  --observation_horizon 2 \
  --language_instruction "pack black camera into box" \
  --output_dir ./results \
  --control_freq 15
```

这说明它部署时会指定机器人类型、动作 horizon、观测 horizon、语言指令、控制频率等参数。

------

# 10. 你应该怎么理解它们和 G1 的关系？

对 G1 来说，可以分成三层：

```
第一层：身体运动 / Locomotion
- 走路
- 平衡
- 跑步
- 转身
- 上下坡
- sim2real RL

第二层：空间导航 / SLAM + Navigation
- 我在哪里
- 地图长什么样
- 怎么走到目标位置
- 避障

第三层：操作智能 / VLA 或 WMA
- 看到桌子上的东西
- 理解人类指令
- 用手臂和夹爪操作物体
```

也就是说：

| 能力                     | 主要技术                     |
| ------------------------ | ---------------------------- |
| 让 G1 站稳、走路         | RL locomotion / MPC / 控制器 |
| 让 G1 知道自己在哪里     | SLAM                         |
| 让 G1 从 A 点走到 B 点   | Nav2 / 路径规划 / 避障       |
| 让 G1 抓东西、整理桌面   | VLA                          |
| 让 G1 在脑中预测动作后果 | WMA                          |
| 让 G1 听懂复杂任务并拆解 | LLM / planner / agent        |
| 让 G1 真正执行           | SDK2 / DDS / ROS2 / 低层控制 |

------

# 11. SLAM 是什么？

**SLAM** 全称是：

```
Simultaneous Localization and Mapping
同步定位与建图
```

它解决的是机器人最基础的空间问题：

> **机器人在未知环境里，一边构建地图，一边估计自己在地图中的位置。**

比如 G1 进入一个陌生房间：

```
它一开始不知道：
- 房间多大
- 墙在哪里
- 门在哪里
- 桌子在哪里
- 自己当前在地图哪个位置

SLAM 的作用：
- 用 LiDAR / 深度相机 / RGB-D / IMU / 里程计
- 一边移动
- 一边生成地图
- 同时估计自己的位姿 x, y, z, roll, pitch, yaw
```

ROS2 Nav2 官方教程也把 SLAM 用于生成 occupancy grid map，并配合 Nav2 让机器人移动；教程要求 SLAM 节点发布 `/map` topic，并提供 `map -> odom` transform。

------

# 12. SLAM 输入什么，输出什么？

## 12.1 输入

SLAM 通常需要：

| 输入             | 作用                               |
| ---------------- | ---------------------------------- |
| LiDAR scan       | 看周围墙体、障碍物、轮廓           |
| RGB-D / 深度相机 | 获取图像和深度                     |
| IMU              | 获取姿态变化、角速度、加速度       |
| Odometry         | 估计机器人短时间移动了多少         |
| TF 坐标变换      | 知道雷达、相机、机身之间的位置关系 |

------

## 12.2 输出

SLAM 通常输出：

| 输出                | 含义                           |
| ------------------- | ------------------------------ |
| `/map`              | 地图                           |
| `map -> odom`       | 地图坐标系到里程计坐标系的变换 |
| `odom -> base_link` | 机器人短期运动估计             |
| robot pose          | 机器人在地图里的位置           |
| occupancy grid      | 2D 栅格地图                    |
| point cloud map     | 3D 点云地图                    |
| pose graph          | 位姿图，用于回环检测和优化     |

`slam_toolbox` 文档中也说明，它会订阅 laser scan 和 odometry，发布 map-to-odom transform 和 map；其内部会用激光扫描和里程计构建 pose graph，并通过回环检测和图优化修正位姿。

------

# 13. SLAM 和 VLA/WMA 有什么关系？

这是非常关键的一点：

> **SLAM 解决“我在哪里”。VLA/WMA 解决“我该怎么操作物体”。**

它们不是替代关系，而是互补关系。

## 13.1 没有 SLAM，机器人会怎样？

如果没有 SLAM，机器人可能只能做：

```
站在桌前
看到桌面
抓取桌面上的物体
```

也就是局部操作。

但它很难做：

```
去厨房
找到桌子
走到桌边
拿起杯子
送到客厅
```

因为它不知道：

```
厨房在哪里？
自己在哪里？
路线怎么走？
障碍物在哪里？
```

------

## 13.2 有 SLAM 后，VLA/WMA 可以做更大的任务

有 SLAM 后，系统可以这样分工：

```
LLM / Planner:
“去厨房拿杯子”

SLAM + Navigation:
定位自己，规划路径，走到厨房

VLA / WMA:
看到杯子，控制手臂抓取

Navigation:
返回客厅

VLA / WMA:
把杯子放到桌上
```

所以完整 embodied AI 系统应该是：

```
语言任务规划
  ↓
SLAM 定位建图
  ↓
导航到目标区域
  ↓
视觉识别目标物
  ↓
VLA/WMA 操作物体
  ↓
低层控制执行
```

------

# 14. SLAM 怎么用？以 ROS2 为主线

## 14.1 最常见方案：ROS2 + slam_toolbox + Nav2

如果你做的是室内 2D 导航，最经典组合是：

```
ROS2
  + slam_toolbox
  + Nav2
  + LiDAR / depth camera
  + robot odometry
```

Nav2 官方教程的流程是：

1. 启动机器人接口；
2. 启动 Navigation2；
3. 启动 SLAM；
4. 移动机器人，让地图实时更新；
5. 保存地图。

典型安装：

```
sudo apt update
sudo apt install ros-$ROS_DISTRO-slam-toolbox
sudo apt install ros-$ROS_DISTRO-navigation2 ros-$ROS_DISTRO-nav2-bringup
```

典型流程：

```
# 1. source ROS2
source /opt/ros/humble/setup.bash

# 2. 启动机器人 bringup
# 这里换成你的 Unitree / G1 / Go2 / 自己写的 bringup
ros2 launch your_robot_bringup robot.launch.py

# 3. 启动 Nav2
ros2 launch nav2_bringup navigation_launch.py

# 4. 启动 SLAM Toolbox
ros2 launch slam_toolbox online_async_launch.py

# 5. 打开 RViz 看地图
rviz2

# 6. 建完地图后保存
ros2 run nav2_map_server map_saver_cli -f ~/map
```

Nav2 教程中也明确说，SLAM 实现需要提供 `map -> odom` transform 和 `/map` topic，之后可以在 RViz 里看 `/map`、`/tf`、`/laserscan` 等 topic。

------

## 14.2 2D SLAM 和 3D SLAM 的区别

| 类型                | 传感器                        | 输出                     | 适合场景                       |
| ------------------- | ----------------------------- | ------------------------ | ------------------------------ |
| 2D SLAM             | 2D LiDAR / 转换后的 LaserScan | 2D 栅格地图              | 室内导航、平面移动机器人       |
| 3D SLAM             | 3D LiDAR / RGB-D / Stereo     | 3D 点云地图              | 多层空间、复杂环境、人形机器人 |
| Visual SLAM         | 单目/双目/RGB-D 相机          | 相机轨迹 + 稀疏/稠密地图 | 视觉定位、AR、轻量移动         |
| LiDAR-Inertial SLAM | LiDAR + IMU                   | 高精度位姿 + 点云地图    | 机器人导航、室内外移动         |

如果你是 **G1 人形机器人**，我建议你先按阶段来：

```
阶段 1：先让传感器 topic 正常
- 相机
- LiDAR
- IMU
- robot state
- TF

阶段 2：先跑 2D/简化 SLAM
- 能看到 /map
- 能看到 /tf
- 能在 RViz 里定位

阶段 3：接 Nav2
- 能给目标点
- 能规划路径
- 能避障

阶段 4：再接 VLA/WMA
- 到桌边
- 看物体
- 抓取
- 放置
```

------

# 15. slam_toolbox 和 RTAB-Map 怎么选？

## 15.1 slam_toolbox

适合：

```
2D LiDAR
室内平面地图
Nav2 导航
快速开始
```

slam_toolbox 是 ROS 里常用的 2D SLAM 工具包，文档说明它会订阅 laser scan 和 odometry，发布 map 和 map-to-odom transform。

你可以把它理解成：

> **先用它做“机器人平面导航地图”。**

------

## 15.2 RTAB-Map

适合：

```
RGB-D 相机
双目相机
3D LiDAR
3D 建图
视觉回环检测
```

RTAB-Map 官方说明它是 RGB-D、Stereo 和 LiDAR 的 graph-based SLAM 方法，可以用于 6DoF mapping，也可以在带激光测距仪的机器人上做 3DoF mapping。

RTAB-Map 的 ROS2 包也提供传感器集成示例，包括 stereo、RGB-D camera、3D LiDAR，以及 Turtlebot/Nav2 集成示例。

所以选择建议：

| 你的目标                          | 推荐                                       |
| --------------------------------- | ------------------------------------------ |
| 先跑通室内导航                    | slam_toolbox                               |
| 想做 2D 地图 + Nav2               | slam_toolbox                               |
| 想用深度相机建 3D 图              | RTAB-Map                                   |
| 想做视觉回环和 3D 场景记忆        | RTAB-Map                                   |
| 想做大型室内点云建图              | 3D LiDAR SLAM / RTAB-Map / 其他 LiDAR SLAM |
| 想让 G1 完成“走到某地 + 操作物体” | SLAM/Nav2 + VLA/WMA                        |

------

# 16. SLAM 在宇树项目里怎么接？

你可以按这个架构理解：

```
Unitree G1 / Go2 / B2
  ↓
传感器：
- LiDAR
- RGB-D camera
- IMU
- robot state
  ↓
ROS2 topic：
- /scan
- /points
- /camera/color/image_raw
- /camera/depth/image_raw
- /imu
- /odom
- /tf
  ↓
SLAM：
- slam_toolbox / RTAB-Map / LiDAR SLAM
  ↓
输出：
- /map
- map -> odom
- robot pose
  ↓
Nav2：
- global planner
- local planner
- costmap
- obstacle avoidance
  ↓
Unitree 控制：
- 高层速度命令
- locomotion controller
- SDK2 / DDS
  ↓
机器人移动
```

如果你要接 G1，核心不是一上来就跑 VLA/WMA，而是先检查：

```
ros2 topic list
ros2 topic echo /tf
ros2 topic echo /odom
ros2 topic echo /scan
ros2 topic echo /imu
ros2 topic hz /scan
ros2 topic hz /odom
```

你必须先确认：

| 检查项                                  | 目的                   |
| --------------------------------------- | ---------------------- |
| `/scan` 是否有数据                      | LiDAR 是否正常         |
| `/odom` 是否有数据                      | 机器人短期位姿是否正常 |
| `/tf` 是否完整                          | 坐标系是否连通         |
| `base_link` 是否存在                    | 机器人主体坐标系       |
| `laser_frame` / `camera_frame` 是否正确 | 传感器外参是否正确     |
| RViz 是否能显示 laser/map               | 可视化是否正常         |

------

# 17. 为什么 SLAM 对 VLA/WMA 很重要？

因为 VLA/WMA 通常只看到局部画面，例如桌面、物体、夹爪。

但真正的机器人任务经常是：

```
“去厨房，把桌上的药盒拿过来。”
```

这句话拆开是：

| 子任务                   | 需要的技术              |
| ------------------------ | ----------------------- |
| 理解“厨房”“药盒”“拿过来” | LLM / planner           |
| 知道厨房在哪里           | SLAM map / semantic map |
| 走到厨房                 | Nav2 / locomotion       |
| 找到药盒                 | 视觉识别 / VLM          |
| 抓药盒                   | VLA / WMA               |
| 返回用户身边             | SLAM + navigation       |
| 放下药盒                 | VLA / WMA               |

所以如果你未来想做高级 AI 功能，完整路线应该是：

```
第一阶段：G1 locomotion 跑通
第二阶段：G1 传感器和 ROS2 topic 跑通
第三阶段：SLAM 建图和定位跑通
第四阶段：Nav2 或自定义导航跑通
第五阶段：VLA/WMA 操作任务跑通
第六阶段：LLM agent 做任务规划
第七阶段：把导航 + 操作 + 记忆 + 安全策略组合起来
```

------

# 18. 最后给你一个非常清晰的结论

## 18.1 UnifoLM-VLA 解决什么？

> **解决“看到物体和听到指令以后，机器人手臂/夹爪怎么操作”的问题。**

它适合：

```
桌面操作
抓取
放置
整理
擦桌
叠毛巾
双臂协作
```

------

## 18.2 UnifoLM-WMA 解决什么？

> **解决“机器人能不能预测动作后果，并用这种预测来提升决策”的问题。**

它适合：

```
未来交互预测
动作结果模拟
合成数据生成
策略增强
更高级的 model-based robot learning
```

------

## 18.3 SLAM 解决什么？

> **解决“机器人在哪里，环境地图是什么样”的问题。**

它适合：

```
建图
定位
导航
避障
移动到目标地点
把局部操作扩展成全屋任务
```

------

# 19. 我的建议：你现在应该怎么学

结合你现在研究 Unitree G1、SDK、ROS2、RL 和 VLA/WMA，我建议顺序是：

```
1. 先彻底理解 Unitree SDK2 / DDS / low_state / low_cmd / high_state / high_cmd
2. 跑通 G1 的基础控制和仿真
3. 跑通 locomotion RL：让机器人稳定走
4. 跑通 ROS2 topic 桥接：/tf /odom /scan /camera
5. 跑通 SLAM：至少在 RViz 里看到地图
6. 跑通 Nav2：能从 A 点走到 B 点
7. 跑通 VLA：站在桌前完成抓取/放置
8. 再研究 WMA：用世界模型预测未来动作结果
9. 最后接 LLM Agent：把复杂任务拆成导航 + 操作 + 反馈
```

最简洁地说：

> **走路靠 RL/控制器，知道自己在哪靠 SLAM，去哪里靠 Navigation，怎么用手完成任务靠 VLA，怎么预测动作后果靠 WMA，怎么理解复杂人类任务靠 LLM Agent。**