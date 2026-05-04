# va-demo 视觉理解模块（Vision-Only 测试模式）— 使用指南

> 配套文档：[`video-design.md`](video-design.md) 讲**为什么这样实现**；本文档讲**当前设计是什么、怎么用、出问题怎么查**。
>
> 适用分支：`feature/video-listen`（基于 `feature/audio-fix` 之上的 8 个 commit）

---

## 0. 一句话总结

确认 teleimager 能拉到摄像头帧、conda 进 `agi` 环境、`.env` 里写了 `OPENAI_API_KEY`，然后**两个终端**：

```bash
# Terminal 1: 摄像头服务（必需，但 MuJoCo 不需要）
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 2: vision-only 模式跑 va-demo
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a              # 关键：把 .env 导出到环境变量
python -m va_demo.main --vision-only -v
```

启动后等到日志里出现这两行就 ready：

```
INFO va_demo: vision-only mode: tools=[say, describe_scene]; motion tools removed
INFO va_demo: wake-word enabled: phrases=['hi sparky', ...]
```

然后对着麦克风：

> 你: "Hi Sparky"
> （日志：`[wake]` → `IDLE -> CAPTURING`）
> 你: "前面有什么？"
> （日志：`[utterance] commit_silence` → `CAPTURING -> THINKING -> SPEAKING`）
> Sparky: "我看到桌子上有……" （扬声器播放，时长视描述长短）
> （日志：`SPEAKING -> LISTENING_WINDOW`，8 秒后回 IDLE）

完整流程就这样。

---

## 1. 这个模式做什么 / 不做什么

| 能做 | 不能做 |
|---|---|
| 用语音唤醒 ("Hi Sparky") | 让 Sparky 走/挥手/做任何动作 |
| 让 GPT-5.5 视觉模型描述当前摄像头画面 | 多帧理解 / 视频理解（仅单帧关键帧） |
| 用 Sparky 的语音读出描述结果 | 实时（持续）视觉理解（每次需语音触发） |
| 中英文自适应回答 | 自定义关键帧选择策略（拿到的就是当前最新帧） |
| 8 秒追问窗（不需重唤醒） | 离线运行（Realtime + Vision API 都需联网） |

vision-only 模式下 Realtime 模型只看到两个 tool：

| Tool | 用途 |
|---|---|
| `say(text)` | 简短的固定话语（一般不主动调，Realtime 自带语音） |
| `describe_scene(question?, detail?)` | 抓最新帧 → vision API → 文本，模型再用语音读出来 |

`walk` / `gesture` / `stop` / `release_arms` **从 Realtime API 的 schema 里整段撤掉**，模型连知都不知道有这些工具。所以即使你说"向前走两步"，Sparky 不会调 motion tool，而是用语言回："我现在在视觉测试模式，无法移动，需要我描述一下场景吗？"

---

## 2. 启动前的环境检查清单

下面 5 项任意一项不满足都会启动失败或对话异常，建议第一次跑前从上到下过一遍。

### 2.1 conda 环境是 `agi`

```bash
conda activate agi
which python
# 期望: /home/helios/miniforge3/envs/agi/bin/python
python --version
# 期望: Python 3.11.x
```

如果 `agi` 环境不存在，参考工作区 README 或 `~/.claude/.../memory/agi_env.md`（这是 numpy 1.26.4 + sdk2py + mujoco + rl_mjlab + teleimager 的统一环境）。

### 2.2 va-demo 依赖装好

```bash
cd ~/unitree/unitree-notes/va-demo
pip install -r requirements.txt
```

`requirements.txt` 包含：`openai`, `sounddevice`, `websockets`, `pyyaml`, `numpy`, `opencv-python`, `pyzmq`, `faster-whisper`, `webrtcvad-wheels`。已经装过就跳过。

### 2.3 `.env` 文件存在并有 key

