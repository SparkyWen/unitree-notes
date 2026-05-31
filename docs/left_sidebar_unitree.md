# MuJoCo `simulate` 左侧侧边栏完整解释：以 Unitree G1 29DoF 场景为例

> 适用场景：你当前打开的是 `MuJoCo : g1_29dof scene`，左侧侧边栏是 MuJoCo 官方 `simulate` 可视化程序的调试 UI。它不是 Unitree 专用控制器界面，而是 MuJoCo 用来调试模型、仿真、传感器、渲染、物理参数、接触、约束和可视化元素的通用工具。
>
> 注意：不同 MuJoCo 版本的 UI 名称可能略有变化。下面解释以你截图中出现的栏目为准，并结合 MuJoCo `simulate` 的常见含义说明。

---

## 0. 左侧侧边栏整体结构

你截图中的左侧侧边栏大致包含这些可展开栏目：

| 栏目 | 主要作用 | 对 Unitree G1 调试的价值 |
|---|---|---|
| `File` | 文件保存、模型打印、截图、退出 | 保存当前模型、打印模型/数据、截图记录问题 |
| `Option` | UI 显示选项 | 打开/关闭 Help、Info、Profiler、Sensor 等调试面板 |
| `Simulation` | 仿真运行控制 | Pause/Run、Reset、Reload、Keyframe、噪声等 |
| `Watch` | 查看某个 `mjData` / 状态数组的具体数值 | 检查 `qpos`、`qvel`、`ctrl`、`sensordata` 等索引值 |
| `Physics` | 物理求解器、时间步、重力、接触参数、禁用/启用物理特性 | 排查机器人抖动、穿模、接触异常、求解器不稳定 |
| `Rendering` | 显示哪些模型元素、OpenGL 效果 | 显示关节、接触点、力、惯性、碰撞几何、wireframe 等 |
| `Visualization` | 相机、灯光、颜色、比例尺、RGBA 显示风格 | 调整可视化方式，帮助观察机器人结构与物理状态 |
| `Group enable` | 按 group 开关 geom/site/joint/tendon/actuator/skin/flex 显示 | 分组隐藏/显示模型组件，定位身体部件或传感器对象 |

最重要的理解方式是：

```text
File        = 文件/输出
Option      = UI 调试面板开关
Simulation  = 仿真运行控制
Watch       = 查看底层数据数组
Physics     = 改物理引擎和接触求解行为
Rendering   = 决定画什么
Visualization = 决定怎么画
Group enable  = 按组显示/隐藏对象
```

---

# 1. File 栏目

截图中 `File` 栏目包含：

```text
Save xml    Save mjb
Print model Print data
Quit        Screenshot
```

---

## 1.1 `Save xml`

### 作用

把当前加载后的 MuJoCo 模型保存成 XML 文件。

### 重要理解

MuJoCo 加载模型时，会把原始 XML、include 文件、默认属性、asset、compiler 处理结果等解析成内部 `mjModel`。`Save xml` 保存的是 MuJoCo 当前理解后的模型结构。

### 什么时候用

| 场景 | 用法 |
|---|---|
| 你怀疑 include/default 被展开后和你想的不一样 | 保存 XML 后检查最终模型 |
| 想确认 Unitree G1 的 joint/actuator/sensor 是否真的被加载 | 保存 XML 后搜索 `<joint>`、`<actuator>`、`<sensor>` |
| 想把当前模型状态导出给别人复现 | 保存当前 XML |

### 注意

`Save xml` 保存的是模型定义，不一定保存当前仿真瞬间的所有动态状态，例如当前速度、接触缓存等。动态状态通常在 `mjData` 中。

---

## 1.2 `Save mjb`

### 作用

保存 MuJoCo binary model，即 `.mjb` 文件。

### `.mjb` 是什么？

`.mjb` 是 MuJoCo 编译后的二进制模型格式，比 XML 读取更快，也不需要重新解析 XML。

### 什么时候用

| 场景 | 是否适合 |
|---|---|
| 快速加载固定模型 | 适合 |
| 部署/测试中不希望每次解析 XML | 适合 |
| 还在频繁修改 XML | 不太适合，因为 `.mjb` 不方便人工编辑 |
| 想检查模型文本结构 | 不适合，应使用 `Save xml` |

### 对 Unitree G1 的意义

如果你已经确认 `g1_29dof` 模型没有问题，可以保存 `.mjb` 用于更快加载。但在调试 joint order、actuator order、sensor order 时，还是 XML 更直观。

---

## 1.3 `Print model`

### 作用

把当前 `mjModel` 的结构信息打印到终端。

### 可能包含什么

通常会输出模型中的：

- body 数量；
- joint 数量；
- geom 数量；
- actuator 数量；
- sensor 数量；
- qpos/qvel/ctrl 维度；
- name table；
- 各类对象的索引和属性。

### 什么时候用

你想确认这些内容时非常有用：

```text
G1 到底有多少 joint？
actuator 顺序是什么？
sensor 顺序是什么？
qpos 第 0 个对应什么？
right_shoulder_pitch_torque 的 sensor 地址在哪里？
```

### 对 Unitree / RL 调试的核心价值

很多机器人控制错误不是动力学错误，而是 **索引顺序错了**：

```text
policy 输出的第 5 维本来应该控制 left_knee，
但代码错误地发给了 right_hip_pitch。
```

`Print model` 可以帮助你核对 MuJoCo 模型内部顺序。

---

## 1.4 `Print data`

### 作用

打印当前 `mjData` 的动态数据。

### `mjData` 是什么？

可以把 `mjModel` 和 `mjData` 区分成：

| 对象 | 含义 | 类比 |
|---|---|---|
| `mjModel` | 模型本身的静态定义 | 机器人图纸 |
| `mjData` | 当前仿真时刻的动态状态 | 机器人当前状态 |

`Print data` 可能包含：

- `qpos`：广义位置；
- `qvel`：广义速度；
- `qacc`：广义加速度；
- `ctrl`：控制输入；
- `sensordata`：传感器数据；
- contact 信息；
- actuator force；
- solver 信息。

### 对 Unitree G1 的意义

如果你想排查：

```text
为什么机器人不动？
为什么 torque 是 0？
为什么 qpos 不变？
为什么 sensordata 和代码读到的不一致？
```

可以用 `Print data` 打印当前帧数据。

---

## 1.5 `Quit`

### 作用

退出 MuJoCo `simulate` 窗口。

---

## 1.6 `Screenshot`

### 作用

保存当前窗口截图。

### 什么时候用

| 场景 | 用法 |
|---|---|
| 记录机器人异常姿态 | 截图保存 |
| 记录 Profiler/Sensor 状态 | 打开对应面板后截图 |
| 给别人复现 bug | 截图 + 终端日志 + XML 一起发 |

---

# 2. Option 栏目

截图中 `Option` 栏目包含：

```text
Help        Info
Profiler    Sensor
Pause update Fullscreen
Vertical Sync Busy Wait
Spacing      Tight
Color        Default
Font         100 %
```

---

## 2.1 `Help`

### 作用

打开/关闭屏幕中央的快捷键帮助面板。

你截图中间半透明区域就是 `Help` 打开后的结果。

### 常见快捷键

| 功能 | 快捷键 |
|---|---|
| Play / Pause | `Space` |
| Speed Up / Down | `+` / `-` |
| Step Back / Forward | 左右方向键 |
| Toggle Left / Right UI | `Tab` / `Shift + Tab` |
| Cycle cameras | `[` / `]` |
| Free camera | `Esc` |
| Select | 双击 |
| Zoom | 滚轮 / 中键拖动 |
| View Orbit | 左键拖动 |
| View Pan | Shift + 右键拖动 |
| Object Rotate | Ctrl + Shift + 拖动 |
| Object Translate | Ctrl + Shift + 右键拖动 |
| Help | `F1` |
| Info | `F2` |
| Profiler | `F3` |
| Sensors | `F4` |
| Full screen | `F5` |

### 对 Unitree 调试的意义

当你要看 G1 的脚底、膝盖、腰部、肩部时，鼠标视角控制很重要。`Help` 面板就是告诉你如何旋转、平移、缩放、选择对象。

---

## 2.2 `Info`

### 作用

打开/关闭左下角状态信息面板。

你截图左下角类似：

```text
Time     1000.440
Size     29 (0 con)
CPU      0.088
Solver   -15.0 (1 it)
FPS      13
Memory   0.3% of 15M
Islands  1
```

### 字段解释

| 字段 | 含义 | 怎么看 |
|---|---|---|
| `Time` | 仿真时间 | 当前仿真已经运行到多少秒 |
| `Size` | 模型/约束规模摘要 | `29 (0 con)` 中 `0 con` 表示当前接触约束数接近 0 |
| `CPU` | 每步物理仿真耗时 | 单位通常是 ms，越低越快 |
| `Solver` | 求解器收敛状态 | `-15.0 (1 it)` 表示残差很小、迭代很少 |
| `FPS` | 渲染帧率 | 画面刷新速度，不等于物理步频 |
| `Memory` | MuJoCo 内部内存使用 | 判断是否接近分配上限 |
| `Islands` | 约束岛数量 | 多个互不接触的动力学系统会形成多个 island |

### 你截图中的判断

你的截图里：

```text
CPU 很低，但是 FPS 只有 11~13
```

这说明物理仿真本身很轻，慢的更可能是渲染、远程桌面、WSLg、OpenGL 或显示层。

---

## 2.3 `Profiler`

### 作用

打开/关闭右侧 Profiler 图表。

Profiler 主要展示 MuJoCo 物理引擎内部状态，例如：

- Counts；
- Convergence；
- Dimensions；
- CPU time。

### 对 Unitree G1 调试的价值

Profiler 不是看机器人关节角度的，而是看：

```text
仿真是否稳定？
接触约束多不多？
solver 迭代是否暴涨？
CPU 时间花在 collision 还是 solve？
```

### 什么时候打开

| 场景 | 是否需要打开 Profiler |
|---|---|
| 机器人正常站着，只看外观 | 可不打开 |
| 机器人一落地就抖动 | 必开 |
| 机器人走路时 FPS 低 | 必开 |
| 想知道是碰撞慢还是求解慢 | 必开 |
| RL policy 部署后机器人炸飞 | 必开 |

