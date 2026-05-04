# va-demo 已完成内容总结

> 日期：2026-05-04
> 配套文件：`docs/va-demo-design.md`（更细的工程设计），代码仓 `~/unitree/unitree-notes/va-demo/`

本文件记录截至当前 session 已经写完并自动验证过的所有内容，作为后续接续开发的入口。

---

## 1. 用户需求 → 已交付的对应

| 用户原话 | 对应实现 |
|---|---|
| TeleImager 实时采集视频 | `va_demo/camera.py` 包装 `teleimager.image_client.ImageClient`，提供 `latest_bgr()` / `latest_jpeg_b64()` / `frame_age_seconds()` |
| 实时采集音频 | `va_demo/audio_io.py` 用 `sounddevice` 24 kHz PCM16 mono：`MicStream`（input callback → asyncio queue）+ `SpeakerStream`（输出环形缓冲） |
| OpenAI Realtime API 实时对话 | `va_demo/realtime_agent.py` 直接 raw WebSocket 到 `wss://api.openai.com/v1/realtime`；server VAD 自动断句；barge-in（用户说话时清空扬声器队列） |
| TTS 让机器人说话 | `va_demo/tts.py` 流式调用 `client.audio.speech.with_streaming_response.create(response_format="pcm")` → `SpeakerStream` |
| 发送指令让 G1 理解当前画面 | Realtime 模型暴露 `describe_scene` 工具：抽一帧 → JPEG b64 → `client.responses.create(model=gpt-5.5)` → 文本回填 → 模型用语音读出来 |
| 对图片的理解，语音说出来 | 同上：vision 文本结果作为 `function_call_output` 回送 Realtime，再 `response.create` 触发模型语音回答 |
| 保留之前的行动等能力（走路+手势） | `va_demo/skills.py` import 现有的 `g1_sim_demo/g1_sim_rl_combo.py`（**不改原文件**），把 `ComboController.set_command` / `push_arm_action` / `release_arms` 包成 async `walk` / `gesture` / `stop` / `release_arms` |
| 新写一个文件夹 va-demo，所有代码放在该文件夹下 | `~/unitree/unitree-notes/va-demo/` 下完整自包含 |

---

## 2. 文件清单

```
~/unitree/unitree-notes/va-demo/        （1785 行 Python）
├── README.md                  启动顺序 / CLI 标志 / 故障排查
├── requirements.txt           openai>=1.55, sounddevice, websockets, pyyaml, numpy, opencv-python, pyzmq
├── configs/
│   └── va_demo.yaml           model id / 音频 / 相机 / DDS / 安全限值 / 运行模式
├── va_demo/                   核心包
│   ├── __init__.py
│   ├── prompts.py             REALTIME_SYSTEM_PROMPT + VISION_SCENE_PROMPT
│   ├── audio_io.py            MicStream / SpeakerStream / rms()
│   ├── camera.py              Camera 类，包装 TeleImager ImageClient
│   ├── vision.py              VisionClient.describe()，含 Responses→chat.completions 兜底
│   ├── tts.py                 TTSClient.speak()，PCM16 流式直推扬声器
│   ├── skills.py              SkillBackend + GESTURE_KEY_MAP + build_skill_backend()
│   ├── safety.py              SafetySupervisor + WatchdogState + SafetyConfig
│   ├── realtime_agent.py      RealtimeAgent，含 _build_tool_schemas / uplink / downlink / 工具分派
│   └── main.py                CLI + asyncio 装配 + SIGINT 优雅退出
├── scripts/                   独立调试脚本
│   ├── audio_loopback.py      麦→扬声器 echo 5 秒，打印 RMS
│   ├── camera_debug.py        单帧 → Vision → 打印
│   ├── tts_debug.py           文字 → 播放
│   ├── skill_debug.py         键盘驱动 ComboController（不接 AI）
│   └── vision_loop_debug.py   1 Hz 抽帧 → Vision → 打印
└── tests/
    ├── test_safety.py         14 个用例
    └── test_skills_mock.py    8 个用例（用 FakeCtl 替身）
```