```bash
ls -la .env
# 期望: -rw------- ... .env  （权限 600，只有你能读）

cat .env
# 期望:
# OPENAI_API_KEY=sk-...
# OPENAI_REALTIME_MODEL=gpt-realtime
# OPENAI_VISION_MODEL=gpt-5.5     # ← 你要确保账号能用这个
# OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

如果 `.env` 不存在：

```bash
cp .env.example .env
nano .env       # 填入 sk-... 真实 key
chmod 600 .env  # 防止其他用户偷看
```

`.env` 已经在 `.gitignore`，**绝不会被 commit**。

> ⚠️ **关键提醒：代码本身不会自动 load `.env`** —— `va_demo/main.py` 直接读 `os.environ.get("OPENAI_API_KEY")`，不依赖 `python-dotenv`。所以**每次开新终端都必须手动导**：
>
> ```bash
> set -a; source .env; set +a
> ```
>
> 这条命令把 `.env` 里所有 `KEY=val` 临时导入当前 shell 的环境变量。验证：
>
> ```bash
> echo "${OPENAI_API_KEY:0:7}..."
> # 期望输出: sk-xxx...
> ```
>
> 如果你忘了 source，va-demo 启动会立刻报错：
> ```
> ERROR va_demo: OPENAI_API_KEY is not set; either export it or pass --no-realtime
> ```

### 2.4 麦克风 + 扬声器能用（WSL2 / WSLg）

最快的验证：

```bash
python scripts/audio_loopback.py
# 5 秒内对着麦说话，应该能从扬声器听到回声 + 看到 RMS 数值
```

如果 RMS 一直 0 或听不到回声，参考 README 的「Audio prerequisites in WSL2」一节。常见根因（已记在 user memory）：conda env 里没 ALSA→PulseAudio plugin，需要软链 `$CONDA_PREFIX/lib/alsa-lib` → `/usr/lib/x86_64-linux-gnu/alsa-lib`。

### 2.5 摄像头能被 teleimager 拉到

```bash
# 单独测一下 teleimager 这边连得通
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
# 期望: 进程不退；不报错；类似
#   "head_camera bound on port 55555"
#   或
#   "ImageServer running on tcp://127.0.0.1:55555"
```

WSL2 + USB 相机的 usbipd 接入步骤详见 `docs/camera_ui_demo.md`（不在本文档范围内）。

启 teleimager 后，在另一个终端用 `camera_debug.py` 验证 va-demo 这边能拿到帧 + vision API 能调通：

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python scripts/camera_debug.py --question "前面有什么"
# 期望:
#   waiting up to 5s for first frame ...
#   frame ok (54321 bytes b64). sending to gpt-5.5 (detail=medium) ...
#   === vision result ===
#   我看到 ... （某段描述）
```

到这一步 vision 链路就已经独立验证通过了。下面才是把它接进 Realtime 跑完整对话。

---

## 3. 启动完整 vision-only 对话

两个终端：

### Terminal 1 — teleimager

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
# 保持运行，不要 Ctrl-C
```

### Terminal 2 — va-demo

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python -m va_demo.main --vision-only -v
```

`-v` 是 verbose，强烈建议第一次跑加上，方便看每个状态机迁移。

### 期望启动日志（前 ~5 秒）

```
INFO va_demo: --vision-only implies --no-skills; skipping DDS init
INFO va_demo.audio_io: mic started: samplerate=24000, block_frames=1200, device=None
INFO va_demo.audio_io: speaker started: samplerate=24000, device=None
INFO va_demo.wake_word: OpenAITranscribeBackend ready: model=gpt-4o-transcribe prompt='Sparky' language=None
INFO va_demo: run_mode=confirm
INFO va_demo: connecting Realtime: wss://api.openai.com/v1/realtime?model=gpt-realtime
INFO va_demo: vision-only mode: tools=[say, describe_scene]; motion tools removed
INFO va_demo: wake-word enabled: phrases=['hi sparky', 'hey sparky', ...]
```