---

## 2.4 `Sensor`

### 作用

打开/关闭底部 Sensor data 图。

Sensor data 图显示的是模型 XML 中 `<sensor>` 定义出来的传感器输出，数据来自 `mjData.sensordata`。

### 关键理解

Sensor 图不是时间序列图。它的横轴通常是 sensor data 数组的 index，纵轴是当前这一帧的 sensor 数值。

例如你之前截图底部出现：

```text
sensor_index: 80, name: right_shoulder_pitch_torque, dim: 1
```

表示当前选中的是：

```text
右肩 pitch 关节力矩传感器
```

### 对 Unitree G1 调试的价值

Sensor 最适合检查：

- joint position 是否正常；
- joint velocity 是否异常；
- torque 是否饱和；
- IMU 是否有值；
- sensor 顺序是否和代码 observation 顺序一致；
- 是否出现 NaN / inf / 巨大尖峰。

---

## 2.5 `Pause update`

### 作用

控制暂停状态下 UI / 图表 / 状态显示是否继续更新。

### 怎么理解

当仿真暂停时，有些 UI 仍然可以继续刷新，例如你移动相机、选择对象、查看 Watch 数值。`Pause update` 和暂停时的界面更新行为有关。

### 什么时候用

| 场景 | 建议 |
|---|---|
| 想暂停后仔细看当前状态 | 可以开启/保持更新 |
| 想减少暂停时 CPU/GPU 开销 | 可以关闭 |
| 想对比某一帧的 sensor/profiler | 暂停后打开相关图表 |

---

## 2.6 `Fullscreen`

### 作用

切换全屏显示。

### 什么时候用

适合看机器人细节，尤其是：

- 脚底接触；
- 手臂姿态；
- 关节轴；
- contact force；
- inertia box；
- collision geometry。

---

## 2.7 `Vertical Sync`

### 作用

开启/关闭垂直同步，也就是 VSync。

### 怎么理解

VSync 会让渲染帧率和显示器刷新率同步，通常用于避免画面撕裂。

### 对性能的影响

| 状态 | 影响 |
|---|---|
| 开启 VSync | 画面更稳定，但 FPS 可能被显示器刷新率限制 |
| 关闭 VSync | 可能获得更高 FPS，但画面可能撕裂 |

### 对你当前截图的意义

你当前 FPS 约 11~13，但物理 CPU 时间很低，这更像渲染/显示问题。可以尝试切换 `Vertical Sync` 观察 FPS 是否变化。

---

## 2.8 `Busy Wait`

### 作用

控制等待下一帧时是否使用 busy-wait。

### 怎么理解

程序为了保持实时播放速度，有时需要等待。等待方式大致有两种：

| 方式 | 特点 |
|---|---|
| sleep 等待 | CPU 占用低，但计时可能不够精细 |
| busy-wait | CPU 占用高，但计时更精确 |

### 什么时候用

| 场景 | 建议 |
|---|---|
| 普通查看模型 | 关闭即可 |
| 需要更稳定的实时同步/计时 | 可尝试开启 |
| 笔记本发热/CPU 占用高 | 不建议开启 |

---

## 2.9 `Spacing`

### 作用

调整 UI 控件间距。

截图中是：

```text
Spacing: Tight
```

表示控件排列比较紧凑。

### 选项含义

| 选项 | 效果 |
|---|---|
| Tight | 紧凑，屏幕能显示更多控件 |
| Normal / Wide | 更宽松，易读但占空间 |

---

## 2.10 `Color`

### 作用

调整 UI 配色主题。

截图中是：

```text
Color: Default
```

一般保持默认即可。

---

## 2.11 `Font`

### 作用

调整 UI 字体大小。

截图中是：

```text
Font: 100 %
```

如果你在高分屏、远程桌面或截图中看不清，可以把字体调大。

---

# 3. Simulation 栏目

截图中 `Simulation` 栏目包含：

```text
Pause       Run
Reset       Reload
Align       Copy state
Key         -1
Load key    Save key
Noise scale
Noise rate
History
```

---

## 3.1 `Pause` / `Run`

### 作用

暂停或继续仿真。

### 对应快捷键

```text
Space
```

### 怎么用

| 任务 | 操作 |
|---|---|
| 观察某一瞬间姿态 | Pause |
| 继续仿真 | Run |
| 一边观察 Sensor data 一边看数值变化 | Run + Sensor |
| 机器人快要炸飞时抓一帧 | 快速 Pause |

---

## 3.2 `Reset`

### 作用

重置仿真状态到初始状态。

### 会重置什么

通常包括：

- `qpos` 回到初始姿态；
- `qvel` 清零或回到初始速度；
- control 状态回到初始；
- contact/solver 缓存清空；
- 时间可能回到 0 或重置状态。

### 对 Unitree G1 的意义

如果机器人摔倒、炸飞、姿态异常，最直接就是 `Reset`。

---

## 3.3 `Reload`

### 作用

重新加载模型文件。

### 和 Reset 的区别

| 操作 | 作用范围 |
|---|---|
| Reset | 不重新读 XML，只重置当前状态 |
| Reload | 重新读取模型文件，重新编译模型 |

### 什么时候用 Reload

| 场景 | 操作 |
|---|---|
| 修改了 XML | Reload |
| 修改了 mesh / asset | Reload |
| 修改了 actuator/sensor/joint 配置 | Reload |
| 只是机器人姿态乱了 | Reset 即可 |

---

## 3.4 `Align`

### 作用

把相机视角对齐到当前选中对象或模型的合适视角。

### 什么时候用

- 视角转乱了；
- 找不到机器人；
- 选择了某个 body 后想对齐它；
- 想快速回到整机视角。

---

## 3.5 `Copy state`

### 作用

复制当前仿真状态。

### 可能复制的内容

通常会复制当前状态向量，例如：

```text
qpos / qvel / act / time / ctrl 等
```

具体输出格式依赖 MuJoCo 版本和 simulate 实现。

### 对调试的意义

如果你发现一个异常瞬间，例如：

```text
G1 刚落地时膝盖突然反折
```

可以 `Pause` 后 `Copy state`，把该状态保存下来用于复现。

---

## 3.6 `Key`

截图中：

```text
Key: -1
```

### 作用

选择当前 keyframe 编号。

### 什么是 keyframe

MuJoCo XML 可以定义 `<keyframe>`，保存一组状态，例如：

- 初始站立姿态；
- 蹲下姿态；
- 抬腿姿态；
- 某个测试状态。

### `-1` 的含义

通常表示：

```text
当前没有选中特定 keyframe
```

或者模型没有加载某个 keyframe 作为当前目标。

---

## 3.7 `Load key`

### 作用

把当前选择的 keyframe 加载到仿真中。

### 用法

如果 `Key = 0`，点击 `Load key` 会把第 0 个 keyframe 的状态加载出来。

### 对 Unitree G1 的意义

如果 XML 中定义了不同测试姿态，可以用它快速切换。

例如：

```text
key 0 = default standing
key 1 = crouch
key 2 = single leg
```

---

## 3.8 `Save key`

### 作用

把当前状态保存为 keyframe。

### 什么时候用

| 场景 | 用法 |
|---|---|
| 调整出一个好的初始站姿 | Save key |
| 想保存摔倒前一刻状态 | Save key |
| 做控制器测试，需要固定初始条件 | Save key |

### 注意

保存 keyframe 后是否写回 XML，取决于具体版本和保存流程。建议保存后再用 `Save xml` 导出。

---

## 3.9 `Noise scale`

### 作用

控制仿真中噪声的整体强度。

### 通常影响什么

可能影响 sensor noise 或扰动噪声，具体取决于模型是否定义了 sensor noise 或相关配置。

### 对 RL 的意义

训练和测试机器人策略时，噪声可以模拟真实世界不确定性：

- IMU 噪声；
- 关节编码器噪声；
- torque 测量噪声；
- 状态估计误差。

如果你只是看模型，通常保持 0。

---

## 3.10 `Noise rate`

### 作用

控制噪声变化频率。

### 怎么理解

| 参数 | 含义 |
|---|---|
| Noise scale | 噪声幅度有多大 |
| Noise rate | 噪声变化有多快 |

例如：

```text
scale 大，rate 小：噪声幅度大，但变化慢
scale 小，rate 大：噪声幅度小，但变化快
```

---

## 3.11 `History`

### 作用

显示或控制 simulate 内部的历史状态/历史显示相关功能。

### 怎么理解

在 `simulate` 中，Profiler、Sensor、状态显示等都可能维护最近若干帧的历史数据。`History` 通常和这些历史记录或时间回看有关。

### 普通使用建议

大多数情况下不需要主动调整。你主要关注：

- Pause/Run；
- Reset/Reload；
- Copy state；
- Load/Save key。

---

# 4. Watch 栏目

截图中 `Watch` 栏目包含：

```text
Field
Index
Value
```

在你的截图里类似：

```text
Field: qpos
Index: 0
Value: -0.000772458
```

---

## 4.1 Watch 是什么？

`Watch` 是一个非常实用的底层数据查看器。

它允许你查看某个数据数组中的某个 index 当前是多少。

最常用的是查看 MuJoCo `mjData` 里的数组，例如：

```text
qpos
qvel
qacc
ctrl
sensordata
actuator_force
xpos
xquat
```

---

## 4.2 `Field`

### 作用

选择要查看的字段名。

例如：

```text
Field = qpos
```

表示查看当前广义位置数组。

### 常见 Field 解释

| Field | 含义 | 对 Unitree 调试的用途 |
|---|---|---|
| `qpos` | 广义位置 | 看 base pose、关节角度 |
| `qvel` | 广义速度 | 看 base velocity、关节速度 |
| `qacc` | 广义加速度 | 看是否有异常加速度 |
| `ctrl` | 控制输入 | 看控制器有没有真的发命令 |
| `sensordata` | 传感器输出 | 看 sensor 数值 |
| `actuator_force` | actuator 实际输出力/力矩 | 看电机输出是否饱和 |

---

## 4.3 `Index`

### 作用

选择数组中的第几个元素。

例如：

```text
Field = qpos
Index = 0
```

表示查看：

```text
data.qpos[0]
```

