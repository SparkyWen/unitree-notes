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


# 6. Fleet 指挥中心（read-only 底座）

跨机的 AI coordinator 第一切片：在 N 台 headless `g1_brain` harness 之上叠一个**只读**指挥控制面（统一状态 + 语义感知聚合 + 事件日志/replay）。**本切片 coordinator→电机零路径**——所有机器人控制仍只经各机本地 `SkillServer → SafetySupervisor`，这里只收遥测、不下发命令。

设计在 `docs/superpowers/specs/2026-06-06-fleet-foundation-design.md`，实现计划在 `docs/superpowers/plans/2026-06-06-fleet-foundation.md`。代码全在 `g1_brain/g1_brain/fleet/`。

## 6.1 现状边界（重要，先读）

当前**可独立运行**的只有 coordinator + 只读 API + console：

- `python -m g1_brain.fleet.coordinator` —— 起 aiohttp 服务，挂 `/fleet`（WS 上行入口）+ 只读 HTTP API。
- `python -m g1_brain.fleet.console.cli` —— 拉 API 打印 fleet 状态。

**还没有独立的 robot-agent 进程**：`RobotAgent`（`g1_brain/fleet/agent/robot_agent.py`）目前是一个库类（由测试装配 `HarnessCore` + `WsFleetClient` 注入驱动），还没有 `__main__`。把真实 `HarnessCore`（复用 `agent_main` 的 DDS/combo/perception 初始化、跳过快慢脑）接到 FleetBus 上的"headless 车队机进程"是**下一切片**。

所以：单跑 coordinator 时没有机器人接入，`GET /robots` 返回 `[]`。要看到机器人/感知/replay 真数据，目前走 §6.4 的端到端测试（两台真 robot-agent 打到真 coordinator）。

## 6.2 启动 coordinator

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.coordinator --host 0.0.0.0 --port 8090 --db logs/fleet/fleet.sqlite
```

- `--db` 是 append-only 事件库（sqlite WAL + 同名 `.jsonl` 镜像）；replay 从这里读。
- 不需要 `.env`（这一层不碰 OpenAI / Twilio）。
- 端口默认 8090。

## 6.3 只读 API 与 console

另开一个终端查状态：

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain

# 轻量 console（拉 /robots + /perception 打印一屏）
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090

# 或直接打 API
curl -s http://127.0.0.1:8090/robots            | python -m json.tool
curl -s http://127.0.0.1:8090/robots/g1-sim-01  | python -m json.tool
curl -s "http://127.0.0.1:8090/events?robot_id=g1-sim-01&limit=50" | python -m json.tool
curl -s http://127.0.0.1:8090/replay/<trace_id> | python -m json.tool
curl -s http://127.0.0.1:8090/perception        | python -m json.tool
```

只读路由（无任何 POST/PUT/DELETE，无命令/派发路由）：

| 路由 | 含义 |
|---|---|
| `GET /robots` | 全队 {robot_id, status(online/stale/offline), capabilities, 最新 state} |
| `GET /robots/{id}` | 单机；未知 id 返回 404 |
| `GET /events?robot_id=&trace_id=&since=&until=&limit=` | 事件查询（按 ts 升序） |
| `GET /replay/{trace_id}` | 按 trace_id 回放整条时间线 |
| `GET /perception` | 车队感知 roll-up（reporting / path_blocked / with_humans） |
| `GET /fleet` (WS) | **上行**入口：robot-agent 发 REGISTER/HEARTBEAT/EVENT，coordinator 只回 PONG |

## 6.4 端到端验证（当前没有 agent 进程，用测试当 proof）

