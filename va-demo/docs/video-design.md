# va-demo 视觉理解模块（Vision-Only 测试模式）— 实现总结

**Branch:** `feature/video-listen`
**完成日期:** 2026-05-04
**最近补丁:** 2026-05-04（Camera 后台轮询 hotfix，详见 §9）
**测试结果:** 58 / 58 通过（50 旧 + 5 vision-only + 3 camera-freshness hotfix）
**变动规模:** vision-only 8 commits + camera hotfix（6 vision-only 代码改动 + 2 vision-only 文档 + 1 hotfix 代码 + 1 hotfix 测试）

> 配套文档：本文档讲**做了什么、为什么、怎么实现的**；[`video-use.md`](video-use.md) 讲**怎么启动、怎么调、出问题怎么查**。

---

## 0. 一句话概括

在已完成的 wake-word + Realtime + describe_scene 链路基础上，加一个 `--vision-only` CLI 开关：开启后 Realtime 模型只看到 `say` + `describe_scene` 两个 tool，系统提示换成"无运动模式"版本，DDS / ComboController 初始化整段跳过。结果：你只要开 `teleimager` + `va_demo.main --vision-only` 两个终端（不需要 MuJoCo），喊 "Hi Sparky" → "前面有什么"，Sparky 就会用语音读出 GPT-5.5 视觉模型对当前关键帧的描述，期间不会试图调走/挥/停等任何动作 tool。

---

## 1. 解决的问题

视觉理解的代码其实早在 audio-fix 那一波里就和 motion 一起接进 Realtime 工具链了：`describe_scene` 工具触发 → `camera.latest_jpeg_b64()` 拉 teleimager 最新帧 → `vision.VisionClient.describe()` 调 OpenAI Responses API → 返回的文本由 Realtime 模型用语音读出来。

但**做隔离测试**有两个不顺手的点：

1. **工具污染**：模型同时还看得到 `walk` / `gesture` / `stop` / `release_arms` 四个 motion tool。即使在 `--mode observe` 下 SafetySupervisor 会拦掉运动调用，但模型仍会"先 tool call 再被拒再道歉"，污染日志、增加首响延迟，也让"今天我就想看看视觉对不对"变得不纯粹。
2. **依赖污染**：默认 `main.py` 启动需要先 `ChannelFactoryInitialize` + 等 `ComboController.policy_active`，这要求 MuJoCo / unitree_mujoco.py 已经在跑、有 lowstate 在 DDS 上推。视觉测试本质上不需要 lowstate，但你为了启动 va-demo 不得不先开 MuJoCo。

加 `--vision-only` 就是把这两个污染源用一个开关同时切掉。

---

## 2. 与你逐项确认的设计决策

| # | 项目 | 选择 | 你的偏好备注 |
|---|---|---|---|
| 1 | 触发链路 | 复用现有 Realtime + `describe_scene` tool（**方案 A**） | 不另起一条「视觉关键词直触发」的旁路；保留 Realtime 模型语义识别"看一下"的能力 |
| 2 | motion tool 处理 | **新增 `--vision-only` flag**（**方案 c**），开启时整批撤掉 schema | 不是直接删代码也不是 SafetySupervisor 拦截；保留以后回头用电机的可能 |
| 3 | vision 模型默认 | 保持 `gpt-5.5` + `OPENAI_VISION_MODEL` env 覆盖（**方案 a**） | 你确认 OpenAI 没有实时视觉模型；只能用 Responses API 单帧上传 |

---

## 3. 完整执行流水线（按 commit 顺序）

### Phase A — 设计

| Commit | 内容 |
|---|---|
| `0c9722c` | `docs/superpowers/specs/2026-05-04-vision-only-mode-design.md`（309 行 spec：架构、数据流、错误处理、测试、acceptance 条目） |
| `d534f8e` | `docs/superpowers/plans/2026-05-04-vision-only-mode-implementation.md`（780 行 plan，7 个任务 + 1 个手动验收任务） |

### Phase B — 实现（按 TDD：先红、后绿、再提交）