---

## 4.4 `Value`

### 作用

显示当前 `Field[Index]` 的值。

例如：

```text
Value = -0.000772458
```

表示当前：

```text
data.qpos[0] = -0.000772458
```

---

## 4.5 Watch 对 Unitree G1 最重要的用途

### 用途 1：确认 `ctrl` 有没有发进去

如果机器人不动，可以看：

```text
Field = ctrl
Index = 0, 1, 2, ...
```

如果所有 `ctrl` 都是 0，说明控制器没有真正输出到 MuJoCo。

---

### 用途 2：检查 qpos / qvel 是否爆炸

如果机器人突然飞走，可以看：

```text
qpos 是否变成极大值？
qvel 是否突然几百几千？
```

---

### 用途 3：检查 sensor 顺序

如果你代码里认为：

```text
sensordata[80] = right_shoulder_pitch_torque
```

可以通过 Watch 或 Sensor 图核对。

但更推荐在代码中通过名字查地址，而不是硬编码 index。

---

# 5. Physics 栏目

`Physics` 是左侧最重要、也最容易误改出问题的栏目。它控制 MuJoCo 物理引擎的核心参数。

截图中包含：

```text
Integrator
Cone
Jacobian
Solver

Algorithmic Parameters
Physical Parameters
Disable Flags
Enable Flags
Contact Override
Actuator Group Enable
```

---

# 5.1 基础求解设置

截图中显示：

```text
Integrator: Euler
Cone:       Pyramidal
Jacobian:   Auto
Solver:     Newton
```

---

## 5.1.1 `Integrator`

### 作用

选择时间积分器。积分器决定 MuJoCo 如何从当前状态推进到下一帧。

### 常见选项

| Integrator | 含义 | 特点 |
|---|---|---|
| `Euler` | 显式/半隐式欧拉类积分 | 快，简单，常用 |
| `RK4` | 四阶 Runge-Kutta | 精度高但更慢 |
| `implicit` / `implicitfast` | 隐式积分 | 对刚性系统更稳定，适合高刚度或强阻尼场景 |

### 你截图中的 `Euler`

`Euler` 比较常见，速度快。但如果你把 Unitree G1 的 PD 增益调得很高、接触很硬、timestep 又偏大，Euler 可能更容易出现振荡或不稳定。

### 调试建议

| 现象 | 可考虑 |
|---|---|
| 机器人站立轻微抖动 | 减小 timestep，或尝试更稳定的 integrator |
| 高刚度 PD 导致爆炸 | 降低 kp/kd，减小 timestep，或尝试 implicit |
| 只是看模型 | Euler 足够 |

---

## 5.1.2 `Cone`

### 作用

选择摩擦锥模型。

### 常见选项

| Cone | 含义 | 特点 |
|---|---|---|
| `Pyramidal` | 用多面锥近似摩擦锥 | 更快，常用 |
| `Elliptic` | 椭圆摩擦锥 | 更平滑，但可能更重 |

### 对机器人脚底接触的意义

G1 走路时，脚底和地面之间的摩擦非常关键。`Cone` 会影响：

- 脚底是否容易滑；
- 接触求解是否稳定；
- solver 计算量；
- 摩擦方向是否平滑。

### 你的截图

```text
Cone = Pyramidal
```

这是常见选择。

---

## 5.1.3 `Jacobian`

### 作用

选择约束 Jacobian 的存储和计算方式。

### 常见选项

| Jacobian | 含义 |
|---|---|
| `Dense` | 稠密矩阵 |
| `Sparse` | 稀疏矩阵 |
| `Auto` | MuJoCo 根据模型规模自动选择 |

### 你的截图

```text
Jacobian = Auto
```

一般保持 Auto 即可。

### 对 Unitree G1 的意义

G1 有不少 body、joint、actuator 和 contact。Auto 通常能选择比较合适的内部表示。

---

## 5.1.4 `Solver`

### 作用

选择约束求解器算法。

### 常见选项

| Solver | 特点 |
|---|---|
| `PGS` | Projected Gauss-Seidel，较简单，速度快 |
| `CG` | Conjugate Gradient，适合某些中等问题 |
| `Newton` | 更强的二阶求解器，常用于更稳定/精确约束求解 |

### 你的截图

```text
Solver = Newton
```

这通常是比较强的求解方式。

### 对 Unitree G1 的意义

人形机器人脚底接触、关节限制、摩擦约束比较复杂。`Newton` 往往更稳，但如果接触很多，计算可能更重。

---

# 5.2 Algorithmic Parameters

截图中 `Algorithmic Parameters` 包含：

```text
Timestep
Iterations
Tolerance
LS Iter
LS Tol
Noslip Iter
Noslip Tol
CCD Iter
CCD Tol
SDF Iter
SDF Tol
```

这些参数决定仿真步长和求解器停止条件。

---

## 5.2.1 `Timestep`

截图中：

```text
Timestep: 0.005
```

### 作用

每个物理仿真 step 的时间长度。

```text
0.005 s = 5 ms = 200 Hz
```

### 对 Unitree G1 的意义

机器人控制非常依赖 timestep。

| timestep | 含义 |
|---|---|
| 小 | 更稳定、更精细，但更耗 CPU |
| 大 | 更快，但容易不稳定 |

### 常见判断

| 现象 | 可能处理 |
|---|---|
| 机器人接触地面后抖动 | 减小 timestep |
| 高速运动穿透 | 减小 timestep / 开启 CCD |
| 仿真很慢但稳定 | 可以尝试增大 timestep |
| RL policy 训练环境是 0.005 | 部署时最好保持一致 |

### 重要提醒

如果 RL 策略训练时 timestep 是 0.005，部署时改成 0.002 或 0.01，可能导致策略表现明显变化。

---

## 5.2.2 `Iterations`

截图中：

```text
Iterations: 100
```

### 作用

约束求解器最大迭代次数。

### 怎么看

Profiler 里 `Solver -15.0 (1 it)` 中的 `(1 it)` 表示当前实际只用了 1 次迭代。

如果最大 `Iterations = 100`，但实际经常打满 100，说明求解很困难。

### 对 Unitree G1 的意义

| 现象 | 解释 |
|---|---|
| iteration 很低 | 求解轻松 |
| iteration 偶尔升高 | 接触变化，正常 |
| iteration 长期很高 | 接触/约束/模型参数可能有问题 |
| iteration 打满 | 求解器可能没收敛 |

---

## 5.2.3 `Tolerance`

截图中：

```text
Tolerance: 1e-08
```

### 作用

求解器收敛容差。误差低于这个阈值时可以停止迭代。

### 怎么理解

| Tolerance | 效果 |
|---|---|
| 更小 | 更精确，但可能迭代更多 |
| 更大 | 更快，但可能精度下降 |

### 对 G1 的建议

一般不要随意调。除非你明确知道 solver 没收敛，或为了速度做 trade-off。

---

## 5.2.4 `LS Iter`

截图中：

```text
LS Iter: 50
```

### 作用

Line Search 最大迭代次数。

### 什么是 Line Search

Newton 求解器会尝试沿某个方向更新解。Line Search 用来决定这一步走多大。

### 怎么看

如果 Line Search 经常打满，说明求解器找不到合适步长，可能是接触/约束条件很难解。

---

## 5.2.5 `LS Tol`

截图中：

```text
LS Tol: 0.01
```

### 作用

Line Search 的停止容差。

### 普通建议

一般不需要调。除非你在深入调 MuJoCo solver。

---

## 5.2.6 `Noslip Iter`

截图中：

```text
Noslip Iter: 0
```

### 作用

No-slip 后处理迭代次数，用来减少接触中的滑移误差。

### 对脚底接触的意义

人形机器人走路时脚底如果不该滑，却出现轻微滑动，可以关注 no-slip 相关参数。

### 你的截图

```text
Noslip Iter = 0
```

表示不进行 no-slip 后处理。

---

## 5.2.7 `Noslip Tol`

截图中：

```text
Noslip Tol: 1e-06
```

### 作用

No-slip 后处理的容差。

如果 `Noslip Iter = 0`，这个参数基本不会发挥作用。

---

## 5.2.8 `CCD Iter`

截图中：

```text
CCD Iter: 35
```

### 作用

Continuous Collision Detection，连续碰撞检测的迭代次数。

### CCD 是什么

普通碰撞检测是离散的：

```text
上一帧没碰撞
下一帧已经穿过去了
```

如果物体速度很快，可能发生穿透。CCD 会检查连续运动路径，减少高速穿透。

### 对 G1 的意义

通常 G1 关节运动不会像子弹一样快，但如果：

- timestep 太大；
- 控制输出太激烈；
- 脚高速砸地；
- 手臂高速撞击物体；

CCD 可能有帮助。

---

## 5.2.9 `CCD Tol`

截图中：

```text
CCD Tol: 1e-06
```

### 作用

CCD 求解容差。

容差越小越精确，但可能越慢。

---

## 5.2.10 `SDF Iter`

截图中：

```text
SDF Iter: 10
```

### 作用

Signed Distance Field 相关碰撞/距离求解迭代次数。

### SDF 是什么

SDF 表示有符号距离场，用于表示点到物体表面的距离：

- 正值：在外部；
- 负值：在内部；
- 0：在表面。

如果模型使用 SDF 相关几何或碰撞，`SDF Iter` 会影响求解精度。

---

## 5.2.11 `SDF Tol`

截图中：

```text
SDF Tol: 1e-06
```

### 作用

SDF 求解容差。

普通 G1 模型如果没有复杂 SDF 几何，一般不需要关心。

---

# 5.3 Physical Parameters

截图中 `Physical Parameters` 包含：

```text
Gravity
Wind
Magnetic
Density
Viscosity
Imp Ratio
```

---

## 5.3.1 `Gravity`

截图中：

```text
Gravity: 0 0 -9.81
```

### 作用

设置重力加速度向量。

```text
x = 0
y = 0
z = -9.81
```

表示 z 轴向下，地球标准重力。

### 对 Unitree G1 的意义

重力方向错了，机器人会出现非常奇怪的行为。

| 设置 | 结果 |
|---|---|
| `0 0 -9.81` | 正常地球重力 |
| `0 0 0` | 失重 |
| `0 0 9.81` | 向上重力，机器人会往上“掉” |
| `0 -9.81 0` | y 方向重力，世界坐标定义可能错乱 |

