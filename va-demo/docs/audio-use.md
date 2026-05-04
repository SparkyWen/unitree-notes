# va-demo 唤醒词与音频流水线 — 使用指南

> 配套文档：[`audio-awake.md`](audio-awake.md) 讲**为什么这样实现**；本文档讲**当前设计是什么、怎么用、怎么调、出问题怎么查**。
>
> 适用分支：`feature/audio-fix`（含三次后续修订：`4ad6ecc` 阈值/精度、`c6ae88e` 4o 默认、`8f04553` 自然交互 — 详见 §2）

---

## 0. 一句话总结

把麦克风插好、conda 进 `agi` 环境、写好 `.env`，然后选一个后端跑：

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a   # 把 OPENAI_API_KEY 之类导出来

# A) 调试唤醒词（不连 Realtime，单独跑 detector）
#    脚本 CLI 默认 --backend local；切到 openai 需显式指定。
python scripts/wake_word_debug.py --backend openai --verbose

# B) 跑完整 demo（自动加唤醒词门控 + Realtime 对话）
#    主入口默认从 configs/va_demo.yaml::wakeword.backend 取，
#    yaml 默认 openai → gpt-4o-transcribe。
python -m va_demo.main
```

对着麦克风喊 "**Hi Sparky**" → 看到 `WAKE @ ...` 或日志里 `[wake] ... [state] IDLE -> CAPTURING` 就成。

---

## 1. 系统架构

### 1.1 数据流

```
                      ┌──────────────────┐
   USB / WSLg 麦克风 ─▶│ MicStream        │ 24 kHz int16 mono，50 ms 一块
                      │ (sounddevice)    │ subscribe() fan-out 给多个消费者
                      └──────┬───────────┘
                             │ 原始 PCM
            ┌────────────────┼────────────────────┐
            ▼                                     ▼
   ┌─────────────────────┐              ┌──────────────────────┐
   │ WakeWordDetector    │              │ UtteranceVAD         │
   │ rolling 1.5 s 缓冲  │              │ webrtcvad，在        │
   │ 每 0.5 s 转录一次   │              │ CAPTURING 状态下喂   │
   │  + RMS 门 100       │              │ 24→16 kHz 重采样     │
   │  + 短语子串匹配     │              │ 30 ms 帧             │
   │  + 自回声去重       │              └──────────┬───────────┘
   │  + 2 s 冷却         │                         │ commit_silence /
   └────────┬────────────┘                         │ commit_max
            │ on_wake(...)                         │
            ▼                                       ▼
   ┌─────────────────────────────────────────────────────────┐
   │ ConversationStateMachine（6 状态，单事件循环）          │
   │ IDLE → CAPTURING → THINKING → SPEAKING → LISTENING_WIN. │
   │             ↑                                  │        │
   │             └──────  (拿到 wake 才再开)  ──────┘        │
   └────────┬─────────────────────────────────────┬──────────┘
            │ open uplink / commit / (no cancel)  │ pause/resume wake_word
            ▼                                      
   ┌─────────────────┐    ┌──────────────────┐
   │ RealtimeAgent   │ ─▶ │ OpenAI Realtime  │
   │ (WebSocket)     │ ◀─ │  (LLM + 语音)    │
   │ turn_detection  │    │                  │
   │      = null     │    │                  │
   └────────┬────────┘    └──────────────────┘
            │ audio.delta + audio_transcript.delta
            ▼
   ┌─────────────────┐    ┌──────────────────┐
   │ SpeakerStream   │    │SpokenTranscript  │
   │ 60 s sanity cap │    │  Cache（自回声  │
   │ (不截断回复)    │    │  去重的真相源）  │
   └─────────────────┘    └──────────────────┘
