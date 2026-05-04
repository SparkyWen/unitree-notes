# va-demo 唤醒词改造完成总结

**Branch:** `feature/audio-fix`
**Date:** 2026-05-04
**Tests:** 49 / 49 通过

---

## 1. 解决的问题

原 `realtime_agent.py` 用 OpenAI Realtime 的 `server_vad` 做轮次检测，两个根本性故障：

1. **Sparky 自我打断** —— 麦克风录到了自己 TTS 的回放，server VAD 认为"用户在说话"，于是 `speaker.clear()` 把 Sparky 自己的回复打断了。结果就是 Sparky 永远说不完一句话。
2. **触发太敏感** —— 任何咳嗽、清嗓子、背景嘀咕都会被当成一次完整 turn 提交给模型。

---

## 2. 设计决策（已与您逐项确认）

| # | 项目 | 选择 |
|---|---|---|
| 1 | 唤醒词检测后端 | `faster-whisper` `tiny`（int8、CPU），首跑下载约 75 MB |
| 2 | 唤醒后对话生命周期 | 单轮 + 8 秒短窗口模式（回复后 8 秒内不需重新唤醒） |
| 3 | 自回声防护 | 系统提示禁说「Sparky」+ 麦克风 RMS 门控 + 已说文本去重（C 方案）|
| 4 | 句末检测 | `webrtcvad` 主动度 2，**1500 ms** 静音阈值，**30 s** 最长录音 |

---

## 3. 已完成任务

| # | 任务 | 状态 | 提交 |
|---|---|---|---|
| T1 | 加依赖 `faster-whisper` + `webrtcvad-wheels` 并安装 | ✅ | `3dcc12b` |
| T2 | `SpokenTranscriptCache` + 5 个单元测试 (TDD) | ✅ | `5bfe060` |
| T3 | `UtteranceVAD`（24 kHz → 16 kHz 重采样、30 ms 帧）+ 7 个单元测试 (TDD) | ✅ | `b157971` |
| T4 | `WakeWordDetector`（可注入后端、RMS 门控、冷却、去重）+ 7 个单元测试 (TDD) | ✅ | `dc408ae` |
| T5 | `MicStream.subscribe()` fan-out（多消费者共享同一份麦克风音频）+ 1 个单元测试 | ✅ | `230a005` |
| T6 | `prompts.py` 加「Sparky 不许自称 Sparky」规则 | ✅ | `88f5e74` |
| T7 | `TTSClient` 写入 `SpokenTranscriptCache`（自回声去重的 writer 之一） | ✅ | `88f5e74` |
| T8 | `RealtimeAgent` 手动控制：`turn_detection: null`、`commit_and_respond` / `cancel_response` / `set_uplink_enabled`、移除自动 barge-in | ✅ | `69f6500` |
| T9 | `ConversationStateMachine`（5 状态：IDLE / AWAKE / CAPTURING / THINKING / SPEAKING / LISTENING_WINDOW）+ 7 个单元测试 (TDD) | ✅ | `e42c5e9` |
| T10 | `main.py` 接线：构建 cache / vad / wake / sm，传给 agent；新增 `--no-wakeword` flag | ✅ | `06cc8d2` |
| T11 | `configs/va_demo.yaml` 新增 `wakeword:` / `utterance:` / `conversation:` 三段 | ✅ | `06cc8d2` |
| T12 | `scripts/wake_word_debug.py` —— 实时麦克风调参脚本（不连 Realtime） | ✅ | `06cc8d2` |
| T13 | `README.md` 新增 *Wake word* 一节 + CLI flag 表更新 | ✅ | `541a941` |
| T14 | 全量测试 sweep + 全模块导入冒烟 | ✅ | 49/49 通过 |
| T15 | MuJoCo 实地烟测 | 待您手动跑 | 步骤见 plan §15 |

---

## 4. 状态机（架构核心）

```
                     wake match
                ┌──────────────────────►  AWAKE  (~0 ms 过渡)
                │                           │
                │                           ▼
              IDLE                     CAPTURING
              ▲ ▲                          │
              │ │                          │ silence ≥ 1500 ms
              │ │                          │   或 length ≥ 30 s
              │ │                          ▼
              │ │   no_speech_timeout    THINKING (commit + response.create)
              │ └────────────────────────  │
              │     (4 s 默认)             │ response.audio.delta
              │                            ▼
              │  window expires        SPEAKING
              │ ┌────────────────────────  │
              │ │                          │ response.done
              │ │                          ▼
              │ └─────────────  LISTENING_WINDOW (8 s)
              ▼
              IDLE

   特殊边：
   * SPEAKING + 唤醒词命中 → cancel_response → speaker.clear() → CAPTURING
   * THINKING + 唤醒词命中 → response.cancel → CAPTURING
```

---

## 5. 新增 / 修改文件清单

