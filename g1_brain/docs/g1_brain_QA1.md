# g1_brain — QA round #1

针对 [`docs/how_to_run.md`](how_to_run.md) 的几个深入疑问，写在一起方便以后回头查阅。

> 环境前提：所有 `agi` 操作均假设你已激活 conda 环境
> `conda activate agi` （Miniforge，路径 `~/miniforge3/envs/agi`，
> Python 3.11.15）。

---

## Q1 — 为什么 `agi` 已经有 `unitree_sdk2py / mujoco / openai / sounddevice / …` 了，还要 `pip install -e .`？

### 1.1 「装依赖」 vs 「装 g1\_brain 自己」是两件事

`pyproject.toml` 里写的 `dependencies = [...]` 只是 g1\_brain 这个包**所需要的第三方依赖**。`pip install -e .` 做了两件不同性质的事：

1. **解析并安装 `dependencies` 列表里缺失的包**（比如本次新装的 `ultralytics` 和 `mediapipe`）。
2. **把 `g1_brain` 这个 *本地源码包* 自己注册进当前 Python 环境的 `site-packages`**，让任何地方运行 `python -m g1_brain.apps.agent_main` 都能 `import g1_brain.*`。

第二件事是关键。`/home/helios/unitree/unitree-notes/g1_brain/g1_brain/` 是一个普通目录，Python 默认看不到。安装之后，`agi` 的 site-packages 里会出现一个 `.pth` 文件（或 `__editable__.g1_brain-0.1.0.pth`），里头一行写着：

```
/home/helios/unitree/unitree-notes/g1_brain
```

这一行就让 Python 解释器把这个目录加入 `sys.path`，于是 `import g1_brain` / `python -m g1_brain.apps.*` 才会工作。

### 1.2 为什么用 `-e`（editable）而不是普通 `pip install .`

- 普通 `pip install .` 会把 `g1_brain/` 复制到 `site-packages/g1_brain/`，之后**改源码**不会生效，必须重装。
- `pip install -e .` （editable / develop install）只放一个指针指回原目录，**改一行代码立即生效**。
- 你正在边写边调（比如改 `safety/supervisor.py` 测试），用 `-e` 是正确的选择。
- 跟你 `agi` 里已经存在的几个 editable 包是同一种安装方式：

  ```text
  dex_retargeting       0.4.7   /home/helios/unitree/unitree-notes/xr_teleoperate/teleop/robot_control/dex-retargeting
  teleimager            1.5.0   /home/helios/unitree/unitree-notes/teleimager
  televuer              4.0.0   /home/helios/unitree/unitree-notes/xr_teleoperate/teleop/televuer
  unifolm_vla           0.0.1   /home/helios/unitree/unitree-notes/unifolm-vla
  unitree_rl_mjlab      0.0.1   /home/helios/unitree/unitree-notes/unitree_rl_mjlab
  unitree_sdk2py        1.0.1   /home/helios/unitree/unitree-notes/unitree_sdk2_python
  ```

### 1.3 那 `va-demo` / `g1_sim_demo` 为什么没装？

g1\_brain **运行时通过 `sys.path.insert(...)` 临时把它们加进路径**（见 `apps/agent_main.py` 中的 `_ensure_sibling_repos_on_path()`），不走 pip。这是设计选择：那两个仓库是 sibling repo，不愿污染 site-packages。所以**只有 `g1_brain` 这一个新包需要 `pip install -e .`**。

---

## Q2 — `agi` 环境里还少哪些包？是否兼容？

### 2.1 比对结果（`pyproject.toml` + `requirements.txt` vs `pip list`）