fleet 全套测试（真 aiohttp server + 真 WS client + 两台真 `RobotAgent`，含注册→心跳→感知事件→API 可见→replay 一致）：

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
~/miniforge3/envs/agi/bin/python -m pytest tests/fleet/ -v
# 预期: 40 passed
```

> ⚠️ fleet 这一层用的是 `agi` 环境（有 `aiohttp` / `pydantic`）；`unitree` 环境没装 aiohttp，跑 fleet 测试会 ImportError。

## 6.5 下一切片（已落地 → 见 §7）

read-only 底座之上的**闭环智能调度**切片已经实现：命令下行链路（`CommandEnvelope`）+ 每机本地 `AdmissionGate`（最终否决权）+ coordinator 自主异常感知（电池过热等）→ 安全休眠 → 任务接替，以及人类自然语言/命令派发。运行方式与两台 G1 在 MuJoCo 中的统一调度验证见 **§7**。

---

# 7. Fleet 智能调度（closed-loop 闭环：感知异常 → 安全休眠 → 任务接替）

§6 的只读底座之上叠的闭环切片：AI 指挥调度中心读每台机器人的真实关节/传感遥测，**自主**发现异常（电池过热、电机过热、跌倒、低电量、失联），把高温机器人**安全休眠**，再把它的任务**接替**给健康机器人；也支持**人类命令**驱动多机协作。

不变的安全原则（与 §6 一致，强化）：

- **coordinator 永不直控电机**：它只发 typed `CommandEnvelope`（能力/任务级），机器人本地快慢脑执行。
- **本地最终裁决**：每机 `AdmissionGate`（快脑）可拒绝任何中心命令；安全休眠/急停是**确定性**的，不由 LLM 决定。
- **每台机器人保留自己的快慢脑**：快脑＝`RobotFsm`（新增 `DORMANT` 态）+ 看门狗 + admission gate；慢脑＝`LocalPlanner`（能力→姿态技能），可选叠加 LLM 解释。
- **确定性引擎是最终调度权威**：`AnomalyDetector`（带迟滞）+ `DispatchEngine`（按能力/健康/电量分配）；LLM 只做自然语言解析 + 决策解释，且每个 op 都被重新校验，无 API key 时自动回退到命令语法。

设计文档 `docs/superpowers/specs/2026-06-06-fleet-coordinator-dispatch-design.md`，计划 `docs/superpowers/plans/2026-06-06-fleet-coordinator-dispatch.md`。代码全在 `g1_brain/g1_brain/fleet/`（contracts/bus/agent/coordinator/console/sim）。

## 7.1 一键验证：两台 G1 在 MuJoCo 中统一调度（推荐先跑这个）

**全自动 headless 验证**——两个真实 MuJoCo G1 物理世界 + 完整调度栈，单进程跑完整闭环（自主过热→休眠→接替 + 人类 wake+takeover），并自检打印 `ALL CHECKS PASSED`：

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
MUJOCO_GL=egl python -m g1_brain.fleet.sim.scenario_two_g1 --inject-after 1.0
```

预期结尾：

```
=== VERIFICATION ===
  [PASS] overheated <robot> put to sleep (DORMANT)
  [PASS] <robot> in SLEEP posture
  [PASS] task t1 reassigned to <other>
  [PASS] <other> now patrolling
  [PASS] both G1s upright in MuJoCo throughout
  [PASS] <robot> woke on human command
  [PASS] task handed back to original robot
  [PASS] anomaly_detected / task_reassigned / robot_sleeping event logged
=== ALL CHECKS PASSED ===
```

> 两台 G1 各跑在独立的 `MujocoG1` 物理世界（真实 `mj_step`，弹性带 + PD 维持直立），harness 直接读 `mj_data` 的真实关节力矩 `tau` 喂热模型——`MUJOCO_GL=egl` 走离屏渲染，无需显示器。电池/电机温度 MuJoCo 不建模，由热模型从真实 `tau` 合成 + `inject()` 钩子确定性触发过热。

同样的场景被包进测试做回归（无 MuJoCo/资产时自动跳过）：

```bash
MUJOCO_GL=egl ~/miniforge3/envs/agi/bin/python -m pytest tests/fleet/test_scenario_two_g1.py -v
```

## 7.2 纯 Python 闭环证明（Tier-1，CI 永远绿，无需 MuJoCo）

确定性证明整条调度逻辑（过热→异常→休眠→接替→人类协作），用事件日志回放断言顺序：

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
~/miniforge3/envs/agi/bin/python -m pytest tests/fleet/ -q
# 预期: 全绿（135 passed，含 Tier-1 e2e + Tier-2 mujoco 场景）
```

## 7.3 coordinator 调度路由（在 §6.2 起的服务上）

`python -m g1_brain.fleet.coordinator` 起的服务现在除了 §6.3 的只读路由，还有调度面：

| 路由 | 含义 |
|---|---|
| `POST /missions` | 提交 `Mission`（含 `TaskSpec` 列表）→ 按能力/健康分配 |
| `POST /commands` | 操作命令：`{"op":"sleep","args":{"robot":"g1_a"}}` / `wake` / `{"op":"takeover","args":{"from":"g1_a","to":"g1_b"}}` / `{"op":"dispatch","args":{"task":"patrol"}}`；自然语言：`{"nl":"sleep g1_a"}`；注入（仿真/调试）：`{"op":"inject","robot":"g1_a","battery_temperature_c":75.0,"fault":"battery_hot"}` |
| `GET /anomalies` | 最近一次 tick 感知到的异常 |
| `GET /dispatch` | 当前分配 + needs_operator + 租约 |

后台 tick 每 1s 自动 `scan → 处理异常 → 派发`（`tick_interval_s`，可在 `build_coordinator_app` 调）。

### 浏览器仪表盘（GET /）

coordinator 在根路径 `GET /` 提供一个自带网页(纯前端,无新依赖,每秒自动刷新):
- **每台机器人一个实时小人图**(姿态驱动:站立 / 巡逻挥臂动画 / 过热坐下,颜色随健康/电池变)——**不开 MuJoCo 窗口也能直接在浏览器里看到每台在干什么**;
- **实时事件流**(anomaly_detected → command_issued → task_reassigned → robot_sleeping …,带时间戳);
- 任务分配、异常、命令按钮(派发 / 休眠 / 唤醒 / **🔥注入过热**——按钮经 DDS 下发到机器人节点,真实触发过热→休眠→接替)。

> 想看**真实 3D 物理画面**(机器人在地面/弹性带上的真实动作),那是 §7.5 的 MuJoCo GUI 窗口;浏览器仪表盘看的是**示意小人 + 调度状态 + 实时事件**。两者互补:不想折腾 GUI 就只看浏览器(小人 + 事件流已足够判断"实时在执行什么");想看物理本体再开 §7.5 的窗口。

**最省事:一条命令起整套(coordinator + 2 台 G1)并常驻,然后开浏览器看 + 用按钮指挥:**

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.verify_dds_fleet --keep-alive
# 它会打印要打开的 URL(含 WSL2 IP 兜底);两台 g1_a/g1_b 在线,Ctrl-C 停止
```