看到最后两行 INFO 就 ready 了。

### 一次完整对话的日志样子

```
... 你说 "Hi Sparky" ...
INFO va_demo.conversation_state: [wake] Hi, Sparky. (state=IDLE)
INFO va_demo.conversation_state: [state] IDLE -> CAPTURING

... 你说 "前面有什么？" ...
... 1.5 秒静默 ...
INFO va_demo.conversation_state: [utterance] commit_silence after 2.34s
INFO va_demo.conversation_state: [state] CAPTURING -> THINKING

... ~300 ms Realtime 模型识别意图，调 tool ...
INFO va_demo.realtime_agent: tool call: describe_scene({'question': '前面有什么？'})

... ~1.5-4 秒 vision API ...
INFO va_demo.conversation_state: [state] THINKING -> SPEAKING
（扬声器开始播 Sparky 的语音回答）

... Sparky 说完 ...
INFO va_demo.conversation_state: [state] SPEAKING -> LISTENING_WINDOW

... 8 秒追问窗：在这期间继续说话不需要重新喊唤醒词 ...
（如果你没说话）
INFO va_demo.conversation_state: [state] LISTENING_WINDOW -> IDLE
```

任何路径偏离这套都说明配置或环境有问题，第 §6 节有故障速查。

---

## 4. CLI flags 参考

| Flag | 默认 | 在 vision-only 下的作用 |
|---|---|---|
| `--vision-only` | off | **本节主角**：撤掉 motion tool + 跳 DDS init |
| `--config` | `configs/va_demo.yaml` | 配置文件路径 |
| `--mode {observe,confirm,active}` | `confirm` | 实质上没影响（vision-only 下没有 motion tool 可调） |
| `--no-realtime` | off | 不连 Realtime；只跑 audio/camera。**配 `--vision-only` 没意义**（vision-only 的全部价值就在 Realtime 链路） |
| `--no-skills` | off | 已被 `--vision-only` 自动设为 true |
| `--no-wakeword` | off | 关掉唤醒词；mic 持续推 Realtime（debug 用，不推荐 vision-only 下用） |
| `-v` / `--verbose` | off | DEBUG 日志（含状态机迁移、wake、utterance 全部细节）|

最常用的就两条：

```bash
# 标准：唤醒词 + verbose
python -m va_demo.main --vision-only -v

# 非常规：跳过唤醒词，麦克风持续推 Realtime（用来 A/B 验证状态机的影响）
python -m va_demo.main --vision-only --no-wakeword -v
```

---

## 5. 调参点（vision-only 模式下最常调的几项）

vision-only 不引入新调参；下面是从你视觉测试角度最可能想动的几项，全部在 `configs/va_demo.yaml`：

### 5.1 视觉质量 vs 延迟

```yaml
openai:
  vision_model: "gpt-5.5"     # ← .env 里 OPENAI_VISION_MODEL 覆盖优先
  vision_detail: "medium"     # low / medium / high

camera:
  vision_resize_width: 1024   # 上传前 resize 到的最大宽
  vision_jpeg_quality: 85     # JPEG 压缩质量 1-100
```

| 参数 | 影响 |
|---|---|
| `vision_detail: low` | 模型只看缩略图，快但少细节，2 秒级首响 |
| `vision_detail: medium`（默认）| 平衡，3-4 秒首响 |
| `vision_detail: high` | 看到字、读到 OCR 级文本，5-7 秒首响 |
| `vision_resize_width: 768` | 网络上传更快（图小约 40%），细节略损 |
| `vision_jpeg_quality: 70` | 文件再小约 20%，画质明显变糊；不建议低于 70 |

### 5.2 帧"新鲜度"门槛

```yaml
safety:
  watchdog:
    max_frame_age_s: 2.0     # 帧老于 2 秒 → describe_scene 被 SafetySupervisor 拒
```