```

### 1.2 关键模块

| 模块 | 文件 | 作用 |
|---|---|---|
| MicStream | `va_demo/audio_io.py` | 采集 PCM16 24 kHz mono；subscribe() fan-out |
| SpeakerStream | `va_demo/audio_io.py` | 播 PCM16；**60 s sanity cap，不丢实际语音**（`8f04553`） |
| WakeWordDetector | `va_demo/wake_word.py` | 后台线程 + 转录后端 + RMS 门 + 短语匹配 + 冷却 + 自回声去重 |
| FasterWhisperBackend | `va_demo/wake_word.py` | 本地 faster-whisper（默认 tiny / int8 / cpu） |
| **OpenAITranscribeBackend** | `va_demo/wake_word.py` | **云端 4o transcribe；准确率高、按次计费** |
| SpokenTranscriptCache | `va_demo/spoken_cache.py` | 记录 Sparky 自己最近说过的文本，挡掉自回声 |
| UtteranceVAD | `va_demo/utterance_vad.py` | webrtcvad 检测你说完没（24→16 kHz 重采样） |
| ConversationStateMachine | `va_demo/conversation_state.py` | 6 状态机，控制 uplink 开合与 wake_word pause/resume |
| RealtimeAgent | `va_demo/realtime_agent.py` | WS 客户端，手动 turn 控制（`turn_detection: null`），不再做自动 barge-in |

### 1.3 状态机：6 状态、wake-word 在每个状态下的开关

| 状态 | 含义 | wake_word | uplink | 进入条件 | 退出 |
|---|---|---|---|---|---|
| `IDLE` | 待机 | **ON** | OFF | 启动 / 各种 timeout | 收到 wake |
| `AWAKE` | 过渡（< 1 个 tick） | — | — | 收到 wake | 立刻进 CAPTURING |
| `CAPTURING` | 你正在说话 | **PAUSED** | **ON** | wake 触发或仍在 LISTENING_WINDOW | VAD commit / 4 s 无声 |
| `THINKING` | 已 commit，等模型首块回复 | **PAUSED** | OFF | VAD commit | `response.audio.delta` |
| `SPEAKING` | 模型在播 | **PAUSED** | OFF | 收到首块 audio delta | `response.done` |
| `LISTENING_WINDOW` | 8 s 后续追问窗 | **ON** | OFF | `response.done` | 8 s 到 → IDLE / 收到 wake → CAPTURING |

**重要不变量：**

- 在 `THINKING` 和 `SPEAKING` 期间 wake_word 都是 **PAUSED**。任何在暂停瞬间已经在途的转录结果，会被 `_on_wake_in_loop` 显式丢弃（详见 §2.2）。
- `cooldown_s`、`rms_threshold`、`SpokenTranscriptCache` 三道防御仍在，但现在是 **第二层防线**——主防线是状态机直接 pause 检测器。
- `LISTENING_WINDOW` 期间 wake_word resume，所以追问 "嗯，那再走两步" 不需要再喊唤醒词；但严格来说也允许重新说唤醒词（会触发新一轮 CAPTURING，等价于追问）。

---

## 2. 设计意图（这版的新合约）

### 2.1 唤醒词是唯一入口

`turn_detection: null` 让 OpenAI Realtime 服务器不做自动断句、也不自动回复。整个对话节奏由本地状态机驱动：

```
喊 "Hi Sparky"
    └─ wake 触发 → CAPTURING（开 uplink + 启动 4 s no-speech 倒计时）
    └─ 你说完话 → UtteranceVAD commit_silence（默认 1.5 s 静音）→ THINKING
    └─ 模型回首块音频 → SPEAKING
    └─ 模型说完 → LISTENING_WINDOW（8 s）
        ├─ 你说话 → 不需要喊唤醒词，VAD 仍会自动断句并提交
        └─ 8 s 没动静 → 回 IDLE
```

### 2.2 Barge-in 已禁用（这版的关键改动，`8f04553`）

**旧行为：** SPEAKING 中喊 "Hi Sparky" → 发 `response.cancel` → speaker.clear() → 重新进 CAPTURING。

**新行为：** SPEAKING / THINKING 中喊任何话都不打断模型；模型必须把当前 turn 说完才进 LISTENING_WINDOW。

**为什么改：**

1. WSL2 + USB 音箱场景下扬声器回灌严重，模型自己说完一句话扬声器还没放完，回灌的音频被 wake-word 误触发 → 自我打断 → 模型永远说不完话。这是改造前最痛的故障。
2. 戴耳机能物理消除回灌，但 demo 现场不一定有耳机。
3. 即使加了 `prompt 禁说 Sparky` + `RMS 门` + `自回声 dedup`，长答案 + 房间混响下仍然偶发误触。
4. 牺牲打断能力换来"模型一定能把话说完"的可预测性，对 demo 来说更重要。

**实现两道闸：**

```python
# 闸 1：状态机进入 THINKING / SPEAKING 时直接 pause
def _enter_thinking(self):
    self.wake_word.pause()    # 不再 resume()
    ...

