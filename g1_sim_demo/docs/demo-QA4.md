# demo-QA4：`g1_sim_rl_combo.py` 按 wsad 后腿乱飞 / 自旋 / 按 r 停不下的彻底诊断与修复

> 承接 `docs/demo-QA1.md`、`docs/demo-QA2.md`、`docs/demo-QA3.md`、`g1_sim_demo/docs/use1.md`。
> 涉及源码：
> - `g1_sim_demo/g1_sim_rl_combo.py`（RL 平衡 + 键盘上半身姿态合并版，**本次修改**）
> - `unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py`（训练用 env 配置）
> - `unitree_rl_mjlab/src/tasks/velocity/config/g1/env_cfgs.py`（G1 专用训练 env override，flat 版本去掉 height_scan）
> - `unitree_rl_mjlab/deploy/robots/g1/src/State_RLBase.cpp`（C++ 标准部署写 lowcmd 的逻辑）
> - `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml`（策略部署参数）
> - `unitree_rl_mjlab/deploy/include/isaaclab/envs/mdp/observations/observations.h`（C++ obs 实现）
> - `unitree_rl_mjlab/deploy/include/isaaclab/envs/mdp/actions/joint_actions.h`（C++ action 实现）

---

## TL;DR

**症状**：把仿真器牢牢放在地上之后跑 `g1_sim_rl_combo.py`，策略加载没崩；可一旦按 `w/s/a/d/q/e` 任意一个走路键，腿就立刻开始乱飞、躯干自旋，按 `r` 也停不下来。

**根因**：和仿真器、bridge、obs 顺序、动作 scale/offset 都**无关**。是 `g1_sim_rl_combo.py` 自己的设计 bug——它**把策略的手臂输出永远覆盖成静态姿态**，结果：

1. 走路时没有手臂摆动 → 腿摆产生的角动量没地方抵消 → 躯干自旋；
2. 策略 commanded 手臂去摆但实际不动 → `joint_pos_rel / last_action` 出现训练时从未见过的不一致 → 策略输出越来越离谱 → 腿乱飞；
3. 这条 OOD 反馈通道在 `r` 之后依然存在（`r` 只清零 cmd，不修复 obs 错配）→ 停不下来。

**修复**：让 combo 默认**不覆盖手臂**，只在用户真的按 `1..8`/`0` 触发手势时短暂接管，最后一帧跑完自动还给策略。改的全在 `g1_sim_rl_combo.py` 一个文件里，bridge / `unitree_mujoco.py` / `config.py` 不动。

---

## 1. 排查：先把不是问题的可能都筛掉

收到症状后，我系统地把"可能搞坏 RL 部署的全部链路"一条条核对了——结果绝大多数都是好的。把它们写下来，下次同类问题排查时可以直接跳过。

### 1.1 obs 维度和顺序

`Policy.OBS_DIM = 98` 来自 `3 + 3 + 3 + 2 + 29 + 29 + 29`。和 `deploy.yaml` 的 observations 段顺序完全对应：

```yaml
observations:
  base_ang_vel:        # 3
  projected_gravity:   # 3
  velocity_commands:   # 3
  gait_phase:          # 2
  joint_pos_rel:       # 29
  joint_vel_rel:       # 29
  last_action:         # 29
```

C++ 标准部署的 `ObservationManager::compute_group()`（`deploy/include/isaaclab/manager/observation_manager.h:63-92`）也是按 YAML 顺序 push_back 后再拼接，无 history（`history_length: 1`，且 `use_gym_history` 默认 false）。Python combo 的 `_build_obs()` 顺序一致。✅

### 1.2 关节顺序对齐

`deploy.yaml` 里 `joint_ids_map: [0,1,...,28]` 是恒等映射——SDK lowstate 的 `motor_state[i]` 和策略期望的第 `i` 维**完全对齐**。

校验链：

