# va-demo

Voice + vision agent for the Unitree G1 in MuJoCo simulation. Built on top of:

- `g1_sim_demo/g1_sim_rl_combo.py` — RL walking + 8 arm gestures (imported, not modified)
- `teleimager` — image server feeding head-camera frames over ZMQ
- OpenAI **Realtime API** — full-duplex voice conversation with tool calls
- OpenAI **Responses API (vision)** — single-frame scene description tool
- OpenAI **Audio Speech (TTS)** — canned/agent-initiated speech

Design doc: [`docs/va-demo-design.md`](../docs/va-demo-design.md).

---

## What it does

You speak to the laptop microphone. The Realtime model talks back through the
speaker in low latency. When you ask anything visual ("what do you see?",
"看看前面"), the model calls `describe_scene` → va-demo grabs the latest frame
from the TeleImager server → sends it to the vision model → returns a short
text answer that the Realtime model speaks back. When you ask the robot to
walk or wave, it tool-calls `walk(...)` / `gesture(...)`, the safety
supervisor validates, and the existing `ComboController` executes in the
MuJoCo sim.

Tools the model can call:

| Tool | Purpose |
|---|---|
| `say(text)` | TTS canned reply |
| `stop()` | zero velocity + release arms |
| `release_arms()` | hand arms back to the locomotion policy |
| `walk(vx, vy, wz, duration_s)` | short low-speed move |
| `gesture(name)` | one of: wave_right, wave_left, hands_up, t_pose, salute, clap, guard, punch_combo |
| `describe_scene(question?, detail?)` | snapshot frame → vision model |

---

## Wake word

The agent does **not** stream mic audio to OpenAI Realtime until you say
"**Hi, Sparky**". This solves two problems the original always-on Realtime
session had:

1. The Realtime API's server VAD was so eager that any cough committed a turn.
2. Sparky's own TTS playback bled into the mic and Sparky kept cutting itself
   off mid-reply.

After the wake word fires, you speak your request normally. When you stop
talking for ~1.5 s the whole utterance is committed in one shot. After
Sparky replies, you have an 8 s "listening window" where you can speak
again **without** re-saying the wake word — useful for follow-ups like
"那再向前走两步".

The wake-word detector is `faster-whisper` `tiny` running locally on CPU.
First launch downloads the model (~75 MB) into `~/.cache/huggingface`.

Tuning lives in `configs/va_demo.yaml::wakeword`. The two values you most
often want to touch:

- `wakeword.rms_threshold` — minimum mic loudness for the matcher to even
  consider firing. Raise if the detector triggers on background sound;
  lower if it doesn't fire when you talk normally.
- `wakeword.phrases` — substring list. Add variants ("hi sparkie",
  "嗨 spark") if your accent doesn't match the defaults.

To verify the model and mic before plumbing through Realtime:

```bash
python scripts/wake_word_debug.py
# say "Hi Sparky" — you should see a WAKE line print.
```

Behavior summary:

- Sparky cannot interrupt itself: its own TTS playback never triggers a
  new turn, and a system-prompt rule keeps it from saying "Sparky" out loud.
- You can interrupt Sparky mid-reply by saying "Hi, Sparky …" — the
  current response is cancelled and your new utterance is captured.
- Wake-word matches that overlap with Sparky's recent transcript window
  are suppressed (`conversation.selfecho_dedup_window_s = 6.0` by default).

To bypass the wake word entirely (legacy, hair-trigger Realtime
behavior — only useful for A/B debugging):

```bash
python -m va_demo.main --no-wakeword
```

---

## Run order (3 terminals, all in the `agi` conda env)

### 0. One-time setup

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...   # required
```

If your account doesn't have `gpt-5.5` enabled, override:

```bash
export OPENAI_VISION_MODEL=gpt-5.1     # or whatever vision-capable model is available
export OPENAI_REALTIME_MODEL=gpt-realtime
export OPENAI_TTS_MODEL=gpt-4o-mini-tts
```

### 1. Terminal 1 — MuJoCo simulator

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# in the mujoco viewer, press 8 a few times to lower the elastic band; optionally 9 to disable
```

### 2. Terminal 2 — TeleImager image server

```bash
conda activate agi
cd ~/unitree/unitree-notes/teleimager
python -m teleimager.image_server
```

(WSL2 + USB camera setup is documented in `docs/camera_ui_demo.md`.)