---

## 3. 架构（落地版）

```
                     ┌─────────────────────────┐
                     │   asyncio event loop    │
                     │      (va_demo.main)     │
                     └─┬─────────┬──────┬──────┘
                       │         │      │
       ┌───────────────┘         │      └──────────────────┐
       ▼                         ▼                          ▼
 ┌───────────┐            ┌──────────────┐          ┌────────────────┐
 │ MicStream │            │ Camera       │          │ ComboController│
 │  24 kHz   │            │  (TeleImager │          │  (g1_sim_demo, │
 │  PCM16    │            │   ZMQ 55555) │          │   50 Hz tick)  │
 └─────┬─────┘            └──────┬───────┘          └────────┬───────┘
       │                         │                            ▲
       │                         │                            │
       ▼                         │                            │
 ┌─────────────────────────┐     │                  ┌─────────┴──────┐
 │  RealtimeAgent          │     │                  │ SkillBackend   │
 │   - WS to OpenAI        │     │                  │ walk / gesture │
 │   - uplink: mic → API   │     │                  │ stop / release │
 │   - downlink: events    │     │                  └─────────┬──────┘
 │   - 工具分派 ───────────┼─────┼────────────────────────────┘
 │     • describe_scene ───┼─►(grab b64)─► VisionClient ─────► gpt-5.5
 │     • say          ─────┼─► TTSClient ─────────► gpt-4o-mini-tts
 │     • walk/gesture ─────┼─► SafetySupervisor.validate ─► SkillBackend
 │     • stop/release_arms ┘
 │                         │
 │   音频回放 ─────────────┼─► SpeakerStream
 └─────────────────────────┘     ▲
                                 │
                       ┌─────────┴────────┐
                       │  SpeakerStream   │
                       │   24 kHz PCM16   │
                       └──────────────────┘
```

进程拓扑（3 个终端，全在 `agi` conda env）：
1. `unitree_mujoco/simulate_python/python unitree_mujoco.py` — MuJoCo 仿真
2. `python -m teleimager.image_server` — 相机服务（已经在 `docs/camera_ui_demo.md` 调通）
3. `python -m va_demo.main` — 本 demo

---

## 4. Realtime 工具白名单

注册给 OpenAI Realtime 模型的 6 个 function tool（`va_demo/realtime_agent.py::_build_tool_schemas`）：

| 工具 | 参数 | 行为 |
|---|---|---|
| `say` | `text: str ≤200` | TTS 播放（`gpt-4o-mini-tts` PCM16） |
| `stop` | — | `set_command(0,0,0)` + `release_arms()` |
| `release_arms` | — | 把手交还给 RL 策略 |
| `walk` | `vx∈[-0.3,0.3] vy∈[-0.1,0.1] wz∈[-0.4,0.4] duration_s∈[0.2,1.5]` | 设速度 → 等 → 归零 |
| `gesture` | `name∈{wave_right,wave_left,hands_up,t_pose,salute,clap,guard,punch_combo}` | 把现成关键帧推入 `push_arm_action` |
| `describe_scene` | `question?` `detail?∈{low,medium,high}` | 抽帧 → Vision API → 文本结果 |

每个工具调用都先经过 `SafetySupervisor.validate()`：白名单检查 + 数值 clip + 看门狗（帧>2s 拒 describe_scene；lowstate>0.5s 拒 motion）+ 运行模式门（observe/confirm/active）。

---

## 5. 三档运行模式

| `--mode` | motion 工具 | say + describe_scene | 适用场景 |
|---|---|---|---|
| `observe` | 全部拒（reason=observe_only） | 通过 | 验证视觉+TTS+Realtime 闭环 |
| `confirm`（默认） | 终端 y/N 提示后执行 | 通过 | 第一次跑真实组合 |
| `active` | 仅 safety 边界 | 通过 | 可信场景下放手 |