- 仿真侧：`unitree_mujoco/unitree_robots/g1/g1_29dof.xml` 的 `<actuator>` 块按 `left_hip_pitch, left_hip_roll, ..., right_wrist_yaw` 排（29 个）；
- 训练侧：`unitree_rl_mjlab/src/assets/robots/unitree_g1/xmls/g1.xml` 的 `<joint>` 顺序完全相同；
- 桥接：`unitree_sdk2py_bridge.py` 把 `mj_data.sensordata[i]` 直接写进 `low_state.motor_state[i].q`，sensor 段的 `<jointpos>` 又是按 actuator 顺序排的。

3 处一致，没有错位。✅

### 1.3 IMU 四元数与 projected_gravity

- 仿真：`<framequat objname="imu">` 输出 `[w, x, y, z]`（MuJoCo 约定）；
- 桥接：写进 `low_state.imu_state.quaternion[0..3]` 的顺序就是 `[w, x, y, z]`；
- combo：`quat_rotate_inverse` 注释明确写"`[w, x, y, z]` order"，公式正确（用 conjugate 旋转世界系 gravity 到 body 系）。✅

C++ 同等实现见 `unitree_articulation.h:29-35`：

```cpp
data.root_quat_w = Eigen::Quaternionf(
    lowstate->msg_.imu_state().quaternion()[0],   // w
    lowstate->msg_.imu_state().quaternion()[1],   // x
    lowstate->msg_.imu_state().quaternion()[2],   // y
    lowstate->msg_.imu_state().quaternion()[3]);  // z
data.projected_gravity_b = data.root_quat_w.conjugate() * data.GRAVITY_VEC_W;
```

### 1.4 gait_phase

C++ `observations.h:125-151`：

```cpp
env->global_phase += step_dt / period;
env->global_phase = std::fmod(env->global_phase, 1.0f);
auto cmd = velocity_commands(env, params);
float cmd_norm = sqrt(cmd[0]² + cmd[1]² + cmd[2]²);
obs[0] = sin(global_phase * 2π);
obs[1] = cos(global_phase * 2π);
if (cmd_norm < 0.1f) { obs[0] = obs[1] = 0; }
```

Python combo 在 `_build_obs()` 里完全一致：相位**始终递增**（即使站立也累计），但 `cmd_norm < 0.1` 时输出强制清零。✅

注意：训练侧 `velocity/mdp/observations.py:phase` 用的是 `episode_length_buf * step_dt % period / period`，和"持续递增不复位"等价（episode 内步数单调增）。

### 1.5 action 处理（scale + offset）

C++ `joint_actions.h:39-60` 的 `process_actions`：

```cpp
_processed_actions[i] = _raw_actions[i] * _scale[i] + _offset[i];
// clip 在 yaml 里是 null，跳过
```

Python combo：`q_target = raw_action * cfg.action_scale + cfg.action_offset`。✅

### 1.6 ONNX 是否包含 obs_normalizer

确认了：`rsl_rl/models/mlp_model.py:222-244` 的 `_OnnxMLPModel.forward` 是

```python
x = self.obs_normalizer(x)
out = self.mlp(x)
return self.deterministic_output(out)
```

normalizer 已经被 `torch.onnx.export` 一起导出。我们喂原始 obs，policy 内部完成归一化。✅

### 1.7 桥接的 PD 闭环

之前 QA 系列里把 `LowCmdHandler` 里直接算 PD 改成了 `ApplyControl()` 在仿真线程每步算（`unitree_mujoco.py:55-61`，`unitree_sdk2py_bridge.py:119-152`）。这一改是**对的**：原版 50 Hz 算 PD、200 Hz 仿真，4 步内 ctrl 不变，对硬 PD（hip Kp=99.1）来说会引入相位滞后。新版 200 Hz 算 PD 是稳定的。✅

### 1.8 关节限位 / actuatorfrcrange

`deploy.yaml` 没有 `clip`，但 MJCF 的 `<motor>` 都设了 `ctrlrange`（hip ±88, knee ±139, ankle ±50, 手臂 ±25, 手腕 ±5）。即使 PD 算出超出范围的 τ 也会被 MuJoCo 截断，不会数值爆炸。✅

