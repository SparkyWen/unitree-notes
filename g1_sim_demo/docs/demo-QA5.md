# demo-QA5：`g1_sim_rl_combo.py` —— 走路正常但触发上半身手势就崩溃；以及"走路打滑"的彻底诊断与修复

> 承接 `docs/demo-QA1.md`、`docs/demo-QA2.md`、`docs/demo-QA3.md`、`docs/demo-QA4.md`。
> QA4 修了"按 wsad 立刻乱飞"的根因（手臂被永久 override），让 combo 默认把手臂还给策略。
> 本文修复 QA4 之后的下一个根因：**手臂还给策略之后，按 1..8 触发任何手势也会让机器人乱飞、起飞、崩溃**；以及顺带解释为什么走路时偶尔脚下打滑。
>
> 涉及源码：
> - `g1_sim_demo/g1_sim_rl_combo.py`（**本次修改**）
> - `unitree_mujoco/unitree_robots/g1/scene_29dof.xml`（**本次修改**：抗滑）
> - `unitree_rl_mjlab/deploy/robots/g1/config/policy/velocity/v0/params/deploy.yaml`（参数读起源；不动）
> - `unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py`（训练侧 env，仅作分布对照）
> - `unitree_rl_mjlab/src/assets/robots/unitree_g1/xmls/g1.xml`（训练侧 MJCF；本节解释打滑会用到）

---

## TL;DR

| 问题 | 根因 | 修复 |
|---|---|---|
| 走路 OK，但**按 1..8 任何手势** → 上半身刚开始动机器人就发疯起飞乱飞 | 手势的目标姿态远超策略训练分布；同时 `last_action` 还停在策略原本要的值，和 `joint_pos_rel` 完全失配 → MLP 输入 OOD → **腿、腰、所有 joint 同时输出垃圾** | 手势改成 "默认姿态 + delta · action_scale" 表达；强制把 14 个手臂关节裁进 `default ± 2·action_scale` 包络；override 时把 `last_raw_action[15:29]` 改写成与实际发布姿态一致的等效 raw action；额外做 per-tick 速率限幅 |
| 走路时脚下偶尔打滑 / 拖一下 | 仿真 MJCF 脚是 4 个 size=0.005m 小球，contact `condim=3`（无切向摩擦力矩），地面摩擦默认 1.0；训练侧 MJCF 是 7 段胶囊 `condim=6 priority=1` | `scene_29dof.xml` 的地板加 `friction="1.5 0.05 0.005" condim="6" priority="1"` |

只动两个文件：

- `g1_sim_demo/g1_sim_rl_combo.py`
- `unitree_mujoco/unitree_robots/g1/scene_29dof.xml`

---

## 1. 症状回顾

QA4 修复之后：

- 启动正常，进入 `[combo] policy ready`，机器人站得稳；
- 按 `w/s/a/d/q/e` 走动一切正常，手臂会自然摆；
- 按 `r` 也能立刻停；
- **按 `1..8` 任意一个手势键，刚开始动手臂，机器人就开始全身乱抽 → 躯干失控 → 离地 / 翻身 / NaN**。

也就是说，QA4 把"默认 lock 手臂"这条 OOD 通道关上了，但它一旦被有意打开（用户按手势键，主动 override 手臂），就把同一条 OOD 通道**重新打开了**——而且打得比 QA4 那次还猛，因为手势的目标比 `default` 偏离更远。

---

## 2. 根因（一）：手势姿态严重超出策略训练分布

### 2.1 训练侧 actuator + reward 的事实

来自 `unitree_rl_mjlab/src/tasks/velocity/velocity_env_cfg.py`：

```python
actions = {
    "joint_pos": JointPositionActionCfg(
        entity_name="robot",
        actuator_names=(".*",),     # ← 全部 29 维都给策略
        scale=0.25,
        use_default_offset=True,
    )
}
rewards.pose = PoseDeviationReward(weight=-some_weak_value)  # 让手臂别飞太远
```

而 `deploy.yaml` 实际部署用的 per-joint scale 是：

