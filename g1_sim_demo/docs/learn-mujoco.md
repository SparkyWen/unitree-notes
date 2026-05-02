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

我会先把“高层/低层”按机器人控制架构讲清楚，再结合宇树 SDK 里的典型命令形式解释，避免把它误解成“高层=一整套编译好的动作”。

Thought for 29s

David，你的理解**大方向是对的**，但需要稍微修正一下：

> **高层命令不是简单等于“已经编译好的一整套动作”。**
>  更准确地说：**高层命令是发给宇树内置运动控制器 / 运动服务的“意图级命令”**，比如“站起来、趴下、以 0.3m/s 往前走、保持平衡站立、跟随轨迹走”。
>
> **低层命令基本就是发给各个关节电机的控制目标**，比如某个电机的目标角度 `q`、目标速度 `dq`、前馈力矩 `tau`、刚度 `Kp`、阻尼 `Kd`。

------

# 1. 一句话理解

你可以这样区分：

| 层级                    | 你告诉机器人什么                                      | 谁负责算动作细节   | 典型命令                                                     |
| ----------------------- | ----------------------------------------------------- | ------------------ | ------------------------------------------------------------ |
| **高层命令 High-level** | “我要机器人走、站、坐、转向、跟轨迹”                  | 宇树内置运动控制器 | `Move(vx, vy, vyaw)`、`StandUp()`、`BalanceStand()`、`TrajectoryFollow()` |
| **低层命令 Low-level**  | “第 1 个电机到多少角度，第 2 个电机用多少 Kp/Kd/力矩” | 你自己的程序       | `motor_cmd[i].q / dq / kp / kd / tau`                        |

------

# 2. 高层命令到底是什么？

在宇树四足机器人，比如 Go1 / Go2 里，高层命令可以理解为：

> **你不是直接控制每个电机，而是把运动意图发给宇树已经写好的运动控制系统。**

例如在 Go1 的 `HighCmd` 里，官方文档列出的模式包括：

| mode      | 含义               |
| --------- | ------------------ |
| `0`       | Idle               |
| `1`       | Standing，力控站立 |
| `2`       | 按目标速度行走     |
| `5`       | 趴下 / stand down  |
| `6`       | 站起来 / stand up  |
| `7`       | 阻尼模式           |
| `8`       | 恢复站立           |
| `9`       | backflip           |
| `12 / 13` | dance1 / dance2    |

官方文档里明确写到，Go1 的 `HighCmd` 中 `mode=2` 是“Walking, following target velocity”，也就是机器人按照目标速度行走；`velocity[2]` 是机体坐标系下的前进速度和侧向速度，`yawSpeed` 是旋转速度。

所以高层命令不只是“播放一个动作包”。它分两类：

## A. 连续控制类高层命令

比如：

```
sport_client.Move(0.3, 0, 0.3);
```

意思是：

> 让机器人以 `0.3 m/s` 前进，同时以 `0.3 rad/s` 转向。

在 Go2 的 SDK2 示例中，`velocity_move` 对应的就是 `sport_client.Move(0.3, 0, 0.3)`；代码注释也写了这是“target velocity walking”，由速度和 yaw speed 控制。

这不是一个固定动作，因为你可以每 2ms / 5ms 改一次速度，机器人会持续根据你的目标速度实时调整步态。

------

## B. 预定义动作 / 状态切换类高层命令

比如：

```
sport_client.StandUp();
sport_client.StandDown();
sport_client.BalanceStand();
sport_client.Damp();
sport_client.RecoveryStand();
sport_client.Sit();
sport_client.RiseSit();
```

这些更接近你说的“已经写好的动作 / 状态”。Go2 示例代码里就有 `StandUp()`、`StandDown()`、`Damp()`、`RecoveryStand()`、`Sit()` 等高层接口。

但注意：
 **即使是这些动作，也不是你直接拿到每个电机轨迹去发。**
 你只是调用一个高层接口，真正的关节轨迹、平衡控制、落脚点规划、力矩控制，都是宇树底层控制器内部完成的。

------

# 3. 所以“高层命令 = 完整编译好的动作”对不对？

**不完全对。**

更准确地说：

> 高层命令 = 发给宇树内置运动控制器的“运动意图 / 行为指令”。