| 依赖 | `pyproject` 要求 | `agi` 中现状 | 结论 |
| --- | --- | --- | --- |
| `ultralytics` | `>=8.3` | **缺失** | 新装 |
| `mediapipe` | `>=0.10` | **缺失** | 新装 |
| `pynput` | `>=1.7` | 1.8.1 | OK |
| `pyyaml` | `>=6.0` | 6.0.3 | OK |
| `numpy` | `>=1.24` | 1.26.4（agi memory 锁定） | OK，不可升 |
| `opencv-python` | `>=4.8` | 4.11.0.86 → **被 `opencv-contrib-python` 取代**（同版本号） | 见 §2.3 |
| `openai` | `>=1.30` | 2.33.0 | OK |
| `websockets` | `>=12` | 16.0 | OK |
| `sounddevice` | `>=0.4` | 0.5.5 | OK |
| `webrtcvad` | `>=2.0` | `webrtcvad-wheels 2.0.14` | OK（同 import name） |
| `torch` (req.txt) | `>=2.1` | 2.11.0+cu130 | OK |
| `torchvision` (req.txt) | `>=0.16` | 0.26.0+cu130 | OK |
| `transformers` (mono\_depth opt) | `>=4.40` | 4.52.3 | OK（默认用不到） |
| `accelerate` (mono\_depth opt) | `>=0.30` | 1.5.2 | OK（默认用不到） |
| `pytest` / `pytest-asyncio` | `>=7 / >=0.21` | 9.0.3 / 1.3.0 | OK |

### 2.2 兼容性陷阱（已规避）

- `ultralytics 8.4.x` 的依赖声明里 `numpy>=1.23.0` **没有上限**。如果不显式 pin，pip 会把 numpy 升到 2.4.4，破坏 `unifolm-vla / mujoco 3.5.0 / sdk2py` 这一锁定栈（见 `agi_env.md` 备忘录）。安装时必须带 `numpy==1.26.4` 约束。
- `mediapipe` 依赖 `opencv-contrib-python`（不是 `opencv-python`），且没有版本上限。在 numpy 被锁住的前提下，pip 解析器自动把 `opencv-contrib-python` 解到 4.11.0.86，与原本 `opencv-python==4.11.0.86` 完全同版本，cv2 ABI 一致。
- `mediapipe / ultralytics` 都不会下载新的 torch wheel（要求只是 `>=`），现有 `torch 2.11+cu130` 满足。
- `mediapipe 0.10.x` 要求 `protobuf<5,>=4`；`agi` 当前是 `protobuf 4.25.9`，命中。
- `tensorflow 2.15` 需要 `protobuf<4.24` —— 但这是 `agi` 里已经妥协过的状态（其它包压制了），新装 mediapipe 不会再恶化。

### 2.3 实际执行的命令

```bash
conda activate agi

# 安装 ultralytics + mediapipe，强制 numpy 不动
pip install "ultralytics>=8.3" "mediapipe>=0.10" "numpy==1.26.4"
```

> 我一开始想先 `pip uninstall -y opencv-python` 再装，避免和 mediapipe 拉进来的
> `opencv-contrib-python` 双包共存。但 ultralytics 自己**也硬声明了
> `opencv-python` 依赖**，pip 在解析过程中又把它装了回来。最终 site-packages
> 里两个 cv2 distribution 共存（同版本 4.11.0.86）—— 实测 `import cv2` 正常、
> `pip check` 没有因此新增任何冲突，所以**保持现状**。如果你后面遇到 cv2
> 模块缺失的诡异 bug，再考虑两者只留一个。

实际 pip 装上的 7 个新包（截至 2026-05-05）：

```text
mediapipe              0.10.35
ultralytics            8.4.46
ultralytics-thop       2.0.19
opencv-contrib-python  4.11.0.86     # mediapipe 拉进来的
opencv-python          4.11.0.86     # ultralytics 拉进来的（共存）
polars                 1.40.1        # ultralytics 间接依赖
polars-runtime-32      1.40.1
```

接着 `pip install -e .` 又会顺手装一个 `webrtcvad-2.0.10`（pyproject 写的是
`webrtcvad`，跟原本环境里的 `webrtcvad-wheels-2.0.14` 是两个不同
distribution、同名 module 共存，import 也照常工作）。