如果 teleimager 偶发卡顿（USB 相机重新枚举常见），调到 5.0 可以让 vision 更宽容；调到 0.5 可以强制只用最新一帧。**vision-only 模式下这条仍然生效**——`describe_scene` 经过 SafetySupervisor.validate。

### 5.3 唤醒词 / 句末检测（与 audio-fix 一致）

详见 [`audio-use.md`](audio-use.md)。最常调的两个：

```yaml
wakeword:
  rms_threshold: 100         # 喊了没反应就调低；误触发就调高
  cooldown_s: 2.0            # 唤醒后多久不再次触发

utterance:
  silence_threshold_ms: 1500 # 句末静默多久算说完。说话有顿挫的人调到 2000+
  no_speech_timeout_s: 4.0   # 唤醒后这么久没人说话 → 回 IDLE
```

---

## 6. 故障速查

| 现象 | 大概率原因 | 验证方法 | 修法 |
|---|---|---|---|
| 启动报 `OPENAI_API_KEY is not set` | 没 `source .env` | `echo "${OPENAI_API_KEY:0:7}"` 是空 | `set -a; source .env; set +a` |
| 启动报 `Connection refused` 拉摄像头 | teleimager 没启动 | `ps aux \| grep teleimager` | 起 Terminal 1 的 teleimager.image_server |
| Sparky 念 "(vision request failed: ... model not found)" | 你账号没 gpt-5.5 权限 | `python scripts/camera_debug.py --question x`，看返回的错误 | `.env` 里改 `OPENAI_VISION_MODEL=gpt-5.1` 或 `gpt-4o`，重启 va-demo |
| Sparky 念 "no frame available" | teleimager 在跑但没拉到帧（相机断了） | 看 teleimager 终端日志；`v4l2-ctl --list-devices` | 重新 `usbipd attach`；重启 teleimager |
| Sparky 念 "frame too old" / "no recent frame" | hotfix 后只在 teleimager **真的连续 ≥ 2 s 没推帧**才会出现（USB 相机重连 / WSL2 USB 重新枚举 / teleimager 卡死） | teleimager 终端 FPS 是不是 < 0.5 | 调高 `safety.watchdog.max_frame_age_s`；或修 teleimager 卡顿根因 |
| 第一次 describe_scene 就被拒、reason 含 `age=inf.0s` | 你没装 hotfix（`va_demo/camera.py` 没有后台 poller） — chicken-and-egg bug 详见 [`video-design.md`](video-design.md) §9 | `git log --oneline va_demo/camera.py \| head -3` 看是否有 `fix(va-demo): camera background-poll thread`；`grep "_poll_loop" va_demo/camera.py` | `git pull` 拉最新，或手动 patch 到 hotfix 版 |
| 喊 hi sparky 没任何 WAKE | wake-word RMS 阈值过高 / 麦克风没声 | `-v` 看 `rms gate: X < N (skip)` 行 | 调低 `wakeword.rms_threshold`；详见 audio-use.md §7 |
| WAKE 触发了但提交后 Sparky 不响应 | Realtime WS 出错 | 看 va-demo 终端有没有 `realtime error:` 日志 | 检查 key 是否被 revoke；网络是否稳；重启 va-demo |
| Sparky 念了一句中文但场景描述全是英文 | system prompt 语言适配生效但 vision API 默认英文 | 用户 question 里包含中文会让 vision 也用中文 | 触发时多说一句明确语言: "用中文描述前面" |
| 模型在 vision-only 下还是试图调 motion tool | 不可能（schema 没传给模型）；如果真的看到 → bug | 找日志里的 `tool call:` 行，看 name 是不是 walk/gesture | 报回来；附 `pytest tests/test_vision_only_mode.py -v` 输出 |
| 启动后状态机一直在 CAPTURING <-> THINKING 抖动 | 麦克风回灌 / wake-word 误触 | 详见 audio-use.md §10 | RMS 阈值调高、戴耳机、`--no-wakeword` 排除 |
| 长答案被截断 | 不应该（`SpeakerStream` 60 s sanity cap） | 看是否有 `speaker buffer exceeded sanity cap` WARN | 没 WARN 还截断 → 网络抖动；有 WARN → 报 bug |
| `describe_scene` 一调用 va-demo 就崩 | OpenCV / numpy 版本错配 | `python -c "import cv2, numpy; print(cv2.__version__, numpy.__version__)"` | 重装 requirements.txt（应该 cv2 4.x + numpy 1.26.x） |
| `--vision-only` 在 `--help` 里看不到 | 你跑的不是 `feature/video-listen` | `git branch --show-current` | `git checkout feature/video-listen` |
| 8 秒追问窗内说话被忽略 | 实际上是漏检了 utterance 起点 | `-v` 看是否有 `[utterance] commit_silence` | 调小 `utterance.silence_threshold_ms`，或调大 `conversation.listening_window_s` |

