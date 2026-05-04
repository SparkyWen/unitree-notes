# va-demo 唤醒词 + Barge-in 改造完成总结

**Branch:** `feature/audio-fix`
**完成日期:** 2026-05-04
**测试结果:** 49 / 49 通过
**变动规模:** 22 个文件，+4538 / -60 行

---

## 0. 一句话概括

把 va-demo 的语音入口从「OpenAI server VAD 永远在听」改成「`faster-whisper` 本地唤醒词 → 本地 webrtcvad 句末检测 → 一次性提交给 Realtime」，并加了一个 5 状态的对话状态机驱动 mic 与 Realtime 的开合。结果：Sparky 不再被自己说的话打断，只有「Hi, Sparky」能打断 Sparky 中途的回复，您说完一段会自动整段提交。

---

## 1. 解决的两个具体故障

### 故障 1：Sparky 自我打断
原 `realtime_agent.py` 在收到 `input_audio_buffer.speech_started` 事件时无条件 `speaker.clear()`：
```python
elif t == "input_audio_buffer.speech_started":
    self.speaker.clear()  # barge-in: stop playback when user speaks
```
WSL2 + USB 麦克风环境下，Sparky 的 TTS 从扬声器回灌进麦克风，server VAD 把这个回灌当成了用户讲话，自动 commit + 触发 barge-in，结果 Sparky 永远说不完一句话。

### 故障 2：触发太敏感
`server_vad` + `silence_duration_ms=500` 对正常对话是可用的，但对 demo 这种"想到才开口"的场景，任何咳嗽 / 鼠标声 / 短促回应都会被当成完整 turn 提交给模型，模型再被迫生成回复 → 进一步加剧故障 1。

---

## 2. 与您逐项确认的设计决策

| # | 项目 | 选择 | 您的偏好备注 |
|---|---|---|---|
| 1 | 唤醒词后端 | `faster-whisper` `tiny` (int8 / CPU) | 完全离线、零账号、首次跑下载 ~75 MB 模型到 `~/.cache/huggingface` |
| 2 | 唤醒后对话生命周期 | 单轮 + 8 秒 LISTENING_WINDOW | 既保持单轮可预测性，又允许追问"那再走两步"无需重复唤醒 |
| 3 | 自回声防护 | 系统提示禁说 "Sparky" + RMS 门控 + 已说文本去重 | 您选 C：A 的零依赖 + 文本去重兜底 |
| 4 | 句末检测 | `webrtcvad` 主动度 2，**1500 ms** 静音阈值，**30 s** 最长 | 您要求"最大静音阈值长一点、最长 30 s" |

---

## 3. 完整执行流水线（按 commit 顺序）

### Phase A — 设计

| Commit | 内容 |
|---|---|
| `ffc8447` | `docs/superpowers/specs/2026-05-04-wake-word-design.md`（388 行 spec） |
| `bc9c63f` | `docs/superpowers/plans/2026-05-04-wake-word-implementation.md`（2439 行 plan，15 个任务） |

### Phase B — 实现（按 TDD：先红、后绿、再提交）

| Commit | 任务 | 关键变更 |
|---|---|---|
| `3dcc12b` | T1 加依赖 | `requirements.txt` += `faster-whisper>=1.0.3`、`webrtcvad-wheels>=2.0.14`；pip 安装 + 导入冒烟 |
| `5bfe060` | T2 `SpokenTranscriptCache` | 线程安全 deque of `(text, monotonic_ts)`，`add()` / `recent_text(window_s)`；5 个单测 |
| `b157971` | T3 `UtteranceVAD` | 24 kHz → 16 kHz 重采样（每 3 输入产 2 输出，跨调用保留 24k 与 16k 两段 leftover），30 ms 帧切片，返回 `continue` / `commit_silence` / `commit_max`；7 个单测；可注入 fake VAD 因为真 webrtcvad 不认正弦波 |
| `dc408ae` | T4 `WakeWordDetector` | 后台线程跑可注入 backend；rolling 1.5 s 缓冲；RMS 门控 + 冷却 + 自回声去重；7 个单测（fake backend）+ 真 `FasterWhisperBackend` 实现 |
| `230a005` | T5 `MicStream.subscribe()` fan-out | 从单消费者队列改成多 listener；老的 `mic.queue` 仍是首个 subscriber 的别名（向后兼容）；1 个单测 |
| `88f5e74` | T6+T7 prompts + tts | 系统提示加"never refer to yourself as Sparky"；TTSClient 接受 `spoken_cache` 参数，在 `speak()` 之前写入 cache |
| `69f6500` | T8 `RealtimeAgent` 手动 turn 控制 | `turn_detection: null`；删除自动 `speaker.clear()`；新增 `commit_and_respond` / `cancel_response` / `set_uplink_enabled`；`response.audio_transcript.delta/done` 写入 spoken_cache；`response.audio.delta` / `response.done` 触发回调 |
| `e42c5e9` | T9 `ConversationStateMachine` | 5 状态、线程安全（worker → loop 通过 `call_soon_threadsafe`）；7 个单测覆盖全部状态边 |
| `06cc8d2` | T10+T11+T12 接线 | `main.py` 构建并接入；`configs/va_demo.yaml` 新增三段；`scripts/wake_word_debug.py` 调参脚本；新 CLI flag `--no-wakeword` |
| `541a941` | T13 README | 新增「Wake word」章节 + CLI flag 表更新 |
| `3424ce3` | 总结 | `docs/audio-awake.md`（本文档） |

