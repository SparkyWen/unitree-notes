# demo-QA7：`g1_real_rl_combo.py` —— 真机"躺地测试模式"，在机器人无法站立时验证 DDS / 电机指令是否到位

> 承接 `docs/demo-QA1.md`～`docs/demo-QA5.md`。
> QA5 修好了"按手势就崩"和"走路打滑"；本文加的是 **真机部署前的最后一道安全检查**：
> 当机器人因为线缆/吊索/调试线等原因**只能躺平**、暂时无法站立时，怎么用同一个脚本安全地确认：
>
> 1. `rt/lowstate ↔ rt/lowcmd` DDS 双向通了；
> 2. lowcmd 真的到达电机控制板，对应关节确实有响应；
>
> **而不要让脚本试图把躺着的机器人拉起来。**
>
> 涉及源码（只动一个文件）：
>
> - `g1_real_demo/g1_real_rl_combo.py`（**本次修改**）
>   - 新增 `lying` CLI 模式（躺地测试）
>   - 顺手修一处 `POLICY_DIR` 解析路径

---

## TL;DR

| 问题 | 根因 | 修复 |
|---|---|---|
| 真机线短、机器人只能躺，但又想跑这个脚本验证通讯/电机响应 | 现有 `g1_real_rl_combo.py` 启动后会 (1) 5 s 内把测得姿态 → `default_q`（站立姿态）做 boot ramp，(2) 之后跑 RL policy 控制全身。躺地的机器人 `joint_pos_rel` / `projected_gravity` / 腿姿全部 OOD，policy 输出垃圾；boot ramp 又会用全力 Kp 把腿往站立位置拉，跟地板硬怼 → 电机过流 / 损伤风险 | 加一个 `lying` 模式：**完全跳过 boot ramp，完全不跑 policy**，把首帧测到的姿态当 baseline，每个 tick 用 `kp_scale=0.2` 把它发回去当心跳；用键盘 `1..7` 触发**单关节小幅手臂抖动**（±0.10..0.20 rad）来验证电机能收到指令 |
| 脚本里 `POLICY_DIR` 解析到 `~/unitree-notes/...`，但实际仓库克隆在 `~/unitree/unitree-notes/...`，启动时直接 `FileNotFoundError: deploy.yaml` | 上一个 commit (`dc2f458 update relative path`) 把 `unitree/unitree-notes` 改成 `unitree-notes`，脱钩了 `Path.home()` 与实际仓库根 | 用脚本自身位置（`Path(__file__).resolve().parent.parent`）解析 `POLICY_DIR`，仓库放哪都能跑 |

只动一个文件：

- `g1_real_demo/g1_real_rl_combo.py`

---

## 1. 使用场景

真机调试时常见的一类情形：

- 机器人通过外接电源/调试线连到主机，**线缆比较短**，没办法直接让它在工位边缘站起来；
- 又想趁这个时间窗口验证：**`unitree_sdk2py` + DDS + 网卡 + 电机控制板** 这条链路有没有问题，
  尤其是网卡刚选错过、`mode_machine` 没 ack 过、IP/掩码刚改过，等等情形。

可以观察到的硬件状态（来自 `ip a`）：

```
3: eno3: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 ...
    inet 192.168.123.222/24 brd 192.168.123.255 scope global noprefixroute eno3
```

`eno3` 在 `192.168.123.0/24` 子网里——这就是 G1 出厂的 DDS 子网，机器人本体一般在 `192.168.123.161`。这条链路就是后面要测的目标。

**目标不是站立、不是走路，而是"打个心跳，看 1~2 个手臂关节会不会动 0.15 rad"。**

---

## 2. 为什么不能直接 `python g1_real_rl_combo.py eno3`

主控流程（修改前）见 `ComboController.start()` + `_tick()`：

