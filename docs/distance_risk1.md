# ROS2 / Nav2 中“距离风险”的做法，以及视觉模型如何结合它解决“远处障碍也被判风险”问题

> 生成日期：2026-05-24  
> 目标问题：当前机器人只会判断“前方是否有障碍”，导致即使障碍很远，也被判定为风险。本文专门从 ROS2 / Nav2 的做法出发，解释如何把视觉模型接入 ROS2 导航体系，让风险判断从二值判断变成“距离、速度、轨迹、语义、置信度、时间稳定性”共同决定的系统。

---

## 0. 最重要的结论

你的问题本质上不是“视觉模型不够聪明”，而是**风险建模方式过于粗糙**。

你现在很可能类似这样做：

```python
if front_has_obstacle:
    risk = True
else:
    risk = False
```

这会出现两个严重问题：

1. **没有距离**：3 米外的椅子和 20 厘米前的墙被当成同一种风险。
2. **没有运动意图**：机器人原地旋转、倒车、慢速前进、快速前进，都被同一个“前方有障碍”逻辑处理。
3. **没有轨迹预测**：障碍虽然在视野里，但未必在机器人接下来 1 秒的 footprint 运动轨迹上。
4. **没有速度相关制动距离**：速度越快，需要越早减速；速度很慢时，不应该因为远处障碍直接急停。
5. **没有语义和置信度**：视觉模型看到“远处背景 / 阴影 / 地面纹理”时，可能也触发风险。
6. **没有时间滤波**：单帧误检就触发风险，容易导致机器人抖动或冻结。

ROS2 / Nav2 的成熟做法不是“看到障碍 = 风险”，而是下面这种分层结构：

```text
Camera / Depth / RGBD / LiDAR / Vision Model
        ↓
LaserScan / PointCloud2 / Segmentation Mask / Confidence / Semantic Cost
        ↓
Nav2 Costmap Layers
  - ObstacleLayer / VoxelLayer / STVL
  - Semantic Segmentation Layer
  - DenoiseLayer
  - InflationLayer
        ↓
Local Controller
  - Regulated Pure Pursuit
  - DWB
  - MPPI
        ↓
Collision Monitor
  - stop zone
  - slowdown zone
  - velocity limit zone
  - approach / time-to-collision model
        ↓
cmd_vel_out
```

因此，我建议你的视觉模型不要直接输出最终 `risk=True/False`，而应该输出下面这些信息之一：

| 推荐输出 | 说明 | 适合程度 |
|---|---|---|
| `PointCloud2` | 把视觉深度或深度模型投影成 3D 点云，交给 Nav2 costmap / Collision Monitor | 强烈推荐 |
| `LaserScan` | 把深度图转换成 2D 扫描，交给 ObstacleLayer / Collision Monitor | 简单、稳定、容易落地 |
| `segmentation mask + confidence + aligned pointcloud` | 把语义分割结果写入 semantic costmap | 适合你的“视觉模型”路线 |
| `nearest_distance + class + confidence + angle` | 如果暂时不接完整 Nav2 costmap，可以自己做轻量风险模块 | 可作为过渡方案 |

---

## 1. ROS2 / Nav2 为什么不会简单地“前方有障碍就判风险”

Nav2 的核心思想是：

> 障碍本身不是风险；**障碍与机器人当前速度、方向、未来轨迹、距离、语义、传感器置信度共同决定风险。**

在 Nav2 里，“风险”通常分散在四个层面处理：

| 层级 | ROS2 / Nav2 组件 | 作用 | 解决你的问题的方式 |
|---|---|---|---|
| 感知输入层 | `LaserScan`, `PointCloud2`, depth image, segmentation mask | 提供距离、空间位置、语义类别 | 不再只给 `front_has_obstacle` |
| 地图代价层 | `ObstacleLayer`, `VoxelLayer`, `STVL`, `SemanticSegmentationLayer`, `InflationLayer` | 把障碍转成局部代价地图 | 远障碍可以是低优先级或不在局部窗口内 |
| 控制器层 | RPP / DWB / MPPI | 预测未来轨迹并选择安全速度 | 只对未来轨迹上会碰撞的障碍减速或停车 |
| 安全监控层 | `nav2_collision_monitor` | 在 cmd_vel 输出前做最后安全过滤 | 用 stop/slowdown/approach/TTC，而不是二值判断 |

---

## 2. Nav2 Costmap：先把“障碍”变成“距离相关代价”

### 2.1 ObstacleLayer：不是所有远处点都应该进入风险判断

Nav2 的 `ObstacleLayer` 可以使用 `LaserScan` 或 `PointCloud2` 作为输入。官方文档说明它使用 2D raycasting 处理 2D lidar、depth 或其他传感器，并把它们维护成一个 2D costmap 模型：

- 官方文档：<https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html>
- GitHub 文档源码：<https://github.com/ros-navigation/docs.nav2.org/blob/master/configuration/packages/costmap-plugins/obstacle.rst>

最关键参数是：

| 参数 | 作用 | 对你的问题的意义 |
|---|---|---|
| `observation_sources` | 定义传感器输入源 | 视觉模型可伪装成 `scan` 或 `pointcloud` 输入 |
| `<source>.topic` | 输入 topic | 例如 `/vision/points` 或 `/depth_scan` |
| `<source>.data_type` | `LaserScan` 或 `PointCloud2` | 决定视觉输出格式 |
| `<source>.marking` | 是否把传感器点标记成障碍 | 视觉障碍点需要设为 true |
| `<source>.clearing` | 是否用 raytrace 清除旧障碍 | 对动态环境非常重要 |
| `<source>.obstacle_max_range` | 超过这个距离的点不标记为障碍 | 防止很远的东西参与局部避障 |
| `<source>.raytrace_max_range` | 清除障碍的最大 raytrace 距离 | 通常略大于 `obstacle_max_range` |
| `<source>.min_obstacle_height` | 最低障碍高度 | 过滤地面点、地毯纹理、低噪声 |
| `<source>.max_obstacle_height` | 最高障碍高度 | 过滤天花板、远处墙顶等无关点 |

一个典型的视觉点云输入配置：

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      rolling_window: true
      width: 4.0
      height: 4.0
      resolution: 0.05
      robot_base_frame: base_link
      plugins: ["obstacle_layer", "denoise_layer", "inflation_layer"]

      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        enabled: true
        observation_sources: vision_points

        vision_points:
          topic: /vision/obstacle_points
          data_type: "PointCloud2"
          marking: true
          clearing: true

          # 关键：只把局部避障需要的距离写入 costmap
          obstacle_min_range: 0.10
          obstacle_max_range: 2.50
          raytrace_min_range: 0.10
          raytrace_max_range: 3.00

          # 关键：过滤地面与太高的点
          min_obstacle_height: 0.05
          max_obstacle_height: 1.50

          # 动态环境不要保留太久
          observation_persistence: 0.0
          expected_update_rate: 0.2

      denoise_layer:
        plugin: "nav2_costmap_2d::DenoiseLayer"
        enabled: true
        minimal_group_size: 3
        group_connectivity_type: 8

      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        enabled: true
        inflation_radius: 0.55
        cost_scaling_factor: 6.0