启动时 coordinator 会**打印可访问 URL**(含 WSL2 IP),照着 Windows Chrome 打开即可。

> ⚠️ **`0.0.0.0` 不是用来打开的**:它是服务端*监听*地址。浏览器要连 `http://localhost:8090` / `http://127.0.0.1:8090`。
>
> #### WSL2 网络排查(localhost / 127.0.0.1 都打不开时)
> 服务在 WSL2 里 100% 正常(`0.0.0.0:8090`)、从 WSL2 内 curl 能通,但 Windows 的 Chrome 连不上 —— 这是 **WSL2→Windows 端口转发**问题,按顺序试:
> 1. **用 WSL2 IP 直连**(最快兜底,启动 banner 会打印):`http://<WSL2_IP>:8090`(本机当前 `192.168.108.252`,每次重启会变;查:WSL 里 `hostname -I`)。NAT 模式下 Windows 有 `vEthernet (WSL)` 网卡可直达该 IP,绕过 localhost 转发。
> 2. **重启 WSL 的 localhost 转发**:Windows PowerShell 跑 `wsl --shutdown`,再重开 WSL + 重新起 coordinator。睡眠/VPN/网络切换后转发常失效,重启即恢复。
> 3. **`.wslconfig` 固定 NAT + localhost 转发(已为本机配置好)**:已写入 `C:\Users\Helios\.wslconfig`:
>    ```ini
>    [wsl2]
>    networkingMode=nat
>    localhostForwarding=true
>    ```
>    **生效一次**:Windows PowerShell 跑 `wsl --shutdown`,等约 10 秒,重开 WSL 终端,再起 coordinator。之后 Windows Chrome 用 `http://localhost:8090` 经 WSL2 自动 localhost 转发直达(coordinator 须监听 `0.0.0.0:8090`)。
>    > 注:曾试过 `networkingMode=mirrored`(Windows localhost == WSL2 localhost,最干净),但**镜像模式要求 Windows 11 22H2 / build 22621+**;本机是 Windows 10 22H2 / build 19045,WSL 启动会报 `Mirrored networking mode is not supported ... Falling back to NAT networking` 并回退 NAT。故显式写 NAT 以消除该启动警告;等升级 Win11 后可再改回 mirrored。
> 4. **VPN / 防火墙**:部分 VPN 会劫持 WSL 子网路由;Windows Defender 防火墙可能拦入站。临时关 VPN 或放行 `vEthernet (WSL)` 验证。
> 5. **确认服务真在跑**:`verify_dds_fleet`(不带 `--keep-alive`)跑完会**拆掉所有进程**,端口随之关闭——要看实时画面用 `--keep-alive` 或单独常驻 `python -m g1_brain.fleet.coordinator`。WSL 里自检:`curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8090/` 应为 `200`。
>
> 另外:3D 机器人画面在 **MuJoCo 窗口**里(§7.5),浏览器仪表盘看的是车队**状态/遥测/指挥**。

## 7.4 操作员 console

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 status        # 全队 + 异常 + 分配 + 租约
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 dispatch patrol
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 inject g1_a --temp 75
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 sleep g1_a
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 wake g1_a
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 takeover g1_a g1_b
```

## 7.5 GUI 双进程：在 MuJoCo 窗口里看到两台 G1（真实 DDS 路径）

§7.1 是 headless 直连物理（自动验收基线）。要**亲眼看到**两台 G1 并被指挥调度,走 **DDS 双进程**路径(每进程一个 DDS 域,`config.py` 支持 `UNITREE_DOMAIN_ID` 覆盖)。拓扑:`2 个 GUI sim 窗口 + 2 个 robot 节点 + 1 个 coordinator`,全部经真实 DDS(`rt/lowstate`/`rt/lowcmd`)。

```bash
# 终端 1 — coordinator (悬挂机器人会摆动, 放宽 fall 阈值避免误判)
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
FLEET_FALL_GZ=2.0 python -m g1_brain.fleet.coordinator --port 8090 --db logs/fleet/g.sqlite

# 终端 2 — G1 #1 GUI 窗口 (domain 1)
conda activate unitree && cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
UNITREE_DOMAIN_ID=1 MUJOCO_GL=glfw python unitree_mujoco.py
# 终端 3 — G1 #2 GUI 窗口 (domain 2)
conda activate unitree && cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
UNITREE_DOMAIN_ID=2 MUJOCO_GL=glfw python unitree_mujoco.py

