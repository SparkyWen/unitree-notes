# Vision-Only Test Mode — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--vision-only` CLI flag to `python -m va_demo.main` that strips motion tools (walk/gesture/stop/release_arms) and skips DDS/MuJoCo dependence, leaving the wake-word + Realtime + describe_scene loop available as a focused vision-understanding test.

**Architecture:** Add a single boolean knob to `_build_tool_schemas()` and `RealtimeAgent`; introduce a sibling `REALTIME_SYSTEM_PROMPT_VISION_ONLY`; in `main.py` short-circuit `args.no_skills = True` when `--vision-only` is set so the existing skills-disabled branch handles the rest. Default value `vision_only=False` preserves byte-for-byte behavior.

**Tech Stack:** Python 3.11 (agi conda env), pytest, OpenAI Realtime + Responses APIs, websockets, sounddevice, teleimager (ZMQ).

**Spec:** [`../specs/2026-05-04-vision-only-mode-design.md`](../specs/2026-05-04-vision-only-mode-design.md)

---

## File Map

| File | Role |
|---|---|
| `va_demo/prompts.py` | Add `REALTIME_SYSTEM_PROMPT_VISION_ONLY` next to existing prompts |
| `va_demo/realtime_agent.py` | `_build_tool_schemas(vision_only)`; `RealtimeAgent.vision_only` field; session.update picks correct schemas + prompt |
| `va_demo/main.py` | Parse `--vision-only`; force `args.no_skills = True` when set; pass `vision_only=` into `RealtimeAgent`; banner log |
| `configs/va_demo.yaml` | Add documentary `vision_only: false` (CLI flag is the source of truth) |
| `tests/test_vision_only_mode.py` | New: 3 cases asserting tool schema + prompt selection |
| `README.md` | New "Vision-only test mode" subsection |

---

## Task 1: Add `vision_only` parameter to tool schema builder (TDD)

**Files:**
- Test: `va-demo/tests/test_vision_only_mode.py` (create)
- Modify: `va-demo/va_demo/realtime_agent.py:43-129` (the `_build_tool_schemas` function)

- [ ] **Step 1.1: Write the failing tests for the schema builder**

Create `va-demo/tests/test_vision_only_mode.py`:

```python
"""Unit tests for vision-only mode tool schema + prompt selection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from va_demo.realtime_agent import _build_tool_schemas


def test_tool_schemas_default_keeps_all_tools():
    schemas = _build_tool_schemas()  # default vision_only=False
    names = {s["name"] for s in schemas}
    assert names == {"say", "stop", "release_arms", "walk", "gesture", "describe_scene"}


def test_tool_schemas_vision_only_excludes_motion_tools():
    schemas = _build_tool_schemas(vision_only=True)
    names = {s["name"] for s in schemas}
    assert names == {"say", "describe_scene"}


def test_tool_schemas_vision_only_keeps_describe_scene_shape():
    """The describe_scene schema in vision-only mode is identical to default."""
    full = {s["name"]: s for s in _build_tool_schemas(vision_only=False)}
    vis = {s["name"]: s for s in _build_tool_schemas(vision_only=True)}
    assert vis["describe_scene"] == full["describe_scene"]
    assert vis["say"] == full["say"]
```

- [ ] **Step 1.2: Run the tests; confirm failure**

```bash
cd ~/unitree/unitree-notes/va-demo
pytest tests/test_vision_only_mode.py -v
```

Expected: at least one test fails with `TypeError: _build_tool_schemas() got an unexpected keyword argument 'vision_only'` (or equivalent).

- [ ] **Step 1.3: Modify `_build_tool_schemas` to accept `vision_only`**

In `va-demo/va_demo/realtime_agent.py`, change the function signature and filter at the end. Replace the existing function (lines ~43-129):