```
start():
  等首个 rt/lowstate；
  boot_q_from = 测得 29-D 姿态；
  policy_active = False；
  kp_scale = boot_kp_floor (0.3)；
  开始 50 Hz 的 _tick；
  print "Ramping to default pose over 5.0 s ..."

_tick():
  (1) boot 阶段（前 5 s）：
        s = cosine_easeinout(boot_t / 5.0)
        q_des = (1-s)*boot_q_from + s*default_q
        kp_scale = 0.3 + 0.7*s
        发布 q_des ；
  (2) boot 完成后：
        policy_active = True；kp_scale = 1.0；
        以后每 tick：建 98-D obs → 跑 policy → q_target；发布。
```

把这套流程套到一台**躺平**的 G1 上：

### 2.1 boot ramp 把腿往站立姿势硬拉，地板挡着

`default_q` 是一组站立姿态（髋 pitch ≈ -0.1 rad、膝 ≈ 0.3 rad、踝 pitch ≈ -0.2 rad，等等）。
机器人躺平时实测的 `boot_q_from`（髋几乎全展、膝可能也展开、躯干侧躺）和 `default_q` 差距可能 0.5~1.5 rad/关节。
boot ramp 会用 5 s 时间把这 12 个腿关节同时往站立位置拉，最后 1 s 时 `kp_scale=1.0` —— G1 腿 Kp 名义值是 100~200，**全力扭矩去推一个被地板挡住的腿**。

后果：电机持续过流、保护跳闸，运气不好烧驱动板。

### 2.2 RL policy 收的是 OOD 输入，输出垃圾

策略训练分布里 `projected_gravity ≈ [0, 0, -1]`（机器人直立）；躺地时 IMU 测出来可能是 `[0.95, 0.0, -0.3]` 之类，第一层 MLP 立刻被推到训练分布外。
QA5 已经详细解释过：**MLP 不是 modular 的，OOD 输入会让 29 维输出全部变成垃圾**——腿、腰、手臂同时乱抖。

这种状态下指令是不是"通了"完全无法判断（看到的"动"全部是策略的乱蹦，不是你按的键）。

### 2.3 我们其实根本不需要 policy

测的目标只是 **"lowcmd 发出去 → 电机收到 → 关节动"**。这条链路只需要：

- 一个能定期发 `LowCmd_` 的发布器（`ChannelPublisher("rt/lowcmd", LowCmd_)`）；
- 一个能收 `LowState_` 当心跳/超时检测的订阅器（`ChannelSubscriber("rt/lowstate", LowState_)`）；
- 一组**对躺地机器人安全**的关节目标值。

所以 lying 模式的设计就是把 policy 和 boot ramp 全摘掉，只保留这两条 DDS 通道 + 一组小幅、单关节手臂抖动的测试动作。

---

## 3. 设计

### 3.1 命令行

```bash
# 旧版（站立 + RL，不要拿来跑躺地的机器人）
python g1_real_rl_combo.py eno3

# 新增：躺地测试模式
python g1_real_rl_combo.py eno3 lying
```

`lying` 这个 token 出现在 `argv[1:]` 任意位置就生效；其余参数还是按原来的"网卡名 / `lo` / `sim`"语义解析。
仿真器里也能用：`python g1_real_rl_combo.py lying`（默认走 `lo`）——主要给写脚本的人在没有真机时跑一遍 keypress → 手臂 q_target 的链路自检。

### 3.2 启动序列

`ComboController(cfg, policy, lying_mode=True)` + `ctl.start()` 后：

```
start() (lying 分支):
  等首个 rt/lowstate；
  lying_q_baseline   = 测得 29-D 姿态；   ← 不再向 default_q 靠拢
  arm_rest           = lying_q_baseline[15:29]   ← 让 release_arms 还原到躺地姿势
  arm_q_target       = arm_rest.copy()
  kp_scale           = LYING_KP_SCALE (0.2)        ← 名义增益的 1/5
  RecurrentThread(target=_tick_lying)
  print "[combo] LYING-DOWN TEST MODE. Holding measured pose at kp_scale=0.20."
```

要点：