# 终端 4 — robot 节点 g1_a (domain 1), 14s 后自发电池过热
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.robot_node --robot-id g1_a --domain 1 \
  --coordinator ws://127.0.0.1:8090/fleet --inject-overheat-after 14
# 终端 5 — robot 节点 g1_b (domain 2)
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.robot_node --robot-id g1_b --domain 2 \
  --coordinator ws://127.0.0.1:8090/fleet

# 终端 6 — 操作员: 派发巡逻 + 看状态
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 dispatch patrol
python -m g1_brain.fleet.console.cli --base http://127.0.0.1:8090 status
```

会看到:两台 G1 在各自窗口里站立(弹性带悬挂,可按 `8` 放低着地、`9` 关弹性带);派发后持有者做巡逻动作;14s 后 g1_a 电池过热 → coordinator 自动让 g1_a 阻尼坐下(SLEEP/DORMANT) → 把巡逻接替给 g1_b。也可手动 `inject g1_a --temp 75` / `sleep` / `wake` / `takeover g1_a g1_b`。

**一键验证整条 DDS 路径(无需 GUI 窗口,自动起 headless sim + 节点 + coordinator 并自检):**

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.verify_dds_fleet
# 预期结尾: === ALL CHECKS PASSED ===  (g1_a 过热休眠 → 任务接替给 g1_b, 全程真实 DDS 遥测)
```

> 说明:(1) DDS `ChannelFactoryInitialize` 是进程级单例(一进程一域),故双机=双进程双域。(2) GUI sim 用弹性带悬挂保持直立(无平衡策略),姿态切换时机身会摆动——这不是真实跌倒,所以 GUI/DDS 演示用 `FLEET_FALL_GZ=2.0` 放宽跌倒检测;真实自平衡机器人保留默认阈值。(3) `headless_sim` 与 GUI `unitree_mujoco.py` 是同一 DDS 契约,只差一个窗口——所以 `verify_dds_fleet`(headless)证明的就是 GUI 路径的数据面。

## 7.6 关键文件地图

| 文件 | 职责 |
|---|---|
| `fleet/contracts/models.py` | `CommandEnvelope`/`AdmissionDecision`/`TaskSpec`/`Mission`/`ReplanProposal` + `Battery`/`Health` 遥测 + 调度事件类型 |
| `fleet/bus/{messages,ws_server,ws_client,loopback}.py` | 双向总线：`COMMAND` 下行 / `ADMISSION` 上行；per-robot 路由；in-process loopback |
| `fleet/agent/admission_gate.py` | 快脑本地准入（TTL/幂等/能力/FSM 合法性，可拒绝） |
| `fleet/agent/local_planner.py` | 慢脑能力→姿态技能映射 + 生命周期事件 |
| `fleet/agent/thermal_model.py` | 由真实 `tau` 合成电池/电机温度 + SOC + `inject()` 钩子 |
| `fleet/agent/sim_harness.py` | 组装快慢脑的 `SimRobotHarness`（即 RobotAgent 的 core） |
| `fleet/agent/motion/{base,mock,mujoco_backend,dds_backend}.py` | 可插拔运动后端（mock / 真实 MuJoCo 直连 / DDS 桥接 GUI sim） |
| `fleet/coordinator/{anomaly,dispatch,lease,gateway,controller,agent_llm,app}.py` | 异常感知 + 确定性调度 + 租约 + 命令网关 + 编排 + 可选 LLM + 路由（异常阈值可经 `FLEET_*` 环境变量覆盖） |
| `fleet/sim/{mujoco_world,scenario_two_g1}.py` | headless 直连物理 G1 世界 + 两机验证场景（§7.1） |
| `fleet/sim/{g1_consts,headless_sim,robot_node,verify_dds_fleet}.py` | G1 常量 + 无窗口 sim 进程 + 单机 DDS 节点进程 + 一键 DDS 全链路验证（§7.5） |

# 8. Fleet 共享世界 + RL 真步态 + AI 指挥官（会合 / 接力 · 实时指挥中心）

§7 是"两个独立 MuJoCo 世界 + DDS 双进程"——两台机器人互相看不见。§8 是本次新增的**单一共享世界**路线：**两台 G1 在同一个 MuJoCo 世界（一个窗口）里用 RL 真步态行走、互相感知**，并由**接收自然语言的 AI 指挥官**（OpenAI 或 §8.4 的 **codex 大脑**）给每台机器人委派一个子 agent，去完成**会合 / 接力**配合。最新增的 **§8.4 AI 指挥调度中心**把这条线做成**实时交互**：浏览器打字下达 → codex 规划 → 机器人在 3D 窗口里真的动起来 → 中途可抢占（最新指令优先）。

设计文档 `docs/superpowers/specs/2026-06-07-fleet-shared-world-rl-coordinator-design.md`；计划 `docs/superpowers/plans/2026-06-07-fleet-shared-world-p1.md` + `2026-06-07-fleet-coordinator-p2.md`。

与 §7 的关键区别：