# 闸 2：万一 pause 之前已经有一次转录在途，结果回来时直接丢
def _on_wake_in_loop(self, evt):
    if self._state in (State.SPEAKING, State.THINKING):
        log.debug("ignoring wake during %s (barge-in disabled)", self._state.value)
        return
```

**实操影响：**

- 你不能用 "Hi Sparky stop" 来打断 Sparky 的长回答。要中止只能 Ctrl-C 整个进程。
- 这是有意而为；请不要把它当 bug 报回来。
- 如果你需要打断，最快的人为方式：在系统提示里限制回答长度（`prompts.py`），或在 Realtime API 调用时设较低 `max_response_output_tokens`。

### 2.3 三层自回声防护

按顺序触发：

| 层 | 机制 | 哪里 |
|---|---|---|
| 1 | 系统提示禁止模型自称 "Sparky"（说 "I" 或 "the robot"） | `va_demo/prompts.py::REALTIME_SYSTEM_PROMPT` |
| 2 | SPEAKING/THINKING 期间 wake_word 直接 PAUSED + 状态机丢弃 in-flight 事件 | `conversation_state.py::_enter_thinking + _on_wake_in_loop` |
| 3 | SpokenTranscriptCache 6 s 窗口；如果 cache 里 6 秒内出现过 wake phrase，wake_word worker 自己也会丢匹配 | `wake_word.py::_loop` + `spoken_cache.py` |

第 2 层是新增的主防线；第 3 层是给"刚进 LISTENING_WINDOW、扬声器还在收尾、wake 又恢复了"那个尴尬窗口兜底。

### 2.4 SpeakerStream 不再截断长回复（`8f04553`）

**旧：** 4× `speaker_buffer_ms`（默认 200 ms × 4 = 800 ms）的硬上限，超过就丢老数据。Realtime WS 推流速度比实时快，长回复必然被砍头。

**新：** 60 秒 sanity cap，正常对话**永远不会触发**；唯一作用是防止失控生产者把内存吃光。中断播放只能调 `speaker.clear()`（barge-in 时用，但本版已不再有自动 barge-in）。

实操影响：

- Sparky 现在能讲完任意长的笑话/解释，不会被自己的缓冲机制截尾。
- 如果你看到 `speaker buffer exceeded sanity cap` 的 WARN 日志，那是真有 bug，不是配错。

### 2.5 RMS 门是钱包的总闸（仅对 OpenAI 后端）

OpenAI 后端每次 transcribe = 一次 HTTP 请求，按音频秒计费。`rms_threshold` 直接决定每分钟会调多少次 API。

| 阈值 | 实测对应 | 后果 |
|---|---|---|
| 0–10 | 远低于 idle 噪声 | 持续触发，2 Hz × 1.5 s × 60 s = **180 秒音频/分钟**，账单飞 |
| 100（默认） | idle ~17–30、说话 ~200–500 之间 | 安静环境一分钟可能只发 0–2 次，喊话时持续触发 |
| 1500（旧默认） | 多数环境喊到嘶哑都过不了 | 一直说没反应 |

**WSL2 + RDP 桥接的天花板大约是峰值 RMS ~300–400**，所以 1500 这个上一版默认在我的环境里根本进不来。`4ad6ecc` 把默认从 1500 降到 100 就是修这个。

---

## 3. 选后端：local vs openai

| 维度 | `local` (faster-whisper) | `openai` (4o transcribe) |
|---|---|---|
| 网络 | 不需要 | 必需，每次轮询都走 HTTPS |
| 离线 | ✓ | ✗ |
| API key | 不需要 | `OPENAI_API_KEY` |
| 首启动 | 第一次下模型（int8：tiny ~39 MB / base ~73 MB / small ~244 MB） | 立即可用 |
| 单次延迟 | ~150-400 ms（CPU int8） | ~200-500 ms 网络 RTT |
| Sparky 这种生僻词 | tiny 经常误识（→ "spike" / "spark" / "Marky"），base/small 才可靠 | 加 `prompt="Sparky"` 偏置后非常稳 |
| 计费 | 0 | 检测器 2 Hz 轮询，1.5 s 窗口；只在 RMS 过阈值时调；待机 ~$0.30-0.60/小时 |
| 适用 | 长跑、demo 后台、隐私敏感 | 短期演示、追求识别质量、网络好 |

**两种"默认"互不一致，不是 bug：**

| 入口 | 默认后端 | 在哪 |
|---|---|---|
| `python -m va_demo.main` | `openai`（gpt-4o-transcribe） | `configs/va_demo.yaml::wakeword.backend` |
| `python scripts/wake_word_debug.py` | `local`（faster-whisper tiny） | 脚本 `--backend` argparse default |

`main.py` 走 yaml；`wake_word_debug.py` 是为"无网/调阈值"场景而生的，所以 CLI 默认本地。任意后端都可以通过 `--backend` 强制切换。

**省钱小窍门：** RMS 门是关键的省钱开关。`rms_threshold=100` 意味着只有有声音才转录，安静环境一分钟可能只调 0–2 次 API。把阈值设太低（比如 10），idle 噪声也会触发 → 账单飞涨。

---

## 4. 准备

### 4.1 Conda 环境

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
pip install -r requirements.txt    # faster-whisper + webrtcvad-wheels + openai + sounddevice + ...
```