```

这里最直接解决你问题的是：

```yaml
obstacle_max_range: 2.50
```

这意味着：如果视觉模型看到了 5 米外的东西，它可以存在于视觉检测结果里，但**不应该进入本地避障 costmap**。远距离障碍可以留给全局规划或下一帧逐渐处理，而不是立刻触发风险。

---

### 2.2 InflationLayer：把二值障碍变成距离衰减代价

`InflationLayer` 的作用是把障碍周围扩张成一个距离相关的代价场。官方文档说明，它在障碍周围放置指数衰减的代价，并在机器人内切半径范围内设置 lethal cost：

- 官方文档：<https://docs.nav2.org/configuration/packages/costmap-plugins/inflation.html>

这对你非常重要，因为它把：

```text
有障碍 / 没障碍
```

变成：

```text
很近：危险，必须停或强烈避开
中等距离：高代价，减速或绕开
较远距离：低代价，只影响路径偏好
更远距离：不影响
```

关键参数：

| 参数 | 含义 | 调参建议 |
|---|---|---|
| `inflation_radius` | 障碍周围多远开始产生代价 | 通常 0.4–1.0 m，取决于机器人尺寸和速度 |
| `cost_scaling_factor` | 代价随距离衰减的速度 | 越大衰减越快，越小衰减越慢 |
| `inflate_unknown` | 是否把未知区域当 lethal 膨胀 | 如果打开，机器人可能更容易“害怕远处未知区域” |
| `inflate_around_unknown` | 是否围绕 unknown 膨胀 | 室内调试时要谨慎 |

如果你的机器人“看到远处就停”，除了视觉模型二值化之外，也要检查：

```yaml
inflation_radius: 是否太大
cost_scaling_factor: 是否太小导致代价扩散太远
inflate_unknown: 是否误把未知区域当成障碍
```

---

### 2.3 DenoiseLayer：视觉模型和深度相机一定要抗噪声

视觉模型、深度相机、单目深度、点云投影都可能产生孤立噪声点。Nav2 有 `DenoiseLayer`，官方说明它用于移除由传感器噪声或离散 raycasting 误差产生的简单噪声障碍：

- 官方文档：<https://docs.nav2.org/configuration/packages/costmap-plugins/denoise.html>

关键参数：

```yaml
denoise_layer:
  plugin: "nav2_costmap_2d::DenoiseLayer"
  enabled: true
  minimal_group_size: 3
  group_connectivity_type: 8
```

解释：

| 参数 | 作用 |
|---|---|
| `minimal_group_size: 2` | 移除孤立点 |
| `minimal_group_size: 3~5` | 需要一小簇障碍才认为有效，更适合视觉噪声 |
| `group_connectivity_type: 8` | 斜向相邻也算一组，通常更稳定 |

插件顺序很重要：

```yaml
plugins: ["obstacle_layer", "denoise_layer", "inflation_layer"]
```

原因是：先标记障碍，再去噪，最后膨胀。如果顺序变成：

```yaml
plugins: ["obstacle_layer", "inflation_layer", "denoise_layer"]
```

孤立噪声可能已经被 inflation 放大，机器人就会对一个单点误检过度反应。

---

## 3. Collision Monitor：最后一层安全过滤，不是简单二值停机

Nav2 的 `nav2_collision_monitor` 是解决你问题最直接的组件之一。官方文档说明，它是一个额外的安全层，会绕过 costmap 和 planner，直接根据传感器数据在 emergency-stop 层面防止碰撞：

- 官方文档：<https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html>
- 使用教程：<https://docs.nav2.org/tutorials/docs/using_collision_monitor.html>
- GitHub 主仓库：<https://github.com/ros-navigation/navigation2>

它支持的数据源包括：

```text
LaserScan
PointCloud2
Range
Costmap
```

这意味着你的视觉模型可以输出：

```text
/vision/obstacle_points   sensor_msgs/msg/PointCloud2
```

然后直接交给 Collision Monitor。

---

### 3.1 Collision Monitor 的四种行为模型

官方文档列出的核心行为包括：

| 模型 | 作用 | 适合你的场景 |
|---|---|---|
| `stop` | 指定区域内有足够障碍点则停止 | 近距离急停 |
| `slowdown` | 指定区域内有障碍点则按比例减速 | 中距离减速 |
| `limit` | 限制最大线速度和角速度 | 狭窄区域或不确定视觉场景 |
| `approach` | 根据当前速度估计碰撞时间 TTC，不足阈值则减速 | 最适合解决“远处障碍误判风险” |

你现在的问题可以理解为：你只有一个无限长的“前方有障碍区域”。

Nav2 更合理的做法是把它拆成不同区域：

```text
0.00m ~ 0.45m：stop zone
0.45m ~ 1.50m：slowdown zone
1.50m ~ 2.50m：caution / costmap influence
2.50m 以上：暂不触发局部风险
```

---

### 3.2 为什么 `approach` / TTC 比“有障碍”更合理

`approach` 模型使用当前机器人速度估计 time-to-collision：

```text
TTC = distance_to_collision / current_speed
```

如果：

```text
TTC < time_before_collision
```

则减速，使机器人始终保持至少 `time_before_collision` 秒的安全时间。

这个模型的好处是：

| 情况 | 二值模型 | TTC / approach 模型 |
|---|---|---|
| 机器人静止，前方 2m 有障碍 | 风险 | 不急停，因为没有马上碰撞 |
| 机器人 0.1 m/s，前方 2m 有障碍 | 风险 | TTC=20s，通常安全 |
| 机器人 1.0 m/s，前方 2m 有障碍 | 风险 | TTC=2s，需要减速或准备停止 |
| 机器人正在倒车，前方有障碍 | 风险 | 不一定风险，因为运动方向不是前进 |
| 机器人原地旋转，前方有障碍 | 风险 | 取决于 footprint 旋转轨迹是否碰撞 |

这正是你需要的：**风险随速度和距离变化，而不是只看是否有障碍。**

---

### 3.3 推荐 Collision Monitor 配置

下面是一个适合“视觉点云 + 前方距离风险”的示意配置。不同 ROS2 / Nav2 版本参数名可能略有差异，使用时要对照你当前发行版文档。

```yaml
collision_monitor:
  ros__parameters:
    use_sim_time: false
    base_frame_id: base_link
    odom_frame_id: odom
    transform_tolerance: 0.2
    cmd_vel_in_topic: /cmd_vel_nav
    cmd_vel_out_topic: /cmd_vel
    state_topic: /collision_monitor_state

    # 传感器来源：你的视觉模型输出的点云
    observation_sources: ["vision_points"]
    vision_points:
      type: "pointcloud"
      topic: /vision/obstacle_points
      min_height: 0.05
      max_height: 1.50

    # 多个安全区域
    polygons: ["FrontStop", "FrontSlow", "FootprintApproach"]

    # 近距离急停区：只覆盖机器人前方很近的一小块
    FrontStop:
      type: "polygon"
      points: "[[0.45, 0.35], [0.45, -0.35], [0.05, -0.35], [0.05, 0.35]]"
      action_type: "stop"
      min_points: 5
      trigger_consecutive_points: 2
      release_consecutive_points: 3
      visualize: true
      polygon_pub_topic: /front_stop_zone

    # 中距离减速区：比 stop 区更大，但只减速，不急停
    FrontSlow:
      type: "polygon"
      points: "[[1.50, 0.60], [1.50, -0.60], [0.05, -0.60], [0.05, 0.60]]"
      action_type: "slowdown"
      slowdown_ratio: 0.35
      min_points: 8
      trigger_consecutive_points: 2
      release_consecutive_points: 3
      visualize: true
      polygon_pub_topic: /front_slow_zone

    # TTC / approach 区：根据当前速度和 footprint 预测碰撞
    FootprintApproach:
      type: "polygon"
      action_type: "approach"
      footprint_topic: /local_costmap/published_footprint
      time_before_collision: 1.2
      simulation_time_step: 0.05
      min_points: 5
      visualize: true
      polygon_pub_topic: /approach_zone