### 调试建议

除非特殊实验，不要改。

---

## 5.3.2 `Wind`

截图中：

```text
Wind: 0 0 0
```

### 作用

设置全局风速。

### 对 G1 的意义

如果模型启用了空气动力相关效果，wind 会影响物体。但普通刚体机器人仿真中通常影响不大。

---

## 5.3.3 `Magnetic`

截图中：

```text
Magnetic: 0 -0.5 0
```

### 作用

设置环境磁场方向/强度。

### 对 G1 的意义

通常只有模型中有 magnetometer 传感器时才重要。

如果没有磁力计 sensor，可以暂时忽略。

---

## 5.3.4 `Density`

截图中：

```text
Density: 0
```

### 作用

流体密度参数，和空气/流体阻力相关。

### 怎么理解

如果 density > 0，物体运动可能受到介质阻力影响。

### 对 G1 的意义

普通地面行走仿真中通常设置为 0，不模拟空气阻力。

---

## 5.3.5 `Viscosity`

截图中：

```text
Viscosity: 0
```

### 作用

流体黏性参数。

### 对 G1 的意义

普通机器人行走仿真一般为 0。

如果模拟水下、液体、强阻尼介质，才会用到。

---

## 5.3.6 `Imp Ratio`

截图中：

```text
Imp Ratio: 1
```

### 作用

高级接触/约束相关参数，通常和接触阻抗、摩擦维度相对法向维度的权重比例有关。

### 普通理解

这个参数影响接触约束中不同方向的“硬度/阻抗比例”。

### 对 G1 的意义

如果你只是跑 G1，不建议随意改。改错可能导致：

- 脚底接触变软；
- 摩擦表现异常；
- solver 更难收敛；
- 机器人站不稳。

---

# 5.4 Disable Flags

截图中 `Disable Flags` 包含大量开关：

```text
Constraint    Equality
Frictionloss  Limit
Contact       Spring
Damper        Gravity
Clampctrl     Warmstart
Filterparent  Actuation
Refsafe       Sensor
Midphase      Eulerdamp
AutoReset     NativeCCD
Island
```

这些开关的共同逻辑是：

```text
点亮/启用某个 Disable Flag = 禁用对应物理特性
```

也就是说，它们不是“打开某个功能”，而是“关闭某个功能”。

这是非常容易误解的地方。

---

## 5.4.1 `Constraint`

### 作用

禁用全部约束求解。

### 约束包括什么

- 接触约束；
- joint limit；
- equality constraint；
- tendon constraint；
- friction constraint；
- 其他 solver 约束。

### 后果

禁用后物理会非常不真实，机器人可能穿地、穿模、关节限制失效。

### 建议

只用于极端调试，不要在正常 G1 仿真中启用。

---

## 5.4.2 `Equality`

### 作用

禁用 equality constraints。

### Equality constraint 是什么

它可以把两个 body、joint、tendon 等通过约束关系绑定起来，例如：

- weld；
- connect；
- joint equality；
- tendon equality。

### 对 G1 的意义

如果模型中某些部件靠 equality 绑定，禁用后结构可能松掉或不再满足约束。

---

## 5.4.3 `Frictionloss`

### 作用

禁用关节或自由度中的 friction loss。

### Friction loss 是什么

它模拟类似库仑摩擦的损耗。

### 对 G1 的意义

禁用后关节可能变得更“滑”，能量损失更少。

---

## 5.4.4 `Limit`

### 作用

禁用 joint limit 约束。

### 后果

关节可以超过 XML 中设定的范围。

### 对 Unitree G1 很危险

如果禁用，可能出现：

```text
膝盖反折
肩关节转穿身体
踝关节角度超过真实范围
```

正常调试不要禁用。

---

## 5.4.5 `Contact`

### 作用

禁用接触。

### 后果

机器人会穿过地面、穿过物体，脚底不会产生支撑力。

### 对 G1 的意义

如果你看到 `0 con`，可以检查是不是误开了 `Contact` disable flag。

正常走路绝对不能禁用 Contact。

---

## 5.4.6 `Spring`

### 作用

禁用弹簧类 passive force。

### 对 G1 的意义

如果模型中 joint 或 tendon 使用 spring 参数，禁用后会失去弹性恢复力。

---

## 5.4.7 `Damper`

### 作用

禁用阻尼类 passive force。

### 对 G1 的意义

阻尼对机器人稳定很重要。禁用后可能出现：

- 关节更容易振荡；
- 能量不容易耗散；
- 机器人抖动加剧。

---

## 5.4.8 `Gravity`

### 作用

禁用重力。

### 后果

机器人进入失重状态。

### 用途

可以用于调试单独关节控制，不受重力影响。

### 正常 G1 行走

不要禁用。

---

## 5.4.9 `Clampctrl`

### 作用

禁用控制输入裁剪。

### 背景

MuJoCo actuator 可以设置 `ctrlrange`，限制控制输入范围。

如果不禁用 clamp，控制输入会被限制在合法范围内。

### 禁用后的风险

控制器输出可能超过 actuator 允许范围，导致：

- 关节力矩过大；
- 模型爆炸；
- 与真实机器人控制范围不一致。

### 对 RL 的意义

如果 RL 训练时依赖 action clipping，部署时也必须保持一致。

---

## 5.4.10 `Warmstart`

### 作用

禁用 solver warm-start。

### Warm-start 是什么

求解器会用上一帧的解作为下一帧初始猜测，从而加快收敛。

### 禁用后的影响

- 求解可能更慢；
- iteration 可能增加；
- 但有时用于排查 warm-start 缓存导致的异常。

### 普通建议

正常保持 warm-start 开启，也就是不要打开 `Warmstart` disable flag。

---

## 5.4.11 `Filterparent`

### 作用

禁用父子 body 之间的接触过滤。

### 背景

机器人相邻 body 通常不应该互相碰撞，例如大腿和小腿之间、躯干和肩部连接处。MuJoCo 可以自动过滤父子关系接触。

### 禁用后的后果

相邻 body 可能产生大量无意义接触，导致：

- contact 数暴涨；
- solve 时间变高；
- 机器人抖动；
- 自碰撞异常。

### 对 G1 的意义

正常不要禁用。

---

## 5.4.12 `Actuation`

### 作用

禁用 actuator 作用。

### 后果

控制器发了 `ctrl`，机器人也不会被电机驱动。

### 排查用途

如果你想看纯被动物理，可以禁用 actuation。

### 如果机器人不动

请检查是否误开了 `Actuation` disable flag。

---

## 5.4.13 `Refsafe`

### 作用

禁用 solver reference 参数的安全保护。

### 背景

MuJoCo 接触和约束中的 `solref` 参数如果设置得过硬、过快，可能导致不稳定。Refsafe 会对一些危险组合做保护。

### 禁用后的风险

可能允许更激进的接触参数，导致：

- 接触发硬；
- solver 不稳定；
- 抖动；
- 爆炸。

### 建议

正常不要禁用。

---

## 5.4.14 `Sensor`

### 作用

禁用传感器计算。

### 后果

`sensordata` 不再更新，可能保持 0 或旧值。

### 对 Unitree G1 的意义

如果你发现 Sensor data 不变，检查是否误开了 `Sensor` disable flag。

---

## 5.4.15 `Midphase`

### 作用

禁用碰撞检测中的 midphase 阶段。

### 碰撞检测大致阶段

| 阶段 | 含义 |
|---|---|
| broadphase | 粗略筛选可能碰撞的对象 |
| midphase | 对复杂几何进一步筛选 |
| narrowphase | 精确碰撞计算 |

### 禁用后的影响

可能让碰撞检测更慢或行为不同。

### 普通建议

不要改。

---

## 5.4.16 `Eulerdamp`

### 作用

禁用 Euler 积分器中与阻尼处理相关的稳定化机制。

### 对 G1 的意义

如果使用 Euler 积分器，关节 damping 的处理方式会影响稳定性。禁用后可能导致振荡变明显。

### 建议

除非研究积分器细节，否则不要改。

---

## 5.4.17 `AutoReset`

### 作用

禁用自动重置机制。

### 背景

某些情况下，如果仿真出现严重数值异常，simulate 可能自动 reset。

### 禁用后的影响

严重错误时不会自动重置，方便观察爆炸过程，但可能导致状态继续发散。

---

## 5.4.18 `NativeCCD`

### 作用

禁用原生 CCD 相关处理。

### 对 G1 的意义

如果你没有高速穿透问题，一般不用管。若在测试快速撞击或高速腿部运动，CCD 相关设置才重要。

---

## 5.4.19 `Island`

### 作用

禁用 island 相关求解优化。

### Island 是什么

如果一个场景中有多个互不接触、互不约束的物理系统，它们可以被分成多个 island 分别求解。

### 对 G1 的意义

通常 G1 是一个整体系统，截图里 `Islands = 1`。正常不需要改。

---

# 5.5 Enable Flags

截图中 `Enable Flags` 包含：

```text
Override
Energy
Fwdinv
InvDiscrete
MultiCCD
Sleep
```

这些是“启用额外功能”的开关，和 Disable Flags 相反。

---

## 5.5.1 `Override`

### 作用

启用 contact override。

### 背景

如果开启 override，下面 `Contact Override` 中的参数会覆盖模型 XML 里的接触参数。

### 对 G1 的意义

可以快速测试不同接触参数，而不用改 XML。

例如你怀疑脚底太滑，可以用 override 临时改 friction。

---

## 5.5.2 `Energy`

### 作用

启用能量计算。

### 能量可能包括

- kinetic energy；
- potential energy；
- total energy。

### 对调试的意义

如果系统没有控制输入、没有阻尼，能量应该比较守恒。能量突然爆炸可能表示数值不稳定。

### 普通建议

调试数值稳定性时有用；普通看模型不需要。

---

## 5.5.3 `Fwdinv`

### 作用

启用 forward-inverse dynamics consistency 检查。

### 怎么理解

MuJoCo 可以比较 forward dynamics 和 inverse dynamics 的一致性，用于诊断动力学计算误差。

### 什么时候用