WSL2 麦克风走不通时参考 README 的「Audio prerequisites in WSL2」，常见根因是 conda env 里没 ALSA→PulseAudio plugin，需要把 `$CONDA_PREFIX/lib/alsa-lib` 软链到 `/usr/lib/x86_64-linux-gnu/alsa-lib`（已记在 user memory 里）。

### 4.2 `.env` 与 API key

`.env` 模板见 `.env.example`。

```bash
cp .env.example .env
nano .env   # 填上 OPENAI_API_KEY=sk-...
chmod 600 .env
```

每次开新终端：

```bash
set -a; source .env; set +a
```

`.env` 已经在 `.gitignore` 里，不会被提交。

> **泄密警告：** key 在任何对话或聊天记录里出现过明文，就当它泄漏了；立刻去 https://platform.openai.com/api-keys 撤销重发。

### 4.3 验证麦克风能采到声音（推荐）

```bash
python scripts/audio_loopback.py
# 5 秒内对着麦说话，应该能从扬声器听到回声 + 看到 RMS 条
```

如果 RMS 一直 < 50（典型：WSL2 + RDP 桥），说明系统增益本来就低，**这就是要把 wake-word `rms_threshold` 调低的根本原因**（已经从 1500 默认降到 100）。

### 4.4 WSL 音频增益已经满了？

```bash
pactl list sources short          # 查 input source
pactl get-default-source          # 默认是哪个
pactl list sources | grep Volume  # 增益百分比
```

WSLg/RDPSource 即使 100% 也只能给到 RMS ~300-400 峰值。这是桥接的天花板，软件层只能调阈值，没法把信号本身放大。

---

## 5. 调试脚本：`scripts/wake_word_debug.py` 完整用法

这个脚本只跑唤醒词检测器，不连 Realtime，不进状态机，方便单独调参。

### 5.1 全部参数

```
--rms <int>            RMS 门阈值，int16 振幅。默认 100。
                       静音 ~17-30，环境噪音 ~30-95，正常说话 ~200-500。

--phrase <str>         用单一短语调试（覆盖默认 "hi sparky"）。
                       生产里在 configs/va_demo.yaml::wakeword.phrases 配多条。

--backend {local,openai}
                       脚本默认 local（无网时也能跑）。
                       openai 需要 export OPENAI_API_KEY。

# local 后端专属
--model-size <str>     tiny / base / small。tiny 最快但 Sparky 经常听不出来。
--compute-type <str>   int8 / float16 / float32。CPU 通常 int8。
--device <str>         cpu / cuda。

# openai 后端专属
--openai-model <str>   gpt-4o-transcribe（更准）/ gpt-4o-mini-transcribe（便宜）
                       脚本默认 gpt-4o-transcribe。
--openai-prompt <str>  偏置词，默认 "Sparky"。给生僻名一个提示，识别率明显上去。
                       可以堆多个："Sparky G1 Unitree"

-v, --verbose          DEBUG 日志：打印每次 RMS、是否过门、转录结果、为什么没匹配
```

### 5.2 推荐工作流

**第一次新环境：跑诊断模式看 RMS 量级。**