`pip check` 在装完之后只剩 4 条 **agi env 既有的旧警告**（tensorflow 2.15 抱怨
`ml-dtypes / tensorboard`、`tensorflow-addons` 抱怨 `typeguard`、
`albumentations` 想要 `opencv-python-headless`、`decord` 平台不支持），**没有任何
一条是 g1\_brain 引入的新冲突**。这些旧警告**不要试图修**——之前有人尝试降
protobuf / 切 headless cv 都把别的包打挂过。

### 2.4 然后再做 `pip install -e .`

```bash
cd ~/unitree/unitree-notes/g1_brain
pip install -e .
```

由于上一步已经把所有 `dependencies` 都装好了，这一步只是把 `g1_brain` 自己注册进去，秒级完成。

---

## Q3 — `OPENAI_API_KEY` 用 `set -a; source .env; set +a` 行不行？

完全可以，并且推荐。文档里的 `export OPENAI_API_KEY=sk-...` 只是最朴素的例子，本质上 `agent_main.py` 是 `os.environ.get(...)` 拿环境变量，不关心你怎么把它丢进去的。

### 3.1 推荐做法

在 `~/unitree/unitree-notes/g1_brain/.env` 里（**记得 gitignore**，本仓库目前的 .gitignore 已经覆盖 `.env`，可在 commit 前 `git status` 再确认）：

```bash
# .env
OPENAI_API_KEY=sk-...
# 可选 — 想覆盖默认模型就加上，不加就用 agent_main 里写死的默认值
# OPENAI_REALTIME_MODEL=gpt-realtime
# OPENAI_VISION_MODEL=gpt-5.5
# OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

### 3.2 启动 Terminal 4 时

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a       # 你熟悉的姿势
python -m g1_brain.apps.agent_main --mode confirm
```

`set -a` 把 source 进来的所有变量都标记为 export，等价于在每一行前面加 `export`。`set +a` 关掉这个行为，避免后续误伤。这跟你之前其它项目（va-demo 等）的用法完全一致。

### 3.3 哪些 terminal 需要 key？

| Terminal | 需要 key？ |
| --- | --- |
| 1 (MuJoCo, `unitree` env) | 不需要 |
| 2 (teleimager, `unitree` env) | 不需要 |
| 3 (e-stop listener, `agi` env) | 不需要 |
| 4 (agent\_main, `agi` env) | **需要**（除非加 `--no-realtime`） |
| 任一 debug 入口 (§Q4) | 视情况，见下表 |

只有 Terminal 4 调 OpenAI Realtime + Vision + TTS。把 `set -a; source .env; set +a` 写进 Terminal 4 的启动脚本（或 zshrc / fish abbreviation）就够了。

---

## Q4 — “The 4 debug entry points” 到底怎么开？是不是第 5 个 terminal？

### 4.1 一句话结论

**不是另开第 5 个 terminal。** 4 个 debug 入口是 4 个**用来替换 Terminal 4 (`agent_main`) 的可选启动**。每个入口只测一个子系统，对前 3 个 terminal（MuJoCo / teleimager / e-stop）的依赖**因脚本而异**——很多时候连 MuJoCo 都不需要开。

理解关键：how\_to\_run.md §2 里讲的「4-terminal startup sequence」是**跑完整 agent**的开法；§3 讲的「4 debug entry points」是**调试单个子系统**的开法。两套不互相叠加，你二选一。

### 4.2 4 个入口与所需前置 terminal

| Debug 入口 | 替换哪个 terminal | 还需要起谁？ | 何时用 |
| --- | --- | --- | --- |
| `g1_brain.apps.perception_debug` | T4 | T2（USB 摄像头），可选 T1（拿 head-cam） | 验证「眼睛」能不能看见东西 |
| `g1_brain.apps.safety_debug` | T4 | **谁都不要** —— 全 mock | A/B 改 safety yaml 时跑场景 |
| `g1_brain.apps.skill_debug` | T4 | T1（MuJoCo） | 验证 ComboController + SkillServer 跑通 |
| `g1_brain.apps.estop_test` | T4 | **谁都不要** | 验证 /tmp 那个文件标志位读写正常 |

具体到操作步骤，举三个最常见的场景：

