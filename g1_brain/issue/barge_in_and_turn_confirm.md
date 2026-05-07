# 打断后无法连续发令 / 多步动作反复确认 两大问题排查与修复

日期：2026-05-07
分支：`feature/audio-control`

用户在使用语音 + `--mode confirm` 时反复遇到两类故障：

1. 用 "Hi Sparky" 打断（barge-in）一个还没跑完的任务后，**接下来的命令
   要喊好几遍才被真正执行**。
2. 本来应该一次完成的连续动作（"右转 180 度"、"后退 10 米"），**被
   LLM 拆成 N 个小调用，每一个都要在终端里按 y 才放行**，体验上像是
   "机器人不愿意一口气完成动作，而非依据自身视觉自主判断"。

本文按"现场日志 → 根因 → 修复 → 测试"的顺序把两个问题讲清楚，并解释
为什么这两个问题其实共享同一份 OpenAI Realtime 事件流的设计缺陷。

---

## 0. TL;DR

| # | 症状 | 根因（一句话） | 修复（一句话） |
|---|---|---|---|
| 1 | 打断后下一条命令要喊多次才生效；终端里出现"我已经走了 10 米"这种打断前的旧应答 | 我们发了 `response.cancel`，但 OpenAI Realtime 服务器**已经在生成响应**，cancel 失败（`response_cancel_not_active`），可旧响应的 `audio.delta` / `audio_transcript.delta` / `function_call_arguments.done` 仍源源不断从 WS 来，被 `_handle_event` 当作活动响应处理：旧 TTS 重新写入扬声器、旧的工具链（`stop({})`、`turn(-25)`）继续执行、每次 dispatch 又发一次 `response.create` 撞上新 turn → `conversation_already_has_active_response` 卡 30 秒 → WS keepalive 超时 | 在 `BrainRealtimeAgent` 里给 in-flight response_id 做了一份小型 LRU 黑名单：`cancel_in_flight()` 把当前 response_id 加入黑名单；`_handle_event` 把任何带这个 response_id 的事件直接丢弃；`_dispatch_tool` 在 `await skill.execute()` 返回后再判一次黑名单，命中则跳过 `function_call_output` + `response.create` 的回写，避免与新 turn 的响应碰撞 |
| 2 | "右转 180 度" 被拆成 7 次 `turn(-25)`；"后退 10 米" 被拆成 `look_at(behind)` + `walk(-0.2, 6)` 两次确认 | (a) `turn` 的 schema 上限 ±45°、安全层 ±60°，强迫 LLM 链式调用；(b) `_skill_turn` 几何参数错了，`_TURN_DURATION_PER_DEG = 1/25` 配 `wz = 0.25 rad/s` 实际只转 ~57% 的请求角度，于是 LLM 看 "还没转够" 就继续叠；(c) `_TURN_MAX_DURATION_S = 1.5s` 把任何单次 turn 限死在 ~21°；(d) prompt 没有把 "向后走不需要 look_at(behind)" 写进硬规则 | (a) `tool_schemas.py` 把 `yaw_deg` 范围放到 ±180°；(b) 安全层 clamp 也放到 ±180°；(c) `_TURN_DURATION_PER_DEG = π / (180 × 0.25)` 修正几何，`_TURN_MAX_DURATION_S = 14 s` 让 180° 一次跑完；(d) prompt 加 "一次 `turn(yaw_deg=±N)` 完成所有右转/左转 / 一次 `walk(-0.2, N/0.2)` 完成所有后退；头顶摄像头看不到背后，就别在后退前插 `look_at(behind)`" |

跑全部测试：**287 / 287 通过**，新增 11 条针对取消响应过滤 + turn 几何
的回归测试。

---

## 1. 问题一：打断后必须喊多次 Hi Sparky 才被听到

### 1.1 现场日志切片

下面摘自用户在 19:55–20:04 的会话（节选自 `--mode confirm`）：