```bash
python scripts/wake_word_debug.py --backend local --verbose
# 不喊话 5 秒：看 idle RMS 是多少
# 喊一声 hi sparky：看峰值 RMS 是多少
```

阈值挑在两者中间，留 2-3 倍裕量。比如 idle 20、shout 300，挑 100 合适。

**确认本地模型识别 Sparky：**

```bash
python scripts/wake_word_debug.py --backend local --model-size base --verbose
# 喊几次 hi sparky，看 transcript 字段是不是真的写出 "Sparky"
```

`tiny` 经常听成 "Marky" / "spike" / "spark" / "hope"。`base`（~73 MB）够稳；`small`（244 MB）更稳但加载慢。

**确认 OpenAI 4o 能用：**

```bash
set -a; source .env; set +a
python scripts/wake_word_debug.py --backend openai --verbose
# 喊几次 hi sparky；transcript 几乎一定是 "Hi, Sparky." 之类
```

### 5.3 看 verbose 输出怎么解读

```
... INFO  va_demo.audio_io: mic started: samplerate=24000, ...
... INFO  va_demo.wake_word: loading faster-whisper model_size=base ...
listening; press Ctrl-C to stop
... DEBUG va_demo.wake_word: rms gate: 18 < 100 (skip)        ← idle，没人说话
... DEBUG va_demo.wake_word: rms gate: 345 >= 100 (transcribe) ← 检测到声音，触发转录
... DEBUG va_demo.wake_word: transcript: 'Okay, hi Sparky.'    ← 模型听到的文本
WAKE @ 4035.97: 'Okay, hi Sparky.'                              ← 短语匹配成功，回调触发
... DEBUG va_demo.wake_word: rms gate: 327 >= 100 (transcribe)
... DEBUG va_demo.wake_word: transcript: 'I hope.'              ← 听错了
... DEBUG va_demo.wake_word: no phrase match in normalized='i hope' (phrases=['hi sparky'])
... DEBUG va_demo.wake_word: wake suppressed by self-echo dedup: ... ← Sparky 自己说过这词
... DEBUG va_demo.wake_word: wake suppressed by cooldown        ← 离上次唤醒不足 2 s
```

每一行对应 worker 线程一次循环（每 `1/inference_rate_hz = 0.5 s` 一次）。

**注意：** 这个调试脚本绕过状态机，所以"SPEAKING 期间也能 WAKE"在这里是正常现象（脚本根本不知道 SPEAKING）。要复现状态机行为请用 `python -m va_demo.main`。

---

## 6. 配置文件：`configs/va_demo.yaml`

唤醒词相关在 `wakeword:`、句末检测在 `utterance:`、对话状态在 `conversation:`。

```yaml
wakeword:
  enabled: true              # false 等价于 --no-wakeword
  backend: openai            # openai = gpt-4o-transcribe（云端，默认）
                             # local  = faster-whisper（离线，但 tiny 听不准 "Sparky"，
                             #          至少需 base 模型才稳定）
  # local 后端专属
  model_size: tiny           # tiny / base / small
  compute_type: int8         # int8 / float16 / float32
  device: cpu                # cpu / cuda
  # openai 后端专属
  openai_model: gpt-4o-transcribe   # gpt-4o-transcribe / gpt-4o-mini-transcribe
  openai_prompt: "Sparky"           # 偏置词，给专有名词一个提示
  # 共用
  rolling_window_s: 1.5      # 转录窗口长度。短了听不全，长了延迟大且 CPU 高
  inference_rate_hz: 2.0     # 每秒转录 2 次。降到 1 省一半 CPU/$$
  rms_threshold: 100         # 关键调参点。本环境实测：idle 20 / 说话 300 / 安全值 100
  cooldown_s: 2.0            # 唤醒后多久内不再触发
  language: null             # null = 自动；"en" / "zh" 强制可加快推理
  phrases:                   # 子串匹配，全部 lowercase + 标点替空格归一化
    - "hi sparky"
    - "hey sparky"
    - "hi sparkie"
    - "嗨 sparky"
    - "你好 sparky"

utterance:
  silence_threshold_ms: 1500 # 句末静默多久算说完
  max_duration_s: 30.0       # 单句最长，防卡死
  vad_aggressiveness: 2      # webrtcvad 0-3，越大越严
  no_speech_timeout_s: 4.0   # AWAKE 后这么久没人说话 → 回 IDLE

conversation:
  listening_window_s: 8.0    # Sparky 答完后多久还允许追问而不需要重新唤醒
  selfecho_dedup_window_s: 6.0  # Sparky 自己说过的话多久内挡住唤醒匹配
```