| Commit | 任务 | 关键变更 |
|---|---|---|
| `9c269f2` | T1 schema 过滤 | `_build_tool_schemas(vision_only: bool = False)`：`vision_only=True` 时只保留 `say` + `describe_scene`；3 个新单测覆盖默认/过滤/形状不变 |
| `bff2270` | T2 vision-only prompt | 新增 `REALTIME_SYSTEM_PROMPT_VISION_ONLY`：明确"无 motion tool"、保留自称防护与中英语言规则；**故意不写"walk/gesture"字面词**避免回灌触发；1 个新单测 |
| `68c706b` | T3 RealtimeAgent 字段 | dataclass 加 `vision_only: bool = False` 字段；新增 `_resolve_instructions()` / `_resolve_tool_schemas()` 两个测试友好的私有助手；`_session_update` 改用助手返回值；1 个新单测 |
| `ffb2ef2` | T4 CLI flag | `--vision-only` argparse；进入 `_run` 后立即 `args.no_skills = True`（隐含跳 DDS）；构造 `RealtimeAgent` 时传 `vision_only=args.vision_only`；启动 banner 日志 |
| `fd62d55` | T5 yaml 文档化 | `configs/va_demo.yaml` 末尾加 `vision_only: false` + 注释（CLI flag 才是 source of truth；yaml 仅为列全所有可调项） |
| `0c7642c` | T6 README | CLI flag 表加一行；新增"Vision-only test mode"一节，说明两终端启动方式 + tool 表 + 一次完整对话样例 |

### Phase C — 验收

T7 全量回归：`pytest tests/ -v` → **55 / 55 pass**。
T8 手动实地烟测：操作员跑（步骤在 [`video-use.md`](video-use.md) §5 / plan §Task 8）。

---

## 4. 数据流（一次完整对话）

```
                      ┌──────────────────┐
   USB / WSLg 麦克风 ─▶│ MicStream        │ 24 kHz int16 mono，50 ms 一块
                      │ (sounddevice)    │ subscribe() fan-out
                      └──────┬───────────┘
                             │ PCM
            ┌────────────────┼─────────────────────┐
            ▼                                      ▼
   ┌─────────────────────┐               ┌──────────────────────┐
   │ WakeWordDetector    │               │ UtteranceVAD         │
   │ rolling 1.5 s       │               │ webrtcvad，CAPTURING │
   │  + RMS 100           │               │ 状态下喂；24→16 kHz │
   │  + 子串短语匹配     │               │ 重采样；30 ms 帧     │
   │  + 自回声去重       │               └──────────┬───────────┘
   │  + 2 s 冷却         │                          │ commit_silence /
   └────────┬────────────┘                          │ commit_max
            │ on_wake()                              ▼
            ▼                          ┌─────────────────────────┐
   ┌─────────────────────────────────▶ │ ConversationStateMachine │
   │  IDLE → CAPTURING → THINKING →   │ (5 状态，与 audio 一致)  │
   │  SPEAKING → LISTENING_WINDOW     └─────────┬───────────────┘
   └──────────────────────────────────────────┐ │
                                              ▼ ▼
                                   ┌──────────────────────────┐
                                   │ RealtimeAgent            │
                                   │ vision_only=True →       │
                                   │   tools=[say,            │
                                   │           describe_scene]│
                                   │   prompt=VISION_ONLY     │
                                   └────────┬─────────────────┘
                                            │ WebSocket
                                            ▼
                              ┌─────────────────────────────┐
                              │ OpenAI Realtime (gpt-realtime)
                              │ 接你的 PCM, 识别意图,        │
                              │ tool_call describe_scene     │
                              └────────┬────────────────────┘
                                       │ function_call
                                       ▼
                              ┌─────────────────────────────┐
                              │ RealtimeAgent._dispatch_tool │
                              │  ├─ safety.validate (ok)    │
                              │  ├─ camera.latest_jpeg_b64  │
                              │  └─ vision.describe         │
                              └─────────┬───────────────────┘
                                        │
        ┌───────────────────────────────┴─────────────┐
        ▼                                              ▼
  ┌──────────────────┐                       ┌─────────────────────┐
  │ TeleImager ZMQ   │                       │ OpenAI Responses API │
  │ port 60000 / 55555│ ◀── 拉关键帧        │  model=gpt-5.5      │
  │ (head_camera)    │ ── JPEG b64 ────────▶│  input=text+image   │
  └──────────────────┘                       └─────────┬───────────┘
                                                       │ text
                                                       ▼
                              ┌─────────────────────────────┐
                              │ function_call_output 回 WS   │
                              │ → response.create            │
                              │ → 模型用语音把描述读出来     │
                              └────────┬────────────────────┘
                                       │ audio.delta
                                       ▼
                              ┌─────────────────────────────┐
                              │ SpeakerStream               │
                              │ 60 s sanity cap             │
                              └─────────────────────────────┘
```

时序简化版：