它可能是：

| 类型         | 例子                                | 是否像“动作包”               |
| ------------ | ----------------------------------- | ---------------------------- |
| 状态切换     | `StandUp()`、`StandDown()`、`Sit()` | 比较像                       |
| 连续速度控制 | `Move(0.3, 0, 0.3)`                 | 不像，是实时控制目标         |
| 姿态控制     | 调整 body height、roll、pitch、yaw  | 不像，是目标状态             |
| 轨迹跟随     | `TrajectoryFollow(path)`            | 半像，但轨迹可以由你动态生成 |
| 特技动作     | backflip、dance                     | 很像预设动作                 |

Go2 的轨迹跟随示例中，程序构造了一串 `PathPoint`，包含 `x, y, yaw, vx, vy, vyaw`，然后调用 `TrajectoryFollow(path)`，说明高层也可以不是固定动作，而是你给一条路径，让内置运动控制器去执行。

------

# 4. 高层命令背后发生了什么？

你调用高层命令时，大概流程是：

```
你的程序
  ↓
高层命令：Move(前进速度, 侧向速度, 转向速度)
  ↓
宇树内置运动控制器 / Sport Mode / MFC
  ↓
步态规划：什么时候抬哪条腿
  ↓
足端轨迹规划：脚往哪里落
  ↓
身体平衡控制：身体姿态如何保持
  ↓
逆运动学 / 动力学控制
  ↓
每个关节电机的 q / dq / torque / Kp / Kd
  ↓
电机执行
```

所以你只管说：

> “我要往前走。”

宇树内置控制器负责：

> “哪条腿先抬、脚落在哪里、膝关节转多少、髋关节转多少、身体怎么保持平衡、摔倒怎么恢复。”

------

# 5. 低层命令是什么？

低层命令就是你绕过高层运动控制器，直接控制关节电机级别的数据。

在旧版 `unitree_legged_sdk` 的 `LowCmd` 里，官方代码结构显示：`LowCmd` 里面有 `motorCmd[20]`，每个 `MotorCmd` 包含：

```
mode
q
dq
tau
Kp
Kd
```

其中 `q` 是目标角度，`dq` 是目标速度，`tau` 是目标输出力矩，`Kp` 是位置刚度，`Kd` 是速度阻尼。

Go2 SDK2 的低层示例也类似。示例中定义了低层 DDS topic：

```
#define TOPIC_LOWCMD "rt/lowcmd"
#define TOPIC_LOWSTATE "rt/lowstate"
```

并且创建 `LowCmd_` publisher 和 `LowState_` subscriber，通过 `rt/lowcmd` 发布低层命令，通过 `rt/lowstate` 接收低层状态。

------

# 6. 低层命令是不是“发给电机的命令”？

**是，但还要更精确一点：**

> 低层命令是发给机器人各个关节电机控制接口的目标值，不一定是最原始的电流 / PWM 信号。

你通常发的是：

```
motor_cmd[i].q()    = 目标关节角度
motor_cmd[i].dq()   = 目标关节速度
motor_cmd[i].kp()   = 位置刚度
motor_cmd[i].kd()   = 速度阻尼
motor_cmd[i].tau()  = 前馈力矩
```

例如 Go2 低层示例中，初始化时把 20 个电机都切到伺服模式，然后设置每个电机的 `q / dq / kp / kd / tau`。

后面示例又对某个电机设置：

```
low_cmd.motor_cmd()[2].q() = qDes[2];
low_cmd.motor_cmd()[2].dq() = 0;
low_cmd.motor_cmd()[2].kp() = Kp[2];
low_cmd.motor_cmd()[2].kd() = Kd[2];
low_cmd.motor_cmd()[2].tau() = 0;
```

然后计算 CRC 并发布 `low_cmd`。

所以你的理解可以改成：

> **低层命令不是“直接给电机通电多少”那么原始，而是给每个电机 / 关节发送目标角度、速度、力矩和 PD 参数。**

------

# 7. 高层和低层最大的区别：控制责任不同

## 高层控制：宇树负责“怎么做”

你说：

```
往前走 0.3m/s
```

宇树控制器自己决定：

```
左前腿什么时候抬
右后腿什么时候抬
身体怎么保持平衡
脚落在哪里
每个关节角度是多少
每个电机输出多大力矩
```