**默认后端：** `openai` (`gpt-4o-transcribe`)。需要 `OPENAI_API_KEY`。要切回离线 `faster-whisper`，把 `wakeword.backend` 改成 `local`（仍建议 `model_size: base` 起步，`tiny` 听不准 "Sparky"）。

**改 phrases 的注意事项：**

- 匹配是 `子串 in 规范化转写`，所以 `"hi sparky"` 会同时命中 "Hi, Sparky."、"Okay, hi sparky"、"Sparkie, hi sparky" 之类。
- 规范化只保留 `[a-z0-9]` 和 CJK 字符，其余替空格再合并。所以中英标点都不影响。
- 列表里写多条会"任一命中即触发"。生僻词容易被听岔，多写几个变体（"sparkie"、"sparking"）能显著提升召回。

---

## 7. RMS 阈值调试流程（最常见的问题）

90% 的「喊了没反应」都是 RMS 阈值 vs 实际信号不匹配。

```bash
# 1. 跑 verbose
python scripts/wake_word_debug.py --backend local --verbose

# 2. 安静 5 秒，记下 idle RMS（一般 17-30）

# 3. 用平时音量喊 5 次 "hi sparky"，记下峰值 RMS

# 4. 阈值挑在 idle*3 ~ peak/3 的中间。例：
#    idle=20, peak=300  → 阈值 60-100 都行
#    idle=50, peak=2000 → 阈值 200-500
```

**改完阈值在 3 处都改一致：**

| 文件 | 字段 | 影响 |
|---|---|---|
| `configs/va_demo.yaml` | `wakeword.rms_threshold` | 主入口 `python -m va_demo.main` |
| `va_demo/wake_word.py` | `WakeWordDetector.__init__` 默认 | 直接 import 用的代码 |
| `scripts/wake_word_debug.py` | `--rms` 默认 | 调试脚本 |

或者只改 yaml，调试时通过 `--rms <值>` 临时覆盖。

---

## 8. 跑完整 demo（含唤醒词）

四个终端的标准布置：MuJoCo + 摄像头 + va-demo（+ optional 调试脚本）。

```bash
# Terminal 1：MuJoCo 仿真
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# 进 viewer 后按 8 几次降下弹力带；可选按 9 关掉

# Terminal 2：teleimager 摄像头服务
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server

# Terminal 3：va-demo 主程序
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python -m va_demo.main
# 等到 INFO wake-word enabled: phrases=['hi sparky', ...] 出来
# 喊 "Hi Sparky"，再说请求，比如 "看看前面" / "向前走两步"
```

### 8.1 主入口 CLI flag

| Flag | 默认 | 作用 |
|---|---|---|
| `--config` | `configs/va_demo.yaml` | 配置文件 |
| `--mode {observe,confirm,active}` | `confirm`（来自 yaml） | safety 模式 |
| `--no-realtime` | off | 不连 Realtime；只跑 audio/camera/skill，方便配合调试脚本 |
| `--no-skills` | off | 不初始化 DDS / ComboController；motion 工具调用会报错但不崩 |
| `--no-wakeword` | off | 关掉唤醒词门控；麦克风持续推 Realtime（旧行为，仅 A/B 用） |
| `-v` | off | DEBUG 日志（含状态机所有 `[state] X -> Y` 与 `[wake]` / `[utterance]` 行） |

### 8.2 一次正常对话的日志样子

```
INFO va_demo: wake-word enabled: phrases=['hi sparky', ...]
INFO va_demo.audio_io: mic started: samplerate=24000, ...
INFO va_demo.audio_io: speaker started: samplerate=24000, ...
INFO va_demo.realtime_agent: connected to gpt-realtime
... 对着麦说 "Hi Sparky 看看前面" ...
INFO va_demo.conversation_state: [wake] Hi, Sparky. (state=IDLE)
INFO va_demo.conversation_state: [state] IDLE -> CAPTURING
... 1.5 秒的静默后 ...
INFO va_demo.conversation_state: [utterance] commit_silence after 2.34s
INFO va_demo.conversation_state: [state] CAPTURING -> THINKING
... 大约 300 ms ...
INFO va_demo.conversation_state: [state] THINKING -> SPEAKING
... 模型把回答放完 ...
INFO va_demo.conversation_state: [state] SPEAKING -> LISTENING_WINDOW
... 8 秒不说话 ...
INFO va_demo.conversation_state: [state] LISTENING_WINDOW -> IDLE
```

