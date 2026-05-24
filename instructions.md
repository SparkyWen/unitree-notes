# 1. mujoco跑rl_combo

终端 1：

```bash
conda activate agi

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
conda activate agi
cd ~/unitree/unitree-notes/g1_sim_demo
python g1_sim_rl_combo.py
```

终端2：

```
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

# 2. mujoco跑va

## 1. 启动VA demo

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

#### ==先把摄像头挂载到 WSL2==

确保 WSL2 的 Ubuntu 窗口已经打开，然后在 PowerShell 执行：

```powershell
usbipd attach --wsl --busid 1-8
```

再次检查：

```powershell
usbipd list
```

期望状态：

```text
1-8    322e:2122  USB2.0 HD UVC WebCam    Attached
```

只要状态不是 `Attached`，WSL2 里面就不会有 `/dev/video0`。

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
python -m va_demo.main --mode confirm
```

#### Level 1 — confirm 模式（你日常调试就用这档）

```bash
python -m va_demo.main --mode confirm
```

对话脚本（**核心验收**，眼睛盯 MuJoCo viewer）：

| 你说           | 终端预期                                                     | viewer 里预期看到                         |
| -------------- | ------------------------------------------------------------ | ----------------------------------------- |
| "向我挥右手"   | `tool: gesture(name="wave_right")`，自动执行（gesture 默认不 prompt） | 右臂挥手轨迹，几秒后柔顺回 rest           |
| "向前走一步"   | 打 `walk(...) y/N?` 等你按 `y`                               | 按 `y` 后 G1 迈一步，0.5–1.5 s 后停下站稳 |
| "向左转 90 度" | safety 卡 `wz`/`duration` 上限会拒绝过大的请求               | 实际只小幅旋转或被拒绝（看终端日志）      |
| "出拳"         | `gesture(name="punch_combo")`                                | 出拳组合（和 combo 按 `8` 完全一致）      |
| "停下来"       | `tool: stop()`                                               | 速度归零、手臂松回 policy 默认            |

任何一项视觉不对 = 问题在 `va_demo/realtime_agent.py`（参数解析）或工具描述（`va_demo/prompts.py`）让模型传了奇怪的值，看终端日志里 tool call 的实际参数。

#### Level 2 — active 模式（无 prompt，全自动）

```bash
python -m va_demo.main --mode active
```

只在你已经在 Level 5 信任了模型的判断之后再用。viewer 里看到的动作完全由模型决定，**确保挂带可以快速重启 / `Backspace` 重置 / 备好 Ctrl-C**。

---



## 2. 启动语音控制和安全加载demo

```python
# Terminal 3 — E-stop listener (independent process)
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener


# Press ESC at any time to engage; the file /tmp/g1_brain_estop is
# touched and the agent's SafetySupervisor rejects all motion until the
# file is removed.
```



```python
# Terminal 4 — agent
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --mode confirm
```


# 3. Memory Harness 全流程

把 G1 接入 Codex 订阅做长期记忆 + ask_slow_brain 的完整跑法。设计在 `docs/harness-design.md`,spec 在 `g1_brain/docs/superpowers/specs/2026-05-21-g1-memory-harness-design.md`。

## 3.1 一次性准备

```bash
# 1. Codex CLI 已登录(用你订阅的账号)
codex login                     # 弹浏览器,授权,只做一次
codex --version                 # 应该输出版本号

# 2. ripgrep 已装(快脑 recall_grep 用)
which rg && rg --version | head -1
# 没装就 sudo apt install ripgrep

# 3. agi 环境里有 pytest 等(只为跑测试用,运行 agent 不需要)
~/miniforge3/envs/agi/bin/python -c "import pytest, asyncio; print('ok')"
```

`configs/g1_brain.yaml` 末尾的 `memory:` 节默认 `enabled: true`,无需改。

## 3.2 启动顺序(memory 自动跟随 agent)

只需 2 个终端就能跑 memory harness。**不要单独再跑 `g1_sim_rl_combo.py`** —— `agent_main.py` 内部默认 `isolate_controller=True`,会自动 spawn 一个 `ComboProxy` 子进程跑 ComboController;如果你再独立启动 `g1_sim_rl_combo.py`,两个 ComboController 会同时往 `/rt/lowcmd` 发包打架。