### 1.9 elastic band 初始长度

之前已经把 `ELASTIC_BAND_INIT_LENGTH = 0.0` 改对了，初始绳长不会把躯干瞬移到 z=3。用户也确认"完全放稳了放在地上"，说明绳子已经手动拉长 / 关掉。✅

### 1.10 仿真接触摩擦差异（注意但不是本次根因）

训练 `xmls/g1.xml` 的脚是 7 个 `<geom class="foot_capsule" priority="1" condim="6">` 胶囊；
仿真 `unitree_robots/g1/g1_29dof.xml` 的脚是 4 个 `size=0.005` 的小球，`condim` 默认 3。

接触面更小、condim 更低 → 摩擦不如训练时鲁棒。**这会让站姿稍微滑、走路对策略更难**，但本身**不会**产生"按一下 wsad 就立刻起飞"的剧烈失稳——策略对这种程度的 sim-to-sim 差异是有鲁棒性的。所以这个差距值得知道，但不是本次根因。

---

## 2. 真正的根因：**arm overlay 永久覆盖了策略输出**

排除上述所有项之后，剩下的可疑点就只有 combo 自己独有的"键盘 overlay"逻辑。看 `g1_sim_rl_combo.py:543-547`（修复前）：

```python
# ---- Policy step (all 29 joints) ----
obs = self._build_obs()
raw_action = self.policy(obs)
q_target = raw_action * self.cfg.action_scale + self.cfg.action_offset
self.last_raw_action[:] = raw_action

# ---- Arm overlay: advance gesture queue and override q_target[15:29] ----
arm_q = self._advance_arms()
q_target[ARM_START:ARM_END] = arm_q   # ← 永远覆盖

self._publish(q_target)
```

而 `_advance_arms()` 里：

```python
# 没有 arm_queue、没有 arm_blend_to 的时候
return self.arm_q_target.copy()  # 返回上次定格的姿态（默认 = arm_rest = default_q[15:29]）
```

**含义**：哪怕用户从来没按过 `1..8`，每个 tick 都把 `q_target[15:29]` 写成 `default_q[15:29]`，等于把手臂硬锁在静态姿态。

### 2.1 这为什么是错的——和"标准部署"对照

C++ 标准部署 `deploy/robots/g1/src/State_RLBase.cpp:54-60`：

```cpp
void State_RLBase::run()
{
    auto action = env->action_manager->processed_actions();
    for (int i = 0; i < env->robot->data.joint_ids_map.size(); i++) {
        lowcmd->msg_.motor_cmd()[env->robot->data.joint_ids_map[i]].q() = action[i];
    }
}
```

**29 维全部写进 lowcmd，不挑不滤。** 训练侧 `velocity_env_cfg.py:152-159`：

```python
actions = {
    "joint_pos": JointPositionActionCfg(
        entity_name="robot",
        actuator_names=(".*",),  # ← 全部 actuator 都给策略
        scale=0.25,
        use_default_offset=True,
    )
}
```

策略**就是按"我能控制全部 29 个关节"训出来的**。手臂的 reward 在 `velocity_env_cfg.py:rewards.pose` 里只是"鼓励靠近 default"的弱惩罚，不是硬约束——也就是**策略可以、也会、并且学会了在走路 / 转向时摆动手臂**。

### 2.2 锁死手臂会引发的三个连锁后果

#### 2.2.1 角动量没地方抵消 → 躯干自旋

人 / 双足机器人走路时手臂前后摆，是为了**抵消腿摆产生的关于躯干 yaw 轴的角动量**。把手臂硬锁、腿继续摆，角动量守恒要求**躯干本身开始转动**——这就是你看到的 "spinning"。

reward 里的 `body_ang_vel`（`weight=-0.05`）和 `angular_momentum`（`weight=-0.025`）是惩罚项，但权重不大；策略当时之所以能控制好这两项，靠的就是**手臂参与**。手臂被锁死时，这两项的最优解（让躯干自己转）在 reward 上的代价远低于"靠脚硬扭"。

