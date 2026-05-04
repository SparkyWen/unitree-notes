# va-demo 使用指南

> 配套于 `va-demo/README.md` 和 `docs/va-demo-design.md`。
> 这份文档专门记录"从零打开终端到能跟 G1 对话"的完整步骤。

---

## 1. va-demo 长什么样（不是网页！）

va-demo **没有 web UI**。它是一个 CLI 进程 + 三个外部依赖：

| 你看到的窗口 | 来源 | 内容 |
|---|---|---|
| MuJoCo 3D 视窗 | `unitree_mujoco.py` | G1 在场景里站立/行走/做手势 |
| 终端日志（va-demo） | `python -m va_demo.main` | 模型工具调用、安全检查、状态日志 |
| 终端日志（teleimager） | `python -m teleimager.image_server` | 摄像头帧率、客户端连接 |
| 终端日志（mujoco） | 同上 | 物理仿真 tick |
| 你的扬声器 | `sounddevice` + OpenAI Realtime/TTS | G1 的语音 |

交互方式：**对着笔记本麦克风说话** → Realtime 模型语音回答；问"看到什么"会自动调 vision 工具读 teleimager 的最新帧；让它走/挥手会触发 ComboController 在 MuJoCo 里执行。

### 1.1 va-demo 和你熟悉的 `g1_sim_rl_combo.py` 是同一套底层

这点对你的"我经常跑 `g1_sim_rl_combo.py` 看策略"的习惯非常关键 —— **va-demo 直接 import 了未改动的 `g1_sim_rl_combo.py`，复用同一个 `ComboController`、同一个 `policy.onnx`、同一组 8 个手势**。代码证据在 `va_demo/skills.py:101`：

```python
import g1_sim_rl_combo as combo
cfg    = combo.DeployCfg(combo.POLICY_YAML)
policy = combo.Policy(combo.POLICY_ONNX)
ctl    = combo.ComboController(cfg, policy)
```

所以：**你过去在 MuJoCo viewer 里看到 `g1_sim_rl_combo.py` 怎么走、怎么挥手，va-demo 跑出来一模一样**。区别只有一个 —— 触发源：

| 谁说"走/挥手" | `g1_sim_rl_combo.py` | va-demo |
|---|---|---|
| 触发 | 终端键盘 (w/a/s/d/1..8) | 你的语音 → Realtime 模型 → 工具调用 |
| 安全层 | 直接执行 | `SafetySupervisor`：observe / confirm / active 三档 + 数值上限 + watchdog |
| DDS | domain 1, iface lo | 同 |
| ComboController 实例 | 1 个 | 1 个（不能并行） |

va-demo 内部的手势名 ↔ `g1_sim_rl_combo.py` 键位映射（`va_demo/skills.py:22-31`）：

| va-demo `gesture(name)` | combo 键 | 你说的话 |
|---|---|---|
| `wave_right` | `1` | "向我挥右手" |
| `wave_left` | `2` | "挥左手" |
| `hands_up` | `3` | "举手" |
| `t_pose` | `4` | "T pose" |
| `salute` | `5` | "敬礼" |
| `clap` | `6` | "鼓掌" |
| `guard` | `7` | "防御姿势" |
| `punch_combo` | `8` | "出拳" |

⚠️ **互斥**：`g1_sim_rl_combo.py main` 和 `va_demo.main` **不能同时跑**。两个都创建 `ComboController` 都往 `rt/lowcmd` 发指令，最后写入的赢，但中间会打架、G1 抽搐。任意时刻只能有一个 ComboController 在 lo:1 上。

### 1.2 重要：teleimager 的相机 ≠ MuJoCo 的虚拟相机

`teleimager.image_server` 拉的是**真实 USB 摄像头**（UVC/RealSense），不是 MuJoCo 场景里 G1 头部的虚拟相机。所以当你问 G1 "你看到什么"，模型描述的是**你笔记本/桌面那只 USB 摄像头对着的真实世界**，跟 MuJoCo viewer 里的画面没关系。

含义：

- 测视觉时，把 USB 摄像头对准一些有意思的东西（杯子、书、你的脸），然后才有内容可描述。
- 如果你想让"看到的"和"动的"对得上（视觉闭环），需要把相机摆好，手动对准你想让 G1 反应的真实场景；MuJoCo 里 G1 走出去多远跟相机看到什么没有耦合。
- 真正的"虚拟相机进 LLM"链路在 `docs/vlm_audio_mock_deep.md` 后续 phase，不在 va-demo v1 里。

