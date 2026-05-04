# va-demo 唤醒词与音频流水线 — 使用指南

> 配套文档：[`audio-awake.md`](audio-awake.md) 讲**为什么这样实现**；本文档讲**怎么用、怎么调、出问题怎么查**。

---

## 0. 一句话总结

把麦克风插好、conda 进 `agi` 环境、写好 `.env`，然后选一个后端跑：

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a   # 把 OPENAI_API_KEY 之类导出来

# 路线 A — 本地离线（faster-whisper），零网络费用
python scripts/wake_word_debug.py --backend local --model-size base --verbose

# 路线 B — OpenAI 4o transcribe（默认），云端识别 Sparky 这种生僻词更准
python scripts/wake_word_debug.py --backend openai --verbose

# 真用：跑完整 demo（自动加唤醒词门控 + Realtime 对话）
python -m va_demo.main
```

对着麦克风喊 "**Hi Sparky**" — 看到 `WAKE @ ...` 就成。

---

## 1. 你在用的是什么

```
                      ┌─────────────┐
   USB / WSLg 麦克风 ─▶│ MicStream   │ 24 kHz int16 mono，50 ms 一块
                      │ (sounddevice)│ subscribe() fan-out 给多个消费者
                      └──────┬──────┘
                             │ 原始 PCM
            ┌────────────────┼────────────────┐
            ▼                                 ▼
   ┌─────────────────┐              ┌──────────────────┐
   │WakeWordDetector │              │ UtteranceVAD     │
   │ rolling 1.5 s   │              │ webrtcvad        │
   │ 每 0.5 s 转录   │              │ 句末静音检测     │
   │  + RMS 门 100   │              └────────┬─────────┘
   │  + 自回声去重   │                       │ commit
   └────────┬────────┘                       │
            │ on_wake(...)                   │
            ▼                                 ▼
   ┌─────────────────────────────────────────────────┐
   │ ConversationStateMachine (5 状态)               │
   │ IDLE → AWAKE → LISTENING → RESPONDING → WINDOW  │
   └────────┬────────────────────────────────────────┘
            │ open uplink / commit / cancel
            ▼
   ┌─────────────────┐    ┌──────────────────┐
   │ RealtimeAgent   │ ─▶ │ OpenAI Realtime  │
   │ (WebSocket)     │ ◀─ │  (LLM + 语音)    │
   └────────┬────────┘    └──────────────────┘
            │ audio delta + transcript
            ▼
   ┌─────────────────┐    ┌──────────────────┐
   │ SpeakerStream   │    │SpokenTranscript  │
   │ (sounddevice)   │    │  Cache (去重源) │
   └─────────────────┘    └──────────────────┘
```

**关键事实：**

| 模块 | 文件 | 作用 |
|---|---|---|
| MicStream | `va_demo/audio_io.py` | 采集 PCM16 24 kHz mono；fan-out 多消费者 |
| WakeWordDetector | `va_demo/wake_word.py` | 后台线程 + 转录后端 + RMS 门 + 短语匹配 + 冷却 + 自回声去重 |
| FasterWhisperBackend | `va_demo/wake_word.py` | 本地 faster-whisper（默认 tiny / int8 / cpu） |
| **OpenAITranscribeBackend** | `va_demo/wake_word.py` | **云端 4o transcribe；准确率高、按次计费** |
| SpokenTranscriptCache | `va_demo/spoken_cache.py` | 记录 Sparky 自己最近说过的文本，挡掉自回声 |
| UtteranceVAD | `va_demo/utterance_vad.py` | webrtcvad 检测你说完没 |
| ConversationStateMachine | `va_demo/conversation_state.py` | 5 状态机，控制 uplink 开合 |
| RealtimeAgent | `va_demo/realtime_agent.py` | WS 客户端，手动 turn 控制（`turn_detection: null`） |

---

## 2. 选后端：local vs openai

| 维度 | `local` (faster-whisper) | `openai` (4o transcribe) |
|---|---|---|
| 网络 | 不需要 | 必需，每次轮询都走 HTTPS |
| 离线 | ✓ | ✗ |
| API key | 不需要 | `OPENAI_API_KEY` |
| 首启动 | 第一次下模型（tiny ~75 MB / base ~73 MB / small ~244 MB） | 立即可用 |
| 单次延迟 | ~150-400 ms（CPU int8） | ~200-500 ms 网络 RTT |
| Sparky 这种生僻词 | tiny 经常误识（→ "spike" / "spark" / "Marky"），base/small 才可靠 | 加 `prompt="Sparky"` 偏置后非常稳 |
| 计费 | 0 | 检测器 2 Hz 轮询，1.5 s 窗口；只在 RMS 过阈值时调；待机 ~$0.30-0.60/小时 |
| 适用 | 长跑、demo 后台、隐私敏感 | 短期演示、追求识别质量、网络好 |

**用户的默认选择：** `--backend openai --openai-model gpt-4o-transcribe`（已在脚本里设为默认）。

**省钱小窍门：** RMS 门是关键的省钱开关。`rms_threshold=100` 意味着只有有声音才转录，安静环境一分钟可能只调 0–2 次 API。把阈值设太低（比如 10），idle 噪声也会触发 → 账单飞涨。

---

## 3. 准备

### 3.1 Conda 环境

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
pip install -r requirements.txt    # faster-whisper + webrtcvad-wheels + openai + sounddevice + ...
```