```
19:56:23  tool call: walk({'vx': 0.2, 'duration_s': 50})        ← "前进 10 米"
[g1_brain confirm] y                                            ← 用户按 y
19:56:26  fsm: ENGAGED -> ACTING (skill walk)
19:56:37  [wake] 'Hi Sparky.' (state=SPEAKING)                  ← 用户打断
19:56:37  stop                                                  ← stop_skill_callable
19:56:37  fsm: ACTING -> ENGAGED (skill stop done)
19:56:37  [state] SPEAKING -> CAPTURING (barge_in)              ← 进入捕获

# —— 注意时间轴：从这里开始，state 已经是 CAPTURING ——

19:56:55  [wake] 'Hi Sparky' (state=CAPTURING)                  ← 用户再喊一次
19:57:11  [wake] 'Hi Sparky' (state=CAPTURING)                  ← 第三次
19:57:16  ERROR realtime error: response_cancel_not_active
          I've moved forward about 10 meters as you requested.  ← 旧响应的转写仍在打印
19:57:23  [wake] 'Hi Sparky.' (state=CAPTURING)                 ← 第四次
19:57:30  [utterance] commit_silence after 6.98s                ← 终于收住一段输入
[user] Turn right.
```

打断之后的 53 秒里，用户喊了 4 次 "Hi Sparky" 才让系统真正听他下一句话。
更糟的是终端里跳出了 "I've moved forward about 10 meters as you
requested." —— 这句**不是新 turn 的应答**，而是被 cancel 的那一段对话
的 transcript 仍在飘出来。

随后在 20:00–20:01 的另一次 barge-in 出现了更严重的行为：

```
20:00:49  [wake] 'Hi Sparky' (state=THINKING)
20:00:49  fsm: ENGAGED -> ACTING (skill stop)
20:00:49  [state] THINKING -> CAPTURING (barge_in)
20:00:53  [state] CAPTURING -> THINKING (vad_commit)
20:00:56  ERROR response_cancel_not_active
20:00:56  tool call: stop({})                                   ← 旧 plan 的工具调用
20:00:56  fsm: ENGAGED -> ACTING (skill stop)
20:00:56  fsm: ACTING -> ENGAGED (skill stop done)
[user] Turn right.                                              ← 用户的新指令
20:00:56  ERROR response_cancel_not_active
[user] Turn right.
20:00:56  tool call: turn({'yaw_deg': -25})                     ← 旧 plan 的另一个工具调用
20:00:58  fsm: ENGAGED -> ACTING (skill turn)
20:00:59  fsm: ACTING -> ENGAGED (skill turn done)
20:00:59  ERROR conversation_already_has_active_response: ... resp_DcppItkq2wb9l0ytsLStj
20:00:59  tool call: turn({'yaw_deg': -25})                     ← 旧响应又催了一次
[...]
20:04:06  [plan_watchdog] forcing plan_done after 30.0s         ← 终于卡到看门狗
20:04:14  ERROR sent 1011 (internal error) keepalive ping timeout
```

这是非常严重的"打断不干净"。`response.cancel` 失败，旧响应的工具调用还
在执行，新 `response.create` 跟旧响应抢资源被服务器拒绝，最后 30 秒后看
门狗才把整个会话强制收回，websocket 也撑到 keepalive 超时。

### 1.2 根因

OpenAI Realtime 服务器在我们发出 `response.cancel` 时，**那条响应可能
已经在服务端最终化了**。这有两类后果：

1. **服务器返回 `response_cancel_not_active` 错误**（cancel 找不到目
   标），日志里能直接看到。
2. **该响应的事件流仍在 WS 里**：剩下的 `audio.delta` /
   `audio_transcript.delta` / `function_call_arguments.done` /
   `response.done` 已经通过 WS 缓冲送出来了，cancel 不会"撤回"它们。

我们的 `BrainRealtimeAgent._handle_event` 没有任何 response_id 维度
的过滤，所以这些"在打断之后才到的旧事件"会被当成现役响应处理：

| 事件类型 | 旧实现的行为 | 用户感知 |
|---|---|---|
| `response.audio.delta` | `self.speaker.write(...)` 立刻写扬声器 | 打断之后机器人继续讲完上一段（"我已经走了 10 米..."） |
| `response.audio_transcript.delta` | `print(piece, end="")` 打到终端 | 终端里冒出旧应答的中文/英文文本 |
| `response.function_call_arguments.done` | `await self._dispatch_tool(...)` 真的去跑 skill | 用户喊完 "右转" 后还看见 `tool call: stop({})` / `turn(-25)` 在跑 |
| 上面 dispatch 跑完后发的 `response.create` | 服务器有现役响应没收回 | `conversation_already_has_active_response` 错误，新 turn 卡死 |