---

## 2. 启动顺序心智模型：谁能并行、谁互斥

这一节是**最容易踩的坑**，先搞清楚再启动任何东西。

### 2.1 一句话规则

> **mujoco（+ 可选的 teleimager）一直跑；`g1_sim_rl_combo.py` / `scripts/skill_debug.py` / `python -m va_demo.main` 三个里只能同时跑一个，不能并行。**

下面解释为什么、以及哪些可以并行哪些不能。

### 2.2 为什么不能并行：不是"频率冲突"，是"指令竞写"

直觉上你可能担心"两个 50 Hz 的控制器一起发指令，频率会冲突或卡死"。**这不是 DDS 层的问题** —— DDS 不会因为有两个 publisher 在同一个 topic 上就降频或卡死。**真正的问题是 publisher 数量，不是频率。**

仿真的 DDS topology：

```
unitree_mujoco.py     ──发布──>  rt/lowstate (50 Hz, 关节角/速度/IMU)
                      ──订阅──>  rt/lowcmd  (接收谁要它做什么)

ComboController       ──订阅──>  rt/lowstate
                      ──发布──>  rt/lowcmd  (50 Hz, 关节目标 + Kp/Kd)
```

如果你**同时**起了 `g1_sim_rl_combo.py` **和** `skill_debug.py`，每一个内部都会 `combo.ComboController(cfg, policy)`，结果是：

```
g1_sim_rl_combo.py    ──发布──>  rt/lowcmd  (50 Hz, "前进 0.3")
                                       │
skill_debug.py        ──发布──>  rt/lowcmd  (50 Hz, "停在原地")
                                       │
                                       ▼
                          mujoco 同时收到两路消息，时间上交错
                          每 10 ms 关节目标在两套之间反复横跳
                          → G1 抽搐 / 飘 / 摔倒
```

DDS 默认 reliability 是 best-effort + last-is-best，**没有任何"合并"语义**。两个 publisher 写同一个 topic = 互相覆盖。所以症状不是"卡顿"，而是"控制器打架，机器人乱动"。

### 2.3 哪些会创建 ComboController（互斥的）、哪些不会（可以并行）

| 组件 | 是否创建 ComboController | 是否发 `rt/lowcmd` | 能不能跟别人并行 |
|---|---|---|---|
| `unitree_mujoco.py` | ❌ 它是仿真本身 | ❌（只接收） | 必须一直开，是基础 |
| `teleimager.image_server` | ❌ 只碰 ZMQ + USB 摄像头 | ❌ | 任何时候都能开 |
| `g1_sim_rl_combo.py` main | ✅ | ✅ 50 Hz | **互斥组：三选一** |
| `va-demo/scripts/skill_debug.py` | ✅（通过 `build_skill_backend()`）| ✅ 50 Hz | **互斥组：三选一** |
| `python -m va_demo.main` | ✅（默认） | ✅ 50 Hz | **互斥组：三选一** |
| `python -m va_demo.main --no-skills` | ❌（显式跳过） | ❌ | 可以跟上面三个之一并存（但意义不大） |
| `scripts/audio_loopback.py` | ❌ 只用 sounddevice | ❌ | 任何时候（占用麦+喇叭） |
| `scripts/tts_debug.py` | ❌ | ❌ | 任何时候（占用喇叭） |
| `scripts/camera_debug.py` | ❌ | ❌ | 任何时候（需要 teleimager） |
| `scripts/vision_loop_debug.py` | ❌ | ❌ | 任何时候（需要 teleimager） |

记忆口诀：**"谁创建 ComboController 谁就要排队"**。

### 2.4 你应该按这个顺序操作

把每一级看成"换装"：底座（mujoco + teleimager）不变，控制器一次只插一个。