T14 全量测试 sweep：49/49 通过。
T15 MuJoCo 实地烟测：操作员手动跑（步骤在 plan §15 / 本文档 §10）。

---

## 4. 新增模块详解

### 4.1 `va_demo/spoken_cache.py`（40 行）

**职责：** 跟踪 Sparky 最近说过的所有文本，给唤醒词检测器去重。

**为什么需要：** Sparky 的 TTS 从扬声器回灌进麦克风时，本地 whisper 可能转出 "hi sparky" → 误唤醒。如果 cache 里 6 秒内 Sparky 自己说过 "hi sparky"，就忽略这次匹配。

**API：**
```python
class SpokenTranscriptCache:
    def __init__(self, max_age_s: float = 30.0): ...
    def add(self, text: str, t: float | None = None) -> None: ...
    def recent_text(self, window_s: float) -> str: ...   # 小写、合并、去重
```

**写入方：**
- `RealtimeAgent`：每个 `response.audio_transcript.delta` 和最终 `done` 事件
- `TTSClient`：每次 `speak(text)` 之前

**读取方：** `WakeWordDetector` 在每次匹配前查询 6 秒窗口

---

### 4.2 `va_demo/utterance_vad.py`（110 行）

**职责：** 唤醒后判断"用户说完了"，触发 commit。

**核心算法：**
1. 24 kHz mic → 16 kHz：每 3 个输入采样 `[a, b, c]` 产 2 个输出 `avg(a,b)`、`avg(b,c)`，得到正确的 16/24 = 2/3 比例
2. 16 kHz → 30 ms 帧（480 samples / 960 bytes）喂 webrtcvad
3. 跟踪 `consecutive_silence_ms`（voiced 帧时清零）和 `total_ms`
4. **关键正确性：** 跨调用同时保留 24 kHz 和 16 kHz 两段 leftover，否则会丢音（修过一个 bug：原本只保留 24k leftover，每 50 ms 块少 20 ms 音频）

**返回值：**
- `"continue"` — 还没到 commit 条件
- `"commit_silence"` — 至少听到过一次 voiced 帧、且最近 silence ≥ `silence_threshold_ms`
- `"commit_max"` — 总时长 ≥ `max_duration_s * 1000`

**测试可注入：** 真 webrtcvad 不认正弦波，所以构造函数允许传 `vad=...`，测试用 FakeVad 控制 voice/silence；同时仍保留一个用真 webrtcvad 跑 silence 流的冒烟测试。

---

### 4.3 `va_demo/wake_word.py`（189 行）

**职责：** 用本地 whisper 做关键词监听，有匹配就回调 `on_wake(WakeEvent)`。

**两个类：**

#### `FasterWhisperBackend`
真后端，包 `faster-whisper`：
- 模型大小可配（tiny / base / small）
- 计算精度可配（int8 / float16 / float32）
- 设备可配（cpu / cuda）
- 自动重采样到 16 kHz
- `vad_filter=True` 让 whisper 跳过纯静音段（省 CPU）
- `beam_size=1`、`condition_on_previous_text=False`（短窗口不要历史依赖）

#### `WakeWordDetector`
后台 daemon 线程驱动：