```yaml
scale: [0.55, 0.35, 0.55, 0.35, 0.44, 0.44,    # 左腿
        0.55, 0.35, 0.55, 0.35, 0.44, 0.44,    # 右腿
        0.55, 0.44, 0.44,                       # 腰
        0.44, 0.44, 0.44, 0.44, 0.44, 0.07, 0.07,   # 左臂 ← shoulder/elbow/wrist_roll = 0.44, wrist_pitch/yaw = 0.07
        0.44, 0.44, 0.44, 0.44, 0.44, 0.07, 0.07]   # 右臂
```

含义：策略输出 `raw_action ∈ [-1, 1]`，乘以 scale + offset 后得到 PD 目标 `q_target = scale*raw_action + offset`。`offset = default_joint_pos`。所以策略**主动控制**下一步的 q_target 必然在 `default ± scale` 的小盒子里：

| 关节 | offset (rad) | scale (rad) | 训练时 q_target 大致范围 |
|---|---|---|---|
| LeftShoulderPitch (15)  | 0.35 | 0.44 | [-0.09, 0.79] |
| LeftShoulderRoll (16)   | 0.18 | 0.44 | [-0.26, 0.62] |
| LeftElbow (18)          | 0.87 | 0.44 | [0.43, 1.31] |
| LeftWristPitch (20)     | 0.00 | **0.07** | [-0.07, 0.07] |
| LeftWristYaw (21)       | 0.00 | **0.07** | [-0.07, 0.07] |

PD 跟随是闭环+滤波，所以训练里**实际**测到的 `joint_pos_rel = q - default` 也大致集中在 `[-scale, +scale]`，再叠加 pose-deviation reward 的拉力，更进一步集中在 `±scale` 以内。

### 2.2 旧版 combo 的手势姿态写多远？

修改前的 `g1_sim_rl_combo.py` 手势是绝对角度：

| 手势 | 关节 | 目标值 (rad) | 偏离 default | scale | k = 偏离 / scale |
|---|---|---|---|---|---|
| hands_up      | LeftShoulderPitch | -1.6 | -1.95 | 0.44 | **4.43** |
| hands_up      | RightShoulderPitch | -1.6 | -1.95 | 0.44 | **4.43** |
| t_pose        | LeftShoulderRoll  | +1.5 | +1.32 | 0.44 | **3.00** |
| t_pose        | RightShoulderRoll | -1.5 | -1.32 | 0.44 | **3.00** |
| wave_right    | RightShoulderRoll | -1.2 | -1.02 | 0.44 | **2.31** |
| salute        | RightWristPitch   | -0.3 | -0.30 | **0.07** | **4.29** |
| punch_*       | shoulder/elbow    | ±1.0 | ~1.0 | 0.44 | **2.27** |

**所有 8 个手势都把至少一个关节推到 k ≥ 2.3**，最猛的（hands_up）把肩 pitch 推到 k ≈ 4.4，是训练分布的 4 倍多。**salute 因为 wrist_pitch scale 只有 0.07**，看起来才偏 0.3 rad 已经是 k ≈ 4.3。

### 2.3 OOD 输入会怎样毁掉策略？

策略是单个 MLP，吃 98 维 obs（拼接：`base_ang_vel(3) + projected_gravity(3) + cmd(3) + gait(2) + joint_pos_rel(29) + joint_vel_rel(29) + last_action(29)`），输出 29 维 `raw_action`。

MLP 不是 modular 的——你把**任何一个**输入维度推到训练时从未见过的范围，激活在第一层就被推到训练时从未到过的方向；后续每一层都是非线性变换；最后输出 29 维**所有维度同时变垃圾**，包括腿和腰。

这就是为什么"明明只 override 了手臂"，**腿也开始乱蹬、躯干也开始翻**。

实测能感知到的现象顺序：

1. t≈0：触发手势，控制器开始把手臂往 hands_up 拉；
2. t≈ 50 ms（2~3 个 tick）：肩 pitch 已经推到 -0.5 rad 附近（k≈2），策略输出开始飘；
3. t≈ 100~200 ms：肩 pitch 拉到 -1 rad（k≈3.4）以上，策略对腿的输出已经完全失控；
4. t≈ 300 ms：腿乱踢、踩地变成踩空、躯干被力矩抛起 → "起飞"。

---

## 3. 根因（二）：`last_action` 与 `joint_pos_rel` 失配（即使姿态没那么夸张也炸）

### 3.1 失配是怎么产生的

策略的 `last_action` obs 应该满足"上一步策略给了什么命令"。训练时的不变量是：