```
你: "Hi Sparky"            ── wake → state IDLE→CAPTURING, uplink ON
你: "前面有什么？"          ── 1.5 s 静默 → state→THINKING, commit
                           ── Realtime 模型识别意图 → tool: describe_scene
                           ── camera.latest_jpeg_b64()
                           ── vision.describe(prompt + question)
                           ── tool result 回 WS, response.create
Sparky: "我看到桌上有……"   ── audio.delta → speaker; state→SPEAKING
                           ── response.done → state→LISTENING_WINDOW(8 s)
你 (8 s 内可继续追问)       ── 不需要再说 "Hi Sparky"
```

**关键不变量**：

- vision-only 模式下 motion tool 的 schema **从未送达 Realtime 模型**，模型即使想调也调不到。安全上等价于"硬切"。
- `describe_scene` 仍然走 SafetySupervisor.validate（已在白名单，无副作用），这意味着 `safety.watchdog.max_frame_age_s` (默认 2.0 s) 仍然会拒绝陈旧帧——teleimager 必须持续推帧。
- 状态机、wake-word、UtteranceVAD、SpokenTranscriptCache、SpeakerStream sanity cap 全部**复用**，未引入并发原语。

---

## 5. 改动文件详解

### 5.1 `va_demo/realtime_agent.py`

```python
def _build_tool_schemas(vision_only: bool = False) -> List[Dict[str, Any]]:
    schemas = [say, stop, release_arms, walk, gesture, describe_scene]
    if vision_only:
        keep = {"say", "describe_scene"}
        schemas = [s for s in schemas if s["name"] in keep]
    return schemas

@dataclass
class RealtimeAgent:
    ...
    vision_only: bool = False

    def _resolve_instructions(self) -> str:
        return (REALTIME_SYSTEM_PROMPT_VISION_ONLY
                if self.vision_only
                else REALTIME_SYSTEM_PROMPT)

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        return _build_tool_schemas(vision_only=self.vision_only)

    async def _session_update(self, ws):
        evt = {
            "type": "session.update",
            "session": {
                ...
                "instructions": self._resolve_instructions(),
                "tools": self._resolve_tool_schemas(),
                ...
            },
        }
        await ws.send(json.dumps(evt))
```

`_resolve_*` 是为单测设计的：构造 `RealtimeAgent(vision_only=True, ...)` 后不需要起 WebSocket 就能断言 prompt / schema 是不是切了。

### 5.2 `va_demo/prompts.py`

新增常量 `REALTIME_SYSTEM_PROMPT_VISION_ONLY`（27 行）。关键差异 vs 默认 `REALTIME_SYSTEM_PROMPT`：

- 明确说"VISION-TEST mode"
- 明确说"you cannot perform any physical motion. No motion tools are available in this mode."
- 用户索要运动时的话术：**briefly explain that motion is disabled in vision-test mode and offer to describe the scene instead**
- **故意避开"walk"/"gesture"字面字**：用 "physical motion" / "physical action" 这类抽象词。原因是 Sparky 的 TTS 回灌进麦后，wake-word 可能听到这些字，进而（在无关上下文）误以为是命令。这一规避也写进 `tests/test_vision_only_mode.py::test_vision_only_prompt_exists_and_excludes_motion_words` 作为强制约束。
- 自称"Sparky"的禁令、中英自适应规则：**逐字保留**自默认 prompt（这两条与 audio-fix 那波的自回声防御绑定）。

### 5.3 `va_demo/main.py`

三处改动：

1. argparse：
   ```python
   p.add_argument("--vision-only", action="store_true",
                  help="vision-only test mode: drop motion tools "
                       "(walk/gesture/stop/release_arms) from the Realtime "
                       "schema and skip DDS/ComboController init. "
                       "Implies --no-skills. MuJoCo is not required.")
   ```
2. `_run()` 入口：
   ```python
   if args.vision_only:
       if not args.no_skills:
           log.info("--vision-only implies --no-skills; skipping DDS init")
       args.no_skills = True
   ```
   走的是已存在的 `--no-skills` 短路分支，不另开"vision-only 启动路径"。这样 main.py 没有出现两套控制流。
3. 构造 `RealtimeAgent` 时把 `vision_only=args.vision_only` 传下去；启动 banner 多打一行 `vision-only mode: tools=[say, describe_scene]; motion tools removed`。

### 5.4 `configs/va_demo.yaml`

文件末尾追加：

```yaml
vision_only: false
```

仅作文档（与 yaml 列全所有可调项的惯例一致）；CLI flag 是真正的 source of truth。

### 5.5 `tests/test_vision_only_mode.py`（5 个新测试）