更恶劣的回环：`SpeakerStream.write` 把 PCM 塞进本地播放缓冲；扬声器播
出去后被同一个 WSL2 麦克风听到（ALSA + WSLg 没有回声消除）；麦克风把
"机器人自己的声音" 当成用户语音 → VAD 误触发 `commit_silence` →
`response.create` → 服务器收到一段乱码音频 → 又生成一个回复... 用户
在外面听到的就是 "robot 还在自言自语"，于是再喊一遍 "Hi Sparky"，循环
继续。这就是为什么前后要喊 4 次。

### 1.3 修复：给被取消的 response_id 上小型 LRU 黑名单

核心思路：**barge-in 之后，这个 response_id 的所有事件一律丢弃。** 由于
WS 帧是按时间到达的，新 turn 走的是新的 `response.created`，自然有新
id，不在黑名单里，不会被误伤。

代码改动集中在 `g1_brain/brain/realtime_agent.py`：

1. `__post_init__` 加两个字段：

   ```python
   self._current_response_id: Optional[str] = None
   self._cancelled_response_ids: List[str] = []
   self._cancelled_response_id_cap: int = 16
   ```

   `List[str]` 不是 `Set[str]` 是有意为之 —— 我们要的是 LRU 顺序，最多
   16 个，`in` 测试 O(16) 远比 WS 一来一回便宜。

2. `_handle_event` 入口先做两件事：

   ```python
   if t == "response.created":
       rid = (evt.get("response") or {}).get("id")
       if rid:
           self._current_response_id = rid
   rid = self._event_response_id(evt)
   if rid is not None and rid in self._cancelled_response_ids:
       log.debug("dropping event %s for cancelled response %s", t, rid)
       return
   ```

   `_event_response_id` 是新加的静态方法，兼容两种事件形状：大多数
   `response.*.delta` 顶层带 `response_id`，而 `response.created` /
   `response.done` 把 id 嵌在 `response.id` 里。

3. `cancel_in_flight()` 现在先把当前 in-flight id 推进黑名单再发 WS：

   ```python
   self._mark_current_response_cancelled()   # 必须在 ws.send 之前，
                                             # 抢在 race-in 的 audio.delta 之前
   await ws.send(...response.cancel...)
   await ws.send(...input_audio_buffer.clear...)
   self.speaker.clear()
   ...
   ```

   `_mark_current_response_cancelled()` 维护 LRU：满 16 个时从头部 pop
   一个，再把当前 id append 到尾部。同时把 `_current_response_id` 置
   None，等下一次 `response.created` 重新填。

4. `_dispatch_tool` 在 `await execute(...)` 返回后再判一次黑名单：

   ```python
   if rid is not None and rid in self._cancelled_response_ids:
       log.debug("skipping ws send for tool %s ...", name)
       self._emit_plan_done()           # 让 SM 不要傻等 leaf response.done
       return                            # 关键：跳过 function_call_output + response.create
   ```

   这一段处理的是 **取消发生在工具执行中** 的赛跑：用户在 50 秒
   `walk` 跑到第 14 秒时按了 `Hi Sparky`，barge-in 的 cancel 已经发完
   也已经把 id 放进黑名单，但 walk 这边的 dispatch task 还在 await
   sleep；50 秒 walk 自然结束之后，`_dispatch_tool` 才回到 `ws.send(
   function_call_output) + response.create` 那两行。如果这两个还发出
   去，就会再次产生 `conversation_already_has_active_response`。我们直
   接静默跳过，并 emit 一次 `plan_done` —— 由于 SM 那边已经因 barge-in
   切到 CAPTURING，`_handle_plan_done` 是 no-op。

### 1.4 副作用 / 已知边界情况

* WS 已经关闭时 `cancel_in_flight()` 仍然会执行
  `_mark_current_response_cancelled()`。这没问题：黑名单是本地状态，
  下次该 id 有事件再来直接丢弃。
* in-flight `_skill_walk` 的 sleep 循环不会被打断 —— 它会一直跑到
  `duration_s` 用完为止。机器人本身已经被 `stop_skill_callable` 设到
  零速所以不会乱动，但 walk 的 task 会在后台多活几十秒。如果你打断后
  马上又下达 walk，两次 walk 的 `set_command` 会交替写入；不在用户报告
  范围内，先标记，必要时再加 `asyncio.Task.cancel()` 路径。
* LRU 容量上限 16 是配合实际使用频次拍的：barge-in 不可能每秒发生几
  十次，这个容量足够覆盖一次会话。