适合：

- 让机器人稳定行走
- 做应用层开发
- 做导航、巡检、交互
- 做视觉 / 语音 / Agent 控制机器人
- 不想自己写全身控制器

------

## 低层控制：你负责“怎么做”

你直接说：

```
第 0 个电机 q = 0.1
第 1 个电机 q = 1.2
第 2 个电机 q = -2.0
Kp = 5
Kd = 1
tau = 0
```

这时你自己要负责：

- 关节轨迹是否连续
- 电机是否超限
- 腿会不会打架
- 身体会不会倒
- 机器人重心是否稳定
- 足端是否打滑
- 力矩是否过大
- 通信频率是否稳定

适合：

- 做强化学习控制策略部署
- 做自研 MPC / WBC / 全身控制
- 做关节空间轨迹实验
- 做动力学控制研究
- 做底层电机控制实验

------

# 8. 用汽车类比最好理解

| 类比     | 高层命令                         | 低层命令                                 |
| -------- | -------------------------------- | ---------------------------------------- |
| 开车     | “以 60km/h 往前开，向左转 10 度” | “每个轮子的扭矩是多少，转向机角度是多少” |
| 无人机   | “悬停、上升、向前飞”             | “四个电机分别多少转速”                   |
| 机器人狗 | “站起来、往前走、转向”           | “12 个关节分别到什么角度、输出多少力矩”  |

所以：

> **高层像驾驶员指令。**
>  **低层像电机级控制。**

------

# 9. 为什么初学者通常先用高层命令？

因为四足机器人真正困难的不是“让一个电机转”，而是：

```
让 12 个电机协调运动，同时保持身体不倒。
```

如果你用低层命令控制四足机器人，哪怕只让一个关节动作，也可能导致：

- 姿态突然变化
- 机器人失去平衡
- 腿部结构冲击
- 电机过流 / 过热
- 机器人摔倒
- 损坏减速器或关节

所以实际开发路线通常是：

```
第一阶段：高层命令
    ↓
Move / StandUp / StandDown / BalanceStand / TrajectoryFollow

第二阶段：读取状态
    ↓
HighState / LowState / IMU / joint state / odometry

第三阶段：半低层控制
    ↓
只控制机械臂、头部、单腿、特定关节

第四阶段：完整低层控制
    ↓
自己写 gait planner / whole-body controller / RL policy
```

------

# 10. 高层状态和低层状态也不同

除了命令不同，反馈状态也不同。

## HighState / SportModeState

高层状态通常更偏“机器人整体运动状态”，比如：

- 当前模式
- 当前步态
- 机体位置
- 机体速度
- yaw speed
- body height
- IMU
- 足端位置
- 足端速度

旧版 `HighState` 里就包含 `mode`、`gaitType`、`position`、`bodyHeight`、`velocity`、`yawSpeed`、`footPosition2Body` 等整体运动信息。

## LowState

低层状态通常更偏“电机和传感器反馈”，比如：

- 每个电机当前角度 `q`
- 当前速度 `dq`
- 当前估计力矩 `tauEst`
- 温度
- IMU
- 足底力
- 电池状态

旧版 `LowState` 中包含 `motorState[20]`、IMU、BMS、足底力等低层反馈。

------

# 11. 结合宇树机械臂 Z1 再看一遍

如果是宇树 Z1 机械臂，概念也类似。

官方 Z1 文档中，高层接口里有：

```
MoveJ()
MoveL()
MoveC()
backToStart()
```

这些是更高层的运动接口，比如关节空间运动、直线运动、圆弧运动、回到起点。官方文档说明 `highcmd_basic` 适合用户简单理解如何控制机械臂，并且 `armCtrlByFSM()` 会调用 `unitreeArm` 类里的 `MoveJ()`、`MoveL()`、`MoveC()`、`backToStart()` 等方法。

而 Z1 的低层开发文档明确说，如果用户想直接控制电机的：

```
q, qdot, tau_f, kp, kd
```

就看 `lowcmd_development`。文档还给出了最终输出力矩的 PD 形式。

这和四足机器人是一致的：

```
高层：MoveJ / MoveL / MoveC
低层：q / qdot / tau / kp / kd
```