- 研究动力学正确性；
- 怀疑模型质量、惯性、约束导致动力学异常；
- 高级调试。

普通跑 G1 不一定需要。

---

## 5.5.4 `InvDiscrete`

### 作用

启用离散 inverse dynamics 相关计算。

### 普通理解

这是更高级的动力学诊断功能，通常用于对比离散时间动力学的一致性。

普通仿真不需要主动开启。

---

## 5.5.5 `MultiCCD`

### 作用

启用多点/多接触 CCD 相关处理。

### 对 G1 的意义

如果你遇到高速穿透问题，可以尝试开启。但通常走路场景不是第一优先项。

---

## 5.5.6 `Sleep`

### 作用

启用 sleeping 机制。

### Sleeping 是什么

当物体长时间静止时，物理引擎可以让它“睡眠”，减少计算。

### 对机器人仿真的意义

对于动态机器人控制，通常不希望核心机器人 body 被错误 sleep。普通机器人仿真中要谨慎使用。

---

# 5.6 Contact Override

截图中 `Contact Override` 包含：

```text
Margin
Sol Imp
Sol Ref
Friction
```

只有当 `Enable Flags -> Override` 开启时，这些参数才会覆盖原模型接触参数。

---

## 5.6.1 `Margin`

截图中：

```text
Margin: 0
```

### 作用

接触检测 margin。

### 怎么理解

margin 可以让两个 geom 在真正接触前就进入接触处理范围。

### 对 G1 的意义

如果 margin 太大，脚还没真正接触地面就产生接触；如果太小，接触可能太突然。

---

## 5.6.2 `Sol Imp`

截图中类似：

```text
Sol Imp: 0.9 0.95 0.001
```

### 作用

solver impedance 参数，控制接触/约束从软到硬的阻抗变化。

### 普通理解

它影响接触“硬度”和过渡方式。

| 设置倾向 | 可能效果 |
|---|---|
| 更硬 | 脚底不容易陷入地面，但可能抖动 |
| 更软 | 接触更柔和，但脚可能有可见压入 |

### 对 G1 的意义

脚底接触质量和 `solimp` 有很大关系，但不要随便改。建议先用默认值。

---

## 5.6.3 `Sol Ref`

截图中类似：

```text
Sol Ref: 0.02 1
```

### 作用

solver reference 参数，控制接触约束的时间常数和阻尼比。

### 普通理解

它决定接触误差被修正得多快、多硬。

| 设置 | 可能结果 |
|---|---|
| 时间常数太小 | 接触非常硬，可能抖动 |
| 时间常数较大 | 接触更软，可能下陷 |
| 阻尼不足 | 可能弹跳 |
| 阻尼过大 | 运动迟钝 |

### 对 G1 的意义

脚底接触稳定性非常依赖 `solref`。

---

## 5.6.4 `Friction`

截图中类似：

```text
Friction: 1 1 0.005 0.0001 0.0001
```

### 作用

接触摩擦参数。

### 常见含义

MuJoCo friction 参数通常包含多个维度，例如：

- sliding friction；
- torsional friction；
- rolling friction。

具体维度和 cone 类型、接触模型有关。

### 对 G1 的意义

脚底摩擦太小：

```text
机器人脚打滑，走不稳
```

脚底摩擦太大：

```text
可能不真实，接触求解变硬，转身困难
```

---

# 5.7 Actuator Group Enable

截图中包含：

```text
Act Group 0
Act Group 1
Act Group 2
Act Group 3
Act Group 4
Act Group 5
```

### 作用

按 actuator group 启用或禁用 actuator。

### group 是什么

MuJoCo 对许多对象都支持 `group` 属性，例如：

```xml
<motor name="left_hip_pitch" joint="left_hip_pitch" group="0" />
```

如果 actuator 被分到不同 group，UI 可以按组控制它们是否启用。

### 对 Unitree G1 的意义

可以用来单独测试某些 actuator 组。

例如：

| 目的 | 操作 |
|---|---|
| 只看下肢控制 | 关闭上肢 actuator group |
| 检查手臂是否影响平衡 | 临时关闭手臂 actuator group |
| 排查某组电机是否导致爆炸 | 分组启停定位 |

### 注意

如果你不知道 G1 XML 中 group 如何分配，不要乱关。否则可能出现机器人突然不受控。

---

# 6. Rendering 栏目

`Rendering` 决定 MuJoCo 画面中显示哪些对象、显示哪些调试元素、启用哪些 OpenGL 效果。

截图中包含：

```text
Camera
Label
Frame
Copy camera

Model Elements
OpenGL Effects
```

---

# 6.1 Camera / Label / Frame

---

## 6.1.1 `Camera`

截图中：

```text
Camera: Free
```

### 作用

选择当前使用的相机。

### 常见相机类型

| 类型 | 含义 |
|---|---|
| `Free` | 自由相机，用户用鼠标控制 |
| 固定 camera name | XML 中定义的 camera |
| Tracking camera | 跟踪某个 body |

### 对 G1 的意义

如果你只想自由观察机器人，使用 `Free`。如果 XML 中定义了跟随机器人相机，可以切换到固定/跟踪相机。

---

## 6.1.2 `Label`

截图中：

```text
Label: None
```

### 作用

控制是否在画面上显示对象标签。

### 常见标签

可能包括：

- body name；
- joint name；
- geom name；
- site name；
- camera name；
- actuator name；
- constraint/contact 信息。

### 对 G1 的意义

如果你想知道某个身体部件名字，例如：

```text
这是 left_ankle_roll 还是 left_ankle_pitch？
```

可以打开 Label。

---

## 6.1.3 `Frame`

截图中：

```text
Frame: None
```

### 作用

控制是否显示坐标系 frame。

### 可显示对象

可能包括：

- body frame；
- geom frame；
- site frame；
- camera frame；
- world frame。

### 对机器人调试的价值

非常重要。

如果你排查：

```text
pitch / roll / yaw 方向是不是搞反了？
IMU 坐标系是不是和代码一致？
foot frame 方向是否正确？
base frame 是 x forward 还是 y forward？
```

就应该打开 Frame。

---

## 6.1.4 `Copy camera`

### 作用

复制当前相机配置。

### 可能复制的内容

通常包括：

- camera type；
- lookat/center；
- distance/extent；
- azimuth；
- elevation；
- field of view。

### 什么时候用

| 场景 | 用法 |
|---|---|
| 找到一个很好的演示视角 | Copy camera 保存参数 |
| 想在代码里复现截图视角 | 复制相机参数 |
| 写 demo/论文图 | 固定相机参数保证图片一致 |

---

# 6.2 Model Elements

截图中 `Model Elements` 包含很多按钮：

```text
Convex Hull     Texture
Joint           Camera
Actuator        Activation
Light           Tendon
Range Finder    Equality
Inertia         Scale Inertia
Perturb Force   Perturb Object
Contact Point   Island
Contact Force   Contact Split
Transparent     Auto Connect
Center of Mass  Select Point
Static Body     Skin
Flex Vert       Flex Edge
Flex Face       Flex Skin
Body Tree       Mesh Tree
SDF Iters
```

这些控制“显示哪些调试元素”。

---

## 6.2.1 `Convex Hull`

### 作用

显示 mesh 的凸包或碰撞近似。

### 对 G1 的意义

视觉 mesh 和碰撞 mesh 可能不是同一个东西。你看到的漂亮外壳不一定参与碰撞。

开启 `Convex Hull` 可以帮助你检查：

```text
脚底碰撞形状是不是正确？
小腿碰撞体是否太大？
手臂是否有异常碰撞体？
```

---

## 6.2.2 `Texture`

### 作用

显示/隐藏纹理。

### 关闭后的效果

模型可能变成纯色材质。

### 用途

调试结构时可以关闭纹理，减少视觉干扰。

---

## 6.2.3 `Joint`

### 作用

显示 joint 可视化标记。

### 对 G1 的意义

非常有用。可以检查：

- 关节位置是否在正确地方；
- 关节轴方向是否正确；
- 左右腿关节是否对称；
- 手臂关节是否和 mesh 对齐。

如果机器人某个关节转动方向反了，打开 `Joint` 和 `Frame` 能更快定位。

---

## 6.2.4 `Camera`

### 作用

显示 XML 中定义的 camera 对象。

### 对 G1 的意义

如果模型里有 head camera、tracking camera、debug camera，可以打开查看它们的位置和方向。

---

## 6.2.5 `Actuator`

### 作用

显示 actuator 相关可视化元素。

### 对 G1 的意义

可以帮助你确认 actuator 和 joint 的映射。

例如：

```text
right_shoulder_pitch motor 是否绑定到了 right_shoulder_pitch joint？
```

---

## 6.2.6 `Activation`

### 作用

显示 actuator activation 状态。

### 背景

某些 actuator 有内部激活状态，例如 muscle、filter actuator 等。

### 对 G1 的意义

如果 G1 使用简单 motor/position actuator，activation 可能不明显；如果使用带 dynamics 的 actuator，则有用。

---

## 6.2.7 `Light`

### 作用

显示场景中的光源对象。

### 用途

主要用于渲染调试，不影响机器人动力学。

---

## 6.2.8 `Tendon`

### 作用

显示 tendon。

### Tendon 是什么

MuJoCo tendon 可以模拟绳索、肌腱、耦合传动等。

### 对 G1 的意义

如果 G1 模型没有 tendon，可以忽略。如果某些关节通过 tendon 耦合，打开它可以查看路径。

---

## 6.2.9 `Range Finder`

### 作用

显示 rangefinder 传感器射线。

### 对 G1 的意义

如果机器人装有距离传感器、深度感知模拟、激光射线等，可以打开查看射线方向。

---

## 6.2.10 `Equality`

### 作用

显示 equality constraints。

### 对 G1 的意义

如果模型中有 weld/connect 等约束，打开后可以查看约束位置。

---

## 6.2.11 `Inertia`

### 作用

显示 body 的惯性盒/惯性椭球。

### 对 G1 非常重要

机器人动力学强烈依赖质量和惯性。

如果惯性设置错误，可能出现：

- 机器人奇怪抖动；
- 关节控制很难稳定；
- RL 训练和仿真不一致；
- 某个 limb 看起来质量分布不合理。