```python
def _build_tool_schemas(vision_only: bool = False) -> List[Dict[str, Any]]:
    gesture_enum = [
        "wave_right", "wave_left", "hands_up", "t_pose",
        "salute", "clap", "guard", "punch_combo",
    ]
    schemas = [
        {
            "type": "function",
            "name": "say",
            "description": (
                "Speak a short message to the user via OpenAI TTS. Prefer this "
                "for canned/short replies; the Realtime audio reply is usually "
                "better for conversational content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 200},
                },
                "required": ["text"],
            },
        },
        {
            "type": "function",
            "name": "stop",
            "description": "Immediately stop walking and release any active arm gesture.",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "release_arms",
            "description": "Hand the arms back to the locomotion policy (no walking change).",
            "parameters": {"type": "object", "properties": {}},
        },
        {
            "type": "function",
            "name": "walk",
            "description": (
                "Walk for a short duration. Conservative bounds; do not exceed "
                "0.2 m/s unless the user insists."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "vx": {"type": "number", "minimum": -0.3, "maximum": 0.3,
                            "description": "forward velocity m/s"},
                    "vy": {"type": "number", "minimum": -0.1, "maximum": 0.1,
                            "description": "lateral velocity m/s"},
                    "wz": {"type": "number", "minimum": -0.4, "maximum": 0.4,
                            "description": "yaw rate rad/s"},
                    "duration_s": {"type": "number", "minimum": 0.2, "maximum": 1.5},
                },
                "required": ["duration_s"],
            },
        },
        {
            "type": "function",
            "name": "gesture",
            "description": "Play one prevalidated arm gesture. The robot keeps walking unaffected.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": gesture_enum},
                },
                "required": ["name"],
            },
        },
        {
            "type": "function",
            "name": "describe_scene",
            "description": (
                "Take one snapshot from the front camera and ask the vision "
                "model to describe what it sees. Use this whenever the user "
                "asks any visual question."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Optional specific question to answer about the scene.",
                    },
                    "detail": {"type": "string", "enum": ["low", "medium", "high"]},
                },
            },
        },
    ]
    if vision_only:
        keep = {"say", "describe_scene"}
        schemas = [s for s in schemas if s["name"] in keep]
    return schemas
```

- [ ] **Step 1.4: Run the tests; confirm pass**

```bash
pytest tests/test_vision_only_mode.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add va-demo/va_demo/realtime_agent.py va-demo/tests/test_vision_only_mode.py
git commit -m "$(cat <<'EOF'
feat(va-demo): _build_tool_schemas(vision_only=) flag

When vision_only=True, drop walk/gesture/stop/release_arms from the
schema list so the Realtime model cannot call motor tools. Default
False preserves existing behavior. New tests cover both paths.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Add `REALTIME_SYSTEM_PROMPT_VISION_ONLY` constant

**Files:**
- Modify: `va-demo/va_demo/prompts.py`
- Modify: `va-demo/tests/test_vision_only_mode.py` (extend)

- [ ] **Step 2.1: Extend the test file with prompt assertions**

Append to `va-demo/tests/test_vision_only_mode.py`:

```python
def test_vision_only_prompt_exists_and_excludes_motion_words():
    from va_demo.prompts import REALTIME_SYSTEM_PROMPT, REALTIME_SYSTEM_PROMPT_VISION_ONLY

    p = REALTIME_SYSTEM_PROMPT_VISION_ONLY
    assert p, "vision-only prompt is empty"
    # Must NOT advertise motion tools
    assert "walk" not in p.lower()
    assert "gesture" not in p.lower()
    # Must still mention describe_scene and the self-name rule (carried over)
    assert "describe_scene" in p
    assert "Sparky" in p
    # Must be a different string from the default (sanity)
    assert p != REALTIME_SYSTEM_PROMPT
```

- [ ] **Step 2.2: Run the test; confirm failure**

```bash
pytest tests/test_vision_only_mode.py::test_vision_only_prompt_exists_and_excludes_motion_words -v
```

Expected: `ImportError: cannot import name 'REALTIME_SYSTEM_PROMPT_VISION_ONLY'`.

- [ ] **Step 2.3: Add the new constant in `prompts.py`**

Append to `va-demo/va_demo/prompts.py`:

```python