**新文件**
- `va_demo/spoken_cache.py`
- `va_demo/utterance_vad.py`
- `va_demo/wake_word.py`
- `va_demo/conversation_state.py`
- `tests/test_spoken_cache.py`
- `tests/test_utterance_vad.py`
- `tests/test_wake_word.py`
- `tests/test_audio_io_fanout.py`
- `tests/test_conversation_state.py`
- `scripts/wake_word_debug.py`
- `pytest.ini`
- `docs/superpowers/specs/2026-05-04-wake-word-design.md`
- `docs/superpowers/plans/2026-05-04-wake-word-implementation.md`

**修改文件**
- `requirements.txt` —— 加 `faster-whisper>=1.0.3`、`webrtcvad-wheels>=2.0.14`
- `configs/va_demo.yaml` —— 新增 `wakeword` / `utterance` / `conversation` 三段
- `va_demo/audio_io.py` —— `MicStream.subscribe()` fan-out
- `va_demo/realtime_agent.py` —— 手动 turn 控制 + spoken_cache 写入 + 回调
- `va_demo/main.py` —— 整体接线 + `--no-wakeword` flag
- `va_demo/prompts.py` —— 「不许自称 Sparky」规则
- `va_demo/tts.py` —— 写入 `SpokenTranscriptCache`
- `README.md` —— 新增 *Wake word* 章节

---

## 6. 关键配置（`configs/va_demo.yaml`）

```yaml
wakeword:
  enabled: true
  model_size: tiny           # tiny / base / small
  compute_type: int8         # int8 / float16 / float32
  device: cpu                # cpu / cuda
  rolling_window_s: 1.5
  inference_rate_hz: 2.0
  rms_threshold: 1500        # 麦克风音量门槛，根据您的麦克风调
  cooldown_s: 2.0
  language: null             # null = 自动；"en" 或 "zh" 强制
  phrases:
    - "hi sparky"
    - "hey sparky"
    - "hi sparkie"
    - "嗨 sparky"
    - "你好 sparky"

utterance:
  silence_threshold_ms: 1500   # 您要求略长一点
  max_duration_s: 30.0          # 您要求 30 秒
  vad_aggressiveness: 2
  no_speech_timeout_s: 4.0      # 唤醒后 4 秒没说话 → 回 IDLE

conversation:
  listening_window_s: 8.0
  selfecho_dedup_window_s: 6.0
```

---

## 7. 怎么跑

### 一次性：调唤醒词阈值

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python scripts/wake_word_debug.py        # 默认 rms=1500
# 喊几句 "Hi Sparky"，看到 WAKE 行就对了
# 不动就 --rms 800；猛动就 --rms 2500
# 调到合适后写进 configs/va_demo.yaml::wakeword.rms_threshold
```

### MuJoCo 全流程（3 个终端，每个先 `conda activate agi`）

T1 仿真器：
```bash
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# 在 viewer 里按 8 几次降下吊带；可选按 9 关闭
```

T2 摄像头服务：
```bash
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

T3 va-demo：
```bash
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main --mode observe -v   # 不能动腿，先验视觉+对话
# 后续验证动作时换 --mode confirm（每个动作要 y 确认）
```

### 紧急回退

需要旧的「永远在听」行为时：
```bash
python -m va_demo.main --no-wakeword
```

---

## 8. 测试一览

```
$ python -m pytest tests/ -v
=========================== 49 passed in 6.06s ===========================
```

明细：
- `test_safety.py` 14 个（已有）
- `test_skills_mock.py` 9 个（已有）
- `test_spoken_cache.py` 5 个（新）
- `test_utterance_vad.py` 7 个（新）
- `test_wake_word.py` 7 个（新）
- `test_audio_io_fanout.py` 1 个（新）
- `test_conversation_state.py` 7 个（新）

---

## 9. 提交历史（feature/audio-fix）

```
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

## 10. 待您验证的实地行为（plan §15）

1. **唤醒词单测** —— `wake_word_debug.py` 喊 "Hi Sparky" 能稳定 WAKE。
2. **唤醒 + 视觉问句** —— "Hi Sparky" → "你看到什么？" → describe_scene 工具被调用 → Sparky 回答 → 8 秒 LISTENING_WINDOW → 自动回 IDLE。
3. **自不打断回归** —— 让 Sparky 讲长一点的笑话；自己保持安静；Sparky 必须把整个回答说完（这是原 bug 的根本测试）。
4. **唤醒词中途打断** —— Sparky 讲长答案过程中喊 "Hi Sparky stop"；声音应立即切断、状态进 CAPTURING。
5. **运动指令（confirm 模式）** —— "Hi Sparky 走两步" → 终端出 y/N 提示 → 按 y → MuJoCo 里机器人迈步。

跑通就可以推上去做 PR；某条没过就回到本文档里找对应模块的代码。

---

## 11. 下一步选择

跑完上面五条后，再回 `feature/audio-fix` 上做：
- **本地 merge 进 main**（适合先用一段时间）
- **推 origin + 开 PR**（适合让团队 review）
- **保留分支不动**（适合还要继续打磨）