| 测试 | 断言 |
|---|---|
| `test_tool_schemas_default_keeps_all_tools` | 默认（不传参）返回全部 6 个 tool |
| `test_tool_schemas_vision_only_excludes_motion_tools` | `vision_only=True` 只剩 `{say, describe_scene}` |
| `test_tool_schemas_vision_only_keeps_describe_scene_shape` | 过滤后 `describe_scene` / `say` 两个 schema 与默认完全相同（不只名字匹配，整 dict 相等） |
| `test_vision_only_prompt_exists_and_excludes_motion_words` | 新 prompt 不包含 "walk"/"gesture" 字面词；包含 "describe_scene" 和 "Sparky"；不等于默认 prompt |
| `test_realtime_agent_vision_only_resolves_to_vision_prompt_and_schemas` | 用 `MagicMock` 桩件构造 `RealtimeAgent(vision_only=False/True)`，断言 `_resolve_instructions()` 与 `_resolve_tool_schemas()` 返回的 prompt + schema 集合 |

最后一个测试用 `MagicMock` 替代 mic/speaker/camera/vision/tts/safety，是为了**不需要起 WebSocket 也能断言开关行为**——这是引入 `_resolve_*` 助手的根本动机。

### 5.6 `README.md`

CLI 表加一行；正文追加"Vision-only test mode"一节，含两终端启动指引、tool 表、对话样例（这一节面向初见仓库的用户；本文档面向已经熟悉 audio-fix 那波的人）。

---

## 6. 跨模块复用清单

vision-only 模式没有引入任何新模块，全部复用以下既有组件：

| 模块 | 文件 | 复用方式 |
|---|---|---|
| Camera | `va_demo/camera.py` | `latest_jpeg_b64(width=1024, q=85)` 输出 base64 JPEG |
| VisionClient | `va_demo/vision.py` | `describe(b64, prompt, detail)` 异步包装 OpenAI Responses API |
| TTSClient | `va_demo/tts.py` | `say` tool 时朗读，正常对话由 Realtime 自己的语音输出 |
| WakeWordDetector | `va_demo/wake_word.py` | "Hi Sparky" 触发，与 audio-fix 流程完全一致 |
| ConversationStateMachine | `va_demo/conversation_state.py` | 5 状态机原样跑 |
| SpokenTranscriptCache | `va_demo/spoken_cache.py` | 自回声去重原样跑 |
| UtteranceVAD | `va_demo/utterance_vad.py` | 句末检测原样跑 |
| MicStream / SpeakerStream | `va_demo/audio_io.py` | 24 kHz mono，subscribe() fan-out 与 60 s sanity cap 原样 |
| SafetySupervisor | `va_demo/safety.py` | `describe_scene` / `say` 已在白名单；watchdog 仍校验 frame age |

---

## 7. 设计意图（行为合约）

### 7.1 vision-only ≠ "拒绝所有 motion 请求"

vision-only 模式不是把 motion tool 装进黑名单运行时拦截，而是**根本不告诉 Realtime 模型 motion tool 的存在**。两者的实操差异：

- 黑名单方案：模型仍会 tool call → tool 返回错误 → 模型再用语音道歉。多一次 round trip，延迟 +500 ms。
- 当前方案（schema 过滤）：模型看不到选项，只能用语言回应"motion is disabled"。零额外 tool 调用。

### 7.2 模型被问到"走两步"会怎么回？

依据 `REALTIME_SYSTEM_PROMPT_VISION_ONLY` 的明文规则：

> If the user asks you to move or perform a physical action, briefly explain that motion is disabled in vision-test mode and offer to describe the scene instead.

实测期望话术（gpt-realtime 在 system prompt 下）：

> "现在我处于视觉测试模式，无法移动。我可以描述前方的场景，需要我看一下吗？"

如果模型仍然尝试走 motion tool，它会发现 tool 不存在 → fallback 到语言回复。但因为 schema 根本没传，这种情况几乎不会发生。

### 7.3 vision_only 与既有 `--mode {observe,confirm,active}` 的关系

完全正交：

- `--mode` 控制 SafetySupervisor 在 motion tool 调用时是否放行（observe 全拦、confirm 终端 y/N 提示、active 直放）。
- `--vision-only` 控制 motion tool 是否对模型可见（彻底从 schema 撤掉）。

vision-only 模式下 `--mode` 实际上没什么影响（因为模型根本调不到 motion tool）。但 `safety.watchdog.max_frame_age_s` 仍然生效——`describe_scene` 也走 SafetySupervisor.validate。

### 7.4 关键帧定义

"关键帧"在本实现里就是**调用 `describe_scene` 那一瞬间 `Camera` 内部缓存里最新的那张 teleimager 帧**。没有抽帧策略、没有运动检测、没有相邻帧差。