WSL2 麦克风走不通时参考 README 的「Audio prerequisites in WSL2」，常见根因是 conda env 里没 ALSA→PulseAudio plugin，需要把 `$CONDA_PREFIX/lib/alsa-lib` 软链到 `/usr/lib/x86_64-linux-gnu/alsa-lib`（已记在 user memory 里）。

### 3.2 `.env` 与 API key

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

### 3.3 验证麦克风能采到声音（可选但建议）

```bash
python scripts/audio_loopback.py
# 5 秒内对着麦说话，应该能从扬声器听到回声 + 看到 RMS 条
```

如果 RMS 一直 < 50（比如 WSL2 + RDP 桥），说明系统增益本来就低，**这就是要调低 wake-word `rms_threshold` 的根本原因**（已经从 1500 默认降到 100）。

### 3.4 WSL 音频增益已经满了？

```bash
pactl list sources short          # 查 input source
pactl get-default-source          # 默认是哪个
pactl list sources | grep Volume  # 增益百分比
```

WSLg/RDPSource 里 100% 也只能给到 RMS ~300-400 峰值。这是桥接的天花板，软件层只能调阈值，没法把信号本身放大。

---

## 4. 调试脚本：`scripts/wake_word_debug.py` 完整用法

这个脚本只跑唤醒词检测器，不连 Realtime，方便单独调参。

### 4.1 全部参数

```
--rms <int>            RMS 门阈值，int16 振幅。默认 100。
                       静音 ~17-20，环境噪音 ~30-95，正常说话 ~200-500。

--phrase <str>         用单一短语调试（覆盖默认 "hi sparky"）。
                       生产里在 configs/va_demo.yaml::wakeword.phrases 配多条。

--backend {local,openai}
                       local  = faster-whisper（默认离线）
                       openai = 4o transcribe（默认，需要 API key）

# local 后端专属
--model-size <str>     tiny / base / small。tiny 最快但 Sparky 经常听不出来。
--compute-type <str>   int8 / float16 / float32。CPU 通常 int8。
--device <str>         cpu / cuda。

# openai 后端专属
--openai-model <str>   gpt-4o-transcribe（默认，更准）/ gpt-4o-mini-transcribe（便宜）
--openai-prompt <str>  偏置词，默认 "Sparky"。给生僻名一个提示，识别率明显上去。
                       可以堆多个："Sparky G1 Unitree"

-v, --verbose          DEBUG 日志：打印每次 RMS、是否过门、转录结果、为什么没匹配
```

### 4.2 推荐工作流

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

`tiny` 经常听成 "Marky" / "spike" / "spark" / "hope"。`base` 在 ~70 MB 体积下能识别 Sparky。`small` 更稳但占 244 MB。

**确认 OpenAI 4o 能用：**

```bash
set -a; source .env; set +a
python scripts/wake_word_debug.py --backend openai --verbose
# 喊几次 hi sparky；transcript 几乎一定是 "Hi, Sparky." 之类
```

### 4.3 看 verbose 输出怎么解读

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
... DEBUG va_demo.wake_word: wake suppressed by cooldown        ← 离上次唤醒不足 1 s
```

每一行对应 worker 线程一次循环（每 `1/inference_rate_hz = 0.5 s` 一次）。

---

## 5. 配置文件：`configs/va_demo.yaml`

唤醒词相关在 `wakeword:`、句末检测在 `utterance:`、对话状态在 `conversation:`。

```yaml
wakeword:
  enabled: true              # false 等价于 --no-wakeword
  model_size: tiny           # local 后端：tiny / base / small
  compute_type: int8         # local 后端：int8 / float16 / float32
  device: cpu                # local 后端：cpu / cuda
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