```

关键点：

1. **stop zone 不能太大**。如果你把 stop zone 做成 3 米长，那么 3 米外的障碍也会急停。
2. **slow zone 可以大一些**。远一点的障碍应该先减速，而不是直接停车。
3. **approach 模型用 TTC**。速度越快，看得越远；速度越慢，看得越近。
4. **`min_points` 不能太小**。视觉点云单点噪声很多，建议至少 5–10 个点才触发。
5. **`trigger_consecutive_points` / `release_consecutive_points` 用于抗抖动**。避免单帧误检导致急停。

---

### 3.4 VelocityPolygon：安全区应该随速度方向改变

Nav2 Collision Monitor 还支持 `VelocityPolygon`，可以根据当前速度切换不同的安全区域。

这对你的问题很重要，因为：

```text
机器人前进：需要看前方
机器人后退：需要看后方
机器人左移/右移：需要看侧方
机器人原地转弯：需要看 footprint 旋转会扫到的区域
```

如果你的机器人是差速底盘，可以做：

```text
forward zone：前进时启用
backward zone：后退时启用
stopped / rotation zone：低速或原地旋转时启用较小区域
```

示意配置：

```yaml
VelocitySafetyZone:
  type: "velocity_polygon"
  action_type: "stop"
  min_points: 5
  velocity_polygons: ["Forward", "Backward", "Stopped"]

  Forward:
    points: "[[0.80, 0.40], [0.80, -0.40], [0.05, -0.40], [0.05, 0.40]]"
    linear_min: 0.05
    linear_max: 1.00
    theta_min: -1.50
    theta_max: 1.50

  Backward:
    points: "[[-0.05, 0.40], [-0.05, -0.40], [-0.60, -0.40], [-0.60, 0.40]]"
    linear_min: -1.00
    linear_max: -0.05
    theta_min: -1.50
    theta_max: 1.50

  Stopped:
    points: "[[0.35, 0.35], [0.35, -0.35], [-0.35, -0.35], [-0.35, 0.35]]"
    linear_min: -0.05
    linear_max: 0.05
    theta_min: -0.30
    theta_max: 0.30
```

这样可以避免“前方有障碍就禁止所有动作”的错误。例如前方有障碍时，机器人仍然可以倒车或轻微旋转脱困。

---

## 4. Regulated Pure Pursuit：沿当前速度向前模拟 footprint，而不是检查所有远处障碍

Nav2 的 Regulated Pure Pursuit Controller，简称 RPP，是非常适合移动机器人路径跟踪的控制器：

- 官方配置文档：<https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html>
- GitHub 目录：<https://github.com/ros-navigation/navigation2/tree/main/nav2_regulated_pure_pursuit_controller>

RPP 的核心特点之一是**主动碰撞检测**。它不是看到任意障碍就停，而是：

```text
拿当前将要发出的 linear/angular velocity
        ↓
向未来模拟一段时间
        ↓
每一步把机器人 footprint 投影到 costmap
        ↓
如果 footprint 与障碍碰撞，则停止
```

关键参数：

| 参数 | 含义 | 解决你的问题的方式 |
|---|---|---|
| `use_collision_detection` | 是否启用碰撞检测 | 应该开启 |
| `max_allowed_time_to_collision_up_to_carrot` | 向未来检查几秒 | 不要设太大，否则会过度检查远处 |
| `use_cost_regulated_linear_velocity_scaling` | 是否根据障碍 proximity 调速 | 推荐开启，尤其是非极窄环境 |
| `cost_scaling_dist` | 离障碍多近开始减速 | 应小于或等于 costmap inflation radius |
| `cost_scaling_gain` | 减速强度 | 越小减速越快 |
| `min_distance_to_obstacle` | 轨迹上允许的最小障碍距离 | 可用于强安全边界 |

官方文档对 `max_allowed_time_to_collision_up_to_carrot` 的解释是：当启用 collision detection 时，它会按当前速度命令向前模拟，直到达到这个时间限制或 carrot distance；如果任何投影姿态碰撞，机器人停止。

### 推荐初始值

```yaml
controller_server:
  ros__parameters:
    controller_plugins: ["FollowPath"]

    FollowPath:
      plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"

      desired_linear_vel: 0.45
      max_linear_vel: 0.60
      max_angular_vel: 1.20
      max_linear_accel: 0.8
      max_linear_decel: -0.8

      lookahead_dist: 0.6
      min_lookahead_dist: 0.3
      max_lookahead_dist: 0.9
      lookahead_time: 1.5
      use_velocity_scaled_lookahead_dist: true

      use_collision_detection: true
      max_allowed_time_to_collision_up_to_carrot: 1.0

      use_cost_regulated_linear_velocity_scaling: true
      cost_scaling_dist: 0.45
      cost_scaling_gain: 0.8
      regulated_linear_scaling_min_speed: 0.10

      min_distance_to_obstacle: 0.10
```

### 为什么 RPP 能解决“远障碍误判”

假设：

```text
机器人速度：0.2 m/s
max_allowed_time_to_collision_up_to_carrot: 1.0 s
```

那么它大约只需要重点检查未来：

```text
0.2 m/s × 1.0 s = 0.2 m
```

当然还会受到 lookahead/carrot 等限制影响，但核心思想是：**慢速时不应该检查很远的未来**。

如果机器人速度变成：

```text
1.0 m/s
```

同样 1 秒就会检查大约 1 米范围，所以高速时自然更保守。

这比固定“前方有障碍就风险”合理很多。

---

## 5. DWB Controller：采样很多候选轨迹，用 critic 给轨迹打分

DWB 是 Nav2 的一个经典控制器，基于 Dynamic Window Approach：

- 官方文档：<https://docs.nav2.org/configuration/packages/configuring-dwb-controller.html>
- `ObstacleFootprintCritic`：<https://docs.nav2.org/configuration/packages/trajectory_critics/obstacle_footprint.html>
- GitHub README：<https://github.com/ros-navigation/navigation2/blob/main/nav2_dwb_controller/README.md>

DWB 的核心不是：

```text
前方有障碍 → risk
```

而是：

```text
采样很多速度命令 vx, vy, vtheta
        ↓
每个速度命令向前模拟 sim_time
        ↓
得到候选轨迹
        ↓
用多个 critic 评分
        ↓
选总分最低、最安全、最贴近路径的速度
```

其中与障碍相关的 critic 包括：

| critic | 作用 |
|---|---|
| `BaseObstacleCritic` | 根据轨迹经过的 costmap 障碍代价评分 |
| `ObstacleFootprintCritic` | 检查轨迹上机器人 footprint 是否碰到 costmap 障碍 |
| `PathAlignCritic` | 偏好贴近全局路径的轨迹 |
| `GoalDistCritic` / `PathDistCritic` | 偏好朝目标和路径推进 |

一个常见 DWB 配置片段：

```yaml
controller_server:
  ros__parameters:
    controller_frequency: 20.0
    controller_plugins: ["FollowPath"]

    FollowPath:
      plugin: "dwb_core::DWBLocalPlanner"
      debug_trajectory_details: true

      min_vel_x: 0.0
      max_vel_x: 0.45
      max_vel_theta: 1.0
      acc_lim_x: 0.8
      decel_lim_x: -0.8
      acc_lim_theta: 1.5
      decel_lim_theta: -1.5

      vx_samples: 20
      vtheta_samples: 20
      sim_time: 1.5
      linear_granularity: 0.05
      angular_granularity: 0.025

      critics: ["RotateToGoal", "Oscillation", "ObstacleFootprint", "BaseObstacle", "PathAlign", "PathDist", "GoalDist"]
      ObstacleFootprint.scale: 1.0
      BaseObstacle.scale: 0.05
      PathAlign.scale: 24.0
      PathDist.scale: 24.0
      GoalDist.scale: 20.0
      RotateToGoal.scale: 20.0