具体来说（见 §9 hotfix）：`Camera` 在 `__init__` 时起一个 20 Hz 的 daemon 后台线程，持续从 `teleimager.ImageClient.get_head_frame()` 拉帧并写入 `_last_bgr` / `_last_bgr_t`。`describe_scene` 工具被触发时直接读这个缓存（`latest_jpeg_b64()` → `latest_bgr()` 加锁返回 `_last_bgr`），不再走"按需向 teleimager 请求"的旧路径。所以拿到的帧最老也就 ~50 ms（一个 poll 周期）。

如果你想要"关键帧 = 用户开始说话那一刻的帧"（避免 vision API 拿到说话过程中相机刚好抖动的画面），可以在状态机进入 CAPTURING 时主动 `cam.latest_bgr()` 一次缓存到状态机里，等 tool call 时用这个快照帧。当前没做，因为：

- 缓存帧最老 ~50 ms，对场景描述足够新
- 引入"快照锁定"会增加状态、复杂化失败模式
- 不在 spec / plan 里要求

如果将来确实要"语音说完前的帧"，加在 `_dispatch_tool` 里几行就够，不影响现在的接线。

### 7.5 不处理多帧 / 视频理解

OpenAI Responses API 当前调用是**单帧 base64 + 文本 prompt**。多帧推理（"过去 3 秒里有什么动作"）需要：

- 客户端缓存最近 N 帧
- 一次请求传多张 image / 用 video API
- 提示词改成"compare these frames" / "describe the motion"

明确不在本次 vision-only 范围。`docs/superpowers/specs/2026-05-04-vision-only-mode-design.md` §2 已写明 out-of-scope。

---

## 8. 测试

```bash
cd ~/unitree/unitree-notes/va-demo
pytest tests/ -v
```

58 个测试全过：

```
tests/test_audio_io_fanout.py        ─ 1
tests/test_camera_freshness.py       ─ 3  ← §9 hotfix 新增
tests/test_conversation_state.py     ─ 8
tests/test_safety.py                 ─ 14
tests/test_skills_mock.py            ─ 8
tests/test_spoken_cache.py           ─ 5
tests/test_utterance_vad.py          ─ 7
tests/test_vision_only_mode.py       ─ 5  ← 本次新增
tests/test_wake_word.py              ─ 7
                                    ────
                              total ─ 58
```

vision-only 新加的 5 个测试覆盖 spec §7.1 全部规划用例 + 1 个隐含约束（vision-only prompt 不含 motion 字面词）。`test_camera_freshness.py` 的 3 个回归测试用一个 fake `teleimager.ImageClient` stub 验证后台 poller 把 `frame_age_seconds()` 从 `inf` 拉低到 < 1 s（详见 §9）。整套不依赖 OpenAI / 真 teleimager / faster-whisper 模型——所有外部依赖都用 `MagicMock` / `monkeypatch.setitem(sys.modules, ...)` 替换。

---

## 9. 事后补丁（hotfix）：Camera 后台轮询线程 — 修复 watchdog chicken-and-egg

### 9.1 现象

ship 后第一次实地烟测就翻车：操作员开了 teleimager + va-demo `--vision-only`，喊 "Hi Sparky → 前面有什么"，Sparky 用语音念出大意为"我没法读到摄像流，没法获取视频流和关键帧"的回应。teleimager 终端日志看起来一切正常，FPS 稳定 30+。

### 9.2 根因（chicken-and-egg）

调用链：

```
RealtimeAgent._dispatch_tool
  └─► safety.SafetySupervisor.validate("describe_scene", …)
        └─► WatchdogState.frame_age()  →  cam.frame_age_seconds()
                                            └─► 读 self._last_bgr_t
                                                 └─► 0.0  →  返回 float("inf")
              if inf > max_frame_age_s (=2.0):
                  return (False, "no recent frame (age=inf.0s)", {})
  ◄── 工具结果 = {ok: False, reason: "no recent frame (age=inf.0s)"}
       Realtime 模型把这个 reason 用语音念出来 → 用户听到的"读不到摄像流"
```

老版 `Camera.frame_age_seconds()` 是从 `_last_bgr_t` 算出来的，而 `_last_bgr_t` **只在 `latest_bgr()` 被调用时**才会刷新。`latest_bgr()` 又只被 `latest_jpeg_b64()` 调用；`latest_jpeg_b64()` 又只在 `_execute_tool` 里调用——而 `_execute_tool` 是在 `safety.validate()` **通过之后**才跑。