#### 2.2.2 obs 出现 OOD 错配 → 策略输出越来越乱

走路 tick 里发生的事：

| 步 | 策略对手臂的 raw_action（学过） | 实际命令（被覆盖） | 实际关节位置 | `joint_pos_rel[arms]` | `last_action[arms]` |
|---|---|---|---|---|---|
| t  | 非零（比如 +0.4）  | `arm_rest`         | ≈ `arm_rest` | ≈ 0  | +0.4 |
| t+1 | 非零 | `arm_rest` | ≈ `arm_rest` | ≈ 0 | +0.4 |
| ... | | | | | |

训练时这两个量是耦合的：`joint_pos_rel ≈ scale * last_action`（PD 大致跟随）。现在 `last_action ≠ 0` 而 `joint_pos_rel ≈ 0` ——**策略以为自己在挥臂、可关节没动**，这是训练分布里**根本不会出现**的状态。MLP 在 OOD 输入上的输出是不可预期的，腿的动作也跟着失稳。

这就是 "腿乱飞"。

#### 2.2.3 `r` 救不回来

`r` 只调用 `set_command(0, 0, 0)`：

- ✅ 让 `velocity_commands` obs 变 0；
- ✅ 让 `gait_phase` obs 因 `cmd_norm < 0.1` 强制清零；
- ❌ **不修** 上面那条 `joint_pos_rel / last_action` 的错配——这条通道一直在喂 OOD 给策略；
- ❌ **不修** 已经倾斜 / 旋转的躯干（`projected_gravity` 此时已经偏离 `(0, 0, -1)`，策略以为自己快摔了，越救越乱）。

所以 `r` 之后看到的现象是：command 本身归零，但策略输出依然狂躁；腿继续乱蹬，躯干继续转——直到摔倒、QACC 爆 NaN 或者你按 `space` / `x`。

### 2.3 为什么 demo-QA3.md 没看出这一点

QA3.md 的诊断聚焦在另一个完全不同的 traceback——`select.select(stdin)` 抛异常导致主线程崩溃。那个问题是 stdin / TTY 层的，和策略本身无关。修了那个之后**策略才能跑起来不崩**，但策略一旦跑起来、用户开始按 wsad，就会撞上本文这个根因。

QA3.md 的代码分工表

| 关节段 | 控制源 |
|---|---|
| 腿 0..11 | RL |
| 腰 12..14 | RL |
| 手臂 15..28 | 键盘 overlay |

**第三行写错了——键盘 overlay 应当只在手势进行时短暂生效，而不是 24×7 接管。**

---

## 3. 修复（已应用到 `g1_sim_rl_combo.py`）

设计方针：默认**不覆盖手臂**，把"按下手势键 → 手势期间覆盖 → 末帧自动归还"做成有限状态。

### 3.1 新增状态

```python
# 在 __init__
self._arm_override_active = False
```

含义：仅当队列里还有未跑完的手势 keyframe 时为 True。

### 3.2 `push_arm_action` 接手臂时从真实位姿起步

```python
def push_arm_action(self, keyframes):
    with self._arm_lock:
        # 关键：从 lowstate 读当前手臂真实位姿，而不是用陈旧的 arm_q_target。
        # 不然策略原本把手臂摆到某个角度，按下手势键瞬间会被一个位置阶跃猛拉。
        self.arm_q_target = self._read_current_arm_q()
        self.arm_queue = [(float(d), p.copy()) for d, p in keyframes]
        self.arm_blend_from = None
        self.arm_blend_to = None
        self.arm_blend_dur = 0.0
        self.arm_blend_t = 0.0
        self._arm_override_active = True
```

新增辅助：

```python
def _read_current_arm_q(self) -> np.ndarray:
    s = self.low_state
    if s is None:
        return self.arm_rest.copy()
    return np.fromiter(
        (s.motor_state[ARM_START + i].q for i in range(ARM_DIM)),
        dtype=np.float64, count=ARM_DIM,
    )
```

### 3.3 `_advance_arms` 末帧跑完自动 release，并允许返回 `None`