**主循环每 `1/inference_rate_hz` 秒（默认 0.5 s）执行：**
1. 暂停标志已置位 → skip
2. 缓冲区不足半窗口 → skip
3. 缓冲区 RMS < `rms_threshold` → skip（**第一道闸**）
4. 调 backend.transcribe()
5. 转写非空 → 规范化（小写、去标点、合并空白、保留 ASCII + CJK）
6. 任一 `phrases` 列表项是规范化转写的子串 → 否则 skip
7. **自回声去重：** `cache.recent_text(6s)` 里也含同样 phrase → skip
8. **冷却：** 距上次 fire 不到 `cooldown_s`（默认 2 s） → skip
9. 全部通过 → 调 `on_wake(WakeEvent(text, t))`

**线程接口：**
- `start()` / `stop()` — 起停 worker
- `pause()` / `resume()` — 状态机进入 CAPTURING 时 pause（避免拿用户的请求当唤醒词），离开 CAPTURING 时 resume + 清缓冲（不复触发）
- `feed(pcm)` — 状态机把每个 mic 块转发进来

---

### 4.4 `va_demo/conversation_state.py`（221 行）

**核心数据结构：**
```python
class State(Enum):
    IDLE              # 只听唤醒词；mic 不流向 Realtime
    AWAKE             # 过渡态（< 1 ms）
    CAPTURING         # 流向 Realtime + utterance VAD 跑
    THINKING          # 已 commit；等 audio.delta
    SPEAKING          # 模型在说；speaker 在播
    LISTENING_WINDOW  # 8 s 后续窗口
```

**状态转换全表：**

| From | Event | To | 副作用 |
|---|---|---|---|
| IDLE | wake match | CAPTURING | wake.pause() / vad.reset() / set_uplink_enabled(True) / 启动 4s no-speech 计时器 |
| LISTENING_WINDOW | wake match | CAPTURING | 同上 |
| SPEAKING | wake match | CAPTURING | **额外：** `await agent.cancel_response()` → speaker.clear() → 然后进 CAPTURING |
| THINKING | wake match | CAPTURING | 同 SPEAKING（cancel + recapture） |
| CAPTURING | VAD `commit_silence` 或 `commit_max` | THINKING | 取消 no-speech 计时器 / set_uplink_enabled(False) / wake.resume() / `await agent.commit_and_respond()` |
| CAPTURING | no-speech 4 s 到 + 没听到 voice | IDLE | set_uplink_enabled(False) / wake.resume() |
| THINKING | `response.audio.delta` 回调 | SPEAKING | 无副作用 |
| SPEAKING | `response.done` 回调 | LISTENING_WINDOW | 启动 8s 计时器 |
| LISTENING_WINDOW | 8s 计时器到 | IDLE | 无副作用 |

**线程模型：**
- 主循环里跑 `_consume_mic()` 协程，从 `mic.subscribe()` 拿每个块、喂给 `wake_word.feed()` 和（CAPTURING 状态下）`vad.process()`
- 唤醒事件来自 wake_word worker 线程 → `loop.call_soon_threadsafe(_on_wake_in_loop, evt)`
- Realtime 回调（`response.audio.delta`、`response.done`）也走 `call_soon_threadsafe`，保证所有状态变更都在事件循环线程

**测试覆盖：** 7 个单测（FakeWake / FakeVAD / FakeAgent）覆盖了所有上面的边，包括 `_force_state` 测试钩子让我们能精确测 wake-during-SPEAKING 这种难触发的边。

---

## 5. 修改的现有模块

### 5.1 `va_demo/audio_io.py` — `MicStream` fan-out

**改动：** 从单 `asyncio.Queue` 改成 `_listeners: List[Queue]`，`_callback` → `_enqueue_nowait` 把每个 chunk fan-out 到所有 listener。

**新方法：**
```python
def subscribe(self) -> asyncio.Queue: ...
def unsubscribe(self, q: asyncio.Queue) -> None: ...
```

**向后兼容：** `mic.queue` 仍存在，是首个 listener；这样 `RealtimeAgent._uplink()` 不需要改（它继续用 `self.mic.queue.get()`）。

---

### 5.2 `va_demo/realtime_agent.py` — 手动 turn 控制

**关键改动：**

#### a) Session 配置：
```python
"turn_detection": None,   # 之前是 server_vad
```
不再让 OpenAI 自动断句和自动回复 —— 全由我们的状态机驱动。