```
┌─────────────────────────────────────────────────────────────┐
│ 终端 1 (从头到尾不关)：                                      │
│   conda activate agi                                        │
│   cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python │
│   python unitree_mujoco.py                                  │
│   # viewer 弹出 → 按 7 放下 → 按 9 松带                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 终端 2 (Level 3+ 才需要，开了就一直留着)：                   │
│   conda activate agi                                        │
│   cd ~/unitree/unitree-notes/teleimager                     │
│   python -m teleimager.image_server                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ 终端 3 (来回换，一次只跑一个)：                              │
│                                                             │
│  Level 0:  cd ~/unitree/unitree-notes/g1_sim_demo           │
│            python g1_sim_rl_combo.py                        │
│            # 测完按 x 退出 ←←← 必须先退                     │
│                                                             │
│  Level 1:  cd ~/unitree/unitree-notes/va-demo               │
│            python scripts/skill_debug.py                    │
│            # 测完按 x 退出 ←←← 必须先退                     │
│                                                             │
│  Level 4+: cd ~/unitree/unitree-notes/va-demo               │
│            set -a; source .env; set +a                      │
│            python -m va_demo.main --mode confirm            │
└─────────────────────────────────────────────────────────────┘
```

每次切换之前，**确认终端 3 上一个进程已经按 `x` 退出**，看到 `[combo] softening and exiting ...` 才安全。

### 2.5 怎么判断"是不是有两个 ComboController 在跑"

如果忘了关上一个，最快验证方法：

```bash
# 查所有发 rt/lowcmd 的 python 进程
ps aux | grep -E "g1_sim_rl_combo|skill_debug|va_demo.main" | grep -v grep
```

如果列出超过 1 行 → 有冲突。kill 掉旧的再启新的：

```bash
kill <PID>     # 优雅退出（ComboController 会 stop_and_settle）
# 实在不响应再 kill -9 <PID>
```

mujoco viewer 里 G1 一旦开始没来由地抽搐 / 关节乱跳 / 站不稳，**先想这件事**。

### 2.6 音频/喇叭的"轻度并行"问题（不严重但要知道）

`audio_loopback.py` / `tts_debug.py` / `va_demo.main` 都会打开 sounddevice 的输入/输出流。同时跑两个会争抢声卡设备：

- ALSA / Pulse 一般会让后者打开失败（报 `device unavailable` 或 `Error opening InputStream`）。
- 即使两个都打开成功，喇叭里会听到混音 / 卡顿。

所以音频脚本之间也不要并行。但这个 **不会让 G1 抽搐**，只是音频体验差，跟 ComboController 互斥不是一个级别的问题。

### 2.7 总结：最常用的"我就想测一下完整闭环"启动序列

4 个终端，按顺序起：

1. **终端 1**：`unitree_mujoco.py` → 按 `7` `9` 让 G1 站稳
2. **终端 2**：`teleimager.image_server` → 看到 "publishing on tcp://127.0.0.1:55555"
3. **（可选）终端 3 先做基线**：`g1_sim_rl_combo.py` → 按 `w` `1` 验证 mujoco/policy 正常 → **按 `x` 退出**
4. **终端 3 换成 va-demo**：`set -a; source .env; set +a` → `python -m va_demo.main --mode confirm`
5. **对着麦克风说话**

终端 1、2 全程不动；终端 3 是**唯一会换进程**的地方。下面 §6 的 ladder 就是按这个心智模型展开的。

---

## 3. API key 放在哪里

key 已经放在 `va-demo/.env`，权限 `600`，被 `unitree-notes/.gitignore` 完整忽略（连 `git status` 都不会显示）。

```
va-demo/
├── .env             # 真实 key，gitignored、chmod 600
├── .env.example     # 模板，提交到仓库
└── ...
```

`.env` 当前内容（占位示意，真实值在文件里）：

```bash
OPENAI_API_KEY=sk-proj-...
OPENAI_REALTIME_MODEL=gpt-realtime
OPENAI_VISION_MODEL=gpt-5.5
OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

启动 va-demo 前，必须先把 `.env` 加载进 shell：

```bash
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
echo "${OPENAI_API_KEY:0:12}..."   # 验证已注入
```

> ⚠️ 这次对话里 key 是明文贴出来的，已经留在 Claude 的 transcript 里。建议你**到 OpenAI 后台 revoke 一次再生成新的**，然后只更新 `va-demo/.env`，其它地方不需要动。

---

## 4. 一次性环境准备

只在第一次（或换机器）做一次：

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
pip install -r requirements.txt        # openai/sounddevice/websockets/...

# WSL2 必装：PortAudio（让 sounddevice 能找到设备）
conda install -n agi -c conda-forge portaudio
```