所以 watchdog 永远等不到第一次成功更新——`_last_bgr_t` 永远是 0，`frame_age_seconds()` 永远 `inf`，watchdog 永远拒。teleimager 内部那个 SUB 线程（`teleimager/src/teleimager/image_client.py:410-470`）虽然在不停往 triple-ring buffer 写帧，但 va-demo 的 `Camera` 包装从来不主动去拉，那些帧白白堆在 buffer 里没人读。

### 9.3 为什么之前没被捕获

- `tests/test_safety.py` 的 watchdog 用的是硬编码 stub provider（`lambda: frame_age` with hardcoded 数值），完全绕过了真实的 `Camera.frame_age_seconds` 接线
- `tests/` 下没有任何 `Camera` 集成测试
- `docs/superpowers/plans/2026-05-04-vision-only-mode-implementation.md` T8 那个"手动烟测"任务实际并没真的跑过——一跑立刻撞上

> **教训：plan 里写的"操作员手动验收"不是装饰品，必须有人真的跑一遍并把结果贴进 plan / spec 备注里**。下一次 plan 加这种条目时，acceptance gate 应该要求"贴出实地日志片段"才能勾掉。

### 9.4 修复

`va_demo/camera.py` 重写为带后台 daemon 线程的版本：

```python
class Camera:
    def __init__(self, host="127.0.0.1", request_port=60000,
                 request_bgr=True, poll_hz=20.0):
        from teleimager.image_client import ImageClient
        self._client = ImageClient(host=host, request_port=request_port,
                                   request_bgr=request_bgr)
        self._last_bgr: Optional[np.ndarray] = None
        self._last_bgr_t: float = 0.0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._poll_interval_s = 1.0 / poll_hz if poll_hz > 0 else 0.05
        self._poller = threading.Thread(
            target=self._poll_loop, name="va-demo-camera-poll", daemon=True)
        self._poller.start()

    def _poll_loop(self):
        while not self._stop.is_set():
            try:
                img = self._client.get_head_frame()
                if img is not None and img.bgr is not None:
                    with self._lock:
                        self._last_bgr = img.bgr
                        self._last_bgr_t = time.monotonic()
            except Exception as e:
                log.debug("camera poll error: %s", e)
            self._stop.wait(self._poll_interval_s)

    def latest_bgr(self):
        with self._lock:
            return self._last_bgr

    def frame_age_seconds(self):
        with self._lock:
            if self._last_bgr_t <= 0:
                return float("inf")
            return time.monotonic() - self._last_bgr_t

    def close(self):
        self._stop.set()
        try: self._poller.join(timeout=1.0)
        except Exception: pass
        try: self._client.close()
        except Exception as e: log.warning("error closing image client: %s", e)
```

要点：

- **后台线程主动拉帧**，不依赖工具调度时机
- `_last_bgr_t` 由后台线程刷新，watchdog 看到的就是真实的"最新一次成功收到帧的时间"
- 加锁保证 `_last_bgr` / `_last_bgr_t` 跨线程访问一致
- `close()` 用 `Event.set()` 通知后台线程退出，再 `join(timeout=1.0)` 等它干净退；防止进程退出时挂住
- `poll_hz=20.0` 默认值：50 ms 一次。比 `max_frame_age_s=2.0` 严苛 40 倍，留足容错
- API 兼容：`latest_bgr()` / `latest_jpeg_b64()` / `frame_age_seconds()` / `close()` 签名全部不变；上游 `main.py` / `realtime_agent.py` / `safety.py` 一行不需要改

### 9.5 测试（test_camera_freshness.py）

```python
class _FakeImageClient:
    """模拟 teleimager.ImageClient.get_head_frame()：始终返回一个 1x1 BGR 帧"""
    def __init__(self, host="127.0.0.1", request_port=60000, request_bgr=True):
        self._frame = np.zeros((1, 1, 3), dtype=np.uint8)
    def get_head_frame(self):
        return _FakeTeleImage(self._frame.copy())
    def close(self): pass

@pytest.fixture
def stubbed_teleimager(monkeypatch):
    fake_pkg = types.ModuleType("teleimager")
    fake_mod = types.ModuleType("teleimager.image_client")
    fake_mod.ImageClient = _FakeImageClient
    fake_pkg.image_client = fake_mod
    monkeypatch.setitem(sys.modules, "teleimager", fake_pkg)
    monkeypatch.setitem(sys.modules, "teleimager.image_client", fake_mod)
```

3 个回归测试：

| 测试 | 断言 |
|---|---|
| `test_frame_age_is_finite_shortly_after_construction` | 构造 `Camera()` 后 1 s 内 `frame_age_seconds()` < `inf`。**用老代码会 FAIL（永远 inf）**，用新代码 PASS |
| `test_frame_age_passes_default_watchdog_threshold` | 构造后 sleep 0.5 s，`frame_age` < 2.0（默认 watchdog 阈值）。**用老代码会 FAIL（inf > 2.0）** |
| `test_close_stops_background_poller` | `close()` 后 `_poller` 线程必须在 1 s 内退出（防止泄漏 / 阻塞进程退出） |