- **没有 boot_t、没有 boot_dur、没有 cosine ramp**，因此 12 个腿关节不会被任何"目标姿态"拉走；
- `kp_scale=0.2` 让 12 腿 + 3 腰 + 14 臂 整体增益统一缩到 1/5。G1 腿名义 Kp ≈ 100~200，缩到 ≈ 20~40，已经低到压不动地板，但又不至于完全松垮（仍能维持心跳/状态可见的力闭环）。
- `arm_rest` 被重新指向 baseline 的手臂切片，所以 `release_arms()` 在 lying 模式下会"还原回测得姿态"，而不是"还原回站立默认姿态"。

### 3.3 50 Hz tick（lying）

```python
def _tick_lying(self):
    if self._stop.is_set() or not self.first_state_received:
        return
    # soften ramp（让 'space' 还能软关闭电机）
    if self._soften_steps_left > 0:
        self.kp_scale += self._soften_step
        self._soften_steps_left -= 1
        ...
    # watchdog：状态丢了就一直发 baseline
    if time.monotonic() - self.last_state_time > LOWSTATE_TIMEOUT:
        self._publish(self.lying_q_baseline)
        return
    q_target = self.lying_q_baseline.copy()
    arm_q = self._advance_arms()
    if arm_q is not None:
        arm_q = self._clamp_arm_to_safe_envelope(arm_q)   # baseline ± 0.25 rad
        arm_q = self._rate_limit_arm_step(arm_q)
        q_target[ARM_START:ARM_END] = arm_q
    self._publish(q_target)
```

对比正常 `_tick`，删掉了：

- boot ramp 全段；
- `obs = self._build_obs()` + `raw_action = self.policy(obs)` + `q_target = raw_action*scale + offset`；
- `last_raw_action` 的反向同步（lying 模式 policy 不跑，没必要保持 obs 自洽）。

### 3.4 安全包络：`baseline ± LYING_TEST_DELTA`

`_clamp_arm_to_safe_envelope` 现在是 mode-aware 的：

```python
def _clamp_arm_to_safe_envelope(self, arm_q):
    if self.lying_mode:
        base = self.lying_q_baseline[ARM_START:ARM_END]
        return np.clip(arm_q, base - LYING_TEST_DELTA, base + LYING_TEST_DELTA)
    # normal mode：default ± K * action_scale，沿用 QA5
    lo = self.arm_offset - self.ARM_GESTURE_K * self.arm_scale
    hi = self.arm_offset + self.ARM_GESTURE_K * self.arm_scale
    return np.clip(arm_q, lo, hi)
```

`LYING_TEST_DELTA = 0.25 rad`（约 14°）是绝对值上限，因为：

- 躺地时 baseline 不是 `default_q`，policy 训练分布的 `± K·action_scale` 包络在这里没意义；
- 0.25 rad 远小于关节物理 ROM，对各臂关节都安全；
- 即使某只手臂被压在身体下、关节阻塞了，`kp_scale=0.2` 下产生的扭矩也在电机持续输出范围内。

### 3.5 测试手势（键 `1..7`）

每个动作只移动**一个**手臂关节，幅度 0.10~0.20 rad，blend 1.0 s → hold 0.5 s → blend 1.0 s 回到 baseline：

| 键 | 动作 | 关节 | 偏移 |
|---|---|---|---|
| 1 | wiggle right shoulder pitch | RightShoulderPitch (22) | +0.15 rad |
| 2 | wiggle left shoulder pitch  | LeftShoulderPitch (15)  | +0.15 rad |
| 3 | wiggle right elbow          | RightElbow (25)         | +0.20 rad |
| 4 | wiggle left elbow           | LeftElbow (18)          | +0.20 rad |
| 5 | wiggle right wrist roll     | RightWristRoll (26)     | +0.15 rad |
| 6 | wiggle left wrist roll      | LeftWristRoll (19)      | +0.15 rad |
| 7 | bilateral shoulder roll outward | LeftShoulderRoll (16) +0.10 / RightShoulderRoll (23) -0.10 | ±0.10 rad |

为什么是单关节为主？因为目的是"逐通道排查"——按 1 不动但按 2 动，可以推断出右肩 pitch 那条电机/线缆/编码器有问题；按全身动作就分不清了。