------

# 12. 最核心的总结

你可以记住这句话：

> **高层命令控制“机器人行为”，低层命令控制“关节电机”。**

更完整地说：

```
高层命令：
    我想让机器人做什么
    例如：站起来、往前走、转向、跟随轨迹、坐下、恢复站立

低层命令：
    每个电机应该怎么动
    例如：第 i 个关节目标角度 q、目标速度 dq、前馈力矩 tau、Kp、Kd
```

所以你的两个问题可以这样回答：

## 问题 1：高层命令指的是已经编译好的完整动作吗？

**部分是，但不完全是。**

- `StandUp()`、`Sit()`、`Dance()`、`Backflip()` 这类比较像预设动作。
- `Move(vx, vy, vyaw)`、`TrajectoryFollow(path)` 这类不是固定动作，而是连续运动目标。
- 本质上，高层命令是调用宇树内置运动控制器，让它帮你完成步态、平衡和电机控制。

## 问题 2：低层命令就是发给电机的命令吗？

**基本是。**

但更准确地说：

- 你发的是关节 / 电机级目标值。
- 包括 `q`、`dq`、`tau`、`Kp`、`Kd`。
- 它不是最底层的 PWM 或电流环，而是比高层运动控制更接近电机的一层控制接口。

------

# 13. 最后给你一个非常实用的判断标准

以后你看到宇树代码，可以这样判断：

| 代码里出现什么         | 大概率是什么层 |
| ---------------------- | -------------- |
| `SportClient`          | 高层           |
| `Move()`               | 高层           |
| `StandUp()`            | 高层           |
| `StandDown()`          | 高层           |
| `BalanceStand()`       | 高层           |
| `TrajectoryFollow()`   | 高层           |
| `HighCmd`              | 高层           |
| `SportModeState`       | 高层状态       |
| `LowCmd`               | 低层           |
| `LowState`             | 低层状态       |
| `motor_cmd()[i].q()`   | 低层           |
| `motor_cmd()[i].kp()`  | 低层           |
| `motor_cmd()[i].tau()` | 低层           |
| `rt/lowcmd`            | 低层 DDS topic |
| `rt/lowstate`          | 低层 DDS topic |

最简单的开发建议是：

> **做应用、导航、交互、Agent 控制：优先用高层。**
>  **做控制算法、强化学习、全身控制、电机实验：才进入低层。**

我会把它理解为“状态反馈层级”的区别来讲：**High State 更像机器人整体运动状态，Low State 更像传感器和电机原始反馈状态**。下面我会结合宇树四足机器人和机械臂的常见字段解释。

Thought for 21s

David，**Low State 和 High State 的区别，本质上不是“数据多/少”的区别，而是“反馈状态的抽象层级不同”。**

一句话：

> **Low State = 机器人底层硬件/关节/电机/传感器反馈。**
>  **High State = 机器人整体运动状态/步态状态/机体状态反馈。**

也可以这样理解：

```
Low State  关注：每个电机现在怎么样？
High State 关注：整台机器人现在在做什么、怎么运动？
```

------

# 1. 先纠正一个关键点：State 不是 Command

前面我们说过：

```
HighCmd / SportClient  = 高层命令
LowCmd                 = 低层命令
HighState / SportModeState = 高层状态反馈
LowState               = 低层状态反馈
```

所以：

| 类型              | 含义                     |
| ----------------- | ------------------------ |
| **Cmd / Command** | 你发给机器人的控制命令   |
| **State**         | 机器人返回给你的当前状态 |

也就是说：

```
LowCmd  是你发出去的低层电机控制目标
LowState 是机器人返回来的低层电机/传感器反馈

HighCmd / SportClient 是你发出去的高层运动意图
HighState / SportModeState 是机器人返回来的整体运动状态
```

------

# 2. Low State 是什么？

**Low State 是低层状态反馈。**

它主要告诉你：

> 每个关节电机当前的角度、速度、估计力矩、温度，以及 IMU、电池、足底力等底层传感器信息。

在宇树旧版 `unitree_legged_sdk` 的 `LowState` 结构中，官方代码里包含 `IMU imu`、`motorState[20]`、`BmsState bms`、`footForce`、`footForceEst`、`tick`、`wirelessRemote` 等字段，并且注释写的是 `LowState; // low level feedback`。