```
joint_pos_rel(t)  ≈  scale * last_action(t-1)   （PD 跟随闭环 + 一拍延迟）
```

也就是说，"我说要往哪儿动"和"实际动到哪儿"一致——这是 PD 控制下的固有结构。

但旧版 combo 的代码是：

```python
raw_action = policy(obs)
q_target = raw_action * scale + offset
self.last_raw_action[:] = raw_action          # ← 存的是策略的输出

# override
arm_q = self._advance_arms()
if arm_q is not None:
    q_target[15:29] = arm_q                   # ← publish 的是 override
self._publish(q_target)
```

下一拍 obs 里：

- `joint_pos_rel[15:29]` = 实际关节位置（被 override 拉过去的，比如 -1.95 rad）
- `last_action[15:29]`   = 策略原本的 raw_action（比如 +0.2，被 weak pose-deviation reward 拽向 0）

策略看到："**我上一拍说要往 +0.2 方向走，现在关节却在 -1.95**" —— 这个 (last_action, joint_pos_rel) 组合训练时**根本不可能出现**。

### 3.2 哪怕姿态被 clamp 进了包络，失配本身也会出问题

假设我们把手势 clamp 到 k ≤ 2，shoulder pitch 最多拉到 -0.53 rad。`joint_pos_rel = -0.88`，看起来勉强还在分布边缘。

但如果 `last_action[shoulder_pitch]` 还是策略原本的 +0.05（站立时手臂保持微调），策略看到的：

```
joint_pos_rel = -0.88   →  "我现在远离默认"
last_action   = +0.05   →  "我说我没怎么动"
```

这两个**矛盾**——训练分布里如果 `joint_pos_rel ≈ -0.88` 必然伴随 `last_action ≈ -0.88/scale ≈ -2.0`。MLP 内部学会的"如果 joint_pos_rel 大但 last_action 小，意味着外力把它拽过去 / 这是踩到东西 / 该启动恢复力矩"——而我们这里实际上是用户的手势在拽，不是外力，policy 启动的恢复力矩反而会破坏走路的稳态。

**结论：仅仅 clamp 不够，还必须把 `last_action[15:29]` 改写成与实际发布姿态一致的等效 raw_action**，即：

```python
last_raw_action[15:29] = (q_target[15:29] - offset[15:29]) / scale[15:29]
```

这样 (joint_pos_rel, last_action) 满足训练时的不变量 `joint_pos_rel ≈ scale*last_action`，策略就当作"我上一拍就说要走到这儿，确实走到了，正常"。

### 3.3 为什么 QA4 没踩到这个

QA4 之前的 bug 是手臂**永久** lock 在 default。default 对策略来说是 q_target 的中心点，对应 `raw_action ≈ 0`。所以即使没改 `last_action`，那时的 `joint_pos_rel ≈ 0` 和 `last_action ≈ 0` 也"勉强一致"——不是分布里最常见的状态，但还在边缘。问题不在那里，问题在"手臂没参与角动量抵消导致躯干自旋 → projected_gravity 偏 → 全身都 OOD"。

QA4 把"手臂默认归策略"修好之后：
- 站立 / 直走时，策略主动把手臂保持在 default 附近，没事；
- **但一旦用户按手势，手臂被推走，QA4 没处理 last_action 失配**。

所以本文 QA5 修的是 QA4 修复后剩下的、**只有手势激活时才暴露**的那条 OOD 通路。

---

## 4. 修复方案

代码改动全在 `g1_sim_rl_combo.py`。设计目标：

1. 让任何手势姿态**结构性地**落在策略可接受的包络内；
2. 让 override 期间的 `last_action` 与发布的 `q_target` 保持训练分布一致性；
3. 让手势的过渡速度也不超过训练时关节速度的量级。

### 4.1 把手势写成 "delta · scale" 而不是绝对角度

新版每个手势函数返回的不再是 14 维**绝对角度**，而是 14 维 **delta（每个分量约束在 [-2, +2]）**。最终姿态：

```python
final_pose = arm_rest + delta * arm_scale
```

例如：

```python
def hands_up_delta() -> np.ndarray:
    p = _arm_zero_delta()
    p[_slot(J.LeftShoulderPitch)]  = -2.0   # default 0.35 + (-2*0.44) = -0.53 rad
    p[_slot(J.RightShoulderPitch)] = -2.0
    p[_slot(J.LeftElbow)]          = -1.0   # 比默认 0.87 直一些
    p[_slot(J.RightElbow)]         = -1.0
    return p
```