为什么 elbow 是 0.20 而不是 0.15？elbow 在多数躺姿下被压住的可能性小，多给点幅度好让肉眼分辨。

### 3.6 其他键

| 键 | 行为（lying 模式） |
|---|---|
| `0` | 取消当前 wiggle，blend 回 baseline（在 normal 模式下含义是 "hand back to policy"，lying 下没有 policy，行为退化为"还原"）|
| `space` | `kp_scale → 0`，软释放所有电机；机器人摊在地上不施力 |
| `?` | 打印 lying 模式 help（与 normal 不同） |
| `x` / Ctrl-C | 软释放后退出 |
| `w/s/a/d/q/e/r/f` | **禁用**，按下打印 `[combo] walking keys disabled in lying-down test mode` |

---

## 4. 代码改动总览（同一文件）

文件：`g1_real_demo/g1_real_rl_combo.py`

| 区段 | 修改 |
|---|---|
| 模块 docstring | 加 "Lying-down test mode" 一节，说明用法和与 normal 模式的区别 |
| `POLICY_DIR` | 改成 `Path(__file__).resolve().parent.parent / "unitree_rl_mjlab/..."`（**同时修了 dc2f458 留下的路径不存在问题**）|
| `ComboController` 类常量 | 新增 `LYING_KP_SCALE = 0.2`、`LYING_TEST_DELTA = 0.25` |
| `ComboController.__init__` | 新增 `lying_mode: bool = False` 参数；新增字段 `self.lying_q_baseline` (29-D) |
| `ComboController.start()` | 拆出 `if self.lying_mode` 分支：跳过 boot 系列状态、设置 `arm_rest = baseline 的手臂切片`、启动 `_tick_lying` |
| `ComboController._tick_lying()` | **新增方法**。soften / watchdog / 发 baseline + 可选手臂叠加，纯心跳，无 policy |
| `ComboController._clamp_arm_to_safe_envelope()` | 加 `if self.lying_mode` 分支，envelope 改为 `baseline ± LYING_TEST_DELTA` |
| `build_lying_test_actions(arm_baseline)` | **新增**。生成 7 条单关节小幅 wiggle 动作 |
| `format_help(actions, lying_mode=False)` | 加 `lying_mode` 参数，渲染不同的帮助文案；禁用走路键时也 reflect 在 help |
| `main()` | 解析 `lying` token；先 `ctl.start()` 再 `build_lying_test_actions(ctl.arm_rest)`（要等首帧 lowstate 捕获到 baseline 后再建表）；走路键在 lying 模式下打印禁用提示 |

---

## 5. 怎么跑

### 5.1 前置条件

- 机器人通电、连好调试线；
- 主机网卡 IP 在 `192.168.123.0/24` 段内（见本机 `eno3 = 192.168.123.222`）；
- 机器人**已经处于安全的躺平姿态**（即没有关节被地板别扭的角度卡住）；
- 急停在手边。

### 5.2 启动

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_real_demo
python g1_real_rl_combo.py eno3 lying
```

预期 stdout：

```
[combo] LYING TEST MODE on eno3 (domain 0).
[combo] No policy, no boot ramp. Robot holds measured pose.
[combo] loaded deploy.yaml (vx in (..., ...), ..., step_dt=0.02s)
[combo] loaded policy: /home/.../policy.onnx        # ← 仍会加载，但不会跑推理
[combo] waiting for first /rt/lowstate ...
[combo] LYING-DOWN TEST MODE. Holding measured pose at kp_scale=0.20. No policy, no boot ramp.

==== G1 RL walk + arm gesture combo ====
LYING-DOWN TEST MODE — robot stays at measured pose.
No policy, no boot ramp, walking keys disabled.
Arm wiggles (small per-joint motion, returns to baseline):
  1        wiggle right shoulder pitch +0.15
  2        wiggle left shoulder pitch +0.15
  3        wiggle right elbow +0.20
  4        wiggle left elbow +0.20
  5        wiggle right wrist roll +0.15
  6        wiggle left wrist roll +0.15
  7        bilateral shoulder roll outward 0.10
  0        cancel wiggle, return arms to baseline