```bash
# 终端 1 — MuJoCo 仿真
conda activate agi

# WSL2 下走 D3D12 GPU 加速(原生 Linux 可跳过这段)
export MESA_LOADER_DRIVER_OVERRIDE=d3d12
export GALLIUM_DRIVER=d3d12
export MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
export LIBGL_ALWAYS_SOFTWARE=0
export MUJOCO_GL=glfw
glxinfo -B | grep -E "OpenGL renderer|Accelerated|Device|Vendor"

cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py    # 按 7 放下,按 9 松开吊带

# 终端 2 — agent(memory 自动启用,内部自带 ComboProxy 子进程)
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

可选的第 3 个终端 —— E-stop 监听(panic-button,按 ESC 立刻零力矩):

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
```

不启它的话 SafetySupervisor 的软安全仍然在工作,只是少了一个独立兜底进程。

> ⚠️ `cameras.usb.source` 默认是 `teleimager`,如果你不打算测 wave / pose 类视觉技能,agent 起来会持续报 `watchdog usb_frame tripped`(不致命,memory harness 主流程不受影响)。要彻底消掉就跑 `teleimager.image_server`,或在 `configs/g1_brain.yaml` 里把 `cameras.usb.enabled` 改 `false`。

启动时 `agent.log` 里应看到:
```
memory subsystem started; root=/home/<user>/.unitree/g1_brain
codex daemon ready (tool=codex)
memory: injected N chars of passive context     # 首次启用时 N=0,Phase2 跑过一次以后才有
```

## 3.3 第一次运行会发生什么

- `~/.unitree/g1_brain/` 自动建出来:`memories/{AGENTS.md, MEMORY.md, .git/, rollout_summaries/}` + `state.sqlite` + `.codex_runtime/`(隔离的 CODEX_HOME)
- `MEMORY.md` 首行写下时间锚:`# Memory enabled at <ISO>`,这之前的所有 `logs/conversations/*.jsonl` 永不进 pipeline
- 每个 turn 的 `plan_done` 后,Phase1 在 30s debounce 后台跑(`codex exec --json --ephemeral`),把这次 session 的 JSONL 抽成 `{raw_memory, rollout_summary, slug}` 写进 SQLite
- Phase1 完成立刻评估 Phase2(没有 idle 周期):同步 `raw_memories.md` + `rollout_summaries/`,git diff 非空时再调一次 `codex exec` 整合,产出 `MEMORY.md` 和 `memory_summary.md`,然后 `git commit`
- session 结束(Ctrl-C / 关 agent)时强制 Phase1 + Phase2 各跑一次,保证当前 session 落盘

## 3.4 LLM 在 turn 内能用的 4 个新 tool

- `recall_grep(pattern, scope, [session_id], [max_lines])` — scope: `registry` / `rollouts` / `jsonl` / `all`。毫秒级,纯本地 rg。
- `recall_read(path, [start_line], [end_line])` — 沙箱路径,只读 `memories/` 和 `logs/conversations/`。
- `recall_glob(pattern, [limit])` — 列出 memory 文件。
- `ask_slow_brain(query, [timeout_s=20])` — 通过常驻 `codex mcp-server` daemon 做深思考。barge-in 自动取消。

LLM 按 `~/.unitree/g1_brain/memories/AGENTS.md` 里写的 4-6 步顺序自主调用(summary → 提关键词 → grep MEMORY.md → 开 1-2 个 rollout_summaries → 必要时 grep jsonl)。

## 3.5 检查状态

```bash
# 看 memory 树
ls -la ~/.unitree/g1_brain/memories/
cat ~/.unitree/g1_brain/memories/MEMORY.md
cat ~/.unitree/g1_brain/memories/memory_summary.md
ls ~/.unitree/g1_brain/memories/rollout_summaries/

# 看 SQLite jobs 表
sqlite3 ~/.unitree/g1_brain/state.sqlite \
  "SELECT kind, job_key, status, retry_remaining, last_error
   FROM jobs ORDER BY started_at DESC LIMIT 10;"

# 看 stage1 输出
sqlite3 ~/.unitree/g1_brain/state.sqlite \
  "SELECT session_id, rollout_slug, length(raw_memory), generated_at
   FROM stage1_outputs ORDER BY generated_at DESC LIMIT 10;"

# 看 baseline 历史
git -C ~/.unitree/g1_brain/memories log --oneline

# 看 agent 日志里的 memory 子系统轨迹
grep -E "memory|phase1|phase2|codex daemon" \
  ~/unitree/unitree-notes/g1_brain/logs/agent.log | tail -30
```

