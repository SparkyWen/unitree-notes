# Extending the SkillServer

The 4 places to touch when adding a new tool. Order matters — the test is
the cheapest way to catch interface drift, so write it first.

---

## 1. Decide the layer

| If the skill is ... | Add it as |
| --- | --- |
| an *intent* the LLM should think about ("approach the chair") | **L1** — high-level, accepts symbolic args, internally calls L2/L3. |
| a parameterized motion ("walk vx=0.2 for 0.5 s") | **L2** — concrete bounds on every numeric arg, single underlying skill call. |
| a static keyframe pose ("salute") | **L2 static_pose name** — extend the enum in `tool_schemas.py`. |

L3 (raw joint angles) is **never** exposed to the LLM. If you need a
new joint motion, wrap it in an L2 skill with bounded args and add a new
`_skill_<name>` method.

---

## 2. Add the JSON schema (`skills/tool_schemas.py`)

OpenAI Realtime tools need `{"type": "function", "name": "...",
"description": "...", "parameters": {...}}`. Keep descriptions short —
they go into every Realtime session prompt and burn tokens.

```python
{
    "type": "function",
    "name": "look_at",
    "description": (
        "Turn the body to face one of: person, ahead, left, right, ground."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["person", "ahead", "left", "right", "ground"],
            },
        },
        "required": ["target"],
    },
},
```

Then add `look_at` to the appropriate set in `safety/supervisor.py`:

- `ALLOWED_MOTION_TOOLS` if it commands motion
- `ALLOWED_TOOLS_NO_MOTION` if it's pure I/O (say / describe / query)
- `REAL_ROBOT_ONLY_TOOLS` if it needs a real-robot client

(The supervisor refuses anything not in `ALLOWED_TOOLS = motion |
no_motion | real_only`. Forgetting to add it here is the #1 cause of
"LLM call returns ok=false reason='unknown tool'" bugs.)

---

## 3. Implement `_skill_<name>` in `skills/skill_server.py`

```python
async def _skill_look_at(self, target: str) -> dict:
    # Symbolic target -> concrete yaw (caller is L1; we delegate to L2 turn).
    yaw = {"person": 0.0, "ahead": 0.0,
           "left": -30.0, "right": 30.0, "ground": 0.0}[target]
    if target == "ground":
        # nod head down; not all sims support this — fall back gracefully.
        return {"ok": False, "reason": "not implemented in sim v1",
                "scene": self.scene.snapshot().summary_for_llm()}
    return await self._skill_turn(yaw_deg=yaw)
```

Conventions:

- Coroutine, not a sync function. SkillServer.execute is async; you can
  `await` other `_skill_*` methods.
- Always return a dict with `"ok": bool` and optionally `"reason"`,
  `"skill"`, `"actual_duration_s"`. Add `"scene":
  scene_bus.snapshot().summary_for_llm()` so the LLM doesn't need a
  follow-up `query_scene_state` call.
- For **walk-style** skills that take time, re-read the scene every
  ~0.2s (`time.monotonic()`-driven loop with `await asyncio.sleep`) and
  abort if `clear_path` flips false. See `_skill_walk` for the pattern.
- Catch known exceptions; let unknown ones bubble up to
  `SkillServer.execute` which has a generic `try/except` that calls
  `_skill_stop()` and returns `ok=False`.

---

## 4. Tighten safety if needed (`safety/supervisor.py`)

The 11 rules already cover walk + gesture + estop. New skills usually
fit one of these patterns:

- **Pure motion of legs** (push, kick, jump): treat exactly like `walk`
  — needs all four scene checks. Add the tool name to the
  `tool in {"walk", "approach"}` branches around lines 250–315.
- **Arm-only motion** (a new gesture name, salute variant): treat like
  `gesture` — only the `min_person_for_gesture_m` rule applies. Add to
  the `tool in {"gesture", "mock_imitate", "static_pose"}` branch.
- **Symbolic / data-only** (look_at when it just queries IMU yaw, ask_human
  which is a TTSClient call): no extra rule needed; it's already covered
  by FSM gating + run_mode + estop.
- **Real-robot-only**: add to `REAL_ROBOT_ONLY_TOOLS`. The supervisor
  rejects with `sim_only:` when `cfg.mode == "sim"`.

If the new skill needs a *new* numeric clamp (e.g. an `approach` skill
with a max_distance), add a section in `_sanitize_motion` and wire
the bound to a new key under `safety:` in `g1_brain.yaml`.

---

## 5. Add a test (`tests/test_skill_server.py`)

Tests live alongside the existing skill tests. Pattern (you can copy
from the walk test):

```python
async def test_skill_look_at_person(monkeypatch):
    sup = _build_test_supervisor(run_mode="active", state="ENGAGED",
                                  scene={"clear_path": True,
                                         "nearest_obstacle_m": 5.0,
                                         "nearest_person_m": 1.5})
    server = _build_test_skill_server(supervisor=sup)
    res = await server.execute("look_at", {"target": "person"})
    assert res["ok"] is True
    assert "scene" in res
```

Run it:

```bash
pytest tests/test_skill_server.py -v -k look_at
```

If you also added a new safety rule, add a row to
`tests/test_safety_supervisor.py`.

---

## 6. (Optional) Update perception

If the skill needs new data — e.g. `approach(target_name="chair")` needs
a class-name lookup against head detections — propose a change to
`SceneState`:

1. Add a field to `scene_state/types.py::SceneState`. Keep it
   `Optional[...]` so existing producers don't break.
2. Add an `update_*` method on `SceneStateBus` and rebuild it in
   `snapshot()`.
3. Update the producer (perception/runner.py) to call the new updater.
4. Re-export the field through `summary_for_llm()` if the LLM should see
   it directly.

Avoid putting raw images / numpy arrays in SceneState — the contract is
that the safety + brain layers see only summarized scalars and small
lists. If you need the image, fetch it from `CameraHub` directly inside
the skill.

---

## 7. (Optional) Update prompts

If you want the LLM to *prefer* the new skill over an existing one, edit
`brain/prompts.py::REALTIME_SYSTEM_PROMPT_BRAIN`. Mention the new tool
in the "You can:" section, and add a one-line guideline if there's a
common misuse to avoid (mirror the "Before you walk forward, ALWAYS call
describe_scene first" line for navigation).

Don't forget the vision-only prompt
(`REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY`) — it must NOT contain the
word `walk` or `gesture` (those echo into the wake-word detector and
trip false utterances; design doc §5.3 explains the constraint).

---

## 8. Checklist before merging

- [ ] Tool added to `tool_schemas.py`
- [ ] Tool name in `ALLOWED_*_TOOLS` in `supervisor.py`
- [ ] `_skill_<name>` implemented in `skill_server.py`
- [ ] Returns `{"ok": bool, "scene": ..., ...}` shape
- [ ] Re-reads scene mid-execution for any motion that lasts > 0.3 s
- [ ] Test in `tests/test_skill_server.py`
- [ ] If new safety rule, test in `tests/test_safety_supervisor.py`
- [ ] If new SceneState field, `summary_for_llm()` updated and tested
- [ ] If new safety bound, key added under `safety:` in `g1_brain.yaml`
- [ ] Manually invoked once via `python -m g1_brain.apps.skill_debug`