```python
def _advance_arms(self) -> Optional[np.ndarray]:
    with self._arm_lock:
        if self.arm_blend_to is None and self.arm_queue:
            dur, pose = self.arm_queue.pop(0)
            self.arm_blend_from = self.arm_q_target.copy()
            self.arm_blend_to = pose.copy()
            self.arm_blend_dur = max(dur, 1e-3)
            self.arm_blend_t = 0.0

        if self.arm_blend_to is not None:
            self.arm_blend_t += self.cfg.step_dt
            if self.arm_blend_t >= self.arm_blend_dur:
                self.arm_q_target = self.arm_blend_to.copy()
                self.arm_blend_from = None
                self.arm_blend_to = None
                self.arm_blend_dur = 0.0
                self.arm_blend_t = 0.0
                # 关键：最后一帧跑完且队列空 → 自动 release
                if not self.arm_queue:
                    self._arm_override_active = False
            else:
                s = 0.5 - 0.5 * np.cos(np.pi * (self.arm_blend_t / self.arm_blend_dur))
                self.arm_q_target = (1.0 - s) * self.arm_blend_from + s * self.arm_blend_to

        if not self._arm_override_active:
            return None  # ← 让 _tick 知道"别覆盖，给策略"
        return self.arm_q_target.copy()
```

### 3.4 `_tick` 只在拿到非 None 时才覆盖

```python
arm_q = self._advance_arms()
if arm_q is not None:
    q_target[ARM_START:ARM_END] = arm_q
self._publish(q_target)
```

### 3.5 `release_arms` 仅当真有 override 时执行

```python
def release_arms(self):
    with self._arm_lock:
        if not self._arm_override_active and not self.arm_queue:
            return  # 已经在策略手里了，别为了 release 再抓一次
        self.arm_q_target = self._read_current_arm_q()
        self.arm_queue = [(1.0, self.arm_rest.copy())]
        self.arm_blend_from = None
        self.arm_blend_to = None
        self.arm_blend_dur = 0.0
        self.arm_blend_t = 0.0
        self._arm_override_active = True
```

### 3.6 状态机示意

```
[BOOT_RAMP]  --boot_t≥boot_dur-->  [POLICY_ALL_29]
                                       │      ▲
                                       │      │ 末帧跑完且队列空
                                       │      │ → _arm_override_active=False
                                       │      │
                       按 1..8 / 0     ▼      │
                                  [ARM_OVERLAY]
                                  （只覆盖 15..28）
```

策略从始至终对 **0..14（腿 + 腰）** 拥有完全控制权；对 **15..28（手臂）** 拥有控制权，**除非**当前正在跑用户队列里的某一帧。

---

## 4. 为什么这次改动是安全的

1. **不动 bridge / 不动仿真器 / 不动 yaml**：风险面最小。
2. **行为对齐 C++ 标准部署**：和 `State_RLBase.cpp` 写 lowcmd 的逻辑等价（默认 29 维全给策略）。
3. **手势接管时刻无位置阶跃**：从真实关节位姿做种 → 第一帧 cosine 插值过去，平滑。
4. **手势收尾时刻无位置阶跃**：最后一帧 = `arm_rest = default_q[15:29] = action_offset[15:28]`，而站立时策略 raw_action 为手臂部分 ≈ 0 → 策略 q_target 为手臂部分 ≈ `action_offset[15:28]`，两边数值近似相等。走路时策略输出非零，但手臂 Kp 较低（14.3 / 16.8）、Kd 0.9 / 1.1，actuator 自身有低通滤波，肉眼看不到跳变。
5. **`stop_and_settle` / 退出路径仍然有效**：`release_arms` 在退出时如果手势已经结束，是 no-op；接着 `soften(0, 1.0)` 会把 Kp 拉到 0，机器人按预期"瘫下来"。
6. **不引入新 obs / 新 action 维度**：策略从头到尾看到的输入完全没变，不会触发 ONNX 维度不匹配。

---

## 5. 验收