#### b) 删除自动 barge-in：
```python
# 原来：
elif t == "input_audio_buffer.speech_started":
    self.speaker.clear()
# 现在：
elif t == "input_audio_buffer.speech_started":
    log.debug("user speech started")
    # NOTE: do NOT clear the speaker here.
```

#### c) 上行门控：
```python
async def _uplink(self, ws):
    while True:
        chunk = await self.mic.queue.get()
        if not self._uplink_enabled.is_set():
            continue   # state machine has us muted; discard
        ...
```

#### d) 三个新公共方法：
```python
async def commit_and_respond(self):    # input_audio_buffer.commit + response.create
async def cancel_response(self):       # response.cancel + speaker.clear()
def set_uplink_enabled(self, b: bool): # 切 _uplink_enabled Event
```

#### e) 两个新回调钩子：
```python
on_response_audio_delta: Optional[Callable[[], None]] = None  # → 状态机 THINKING→SPEAKING
on_response_done:        Optional[Callable[[], None]] = None  # → 状态机 SPEAKING→LISTENING_WINDOW
```

#### f) `spoken_cache` 写入：
- `response.audio_transcript.delta` 来一条写一条
- `response.audio_transcript.done` 把完整 transcript 再写一遍

---

### 5.3 `va_demo/tts.py` — 接 spoken_cache

新增构造参数 `spoken_cache: Optional[SpokenTranscriptCache] = None`；`speak(text)` 在调 OpenAI TTS 之前先 `cache.add(text)`，让 `say` 工具的输出也走自回声去重。

---

### 5.4 `va_demo/prompts.py` — 不许自称

`REALTIME_SYSTEM_PROMPT` 增加：
> IMPORTANT: never refer to yourself as "Sparky" in your replies. Say "I" or "the robot" instead. The wake-word detector listens for "Sparky", and if you say it yourself you will accidentally interrupt your own answer.

这是防自回声的第一道闸：模型根本不说出唤醒词，自然不会被自己唤醒。

---

### 5.5 `va_demo/main.py` — 接线

把所有新组件构造起来传给 agent：

```python
spoken_cache = SpokenTranscriptCache()                     # 单例

tts_client = TTSClient(..., spoken_cache=spoken_cache)     # writer

agent = RealtimeAgent(..., spoken_cache=spoken_cache)      # writer

if not args.no_wakeword and wakeword_cfg["enabled"]:
    backend  = FasterWhisperBackend(...)                   # 加载模型（首次会下载）
    utt_vad  = UtteranceVAD(samplerate=sr, ...)
    wake     = WakeWordDetector(backend=backend,
                                 spoken_cache=spoken_cache,  # reader
                                 on_wake=lambda e: sm.handle_wake(e),
                                 ...)
    sm = ConversationStateMachine(cfg=..., wake_word=wake,
                                   utterance_vad=utt_vad,
                                   realtime_agent=agent,
                                   mic=mic)
    agent.on_response_audio_delta = sm.handle_response_audio_delta
    agent.on_response_done       = sm.handle_response_done

await sm.start()        # subscribe 麦、起 wake worker、初始 IDLE/uplink off
await agent.run()       # 进入 ws 双工循环
```

新 CLI flag：`--no-wakeword` 跳过整个状态机，agent 直接 `set_uplink_enabled(True)` 进入老的常开模式（A/B 调试用）。

---

## 6. 配置文件（`configs/va_demo.yaml`）新增三段

```yaml
wakeword:
  enabled: true
  model_size: tiny           # tiny / base / small
  compute_type: int8         # int8 / float16 / float32
  device: cpu                # cpu / cuda
  rolling_window_s: 1.5
  inference_rate_hz: 2.0
  rms_threshold: 1500        # int16 RMS；高了不灵敏，低了会误触
  cooldown_s: 2.0
  language: null             # null = 自动；"en" / "zh" 强制
  phrases:
    - "hi sparky"
    - "hey sparky"
    - "hi sparkie"
    - "嗨 sparky"
    - "你好 sparky"

utterance:
  silence_threshold_ms: 1500
  max_duration_s: 30.0
  vad_aggressiveness: 2
  no_speech_timeout_s: 4.0

conversation:
  listening_window_s: 8.0
  selfecho_dedup_window_s: 6.0
```

---