- **一个世界一个窗口**：`MjSpec.attach` 把两台 G1 合进一个 `MjModel`，真实共享物理（靠近会真碰撞）+ 邻居感知；不再是两域两窗口。
- **真步态**：移动用 RL 速度跟踪策略（复用 `g1_sim_demo` 的 `ComboController`，去 DDS 直驱），不是绑带悬吊摆姿势。
- **分层 AI 调度**：`FleetCommander`(NL→多机计划) → 每机 `RobotSubAgent`(→op 序列) → 确定性 `RendezvousBarrier`(会合同步)；无 `OPENAI_API_KEY` 自动回退确定性规划。

## 8.1 看会合 / 接力演示（推荐先跑这个）★ 新 GUI

一句自然语言 → AI 指挥官拆解 → 两个子 agent 各自规划 → 两台 G1 在**同一个窗口**里走到中间会合 → barrier 同步 → 巡逻令牌 a→b：

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.scenario_rendezvous --viewer
# 自定义指令：--nl "让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b"
```

一个 MuJoCo 窗口里能看到：两台 G1 真步态相向走到中点（保持安全间距不相撞）→ g1_b 接手开始巡逻（原地小圈）、g1_a 停下待命。

**headless 自动验收**（无窗口，CI 用，结尾打印 `ALL CHECKS PASSED`）：

```bash
MUJOCO_GL=egl python -m g1_brain.fleet.sim.scenario_rendezvous
```

预期结尾（9 项全过）：

```
[commander] 会合后交接巡逻 [relay] handoff g1_a -> g1_b
[subagent g1_a] navigate -> await_barrier -> idle
[subagent g1_b] navigate -> await_barrier -> patrol
=== VERIFICATION (rendezvous / relay) ===
  [PASS] rendezvous barrier fired (both arrived)
  [PASS] g1_b patrolling after handoff / g1_a idle / both upright / no collision
=== ALL CHECKS PASSED ===
```

## 8.2 只看共享世界本身（两台 G1 同窗行走）★ 新 GUI

不带 AI、直接看"两台 G1 在一个世界里走到中点"：

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.fleet.sim.shared_world_node --viewer
# headless 冒烟（打印两机末位姿 / gz / 间距）：
python -m g1_brain.fleet.sim.shared_world_node --seconds 9
```

> WSL2 下窗口走 WSLg 显示（与 §7.5 的 GUI 一致）。屏显 GL 默认 `glfw`；headless 用 `MUJOCO_GL=egl`。RL 策略走 `onnxruntime` CPU，无需额外 GPU。窗口打不开属显示问题（非本代码），排查思路同 §7.3。

## 8.3 AI 指挥官聊天（仪表盘 / API）

coordinator 网页（§7.3 的 `GET /`）新增 **"AI 指挥官"聊天卡**：打字下达自然语言，返回指挥官的多机计划 + 每机子 agent 的 op 序列。也可直接打 API：

```bash
curl -s -X POST http://127.0.0.1:8090/chat -H 'content-type: application/json' \
  -d '{"nl":"两机到中间会合，然后 g1_a 把巡逻交给 g1_b"}' | python -m json.tool
```

无 `OPENAI_API_KEY` 时走确定性规划器（关键词 + 快照）；设了 key 则经 OpenAI（同一 op 语法、同样校验）。

> ⚠️ 边界（已更新）：本聊天卡（§8.3，coordinator 网页）只返回**指挥官的决策（计划 + op）**，且接的是 DDS registry。要"网页打字 → 共享世界机器人真的动起来"，见下面 **§8.4 AI 指挥调度中心**——同进程把 WorldSim + 3D 窗口 + 网页 + codex 指挥官 + 抢占式执行接通了。

## 8.4 AI 指挥调度中心（实时看 + 实时下达 + 真驱动）★ 新 GUI

把 §8.3 那条"尚未接通"的线接上：**一个进程**同时起 **WorldSim（§8.2 的共享世界）+ MuJoCo 3D 窗口 + 网页控制台**，由 **codex 大脑**当指挥官。浏览器打字 → codex 规划 → 子 agent 展开 op → `LiveExecutor` **抢占式**驱动活的 WorldSim（最新指令优先），机器人在 3D 窗口里动，网页俯视图 / 遥测 / 事件流实时更新。

> 本次（`feature/multi-geo`）新增三件事，下面"网页界面 + 自然语言指令大全"会详细讲：①**自然语言位置控制**——坐标 / 命名地标 / 相对移动 / 多机一起，**不依赖 codex 也能用**；②**演示场景**——平地竞技场放了障碍物 + 一条缓地形测试带，导航**自动绕开障碍**；③**单机模式 `--solo`**——只起一台 G1，方便单独测一台的表现。`--viewer` 默认就带这个场景（`--scene demo`）。

### 关键认知（先读，省得走弯路）

**§8.4 是单一进程，自带整个世界。** 和 §7 的"6 个终端 + DDS 双进程"完全不同——这里**只需要一个终端、一条命令**。你**不需要**先做下面任何一件事：