#### 场景 A：「我只想看 perception 层抓不抓得到人」

```bash
# Terminal 1 — MuJoCo（如果你想顺便看 head 摄像头）
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py    # 进 viewer 后按 8 落地、按 9 解松

# Terminal 2 — teleimager（USB 摄像头）
conda activate unitree
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3 — perception_debug（替代原来的 T4）
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.apps.perception_debug --show
```

注意这里**只有 3 个 terminal**。没有 e-stop（不会动），没有 agent\_main（不需要 LLM）。

如果连 head-cam 都不想看，那就**只剩 1 个 terminal**：

```bash
# 单个 terminal —— 仅 USB + MediaPipe-Pose
conda activate agi
python -m g1_brain.apps.perception_debug
```

teleimager 跑不跑也无所谓，CameraHub 取不到 USB 帧时只是 `latest_usb_bgr` 返回 None，print 出来的 `summary_for_llm()` 里 `user_detections=[]` 而已。

#### 场景 B：「我想 A/B 一下 safety yaml 的几个阈值」

```bash
# 单个 terminal —— 全程 mock
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.apps.safety_debug
# 或自己写场景：
python -m g1_brain.apps.safety_debug --scenarios ./my_scenarios.json
```

不需要 MuJoCo / DDS / OpenAI / 摄像头。它内部 mock 了 SceneStateBus / RobotStateBus / FSM / EstopClient，纯逻辑跑十几个 (tool, args, expected) 的 case，告诉你哪个被错放过、哪个被错拦。

#### 场景 C：「我想用键盘戳 9 个 skill 看身体动作正不正常」

```bash
# Terminal 1 — MuJoCo
conda activate unitree
export MUJOCO_GL=glfw
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py

# Terminal 2 — skill_debug（替代 T4）
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.apps.skill_debug
# 然后在该终端按数字键 1..9，q 退出
#   1 walk 2 turn 3 wave_right 4 hands_up 5 salute
#   6 hug  7 t_pose 8 stop 9 release_arms
```

按脚本注释（`apps/skill_debug.py:1-19`）该 debug 跑在 `run_mode=active` + 关闭 perception gating，所以无需 teleimager、无需 e-stop。注意：**这里没有任何避障检查**——就是裸跑 ComboController，仅当你确信 MuJoCo 里没东西挡道时使用。

#### 场景 D：「我刚装完，想测下 e-stop 文件机制有没有问题」

```bash
# 单个 terminal
conda activate agi
python -m g1_brain.apps.estop_test
```

期望输出大致是：

```
flag path: /tmp/g1_brain_estop_test
initial is_engaged: False
engage(): 0.18 ms
reason: 'test'
is_engaged poll: 0.025 ms / call (n=20)
release(): 0.12 ms
re-release() ok (no error)

estop_test: PASS
```

任何一行打 ERROR 就说明 `/tmp` 不可写、或你用了奇怪的 flag\_path。这是装完后第一时间该跑的 smoke test。

### 4.3 多个 debug 入口能否同时开？

可以。比如同时跑 `perception_debug --show` + 另一个 terminal 跑 `estop_test`，互不干扰（前者只读 cameras，后者只敲 /tmp 文件）。但**不要同时跑 `skill_debug` + `agent_main`**：两者都会订阅 `/rt/lowstate`、都会向 `/rt/lowcmd` 发指令，会互相打架。

---

## Q5 — `--mode observe / confirm / active` + `--vision-only` 详解

理解 mode 之前先看 SafetySupervisor 的 11 条规则（见 `safety/supervisor.py:1-23`）：

```
1  whitelist            (这个 tool 名字合法吗)
2  FSM gating           (当前 FSM state 允许这个 tool 吗)
3  run_mode             (observe→拒  confirm→等y/N  active→放行)
4  lowstate watchdog    (DDS lowstate 还活着吗)
5  head-cam watchdog    (head 摄像头帧龄)
6  RL policy active
7  body pose check      (重力投影 z，判定是否倾倒)
8  parameter clamp      (vx/vy/wz/duration 范围)
9  scene check (walk)   (clear_path / 最近障碍 / 最近人)
10 scene check (gesture) (最近的人)
11 E-stop flag
```