由于 wrist_pitch/yaw 的 scale 只有 0.07，delta=±2 对应只 ±0.14 rad，**自动避开了 wrist 的小包络陷阱**。这是最重要的几何一致性收益。

实际包络验收（见仓库 `g1_sim_demo/g1_sim_rl_combo.py` 末尾的 build_arm_actions）：

```
1 wave right arm           max|k|=2.00
2 wave left arm            max|k|=2.00
3 hands up (cheer)         max|k|=2.00
4 T-pose                   max|k|=2.00
5 salute                   max|k|=2.00
6 clap (twice)             max|k|=1.50
7 boxer guard              max|k|=1.50
8 punch combo (jab L+R)    max|k|=2.00
```

**所有 8 个手势都满足 max|k| ≤ 2**，相比旧版的 max|k| ≈ 4.43 是质的改善。

### 4.2 入队即裁、tick 再裁——双层 envelope clamp

类常量：

```python
class ComboController:
    ARM_GESTURE_K = 2.0
    ARM_GESTURE_RATE_K_PER_SEC = 4.0
```

入队时（`push_arm_action`）：

```python
self.arm_q_target = self._clamp_arm_to_safe_envelope(self._read_current_arm_q())
self.arm_queue = [
    (float(d), self._clamp_arm_to_safe_envelope(p.copy()))
    for d, p in keyframes
]
```

每个 tick 应用 override 前再裁一次（防御未来误用）：

```python
arm_q = self._advance_arms()
if arm_q is not None:
    arm_q = self._clamp_arm_to_safe_envelope(arm_q)
    arm_q = self._rate_limit_arm_step(arm_q)
    q_target[ARM_START:ARM_END] = arm_q
    ...
```

裁的实现：

```python
def _clamp_arm_to_safe_envelope(self, arm_q):
    lo = self.arm_offset - self.ARM_GESTURE_K * self.arm_scale
    hi = self.arm_offset + self.ARM_GESTURE_K * self.arm_scale
    return np.clip(arm_q, lo, hi)
```

### 4.3 关键：override 期间合成等效 `last_raw_action`

```python
arm_raw = (arm_q - self.arm_offset) / self.arm_scale
arm_raw = np.clip(arm_raw, -self.ARM_GESTURE_K, self.ARM_GESTURE_K)
self.last_raw_action[ARM_START:ARM_END] = arm_raw
```

这一行是本次修复的**核心**。它让下一拍 obs 里的 `last_action[15:29]` 和实际 `joint_pos_rel[15:29]` 满足训练时的不变量 `joint_pos_rel ≈ scale*last_action`，策略不再 confuse"我说没动但实际却动了"。

### 4.4 速率限幅

```python
def _rate_limit_arm_step(self, arm_q):
    prev = getattr(self, "_last_arm_q_published", None)
    if prev is None:
        return arm_q
    max_step = self.ARM_GESTURE_RATE_K_PER_SEC * self.arm_scale * self.cfg.step_dt
    delta = arm_q - prev
    delta = np.clip(delta, -max_step, max_step)
    return prev + delta
```

Cosine ease-in-out 已经把 keyframe 内的速度做了软化，但是"keyframe duration 太短" 仍然能产生 `joint_vel` 尖峰。这里规定**任何一拍**，arm 的位置变化不会超过 `4 * scale * step_dt`，对应每秒最多 4 个 scale 的位移。换算 50 Hz step_dt=0.02：max_step = `4 * 0.44 * 0.02 = 0.0352 rad/tick`，对应肩 pitch 最大 1.76 rad/s。手臂训练分布里偶尔能见到这个量级的速度（走路转身时），所以 cap 在这里是 in-distribution 的。

### 4.5 Action 表的 duration 全部加长

新版 `build_arm_actions`：

```python
ArmAction("3", "hands up (cheer)",
          [(1.5, hands_u), hold(hands_u, 0.8), (1.5, arm_rest)]),
ArmAction("8", "punch combo",
          [(0.8, grd), (0.35, pr), (0.30, grd), (0.35, pl), (0.30, grd), (1.2, arm_rest)]),
```