**注意：** 主入口 `va_demo/main.py` 当前**只支持 `local` 后端**（构造 `FasterWhisperBackend`）。如果想在 prod 里用 4o，要么扩 main.py 支持 backend 选项，要么先用 wake_word_debug.py 验证设计后再决定要不要切。

---

## 6. RMS 阈值调试流程（最常见的问题）

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

## 7. 跑完整 demo（含唤醒词）

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

**主入口 CLI flag：**

| Flag | 默认 | 作用 |
|---|---|---|
| `--config` | `configs/va_demo.yaml` | 配置文件 |
| `--mode {observe,confirm,active}` | `confirm` | safety 模式 |
| `--no-realtime` | off | 不连 Realtime；只跑 audio/camera/skill，方便配合调试脚本 |
| `--no-skills` | off | 不初始化 DDS / ComboController；motion 工具调用会报错但不崩 |
| `--no-wakeword` | off | 关掉唤醒词门控；麦克风持续推 Realtime（旧行为，仅 A/B 用） |
| `-v` | off | DEBUG 日志 |

---

## 8. 常见故障速查

| 现象 | 大概率原因 | 验证方法 | 修法 |
|---|---|---|---|
| 喊 hi sparky 没任何 WAKE | RMS 阈值过高 | `--verbose` 看 `rms gate: X < N (skip)` | 调低 `rms_threshold` |
| RMS 过了但 transcript 不对 | tiny 模型识别 "Sparky" 差 | 看 `transcript:` 行内容 | 换 `--model-size base` 或 `--backend openai` |
| transcript 全是空字符串 `''` | 信号太弱被 whisper 内置 VAD 过滤；或仅短促咳嗽 | 看是不是 RMS 在 100-150 边缘 | 提高音量或临时关 `vad_filter`（改源码） |
| 唤醒一次后死活不再触发 | 冷却太长 / 自回声去重在挡 | 看 `wake suppressed by cooldown` / `wake suppressed by self-echo dedup` | 调小 `cooldown_s` 或检查 SpokenTranscriptCache 写入 |
| 主入口报 `OPENAI_API_KEY is not set` | 没 `source .env` | `echo $OPENAI_API_KEY` | `set -a; source .env; set +a` |
| `ModuleNotFoundError: faster_whisper` | 包没装 | `pip list \| grep -i whisper` | `pip install -r requirements.txt` |
| 第一次启动卡 30 秒+ 没动静 | tiny 模型在下载 | `ls ~/.cache/huggingface/hub` | 等下载完；或先手动 `huggingface-cli download Systran/faster-whisper-tiny` |
| `OpenAITranscribeBackend` 报 401 | key 错或被 revoke | `openai api models.list` | 重发 key 写进 `.env` |
| `OpenAITranscribeBackend` 报 connection error | 网络挂或外网墙 | `curl https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY"` | 检查代理 / VPN |
| RMS 一直是 0 / mic 沉默 | sounddevice 拿不到 input device | `python -c "import sounddevice as sd; print(sd.query_devices())"` | 见 README「Audio prerequisites in WSL2」 |
| Sparky 边说边自我打断 | 已修过；旧行为 | 你不应该看到 | 确认在 feature/audio-fix 分支上、配置 `wakeword.enabled: true` |

---

## 9. 测试

```bash
cd ~/unitree/unitree-notes/va-demo

# 全量
python -m pytest tests/ -v

# 仅唤醒词相关
python -m pytest tests/test_wake_word.py tests/test_spoken_cache.py tests/test_utterance_vad.py tests/test_conversation_state.py -v
```

`test_wake_word.py` 用 `FakeBackend` 注入脚本化的 transcript，所以不依赖 faster-whisper / openai 也能跑通。

---

## 10. 改了源码想生效

修改 `va_demo/wake_word.py` 等模块后：

```bash
# 重启 wake_word_debug.py 即可，没有缓存
python scripts/wake_word_debug.py --verbose

# 改了 config 也是重启
```

`OpenAITranscribeBackend` 那次改的是 `wake_word.py`，要重启脚本/主程序才会生效。`.pyc` 不用清。

---

## 11. 参考

- 实现总结：[`docs/audio-awake.md`](audio-awake.md)
- 设计 spec：`docs/superpowers/specs/2026-05-04-wake-word-design.md`
- 实施 plan：`docs/superpowers/plans/2026-05-04-wake-word-implementation.md`
- 整体 README：[`../README.md`](../README.md)