## 3.6 出问题怎么救

```bash
cd ~/unitree/unitree-notes/g1_brain

# state.sqlite 损坏 / 想清空 job 状态
python -m g1_brain.tools.reset_memory --rebuild-state

# memories/.git 损坏
python -m g1_brain.tools.reset_memory --rebuild-git

# MEMORY.md / summary / rollout_summaries 想推倒重来(stage1 在 DB 里保留,下次 Phase2 重建)
python -m g1_brain.tools.reset_memory --reset-md

# 整个核弹清空(慎重,要传两次 --confirm)
python -m g1_brain.tools.reset_memory --nuke --confirm --confirm
```

常见症状对照:

| 现象 | 原因 | 修法 |
|---|---|---|
| `codex daemon dead after 5 attempts` 在 agent.log | codex 没登录 / binary 在别处 | `codex login` 后重启 agent |
| ask_slow_brain 总返回 `quota_exhausted` | 订阅额度用尽 | 等 30min 冷却,或换账号 |
| ask_slow_brain 总返回 `queue_full` | 同时太多 LLM 调,设计默认上限 2 | 改 `memory.ask_queue_max` |
| Phase1 jobs 卡在 `failed` | 看 `last_error`,通常是 JSON parse 失败 | 通常自愈,持续失败时 `--rebuild-state` |
| 想关掉 memory 跑老路径 | — | `memory.enabled: false` 改回 |

## 3.7 验证一切就绪

```bash
# 所有测试绿(不烧订阅,codex subprocess 全 mock)
cd ~/unitree/unitree-notes/g1_brain
~/miniforge3/envs/agi/bin/python -m pytest tests/ \
  --ignore=tests/manual -q
# 预期: 416 passed
```


# 4. WSL2 下用 `run_sim.sh` 替代手动 export

前面 §1 / §2 / §3 终端 1 那一坨 `export MESA_LOADER_DRIVER_OVERRIDE=...` 现在不用手敲了 —— `unitree_mujoco/simulate_python/run_sim.sh` 把它们打包好了，并且额外加了三条 WSL2 卡顿缓解的环境变量。

## 4.1 新的启动方式

**终端 1（sim）：**

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

**终端 2（agent）：** 一字不变。

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a            # OPENAI_API_KEY etc.
python -m g1_brain.apps.agent_main --mode confirm
```

顺序还是「先 sim 再 agent」—— agent 启动会立刻去 DDS 上找机器人状态，sim 没起的话第一帧就拿不到数据。

## 4.2 `run_sim.sh` 里装了什么

脚本最后一行 `exec python unitree_mujoco.py "$@"` 才是真正干活的，前面全是 `export`。两组：

**第一组：原本要手 export 的（和 §1 / §3 终端 1 完全一致）**

```
MESA_LOADER_DRIVER_OVERRIDE=d3d12
GALLIUM_DRIVER=d3d12
MESA_D3D12_DEFAULT_ADAPTER_NAME=NVIDIA
LIBGL_ALWAYS_SOFTWARE=0
MUJOCO_GL=glfw
```

没这组会落到 llvmpipe CPU 软渲染，viewer 真卡。

**第二组：本轮新加的 WSL2 viewer 卡顿缓解**

```
vblank_mode=0          # 关掉 Mesa 侧 vsync，避免和 WSLg 的 compositor pacing 叠两层
mesa_glthread=true     # GL 命令在 Mesa 工作线程提交，viewer.sync() 返回更快
LP_NUM_THREADS=4       # 限制 Mesa 内部线程，不和 agent 抢核
```

A/B 实测把 `viewer.sync()` 的 p99 / max 从 ~10 ms 降到 ~6 ms（**中位数没变，砍的是尾延迟** —— 这正是肉眼感知的「卡顿」对应指标）。完整诊断在 `g1_brain/docs/performance-optimization-GPU.md §5`。

## 4.3 和之前手动跑相比，功能有没有缺？

**没有功能缺失。** sim 进程在功能上和你之前 `python unitree_mujoco.py` 完全等价：

- 同一个 viewer 窗口（`7` 放下 / `9` 松吊带 / `Backspace` 重置都一样）
- 同一套物理、同一份 DDS 输出
- `exec` 替换进程，Ctrl-C 行为一致
- 透传命令行参数（`./run_sim.sh --foo` 原样传给 python）

只有三个细节值得明确：

1. **物理频率没动，只是 viewer 重绘变慢了**
   `config.py` 里 `VIEWER_DT` 从 0.02 → 0.033 是**viewer 窗口的重绘周期**，不是物理频率。`SIMULATE_DT = 0.005`（200 Hz）没变。
   - agent 收到的关节状态、IMU、相机数据完全没变频，DDS 那侧无感知
   - 唯一变化：viewer 画面从「目标 50 fps、实际 25–50 跳变」→ 「目标 30 fps、稳定 ~30」
   - 装好 §5.4 的 Windows 端设置后想恢复 50 fps，改 `config.py` 里 `VIEWER_DT = 0.02` 即可

2. **`mesa_glthread=true` 是新引入的**
   对 MuJoCo viewer 这种单线程 GL 调用模式安全；但如果**画面出现纹理错乱、几何丢失、闪烁**，注释掉脚本里那一行。这种 bug 是状态依赖的，可能在长跑 / 切场景时才冒出来。

3. **脚本不替你做两件事**
   - 不激活 conda — 必须先 `conda activate agi`
   - 不 cd — 必须先 `cd` 到 `simulate_python/`，否则 `python unitree_mujoco.py` 找不到文件

## 4.4 §1 / §2 / §3 怎么对接

把上面三章里**终端 1 的所有内容**（从 `export ...` 到 `python unitree_mujoco.py`）替换成：

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
./run_sim.sh
```