任何路径偏离这套都意味着配置或环境有问题，第 §10 节有故障速查。

---

## 9. 实地验收清单（从 `audio-awake.md` §10 提炼）

跑完上述三终端后，依次验证以下 5 个行为。任何一项不通过都先看 §10。

| # | 行为 | 期望日志 / 现象 |
|---|---|---|
| 1 | 「Hi Sparky」→「你看到什么？」 | `[wake]` → `IDLE → CAPTURING → THINKING → SPEAKING → LISTENING_WINDOW`，Sparky 念出视觉描述 |
| 2 | 「Hi Sparky 讲个长一点的笑话」+ 自己保持安静 | Sparky 必须把整个笑话说完不被打断（这是改造前最痛的回归测试） |
| 3 | 长答案中途喊「Hi Sparky stop」 | **Sparky 不应停下；wake_word 在 SPEAKING 期间是 PAUSED**（与本版前不同；详见 §2.2） |
| 4 | `--mode confirm` 重启，「Hi Sparky 走两步」 | 终端打 y/N 确认 → 按 y → MuJoCo 里机器人迈步 |
| 5 | 紧急回退：`python -m va_demo.main --no-wakeword` | 回到老的常开 Realtime 行为（用来对比验证差异；任何噪声都会被 server VAD 当 turn） |

如果 #3 真的能打断，说明你跑的不是 `feature/audio-fix` 上 `8f04553` 之后的版本，请 `git log` 确认。

---

## 10. 常见故障速查

| 现象 | 大概率原因 | 验证方法 | 修法 |
|---|---|---|---|
| 喊 hi sparky 没任何 WAKE | RMS 阈值过高 | `--verbose` 看 `rms gate: X < N (skip)` | 调低 `rms_threshold` |
| RMS 过了但 transcript 不对 | tiny 模型识别 "Sparky" 差 | 看 `transcript:` 行内容 | 换 `--model-size base` 或 `--backend openai` |
| transcript 全是空字符串 `''` | 信号太弱被 whisper 内置 VAD 过滤；或仅短促咳嗽 | 看是不是 RMS 在 100-150 边缘 | 提高音量；或临时去掉 `vad_filter`（改源码） |
| 唤醒一次后死活不再触发 | 冷却太长 / 自回声去重在挡 | 看 `wake suppressed by cooldown` / `wake suppressed by self-echo dedup` | 调小 `cooldown_s` 或检查 SpokenTranscriptCache 写入 |
| 模型说一半我又喊 Hi Sparky 不打断 | **这是设计**（§2.2，barge-in 已禁用） | 日志里有 `ignoring wake during SPEAKING` | 不修。要打断只能 Ctrl-C |
| Sparky 自己念到 "Sparky" 把自己唤醒 | 系统提示没生效，或恢复后 LISTENING_WINDOW 内回灌触发 | 看 `va_demo/prompts.py::REALTIME_SYSTEM_PROMPT` 是否含 "never refer to yourself as Sparky" | prompts.py 必须保留这条；retry |
| 主入口报 `OPENAI_API_KEY is not set` | 没 `source .env` | `echo $OPENAI_API_KEY` | `set -a; source .env; set +a` |
| 主入口报 `unknown wakeword.backend=...` | yaml 里 backend 写错 | 看 `configs/va_demo.yaml::wakeword.backend` | 只允许 `openai` 或 `local` |
| `ModuleNotFoundError: faster_whisper` | 包没装 | `pip list \| grep -i whisper` | `pip install -r requirements.txt` |
| 第一次启动卡 30 秒+ 没动静 | tiny 模型在下载 | `ls ~/.cache/huggingface/hub` | 等下载完；或先手动 `huggingface-cli download Systran/faster-whisper-tiny` |
| `OpenAITranscribeBackend` 报 401 | key 错或被 revoke | `openai api models.list`（或 curl） | 重发 key 写进 `.env` |
| `OpenAITranscribeBackend` 报 connection error | 网络挂或外网墙 | `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"` | 检查代理 / VPN |
| RMS 一直是 0 / mic 沉默 | sounddevice 拿不到 input device | `python -c "import sounddevice as sd; print(sd.query_devices())"` | 见 README「Audio prerequisites in WSL2」 |
| 长答案被截断 / 后半句听不到 | **本版应已修**（§2.4，sanity cap 60 s） | 看是否有 `speaker buffer exceeded sanity cap` WARN | 没 WARN 还截断 → 网络抖动；有 WARN → 真 bug，开 issue |
| 4 秒沉默后回 IDLE，但你才刚要说 | `no_speech_timeout_s` 太短 | 唤醒后看 `[capture] no speech for 4.0s after wake; aborting` | 调大 `utterance.no_speech_timeout_s` |
| LISTENING_WINDOW 8 秒还没说完追问 | 窗口太短 | 日志里 `LISTENING_WINDOW -> IDLE` 出来太早 | 调大 `conversation.listening_window_s` |