- ❌ 不需要先起 §1 的 `unitree_mujoco.py`（它自己用 `MjSpec.attach` 现搭一个共享世界）。
- ❌ 不需要先起 §6.2 的 `coordinator`（§8.3 那条聊天卡才依赖 coordinator；§8.4 不依赖）。
- ❌ 不需要 DDS / `robot_node` / 域设置（§8.4 直驱内存里的世界，不走 DDS）。
- ❌ 不需要 `OPENAI_API_KEY` / `.env`（指挥官走 **codex**，不是 OpenAI API）。
- ❌ 甚至**不需要 codex**：**位置 / 地标 / 相对 / 多机 / 编队（绕圈·面对面·抬手）/ 会合 / 接力**这些常用指令，加 `--no-codex` 也照样能下（走进程内的确定性解析器）。**只有"任意自由句式"**才需要 codex 大脑。详见下面【网页界面 + 自然语言指令大全】。

一条命令进去，它**自己按顺序**把所有东西拉起来。

### 前提（一次性，基本都已就绪）

1. conda `agi` 环境（§1.1）。
2. `codex` 已登录（你的 ChatGPT 账号，`~/.codex/config.toml` 已配 `gpt-5.5`）。不想用 codex 就加 `--no-codex` 走确定性规划。
3. `--viewer` 要弹窗 → WSLg 显示正常（与 §7.5 / §8.2 一致）。没有显示就用 headless（见下面）。

### 启动顺序（照着做，就这几步）

```bash
# ① 开一个终端（就一个，够了）
conda activate agi && cd ~/unitree/unitree-notes/g1_brain

# ②（可选但推荐）先确认 codex 在：有就走真 AI，没有会自动回退确定性规划
which codex && codex --version

# ③ 起指挥中心（这一条命令内部按顺序自动做完 4 件事，见下）
python -m g1_brain.fleet.sim.command_center --viewer
```

`③` 这条命令**进程内部的启动顺序**（你不用管，知道在等什么即可）：

1. 起 **WorldSim**：两台 G1 进同一个 `MjModel`，拉起 **50Hz 控制线程**。终端会打印两行 `[combo] policy engaged …`（两台机器人的 RL 步态控制器就绪，**正常**）。
2. 建 **codex 指挥官**：终端打印 `[command-center] AI 大脑: codex gpt-5.5 (reasoning=xhigh)`。（没装/没登录 codex 则打印"退回确定性规划"。）
3. 在后台线程起 **网页服务**，打印 `[command-center] 控制台: http://127.0.0.1:8787/   (Ctrl-C 退出)`。
4. 在主线程**弹出 MuJoCo 3D 窗口**（`--viewer` 时）。

```bash
# ④ 等终端打印出 “控制台: http://127.0.0.1:8787/” 这一行，再用浏览器打开它
#    （服务起来才打开；端口默认 8787，可用 --port 改）

# ⑤ 在网页“AI 指挥官”框里打字下指令，回车。例：
#    让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b
#    首条指令 codex 思考约 10s（xhigh），网页会显示“指挥官思考中…”，正常等它。

# ⑥ 看效果：3D 窗口里两台 G1 真的相向走到中点会合 → g1_b 接手巡逻、g1_a 待命；
#    网页俯视图 / 遥测 / 事件流实时刷新。中途再下一条新指令 → 立刻抢占（最新优先）。

# ⑦ 退出：关掉 3D 窗口，或在终端按 Ctrl-C（两者都会停掉整个进程）。
```

> 一句话记忆顺序：**`conda activate agi` → `python -m …command_center --viewer` → 等“控制台: http://…”这行 → 开浏览器 → 打字下指令 → 看 3D 窗口里机器人动**。没有别的"先起 A 再起 B"。

### 网页界面 + 自然语言指令大全（核心：怎么用 UI 下 NL 指挥多机）

这是本节的重点——**你只在这个网页里打字，就能用自然语言指挥多台机器人**。打开 `http://127.0.0.1:8787/` 后，页面从上到下四张卡：

| 卡片 | 看什么 / 干什么 |
|---|---|
| **实时俯视图**（top-down） | 每台机器人一个**彩色圆点 + 朝向短线**；**障碍物**按真实颜色画出来（红/绿柱子、蓝/黄箱子、路障，矮墙是背景）；**地标名字**直接标在图上（集合点 / 左上角 / 右上角 / 左下角 / 右下角 / 地形测试区…）；有会合点时画虚线圈；两机之间画间距虚线。**地图上标了名字，你就能直接按名字下指令。** |
| **AI 指挥官**（说出你的想法） | **打字下自然语言指令的输入框**——回车发送。下面一行 `例 / examples` 是常用句式提示；再下面是对话记录（你说的 + 指挥官给出的计划 / 每机 op 序列）。 |
| **事件流**（调度 / 执行） | 指挥官的决策 + 执行日志逐条刷新：`指挥官: …[navigate]`、`g1_a 到位`、`会合完成`、`g1_b 接手巡逻`、`✓ 任务完成`。 |
| **遥测**（telemetry） | 每台机器人的 x / y / 朝向 / 姿态，实时表格。 |

#### 你能下哪些自然语言指令（按类别，附是否需要 codex）

直接在"AI 指挥官"框里打中文或英文，回车。**下面四类前三类离线（`--no-codex`）就能用**：