其它终端（agent / teleimager / estop / va_demo 主进程）都不变。


# 5. mujoco跑 phone bridge (Twilio + Realtime)

通过电话遥控机器人。打通后的流程：你拨打 Twilio 号码 → Twilio Media Streams 走反向隧道 → 落到本机 `g1_brain/phone/bridge_server.py` → 桥接到 OpenAI Realtime → 模型听懂你说的话 → 调用 `gesture` / `walk` / `stop` 等工具 → 现有的安全监督 + 视觉风险门 + SkillServer → DDS → MuJoCo 里的 G1 真的动。

详细设计在 `mcp_twilio_design.md`，实现计划在 `docs/superpowers/plans/2026-05-24-twilio-phone-bridge.md`，VPS 反向隧道在 systemd-user 单元 `sparkytun-tunnel.service` 已常驻。

## 5.1 一次性准备（只做一次）

```bash
# 1. .env 里写好 Twilio + 公网桥 URL（gitignored）
cd ~/unitree/unitree-notes/g1_brain
# 把 TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM_NUMBER /
# PUBLIC_BRIDGE_URL / PHONE_ALLOWED_CALLERS 写入 .env
# 参考: g1_brain/.env.example

# 2. 验证 Twilio 凭据
set -a; source .env; set +a
python -m g1_brain.phone.call_me --dry-run
# 期望: Twilio credentials valid; account: <你的账号 friendly name>

# 3. 验证反向隧道常驻
systemctl --user is-active sparkytun-tunnel    # 应输出 active
curl -i https://twilio.openproduct.cn/healthz  # 桥未跑时返回 502（正常）
```

## 5.2 启动顺序

需要 3 个终端（estop 可选第 4 个）。**电话场景下 `--mode active` 是强制的**——你在打电话，没法去敲终端按 y/N，所以 confirm 模式无法用；安全靠 §10 的 Rule 12 (vision_risk_gate) 兜底。

### 终端 1 — MuJoCo 仿真

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
```

viewer 弹出后：按 `7` 把 G1 放下，按 `9` 松开 elastic band。看到 G1 站稳即可。

### 终端 2 — E-stop listener (recommended but optional)

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
```

`ESC` 触发 E-stop，触发后任何动作 tool 都会被 Rule 11 拒绝，模型会通过电话告诉你「Emergency stop engaged」。

### 终端 3 — brain + phone bridge (the full pipeline)

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active
```

等到看到这两行才往下走：

```
... INFO g1_brain: combo policy active
... INFO g1_brain: phone bridge listening on 127.0.0.1:8787
```

注意 `phone bridge listening` 那行在所有 perception/yolo/vision-gate 初始化完成之后才出现，从 `python ...` 按下回车到桥真正监听大约 60 秒。在这之前打电话，Twilio 会 502 然后 1 秒挂断。

## 5.3 发起电话

两种方式，任选其一。

### 方式 A — CLI 直接拨号

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.phone.call_me
# 默认拨 PHONE_ALLOWED_CALLERS[0]；也可显式 --to +61...
```