## 7. 测试矩阵（49 个，全部通过）

| 测试文件 | 覆盖范围 | 个数 |
|---|---|---|
| `test_safety.py` | 已有；safety supervisor、whitelist、bounds、modes、watchdog | 14 |
| `test_skills_mock.py` | 已有；skill backend with FakeCtl | 9 |
| `test_spoken_cache.py` | 写读、小写归一、过期淘汰、容量上限、读写线程安全 smoke | 5 |
| `test_utterance_vad.py` | continue / commit_silence / commit_max / had_any_voice / reset；fake VAD 校验帧时序；真 webrtcvad 冒烟 | 7 |
| `test_wake_word.py` | 命中、不命中、RMS 门、冷却、自回声去重、pause/resume、标点归一 | 7 |
| `test_audio_io_fanout.py` | subscribe 返回独立队列、unsubscribe 干净、legacy `mic.queue` 别名 | 1 |
| `test_conversation_state.py` | 启动状态、wake→CAPTURING、commit→THINKING、no-speech→IDLE、response.done→LISTENING_WINDOW→IDLE、wake-during-SPEAKING→cancel+recapture、audio.delta→SPEAKING | 7 |

跑命令：
```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python -m pytest tests/ -v
```

---

## 8. 行为合约（您当初提的需求 → 实现到哪儿）

| 您的需求 | 实现位置 | 边界条件 |
|---|---|---|
| 「Hi, Sparky」唤醒才进入 voice 处理 | `WakeWordDetector` + `ConversationStateMachine.IDLE`：mic 不流向 Realtime（`set_uplink_enabled(False)`） | 多种 phrase 变体（"hey sparky"、"嗨 sparky" 等）都触发 |
| Sparky 说话时不被自己生成的语音打断 | (1) `prompts.py` 禁说"Sparky"<br>(2) `WakeWordDetector` RMS 门<br>(3) `SpokenTranscriptCache` 自回声去重<br>(4) `RealtimeAgent` 删除自动 `speaker.clear()` | 前 3 是层防御，配合戴耳机时 100% 可靠 |
| 只有完整说出「Hi, Sparky」才能打断 | `ConversationStateMachine._on_wake_in_loop`：`SPEAKING/THINKING + wake → cancel_response → CAPTURING` | 唤醒词冷却 2 秒避免连续打断 |
| 说完整段后自动整段调用模型 | `UtteranceVAD` + 状态机 CAPTURING→THINKING：`commit_silence`（1500 ms 静音）或 `commit_max`（30 s 强制）触发 `commit_and_respond` | 唤醒后 4 秒无声 → 回 IDLE 不调模型 |

---

## 9. 关键提交（按时间顺序）

```
3424ce3 docs(va-demo): add Chinese summary of wake-word implementation
541a941 docs(va-demo): document wake-word usage and tuning
06cc8d2 feat(va-demo): wire wake-word + state machine into main entrypoint
e42c5e9 feat(va-demo): add ConversationStateMachine (5-state wake/capture/respond)
69f6500 feat(va-demo): manual turn control in RealtimeAgent
88f5e74 feat(va-demo): no-self-name rule + TTS writes to spoken cache
230a005 feat(va-demo): MicStream subscribe() fan-out for multi-listener audio
dc408ae feat(va-demo): add WakeWordDetector with pluggable backend
b157971 feat(va-demo): add UtteranceVAD (webrtcvad end-of-utterance)
5bfe060 feat(va-demo): add SpokenTranscriptCache for self-echo dedup
3dcc12b chore(va-demo): add faster-whisper + webrtcvad deps
bc9c63f docs(va-demo): wake-word implementation plan
ffc8447 docs(va-demo): wake-word + barge-in design spec
```

---

## 10. 您要做的实地烟测（plan §15 / 4 个终端）

### 准备
```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
# 确认依赖装好（应该已经）
python -c "from faster_whisper import WhisperModel; import webrtcvad; print('ok')"
```

### 第一步：调唤醒词阈值（不连 Realtime）
```bash
python scripts/wake_word_debug.py
# 喊几次 "Hi Sparky"，看到 WAKE 行就对了
# 不灵：python scripts/wake_word_debug.py --rms 800
# 误触：python scripts/wake_word_debug.py --rms 2500
```
调好后把数值写进 `configs/va_demo.yaml::wakeword.rms_threshold`。