REALTIME_SYSTEM_PROMPT_VISION_ONLY = """\
You are the voice agent of a Unitree G1 humanoid robot running in a MuJoCo
simulator. The user calls you "Sparky". You are currently in VISION-TEST mode:
you can speak with the user and look at the camera (via the describe_scene
tool), but you CANNOT move. There are no walk, gesture, stop, or release_arms
tools available in this mode.

Rules:
- When the user asks anything about what's around you, what's in front of you,
  what you see, who's there, or any visual question, ALWAYS call describe_scene
  first. Do not guess.
- If the user asks you to move, walk, or gesture, briefly explain that motion
  is disabled in vision-test mode and offer to describe the scene instead.
- If a tool returns ok=false, briefly explain the reason. Do not retry the
  same call.
- Speak in the user's language (Chinese or English). Keep replies short and
  natural. Do not narrate every tool call.
- IMPORTANT: never refer to yourself as "Sparky" in your replies. Say "I" or
  "the robot" instead. The wake-word detector listens for "Sparky", and if
  you say it yourself you will accidentally interrupt your own answer.
"""
```

- [ ] **Step 2.4: Run the test; confirm pass**

```bash
pytest tests/test_vision_only_mode.py::test_vision_only_prompt_exists_and_excludes_motion_words -v
```

Expected: pass.

- [ ] **Step 2.5: Commit**

```bash
git add va-demo/va_demo/prompts.py va-demo/tests/test_vision_only_mode.py
git commit -m "$(cat <<'EOF'
feat(va-demo): REALTIME_SYSTEM_PROMPT_VISION_ONLY

New system prompt for vision-test mode: explicitly tells the Realtime
model that motion tools are unavailable and that visual questions go
through describe_scene. Carries over the self-name and language rules
from the default prompt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire `vision_only` into `RealtimeAgent`

**Files:**
- Modify: `va-demo/va_demo/realtime_agent.py:134-206` (dataclass + `_session_update`)
- Modify: `va-demo/tests/test_vision_only_mode.py` (extend)

- [ ] **Step 3.1: Extend the test file with agent-level assertion**

Append to `va-demo/tests/test_vision_only_mode.py`:

```python
def test_realtime_agent_vision_only_resolves_to_vision_prompt_and_schemas():
    """RealtimeAgent.vision_only=True must select the vision prompt and
    the trimmed schema set. We construct the agent with stub deps so we
    can read its resolved values without going async."""
    from unittest.mock import MagicMock

    from va_demo.prompts import REALTIME_SYSTEM_PROMPT, REALTIME_SYSTEM_PROMPT_VISION_ONLY
    from va_demo.realtime_agent import RealtimeAgent

    stub = MagicMock()
    common = dict(
        api_key="sk-test",
        model="gpt-realtime",
        voice="alloy",
        mic=stub,
        speaker=stub,
        camera=stub,
        vision=stub,
        tts=stub,
        skills=None,
        safety=stub,
    )

    a_default = RealtimeAgent(**common)  # vision_only defaults to False
    assert a_default.vision_only is False
    assert a_default._resolve_instructions() == REALTIME_SYSTEM_PROMPT
    names = {s["name"] for s in a_default._resolve_tool_schemas()}
    assert "walk" in names and "describe_scene" in names

    a_vision = RealtimeAgent(vision_only=True, **common)
    assert a_vision.vision_only is True
    assert a_vision._resolve_instructions() == REALTIME_SYSTEM_PROMPT_VISION_ONLY
    names = {s["name"] for s in a_vision._resolve_tool_schemas()}
    assert names == {"say", "describe_scene"}
```

- [ ] **Step 3.2: Run the test; confirm failure**

```bash
pytest tests/test_vision_only_mode.py::test_realtime_agent_vision_only_resolves_to_vision_prompt_and_schemas -v
```

Expected: failure — `vision_only` field doesn't exist; `_resolve_*` methods don't exist.

- [ ] **Step 3.3: Add the field + helpers + use them in `_session_update`**

In `va-demo/va_demo/realtime_agent.py`:

(1) Update the imports near the top (around line 28-33) to include the new prompt:

```python
from .prompts import REALTIME_SYSTEM_PROMPT, REALTIME_SYSTEM_PROMPT_VISION_ONLY, VISION_SCENE_PROMPT
```

(2) Add the `vision_only` field to the `RealtimeAgent` dataclass. After the existing fields (e.g. after `on_response_done`), add:

```python
    vision_only: bool = False
```

(3) Add two private helpers as methods on `RealtimeAgent` (place them near `_session_update`):