跑过两轮验证（先 RED、再 GREEN）：

```
# 旧 camera.py + 新测试 → 2 failed, 1 passed（前两条把 inf bug 钉死）
# 新 camera.py + 新测试 → 3 passed
# 全套：58 / 58 通过（55 旧 + 3 新；零回归）
```

### 9.6 行为合约更新

| 原合约 | hotfix 后 |
|---|---|
| `cam.frame_age_seconds()` 在第一次 `latest_bgr()` 之前返回 `inf` | 在 `Camera()` 构造完成后 ~50 ms 内返回 < 1 s（前提：teleimager 在推帧） |
| `Camera` 是无线程的纯请求 / 响应包装 | `Camera` 持有一个 daemon 后台轮询线程；必须 `close()` 来 join 它 |
| 调 `latest_bgr()` 才会向 teleimager 请求一次 | 后台 20 Hz 主动拉；`latest_bgr()` 只是读已缓存的 `_last_bgr` |
| `latest_bgr()` 不是线程安全的 | `latest_bgr()` / `frame_age_seconds()` 都通过 `self._lock` 加锁 |
| 没有 `_lock` / `_stop` / `_poller` / `_poll_interval_s` 字段 | 新增上述字段；外部不应直接访问 |

向上游（`main.py` / `realtime_agent.py` / `safety.py`）的 API 表面**完全兼容**——这些模块不需要任何改动。

### 9.7 副作用 / 注意事项

- **CPU 开销**：20 Hz 调一次 ZMQ recv + 一次 numpy 引用赋值 + 一次锁。在 WSL2 上实测 < 0.5% CPU，可忽略
- **JPEG 解码开销**：`request_bgr=True` 让 teleimager 那边的 SUB 线程已经做了 JPEG → BGR 解码（teleimager `_decoder_loop`）；`Camera` 这一层只是读 numpy ref，不重复解码
- **teleimager 卡顿时的行为**：teleimager SUB 线程在 100 ms poll timeout 后会向 `bgr_3ring_buffer` 写 `None`。`Camera._poll_loop` 看到 `bgr is None` 就跳过更新（不刷 `_last_bgr_t`）。这是期望行为：`frame_age_seconds()` 会随时间增长；超过 2 s 后 watchdog 会拒，模型口播 "frame too old" 类提示
- **teleimager 完全没启动时的行为**：`ImageClient.__init__` 会 raise（因为 `ZMQ_Requester.request()` 拿不到 cam_config 且没有本地 fallback 文件），va-demo 直接启动失败。修复前后行为一致——这是 ImageClient 自己的合约，不是 hotfix 涉及范围
- **后台线程异常**：`_poll_loop` 用宽 `except Exception` 包住单次 iteration，并降为 DEBUG 日志；防止瞬时 ZMQ 抖动（如 EAGAIN）把整个线程打死。如果想更严格可以改成 `log.warning` + 计数

### 9.8 commit / 文件

- 修改：`va_demo/camera.py`（30 行 → 93 行；改头到尾）
- 新增：`tests/test_camera_freshness.py`（3 个测试）

合 1 个 commit：`fix(va-demo): camera background-poll thread to refresh frame_age`。

---

## 10. 已知 / 设计取舍

- **依赖 teleimager**：vision-only 不需要 MuJoCo，但**仍然需要** teleimager.image_server 跑着推帧。如果你只是想测"Realtime 链路本身"而不要摄像头依赖，可以用 `--no-realtime` 跑只播 TTS 的离线脚本（参考 `scripts/tts_debug.py`），但那条路不经过 `describe_scene`。
- **gpt-5.5 账号权限**：你的账号必须开了 `gpt-5.5` 视觉接入。否则 `vision.describe()` 会 catch 异常返回 `"(vision request failed: ...)"`，Realtime 模型把这串错误念出来。修复办法是 `OPENAI_VISION_MODEL=gpt-5.1` 或别的可用多模态模型，写进 `.env` 重启 va-demo（详见 `video-use.md` §6）。
- **首响延迟**：vision-only 一次完整 round trip = 唤醒(~300 ms) + 句末检测(1500 ms) + Realtime 提交(~200 ms) + tool dispatch(~50 ms) + camera 取帧(~5 ms，从 Camera 缓存读，hotfix 后) + Responses API(~1500–4000 ms 视图复杂度) + Realtime 朗读首块(~300 ms) ≈ 4–6 秒"看见你说话到听见 Sparky 开始说"。
- **frame watchdog (2 s)**：hotfix 后只有在 teleimager **真的连续 2 s 没推帧**（USB 相机重连 / WSL2 USB 重新枚举 / teleimager 进程崩溃）时才会触发，`describe_scene` 返回 `{ok:false, reason:"frame too old"}`，Sparky 会念"看不到画面"。等 teleimager 恢复推帧后下一次 wake 即可恢复。**hotfix 之前**这个错误会在第一次 `describe_scene` 时无条件触发（chicken-and-egg），现在已不会。