### 第二步：MuJoCo 三终端
**T1（仿真）：**
```bash
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# viewer 里按 8 几次降下吊带；可选按 9 关闭
```

**T2（摄像头）：**
```bash
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

**T3（va-demo, observe 模式不动腿）：**
```bash
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main --mode observe -v
```

### 第三步：依次验证 5 个行为
1. 「Hi Sparky」→「你看到什么？」→ 应看到 `[wake]` → `[state] IDLE -> CAPTURING` → `[utterance] commit_silence` → `[state] CAPTURING -> THINKING -> SPEAKING -> LISTENING_WINDOW`，期间 Sparky 念出视觉描述。
2. 「Hi Sparky 讲个长一点的笑话」→ 自己保持安静 → Sparky 必须把整个笑话说完不被打断。**（这是原 bug 的关键回归测试。）**
3. 长答案中途说「Hi Sparky stop」→ Sparky 应立即静音、状态机进 CAPTURING。
4. `--mode confirm` 重启，「Hi Sparky 走两步」→ 终端出 y/N 确认提示 → 按 y → MuJoCo 里机器人迈步。
5. 紧急回退：`python -m va_demo.main --no-wakeword` 应该回到老的常开 Realtime 行为（用来对比验证差异）。

---

## 11. 当前不在范围内（spec §16）

故意没做的事，列出来好让您知道边界：

- **声学回声消除（AEC）。** 戴耳机已经物理解决；扬声器场景靠 prompt+RMS+dedup 三层防御足够 demo 用。要做产品级，再上 `webrtc-audio-processing` 或 `speexdsp`。
- **自定义唤醒词模型训练。** 我们用通用 whisper 做转写匹配，不需要训练；想换唤醒词只改 yaml 里的 `phrases`。
- **多用户区分。** 两个人同时喊 "hi sparky" 视作一次。
- **GPU 推理。** tiny + int8 + CPU 单次 < 100 ms，2 Hz 轮询完全够用；要换 `device: cuda` 就改 yaml。
- **真机部署。** 还在 `g1_real_demo` 那条线。本改动只动 `va-demo` 一个目录。
- **断线重连。** Realtime ws 中途断 → 退出，让用户重启。

---

## 12. 接下来您选

我已经按 `superpowers:finishing-a-development-branch` 的流程检查过：49/49 通过、工作区干净、领先 main 13 commit。请选：

1. **本地 merge 进 main**（实地烟测过的话最干净）
2. **推 origin + 开 PR**（让团队 review）
3. **保留分支不动**（继续打磨）
4. **丢弃**（不会选这个吧）

要做哪一个？

---

## 附录 A — 全部新增 / 修改文件（`git diff main..feature/audio-fix --stat`）

```
 va-demo/README.md                                  |   54 +
 va-demo/configs/va_demo.yaml                       |   27 +
 va-demo/docs/audio-awake.md                        |  本文档（242+ 行）
 va-demo/docs/superpowers/plans/...                 | 2439 ++++ (plan)
 va-demo/docs/superpowers/specs/...                 |  388 ++++ (spec)
 va-demo/pytest.ini                                 |    2 +
 va-demo/requirements.txt                           |    2 +
 va-demo/scripts/wake_word_debug.py                 |   79 +
 va-demo/tests/test_audio_io_fanout.py              |   40 +
 va-demo/tests/test_conversation_state.py           |  181 ++
 va-demo/tests/test_spoken_cache.py                 |   65 +
 va-demo/tests/test_utterance_vad.py                |  104 +
 va-demo/tests/test_wake_word.py                    |  134 ++
 va-demo/va_demo/audio_io.py                        |   51 +- (subscribe fan-out)
 va-demo/va_demo/conversation_state.py              |  221 ++ (新)
 va-demo/va_demo/main.py                            |  114 +- (接线)
 va-demo/va_demo/prompts.py                         |    8 +- (no-self-name)
 va-demo/va_demo/realtime_agent.py                  |  101 +- (manual turn)
 va-demo/va_demo/spoken_cache.py                    |   40 + (新)
 va-demo/va_demo/tts.py                             |    7 +- (cache hookup)
 va-demo/va_demo/utterance_vad.py                   |  110 + (新)
 va-demo/va_demo/wake_word.py                       |  189 ++ (新)

 22 files changed, 4538 insertions(+), 60 deletions(-)
```