**① 位置控制（最常用·不需要 codex）**

| 想干什么 | 这样说 |
|---|---|
| 让某台走到坐标 | `g1_a 走到 2,1` ／ `g1_a go to 2,1` ／ `g1_a 去 -2 0` |
| 让某台去命名地标 | `让 g1_a 去红色柱子` ／ `g1_b 到集合点` ／ `g1_a 去左上角`（地标名字见俯视图） |
| 相对自己移动 | `g1_a 前进 2米` ／ `g1_a 后退 1m` |
| 多台一起去同一处 | `两机都去集合点` ／ `all go to center` ／ `两机都去地形测试区` |

**② 编队动作（不需要 codex）**

| 想干什么 | 这样说 |
|---|---|
| 绕圈 | `两机顺时针绕圈` ／ `逆时针绕圈 20秒`（两台会朝相反方向转） |
| 列队 / 面对面 | `两机面对面` ／ `列队` |
| 抬手 | `抬双手` ／ `举起双手` |

**③ 会合 / 接力（多机配合·确定性也懂这几句·codex 在更稳）**

| 想干什么 | 这样说 |
|---|---|
| 两机会合 | `两机到中间会合` |
| 会合后交接巡逻 | `让 g1_a 和 g1_b 到中间会合，然后 g1_a 把巡逻交给 g1_b` |

**④ 任意自由句式（需要 codex 大脑）**

codex 在线时，可以把上面的动作随意组合、用更自然的话讲（例：`g1_a 先去右上角看看，再回来和 g1_b 会合`）。`--no-codex` 时只认上面①②③那些固定句式，认不出的会回 `无法执行 / 需要澄清`。

#### 怎么分别指一台 vs 一起指多台

- **指定某台**：句子里写出机器人名 `g1_a` / `g1_b`（如 `g1_a 走到 2,1`，只动 g1_a）。
- **一起指**：用"两机 / 都 / 全部 / all / both"（如 `两机都去集合点`，两台都动）。
- **只写一个目标、不写机器人名、又有两台** → 视为**不明确**，离线解析器**不猜**，交给会合/接力指挥官处理（避免误动一台）。单机模式（`--solo`）只有一台时，不写名字也默认就是那台。

#### 指挥官内部怎么决定（路由，知道就行）

浏览器回车 → `POST /command` → `plan_mission` 依次尝试：

1. **codex 在** → 让 codex 直接编排每机 op（最自由）；
2. 否则 → **离线位置解析**（坐标 / 地标 / 相对 / 多机 → `navigate`）；
3. 否则 → **确定性编队**（绕圈 / 面对面 / 抬手）；
4. 否则 → **会合 / 接力指挥官**（rendezvous / relay，带 barrier 同步）。

命中后交给 `LiveExecutor` **抢占式**驱动活的世界——**中途再下一条新指令会立刻接管（最新优先）**，机器人在 3D 窗口里动、俯视图 / 事件流 / 遥测同步刷新。

> **避障 ↔ 会合的小机关**：导航默认会**绕开静态障碍**（柱子 / 箱子 / 路障），也会**躲开另一台机器人**；但一旦进入**会合 / 面对面**阶段，会**自动关掉"躲另一台"**，所以两机仍能真正贴到一起完成会合。

#### 演示场景 / 障碍 / 地形（`--viewer` 默认自带）

- **默认 `--scene demo`**：一块平地竞技场，放了**走绕障碍**（红 / 绿柱子、蓝 / 黄箱子、路障；矮墙是背景）+ 一条**缓地形测试带**（沿 +X：约 10° 斜坡 + 低起伏 + 矮台阶，机器人能走上去）。
- **测单台**：加 `--solo`（只起 g1_a，网页 / 场景都一样）。例：`--viewer --solo` 后下 `g1_a 去地形测试区` 看它过斜坡、下 `g1_a 去红色柱子` 看它绕开障碍走过去。
- **回到空地板**：`--scene bare`（就是 §8.1/§8.2 那种干净平地）。
- **性能**：障碍 / 地形全是**静态基本体**（box / cylinder，**无高度场 / 网格 / 额外光源、0 自由度增加**），对 WSL2 软件渲染几乎零额外开销（实测 demo 场景 ~2ms/步，远低于 50Hz 的 20ms 预算）。

> 想要一页速查版（不含上面这些细节）：`docs/command-center-arena-how-to-use.md`。

### 常用开关

```bash
--scene demo|bare          # 竞技场场景：demo=障碍+缓地形（默认），bare=干净平地
--solo                     # 只起一台 g1_a，单独测一台机器人的表现
--no-codex                 # 不调 codex，用确定性解析（离线、最跟手；懂位置/地标/相对/多机/编队/会合接力，认不出自由句式）
--reasoning low|medium|high|xhigh   # codex 思考强度（默认 xhigh；想更跟手用 low）
--model gpt-5.5            # codex 模型（默认；codex 自带的 gpt-5.3-codex 在 ChatGPT 计划下不可用，故固定显式传 gpt-5.5）
--port 8787 --host 127.0.0.1
```

### 排查（对症）