最快的 punch 子段从 0.25 s 改为 0.30~0.35 s；wave 从 1.2 s 改为 1.5 s。这和速率限幅是互补的——duration 改长降低了速率限幅触发的频率，让运动更平滑。

### 4.6 状态机示意（更新）

```
[BOOT_RAMP]  --boot_t≥boot_dur-->  [POLICY_ALL_29]
                                       │      ▲
                                       │      │ 末帧跑完且队列空 →
                                       │      │   _arm_override_active = False
                                       │      │
                       按 1..8 / 0     ▼      │
                                  [ARM_OVERLAY]
                                     │
                                     ├─ envelope clamp
                                     ├─ rate limit
                                     ├─ q_target[15:29] := arm_q
                                     └─ last_raw_action[15:29] := (arm_q-offset)/scale
                                                                  ←—————— ★ 本次新增
```

---

## 5. 为什么这次修复是结构性而非凑参数

| 修复手段 | 是参数调优还是结构修复？ |
|---|---|
| envelope clamp K=2.0 | 结构：把 OOD 切到分布边缘以内；K 来自训练时实际 raw_action 量级，可解释 |
| delta · scale 表达 | 结构：天然解决 wrist 小包络问题，写错系数也飞不出去 |
| 合成 last_action | 结构：恢复训练时的 obs 不变量；不依赖具体姿态 |
| 速率限幅 K=4 / s | 结构：把 joint_vel 尖峰 cap 在训练分布内 |
| duration 加长 | 参数；和速率限幅互补，提高鲁棒性而非必要 |
| K=2.0 vs 1.5 vs 3.0 | 唯一一个**参数化** dial。K=2 是经验上"还看得清的姿势 / 不出策略包络"的折中 |

如果以后训练换了一个 scale 更大、reward 更弱的 policy，**包络自动变宽**——因为我们用的是 `K * action_scale`，而不是写死 ±0.5 rad 这种**绝对**量。

---

## 6. 顺带：走路打滑的根因（**根因（三）**）

QA4.md §1.10 提了一句"摩擦差异，不是当时根因"。本文我们正面给个完整解释——它**不是**手势崩溃的根因，但**是**用户感觉"走路时偶尔打滑"的真正原因。

### 6.1 仿真 MJCF vs 训练 MJCF 的脚

`unitree_mujoco/unitree_robots/g1/g1_29dof.xml`（仿真侧 / 部署侧）的脚：

```xml
<body name="left_ankle_roll_link" ...>
  <geom size="0.005" pos="-0.05 0.025 -0.03" rgba="0.2 0.2 0.2 1" />
  <geom size="0.005" pos="-0.05 -0.025 -0.03" rgba="0.2 0.2 0.2 1" />
  <geom size="0.005" pos="0.12 0.03 -0.03" rgba="0.2 0.2 0.2 1" />
  <geom size="0.005" pos="0.12 -0.03 -0.03" rgba="0.2 0.2 0.2 1" />
</body>
```

4 个 5 mm 小球，没设 `friction`、没设 `condim`、没设 `priority`。MuJoCo 默认：

- `friction = "1 0.005 0.0001"`（sliding=1.0, torsional=0.005, rolling=0.0001）
- `condim = 3`（normal + 2 切向 friction，**没有 torsional**）
- `priority = 0`（contact 友坐标用 friction 平均值）

`unitree_rl_mjlab/src/assets/robots/unitree_g1/xmls/g1.xml`（训练侧）的脚：

```xml
<default class="foot_capsule">
  <geom type="capsule" priority="1" condim="6" group="3" size="0.01"/>
</default>
...
<geom name="left_foot1_collision" class="foot_capsule" fromto="0.1 -0.026 -0.025 0.05 -0.027 -0.025"/>
... 7 段胶囊 ...
```

7 段 condim=6 priority=1 的胶囊，加上训练用的 friction randomization——接触面更大、torsional 摩擦显式存在、priority=1 让 foot 的 friction 设置在 contact 里说了算。

### 6.2 condim 的差是关键

`condim=3` 的 contact 物理上**没有切向力矩**——脚踩在地上，只能受到 normal force 和两个切向 friction force，**不能受切向力矩**。这意味着脚一旦着地，可以围绕"沿 normal 的轴"自由旋转（脚跟着地脚尖朝外的"内八字打滑"现象）。