### 6.1 模型权限 / 模型替换

OpenAI 账号通常默认不开 `gpt-5.5`。如果你的账号可以用某个其它视觉模型（比如 `gpt-5.1`、`gpt-4o`），按下面的优先级覆盖（高 → 低）：

1. `OPENAI_VISION_MODEL` 环境变量（最高，最常用）
2. `configs/va_demo.yaml::openai.vision_model`
3. 代码里的 `gpt-5.5` 默认（最低）

把 `.env` 改成：

```dotenv
OPENAI_VISION_MODEL=gpt-5.1
```

重新 `set -a; source .env; set +a` 然后重启 va-demo。日志里会看到 `VisionClient` 用的是新 model（DEBUG 级别才会打）。

要快速 A/B 不同模型，可以临时只在 shell 里 export：

```bash
OPENAI_VISION_MODEL=gpt-4o python -m va_demo.main --vision-only -v
```

### 6.2 单独验证 vision 链路（不走 Realtime）

这是排查"vision API 通不通"vs"Realtime 链路通不通"最快的二分法：

```bash
# 只走 camera + vision，不开 Realtime
set -a; source .env; set +a
python scripts/camera_debug.py --question "前面有什么"
```

如果这个能返回描述，说明 `OPENAI_API_KEY` 有效、vision 模型能用、teleimager 推帧正常。问题在 Realtime 那边。

```bash
# 1 Hz 持续 vision，看延迟稳定性
python scripts/vision_loop_debug.py --rate-hz 1.0
# 期望: 每秒一行 [XXXX ms] 描述...，ms 大致 1500-4000 区间
```

### 6.3 单独验证 Camera 后台 poller（hotfix 引入）

如果你怀疑 watchdog 又开始拒帧（无论是 chicken-and-egg 回归、还是 teleimager 真的卡了），不开 Realtime / vision API、用几行 Python 直接看 `frame_age`：

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python -c "
import time
from va_demo.camera import Camera
cam = Camera(host='127.0.0.1', request_port=60000, request_bgr=True)
for _ in range(10):
    print(f'frame_age={cam.frame_age_seconds():.3f}s')
    time.sleep(0.5)