`stop` / `release_arms` / `say` / `describe_scene` 永远不被 confirm 拦（它们没有破坏性，只受 safety 边界和看门狗约束）。

---

## 6. 配置（`configs/va_demo.yaml`）

可被 env var 覆盖的字段：`OPENAI_API_KEY`（必填）、`OPENAI_REALTIME_MODEL`、`OPENAI_VISION_MODEL`、`OPENAI_TTS_MODEL`。

默认值：

```yaml
openai:
  realtime_model: "gpt-realtime"
  vision_model:   "gpt-5.5"
  tts_model:      "gpt-4o-mini-tts"
  realtime_voice: "alloy"
  tts_voice:      "alloy"
  vision_detail:  "medium"

audio:
  samplerate: 24000
  block_ms: 50              # mic 块大小
  speaker_buffer_ms: 200

camera:
  host: "127.0.0.1"
  request_port: 60000
  vision_resize_width: 1024
  vision_jpeg_quality: 85

robot:
  domain_id: 1
  interface: "lo"

safety:
  walk: { vx_max: 0.3, vy_max: 0.1, wz_max: 0.4, duration_max_s: 1.5, duration_min_s: 0.2 }
  say:  { max_chars: 200 }
  watchdog: { max_frame_age_s: 2.0, max_lowstate_age_s: 0.5 }

run_mode: "confirm"
```

---

## 7. 已通过的自动验证

| 检查 | 命令 | 结果 |
|---|---|---|
| 字节码编译 | `python -m compileall va_demo scripts tests` | ✅ |
| 模块全量 import | `python -c "import va_demo.{audio_io,camera,vision,tts,skills,safety,realtime_agent,main,prompts}"` | ✅ |
| 单元测试 | `python -m pytest tests/ -v` | ✅ **22/22 通过** |
| 入口 `--help` | `python -m va_demo.main --help` | ✅ |
| 调试脚本 `--help` | `scripts/{camera,tts,skill,vision_loop}_debug.py --help` | ✅ 4/4 |

测试覆盖（`pytest tests/`）：

- **test_safety.py（14 个）**：未知工具拒绝、`say` 文本裁剪与空串拒、`walk` 数值 clip、duration 上下限 clip、observe 模式拒 motion、observe 不拒 say/describe_scene、lowstate 看门狗拒 motion、lowstate 不拒 say/describe_scene、frame 看门狗拒 describe_scene、未知 gesture 拒、所有 8 个 gesture 通过、describe_scene detail 字段消毒、非法 run_mode 抛 ValueError、`walk` 坏类型 args。
- **test_skills_mock.py（8 个）**：`walk` 设置→归零、`walk` 取消时仍归零（关键安全保证）、已知 gesture 推入、未知 gesture 返回 ok=false、`stop` 归零并释放、`release_arms`、`lowstate_age_seconds` 在 first_state 收到时返回近 0、未收到时返回 ∞。

---

## 8. 需要外部服务的活验（用户本地跑）

| 验证 | 命令 | 依赖 |
|---|---|---|
| 音频回环 | `python scripts/audio_loopback.py` | 麦+扬（WSL 需 PulseAudio 桥；当前 sandbox ALSA 列表为空） |
| 相机+视觉 | `python scripts/camera_debug.py --question "前面有什么？"` | `teleimager.image_server` + `OPENAI_API_KEY` |
| TTS | `python scripts/tts_debug.py "你好"` | 扬声器 + `OPENAI_API_KEY` |
| 仅技能 | `python scripts/skill_debug.py` | `unitree_mujoco.py` |
| 视觉环 | `python scripts/vision_loop_debug.py --rate-hz 1.0` | `teleimager` + `OPENAI_API_KEY` |
| 全启 demo | `python -m va_demo.main` | 三个全开 |