打开 `Inertia` 可以检查每个 body 的质量分布是否大致合理。

---

## 6.2.12 `Scale Inertia`

### 作用

对惯性可视化进行缩放显示。

### 用途

有些 body 的惯性很小，不缩放看不见；有些很大，显示太夸张。这个选项帮助调整显示效果。

---

## 6.2.13 `Perturb Force`

### 作用

显示用户扰动施加的力。

### 背景

MuJoCo UI 支持鼠标对物体施加外力/扰动。

### 对 G1 的意义

你可以给机器人一个外力，测试控制器抗扰动能力。打开 `Perturb Force` 可以看到扰动力方向和大小。

---

## 6.2.14 `Perturb Object`

### 作用

显示当前被扰动/拖拽的对象。

### 用途

当你用鼠标选择并拖动物体时，能看清当前操作对象。

---

## 6.2.15 `Contact Point`

### 作用

显示接触点。

### 对 Unitree G1 极其重要

走路仿真最常看这个。

可以检查：

```text
脚底有没有真的接触地面？
接触点是不是在脚底？
是不是膝盖/小腿/身体也在接触地面？
脚底接触点数量是否异常？
```

如果机器人看起来站在地面上，但 `Contact Point` 没显示，可能 collision 没有生效。

---

## 6.2.16 `Island`

### 作用

显示动力学约束 island。

### 用途

高级调试。用来观察哪些物体被约束/接触连成同一个求解岛。

### 对 G1 的意义

一般 G1 自身是一个 island。如果机器人和地面接触，地面通常是静态环境，约束仍会进入同一求解问题。

---

## 6.2.17 `Contact Force`

### 作用

显示接触力。

### 对 G1 非常重要

如果脚底接触正常，开启后你应该能看到脚底接触力方向。

### 可以排查

| 现象 | 可能问题 |
|---|---|
| 没有接触力 | 没接触 / Contact 被禁用 / collision 不匹配 |
| 接触力特别大 | 穿透严重 / 接触太硬 / 控制力太大 |
| 接触力方向奇怪 | 法线方向或几何接触异常 |
| 左右脚力差异过大 | 姿态或控制器不平衡 |

---

## 6.2.18 `Contact Split`

### 作用

分解显示接触力的不同分量。

### 可能分量

- normal force；
- tangential friction force；
- torsional friction；
- rolling friction。

### 对 G1 的意义

如果你想分析脚底是“支撑力不够”还是“摩擦力不够”，Contact Split 很有用。

---

## 6.2.19 `Transparent`

### 作用

让模型半透明显示。

### 用途

可以看内部结构，例如：

- joint 位置；
- inertia；
- contact 点；
- body frame；
- actuator/tendon。

---

## 6.2.20 `Auto Connect`

### 作用

自动连接可视化元素，显示 body/joint/tree 关系。

### 对 G1 的意义

可以帮助理解机器人运动链：

```text
pelvis -> hip -> thigh -> knee -> shank -> ankle -> foot
```

---

## 6.2.21 `Center of Mass`

### 作用

显示质心。

### 对 G1 极其重要

人形机器人平衡高度依赖质心位置。

可以观察：

```text
整机 COM 是否落在支撑脚范围内？
单脚站立时 COM 是否偏离？
走路时 COM 是否剧烈晃动？
```

---

## 6.2.22 `Select Point`

### 作用

显示当前选中点。

### 用途

当你双击选择对象或点时，可以显示选择位置。

---

## 6.2.23 `Static Body`

### 作用

显示静态 body。

### 对 G1 场景

地面、固定环境、参考物体等可能属于 static body。

---

## 6.2.24 `Skin`

### 作用

显示 skin 对象。

### Skin 是什么

MuJoCo skin 可用于柔性/表皮可视化，不一定参与碰撞。

### 对 G1 的意义

如果 Unitree 模型使用 skin 表示外观，打开/关闭可以影响外观显示。

---

## 6.2.25 `Flex Vert`

### 作用

显示 flex 对象的顶点。

### Flex 是什么

MuJoCo 中 flex 用于柔性体/可变形对象相关表示。

### 对 G1 的意义

普通刚体机器人通常不关注，除非场景中有软体物体。

---

## 6.2.26 `Flex Edge`

### 作用

显示 flex 边。

---

## 6.2.27 `Flex Face`

### 作用

显示 flex 面。

---

## 6.2.28 `Flex Skin`

### 作用

显示 flex skin。

---

## 6.2.29 `Body Tree`

### 作用

显示 body 层级树。

### 对 G1 的意义

非常有助于理解机器人 kinematic tree。

例如：

```text
torso
 ├── left_shoulder
 ├── right_shoulder
 ├── left_hip
 └── right_hip
```

如果你在调试 parent-child 关系，打开它很有用。

---

## 6.2.30 `Mesh Tree`

### 作用

显示 mesh 或几何层级树相关结构。

### 用途

主要用于复杂 mesh/碰撞结构调试。

---

## 6.2.31 `SDF Iters`

### 作用

显示 SDF 迭代/调试信息。

### 用途

只有涉及 SDF 几何或 SDF collision 时才重要。

---

## 6.2.32 `Tree depth`

截图中：

```text
Tree depth: 1
```

### 作用

控制 tree 可视化显示的深度。

### 对 G1 的意义

如果显示 Body Tree，depth 决定显示到第几层。

例如：

| depth | 可能显示 |
|---|---|
| 1 | torso 及一级子 body |
| 2 | 加上 hip/shoulder 下一级 |
| 更大 | 显示完整 limb tree |

---

## 6.2.33 `Flex layer`

截图中：

```text
Flex layer: 0
```

### 作用

选择 flex 对象显示层。

### 对 G1 的意义

普通 G1 刚体模型通常可以忽略。

---

# 6.3 OpenGL Effects

截图中 `OpenGL Effects` 包含：

```text
Shadow      Wireframe
Reflection  Additive
Skybox      Fog
Haze        Depth
Segment     ID Color
Cull Face
```

这些主要影响画面渲染，不直接改变物理。

---

## 6.3.1 `Shadow`

### 作用

开启/关闭阴影。

### 对截图的影响

你图中机器人下方黑色区域就是阴影/视觉效果的一部分。

### 对性能的影响

阴影会增加渲染负担。如果 FPS 低，可以尝试关闭。

---

## 6.3.2 `Wireframe`

### 作用

以线框模式显示模型。

### 对 G1 的意义

线框可以帮助你看清：

- mesh 拓扑；
- 外观 mesh 是否过于复杂；
- collision/visual 是否对齐。

---

## 6.3.3 `Reflection`

### 作用

开启/关闭反射效果。

### 对性能的影响

反射可能增加渲染开销。FPS 低时可以关闭。

---

## 6.3.4 `Additive`

### 作用

控制 additive blending 相关显示效果。

### 用途

主要是可视化效果，不影响物理。

---

## 6.3.5 `Skybox`

### 作用

显示/隐藏天空盒背景。

### 对 G1 的意义

无物理影响，只影响视觉。

---

## 6.3.6 `Fog`

### 作用

开启/关闭雾效。

### 用途

远处物体变淡，增强深度感。

### 性能

可能略微影响渲染。

---

## 6.3.7 `Haze`

### 作用

开启/关闭 haze 效果。

### 用途

类似大气朦胧效果。

---

## 6.3.8 `Depth`

### 作用

显示深度相关渲染效果/深度缓冲可视化。

### 对机器视觉任务的意义

如果你在用 MuJoCo 生成深度图或调试相机视角，Depth 相关选项会很有用。

---

## 6.3.9 `Segment`

### 作用

显示 segmentation 分割渲染。

### 对 AI/视觉任务的意义

如果你需要为机器人视觉生成语义分割、实例分割数据，Segment 非常重要。

---

## 6.3.10 `ID Color`

### 作用

用对象 ID 对不同物体着色。

### 用途

适合调试：

```text
哪个 geom 是哪个对象？
哪些 body 被分成了哪些可渲染单元？
```

---

## 6.3.11 `Cull Face`

### 作用

开启/关闭背面剔除。

### 背面剔除是什么

渲染三角面时，不显示背向相机的一面，可以提高效率。

### 什么时候关掉

如果你发现某些薄面从背面看消失，可以关闭 cull face。

---

# 7. Visualization 栏目

`Visualization` 控制更细致的可视化参数，包括灯光、相机、全局显示比例、颜色等。

截图中可见：

```text
Headlight
Free Camera
Global
Map
Scale
RGBA
```

---

# 7.1 Headlight

截图中包含：

```text
Active Off / On
Ambient
Diffuse
Specular
```

---

## 7.1.1 `Active`

### 作用

开启/关闭 headlight。

### Headlight 是什么

可以理解为跟随相机的灯光。它让你看向哪里，哪里就有基本照明。

### 对 G1 的意义

如果模型太暗，可以打开。对物理没有影响。

---

## 7.1.2 `Ambient`

截图中类似：

```text
Ambient: 0.3 0.3 0.3
```

### 作用

环境光强度。

### 怎么理解

Ambient 越高，整体越亮，但阴影层次会变弱。

---

## 7.1.3 `Diffuse`

截图中类似：

```text
Diffuse: 0.6 0.6 0.6
```

### 作用

漫反射光强度。

### 怎么理解

影响物体表面受光后的明暗。

---

## 7.1.4 `Specular`

截图中类似：

```text
Specular: 0 0 0
```

### 作用

高光反射强度。

### 怎么理解

Specular 越高，金属/光滑表面高光越明显。

---

# 7.2 Free Camera

截图中包含：

```text
Orthographic No / Yes
Field of view
Center
Azimuth
Elevation
Align
```

---

## 7.2.1 `Orthographic`

### 作用

切换正交投影和透视投影。

| 模式 | 特点 |
|---|---|
| Perspective / No | 近大远小，更接近人眼 |
| Orthographic / Yes | 没有近大远小，适合工程观察 |

### 对 G1 的意义

| 用途 | 建议 |
|---|---|
| 演示视频 | Perspective 更自然 |
| 检查关节对齐 | Orthographic 更准确 |
| 截论文图/结构图 | Orthographic 更规整 |

---

## 7.2.2 `Field of view`

截图中：

```text
Field of view: 45
```

### 作用