`--mode` 控制的是**第 3 条**。其它 10 条**所有 mode 都跑**。下面分别看：

### 5.1 `--mode observe` —— 「闭嘴看戏」

```python
# safety/supervisor.py:236-238
if self.run_mode == "observe":
    return False, "observe_only mode: motion disabled", {}
```

任何 motion tool（`walk / turn / gesture / static_pose / look_at / approach / mock_imitate`）**直接拒绝**，连规则 4..10 都不跑。但下面这些**仍然能用**：

- `say` — Realtime TTS 出声
- `describe_scene` — 看摄像头描述
- `query_scene_state` — 拿当前 SceneState 摘要
- `stop` / `release_arms` — 不算 motion

**用途**：

- 第一次接通 LLM、只想确认「它看得见、说得对」。
- 在你刚改完一版 prompt / safety yaml 后做 dry-run，看 LLM 会不会**意图**调用一些不该调的 motion（被拒就打 log，写在 `logs/agent.log`）。
- demo 给非工程师看的时候，想完全杜绝意外移动。

### 5.2 `--mode confirm` —— 默认，「人在回路里」

`run_mode == "confirm"` 时，规则 3 不立即拒绝；走完 4..10（watchdog / pose / clamp / scene check）后，supervisor 在**主进程的 stdin** 上打印：

```
[g1_brain confirm] execute walk({'vx': 0.15, 'duration_s': 0.6}) ? [y/N]
```

然后 `asyncio.wait_for(loop.run_in_executor(None, sys.stdin.readline), timeout=10.0)` —— **10 秒不输入就当拒绝**（`safety/supervisor.py:100-113`）。输入 `y` 或 `yes` 才放行；其它（包括空回车）都判拒。

**关键细节**：

- 这个 prompt 出现在你**启动 `agent_main` 的那个 terminal** 里——也就是 Terminal 4。所以你在用 confirm 模式时，键盘焦点要留在 T4，不能切走。
- 即使你按了 `y`，supervisor 还会再过一遍参数 clamp 和 scene check 才真发指令。confirm **不能绕过其它规则**。
- watchdog 4..6 / pose 7 / scene 9..10 任何一条不过，直接拒绝、根本不会问你。

**用途**：日常调试 + 真正首次让 LLM 主动控制机器人时。文档把它列为 default + recommended 是有理由的——人脑做最后一道闸。

### 5.3 `--mode active` —— 「相信 LLM」

```python
# safety/supervisor.py:329-333
if self.run_mode == "confirm":
    ok = await self._confirm_fn(tool, sanitized)
    ...
```

active 模式直接跳过这段。规则 1..2 + 4..11 仍然全部跑。用途：

- 已经通过若干轮 confirm 模式验证、对当前 prompt 和 scene checks 有信心。
- 录 demo：不希望中间停下来等你按 y。
- 跑长流程脚本（mock\_imitate、长 walk 序列）。

⚠️ **建议门槛**：在你 confirm 跑 30 分钟以上没出现误触发、且 `safety_debug` 的全部 default scenarios 都符合预期之后，再考虑切 active。real-robot 切换前必须先在 sim 里 active 跑通。

### 5.4 选择决策树

```
我现在最大的问题是什么？
├── 「LLM 听不听得懂我说话 / 看不看得见东西」
│       → --mode observe  （或 + --vision-only，见 §5.5）
│
├── 「LLM 决策对不对、但我不放心让它自动动」
│       → --mode confirm  （default）
│
├── 「都验过了，我要跑 demo / 长任务」
│       → --mode active
│
└── 「我只想测 perception / safety / skill / estop 单个子系统」
        → 不开 agent_main，开对应 debug 入口（§Q4）
```

### 5.5 `--vision-only` —— 与 mode 正交的开关

它**不替换 mode**，是另一个独立 flag。语义（`agent_main.py:285-291`）：