### 3. Terminal 3 — va-demo agent

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
python -m va_demo.main
```

Default mode is `confirm`: motion tool calls print a y/N prompt before
executing. Use `--mode active` once you trust the agent in your scene, or
`--mode observe` to disable motion entirely (vision + TTS still work).

---

## Quick verification (no live services needed)

```bash
cd ~/unitree/unitree-notes/va-demo
python -m pytest tests/ -v
python -c "import va_demo.audio_io, va_demo.camera, va_demo.vision, va_demo.tts, va_demo.skills, va_demo.safety, va_demo.realtime_agent, va_demo.main"
python -m va_demo.main --help
```

`pytest` covers the safety supervisor (whitelist, bounds, modes, watchdog) and
the skill backend (with a fake ComboController). It does not exercise audio,
camera, or OpenAI calls.

### Audio prerequisites in WSL2

`sounddevice` needs PortAudio + a usable host API. If `python -c "import
sounddevice as sd; print(sd.query_devices())"` returns an empty list:

1. Install PortAudio in the conda env:
   `conda install -n agi -c conda-forge portaudio`
2. Confirm WSLg's PulseServer is exposed:
   `ls /mnt/wslg/PulseServer && echo "$PULSE_SERVER"`
3. If only ALSA shows under `query_devices()` and there are no cards, install
   the ALSA→Pulse plugin or attach a USB sound device via `usbipd` (same
   pattern as the camera in `docs/camera_ui_demo.md`).
4. As a last resort, set explicit device indices in
   `configs/va_demo.yaml::audio.input_device` /
   `audio.output_device`.

## Live verification (requires the live services)

```bash
# 1. audio loopback (mic -> speaker echo, 5 s)
python scripts/audio_loopback.py

# 2. camera + vision (needs teleimager.image_server + OPENAI_API_KEY)
python scripts/camera_debug.py --question "前面有什么？"

# 3. TTS (needs speaker + OPENAI_API_KEY)
python scripts/tts_debug.py "你好，我是 G1。"

# 4. skills only (needs unitree_mujoco)
python scripts/skill_debug.py
# then type w / 1 / 8 / r / x

# 5. vision loop at 1 Hz (needs teleimager + OPENAI_API_KEY)
python scripts/vision_loop_debug.py --rate-hz 1.0
```

---

## CLI flags for `python -m va_demo.main`

| Flag | Default | Effect |
|---|---|---|
| `--config` | `configs/va_demo.yaml` | YAML config path |
| `--mode {observe,confirm,active}` | `confirm` | safety run mode |
| `--no-realtime` | off | skip Realtime; just keep audio/camera/skills alive |
| `--no-skills` | off | skip DDS / ComboController; tool calls for motion fail cleanly |
| `--no-wakeword` | off | bypass wake-word gate; mic streams continuously to Realtime |
| `-v / --verbose` | off | DEBUG logging |

---

## Troubleshooting

- **`ModuleNotFoundError: openai` or `sounddevice`** — `pip install -r requirements.txt` inside the `agi` env.
- **`OSError: PortAudioError ... device unavailable`** — your WSL/Linux audio stack isn't exposing a default mic/speaker. Set `audio.input_device` / `audio.output_device` in `va_demo.yaml` to a numeric device index from `python -c "import sounddevice as sd; print(sd.query_devices())"`.
- **`[combo] waiting for first /rt/lowstate ...` hangs** — the MuJoCo sim isn't running, or it's running on a different DDS domain / interface than `va_demo.yaml::robot`.
- **`no frame received`** — TeleImager image server isn't running, or it's bound to a different host. Check `cam_config_server.yaml::head_camera::zmq_port`.
- **`OpenAI API error: model not found`** — your account doesn't have access to the configured model. Override with `OPENAI_VISION_MODEL` / `OPENAI_REALTIME_MODEL` / `OPENAI_TTS_MODEL`.
- **Robot collapses on big arm gesture** — the `ARM_GESTURE_K=2.0` envelope in `g1_sim_rl_combo.py` is the structural safety net; if you've widened it, narrow it back. See the long comment at the top of that file.

---

## Out of scope (handled in later phases per `docs/vlm_audio_mock_deep.md`)

- Real-robot SDK2 backend (sim only here)
- Local YOLO / depth perception
- LeRobot / GMR motion retargeting
- Behavior tree / scene graph memory
- Multi-frame video understanding