```

### DWB 对你问题的启发

DWB 的关键启发是：

> 不要直接判断“场景风险”，而要判断“这个速度命令未来 1~2 秒是否安全”。

也就是说，风险应该绑定到动作：

```python
risk(action, obstacles, robot_state)
```

而不是：

```python
risk(obstacles)
```

这对于你的机器人尤其重要。比如：

| 视觉场景 | 动作 | 风险 |
|---|---|---|
| 前方 1m 有障碍 | 前进 | 高 |
| 前方 1m 有障碍 | 后退 | 低 |
| 左前方 1m 有障碍 | 右转绕开 | 低或中 |
| 远处 4m 有障碍 | 慢速前进 | 低 |
| 远处 4m 有障碍 | 高速直冲 | 中或高 |

---

## 6. MPPI Controller：采样未来轨迹，用代价函数选择最优轨迹

Nav2 的 MPPI Controller 是一个更现代的预测控制器：

- 官方文档：<https://docs.nav2.org/configuration/packages/configuring-mppic.html>
- GitHub 主仓库：<https://github.com/ros-navigation/navigation2>

官方文档说明，MPPI 会使用采样方法选择最优轨迹：它对控制量加入随机扰动，向前模拟一批轨迹，再使用插件化 critic 函数打分，最后用 soft-max 方式得到控制输出。

与障碍相关的 critic：

| critic | 作用 |
|---|---|
| `ObstaclesCritic` | 基于障碍距离和碰撞情况，鼓励远离障碍和避免 near collision |
| `CostCritic` | 使用 costmap 代价检查轨迹，支持点模型或 SE2 footprint |
| `PathAlignCritic` | 轨迹与全局路径对齐 |
| `GoalCritic` / `PathFollowCritic` | 朝目标推进 |

关键参数示意：

```yaml
FollowPath:
  plugin: "nav2_mppi_controller::MPPIController"
  time_steps: 56
  model_dt: 0.05
  batch_size: 1000

  critics: ["ConstraintCritic", "CostCritic", "GoalCritic", "GoalAngleCritic", "PathAlignCritic", "PathFollowCritic", "PathAngleCritic", "PreferForwardCritic"]

  CostCritic:
    enabled: true
    cost_weight: 3.81
    cost_power: 1
    consider_footprint: true
    collision_cost: 1000000.0
    near_collision_cost: 253
    critical_cost: 300.0
    inflation_layer_name: "inflation_layer"
    trajectory_point_step: 2
```

MPPI 对你的启发是：

> 视觉模型可以把“语义危险程度 + 距离 + 置信度”写成 costmap 代价，MPPI 再根据未来轨迹自动选择较低风险动作。

也就是说，视觉模型不需要说：

```text
risk = True
```

它应该说：

```text
这个区域是 grass，cost=254
这个区域是 sidewalk，cost=0
这个区域是 uncertain obstacle，cost=180
这个点云距离 0.8m，costmap lethal
```

然后交给 MPPI/DWB/RPP 这类控制器处理。

---

## 7. VoxelLayer 与 STVL：视觉 / 深度点云应该进入 3D 感知层

如果你的视觉模型能输出深度或点云，建议不要只压成一个 `front_has_obstacle`，而是交给 3D 感知层。

---

### 7.1 VoxelLayer

Nav2 的 `VoxelLayer` 使用 3D raycasting 处理 depth、3D 或其他传感器，维护 3D 环境模型，然后压缩到 2D 供规划与控制使用：

- 官方文档：<https://docs.nav2.org/configuration/packages/costmap-plugins/voxel.html>

关键参数：

| 参数 | 作用 |
|---|---|
| `z_voxels` | 高度方向 voxel 数，最大 16 |
| `origin_z` | z 方向起点 |
| `z_resolution` | 高度分辨率 |
| `mark_threshold` | 一列里多少 voxel 被占据才标记为 2D 障碍 |
| `observation_sources` | 输入源 |
| `<source>.data_type` | `LaserScan` 或 `PointCloud2` |
| `<source>.obstacle_max_range` | 最大障碍标记距离 |
| `<source>.raytrace_max_range` | 最大清除距离 |

视觉点云输入示例：

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      plugins: ["voxel_layer", "denoise_layer", "inflation_layer"]

      voxel_layer:
        plugin: "nav2_costmap_2d::VoxelLayer"
        enabled: true
        publish_voxel_map: false
        origin_z: 0.0
        z_resolution: 0.05
        z_voxels: 16
        mark_threshold: 2
        observation_sources: vision_points

        vision_points:
          topic: /vision/depth_points
          data_type: "PointCloud2"
          marking: true
          clearing: true
          obstacle_min_range: 0.10
          obstacle_max_range: 2.80
          raytrace_min_range: 0.10
          raytrace_max_range: 3.20
          min_obstacle_height: 0.05
          max_obstacle_height: 1.50
```

---

### 7.2 STVL：Spatio-Temporal Voxel Layer

STVL 是 Steve Macenski 的开源 voxel layer，Nav2 官方教程也把它作为外部 costmap plugin 示例：

- Nav2 STVL 教程：<https://docs.nav2.org/tutorials/docs/navigation2_with_stvl.html>
- GitHub 仓库：<https://github.com/SteveMacenski/spatio_temporal_voxel_layer>
- ROS Index：<https://index.ros.org/r/spatio_temporal_voxel_layer/>

STVL 的特点：

| 特点 | 对视觉模型的价值 |
|---|---|
| 稀疏 3D voxel world model | 更适合深度相机 / 3D 点云 |
| voxel decay | 动态物体离开后不会永久残留 |
| sensor FOV frustum | 根据相机视场进行清除和加速 decay |
| 支持 depth camera / lidar / radar | 视觉深度、RGBD、双目都可接入 |
| 比传统 3D sensor processing 更省资源 | 适合实时机器人 |

STVL 对你的问题尤其有用，因为视觉模型经常会看到动态障碍，例如人、椅子、门、移动物体。普通 costmap 如果清除不及时，可能会出现：

```text
障碍已经不在前方，但 costmap 里还残留，机器人继续认为有风险。
```

STVL 的时间衰减机制可以缓解这个问题。

---

## 8. 视觉模型如何接入 ROS2 / Nav2：四条路线

下面是与你最相关的部分。

---

## 路线 A：Depth / RGBD → `depthimage_to_laserscan` → LaserScan → Nav2

如果你有深度图，比如：

```text
/depth/image_raw
/depth/camera_info
```

可以用 `depthimage_to_laserscan` 转成 2D 激光：

- GitHub：<https://github.com/ros-perception/depthimage_to_laserscan>

它会发布：

```text
/scan  sensor_msgs/msg/LaserScan
```

官方 README 中的关键参数：

| 参数 | 作用 |
|---|---|
| `range_min` | 小于这个距离的点丢弃，默认 0.45 m |
| `range_max` | 大于这个距离的点丢弃，默认 10.0 m |
| `scan_height` | 从深度图中取多少行用于投影 |
| `output_frame` | 发布 LaserScan 的 frame |

示意 launch：

```python
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(
            package='depthimage_to_laserscan',
            executable='depthimage_to_laserscan_node',
            name='depthimage_to_laserscan',
            remappings=[
                ('depth', '/camera/depth/image_raw'),
                ('depth_camera_info', '/camera/depth/camera_info'),
                ('scan', '/depth_scan'),
            ],
            parameters=[{
                'range_min': 0.20,
                'range_max': 3.00,
                'scan_height': 8,
                'output_frame': 'camera_depth_frame',
            }]
        )
    ])
```

然后给 Nav2 costmap：

```yaml
obstacle_layer:
  plugin: "nav2_costmap_2d::ObstacleLayer"
  observation_sources: depth_scan

  depth_scan:
    topic: /depth_scan
    data_type: "LaserScan"
    marking: true
    clearing: true
    obstacle_max_range: 2.5
    raytrace_max_range: 3.0
```

也可以给 Collision Monitor：

```yaml
observation_sources: ["depth_scan"]
depth_scan:
  type: "scan"
  topic: /depth_scan
```

### 路线 A 的优缺点

| 优点 | 缺点 |
|---|---|
| 最简单、最快接入 Nav2 | 只抽取深度图某些行，丢失完整 3D 结构 |
| 可直接用于 ObstacleLayer / CollisionMonitor | 对低矮障碍、悬空障碍可能不稳 |
| 参数 `range_max` 可直接解决远障碍误判 | 语义信息丢失 |