cam.close()
"
```

期望（teleimager 在推帧）：

```
frame_age=inf            ← 第一行偶尔会赶在第一次 poll 前；正常
frame_age=0.013s
frame_age=0.027s
frame_age=0.044s
...                      ← 全部 < 0.1 s，节奏稳定
```

故障对照：

| 你看到的 | 说明 | 怎么办 |
|---|---|---|
| 全部行都 `inf` | **chicken-and-egg 回归 / 后台线程没启动 / camera.py 不是 hotfix 版** | `grep _poll_loop va_demo/camera.py`，没有就 `git pull` |
| 前几行正常，之后慢慢爬上 1 s+ | teleimager 卡顿 / USB 相机断 | 看 teleimager 终端；`v4l2-ctl --list-devices`；重新 attach |
| 直接 raise `Failed to get camera configuration` | teleimager 没启动 / 端口不对 | `python -m teleimager.image_server` |
| 抛 `ImportError: No module named teleimager` | 没在 `agi` 环境 / teleimager 没装 | `conda activate agi`；`pip install -e ../teleimager` |

跑回归测试也可以确认 hotfix 在位：

```bash
pytest tests/test_camera_freshness.py -v
# 期望: 3 passed
```

### 6.4 安静期间 vision-only 的成本

vision-only 运行**不发起任何 vision API 调用**直到你 wake + 问视觉问题。安静期间的成本结构：

| 组件 | 频率 | 单价 |
|---|---|---|
| 麦克风采集 | 永远在跑 | 0 |
| Wake-word `gpt-4o-transcribe` | 每 0.5 s 一次，仅在 RMS > 100 时触发 | 按 1.5 s 音频/次计费 |
| Realtime WS 心跳 | 永久连着 | OpenAI Realtime 的会话级计费（按小时；具体查官网） |
| Vision API | **每次 describe_scene 一次** | 单次按 token 计费 |
| TTS / Realtime 语音输出 | 每次 Sparky 回复时 | Realtime audio output 计费 |

**省钱小窍门：**
- 如果你不打算说话（吃饭、开会），Ctrl-C 退出 va-demo。Realtime 会话挂着也是按时间计费的。
- 把 `wakeword.rms_threshold` 调到比环境噪声高 3 倍以上，避免 idle 触发 transcribe。
- 不需要 wake-word 的话用 `--no-wakeword` 切回 server VAD（但是是 audio-fix 之前的旧行为，会被自我打断）。

---

## 7. 与 audio-fix 那波的关系

vision-only 模式**完全建立在** audio-fix（feature/audio-fix 那波）的成果上：

- 唤醒词、句末检测、状态机、自回声防护、SpeakerStream 长回复支持 —— 全部复用，零改动
- 默认 wake-word 后端、配置项、CLI flag 行为 —— 全部继承
- 49 个旧测试 —— 全部保留通过

vision-only 仅仅是在最上层加了一个 **schema 切换 + DDS 跳过** 的开关。所以：

- audio-fix 在你环境里能跑，vision-only 也能跑
- audio-fix 调好的 RMS / cooldown / language，vision-only 直接受益
- audio-use.md 里讲的所有故障速查、调参原则，vision-only 下完全适用

如果你跑 `python -m va_demo.main`（不带 `--vision-only`），就是 audio-fix 的完整功能（含 walk/gesture/stop）；带 `--vision-only` 就只剩视觉。两者切换零状态、零编译。

---

## 8. 测试 / 回归

```bash
cd ~/unitree/unitree-notes/va-demo
pytest tests/ -v
# 期望: 58 passed  (50 旧 + 5 vision-only + 3 camera-freshness hotfix)
```

只跑 vision-only 相关：

```bash
pytest tests/test_vision_only_mode.py -v
# 期望: 5 passed
```

只跑 §6.3 提到的 Camera hotfix 回归：

```bash
pytest tests/test_camera_freshness.py -v
# 期望: 3 passed
```

测试不依赖 OpenAI / 真 teleimager / faster-whisper —— 直接 import 模块用 mock 跑。`test_camera_freshness.py` 用 `monkeypatch.setitem(sys.modules, "teleimager.image_client", fake_mod)` 注入一个 fake `ImageClient`，所以即使没装 teleimager 也能跑。CI 友好。

---

## 9. 改了源码想生效

| 改了 | 怎么生效 |
|---|---|
| `va_demo/realtime_agent.py` | 重启 `python -m va_demo.main --vision-only` |
| `va_demo/prompts.py` | 重启（Realtime session 启动时才发 instructions） |
| `configs/va_demo.yaml` | 重启 |
| `.env`（包括换 `OPENAI_VISION_MODEL`）| `set -a; source .env; set +a` 然后重启 va-demo |
| 改 `va_demo/camera.py` 或 `vision.py` | 重启 |
| 单纯改 prompt 微调试 | 不需要改代码，可以临时 export shell 变量后重启 |

`.pyc` 不需要清；conda env 不需要重建。

---

## 10. 完整的"从零开机到对话"流程清单

第一次跑用这个清单从上到下，全打勾就行：

- [ ] **打开 WSL2 / Linux 终端**
- [ ] `conda activate agi` （prompt 应该变成 `(agi)`）
- [ ] `cd ~/unitree/unitree-notes/va-demo`
- [ ] `ls .env` 确认存在；不存在的话 `cp .env.example .env && nano .env` 填 key
- [ ] `set -a; source .env; set +a` （**关键：每个终端都要做**）
- [ ] `echo "${OPENAI_API_KEY:0:7}..."` 应该看到 `sk-xxx...`
- [ ] **新开一个终端**，`conda activate agi`
- [ ] `cd ~/unitree/unitree-notes/teleimager`
- [ ] `python -m teleimager.image_server` （保持运行）
- [ ] 回到第一个终端，`python scripts/camera_debug.py --question "前面有什么"` 验证 vision 链路通
- [ ] 看到一段描述返回 → vision OK，进入下一步
- [ ] `python -m va_demo.main --vision-only -v`
- [ ] 等到日志里有 `vision-only mode: tools=[say, describe_scene]` + `wake-word enabled`
- [ ] 对着麦克风："**Hi Sparky**"
- [ ] 看到日志 `[wake] ... (state=IDLE)` + `[state] IDLE -> CAPTURING`
- [ ] 接着说："**前面有什么？**"（或别的视觉问题）
- [ ] 听到 Sparky 用语音读出场景描述

任何一步卡住请回到 §6 的故障速查表。

---

## 11. 参考

- 实现总结（按 commit 顺序、设计意图、模块复用）：[`video-design.md`](video-design.md)
- 设计 spec（架构、错误处理、acceptance）：`docs/superpowers/specs/2026-05-04-vision-only-mode-design.md`
- 实施 plan（7 任务的 TDD 详细步骤）：`docs/superpowers/plans/2026-05-04-vision-only-mode-implementation.md`
- audio-fix 使用指南（唤醒词调参、状态机、自回声防护）：[`audio-use.md`](audio-use.md)
- audio-fix 实现总结：[`audio-awake.md`](audio-awake.md)
- 整体 README："Vision-only test mode" 一节：[`../README.md`](../README.md)
- 相关源码（按修改频率）：
  - `va_demo/main.py` — `--vision-only` flag + `args.no_skills` 短路
  - `va_demo/realtime_agent.py` — `vision_only` 字段 + `_resolve_*` 助手 + `_build_tool_schemas(vision_only=)`
  - `va_demo/prompts.py` — `REALTIME_SYSTEM_PROMPT_VISION_ONLY`
  - `va_demo/camera.py` — TeleImager ZMQ client 包装；**hotfix 后**带 daemon 后台 20 Hz poll 线程刷新 `_last_bgr_t`，加锁保线程安全（详见 [`video-design.md`](video-design.md) §9）
  - `va_demo/vision.py` — OpenAI Responses API 调用（无改动）
  - `configs/va_demo.yaml::openai.vision_model` — 模型默认（env 优先）
  - `tests/test_vision_only_mode.py` — 5 个 vision-only 测试覆盖 schema + prompt + agent 字段
  - `tests/test_camera_freshness.py` — **hotfix 新增**：3 个回归测试，用 fake teleimager stub 验证后台 poller 把 `frame_age_seconds()` 从 `inf` 拉低到 < 1 s