---

## 9. 实施过程中发现并已处理的坑

1. **`asyncio.get_event_loop()` 在测试线程报错**（py3.10+ 弃用）
   - `SkillBackend.__init__` 原本 eager 取 loop，未使用 → 直接删掉。
   - `MicStream.__init__` 改为 lazy（在 `start()` 时才取）。

2. **`agi` env 缺包**：openai、sounddevice、pytest、portaudio
   - pip install openai==2.33.0 + sounddevice==0.5.5 + pytest 完成。
   - conda install -c conda-forge portaudio 完成（解决 `OSError: PortAudio library not found`）。

3. **WSL2 没有 ALSA 设备**（当前 sandbox 现象，您的实际环境不一定一样）
   - `aplay -L`/`pactl` 不可用，但 `/mnt/wslg/PulseServer` 和 `PULSE_SERVER` env var 是有的。
   - README 给了 4 步排错路径（`portaudio` 装好 → 检 PulseServer → ALSA→Pulse 插件 / usbipd USB 声卡 → yaml 显式 device 索引）。

4. **`websockets` 16.0 用 `additional_headers`**（旧版 `extra_headers`）
   - `realtime_agent.py` 主路径用 `additional_headers`，`TypeError` 兜底用 `extra_headers`。

5. **OpenAI SDK 版本漂移**
   - Vision：先试 `client.responses.create`，`AttributeError` 兜底 `client.chat.completions.create`。
   - TTS：先试 `with_streaming_response.create`，`AttributeError` 兜底 `client.audio.speech.create(...).read()`。

6. **gesture 阻塞 vs 异步**：`push_arm_action` 把关键帧推入 ComboController 队列后立即返回，关键帧由 50 Hz tick 自己消化。这意味着 Realtime 模型可以在 gesture 进行中继续对话或调用 `walk`。`walk` 则是有 duration 的，期间 `set_command` 持续，`asyncio.sleep` 后归零；如果 task 被 cancel，`finally` 里也会归零（已被 `test_walk_zeroes_even_on_cancel` 覆盖）。

---

## 10. 显式 YAGNI（按 `vlm_audio_mock_deep.md` 后续 phase）

下面这些**没做**，等需要时再加：

- 真机 SDK2 后端（接口已分层，加 `RealRobotBackend` 即可，不需要碰 va_demo 其他模块）
- 本地 YOLO / depth 感知
- LeRobot / GMR 动作重定向 / RL tracking policy
- 行为树 / scene graph 记忆
- 多帧视频理解（每次 `describe_scene` 仍是单帧快照）
- 单独的 STT-only 备用路径（Realtime 双工本身就够用）

---

## 11. 下次接续开发时的入口

- **改 prompt** → `va_demo/prompts.py`
- **加新 skill** → 在 `va_demo/skills.py` 加 async 方法 → `va_demo/safety.py::ALLOWED_TOOLS` 加名字 + bound 检查 → `va_demo/realtime_agent.py::_build_tool_schemas` 加 schema → `_execute_tool` 加分支
- **接真机** → 实现一个新的 `RealRobotBackend(SkillBackend interface)`，在 `main.py` 按 `--target` 二选一注入
- **换 Vision 模型** → `OPENAI_VISION_MODEL` env 或 `configs/va_demo.yaml::openai.vision_model`
- **音频问题** → `scripts/audio_loopback.py` 是第一现场；`README.md::Audio prerequisites in WSL2` 给排错步骤
- **DDS 问题** → 如果 `[combo] waiting for first /rt/lowstate ...` 卡住，看 `unitree_mujoco.py` 是不是真的跑在 domain=1 / iface=lo

---

## 12. 设计细节文档

更详细的工程设计（架构、数据流、模块职责、依赖、风险与缓解、文件清单）见同目录的 `docs/va-demo-design.md`。