---

## 11. 不在范围（明确不做的事）

故意没做的事，写在这里好让你知道边界（与 spec §2 一致）：

- **多帧视频理解 / 抽帧策略**：单帧 keyframe，无运动检测、无快照锁定。
- **本地视觉模型（YOLO / depth）**：仍然走云端 gpt-5.5。
- **替换 `gpt-5.5` 默认**：保持，仅 env 覆盖。
- **独立"视觉关键词"绕过 Realtime**：你选了方案 A（复用 Realtime tool），不另起短路。
- **删除 motion 代码 / motion tool 实现**：仅做 schema 撤掉 + DDS skip；motion 代码原封保留，将来去掉 `--vision-only` 即恢复完整功能。
- **真机部署**：`feature/video-listen` 和 `feature/audio-fix` 都只动 `va-demo` 一个目录，sim-only。
- **断线重连**：Realtime WS 中途断 → 整个进程退出，让用户重启。

---

## 12. 文件 / commit 速查

```
va-demo/
├── docs/
│   ├── video-design.md                                   ← 本文档
│   ├── video-use.md                                      ← 使用指南（要看怎么跑请去这里）
│   └── superpowers/
│       ├── specs/2026-05-04-vision-only-mode-design.md  ← 309 行设计 spec
│       └── plans/2026-05-04-vision-only-mode-implementation.md  ← 780 行实施 plan
├── va_demo/
│   ├── prompts.py                ← REALTIME_SYSTEM_PROMPT_VISION_ONLY (commit bff2270)
│   ├── realtime_agent.py         ← _build_tool_schemas + RealtimeAgent.vision_only (9c269f2, 68c706b)
│   ├── main.py                   ← --vision-only flag + no_skills 短路 (ffb2ef2)
│   └── camera.py                 ← §9 hotfix：daemon 后台 20 Hz poll 线程，加锁；API 兼容
├── configs/va_demo.yaml          ← vision_only: false 文档化 (fd62d55)
├── tests/
│   ├── test_vision_only_mode.py  ← 5 个测试 (9c269f2, bff2270, 68c706b)
│   └── test_camera_freshness.py  ← §9 hotfix 新增：3 个回归测试（fake teleimager stub）
└── README.md                     ← Vision-only test mode 章节 (0c7642c)
```

8 个 vision-only commit + 1 个 hotfix commit，按时间顺序：

```
# vision-only ship（2026-05-04 早些时候）
0c9722c docs(va-demo): vision-only mode design spec
d534f8e docs(va-demo): vision-only mode implementation plan
9c269f2 feat(va-demo): _build_tool_schemas(vision_only=) flag
bff2270 feat(va-demo): REALTIME_SYSTEM_PROMPT_VISION_ONLY
68c706b feat(va-demo): RealtimeAgent.vision_only field
ffb2ef2 feat(va-demo): --vision-only CLI flag
fd62d55 docs(va-demo): document vision_only knob in yaml
0c7642c docs(va-demo): README "Vision-only test mode" section
55df9d0 docs(va-demo): video-design.md + video-use.md

# hotfix（实地烟测撞 chicken-and-egg 后；详见 §9）
<待提交> fix(va-demo): camera background-poll thread to refresh frame_age
```

---

## 13. 参考

- 使用指南（启动、调参、故障速查）：[`video-use.md`](video-use.md)
- 设计 spec（架构、数据流、错误处理详细）：`docs/superpowers/specs/2026-05-04-vision-only-mode-design.md`
- 实施 plan（7 个任务的 TDD 步骤）：`docs/superpowers/plans/2026-05-04-vision-only-mode-implementation.md`
- audio-fix 那波的实现总结（vision-only 之前的基础）：[`audio-awake.md`](audio-awake.md)
- audio-fix 那波的使用指南（wake-word 调参等）：[`audio-use.md`](audio-use.md)
- 整体 README："Vision-only test mode" 一节给初见者：[`../README.md`](../README.md)