```python
    def _resolve_instructions(self) -> str:
        return (
            REALTIME_SYSTEM_PROMPT_VISION_ONLY
            if self.vision_only
            else REALTIME_SYSTEM_PROMPT
        )

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        return _build_tool_schemas(vision_only=self.vision_only)
```

(4) Modify `_session_update` to use them. Replace the existing body (lines ~191-206):

```python
    async def _session_update(self, ws):
        evt = {
            "type": "session.update",
            "session": {
                "modalities": ["audio", "text"],
                "voice": self.voice,
                "instructions": self._resolve_instructions(),
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
                "turn_detection": None,
                "tools": self._resolve_tool_schemas(),
                "tool_choice": "auto",
            },
        }
        await ws.send(json.dumps(evt))
```

- [ ] **Step 3.4: Run the new test; confirm pass**

```bash
pytest tests/test_vision_only_mode.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 3.5: Run the full suite to confirm no regression**

```bash
pytest tests/ -v
```

Expected: all 49 + 5 = 54 tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add va-demo/va_demo/realtime_agent.py va-demo/tests/test_vision_only_mode.py
git commit -m "$(cat <<'EOF'
feat(va-demo): RealtimeAgent.vision_only field

When vision_only=True, the session.update picks
REALTIME_SYSTEM_PROMPT_VISION_ONLY and the trimmed tool schema set
(say + describe_scene only). Default False preserves existing wiring.
Two private helpers (_resolve_instructions, _resolve_tool_schemas)
keep the toggle test-friendly without standing up a websocket.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `--vision-only` CLI flag in `main.py`

**Files:**
- Modify: `va-demo/va_demo/main.py:55-269`

- [ ] **Step 4.1: Add the CLI flag**

In `parse_args()` (around line 256-269), add a new argument before the `-v` flag:

```python
    p.add_argument("--vision-only", action="store_true",
                   help="vision-only test mode: drop motion tools (walk/gesture/stop/release_arms) "
                        "from the Realtime schema and skip DDS/ComboController init. "
                        "Implies --no-skills. MuJoCo is not required.")
```

- [ ] **Step 4.2: Force `no_skills=True` when vision-only is set**

In `_run(args)` near the top (after `cfg = _load_config(args.config)` around line 56-57), add:

```python
    if args.vision_only:
        # Vision-only mode runs without DDS / ComboController; mujoco does not
        # need to be running. The existing --no-skills branch handles the
        # rest of the bypass.
        if not args.no_skills:
            log.info("--vision-only implies --no-skills; skipping DDS init")
        args.no_skills = True
```

- [ ] **Step 4.3: Pass `vision_only` into `RealtimeAgent`**

In `_run(args)`, find the `RealtimeAgent(...)` constructor call (around line 153-167) and add the kwarg:

Existing:
```python
    agent = RealtimeAgent(
        api_key=api_key,
        model=os.environ.get("OPENAI_REALTIME_MODEL", cfg["openai"]["realtime_model"]),
        voice=cfg["openai"]["realtime_voice"],
        mic=mic,
        speaker=speaker,
        camera=cam,
        vision=vision_client,
        tts=tts_client,
        skills=skill_backend,
        safety=sup,
        vision_resize_width=cfg["camera"]["vision_resize_width"],
        vision_jpeg_quality=cfg["camera"]["vision_jpeg_quality"],
        spoken_cache=spoken_cache,
    )
```

Change to:
```python
    agent = RealtimeAgent(
        api_key=api_key,
        model=os.environ.get("OPENAI_REALTIME_MODEL", cfg["openai"]["realtime_model"]),
        voice=cfg["openai"]["realtime_voice"],
        mic=mic,
        speaker=speaker,
        camera=cam,
        vision=vision_client,
        tts=tts_client,
        skills=skill_backend,
        safety=sup,
        vision_resize_width=cfg["camera"]["vision_resize_width"],
        vision_jpeg_quality=cfg["camera"]["vision_jpeg_quality"],
        spoken_cache=spoken_cache,
        vision_only=args.vision_only,
    )
    if args.vision_only:
        log.info("vision-only mode: tools=[say, describe_scene]; motion tools removed")