System:
  space    soft-disable Kp/Kd (release motors)
  ?        print this help
  x / Ctrl-C  quit (settles softly first)
=========================================
```

如果看到 `waiting for first /rt/lowstate ...` 卡住超过 5 秒：DDS 通道没通——通常是网卡选错、防火墙拦了、或者机器人本体没启动 `unitree_sdk2py` 兼容服务。这种情况按 Ctrl-C 退出排查，不要继续按按键。

### 5.3 验证步骤建议

1. **先什么都不按、看 30 s**。机器人应当**不动**（关节误差为 0，PD 不出力）；如果出现轻微抖动，记录一下哪些关节抖，这通常是编码器噪声/IMU 漂移，跟 lying 模式本身无关。
2. **按 `1`**（右肩 pitch + 0.15 rad）。预期：
   - 终端打印 `[combo] arm gesture '1' = wiggle right shoulder pitch +0.15`；
   - 右肩 pitch 在 ~1 s 内向前/向上抬约 8°，停 0.5 s，再回到原位；
   - 其他 28 个关节**完全不动**。
   - 如果右肩没动 → 该电机/驱动板/线缆出问题；
   - 如果其他关节也跟着动 → DDS clobber 风险（本程序内不会发生；如果发生，说明有第二个发布器在打 `rt/lowcmd`，去找那个进程）。
3. **依次按 `2..6`**，每次只动一个关节。
4. **按 `7`**（双肩外展）确认两个 shoulder roll 通道。
5. **按 `space`**：所有 motor `kp/kd → 0`，机器人完全软掉，关节像断电一样自由（在地板上不会动，因为它本来就在地上）。从这一刻起按任何动作键都不会让关节动，因为没有刚度。
6. **按 `x` 或 Ctrl-C** 退出，程序会先 soften 再关线程。

### 5.4 常见排查矩阵

| 现象 | 可能原因 | 下一步 |
|---|---|---|
| 永远卡在 `waiting for first /rt/lowstate ...` | 网卡名错；机器人未启动 SDK 服务；IP 不在 `123.x` 段 | `ip a` 确认 `eno3`；`ping 192.168.123.161`；Unitree app 检查机器人状态 |
| 收到 lowstate，但按 `1..7` 没有任何关节动 | 电机被锁/未上使能；或刚度系数被全局压到 0 | Unitree app 看电机 enable 状态；机器人控制器是否在 "damping" 模式（部分模式会忽略 lowcmd） |
| 按 `1`，**腿和腰也跟着抽** | 不应该发生。lying 模式没有 policy，腿/腰部分 q_target 永远 = baseline。如果发生，几乎只能解释为有第二个进程在发 `rt/lowcmd`（QA1 老坑） | `ps -ef \| grep python`；杀掉别的 demo |
| 关节抖动幅度比 0.15 rad 大很多 | rate-limit 没生效（不太可能）；或测量时有飘移叠加 | 用 `rerun` / `rqt_plot` 抓 `motor_state[i].q` 看真实轨迹 |
| 电机短时报警/温度上升 | 某只手臂被身体压住，0.2 倍 Kp 仍持续推进 | 立刻 `space` 释放；调整机器人姿态后再继续；必要时把 `LYING_KP_SCALE` 调到 0.1 |

---

## 6. 安全注意

1. **永远在急停可触及范围内启动。** 即便已经躺平，电机被卡住时仍可能产生持续电流。
2. **不要在 lying 模式里按 `w/s/a/d/...`。** 程序会拒绝并打印警告，但仍然建议手不要乱按。
3. **不要在 lying 模式跑完后不退出就直接抓机器人去站立。** 这时候 `kp_scale=0.2` 的发布还在跑，被你拉到一个新姿态后程序会试图把关节"拉回 baseline"。**先按 `x` 或 `space` 让程序退出/松力**，再去搬动机器人。
4. **不要把 `LYING_KP_SCALE` 调到 0** 当"心跳"用。Kp=0 + Kd=0 时 lowcmd 不再做闭环，相当于完全开环，你失去了心跳的物理意义；要"软"用 `space`。
5. **本模式不支持 high-level 切换（比如切到 RL 控制）。** 它只测 lowcmd 通路；要测 RL 必须先把机器人架到能站的姿态再跑 normal 模式。

---

## 7. 顺手修的 `POLICY_DIR` 路径

`dc2f458 update relative path` 把：

```python
POLICY_DIR = Path.home() / "unitree/unitree-notes/unitree_rl_mjlab/..."
```

改成：

```python
POLICY_DIR = Path.home() / "unitree-notes/unitree_rl_mjlab/..."
```

但 `~/unitree-notes` 这个路径在本机不存在（仓库实际克隆在 `~/unitree/unitree-notes/`），导致脚本启动直接 `FileNotFoundError: deploy.yaml`，连 lying 测试都跑不起来。

修法是改用脚本自身位置：

```python
_REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = (
    _REPO_ROOT
    / "unitree_rl_mjlab/deploy/robots/g1"
    / "config/policy/velocity/v0"
)
```

这样无论仓库克隆到哪、`$HOME` 长什么样，只要保留 `g1_real_demo/` 和 `unitree_rl_mjlab/` 在同一个仓库根下就能找到。

---

## 8. 自检（不用真机即可）

在 `unitree` conda 环境下：

```bash
conda activate unitree
cd ~/unitree/unitree-notes/g1_real_demo
python -c "
import sys, importlib.util, numpy as np
spec = importlib.util.spec_from_file_location('m', 'g1_real_rl_combo.py')
m = importlib.util.module_from_spec(spec); sys.modules['m'] = m
spec.loader.exec_module(m)