- 把所有 motion tool 从 OpenAI tool schema 里**摘掉**——LLM 根本看不到 walk/turn/...，自然不会调。
- **跳过 DDS / ComboController / RL policy 初始化**——不需要 MuJoCo 在跑。
- **隐式开启** `--no-skills`。

跟 mode 的组合：

| 组合 | 实际效果 |
| --- | --- |
| `--vision-only`（不带 mode） | mode 会被读 default = confirm，但因为没有 motion tool，confirm 永远不会触发 |
| `--vision-only --mode observe` | 等同 `--vision-only`（observe 拦的就是 motion）|
| `--vision-only --mode active` | 同上 |

**典型用例**：在没有 GPU / 没装 MuJoCo 的笔记本上，想确认 OpenAI Realtime 收音、TTS 出声、vision pipeline 抓帧都正常。`--vision-only` 是 va-demo 已经验证过的姿势的延续，参考 va-demo 现有用法即可。

### 5.6 还有几个 bypass flags 顺带说

| Flag | 跳过了谁 | 何时用 |
| --- | --- | --- |
| `--no-realtime` | 不连 OpenAI Realtime websocket | 离线写代码 / 网络问题，单测下游 |
| `--no-skills` | 不 init DDS / ComboController（motion tool 调用必失败） | MuJoCo 没起的时候，只想看 perception 跟 LLM |
| `--no-perception` | 不起 PerceptionRunner | 只想看 LLM + safety 行为时，省 GPU |
| `--no-wakeword` | 麦克风一直开，不靠 wake-word 唤醒 | 演示给观众；调试 wake-word 误触发 |

这几个跟 `--mode` 也都正交，可以叠：比如 `--mode confirm --no-realtime --no-skills` = 「我就想看 perception 喂出来的 SceneState 长什么样，连 LLM 都不要」。

---

## 附：一次完整的「装好 + 自检」流水（已实测）

```bash
# 1) 装依赖（首次约 15-20 min，主要是 polars-runtime-32 和 opencv-contrib 大 wheel）
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
pip install "ultralytics>=8.3" "mediapipe>=0.10" "numpy==1.26.4"
pip install -e .

# 2) 不依赖外部 service 的两个 smoke test
python -m g1_brain.apps.estop_test                     # /tmp 标志位 — 应输出 estop_test: PASS
python -m g1_brain.apps.safety_debug                   # 全 mock 6 个场景 — 应输出 6/6 matched expected

# 3) 模块 import 自检（一行排查所有子包能不能 load）
python -c "
import importlib
for m in ['g1_brain.apps.perception_debug','g1_brain.apps.safety_debug',
         'g1_brain.apps.skill_debug','g1_brain.apps.estop_test','g1_brain.apps.agent_main',
         'g1_brain.perception.runner','g1_brain.safety.supervisor',
         'g1_brain.scene_state.fusion','g1_brain.skills','g1_brain.brain']:
    importlib.import_module(m); print('OK', m)
"

# 4) 真要跑 agent 时再开 4 个 terminal —— 见 how_to_run.md §2
```

实测结果（2026-05-05）：

| 步骤 | 结果 |
| --- | --- |
| `import cv2 / ultralytics / mediapipe / numpy` | cv2 4.11.0 / ultralytics 8.4.46 / mediapipe 0.10.35 / numpy 1.26.4 |
| `pip install -e .` | `Successfully installed g1_brain-0.1.0 webrtcvad-2.0.10` |
| `pip check` | 4 条 agi 旧警告，无新增 |
| `estop_test` | `estop_test: PASS`（engage 0.20 ms、release 0.10 ms、poll 0.002 ms） |
| `safety_debug` | `6/6 matched expected`（say-allowed / walk-rejected-in-standing / walk-blocked-by-obstacle / walk-ok-active / estop-blocks-walk / tipping-triggers-emergency 全过） |
| 10 个核心模块 import | 全 OK |

---

*生成时间 2026-05-05；agi env 状态见 `~/.claude/projects/.../memory/agi_env.md`。*