确认音频设备能被看到（**关键预检**）：

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```

- 列表非空 → OK，进入下一步。
- 列表为空或只有一行 ALSA 没设备 → 看 `va-demo/README.md` §"Audio prerequisites in WSL2"，多半要 `usbipd attach` 一只 USB 麦/声卡，或在 `configs/va_demo.yaml` 里写死 `audio.input_device` / `audio.output_device` 索引。

---

## 5. 三个终端的启动顺序

**所有终端都要 `conda activate agi`。**

### 终端 1 — MuJoCo 仿真

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

- MuJoCo viewer 弹出后：按 `7` **把 G1 放下**到地面，按 `9` **松开/禁用 elastic band**（按 `8` 是反方向把它再吊起来，调试时一般不用）。
- 看到 G1 双脚落地、policy 接管后保持站立（轻微微调脚踝）即可。
- 视窗里可以鼠标拖拽视角、滚轮缩放；摔倒后按一下 `Backspace` 重置仿真状态。

### 终端 2 — TeleImager 图像服务

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

- 默认绑 `127.0.0.1:55555` (PUB) / `60000` (REQ)。
- 摄像头怎么 attach 进 WSL2 看 `docs/camera_ui_demo.md`。

### 终端 3 — va-demo 主进程

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a       # ← 关键，加载 OPENAI_API_KEY
python -m va_demo.main
```

启动后日志大致：

```
INFO va_demo: DDS initialized: domain=1 iface=lo
INFO va_demo: waiting for ComboController policy_active ...
[combo] policy ready
INFO va_demo: run_mode=confirm
... websocket connected to wss://api.openai.com/v1/realtime ...
```

第一次跑保留默认 `--mode confirm`：每次 `walk()` / `gesture()` 都会在终端打印 y/N 提示。信任之后再换：

```bash
python -m va_demo.main --mode active     # 不再 prompt，模型说走就走
python -m va_demo.main --mode observe    # 完全禁动作，只语音+视觉
```

---

## 6. 在 MuJoCo viewer 里逐级验证 va-demo

照着你跑 `g1_sim_rl_combo.py` 的习惯展开成 5 级 ladder。每一级都 **只引入一个新变量**，挂在哪一级就知道是哪一段链路坏了。

### Level 0 — 你已经熟的基线（确认 sim + policy 健康）

如果今天 MuJoCo / policy 本身有问题，va-demo 不可能正常。**先用你最熟的命令把基线跑通**：

```bash
# 终端 A
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 弹出 → 按 7 放下 → 按 9 松开 elastic band

# 终端 B
conda activate agi
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
# 等 "[combo] policy ready"
# 按 w 几次 → G1 应当向前迈步
# 按 1 → 右挥手；按 8 → 出拳组合
# 按 r 停；按 0 释放手臂；按 x 退出
```

✅ 只有这一级跑通了再往下走。这一级出问题就不是 va-demo 的事，是 mujoco/policy/DDS 的事。

退出 `g1_sim_rl_combo.py`（按 `x`）后再做下一级 —— **不要让两个 ComboController 共存**。

### Level 1 — va-demo 的 SkillBackend 链路（无 OpenAI、无音频）

这一级**唯一的新变量**是 va-demo 的包装层 `SkillBackend`。如果 Level 0 OK 而这一级失败，问题在 `va_demo/skills.py` 或 `safety.py`，跟模型/音频无关。

```bash
# 终端 A：unitree_mujoco.py 继续跑

# 终端 C
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python scripts/skill_debug.py
# 等 "ready. type a key (followed by enter): w/s/a/d/q/e/1..8/r/0/x"
```

逐键测试 + 在 viewer 里逐项打勾：

| 输入 | va-demo 调用 | viewer 里你应该看到 |
|---|---|---|
| `w` | `walk(0.15, 0, 0, 0.5)` | G1 微微向前迈一步，0.5 s 后停 |
| `s` | `walk(-0.15, 0, 0, 0.5)` | 后退一小步 |
| `a`/`d` | 横移 vy=±0.08 | 侧向小幅移动 |
| `q`/`e` | 原地转向 wz=±0.3 | 躯干旋转 |
| `1` | `gesture("wave_right")` | 右臂抬起做挥手轨迹（同你按 combo 的 `1`） |
| `2` | `wave_left` | 左臂挥手 |
| `3` | `hands_up` | 双手举高 |
| `4` | `t_pose` | 双臂水平张开 |
| `5` | `salute` | 敬礼 |
| `6` | `clap` | 鼓掌 |
| `7` | `guard` | 防御姿势 |
| `8` | `punch_combo` | 出拳组合 |
| `r` | `stop()` | 速度归零 + 释放手臂 |
| `0` | `release_arms()` | 手臂柔顺回到 policy 默认 |
| `x` | 退出 | `stop_and_settle()` 后退出 |