`condim=6` 加上 normal axis torsional friction 系数 0.005（默认）就足以阻止那种"脚不动只是地面咬不住"的旋转。MJCF 默认 condim 给的是 3，普通 box-on-floor 接触行不通。

### 6.3 接触面积小 + small spheres

5 mm 球的接触是**点接触**，归一化后接触压强很大；MuJoCo 的 soft contact + frictionloss 模型在小球极端的几何下，friction force 上限只受 sliding coefficient 控制，但是没有 torsional 通道，所以即使 sliding=2.0，也救不了内八字打滑。

加上四个球**只在脚的 4 个角**，脚摆动时 normal force 会瞬间集中到一个球上——单点接触，更没有切向力矩。

### 6.4 修复：地板加 `priority` + `condim=6` + 高一点的 friction

只动 scene 一个文件，不动 robot mesh：

```xml
<geom name="floor" size="0 0 0.05" type="plane" material="groundplane"
      friction="1.5 0.05 0.005" condim="6" priority="1"/>
```

要点：

- `priority="1"`：contact 摩擦完全用 floor 的设置（脚那边 priority 默认 0）；
- `condim="6"`：contact 启用全部 6 自由度的摩擦（含 torsional + rolling），**关键**就在它；
- `friction="1.5 0.05 0.005"`：sliding 1.5（训练随机化的中上水平）、torsional 0.05（默认的 10 倍）、rolling 0.005（默认的 50 倍）。

为什么不直接改脚？因为 `g1_29dof.xml` 是 Unitree 上游 mesh 文件，本仓库当 reference repo 看（CLAUDE.md 里说明了"don't edit them as part of normal feature work"）。改 floor 是**最小侵入**的做法，对所有 G1 demo（keyboard / interactive / RL walk / RL combo）都受益。

### 6.5 修复后的预期

打滑还是会少量存在（接触模型差异不可能完全弥合），但是：

- **内八字打滑**显著减少（torsional friction 救了）；
- 高速 q 转向（按 q/e 几下后 wz=±0.9）下不再有"脚滑出去几厘米"的现象；
- 站立时 cmd=0，脚的微抖更小。

如果还要更进一步的鲁棒性，可以单独做一个 `scene_29dof_grippy.xml` 把 `friction="2 0.1 0.01"`，但 1.5 已经是训练域随机的中上端，再高就 sim-to-real 反过来不一致了。

---

## 7. 验收

终端 1：

```bash
conda activate unitree

export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw

glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"

cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

终端 2：

```bash
conda activate unitree

export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw

cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
```

预期：

| 操作 | 修复前（QA4 之后） | 修复后（QA5） |
|---|---|---|
| 站立 cmd=0 | 站得住 | 站得住 |
| 按 wsadqe 走 | 正常 | 正常 |
| 按 r 停 | 正常 | 正常 |
| 站立按 1（挥右手） | 立刻全身乱抽 → 起飞 | **手臂挥一挥归位**，身子稳如老狗 |
| 站立按 3（hands up） | 起飞 | 双手前举到 ~hip pitch -0.5，归位 |
| 站立按 4（T-pose） | 起飞 | T 形展开（roll ±1.06 rad），归位 |
| 站立按 5（salute） | 起飞（wrist 越界） | 标准敬礼，wrist 微调 ±0.14，归位 |
| 站立按 8（punch combo） | 起飞 | 拳击防守 → 右拳 → 左拳 → 防守 → 归位 |
| **走路时按 1** | 起飞 | 边走边挥手；归位之后腿继续走，不丢节奏 |
| **走路时按 4 T-pose** | 起飞 | 边走边展 T；展开 1 s 内手臂归位 |
| **q + 8 联动**（边转边挥拳） | 起飞 | 转身 + 拳击；动作叠加无失稳 |
| 走路打滑感 | 有时脚跟着地一滑 | 明显减轻（floor friction 提升 + condim=6） |

---

## 8. 留给将来的 4 条经验

1. **如果你 override 一个被策略控制的 actuator 段，必须做两件事：① 把 override 值裁到训练分布；② 把 `last_action` 改写成与发布值一致的等效 raw_action**——只做其中一件都还是 OOD。
2. **永远不要写绝对角度的 hard-coded 姿态，除非你能保证 `(target - default) / scale` 落在 [-2, +2]**。在 RL 部署里 scale 经常 per-joint 不一样（这里 wrist 比 shoulder 小 6 倍），写绝对值很容易踩到小 scale 关节的雷。
3. **加 envelope clamp 的成本极低（一行 np.clip）**，应该是 RL 部署 overlay 类代码的默认 boilerplate。
4. **MJCF 的 condim=3 是大多数 G1 / H1 / Go2 上游 release 的默认**——上游不改，但是**仿真 demo 一定要在 scene 文件里通过 `priority=1` 的 floor 把 condim 拉到 6**。否则任何足式机器人 demo 都会有"明明 friction=1.0 怎么还打滑"的迷之问题。

---

## 9. 文件改动总览

### 9.1 `g1_sim_demo/g1_sim_rl_combo.py`

```
模块 docstring:
  - 重写 "Why arms must NOT stay locked when idle" 段为
    "Why arm gestures must stay inside the policy-tolerant envelope"
  - 列出两个 safety net (clamp, last_action synthesis)