------

## 2.1 Low State 里面最重要的是 MotorState

在低层状态里，最核心的是：

```
motorState[i]
```

每一个 `motorState[i]` 对应一个电机/关节。

典型字段包括：

| 字段                 | 含义             | 解释                   |
| -------------------- | ---------------- | ---------------------- |
| `mode`               | 电机当前模式     | 例如伺服、阻尼、过热等 |
| `q`                  | 当前关节角度     | 单位通常是 rad         |
| `dq`                 | 当前关节速度     | 单位通常是 rad/s       |
| `ddq`                | 当前关节加速度   | 单位通常是 rad/s²      |
| `tauEst` / `tau_est` | 当前估计输出力矩 | 单位通常是 N·m         |
| `temperature`        | 电机温度         | 用于判断过热风险       |
| `q_raw` / `dq_raw`   | 原始数据         | 一般是底层保留/调试用  |

旧版 `MotorState` 中，官方代码明确列出了 `q` 当前角度、`dq` 当前速度、`ddq` 当前加速度、`tauEst` 当前估计输出力矩和 `temperature` 当前温度。

------

## 2.2 Low State 更接近“机器人身体的神经末梢”

你可以把 Low State 想象成机器人身体里每个关节的实时反馈：

```
左前腿髋关节现在多少度？
左前腿膝关节现在转多快？
右后腿小腿电机当前力矩多大？
电机有没有过热？
IMU 当前姿态是多少？
足底有没有受力？
电池电量怎么样？
```

所以 Low State 适合用来做：

- 关节控制
- 电机状态监控
- 强化学习控制策略部署
- 自研 MPC / WBC / 全身控制
- 检查关节角度是否超限
- 判断电机是否过热
- 读取足底力
- 做底层控制算法调试

------

# 3. High State 是什么？

**High State 是高层状态反馈。**

它主要告诉你：

> 机器人整体现在处于什么运动模式、什么步态、身体高度是多少、机体速度是多少、位置估计是多少、脚相对身体在哪里。

在旧版 `unitree_legged_sdk` 中，`HighState` 包含 `mode`、`gaitType`、`footRaiseHeight`、`position`、`bodyHeight`、`velocity`、`yawSpeed`、`rangeObstacle`、`footPosition2Body`、`footSpeed2Body` 等字段，官方注释写的是 `HighState; // high level feedback`。

在较新的 SDK2 / ROS2 体系中，很多地方不再叫 `HighState`，而更常见地叫 **`SportModeState`**。Unitree ROS2 文档说明，SportMode state 包含机器人的 position、velocity、foot position 等运动状态；Low-level state 则包含 motors states、power information 和其他 low-level states。

------

## 3.1 High State / SportModeState 关心的是整机运动

典型字段包括：

| 字段                                       | 含义               | 解释                                                         |
| ------------------------------------------ | ------------------ | ------------------------------------------------------------ |
| `mode`                                     | 当前运动模式       | 例如 idle、balance stand、locomotion、sit、recovery stand 等 |
| `gaitType` / `gait_type`                   | 当前步态类型       | 例如 trot、run、climb stair 等                               |
| `position`                                 | 机器人位置估计     | 通常来自自身里程计，可能会漂移                               |
| `velocity`                                 | 机器人整体速度     | 例如前进速度、侧向速度、垂直速度                             |
| `yawSpeed`                                 | 机体偏航角速度     | 也就是绕 z 轴转动速度                                        |
| `bodyHeight`                               | 机身高度           | 当前身体高度                                                 |
| `footRaiseHeight`                          | 抬脚高度           | 行走时脚抬起的高度                                           |
| `footPosition2Body` / `foot_position_body` | 足端相对身体的位置 | 脚在机体坐标系中的位置                                       |
| `footSpeed2Body` / `foot_speed_body`       | 足端相对身体的速度 | 脚相对身体移动速度                                           |
| `rangeObstacle`                            | 障碍物距离         | 某些机型/模式下可用                                          |

Unitree ROS2 文档中的 SportModeState 定义也列出了 `mode`、`gait_type`、`foot_raise_height`、`position`、`body_height`、`velocity`、`yaw_speed`、`foot_force`、`foot_position_body`、`foot_speed_body` 等字段。