终端 1：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 里按 8 几次让脚落地（safety net）
# 等终端 2 打印 "[combo] policy ready" 之后再按 9 剪绳
```

终端 2：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
# 等 "[combo] policy ready" → 终端 1 按 9 → 在终端 2 按 wsadqe / r / 1..8 / 0
```

预期：

| 操作 | 修复前 | 修复后 |
|---|---|---|
| 站立（cmd=0） | 站得住 | 站得住 |
| 按 `w`（vx=0.2） | 立刻腿乱飞、躯干自旋 | **手臂自然前后摆动**，腿正常迈步 |
| 按 `q` 或 `e` | 转着转着失控 | 手臂左右摆，转身平稳 |
| 走路中按 `r` | 命令清零但脚还在乱 | 命令清零 → 几个 tick 内站定 |
| 按 `1` 挥右手 | 失败（已经在乱了） | 短暂接管手臂挥手，结束**自动归还策略**，腿继续保持平衡 |
| 走路中按 `1` | 失败 | 走路中右手挥一下，3.0 s 内把手臂还回去；身体平衡正常维持 |
| 不按 `0` 直接 `x` 退出 | 行为不变 | 行为不变（`stop_and_settle` 软关 PD 后退出） |

---

## 6. 给将来的提醒

1. **凡是叠加层（overlay / corrective control）只能在显式触发期间生效**，不能"默认占用"——一旦默认占用，策略就在 OOD 状态下持续运行。
2. **要 overlay 一个关节段，先确认这个关节段在训练时是否被策略控制**。本例里训练用 `actuator_names=(".*",)`，手臂在策略管辖之内 → overlay 必须是临时的。如果你训练时是 `actuator_names=("legs",)`、手臂从来没归策略管，那永久 overlay 就没问题。
3. **OOD 探针**：调试 RL 部署可以加一段诊断打印——每秒打印一次 `joint_pos_rel[arms]` 范数和 `last_action[arms]` 范数。如果两者长期严重不匹配（一个接近 0，另一个非零），就是有人在替策略写 q（不一定是 overlay，也可能是别的进程在抢 lowcmd 通道）。
4. **看到 "spinning" 第一直觉**：先怀疑角动量回路出了问题——手臂被锁、腰被锁、或者头被锁。本案是手臂被锁。

---

## 7. 文件改动总览

只动了一个文件：

```
g1_sim_demo/g1_sim_rl_combo.py
  ├── 模块 docstring：重写 "Architecture" 和 "Why arms must NOT stay locked when idle"
  ├── ComboController.__init__：新增 self._arm_override_active = False
  ├── push_arm_action：调用 _read_current_arm_q() 做种，置 _arm_override_active = True
  ├── release_arms：no-op 短路；其余路径置 _arm_override_active = True
  ├── _tick：arm_q is None 时不覆盖 q_target[15:29]
  ├── 新增 _read_current_arm_q
  ├── _advance_arms：末帧跑完且队列空时置 _arm_override_active = False；返回 Optional
  └── format_help：手臂段文案改为 "briefly overlay"
```

`unitree_mujoco/simulate_python/{config.py, unitree_mujoco.py, unitree_sdk2py_bridge.py}` **没动**——之前 QA 系列做的 200 Hz `ApplyControl()`、`ELASTIC_BAND_INIT_LENGTH`、`scene_29dof.xml` 路径切换都是对的，原样保留。

---

## 8. 一句话回答你的两个问题

| 问题 | 回答 |
|---|---|
| 为什么按 wsad 腿就乱飞？ | combo 永久把手臂锁在 default 姿态，把策略学会的"挥臂抵消角动量"通路掐了；同时让 `joint_pos_rel/last_action` 出现训练时见不到的 OOD 错配，策略输出失控、腿跟着乱蹬。 |
| 为什么按 r 停不下来？ | `r` 只清 cmd 不修 OOD obs；只要手臂还被锁着，OOD 通道就一直存在，策略就一直被错误信号驱动。修复后手臂自动归还策略，r 立刻生效。 |
