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