适合你现在快速验证：

```text
远处障碍不再触发风险
近处障碍触发 stop / slow
```

---

## 路线 B：视觉深度 / 单目深度 → `PointCloud2` → VoxelLayer / STVL / CollisionMonitor

如果你的视觉模型能估计深度，最推荐输出：

```text
sensor_msgs/msg/PointCloud2
```

例如已有开源项目：

- `ros2-depth-anything-v3-trt`：<https://github.com/ika-rwth-aachen/ros2-depth-anything-v3-trt>

这个仓库说明它是一个 ROS2 TensorRT 节点，可以订阅相机图像和相机内参，并发布：

```text
~/output/depth_image    sensor_msgs/msg/Image
~/output/point_cloud    sensor_msgs/msg/PointCloud2
```

还有 Nav2 issue 中有人明确提出：

> 用 Depth Anything V2 或其他模型处理图像，然后投影成 pointcloud 给 Voxel Layer 使用。

- Issue：<https://github.com/ros-navigation/navigation2/issues/5536>

这与我的建议完全一致：

```text
Vision Model
    ↓ metric depth
Depth Image
    ↓ camera intrinsics projection
PointCloud2
    ↓
VoxelLayer / STVL / ObstacleLayer / CollisionMonitor
```

### 点云投影公式

如果模型输出每个像素的深度 `Z`，相机内参为：

```text
fx, fy, cx, cy
```

像素坐标为：

```text
u, v
```

则相机坐标系下：

```text
X = (u - cx) * Z / fx
Y = (v - cy) * Z / fy
Z = Z
```

投影后必须通过 TF 转到 `base_link` 或 costmap frame。

### 注意：单目深度必须是 metric 或经过标定

如果你的视觉模型是普通单目深度，输出可能只是相对深度：

```text
近 / 远 排序正确，但米制距离不准
```

这时不能直接用于安全停机。你至少要做：

1. 用真实深度相机或标定板校准尺度。
2. 对模型输出做 scale + bias 修正。
3. 对 sky / reflection / glass / floor 做特殊处理。
4. 保留不确定度，低置信度不要直接写 lethal cost。

推荐输出不仅是：

```text
depth
```

还要输出：

```text
confidence / uncertainty
```

这样后续 costmap 可以按置信度调 cost。

---

## 路线 C：语义分割 → Semantic Segmentation Layer → costmap

如果你的视觉模型是语义分割、实例分割、可通行区域分割，这条路线非常适合。

Nav2 官方已经有“使用语义分割导航”的教程：

- 官方教程：<https://docs.nav2.org/tutorials/docs/navigation2_with_semantic_segmentation.html>
- Semantic Segmentation Layer GitHub：<https://github.com/kiwicampus/semantic_segmentation_layer>
- Demo GitHub：<https://github.com/pepisg/nav2_segmentation_demo>

官方教程说明该方案会用 stereo camera 和自定义 `semantic_segmentation_layer` 插件，把语义分割结果接入 costmap。分割节点会发布：

```text
/segmentation/mask
/segmentation/confidence
/segmentation/label_info
/segmentation/overlay
```

costmap layer 需要：

```text
segmentation mask
confidence map
label info
aligned pointcloud
```

为什么需要 aligned pointcloud？

因为 segmentation mask 是 2D 图片坐标，而机器人导航需要 3D/2D 地图坐标。aligned pointcloud 可以把每个 mask 像素投影到 costmap tile。

### Semantic layer 配置示例

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      plugins: ["semantic_segmentation_layer", "denoise_layer", "inflation_layer"]

      semantic_segmentation_layer:
        plugin: "semantic_segmentation_layer::SemanticSegmentationLayer"
        enabled: true
        observation_sources: camera

        camera:
          segmentation_topic: "/segmentation/mask"
          confidence_topic: "/segmentation/confidence"
          labels_topic: "/segmentation/label_info"
          pointcloud_topic: "/rgbd_camera/depth/points"

          # 关键：不要让太远的语义区域影响局部风险
          max_obstacle_distance: 4.0
          min_obstacle_distance: 0.25

          # 动态场景不要永久记忆
          tile_map_decay_time: 2.0

          class_types: ["traversable", "intermediate", "danger"]

          traversable:
            classes: ["floor", "sidewalk", "road"]
            base_cost: 0
            max_cost: 0

          intermediate:
            classes: ["unknown", "low_confidence"]
            base_cost: 90
            max_cost: 160

          danger:
            classes: ["person", "chair", "table", "wall", "vehicle", "grass"]
            base_cost: 220
            max_cost: 254

      denoise_layer:
        plugin: "nav2_costmap_2d::DenoiseLayer"
        enabled: true
        minimal_group_size: 3

      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        inflation_radius: 0.55
        cost_scaling_factor: 6.0
```

### 对你的视觉模型的建议

如果你的模型现在只是检测“障碍”，建议升级为下面至少一种：

| 模型输出 | Nav2 使用方式 |
|---|---|
| `obstacle mask` | 只把 mask 内的 depth 点投影为 PointCloud2 |
| `traversable / non-traversable` | 写入 semantic costmap |
| `object class + depth` | person/chair/wall 等类设置不同 cost |
| `confidence` | 低置信度只给 intermediate cost，不直接 lethal |
| `dynamic/static` | 动态障碍设置较短 decay，静态障碍可保留更久 |

这样能解决非常多视觉误判问题。

---

## 路线 D：自定义 Nav2 Costmap Layer

如果你的模型输出比较特殊，例如：

```text
每个像素的 risk score
每个目标的 3D bbox
每个目标的 motion vector
每个区域的 traversability probability
```

你可以写一个自定义 `nav2_costmap_2d::Layer` 插件。

Nav2 costmap 本来就是插件化的。STVL、Semantic Segmentation Layer 都是这个思路。

一个自定义视觉层可以做：

```text
订阅 /vision/risk_map 或 /vision/detections_3d
        ↓
根据 TF 投影到 costmap 坐标
        ↓
按类别、距离、置信度、时间衰减计算 cost
        ↓
写入 local_costmap
```

伪逻辑：

```python
cost = 0

if cls in traversable_classes:
    cost = 0
elif cls in obstacle_classes:
    cost = 254 * confidence * distance_weight
elif cls in uncertain_classes:
    cost = 80 + 100 * confidence

# 越近代价越高
if distance < 0.5:
    cost = max(cost, 254)
elif distance < 1.5:
    cost = max(cost, 180)
elif distance < 3.0:
    cost = max(cost, 100)
else:
    cost = 0
```

但是注意：即使你写了自定义 costmap layer，也不建议完全绕过 Nav2 控制器和 Collision Monitor。更好的架构是：

```text
视觉模型：负责感知与语义
costmap：负责空间代价表达
controller：负责动作选择
collision_monitor：负责最终安全约束
```

---

## 路线 E：视觉-only 导航方案

Open Navigation 也有一个视觉-only 导航示例：

- GitHub：<https://github.com/open-navigation/opennav_visual_navigation>

该仓库说明它与 Nav2 文档教程配套，展示了使用 Nav2 和 NVIDIA Isaac / Perceptor SDK 的 vision-only navigation，用 stereo cameras 替代 lidar 和主动深度相机，实现 mapping、localization 和 collision avoidance。

这个路线适合你有：

```text
NVIDIA Jetson
stereo cameras
Isaac ROS / Perceptor / NvBlox
较强算力
```

但如果你的当前目标只是解决“远障碍误判风险”，不建议一开始走这个重路线。建议先做：

```text
视觉模型 → PointCloud2 / LaserScan → Collision Monitor + local_costmap
```

---

## 9. 最适合你当前项目的推荐架构

结合你的描述，我建议你采用下面架构。

### 9.1 第一阶段：最小可行修复

```text
视觉模型
  ↓