```

- [ ] **Step 4.4: Verify the CLI prints the new flag**

```bash
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main --help
```

Expected: output includes the `--vision-only` line.

- [ ] **Step 4.5: Verify import / module loads cleanly**

```bash
python -c "import va_demo.main"
```

Expected: no error.

- [ ] **Step 4.6: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all tests still pass.

- [ ] **Step 4.7: Commit**

```bash
git add va-demo/va_demo/main.py
git commit -m "$(cat <<'EOF'
feat(va-demo): --vision-only CLI flag

New flag wires RealtimeAgent.vision_only=True and implies --no-skills,
so va-demo can run a wake-word + Realtime + describe_scene loop without
MuJoCo or DDS. Banner log calls out the trimmed tool list at startup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Documentary `vision_only: false` in yaml

**Files:**
- Modify: `va-demo/configs/va_demo.yaml`

- [ ] **Step 5.1: Append a `vision_only: false` line near `run_mode`**

Open `va-demo/configs/va_demo.yaml`. Find the last line (`run_mode: "confirm"`). Append:

```yaml

# vision-only test mode: when true (or when --vision-only is passed on CLI),
# the Realtime model only sees [say, describe_scene] tools, system prompt is
# replaced with the vision-only variant, and DDS/ComboController init is
# skipped. Source of truth is the CLI flag; this entry is documentary so the
# yaml lists every supported knob.
vision_only: false
```

- [ ] **Step 5.2: Sanity-load the yaml**

```bash
cd ~/unitree/unitree-notes/va-demo
python -c "import yaml; print(yaml.safe_load(open('configs/va_demo.yaml'))['vision_only'])"
```

Expected: `False`.

- [ ] **Step 5.3: Commit**

```bash
git add va-demo/configs/va_demo.yaml
git commit -m "$(cat <<'EOF'
docs(va-demo): document vision_only knob in yaml

Pure documentation entry mirroring the --vision-only CLI flag so the
yaml lists every supported tunable. CLI flag is still the source of
truth for this iteration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: README — "Vision-only test mode" subsection

**Files:**
- Modify: `va-demo/README.md` (insert before "Quick verification" section, after "CLI flags" table)

- [ ] **Step 6.1: Insert the new subsection**

Open `va-demo/README.md`. Find the line `## CLI flags for `python -m va_demo.main\`` and the following table. Update the table to include the new flag and add a subsection right after the table.

(1) In the CLI flags table (around line 197-204), add this row before `-v / --verbose`:

```markdown
| `--vision-only` | off | trim motion tools, skip DDS init; only `say` + `describe_scene` exposed to the Realtime model. Implies `--no-skills`; mujoco not required |
```

(2) Immediately after that table, insert this new section:

```markdown

---

## Vision-only test mode

For testing the keyframe → vision → speech loop in isolation (no walking, no
gestures, no MuJoCo), launch with:

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main --vision-only -v
```

Only **two terminals** are needed in this mode:

1. `teleimager.image_server` (camera frames)
2. `va_demo.main --vision-only` (this process)

`unitree_mujoco.py` does **not** need to be running. The Realtime model is
launched with a vision-only system prompt and a trimmed tool list:

| Tool exposed | Purpose |
|---|---|
| `say(text)` | canned TTS reply |
| `describe_scene(question?, detail?)` | snapshot frame → vision model (`gpt-5.5` by default; override with `OPENAI_VISION_MODEL`) |

`walk` / `gesture` / `stop` / `release_arms` are **not** advertised to the
model in this mode — even if you ask, it will tell you motion is disabled
and offer to describe the scene instead.

Conversation example:

- You: "Hi Sparky"
- (wake-word fires; mic uplink opens)
- You: "看看前面有什么？"
- (1.5 s silence → utterance commits → Realtime calls `describe_scene`)
- Sparky: "我看到桌子上有……" (spoken, in the user's language)
- (8 s listening window — you can ask a follow-up without re-saying the wake word)

```

- [ ] **Step 6.2: Eyeball the rendered Markdown**

```bash
sed -n '/^## Vision-only test mode/,/^---$/p' va-demo/README.md
```

Expected: the new section prints, ending at the `---` divider before the next section.

- [ ] **Step 6.3: Commit**

```bash
git add va-demo/README.md
git commit -m "$(cat <<'EOF'
docs(va-demo): README "Vision-only test mode" section

New subsection + CLI flag table row covering --vision-only: which two
terminals are required (teleimager + va-demo, no mujoco), what tools
the Realtime model sees, and a sample conversation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Final regression sweep + import smoke

**Files:** none (verification only)

- [ ] **Step 7.1: Run the full pytest suite**

```bash
cd ~/unitree/unitree-notes/va-demo
pytest tests/ -v
```

Expected: 54 (49 existing + 5 new) tests pass.

- [ ] **Step 7.2: Import-only smoke**

```bash
python -c "import va_demo.audio_io, va_demo.camera, va_demo.vision, va_demo.tts, va_demo.skills, va_demo.safety, va_demo.realtime_agent, va_demo.main, va_demo.prompts"
```

Expected: no error.

- [ ] **Step 7.3: CLI help smoke**

```bash
python -m va_demo.main --help
```

Expected: `--vision-only` listed; `--help` exits cleanly.

- [ ] **Step 7.4: Verify the spec acceptance criteria are all green by inspection**

Open `docs/superpowers/specs/2026-05-04-vision-only-mode-design.md` §10 and confirm each criterion 1–5 is satisfied:

1. `--help` shows the flag → covered by Step 7.3
2. Smoke procedure produces a spoken description → manual; documented in §7.3
3. Without `--vision-only`, behavior unchanged → covered by Step 7.1 (49 existing tests still green)
4. In vision-only mode the model never receives motion schemas → covered by tests in `test_vision_only_mode.py`
5. va-demo starts cleanly with `--vision-only` even without MuJoCo → covered by `args.no_skills = True` short-circuit in main.py

No commit (verification only).

---

## Task 8 (manual, by operator): live smoke test

**This task is run by the human operator, not by the agent. The plan is
considered complete after Tasks 1–7 are merged; Task 8 is the operator's
acceptance gate.**

- [ ] **Step 8.1:** In Terminal 1, start teleimager:
  ```bash
  conda activate agi
  cd ~/unitree/unitree-notes/teleimager
  python -m teleimager.image_server
  ```
- [ ] **Step 8.2:** In Terminal 2, start va-demo in vision-only mode:
  ```bash
  conda activate agi
  cd ~/unitree/unitree-notes/va-demo
  export OPENAI_API_KEY=sk-...
  python -m va_demo.main --vision-only -v
  ```
  Wait for "wake-word enabled" and "vision-only mode" log lines.
- [ ] **Step 8.3:** Say "Hi Sparky".
  - Expected: state machine log goes IDLE → CAPTURING.
- [ ] **Step 8.4:** Say "前面有什么？" or "What do you see?".
  - Expected: state goes CAPTURING → THINKING → SPEAKING; you hear Sparky describe the camera scene; tool log shows `describe_scene(...)`.
- [ ] **Step 8.5:** Try to ask Sparky to walk: "向前走一步".
  - Expected: Sparky declines and offers to describe the scene; no `walk` tool call appears in the log.
- [ ] **Step 8.6:** Ctrl-C to stop.

If any step fails, file the failure mode against the spec; do not patch in this branch without re-spec.

---

## Self-Review

**1. Spec coverage:**
- §3 user-visible behavior → Task 4 (CLI flag) + Task 6 (README)
- §4.1 file map → matches Tasks 1–6 one-to-one
- §4.2 prompt + tool variants → Tasks 1, 2
- §4.3 main.py wiring → Task 4
- §5 data flow → no code change required (uses existing pipeline); validated end-to-end by Task 8
- §6 error handling → no new failure surfaces; existing handlers reused; tested manually in Task 8 step 5
- §7.1 unit tests → Tasks 1, 2, 3 cover all 5 cases planned in spec
- §7.2 regression → Task 3 step 5, Task 7 step 1
- §7.3 manual smoke → Task 8
- §8 backwards compat → enforced by `vision_only=False` default in Task 1, Task 3
- §10 acceptance criteria → mapped explicitly in Task 7 step 4

**2. Placeholder scan:** no TBD / TODO / "implement later"; all code blocks are complete; all bash commands are exact.

**3. Type consistency:** `vision_only: bool` used consistently across `_build_tool_schemas`, `RealtimeAgent`, `parse_args`. Helper names `_resolve_instructions` / `_resolve_tool_schemas` used identically in Task 3 step 3 and Task 3 step 1 test.

No fixes needed.