✅ 全部按键的视觉效果与 Level 0 一致 → SkillBackend 链路通。

### Level 2 — 音频 / 摄像头初始化（不连 OpenAI）

```bash
# 不需要 mujoco / teleimager
cd ~/unitree/unitree-notes/va-demo
python scripts/audio_loopback.py     # 5 s 麦→喇叭回环，看 RMS 进度条
python -m va_demo.main --no-realtime --no-skills
# 应该卡在 "realtime disabled; idling" 不退出，Ctrl-C 退出
```

这一级失败 = `sounddevice` 没找到设备 → 看 §4 预检 + `va-demo/README.md` §"Audio prerequisites in WSL2"。

### Level 3 — vision 工具单独验证（teleimager + OpenAI vision，无动作）

先 `set -a; source .env; set +a`，然后：

```bash
# 终端 D：teleimager
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# 终端 E：抓一帧问 vision 模型
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python scripts/camera_debug.py --question "前面有什么物体？"
```

把 USB 摄像头对准一个明显的东西（杯子、键盘），应该收到一段中文描述。失败时通常是：

- `no frame received` → teleimager 没启动 / 摄像头没被 WSL attach。
- `model not found` → key 没访问 `gpt-5.5`，把 `.env::OPENAI_VISION_MODEL` 改成 `gpt-5.1` 或别的可用 vision-capable 模型。
- 401/403 → key 失效，去 OpenAI 后台 rotate。

### Level 4 — 完整 va-demo 但禁动作（observe）

```bash
# 终端 A：mujoco
# 终端 D：teleimager
# 终端 F：va-demo observe
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python -m va_demo.main --mode observe
```

对话脚本：

1. "你好。" → 模型语音回应（验证 Realtime 双向）。
2. "看看前面有什么。" → 控制台打 `tool: describe_scene(...)`，几秒后语音说出描述（验证 vision 工具调用 + tool result 喂回 Realtime）。
3. "向前走两步。" → 控制台 `tool: walk(...)` 但 safety supervisor 直接拒绝，**MuJoCo 里 G1 不动**（这是预期，因为 observe 模式禁动作）。

✅ Realtime + vision 链路通，安全层也在生效。

### Level 5 — confirm 模式（你日常调试就用这档）

```bash
python -m va_demo.main --mode confirm
```

对话脚本（**核心验收**，眼睛盯 MuJoCo viewer）：

| 你说 | 终端预期 | viewer 里预期看到 |
|---|---|---|
| "向我挥右手" | `tool: gesture(name="wave_right")`，自动执行（gesture 默认不 prompt） | 右臂挥手轨迹，几秒后柔顺回 rest |
| "向前走一步" | 打 `walk(...) y/N?` 等你按 `y` | 按 `y` 后 G1 迈一步，0.5–1.5 s 后停下站稳 |
| "向左转 90 度" | safety 卡 `wz`/`duration` 上限会拒绝过大的请求 | 实际只小幅旋转或被拒绝（看终端日志） |
| "出拳" | `gesture(name="punch_combo")` | 出拳组合（和 combo 按 `8` 完全一致） |
| "停下来" | `tool: stop()` | 速度归零、手臂松回 policy 默认 |

任何一项视觉不对 = 问题在 `va_demo/realtime_agent.py`（参数解析）或工具描述（`va_demo/prompts.py`）让模型传了奇怪的值，看终端日志里 tool call 的实际参数。

### Level 6 — active 模式（无 prompt，全自动）

```bash
python -m va_demo.main --mode active
```

只在你已经在 Level 5 信任了模型的判断之后再用。viewer 里看到的动作完全由模型决定，**确保挂带可以快速重启 / `Backspace` 重置 / 备好 Ctrl-C**。

---

## 6b. 在 MuJoCo viewer 里到底"看什么"

每次 va-demo 触发动作时，去 viewer 里核对这几样：