输出 front_obstacle_distance，而不是 front_has_obstacle
  ↓
动态距离阈值 + TTC
  ↓
SAFE / CAUTION / SLOW / STOP
```

风险函数：

```python
from enum import Enum
import math

class RiskState(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    SLOW = "SLOW"
    STOP = "STOP"


def compute_distance_risk(
    d_front: float | None,
    v: float,
    robot_radius: float = 0.25,
    safety_margin: float = 0.12,
    reaction_time: float = 0.20,
    max_decel: float = 0.80,
    ttc_stop: float = 0.8,
    ttc_slow: float = 1.8,
    caution_distance: float = 2.5,
) -> RiskState:
    """
    d_front: 前方路径走廊内最近障碍距离，单位 m。
    v: 当前前进速度，单位 m/s。只对正向速度计算前方 TTC。
    """
    if d_front is None or math.isinf(d_front):
        return RiskState.SAFE

    # 非前进时，不应该用前方障碍直接急停；应改看后方/旋转 footprint。
    if v <= 0.02:
        if d_front < robot_radius + safety_margin:
            return RiskState.STOP
        if d_front < 0.6:
            return RiskState.CAUTION
        return RiskState.SAFE

    # 动态制动距离：机器人半径 + 安全边界 + 反应距离 + 刹车距离
    braking_distance = robot_radius + safety_margin + v * reaction_time + (v * v) / (2.0 * max_decel)
    ttc = d_front / max(v, 1e-3)

    if d_front <= robot_radius + safety_margin:
        return RiskState.STOP
    if d_front <= braking_distance or ttc <= ttc_stop:
        return RiskState.STOP
    if ttc <= ttc_slow or d_front <= braking_distance + 0.5:
        return RiskState.SLOW
    if d_front <= caution_distance:
        return RiskState.CAUTION
    return RiskState.SAFE
```

示例：

| 速度 | 前方距离 | 结果 |
|---:|---:|---|
| 0.1 m/s | 2.0 m | SAFE 或 CAUTION，不应 STOP |
| 0.5 m/s | 2.0 m | CAUTION 或 SLOW |
| 1.0 m/s | 2.0 m | SLOW，必要时 STOP |
| 0.5 m/s | 0.4 m | STOP |

---

### 9.2 第二阶段：视觉模型输出 PointCloud2，交给 Nav2

推荐架构：

```text
Camera Image
  ↓
Visual Model: obstacle mask / depth / confidence
  ↓
Project masked depth to PointCloud2
  ↓
/vision/obstacle_points
  ↓
Nav2 local_costmap ObstacleLayer or VoxelLayer
  ↓
RPP / DWB / MPPI controller
  ↓
Collision Monitor final safety filter
```

你的视觉模型输出点云时，不要把整张图所有点都投影进去。建议只投影：

```text
障碍类别 mask 内的点
置信度高于阈值的点
高度在机器人关注范围内的点
距离小于 local planning range 的点
落在机器人未来路径走廊附近的点
```

伪代码：

```python
for pixel in image:
    cls = segmentation[pixel]
    conf = confidence[pixel]
    depth = depth_map[pixel]

    if conf < 0.6:
        continue
    if cls in traversable_classes:
        continue
    if not (0.15 <= depth <= 3.0):
        continue

    point_cam = project_pixel_to_3d(pixel, depth, camera_info)
    point_base = transform(point_cam, "base_link")

    if point_base.z < 0.05 or point_base.z > 1.5:
        continue

    publish_as_pointcloud(point_base)
```

---

### 9.3 第三阶段：用 Collision Monitor 做最终安全过滤

即使 costmap 和 controller 配好了，也建议保留 Collision Monitor：

```text
/controller_server/cmd_vel
        ↓
collision_monitor
        ↓
/robot/cmd_vel
```

原因是视觉模型、costmap、controller 都可能有延迟或误差。Collision Monitor 是最后一道软件安全层。

推荐组合：

| 区域 | 行为 | 范围 |
|---|---|---|
| `FrontStop` | stop | 前方 0.4–0.6 m |
| `FrontSlow` | slowdown | 前方 1.2–1.8 m |
| `FootprintApproach` | TTC approach | 1.0–2.0 s |
| `VelocityPolygon` | 根据速度方向切换区域 | 前进看前方，后退看后方 |

---

## 10. 视觉风险判断应该从“点”升级到“路径走廊”

你现在的问题可能还有一个原因：你判断“前方”太宽或太粗。

如果相机视野中有障碍，但障碍在机器人未来路径旁边，它不应该被判为直接风险。

### 10.1 简单前方走廊模型

对于差速机器人直行，可定义路径走廊：

```text
x > 0
abs(y) < robot_half_width + safety_margin
```

只考虑这个走廊内的点作为 `d_front`。

```python
def nearest_obstacle_in_corridor(points_base, half_width=0.25, margin=0.10, max_range=3.0):
    xs = []
    for p in points_base:
        x, y, z = p
        if x <= 0.0:
            continue
        if x > max_range:
            continue
        if z < 0.05 or z > 1.50:
            continue
        if abs(y) > half_width + margin:
            continue
        xs.append(x)

    if len(xs) < 5:  # min_points 抗噪声
        return None

    # 用 20 分位数比单点 min 更抗噪声
    xs.sort()
    return xs[int(0.20 * (len(xs) - 1))]
```

为什么不用单点最小值？

```python
d_front = min(xs)
```

单点最小值容易被一个错误深度点触发。更稳的是：

```python
d_front = percentile(xs, 10% or 20%)
```

也可以要求：

```text
至少 N 个点连续 M 帧出现
```

这与 Nav2 Collision Monitor 的 `min_points` 和 `trigger_consecutive_points` 思路一致。

---

### 10.2 转弯时要模拟 footprint，不要只看直线走廊

如果机器人正在转弯，障碍可能在弧线轨迹上，而不是正前方。

简化版轨迹模拟：

```python
import math


def simulate_diff_drive_poses(v, w, dt=0.05, horizon=1.0):
    x = y = theta = 0.0
    poses = []
    steps = int(horizon / dt)
    for _ in range(steps):
        x += v * math.cos(theta) * dt
        y += v * math.sin(theta) * dt
        theta += w * dt
        poses.append((x, y, theta))
    return poses
```

然后对每个未来 pose 检查 footprint 是否与障碍点重叠。这就是 RPP / DWB / MPPI 在 Nav2 中做的事情，只是它们更完整、更稳定。

---

## 11. 参数如何选：用速度和制动距离决定风险范围

你不应该手写固定阈值：

```python
if distance < 2.0:
    risk = True
```

更合理的是动态阈值：

```text
stop_distance = robot_radius + safety_margin + v * reaction_time + v² / (2 * max_decel)
```

变量解释：

| 变量 | 含义 |
|---|---|
| `robot_radius` | 机器人半径或 footprint 前缘距离 |
| `safety_margin` | 额外安全边界 |
| `v * reaction_time` | 感知/控制延迟内继续前进的距离 |
| `v² / (2a)` | 物理刹车距离 |

举例：

假设：

```text
robot_radius = 0.25 m
safety_margin = 0.12 m
reaction_time = 0.20 s
max_decel = 0.80 m/s²
```

| 速度 | 动态 stop distance 近似 |
|---:|---:|
| 0.2 m/s | 0.25 + 0.12 + 0.04 + 0.025 = 0.435 m |
| 0.5 m/s | 0.25 + 0.12 + 0.10 + 0.156 = 0.626 m |
| 1.0 m/s | 0.25 + 0.12 + 0.20 + 0.625 = 1.245 m |

这说明：

```text
同样 1 米外的障碍：
慢速时可能只是 caution；高速时可能必须 stop。
```

---

## 12. 常见错误与修正

| 现象 | 可能原因 | 修正方式 |
|---|---|---|
| 远处障碍也急停 | stop zone 太大 | 缩小 stop zone，增加 slow zone |
| 远处障碍也急停 | 只用 `front_has_obstacle` | 改成 `distance + TTC + trajectory` |
| 远处障碍写入局部 costmap | `obstacle_max_range` 太大 | 降到 2–3 m，按速度调 |
| 机器人靠近一点就停死 | `inflation_radius` 太大或 cost decay 太慢 | 调小 inflation 或增大 `cost_scaling_factor` |
| 机器人在空地也认为有障碍 | 深度点云含地面 / 噪声 | 设置 height filter + DenoiseLayer |
| 障碍消失后仍然停 | 没有 clearing / observation_persistence 太大 | 开启 clearing，减小 persistence，用 STVL decay |
| 视觉误检导致频繁停 | 单帧触发 | `min_points` + 连续帧触发 + confidence threshold |
| 点云在 RViz 可见但 costmap 不更新 | TF、frame、QoS、height、topic namespace、data_type 错 | 按调试清单检查 |
| 前方有障碍时不能后退脱困 | 风险逻辑不区分运动方向 | 使用 VelocityPolygon 或按 cmd_vel 方向判断 |
| 原地旋转也被禁止 | 把前方障碍当所有动作风险 | 按 footprint 旋转轨迹检查 |

---

## 13. ROS2 调试清单

当你把视觉模型接入 Nav2 时，按下面顺序排查。

### 13.1 Topic 是否正常

```bash
ros2 topic list
ros2 topic hz /vision/obstacle_points
ros2 topic echo /vision/obstacle_points --once
ros2 topic info /vision/obstacle_points -v
```

检查：

```text
是否有数据
frame_id 是否正确
timestamp 是否更新
QoS 是否匹配
```

---

### 13.2 TF 是否正确

```bash
ros2 run tf2_tools view_frames
ros2 run tf2_ros tf2_echo base_link camera_link
ros2 run tf2_ros tf2_echo odom base_link
```

必须保证：

```text
camera frame → base_link → odom/map
```

如果 TF 错，costmap 可能完全不更新，或者障碍出现在错误位置，导致“前方风险”判断混乱。

---

### 13.3 RViz 检查

在 RViz 中打开：

```text
PointCloud2: /vision/obstacle_points
LaserScan: /depth_scan
Costmap: /local_costmap/costmap
Footprint: /local_costmap/published_footprint
Collision Monitor polygons: /front_stop_zone, /front_slow_zone
RPP lookahead_arc: /lookahead_arc
```

你应该能看到：

1. 点云是否真的在机器人前方。
2. 远处点是否被 costmap 忽略。
3. 近处点是否被标为 obstacle。
4. inflation 是否太大。
5. collision monitor zone 是否尺寸合理。
6. RPP collision checking arc 是否过长。

---

### 13.4 Costmap 参数检查

重点检查：

```yaml
obstacle_max_range
raytrace_max_range
min_obstacle_height
max_obstacle_height
marking
clearing
observation_persistence
expected_update_rate
inflation_radius
cost_scaling_factor
plugins order
```

插件顺序建议：

```yaml
plugins: ["obstacle_layer", "denoise_layer", "inflation_layer"]
```

或：

```yaml
plugins: ["voxel_layer", "denoise_layer", "inflation_layer"]
```

语义路线：

```yaml
plugins: ["semantic_segmentation_layer", "denoise_layer", "inflation_layer"]
```

---

### 13.5 Collision Monitor 参数检查

重点检查：

```yaml
FrontStop.points
FrontSlow.points
time_before_collision
simulation_time_step
min_points
trigger_consecutive_points
release_consecutive_points
VelocityPolygon velocity ranges
```

最常见错误：

```text
把 stop polygon 画得太长。
```

如果 `FrontStop` 覆盖到 2 米甚至 3 米，机器人当然会因为远障碍直接停车。

---

## 14. “其他 GitHub 仓库”具体是怎么处理的

| 仓库 / 项目 | 做法 | 你应该借鉴什么 |
|---|---|---|
| `ros-navigation/navigation2` | Nav2 主仓库，包含 costmap、controller、collision monitor | 用完整导航栈分层处理风险，不要写单个二值判断 |
| `nav2_collision_monitor` | 使用 zones、stop、slowdown、limit、approach/TTC | 用小 stop zone + 大 slow zone + TTC |
| `nav2_regulated_pure_pursuit_controller` | 沿当前速度命令向未来模拟 footprint | 风险应该绑定未来动作，而不是场景本身 |
| `nav2_dwb_controller` | 采样候选速度轨迹，用 critics 打分 | 把障碍变成轨迹代价 |
| `nav2_mppi_controller` | 采样大量未来轨迹，用 CostCritic / ObstaclesCritic | 用 costmap 和 near-collision cost，而非布尔风险 |
| `ros-perception/depthimage_to_laserscan` | depth image 转 LaserScan，支持 `range_min/range_max` | 快速把视觉深度接入 Nav2 |
| `SteveMacenski/spatio_temporal_voxel_layer` | 3D voxel + 时间衰减 + FOV frustum | 处理深度点云和动态障碍残留 |
| `kiwicampus/semantic_segmentation_layer` | mask + confidence + aligned pointcloud → costmap | 把视觉语义直接变成导航代价 |
| `pepisg/nav2_segmentation_demo` | TurtleBot4 + ONNX segmentation + semantic costmap | 学习完整 demo 架构 |
| `ika-rwth-aachen/ros2-depth-anything-v3-trt` | 单目 metric depth + PointCloud2 输出 | 如果你用深度模型，可参考 ROS2 节点输出格式 |
| `open-navigation/opennav_visual_navigation` | stereo vision-only navigation with Nav2 / Isaac / NvBlox | 高阶视觉导航路线，适合算力充足平台 |

---

## 15. 最终推荐实现方案

### 如果你想最快修复当前 bug

把：

```python
risk = front_has_obstacle
```

改成：

```python
risk = f(distance, velocity, ttc, confidence, min_points, action_direction)
```

最小实现：

```python
if obstacle_points_in_front_corridor < min_points:
    state = SAFE
elif d_front < dynamic_stop_distance(v):
    state = STOP
elif ttc < 1.8:
    state = SLOW
elif d_front < 2.5:
    state = CAUTION
else:
    state = SAFE
```

---

### 如果你想和 ROS2 / Nav2 正确结合

推荐路线：

```text
视觉模型
  ↓
输出 obstacle mask + depth + confidence
  ↓
投影成 /vision/obstacle_points: PointCloud2
  ↓
local_costmap:
  - ObstacleLayer 或 VoxelLayer
  - DenoiseLayer
  - InflationLayer
  ↓
Controller:
  - RPP 或 MPPI
  ↓
Collision Monitor:
  - FrontStop
  - FrontSlow
  - FootprintApproach
  - VelocityPolygon
```

这是最接近 ROS2/Nav2 成熟项目的做法。

---

### 如果你的视觉模型是语义分割

推荐路线：

```text
RGB image
  ↓
segmentation model
  ↓
mask + confidence + label_info
  ↓
aligned depth / pointcloud
  ↓
semantic_segmentation_layer
  ↓
local_costmap + inflation
  ↓
MPPI / RPP / DWB
```

这样你的模型可以表达：

```text
地面：可通行 cost=0
草地：中高 cost
人/墙/桌椅：危险 cost=254
低置信度区域：中间 cost，不直接急停
```

---

## 16. 一个完整的落地版本

下面是一个实用的组合配置骨架。

### 16.1 视觉点云进入 local costmap

```yaml
local_costmap:
  local_costmap:
    ros__parameters:
      use_sim_time: false
      global_frame: odom
      robot_base_frame: base_link
      rolling_window: true
      width: 4.0
      height: 4.0
      resolution: 0.05
      footprint: "[[0.30, 0.25], [0.30, -0.25], [-0.30, -0.25], [-0.30, 0.25]]"
      footprint_padding: 0.03

      plugins: ["obstacle_layer", "denoise_layer", "inflation_layer"]

      obstacle_layer:
        plugin: "nav2_costmap_2d::ObstacleLayer"
        enabled: true
        observation_sources: vision_points
        vision_points:
          topic: /vision/obstacle_points
          data_type: "PointCloud2"
          marking: true
          clearing: true
          obstacle_min_range: 0.10
          obstacle_max_range: 2.50
          raytrace_min_range: 0.10
          raytrace_max_range: 3.00
          min_obstacle_height: 0.05
          max_obstacle_height: 1.50
          observation_persistence: 0.0
          expected_update_rate: 0.2

      denoise_layer:
        plugin: "nav2_costmap_2d::DenoiseLayer"
        enabled: true
        minimal_group_size: 3
        group_connectivity_type: 8

      inflation_layer:
        plugin: "nav2_costmap_2d::InflationLayer"
        enabled: true
        inflation_radius: 0.55
        cost_scaling_factor: 6.0
```

---

### 16.2 RPP 控制器

```yaml
controller_server:
  ros__parameters:
    controller_frequency: 20.0
    controller_plugins: ["FollowPath"]

    FollowPath:
      plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
      desired_linear_vel: 0.45
      max_linear_vel: 0.60
      max_angular_vel: 1.20
      max_linear_accel: 0.8
      max_linear_decel: -0.8
      lookahead_dist: 0.6
      min_lookahead_dist: 0.3
      max_lookahead_dist: 0.9
      lookahead_time: 1.5
      use_velocity_scaled_lookahead_dist: true
      use_collision_detection: true
      max_allowed_time_to_collision_up_to_carrot: 1.0
      use_cost_regulated_linear_velocity_scaling: true
      cost_scaling_dist: 0.45
      cost_scaling_gain: 0.8
      regulated_linear_scaling_min_speed: 0.10
```

---

### 16.3 Collision Monitor

```yaml
collision_monitor:
  ros__parameters:
    use_sim_time: false
    base_frame_id: base_link
    odom_frame_id: odom
    transform_tolerance: 0.2

    cmd_vel_in_topic: /cmd_vel_nav
    cmd_vel_out_topic: /cmd_vel

    observation_sources: ["vision_points"]
    vision_points:
      type: "pointcloud"
      topic: /vision/obstacle_points
      min_height: 0.05
      max_height: 1.50

    polygons: ["FrontStop", "FrontSlow", "FootprintApproach"]

    FrontStop:
      type: "polygon"
      points: "[[0.50, 0.35], [0.50, -0.35], [0.05, -0.35], [0.05, 0.35]]"
      action_type: "stop"
      min_points: 5
      trigger_consecutive_points: 2
      release_consecutive_points: 3
      visualize: true

    FrontSlow:
      type: "polygon"
      points: "[[1.50, 0.60], [1.50, -0.60], [0.05, -0.60], [0.05, 0.60]]"
      action_type: "slowdown"
      slowdown_ratio: 0.35
      min_points: 8
      trigger_consecutive_points: 2
      release_consecutive_points: 3
      visualize: true

    FootprintApproach:
      type: "polygon"
      action_type: "approach"
      footprint_topic: /local_costmap/published_footprint
      time_before_collision: 1.2
      simulation_time_step: 0.05
      min_points: 5
      visualize: true
```

---

## 17. 你应该避免的设计

不要这样：

```python
if model.detects_obstacle_in_front():
    stop_robot()
```

也不要这样：

```python
if any_obstacle_in_camera_fov:
    risk = True
```

也不要把视觉模型输出直接写成：

```text
危险 / 不危险
```

更好的输出是：

```json
{
  "obstacles": [
    {
      "class": "person",
      "distance": 1.2,
      "x": 1.2,
      "y": 0.1,
      "z": 0.7,
      "confidence": 0.92,
      "is_dynamic": true
    }
  ],
  "free_space_confidence": 0.85,
  "timestamp": 123456.7
}
```

或者直接发布 ROS2 标准消息：

```text
sensor_msgs/msg/PointCloud2
sensor_msgs/msg/LaserScan
sensor_msgs/msg/Image       # segmentation mask
sensor_msgs/msg/Image       # confidence map
```

---

## 18. 最后的判断公式

最终你可以把风险抽象成：

```text
risk = f(
    obstacle_distance,
    obstacle_angle,
    obstacle_class,
    obstacle_confidence,
    robot_velocity,
    robot_footprint,
    predicted_trajectory,
    braking_distance,
    time_to_collision,
    temporal_consistency
)
```

而不是：

```text
risk = f(front_has_obstacle)
```

如果只记一句话，就是：

> 视觉模型负责“看见什么、在哪里、距离多远、置信度多少”；ROS2/Nav2 负责“这些信息对当前动作是否构成碰撞风险”。

---

## 19. 参考来源

### Nav2 官方文档

- Nav2 Collision Monitor Node  
  <https://docs.nav2.org/configuration/packages/collision_monitor/configuring-collision-monitor-node.html>
- Using Collision Monitor  
  <https://docs.nav2.org/tutorials/docs/using_collision_monitor.html>
- Obstacle Layer Parameters  
  <https://docs.nav2.org/configuration/packages/costmap-plugins/obstacle.html>
- Inflation Layer Parameters  
  <https://docs.nav2.org/configuration/packages/costmap-plugins/inflation.html>
- Denoise Layer Parameters  
  <https://docs.nav2.org/configuration/packages/costmap-plugins/denoise.html>
- Voxel Layer Parameters  
  <https://docs.nav2.org/configuration/packages/costmap-plugins/voxel.html>
- Mapping and Localization / Costmap setup  
  <https://docs.nav2.org/setup_guides/sensors/mapping_localization.html>
- Regulated Pure Pursuit  
  <https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html>
- DWB Controller  
  <https://docs.nav2.org/configuration/packages/configuring-dwb-controller.html>
- ObstacleFootprintCritic  
  <https://docs.nav2.org/configuration/packages/trajectory_critics/obstacle_footprint.html>
- MPPI Controller  
  <https://docs.nav2.org/configuration/packages/configuring-mppic.html>
- Navigating with Semantic Segmentation  
  <https://docs.nav2.org/tutorials/docs/navigation2_with_semantic_segmentation.html>
- Using External Costmap Plugin / STVL  
  <https://docs.nav2.org/tutorials/docs/navigation2_with_stvl.html>

### GitHub 仓库 / Issues

- ROS2 Navigation2 主仓库  
  <https://github.com/ros-navigation/navigation2>
- Regulated Pure Pursuit Controller  
  <https://github.com/ros-navigation/navigation2/tree/main/nav2_regulated_pure_pursuit_controller>
- DWB Controller README  
  <https://github.com/ros-navigation/navigation2/blob/main/nav2_dwb_controller/README.md>
- Depth image to LaserScan  
  <https://github.com/ros-perception/depthimage_to_laserscan>
- Spatio-Temporal Voxel Layer  
  <https://github.com/SteveMacenski/spatio_temporal_voxel_layer>
- Semantic Segmentation Layer  
  <https://github.com/kiwicampus/semantic_segmentation_layer>
- Nav2 Semantic Segmentation Demo  
  <https://github.com/pepisg/nav2_segmentation_demo>
- Depth Anything V2 with Nav2 costmap layers issue  
  <https://github.com/ros-navigation/navigation2/issues/5536>
- ROS2 Depth Anything V3 TensorRT node  
  <https://github.com/ika-rwth-aachen/ros2-depth-anything-v3-trt>
- OpenNav visual navigation  
  <https://github.com/open-navigation/opennav_visual_navigation>