# 路径
assert m.POLICY_YAML.exists(), m.POLICY_YAML
assert m.POLICY_ONNX.exists(), m.POLICY_ONNX

# 加载
cfg = m.DeployCfg(m.POLICY_YAML); pol = m.Policy(m.POLICY_ONNX)

# lying 包络
ctl = m.ComboController(cfg, pol, lying_mode=True)
ctl.lying_q_baseline = np.full(29, 0.1)
out = ctl._clamp_arm_to_safe_envelope(np.full(14, 5.0))
assert np.allclose(out, 0.1 + 0.25), out

# normal 包络（不应被 lying 影响）
ctl2 = m.ComboController(cfg, pol, lying_mode=False)
arm = cfg.default_q[15:29].copy(); arm[0] += 5.0
out2 = ctl2._clamp_arm_to_safe_envelope(arm)
assert abs(out2[0] - (cfg.default_q[15] + 2.0*cfg.action_scale[15])) < 1e-9

# gesture 表
acts = m.build_lying_test_actions(np.zeros(14))
assert [a.key for a in acts] == ['1','2','3','4','5','6','7']
assert all(len(a.keyframes) == 3 for a in acts)
print('lying-mode self-check OK')
"
```

预期输出：

```
lying-mode self-check OK
```

跑通后再上真机即可。

---

## 9. 与 QA1..QA5 的关系

| QA | 解决的 | 与本文 lying 模式的关系 |
|---|---|---|
| QA1 | 多个发布器同时写 `rt/lowcmd` | lying 模式仍是单发布器，这条原则不变 |
| QA2~QA3 | sim 起步姿态/elastic band | lying 模式直接跳过 boot ramp，不存在该问题 |
| QA4 | "默认锁手臂"导致策略 OOD 飞起 | lying 模式里 policy 完全不跑，无关 |
| QA5 | 手势超出训练分布 + last_action 失配 | lying 模式没有 policy，envelope 换成 baseline-relative，不需要 last_action 同步 |
| **QA7（本文）** | **真机躺平、无法 boot/无法 policy 时如何安全验证 DDS + 电机** | 用单独的 `_tick_lying` 走完全不同的快路径 |