视野角。

### 怎么理解

| FOV | 效果 |
|---|---|
| 小 | 更像长焦，透视变形小 |
| 大 | 更广角，能看到更多但变形明显 |

### 对 G1 的建议

如果想看整体机器人，45 是比较正常的值。

---

## 7.2.3 `Center`

截图中类似：

```text
Center: 0 0 0.5
```

### 作用

自由相机围绕观察的中心点。

### 对 G1 的意义

如果机器人在画面里太高/太低，可以调 Center。

例如：

```text
Center z 增大：相机看向更高的位置
Center z 减小：相机看向更低的位置
```

---

## 7.2.4 `Azimuth`

截图中：

```text
Azimuth: -130
```

### 作用

相机绕垂直轴旋转的角度。

### 怎么理解

控制从哪个水平方向看机器人。

---

## 7.2.5 `Elevation`

截图中：

```text
Elevation: -20
```

### 作用

相机俯仰角。

### 怎么理解

| Elevation | 视角 |
|---|---|
| 更大 | 更从上往下看 |
| 更小/负值 | 更接近平视或从下往上 |

---

## 7.2.6 `Align`

### 作用

对齐当前相机视角。

与 Simulation 中的 `Align` 类似，但这里更偏向当前 free camera 参数调整。

---

# 7.3 Global

截图中包含：

```text
Extent
Inertia Box / Ellip
BVH active False / True
```

---

## 7.3.1 `Extent`

截图中：

```text
Extent: 2
```

### 作用

场景全局尺度估计，用于相机、可视化比例等。

### 对 G1 的意义

如果模型显示太大/太小，extent 会影响默认相机距离和一些可视化元素比例。

---

## 7.3.2 `Inertia Box / Ellip`

### 作用

选择惯性可视化形状。

| 选项 | 含义 |
|---|---|
| Box | 用盒子显示惯性 |
| Ellip | 用椭球显示惯性 |

### 对 G1 的意义

不同显示方式可以帮助你判断 body 惯性是否合理。

---

## 7.3.3 `BVH active`

### 作用

显示或控制 BVH active 状态。

### BVH 是什么

BVH = Bounding Volume Hierarchy，包围体层次结构，常用于加速碰撞检测和渲染。

### 对 G1 的意义

高级调试碰撞性能时有用。普通使用可以忽略。

---

# 7.4 Map

截图中包含：

```text
Stiffness
Rot stiffness
Force
Torque
Alpha
Fog start
Fog end
Z near
Z far
Haze
Shadow clip
Shadow scale
```

这些是可视化映射参数，把物理量映射成图形长度、宽度、透明度、阴影范围等。

---

## 7.4.1 `Stiffness`

### 作用

控制平移刚度可视化映射。

### 用途

显示 spring/stiffness 相关元素时影响可视化比例。

---

## 7.4.2 `Rot stiffness`

### 作用

控制旋转刚度可视化映射。

---

## 7.4.3 `Force`

### 作用

控制力向量显示比例。

### 对 G1 的意义

如果你打开 `Contact Force` 或 `Perturb Force`，这个参数会影响力箭头长度。

| 问题 | 处理 |
|---|---|
| 力箭头太长挡住画面 | 调小 Force |
| 看不见力箭头 | 调大 Force |

---

## 7.4.4 `Torque`

### 作用

控制力矩可视化比例。

### 对 G1 的意义

如果显示 torque 相关可视化，影响箭头/旋转标记大小。

---

## 7.4.5 `Alpha`

### 作用

控制透明度相关映射。

### 对 G1 的意义

如果开启透明显示，可用它调整透明效果。

---

## 7.4.6 `Fog start` / `Fog end`

### 作用

控制雾效开始和结束距离。

| 参数 | 含义 |
|---|---|
| Fog start | 从多远开始出现雾 |
| Fog end | 多远完全被雾影响 |

---

## 7.4.7 `Z near` / `Z far`

### 作用

相机深度裁剪范围。

| 参数 | 含义 |
|---|---|
| Z near | 最近能看到的距离 |
| Z far | 最远能看到的距离 |

### 常见问题

如果模型一部分突然消失，可能是裁剪平面设置不合适。

---

## 7.4.8 `Haze`

### 作用

控制 haze 强度。

---

## 7.4.9 `Shadow clip`

### 作用

控制阴影裁剪范围。

---

## 7.4.10 `Shadow scale`

### 作用

控制阴影尺度。

---

# 7.5 Scale

截图中包含：

```text
All (meansize)
Force width
Contact width
Contact height
Connect
Com
Camera
Light
Select point
Joint length
Joint width
Actuator length
Actuator width
Frame length
Frame width
Constraint
Slider-crank
```

这些控制各种可视化元素的大小。

---

## 7.5.1 `All (meansize)`

截图中：

```text
All (meansize): 0.1245
```

### 作用

全局平均尺寸基准。

### 怎么理解

MuJoCo 用模型平均大小作为可视化比例基准。这个参数影响很多显示元素的整体尺寸。

---

## 7.5.2 `Force width`

### 作用

控制力箭头的宽度。

### 用途

配合 `Contact Force` / `Perturb Force` 使用。

---

## 7.5.3 `Contact width`

### 作用

控制接触点显示宽度。

---

## 7.5.4 `Contact height`

### 作用

控制接触点显示高度。

---

## 7.5.5 `Connect`

### 作用

控制连接线可视化大小。

### 对 G1 的意义

用于 body tree、auto connect 等显示。

---

## 7.5.6 `Com`

### 作用

控制 center of mass 标记大小。

### 对 G1 的意义

如果 COM 点太小看不见，调大这个。

---

## 7.5.7 `Camera`

### 作用

控制 camera 对象显示大小。

---

## 7.5.8 `Light`

### 作用

控制 light 对象显示大小。

---

## 7.5.9 `Select point`

### 作用

控制选择点标记大小。

---

## 7.5.10 `Joint length`

### 作用

控制 joint 可视化长度。

### 对 G1 的意义

如果打开 `Joint` 后看不清关节轴，可以调大。

---

## 7.5.11 `Joint width`

### 作用

控制 joint 可视化宽度。

---

## 7.5.12 `Actuator length`

### 作用

控制 actuator 可视化长度。

---

## 7.5.13 `Actuator width`

### 作用

控制 actuator 可视化宽度。

---

## 7.5.14 `Frame length`

### 作用

控制坐标系 frame 轴长度。

### 对 G1 的意义

调试 IMU、base frame、foot frame 时很有用。

---

## 7.5.15 `Frame width`

### 作用

控制坐标系 frame 轴宽度。

---

## 7.5.16 `Constraint`

### 作用

控制 constraint 可视化大小。

---

## 7.5.17 `Slider-crank`

### 作用

控制 slider-crank 机构可视化大小。

### 对 G1 的意义

普通 G1 模型如果没有 slider-crank 机构，可以忽略。

---

# 7.6 RGBA

截图中 `RGBA` 包含大量颜色参数，例如：

```text
fog
haze
force
inertia
joint
actuator
actnegative
actpositive
com
camera
light
selectpoint
connect
contactpoint
contactforce
contactfriction
contacttorque
contactgap
rangefinder
constraint
slidercrank
crankbroken
frustum
bv
bvactive
```

RGBA 的含义是：

```text
R = red
G = green
B = blue
A = alpha / transparency
```

每一行通常是四个数，例如：

```text
0.9 0.9 0.2 1
```

表示：

```text
红色 0.9
绿色 0.9
蓝色 0.2
透明度 1
```

---

## 7.6.1 `fog`

### 作用

雾效颜色。

---

## 7.6.2 `haze`

### 作用

haze 效果颜色。

---

## 7.6.3 `force`

### 作用

外力/扰动力显示颜色。

### 对 G1 的意义

如果你用鼠标给机器人施加外力，force 颜色决定箭头颜色。

---

## 7.6.4 `inertia`

### 作用

惯性可视化颜色。

### 对 G1 的意义

打开 `Inertia` 后，如果看不清惯性盒/椭球，可以改颜色或透明度。

---

## 7.6.5 `joint`

### 作用

joint 可视化颜色。

---

## 7.6.6 `actuator`

### 作用

actuator 可视化颜色。

---

## 7.6.7 `actnegative` / `actpositive`

### 作用

actuator 激活正负方向的颜色。

### 对 G1 的意义

如果显示 actuator activation，可以用颜色区分正向/负向输出。

---

## 7.6.8 `com`

### 作用

质心显示颜色。

### 对 G1 的意义

建议把 COM 颜色设得醒目，方便观察平衡。

---

## 7.6.9 `camera`

### 作用

camera 对象显示颜色。

---

## 7.6.10 `light`

### 作用

light 对象显示颜色。

---

## 7.6.11 `selectpoint`

### 作用

选择点颜色。

---

## 7.6.12 `connect`

### 作用

连接线颜色。

---

## 7.6.13 `contactpoint`

### 作用

接触点颜色。

### 对 G1 的意义

建议设得醒目，这样脚底接触点更容易看清。

---

## 7.6.14 `contactforce`

### 作用

接触力颜色。

---

## 7.6.15 `contactfriction`

### 作用

接触摩擦力颜色。

### 对 G1 的意义

用来区分法向支撑力和切向摩擦力。

---

## 7.6.16 `contacttorque`

### 作用

接触力矩颜色。

---

## 7.6.17 `contactgap`

### 作用

接触 gap 可视化颜色。

### 对 G1 的意义

可以帮助观察几何体之间的接触间隙。

---

## 7.6.18 `rangefinder`

### 作用

rangefinder 射线颜色。

---

## 7.6.19 `constraint`

### 作用

constraint 可视化颜色。

---

## 7.6.20 `slidercrank`

### 作用

slider-crank 机构显示颜色。

---

## 7.6.21 `crankbroken`

### 作用

slider-crank broken 状态颜色。

---

## 7.6.22 `frustum`

### 作用

相机视锥体颜色。

### 对视觉任务意义

如果你调试机器人相机视野，可以打开 camera/frustum 显示。

---

## 7.6.23 `bv` / `bvactive`

### 作用

bounding volume 和 active bounding volume 的颜色。

### 对性能调试意义

用于观察碰撞检测/包围体层级。

---