---

## 11. 测试

```bash
cd ~/unitree/unitree-notes/va-demo

# 全量
python -m pytest tests/ -v

# 仅唤醒词相关（不依赖 faster-whisper / openai；用 FakeBackend 注入脚本化 transcript）
python -m pytest \
    tests/test_wake_word.py \
    tests/test_spoken_cache.py \
    tests/test_utterance_vad.py \
    tests/test_conversation_state.py \
    tests/test_audio_io_fanout.py -v
```

整个套件设计成不依赖网络也不需要 GPU/whisper。`test_conversation_state.py` 用 `FakeWake / FakeVAD / FakeAgent`，`_force_state` 测试钩子让我们能精确测 wake-during-SPEAKING（§2.2 的"丢弃 in-flight 事件"分支）这种边。

---

## 12. 改了源码想生效

修改 `va_demo/wake_word.py` 等模块后：

```bash
# 重启 wake_word_debug.py 即可，没有缓存
python scripts/wake_word_debug.py --verbose

# 改了 config 也是重启
# 改了 prompts.py 必须重启 va_demo.main，Realtime session 会用新提示重连
```

`OpenAITranscribeBackend` 那次改的是 `wake_word.py`，要重启脚本/主程序才会生效。`.pyc` 不用清。

---

## 13. 已知不支持 / 不在范围

故意没做的事，写在这里好让你知道边界（详见 spec §16 / `audio-awake.md` §11）：

- **声学回声消除（AEC）。** 戴耳机已物理解决；扬声器场景靠 prompt + RMS + dedup + barge-in 禁用 四层防御。要做产品级再上 `webrtc-audio-processing` 或 `speexdsp`。
- **打断模型回复（barge-in）。** 已禁用，§2.2 详述。要恢复需把 `_enter_thinking()` 里的 `pause()` 改回 `resume()` 并恢复 `_cancel_then_capture` 协程。
- **自定义唤醒词模型训练。** 只改 yaml 里的 `phrases`，子串匹配。
- **多用户区分。** 两个人同时喊 "hi sparky" 视作一次。
- **GPU 推理。** tiny + int8 + CPU 单次 < 100 ms 够用；想换 `device: cuda` 就改 yaml。
- **真机部署。** 本改动只动 `va-demo` 一个目录。
- **断线重连。** Realtime ws 中途断 → 退出，让用户重启。

---

## 14. 参考

- 实现总结（按 commit 顺序）：[`docs/audio-awake.md`](audio-awake.md)
- 设计 spec：`docs/superpowers/specs/2026-05-04-wake-word-design.md`
- 实施 plan：`docs/superpowers/plans/2026-05-04-wake-word-implementation.md`
- 整体 README：[`../README.md`](../README.md)
- 相关源码（按修改频率）：
  - `va_demo/conversation_state.py` — 状态机，行为合约的核心
  - `va_demo/wake_word.py` — 检测器 + 两个后端实现
  - `va_demo/realtime_agent.py` — turn_detection=null + uplink 门 + spoken_cache 写入
  - `va_demo/audio_io.py` — MicStream fan-out 与 SpeakerStream sanity cap
  - `va_demo/prompts.py` — 第一道自回声防护
  - `va_demo/main.py` — 接线
  - `configs/va_demo.yaml` — 调参入口