------

# 4. 最核心区别：Low State 是“关节级”，High State 是“整机级”

可以直接看这个表：

| 对比维度   | Low State                                        | High State / SportModeState                              |
| ---------- | ------------------------------------------------ | -------------------------------------------------------- |
| 抽象层级   | 低层                                             | 高层                                                     |
| 关注对象   | 电机、关节、IMU、电池、足底力                    | 整机运动状态、步态、速度、位置、身体高度                 |
| 典型字段   | `motorState[i].q`、`dq`、`tauEst`、`temperature` | `mode`、`gaitType`、`position`、`velocity`、`bodyHeight` |
| 主要用途   | 底层控制、关节控制、控制算法、诊断               | 应用开发、导航、运动状态读取、任务层决策                 |
| 数据来源   | 电机/传感器/底层控制器反馈                       | 运动控制器加工后的整体状态                               |
| 你看到的是 | 每个关节当前怎么样                               | 机器人整体现在在干什么                                   |
| 对应命令   | `LowCmd`                                         | `HighCmd` / `SportClient`                                |
| 适合谁用   | 控制算法开发者                                   | 应用开发者、导航/交互开发者                              |

------

# 5. 一个非常形象的例子

假设机器人正在往前走。

## High State 会告诉你：

```
机器人当前处于 locomotion 模式
当前步态是 trot
身体高度是 0.32m
整体速度 vx = 0.3m/s
yaw speed = 0.1rad/s
左前脚相对身体的位置是 ...
右后脚相对身体的位置是 ...
```

也就是说，High State 的视角是：

> **这台机器人现在整体在怎么运动？**

------

## Low State 会告诉你：

```
第 0 个电机当前角度 q = ...
第 0 个电机当前速度 dq = ...
第 0 个电机当前估计力矩 tauEst = ...
第 0 个电机温度 temperature = ...

第 1 个电机当前角度 q = ...
第 1 个电机当前速度 dq = ...
第 1 个电机当前估计力矩 tauEst = ...
...
IMU 当前 roll/pitch/yaw 是 ...
足底力是多少 ...
电池电量是多少 ...
```

也就是说，Low State 的视角是：

> **机器人每个关节和底层硬件现在具体是什么状态？**

------

# 6. High State 不是“更准确”，Low State 也不是“更完整”

这里很容易误解。

## 不是说 High State 更高级就一定更准确

High State 中的 `position` 通常是经过状态估计/里程计得到的，它对应用开发很方便，但可能会漂移。旧版 `HighState` 代码注释里也说明 `position` 是来自自身 odometry 的 inertial frame 位置，通常会 drift。

也就是说：

```
High State 的 position 很方便，但不能盲目当作绝对真实位置。
```

如果你要做高精度定位，通常还要结合：

- LiDAR SLAM
- VIO
- GPS / RTK
- 外部定位系统
- 视觉定位
- 地图融合

------

## 也不是说 Low State 一定更适合所有开发

Low State 虽然更底层，但不代表你做应用就应该优先用它。

如果你只是想让机器人：

```
走到某个地方
巡逻
跟随人
做语音交互
根据 Agent 指令行动
```

你主要应该用：

```
High State / SportModeState + 高层运动接口
```

如果你直接拿 Low State 做全关节控制，你就要自己承担：

- 步态规划
- 平衡控制
- 关节轨迹生成
- 足端落点规划
- 力矩安全限制
- 摔倒保护
- 电机保护

这对初学者非常危险。

------

# 7. 为什么 High State 有时也包含 motorState？

这是一个很关键的细节。

在旧版 `unitree_legged_sdk` 的 `HighState` 结构里，确实也包含了：

```
IMU imu;
std::array<MotorState, 20> motorState;
BmsState bms;
footForce;
footForceEst;
```

然后在此基础上又增加了：

```
mode
gaitType
position
bodyHeight
velocity
yawSpeed
footPosition2Body
footSpeed2Body
```

也就是说，在旧版 SDK 中：

> **HighState 不是完全没有底层信息，而是在部分底层反馈之上，又额外提供了高层运动状态。**

旧版代码中可以看到，`HighState` 先包含 `imu`、`motorState`、`bms`、`footForce`，随后又包含 `mode`、`gaitType`、`position`、`velocity`、`footPosition2Body` 等整体运动字段。