新增 / 改写函数:
  - _arm_zero_delta             (旧 _arm_zero 改名)
  - {wave_right,wave_left,hands_up,t_pose,salute,clap,guard,
     punch_right,punch_left}_delta   (返回 unit-scale delta)
  - materialize(delta, arm_rest, arm_scale)   返回绝对姿态
  - build_arm_actions(arm_rest, arm_scale)   多了 arm_scale 参数

新增 ComboController 类成员:
  - ARM_GESTURE_K = 2.0
  - ARM_GESTURE_RATE_K_PER_SEC = 4.0
  - self.arm_offset, self.arm_scale          (cache 切片)
  - self._last_arm_q_published

新增 ComboController 方法:
  - _clamp_arm_to_safe_envelope(arm_q)
  - _rate_limit_arm_step(arm_q)

修改 ComboController._tick:
  - override 时除了写 q_target[15:29]，还
    1) clamp 一遍；
    2) rate-limit；
    3) 改写 self.last_raw_action[15:29] = (arm_q - offset)/scale；
  - 末尾记录 self._last_arm_q_published

修改 ComboController.push_arm_action:
  - 入队前对每个 keyframe pose 做 clamp
  - 起步 arm_q_target 也 clamp（防御策略本来摆得很大）

修改 ComboController.release_arms:
  - 起步 arm_q_target clamp 后再排空 → arm_rest
  - 持续 1.0s → 1.5s 让退场更平滑

修改 main():
  - build_arm_actions(ctl.arm_rest, ctl.arm_scale)
```

### 9.2 `unitree_mujoco/unitree_robots/g1/scene_29dof.xml`

```
+ floor geom 加 friction="1.5 0.05 0.005" condim="6" priority="1"
+ 旁边写注释解释为什么
```

不改任何其他文件——`unitree_mujoco.py` / `unitree_sdk2py_bridge.py` / `config.py` / `deploy.yaml` / `policy.onnx` 都保持原样。

---

## 10. 一句话回答你两个问题

| 问题 | 回答 |
|---|---|
| 为什么按 1..8 任何上半身手势机器人就乱飞？ | 旧手势的目标姿态偏离 default 远超 `2·action_scale`（最严重的 hands_up 偏 4.4× scale，salute wrist 偏 4.3× 一个 0.07 的极小 scale），同时 override 期间 `last_action` 没改写——`joint_pos_rel` 和 `last_action` 失配，两个因素叠加把策略的 98 维输入推到训练分布外，MLP 输出的 29 维**全部**变垃圾，腿和腰跟着炸。修复：把姿态写成 `default + delta·scale` 形式（结构性把 \|delta\|≤2 当成定义）+ 强制 envelope clamp + 改写 `last_action[15:29] = (arm_q - offset)/scale` + 速率限幅。 |
| 为什么走路时偶尔打滑？ | `g1_29dof.xml` 的脚是 4 个 size=0.005 的小球 + condim 默认 3，**没有切向（torsional）摩擦**，脚一着地就可以绕 normal 轴自由旋转——内八字打滑。训练侧用的是 7 段 capsule + condim=6 + priority=1 不存在这个问题。修复：在 scene 文件给 floor 加 `condim=6 priority=1 friction="1.5 0.05 0.005"`，把 contact 拉到完整六自由度摩擦，问题大幅减轻。 |