- **基线姿态**：触发任何 walk/gesture *之前*，G1 应该是双脚落地、躯干微调、手臂下垂的稳态。如果一开始就在抖、在飘，多半是 elastic band 没松开（按 `9`）或者 policy 还没 `policy_active`（终端会先打 `[combo] waiting for first /rt/lowstate ...`）。
- **walk**：观察脚的接触相位（左脚 → 右脚交替），躯干高度不应明显塌陷。`vx_max=0.3 / vy_max=0.1 / wz_max=0.4 / duration_max=1.5s` 是 `configs/va_demo.yaml::safety.walk` 的硬上限，超出会被 safety 拒绝。
- **gesture**：观察手臂关节按预设关键帧滑过（每个手势在 `g1_sim_demo/g1_sim_rl_combo.py::build_arm_actions()` 里有完整定义），结束后会自动 `release_arms()` blend 回 rest。
- **大幅手势时机器人保持直立**：`punch_combo`、`hands_up` 这种重心偏移大的动作，看 G1 是否被自身惯量带倒。如果倒了：
  - 检查 `g1_sim_rl_combo.py` 顶部 `ARM_GESTURE_K`（默认 `2.0`），改大了就改回去。
  - 或临时按 `7` 把挂带升起来护一下。
- **tool call 的延迟**：从你说完话到 viewer 里 G1 开始动，预期 1–3 s（模型 Realtime turn end + tool dispatch + 你按 y 确认）。明显大于 5 s = WebSocket 卡顿或网络问题，看终端 `websockets` 日志。

可选诊断小工具（在 viewer 弹出后随时按）：

| 键 | 作用 |
|---|---|
| `Tab` | 切换 viewer 左侧菜单 / 右侧统计 |
| 鼠标左键拖 | 旋转视角；右键拖 = 平移；滚轮 = 缩放 |
| `Backspace` | 重置仿真到初始状态（不重启进程） |
| `Ctrl + 左键拖关节` | 给 G1 加扰动，测 policy 鲁棒性 |
| `7` / `8` / `9` | elastic band：放下 / 吊起 / 启用-松开 |
| `Esc` | 释放鼠标 |

---

## 7. 怎么"测"这个 demo（脚本对照表）

无 live 服务也能跑的"冒烟"：

```bash
cd ~/unitree/unitree-notes/va-demo
python -m pytest tests/ -v                   # safety + skills 单测
python -c "import va_demo.audio_io, va_demo.camera, va_demo.vision, \
                  va_demo.tts, va_demo.skills, va_demo.safety, \
                  va_demo.realtime_agent, va_demo.main"
python -m va_demo.main --help
```

需要 live 服务和/或 OpenAI key 的逐项验证（先 `source .env`）：

| 想验证什么 | 命令 | 依赖 |
|---|---|---|
| 麦克风→喇叭回环 | `python scripts/audio_loopback.py` | sounddevice |
| 摄像头+视觉模型 | `python scripts/camera_debug.py --question "前面有什么？"` | teleimager + key |
| TTS 输出 | `python scripts/tts_debug.py "你好，我是 G1。"` | 喇叭 + key |
| 仅技能（走/手势） | `python scripts/skill_debug.py` 然后输入 `w / 1 / 8 / r / x` | unitree_mujoco |
| 1 Hz 视觉循环 | `python scripts/vision_loop_debug.py --rate-hz 1.0` | teleimager + key |

测试时建议的"金路径"对话脚本：

1. "你好，能听到我说话吗？" → 模型应当语音回应。
2. "看一下前面，告诉我有什么。" → 触发 `describe_scene`，控制台会打印 tool call，几秒后语音回答。
3. "向前走一步。" → `confirm` 模式下控制台打印 `walk(...) y/N?`，按 `y`，看 MuJoCo 里 G1 迈步。
4. "挥挥右手。" → `gesture(wave_right)`。
5. "停下来。" → `stop()`，速度归零并放手。

---

## 8. 常见踩坑