### 1.5 测试

`tests/test_brain_realtime_agent_plan_tracker.py` 新增 7 条用例：

| 用例 | 检查项 |
|---|---|
| `test_audio_delta_for_cancelled_response_is_dropped` | 取消后到达的 audio.delta 既不写扬声器，也不触发 `on_response_audio_delta` 回调 |
| `test_audio_transcript_delta_for_cancelled_response_is_dropped` | "I've moved forward 10 meters" 这种泄漏 transcript 不再打印到 stdout/stderr |
| `test_function_call_arguments_done_for_cancelled_response_is_dropped` | 取消后到达的 tool 调用既不执行 skill 也不发 `response.create` |
| `test_response_done_for_cancelled_response_does_not_fire_plan_done` | 旧响应的 leaf done 不会触发 plan_done（避免错误地驱动 SM 进入 drain） |
| `test_new_response_after_cancel_passes_through` | 新 response_id 的事件**正常**通过 —— 不能因为黑名单意外封掉下一轮 |
| `test_in_flight_dispatch_suppresses_response_create_after_cancel` | "工具执行中被打断" 的赛跑场景：dispatch 跑完后跳过 ws.send，但仍 emit plan_done |
| `test_cancelled_response_id_set_is_bounded` | LRU 上限有效，长会话不会内存泄漏 |

---

## 2. 问题二：连续语义动作被拆成 N 个确认

### 2.1 现场日志切片

```
[user] Turn right by one hundred and eighty degrees.            ← "右转 180 度"
20:01:25  tool call: turn({'yaw_deg': -25})    [g1_brain confirm] y     ← 第 1 次
20:01:29  tool call: turn({'yaw_deg': -25})    [g1_brain confirm] y     ← 第 2 次
20:01:31  tool call: turn({'yaw_deg': -25})    [g1_brain confirm] y     ← 第 3 次
20:01:33  tool call: turn({'yaw_deg': -25})    [g1_brain confirm] y     ← 第 4 次
20:01:38  tool call: turn({'yaw_deg': -25})    [g1_brain confirm] y     ← 第 5 次
20:01:41  tool call: turn({'yaw_deg': -25})    [g1_brain confirm]       ← 用户放弃，没按
20:01:56  [g1_brain confirm] timed out, declining.
          safety rejected turn({'yaw_deg': -25}): operator declined in confirm mode
```

```
[user] Take twenty step backs.                                  ← "后退 20 步"
[robot] Understood. I'll take a few steps back first. Let me check behind to ensure it's clear.
        tool call: look_at({'target': 'behind'})  [g1_brain confirm] y    ← 确认 1
        tool call: describe_scene({'question': 'What is behind the robot?'})
        tool call: walk({'vx': -0.2, 'duration_s': 6})  [g1_brain confirm] y  ← 确认 2
```

注意两个都是用户期望"一次说完，机器人一次做完"的连续语义动作，但因为
工具调用按 schema 的限制被强制拆开，**每个调用都触发一次 y/N**。

### 2.2 根因

**A. Schema 上限 ±45°，安全层上限 ±60°。** LLM 看不见安全层 clamp，
按 schema 的 45° 上限去写参数，自然把 180° 拆成 ~5 段。

**B. `_skill_turn` 几何参数错了。** 旧代码：

```python
_TURN_YAW_RATE_RAD_S = 0.25                 # = 14.32 °/s
_TURN_DURATION_PER_DEG = 1.0 / 25.0         # 0.04 s/deg
_TURN_MAX_DURATION_S = 1.5
duration_s = min(yaw_deg * 0.04, 1.5)
```

正确公式是 `duration = yaw_deg × π / (180 × wz_rate) ≈ yaw_deg ×
0.0698`。旧值 `1/25 = 0.04` 比正确值小 1.74 倍，所以：

* `turn(yaw_deg=25)` 实际只跑 1.0 s × 0.25 rad/s = 0.25 rad ≈ 14.3°
  ——只完成请求的 ~57%；
* 1.5 s 的硬封顶意味着任何单次 turn 最多能跑 21.5°，所以即使你把
  `yaw_deg` 写 200° 也无济于事。

LLM 不知道几何 bug，只能根据 "我刚刚说了 turn(-25)，机器人转完了
（？）；我还没数够 180" 不断再叫一次，越叫越多。