# 8. Group enable 栏目

截图中 `Group enable` 包含：

```text
Geom groups
Site groups
Joint groups
Tendon groups
Actuator groups
Flex groups
Skin groups
```

每类下面都有：

```text
Group 0
Group 1
Group 2
Group 3
Group 4
Group 5
```

---

## 8.1 group 是什么？

MuJoCo 中许多对象都有 `group` 属性。

例如：

```xml
<geom name="left_foot_collision" group="1" />
<joint name="left_knee" group="0" />
<site name="imu" group="2" />
<motor name="left_hip_pitch" group="0" />
```

UI 可以按 group 显示/隐藏对象。

---

## 8.2 `Geom groups`

### 作用

控制不同 geom group 是否显示。

### Geom 是什么

geom 是 MuJoCo 里的几何体，可用于：

- 视觉显示；
- 碰撞检测；
- 质量/inertia 推导；
- 接触计算。

### 对 G1 的意义

很多机器人模型会把 geom 分成：

| 可能 group | 可能用途 |
|---|---|
| 0 | visual geom |
| 1 | collision geom |
| 2 | debug geom |
| 3 | simplified collision |
| 4/5 | 其他辅助对象 |

如果你想检查脚底 collision，可能需要打开某些 geom group。

---

## 8.3 `Site groups`

### 作用

控制 site group 显示。

### Site 是什么

site 是 MuJoCo 中常用的参考点/参考坐标系，可用于：

- IMU 位置；
- foot contact marker；
- end-effector marker；
- camera/rangefinder attachment；
- sensor reference frame；
- 控制目标点。

### 对 G1 的意义

如果 G1 XML 中有：

```text
imu site
left_foot site
right_foot site
hand site
head camera site
```

打开 Site groups 可以看到这些点。

---

## 8.4 `Joint groups`

### 作用

控制 joint group 显示。

### 对 G1 的意义

可以按组显示不同关节。

例如：

| group | 可能对应 |
|---|---|
| 0 | 下肢 joint |
| 1 | 上肢 joint |
| 2 | 腰部 joint |
| 3 | debug joint |

具体要看 XML 如何定义。

---

## 8.5 `Tendon groups`

### 作用

控制 tendon group 显示。

### 对 G1 的意义

如果模型没有 tendon，可忽略。

---

## 8.6 `Actuator groups`

### 作用

控制 actuator group 显示。

### 注意和 `Actuator Group Enable` 的区别

| 位置 | 作用 |
|---|---|
| Physics -> Actuator Group Enable | 影响 actuator 是否参与控制/驱动 |
| Group enable -> Actuator groups | 主要影响 actuator 是否显示 |

一个是物理/控制层面，一个是可视化层面。

---

## 8.7 `Flex groups`

### 作用

控制 flex group 显示。

### 对 G1 的意义

普通刚体 G1 模型通常不关注。

---

## 8.8 `Skin groups`

### 作用

控制 skin group 显示。

### 对 G1 的意义

如果 G1 使用 skin 或外观 mesh，可以用它隐藏/显示外观层。

---

# 9. 你在 Unitree G1 调试中最应该关注哪些按钮？

如果你不是研究 MuJoCo UI 本身，而是要调试 Unitree G1，我建议按优先级看下面这些。

---

## 9.1 第一优先级：确认机器人是否真的接触地面

打开：

```text
Option -> Info
Option -> Profiler
Rendering -> Contact Point
Rendering -> Contact Force
Rendering -> Contact Split
```

重点看：

```text
Info 里的 con 数量
Profiler -> Dimensions 里的 contact / constraint
脚底是否显示 contact point
脚底是否显示 contact force
```

如果机器人脚踩地面但 contact 是 0，优先检查：

```text
Contact disable flag 是否误开
脚底 geom 是否有 collision
地面 geom 是否存在
contype / conaffinity 是否匹配
机器人 root 是否被固定在空中
初始高度是否太高
```

---

## 9.2 第二优先级：确认控制器是否真的发力

打开：

```text
Watch -> Field = ctrl
Watch -> Field = actuator_force
Option -> Sensor
Rendering -> Actuator
```

重点看：

```text
ctrl 是否全是 0
actuator_force 是否有值
sensor torque 是否长期饱和
Actuation disable flag 是否误开
Clampctrl 是否导致 action 被裁剪
```

---

## 9.3 第三优先级：确认关节方向和 frame 是否正确

打开：

```text
Rendering -> Joint
Rendering -> Frame
Rendering -> Transparent
Rendering -> Body Tree
Rendering -> Center of Mass
```

重点看：

```text
hip pitch / roll / yaw 轴方向是否正确
left/right 是否反了
base frame 是否和代码一致
foot frame 是否和 observation 一致
COM 是否在合理位置
```

---

## 9.4 第四优先级：确认求解器是否稳定

打开：

```text
Option -> Profiler
Physics -> Algorithmic Parameters
```

重点看：

```text
Solver iteration 是否经常打满
Convergence 是否下降
CPU time 中 collision/solve 是否暴涨
contact/constraint 是否异常增多
```

如果不稳定，优先尝试：

```text
减小 timestep
降低 PD gain
检查 contact 参数
检查 foot collision geometry
检查 joint limit
检查 action scale
```

---

## 9.5 第五优先级：改善显示性能

如果你像截图一样：

```text
CPU 很低
FPS 很低
```

可以尝试：

```text
关闭 Shadow
关闭 Reflection
关闭 Sensor / Profiler
关闭 VSync 试试
减少透明/线框/接触力显示
避免远程桌面低效渲染
检查 WSLg/OpenGL/GPU 驱动
```

---

# 10. 常见误区

---

## 10.1 误区：`Contact` 按钮亮了就是开启接触

在 `Physics -> Disable Flags` 里不是这样。

那里是：

```text
Contact 亮了 = 禁用 Contact
```

所以如果你误点了 Contact，机器人会穿地。

---

## 10.2 误区：FPS 低就是物理仿真慢

不一定。

要看：

```text
Info -> CPU
Profiler -> CPU time
```

如果 CPU time 很低但 FPS 低，说明瓶颈可能在渲染/显示层。

---

## 10.3 误区：Sensor data 横轴是时间

不是。

Sensor data 横轴通常是：

```text
sensordata 数组 index
```

不是时间。

---

## 10.4 误区：`Group enable` 会改变物理

大多数 `Group enable` 是显示控制，不一定改变物理。

但 `Physics -> Actuator Group Enable` 会影响 actuator 是否启用，这个会影响控制。

---

## 10.5 误区：视觉 mesh 等于碰撞 mesh

不一定。

G1 看起来脚踩地，但 collision geom 可能没有接触。要打开：

```text
Contact Point
Contact Force
Convex Hull
Transparent
```

一起检查。

---

# 11. 推荐的 Unitree G1 调试组合

---

## 11.1 检查脚底接触

打开：

```text
Info
Profiler
Contact Point
Contact Force
Contact Split
Transparent
Convex Hull
```

看：

```text
con 是否 > 0
contact 是否出现在脚底
contact force 是否朝上
脚底 collision 是否和视觉脚底对齐
```

---

## 11.2 检查关节顺序和控制输出

打开：

```text
Joint
Frame
Actuator
Sensor
Watch
```

看：

```text
joint 轴方向
actuator 绑定关系
ctrl 数值
actuator_force 数值
sensordata 中 torque / qpos / qvel 是否正常
```

---

## 11.3 检查机器人平衡

打开：

```text
Center of Mass
Contact Point
Contact Force
Frame
```

看：

```text
COM 是否落在支撑区域内
左右脚接触力是否合理
base frame 是否倾斜严重
```

---

## 11.4 检查仿真性能

打开：

```text
Profiler
Info
```

看：

```text
CPU time total
collision
prepare
solve
iteration
contact/constraint 数量
```

---

# 12. 最核心总结

这套左侧侧边栏可以分成三类能力：

## 12.1 控制仿真

```text
File
Simulation
Physics
```

用于保存模型、重置模型、调整 timestep、solver、gravity、contact 等。

---

## 12.2 查看内部状态

```text
Info
Profiler
Sensor
Watch
```

用于查看当前仿真时间、CPU、solver、sensor、qpos/qvel/ctrl 等。

---

## 12.3 改变可视化方式

```text
Rendering
Visualization
Group enable
```

用于显示 joint、frame、contact point、contact force、COM、inertia、body tree、wireframe、shadow、segmentation 等。

---

# 13. 对你当前截图的直接判断

根据你截图中的左侧和右侧信息，当前状态大致是：

```text
1. 模型 g1_29dof scene 已经成功加载。
2. 仿真使用 Euler integrator、Pyramidal cone、Auto Jacobian、Newton solver。
3. timestep 是 0.005，也就是 200Hz 物理步长。
4. solver 最大迭代次数是 100，但当前实际只用 1 iteration。
5. Info 中显示 0 con，说明当前几乎没有有效接触约束。
6. CPU time 很低，物理仿真不慢。
7. FPS 约 11~13，显示慢更像渲染/远程显示问题。
8. Sensor data 正常显示，说明模型中 sensor 有输出。
9. 左侧 Physics/Rendering/Visualization 已展开，说明你正在查看底层调试参数。
```

如果你下一步是让 G1 走路，最应该检查：

```text
Contact Point 是否在脚底出现
Contact Force 是否合理
Disable Flags 里 Contact / Actuation / Sensor / Gravity 是否误禁用
Watch 里的 ctrl 是否真的有控制输入
Sensor data 里的 torque 是否长期饱和
Profiler 里的 contact / constraint / iteration 是否异常
```

---

# 14. 参考资料

- MuJoCo Documentation — Code samples / simulate：说明 `simulate` 是完整交互式仿真器，内置 help、simulation statistics、profiler、sensor data plots。
- MuJoCo Documentation — Modeling / Sensors：说明传感器输出写入 `mjData.sensordata`，sensor 不直接影响仿真。
- MuJoCo Documentation — Visualization：说明 MuJoCo visualizer 可以显示 contact points、forces、inertia boxes、constraint violations、frames、labels 等调试元素。
- MuJoCo Documentation — Simulation：说明 forward dynamics 会计算 active contacts、constraints、constraint forces、sensor data 等中间结果。