- **不弹 3D 窗口**：显示问题（WSLg），与本代码无关；要么修显示，要么**不带 `--viewer`** 纯用网页（headless 时设 `MUJOCO_GL=egl`）。
- **浏览器打不开**：还没等到"控制台: http://…"那行就开了；或端口被占——`--port` 换一个。
- **指挥官只认固定句式（认不出自由句子）**：说明回退到了确定性解析（位置 / 地标 / 相对 / 多机 / 编队 / 会合接力都还能用，但任意自由句式不行）。想要自由句式就让 codex 上：看终端有没有 `AI 大脑: codex …`；没有就 `which codex` / 检查登录。反过来，想纯离线、最跟手，就直接 `--no-codex`。
- **下了"去某地标"却说不认识**：地标名字要和俯视图上标的一致（集合点 / 左上角 / 红色柱子 / 地形测试区…）；坐标用 `走到 2,1` 这种 `x,y`。`--scene bare` 没有任何障碍 / 地标，自然认不出地标名（用坐标即可）。
- **两机"都去同一点"却没贴在一起**：`两机都去集合点`是各自导航到同一点，避障会让它们停在约 0.7m 间距（不重叠）；想要真正贴合会合，用`两机到中间会合`（走会合 barrier，会合阶段自动关互相躲避）。
- **首条指令很慢**：codex `xhigh` 在认真思考，正常（~10s）；想跟手用 `--reasoning low` 或 `--no-codex`。

### headless 自动验收（无窗口，CI；POST 一条指令驱动真实物理跑通会合接力）

```bash
python -m pytest -m slow tests/fleet/test_command_center_e2e.py -q
```

- **AI 大脑 = codex**：`CodexFleetLLM`(gpt-5.5 + xhigh) 把自然语言拆成 FleetPlan；codex 出错 / 无 `codex` 二进制自动回退确定性规划。子 agent 始终确定性展开 op（只让 NL→计划走 codex）。
- **抢占**：机器人还在执行上一条时再下一条，最新指令立即接管（generation 计数，旧任务自停）。

## 8.5 关键文件地图（§8 新增）

| 文件 | 职责 |
|---|---|
| `fleet/sim/shared_world.py` | `MjSpec.attach` 合两台 G1 进一个 `MjModel` + 每机切片 + 每子步重算 PD + 邻居感知 + 按 `scene=` 加静态障碍/地形 |
| `fleet/sim/scene.py` | 场景注册表（单一真源）：`demo`/`bare`/`solo` 的障碍/地形几何 + 命名地标（坐标↔名字）；被世界几何 / 俯视图 / NL 解析 / codex 快照共用 |
| `fleet/sim/rl_adapter.py` | 无 DDS 复用 `ComboController`（伪 LowState 喂入 + 截获 `_publish`）跑 RL 速度策略 |
| `fleet/sim/nav.py` | 位置→速度导航外环（夹到策略命令范围防 OOD）+ 反应式避障（绕开障碍 / 另一台机器人） |
| `fleet/agent/motion/rl_shared_backend.py` | 共享世界单机 MotionBackend（导航 / PATROL 小圈 / IDLE） |
| `fleet/sim/shared_world_node.py` | World Sim 进程：50Hz 隔离控制线程 + 可选 viewer（§8.2） |
| `fleet/coordinator/{fleet_plan,fleet_commander,robot_subagent,barrier}.py` | AI 指挥官决策层：FleetPlan + NL 拆解(OpenAI+回退) + 每机子 agent + 确定性会合 barrier |
| `fleet/sim/scenario_rendezvous.py` | 端到端会合/接力编排 + 验收（§8.1） |
| `fleet/coordinator/app.py` `POST /chat` | 仪表盘/接口的分层调度入口（§8.3） |
| `fleet/sim/command_center.py` | AI 指挥调度中心：WorldSim + 3D 窗口 + 网页控制台 + codex 指挥官 一键起（§8.4） |
| `fleet/sim/live_executor.py` | 抢占式 op 执行器（最新指令优先），驱动活的 WorldSim（§8.4） |
| `fleet/coordinator/codex_fleet_llm.py` | 把 codex 大脑接成 FleetCommander 的 LLM（`plan_fleet`，gpt-5.5 + xhigh） |
| `fleet/coordinator/nl_position.py` | 离线 NL→位置解析（坐标/地标/相对/多机→`navigate`）；遇编队/会合/接力词回退给指挥官；让位置控制**不依赖 codex** |
| `fleet/coordinator/choreographer.py` | NL 路由 `plan_mission`：codex → 离线位置解析 → 确定性编队 → 会合/接力指挥官 |
| `fleet/sim/command_center_ui.py` | 控制台网页：实时俯视图（含障碍/地标）+ 聊天（含例句提示）+ 事件流 + 遥测 |

> 关键工程点：RL 速度策略在自写 MuJoCo 循环里驱动时，**PD 力矩必须每个物理子步（200Hz）用最新 q/dq 重算**，不能每 50Hz 控制 tick 只设一次——否则力矩过时 → 振荡 → 摔倒。这是机器人从"乱飞"到"稳步行走"的分水岭。