| 现象 | 多半原因 | 解决 |
|---|---|---|
| `OPENAI_API_KEY is not set; ... pass --no-realtime` | 忘了 `source .env` | 在同一个终端 `set -a; source .env; set +a` |
| `OpenAI API error: model not found` | 账号没开 `gpt-5.5` | 把 `.env` 里的 `OPENAI_VISION_MODEL` 换成 `gpt-5.1` 或别的 vision-capable 模型 |
| `OSError: PortAudioError ... device unavailable` | WSL 没暴露默认 mic/speaker | `python -c "import sounddevice as sd; print(sd.query_devices())"` 找到索引，写到 `configs/va_demo.yaml::audio.input_device` / `output_device` |
| `[combo] waiting for first /rt/lowstate ...` 一直挂 | 终端 1 的 MuJoCo 没在 `domain=1, iface=lo` | 确认 `unitree_mujoco.py` 跑起来了；`va_demo.yaml::robot` 与之一致 |
| `no frame received` | 终端 2 的 teleimager 没起或绑别的口 | 确认终端 2 在跑；端口对得上 `cam_config_server.yaml::head_camera::zmq_port` |
| 大手势时 G1 摔倒 | 改宽了 `g1_sim_rl_combo.py::ARM_GESTURE_K` | 改回 `2.0`，那是结构性安全网 |
| 启动 va-demo 时 G1 抽搐 / 双脚乱蹬 | 同时还在跑 `g1_sim_rl_combo.py` 的 main，两个 ComboController 互相覆盖 `rt/lowcmd` | 关掉 combo 的 main，只留一个 ComboController（va-demo 内部已经在跑） |
| viewer 里 G1 不动但终端打了 tool call | safety 在 `observe` 模式拒绝动作；或 watchdog 因 frame_age > 2s / lowstate_age > 0.5s 拒绝 | 检查 `--mode`、teleimager 是否在出帧、unitree_mujoco 是否在出 lowstate |
| viewer 里 G1 在动但走的方向 / 手势不对 | 模型把工具参数解析错了 | 看终端日志里 `tool: walk(vx=..., vy=..., wz=...)` 实际值；必要时调 `va_demo/prompts.py` 里的工具描述 |

---

## 9. 安全模式速查

`--mode` 决定动作类工具是否要人确认：

| 模式 | `walk` / `gesture` 行为 | `say` / `describe_scene` |
|---|---|---|
| `observe` | 直接拒绝（safety supervisor 拦下） | 正常 |
| `confirm`（默认） | 终端 y/N 提示 | 正常 |
| `active` | 直接执行 | 正常 |

外加两个独立兜底：

- watchdog：摄像头帧 > 2s 旧 或 lowstate > 0.5s 旧 → 拒绝动作工具调用。
- 数值上限：`vx≤0.3, vy≤0.1, wz≤0.4, duration∈[0.2, 1.5]s`，硬编码在 `configs/va_demo.yaml::safety.walk`。

---

## 10. 收尾

按顺序 Ctrl-C 退出：va-demo → teleimager → mujoco。`va_demo.main` 退出时会主动 `stop()` + `release_arms()` + 关相机/音频流，G1 在 viewer 里会 settle 到 rest 姿态再退出。

如果要 rotate API key：编辑 `va-demo/.env`，新开 shell 重新 `source` 即可，**不要 commit**。

---

## 附录 A：va-demo 与 g1_sim_rl_combo.py 的代码对应

如果你想自己 trace 任何一条 va-demo 路径，对应位置：

| va-demo 文件 | 关键内容 | 对应 combo |
|---|---|---|
| `va_demo/skills.py:101` | `import g1_sim_rl_combo as combo`；构建 `ComboController` | `g1_sim_demo/g1_sim_rl_combo.py::ComboController` |
| `va_demo/skills.py:22` | `GESTURE_KEY_MAP` 把 `wave_right` 等映射到 combo 的 `1`..`8` | `g1_sim_rl_combo.py::build_arm_actions()` |
| `va_demo/skills.py:55` | `walk(vx, vy, wz, dur)` → `ctl.set_command(...)` + `asyncio.sleep` + 归零 | combo main 的 w/a/s/d/q/e 也是这同一对调用 |
| `va_demo/skills.py:64` | `gesture(name)` → `ctl.push_arm_action(action.keyframes)` | combo main 的 1..8 也是这同一对调用 |
| `va_demo/safety.py` | walk 的数值上限 / observe-confirm-active 三档 / watchdog | combo 没有这一层（直接执行） |
| `va_demo/realtime_agent.py` | WebSocket 连 `wss://api.openai.com/v1/realtime`，dispatch tool call → `safety` → `skills` | 不存在 |

换句话说：**`g1_sim_rl_combo.py` 的 `main()` 和 `va_demo.main` 都是 ComboController 的"用户"**，前者用键盘做触发器，后者用 OpenAI Realtime 做触发器，中间多了一层安全审批。