**C. `_TURN_MAX_DURATION_S = 1.5` 直接把单次封顶到 ~21°。** 即使
schema 改对、几何改对，这个上限不动，仍然没法在一个调用里转 180°。

**D. prompt 没有反向行走的硬规则。** "后退 20 步"被 LLM 主动拆成
`look_at(behind)` + `describe_scene` + `walk(-)`，是"我先看一眼再走比
较安全"的合理直觉，但**头顶摄像头根本看不到背后**：

```yaml
# configs/g1_brain.yaml
cameras.head.attach_xyaxes: [0.0, -1.0, 0.0, 0.0, 0.0, 1.0]   # look forward (+X)
```

这是固定朝前的。`look_at("behind")` 转身去看一眼也不能改变摄像头随后
还是只看到当前朝向的前方 —— 转回来再走就更没意义。所以这一步纯粹浪费
一次 confirm，且本来 `_skill_walk` 内部 0.2 s 一次的反应式 abort 已经
能在前进/后退方向都触发"path blocked"。

### 2.3 修复

**A. Schema 范围放大到 ±180°**（`g1_brain/skills/tool_schemas.py`）：

```python
"yaw_deg": {"type": "number", "minimum": -180.0, "maximum": 180.0},
```

并在 description 里直接说明禁止链式调用：

> Use ONE call for the full requested angle (up to ±180°). [...]
> Operator confirmation in confirm-mode is per-call, so chaining many
> small turns for one verbal command (e.g. 7 × turn(-25) for 'turn 180')
> produces 7 y/N prompts and is forbidden — emit a single turn(-180)
> instead.

**B. 安全层 clamp 同步放到 ±180°**（`g1_brain/safety/supervisor.py`）：

```python
return {"yaw_deg": _clip(yaw_deg, -180.0, 180.0)}
```

**C. 修正 `_skill_turn` 几何 + 提高单次时长上限**
（`g1_brain/skills/skill_server.py`）：

```python
import math
_TURN_YAW_RATE_RAD_S = 0.25
_TURN_DURATION_PER_DEG = math.pi / (180.0 * _TURN_YAW_RATE_RAD_S)  # ≈ 0.0698
_TURN_MAX_DURATION_S = 14.0   # 180° at 0.25 rad/s ≈ 12.57 s, +1 s 余量
```

新的几何下：
* `turn(25)` → 1.745 s × 0.25 rad/s = 0.436 rad ≈ 25° ✓
* `turn(90)` → 6.28 s
* `turn(180)` → 12.57 s （仍在 14 s 封顶下）

**D. prompt 明确规定连续语义动作 = 一次确认**
（`g1_brain/brain/prompts.py`）：

```text
- turn(yaw_deg) accepts the FULL requested angle up to ±180° in one call.
  Issue ONE turn(yaw_deg=±N) call for any single verbal turn command.
  NEVER chain multiple small turns for "turn 90°" / "turn 180°" /
  "turn around" — each chained call is a separate operator confirmation.
  The skill rotates at ~14°/s, so turn(180) takes ~13 s; the
  reactive-abort loop still fires if the path becomes unsafe mid-rotation.
- Compound user requests should be ONE confirmation per semantic action
  the user actually asked for. Do not split a single command into a
  pre-flight visual check + the action unless the user explicitly asks
  for the visual check, or the head camera could plausibly help. The
  head camera faces forward, so look_at("behind") cannot actually
  inspect what is behind you before stepping back — skip it for
  backward walks and trust the in-skill reactive-abort.
- Backward walks (vx<0) do NOT need a pre-call to describe_scene/look_at
  — the head camera does not see behind, and the walk skill aborts on
  its own if its forward perception trips. For "step back N meters"
  issue ONE walk call with vx=-0.2 and duration_s=N/0.2.
```

### 2.4 测试

`tests/test_skill_server.py` 新增 4 条 turn 几何回归：

| 用例 | 检查项 |
|---|---|
| `test_turn_constants_are_geometrically_correct` | `_TURN_DURATION_PER_DEG` 与 `π / (180 × wz_rate)` 一致；`_TURN_MAX_DURATION_S × wz_rate ≥ π`（够 180°） |
| `test_turn_short_angle_runs_full_duration_and_zeros` | `turn(10)` 真的跑 `10 × π / (180 × 0.25) ≈ 0.7 s`，且只发了一次非零 wz 命令（不是链式调用） |
| `test_turn_negative_yaw_uses_negative_wz` | 右转（yaw 为负）输出 wz < 0 |
| `test_turn_tiny_yaw_short_circuits` | `turn(0.1)` 短路返回，不发命令 |