所以更准确地说：

```
LowState  = 底层反馈为主
HighState = 底层反馈 + 高层运动控制器加工后的整体状态
```

但在 Go2 / SDK2 / ROS2 里，概念拆得更清楚：

```
LowState       低层状态
SportModeState 高层运动状态
```

Unitree ROS2 文档中也是这样分开的：Sportmode state 用于获取 position、velocity、foot position 等运动状态；Low-level state 用于获取 motors states、power information 等低层状态。

------

# 8. Low State 和 High State 分别怎么用？

## 场景 1：我要知道机器人是不是在走路

用 **High State / SportModeState**。

你看：

```
state.mode
state.gaitType
state.velocity
state.yawSpeed
```

例如：

```
mode = locomotion
gaitType = trot
velocity[0] = 0.3
yawSpeed = 0.1
```

你就知道机器人正在以某个速度运动。

------

## 场景 2：我要知道第 3 个关节现在角度是多少

用 **Low State**。

你看：

```
low_state.motorState[3].q
```

或者 SDK2/ROS2 中类似：

```
low_state.motor_state[3].q
```

这表示第 3 个关节当前角度。

------

## 场景 3：我要判断某个电机是否过热

用 **Low State**。

你看：

```
low_state.motorState[i].temperature
```

High State 通常不是专门给你做电机健康诊断的。

------

## 场景 4：我要让机器人根据导航算法移动

主要用 **High State / SportModeState**。

你需要知道：

```
机器人当前整体位置
机器人当前整体速度
机器人当前朝向
机器人当前步态/运动模式
```

然后你通过高层接口发：

```
Move(vx, vy, vyaw)
```

这样更安全。

------

## 场景 5：我要部署强化学习训练出来的关节策略

主要用 **Low State + Low Cmd**。

强化学习 policy 常见输入可能是：

```
关节角度 q
关节速度 dq
IMU 姿态
IMU 角速度
历史动作
目标速度
```

这些大量来自 Low State。

然后 policy 输出：

```
目标关节角度
目标关节速度
PD 参数
或者目标力矩
```

再通过 LowCmd 发给机器人。

------

# 9. 用人体类比非常好理解

你可以把机器人想象成人。

## Low State 像身体神经反馈

```
膝盖弯曲多少度？
脚踝速度是多少？
肌肉当前用力多少？
体温是多少？
脚底有没有压力？
身体 IMU 感觉到倾斜了吗？
```

这是“身体硬件层”。

------

## High State 像大脑对动作的整体判断

```
我现在是在走路
我现在是小跑步态
我正在往前移动
我身体高度是多少
我脚相对身体在哪里
我当前位置大概在哪里
```

这是“行为状态层”。

------

# 10. 和 LowCmd / HighCmd 的对应关系

这点非常重要：

| 命令                      | 状态反馈                       | 含义                                   |
| ------------------------- | ------------------------------ | -------------------------------------- |
| `LowCmd`                  | `LowState`                     | 你控制电机，机器人返回电机/传感器状态  |
| `HighCmd` / `SportClient` | `HighState` / `SportModeState` | 你控制整机行为，机器人返回整体运动状态 |

可以这样画：

```
低层控制闭环：

你的控制器
  ↓ LowCmd：q / dq / tau / kp / kd
机器人电机
  ↓ LowState：当前 q / dq / tauEst / temperature
你的控制器继续计算下一帧命令
高层控制闭环：

你的应用程序
  ↓ HighCmd / SportClient：Move / StandUp / Sit / TrajectoryFollow
宇树内置运动控制器
  ↓ HighState / SportModeState：mode / gait / velocity / position / foot position
你的应用程序继续决定下一步任务
```

------

# 11. 你应该优先读哪个 State？

这取决于你的开发目标。

## 如果你做应用层项目

比如：

- 语音控制机器人
- 让机器人巡逻
- 机器人导航
- Agent 控制机器人
- 机器人跟随人
- 机器人展示动作
- 机器人作为产品 Demo

优先读：

```
High State / SportModeState
```

因为你最关心的是：

```
机器人整体在哪里？
当前有没有走？
速度是多少？
姿态是否稳定？
当前模式是什么？
```