输出 `call placed; CallSid=CA...; To=+61...` 之后约 3 秒手机响铃。

### 方式 B — 本地说 "Hi Sparky, call me"

T3 已经在跑，话筒打开。说 "Hi Sparky"，等到日志出现 `wake heard`，然后说 "call me"（或 "给我打电话"）。本地 Realtime 看到 `start_phone_call` 工具，调用它 → 自动选 `PHONE_ALLOWED_CALLERS[0]` 拨号。

**安全注意**：模型只能拨 `PHONE_ALLOWED_CALLERS` 白名单里的号码——这是 2026-05-24 一次事故后加的硬门，那次 wake-word ASR 把 `+6848` 听成 `+6888`，结果给一个澳洲陌生人拨了 3 分钟电话。现在即使 ASR 出错，dial 也会被 SkillServer 拒掉并返回 `not in allowed callers`。

## 5.4 通话中

接听后直接说话，**不需要唤醒词**——电话 session 是独立的 Realtime context，server VAD 自动处理 turn-taking。

| 你说 | 期望听到 / 看到 |
|---|---|
| (接通后第一句) | "Hi, this is Sparky. What would you like me to do?" — 英文 |
| "Wave your right hand" | 模型说 "Waving my right hand now"，MuJoCo 里 G1 右手挥动 |
| "Walk forward one step" | 模型说 "Walking forward"，G1 迈步 |
| "Stop" | 模型说 "Stopping"，G1 立即停下 |
| "Goodbye" | 模型调用 `end_call`，电话挂断 |

T3 日志里看：

```
... phone: start streamSid=MZ... callSid=CA... bsid=...
... openai.session.updated
... tool: gesture(name="wave_right")
... safety.check pass
... vision_gate.review: SAFE
... skill.execute → {"ok":true,"summary":"..."}
... [assistant] Waving my right hand now.
... twilio.stop received
... phone: lease released
```

## 5.5 故障排查

| 症状 | 第一时间检查 |
|---|---|
| 拨号成功但 1 秒挂断（"click"）| T3 还没打印 `phone bridge listening`；桥没起来。等到那行再拨。 |
| 电话响 → 接通 → 听到一段 Twilio 自动留言 "by upgrading to a full account, press any key to execute your code" | Twilio 处于 Trial 模式，每次外拨都加 preroll。按任意键跳过；升级账号后消失。 |
| 接通了但 Sparky 说的不是英文也不是中文 | 检查 T3 日志 `[assistant]` 行看模型说了什么。`PHONE_CALL_PREAMBLE` 已经 pin 了语言（caller 用什么语言就回什么，默认英文）；如果还跑偏，加强 prompt。 |
| 拨号返回 `401 Authenticate` | API Key 失效或 Account SID/Auth Token 不匹配。`TwilioDialer._auth()` 默认用 Account SID + Auth Token；改成 API Key 看注释。 |
| 拨号返回 `21219 unverified number` | Twilio Trial 账户只能拨 verified 号码。去 console → Phone Numbers → Verified Caller IDs 加号码（或升级账号）。 |
| Tool call 后机器人没动，模型说 "I can't" | `safety.vision_gate.enabled` 必须 true（fail-closed）。`safety/supervisor.py` 的 `ALLOWED_TOOLS_*` 白名单必须包含该 tool。检查 T3 是否打印了 `vision_gate.review: RISK: ...`。 |
| 通话中我说话模型没反应 | `cancel_in_flight` 已经 gated 在 `_current_response_id` 非空时才发；如果还是有 `response_cancel_not_active` 错，看 OpenAI Realtime WS 状态。或 server VAD threshold 太高，调 `_session_update` 里的 0.5。 |
| 模型自己挂断后 lease 没释放 | bridge_server 的 finally 块永远会 release lease + defensive `stop()`；如果真的卡住，看 `/tmp/g1_brain_voice_lease` JSON。 |

## 5.6 关掉电话桥（保留 brain 本地话筒）

按 Ctrl+C 停 T3。隧道（`sparkytun-tunnel.service`）继续在后台跑——下次 T3 起来时桥立刻又通。要彻底停隧道：

```bash
systemctl --user stop sparkytun-tunnel
# 永久禁用:
systemctl --user disable --now sparkytun-tunnel
```