`tests/test_tool_schemas.py::test_turn_yaw_bounds` 同步从 `±45.0` 改到
`±180.0` 并加注释说明这是为了消除 confirm-mode 的 7 次 y/N 体验。

> **为什么没写 `turn(180)` 的端到端测试？**
> 测试用真实 `asyncio.sleep`，180° 一次跑要 12.6 秒。CI 里一条用例 12
> 秒不可接受。改用 `turn(10)`（0.7 s）做端到端验证 + 常数测试覆盖
> 几何正确性 + 上限测试。

---

## 3. 两个问题之间的关联

表面上是两件事，根上都是 **Realtime 事件流没有以 response 为单位做边
界管理**：

* 问题一：取消之后没有 response 边界 → 旧 response 的事件渗透到新
  turn → 用户感知"系统没听见我"。
* 问题二：一个语义动作被拆成多个 turn 调用 → 每次都过一次 y/N → 用
  户感知"系统不肯一口气做完"。

修完之后：

* 取消即刻生效，旧响应彻底沉默；
* "一次发声 = 一个响应 = 一次确认" 的契约在简单动作（turn 180、走
  10 m、后退 N m）上恢复；
* 复合工具链（视觉检查 + 动作）只在 prompt 明确允许的情形（前进前
  describe_scene）下保留。

---

## 4. 验证

```bash
$ /home/helios/miniforge3/envs/agi/bin/python -m pytest tests/ -q
........................................................................ [ 25%]
........................................................................ [ 50%]
........................................................................ [ 75%]
.......................................................................  [100%]
287 passed in 5.70s
```

* 基线：276 → 287（新增 11 条）
* 0 条回归
* 旧 `test_turn_yaw_bounds` 改成 ±180.0 后通过
* 新增 7 条 cancelled-response 过滤测试 + 4 条 turn 几何测试

---

## 5. 改动清单

| 文件 | 改动概要 |
|---|---|
| `g1_brain/brain/realtime_agent.py` | 新增 `_current_response_id` / `_cancelled_response_ids` LRU；`_event_response_id()` 静态方法；`_handle_event` 入口加事件丢弃；`cancel_in_flight()` 在 ws.send 前先 `_mark_current_response_cancelled()`；`_dispatch_tool` 在 await 之后判一次黑名单跳过 ws.send |
| `g1_brain/skills/skill_server.py` | `import math`；`_TURN_DURATION_PER_DEG = math.pi / (180.0 * _TURN_YAW_RATE_RAD_S)`；`_TURN_MAX_DURATION_S = 14.0`（原 1.5） |
| `g1_brain/skills/tool_schemas.py` | `_turn()` 的 `yaw_deg` 范围 ±180°；description 重写禁止链式调用 |
| `g1_brain/safety/supervisor.py` | `_sanitize_motion(turn)` 的 clamp 从 ±60° 改 ±180°，并加注释解释为什么 |
| `g1_brain/brain/prompts.py` | 新增三条硬规则：单次 turn 完成全部角度 / 复合命令一次确认 / 后退不需要 look_at(behind) |
| `tests/test_brain_realtime_agent_plan_tracker.py` | +7 用例：cancelled-response 过滤、新 response 直通、in-flight 取消、LRU 上限 |
| `tests/test_skill_server.py` | +4 用例：turn 几何常数、短角度端到端、负角度 wz 方向、零角度短路 |
| `tests/test_tool_schemas.py` | `test_turn_yaw_bounds` 改成 ±180.0 |

---

## 6. 用户复测建议

* "右转 180 度" 应当只弹 **一次** y/N，机器人转 ~12.6 秒后停下。
* "后退 10 米" 应当只弹 **一次** y/N，不再先 `look_at(behind)`。
* 在机器人讲话或走路中按 "Hi Sparky"，1–2 秒内：
  * 扬声器立即静音（不再有"我已经走了 10 米..."这种泄漏）；
  * 机器人停下；
  * 终端不再出现 `tool call: turn / stop` 这种属于旧 plan 的工具调用；
  * 紧接着说出的下一句指令应当**第一次**就被识别并执行。
* 即使重复 barge-in 多次，也不应该再看到
  `conversation_already_has_active_response` 错误或
  `plan_watchdog forcing plan_done` 警告。