------

## 如果你做控制算法项目

比如：

- 自研步态
- 强化学习控制
- 关节空间控制
- 力矩控制
- 电机保护
- 机械臂精细控制
- 运动控制论文复现

优先读：

```
Low State
```

因为你最关心的是：

```
每个关节角度是多少？
速度是多少？
力矩是多少？
电机温度是多少？
IMU 原始/底层状态如何？
```

------

# 12. 最容易混淆的地方

## 混淆 1：High State 是不是“高层命令执行结果”？

**可以这样理解，但不完全等于。**

High State / SportModeState 确实会反映高层运动控制器当前的状态，例如：

```
当前 mode
当前 gait type
当前 velocity
当前 body height
当前 foot position
```

但它不是简单告诉你“命令成功/失败”。它更像是：

> 高层运动控制器根据传感器和状态估计后，对整机运动状态的实时反馈。

------

## 混淆 2：Low State 是不是只在 Low Level 控制时才有？

不一定。

很多情况下，即使你用高层控制，也仍然可以读取 Low State，因为电机状态和 IMU 状态一直存在。Unitree ROS2 文档中也把读取 Sportmode state 和读取 Low-level state 分别作为状态获取方式介绍：一个用于运动状态，一个用于低层电机/电源等状态。

但具体能否同时安全地“高层控制 + 低层控制某些部位”，要看机型、固件、SDK、控制模式，不可以随便混用。

------

## 混淆 3：Low State 里的 `q` 是我发的目标角度吗？

不是。

Low State 里的：

```
motorState[i].q
```

是**当前反馈角度**。

LowCmd 里的：

```
motorCmd[i].q
```

才是**你希望它到达的目标角度**。

所以要区分：

```
LowCmd.motorCmd[i].q     = 我想让电机去哪里
LowState.motorState[i].q = 电机现在实际在哪里
```

------

# 13. 举一个完整控制循环例子

假设你想做低层 PD 控制，让某个关节到达目标角度。

你会这样做：

```
1. 读取 LowState
   当前角度 q_current
   当前速度 dq_current

2. 计算目标
   q_desired = 1.0 rad
   dq_desired = 0

3. 发送 LowCmd
   motorCmd[i].q = q_desired
   motorCmd[i].dq = dq_desired
   motorCmd[i].kp = 20
   motorCmd[i].kd = 1
   motorCmd[i].tau = 0

4. 下一帧再读取 LowState
   看 q_current 有没有接近 q_desired
```

这个闭环里，LowState 是反馈，LowCmd 是控制。

------

# 14. 如果是高层运动控制，流程会变成这样

假设你想让 Go2 往前走：

```
1. 发送高层命令
   Move(0.3, 0, 0)

2. 机器人内置运动控制器自己规划步态和平衡

3. 你读取 HighState / SportModeState
   mode = locomotion
   velocity[0] ≈ 0.3
   gait_type = trot
   body_height = ...
   foot_position_body = ...

4. 如果发现速度不对，再调整 Move 的参数
```

这个闭环里，你不需要关心每个电机的目标角度。

------

# 15. 最终总结

你可以这样记：

```
Low State：
    “每个关节、电机、底层传感器现在是什么状态？”

High State / SportModeState：
    “整台机器人现在处于什么运动模式、步态、速度、位置和身体状态？”
```

最核心区别：

| 问题                        | 应该看什么                  |
| --------------------------- | --------------------------- |
| 机器人现在整体是不是在走？  | High State                  |
| 当前是什么步态？            | High State                  |
| 当前机体速度是多少？        | High State                  |
| 当前身体高度是多少？        | High State                  |
| 当前足端相对身体在哪里？    | High State / SportModeState |
| 第 5 个电机现在角度是多少？ | Low State                   |
| 某个关节速度是多少？        | Low State                   |
| 某个电机力矩是多少？        | Low State                   |
| 某个电机有没有过热？        | Low State                   |
| 电池/足底力/IMU 底层反馈？  | Low State                   |

最重要的一句话：

> **Low State 是“硬件/关节级反馈”，High State 是“整机/运动级反馈”。**
>  做应用和导航，主要看 High State；做电机控制、强化学习和全身控制，主要看 Low State。

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
