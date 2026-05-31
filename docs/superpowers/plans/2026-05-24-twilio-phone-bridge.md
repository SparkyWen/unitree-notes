# Twilio Phone Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a phone-call path to the G1 voice loop. Operator dials in (or is dialled out to), speaks to OpenAI Realtime, and the model issues tool calls that flow through the **existing** `SafetySupervisor` + `vision_risk_gate` + `SkillServer` chain to make the sim robot move.

**Architecture:** New `g1_brain/g1_brain/phone/` package runs in-process inside `agent_main.py` (gated on `--enable-phone`). An aiohttp WS server on `127.0.0.1:8787` accepts Twilio Media Streams, transcodes μ-law/8k ⇄ PCM16/24k, and feeds a `PhoneRealtimeSession` that subclasses the existing `BrainRealtimeAgent` — so 95% of brain wiring (tool dispatch, safety, conversation logging, plan tracking) is inherited. A cross-process voice lease (file + fcntl) ensures the local va-demo mic loop and the phone session don't both try to drive the robot at once.

**Tech Stack:** Python 3.11 (agi conda env), aiohttp (existing), websockets (existing), scipy.signal (resample_poly), audioop (stdlib), `twilio` SDK (new), pydantic (new), pytest + pytest-asyncio (existing). Outbound TLS reverse tunnel handled by autossh + systemd-user (provisioned per `TWILIO_BRIDGE_PUBLIC_ENDPOINT.md`).

**Companion docs:**
- Canonical design: `mcp_twilio_design.md` (root of unitree-notes)
- Approved spec: `docs/superpowers/specs/2026-05-24-twilio-realtime-phone-bridge-design.md`
- VPS provisioning manual: pasted in conversation 2026-05-24; covers tunnel-side setup
- Public host: `twilio.openproduct.cn` (resolves to VPS 15.204.242.207); SSH user `sparkytun`

**Working tree:** `/home/helios/unitree/unitree-notes` on branch `feature/mcp-twilio`.

**Conda env:** `agi` (activate with `conda activate agi`). All commands assume this env.

---

## Phase 0 — Dependencies & scaffolding

### Task 0.1: Add required Python deps

**Files:**
- Modify: `g1_brain/pyproject.toml` (`dependencies` array)
- Modify: `g1_brain/requirements.txt` (comment lists deps for humans; pyproject is source of truth)

- [ ] **Step 1: Inspect current deps**

```bash
grep -E '"twilio|scipy|pydantic|aiohttp"' /home/helios/unitree/unitree-notes/g1_brain/pyproject.toml || echo "missing"
```

Expected: `missing` (we add all three; aiohttp is transitive but list it explicitly).

- [ ] **Step 2: Add to pyproject.toml**

Edit `g1_brain/pyproject.toml`, inside the `dependencies = [...]` list, add (alphabetical):

```toml
  "aiohttp>=3.9",
  "pydantic>=2.0",
  "scipy>=1.11",
  "twilio>=9.0",
```

- [ ] **Step 3: Install into agi env**

```bash
conda activate agi && cd ~/unitree/unitree-notes/g1_brain && pip install -e .
```

Expected: `Successfully installed twilio-... pydantic-... scipy-...` (aiohttp likely already present).

- [ ] **Step 4: Smoke-import**

```bash
python -c "import twilio, pydantic, scipy.signal, aiohttp; print('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
cd ~/unitree/unitree-notes && git add g1_brain/pyproject.toml && \
  git commit -m "deps(g1_brain/phone): add twilio + pydantic + scipy + aiohttp pin

For the Twilio phone bridge.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 0.2: Create empty phone package skeleton

**Files:**
- Create: `g1_brain/g1_brain/phone/__init__.py`
- Create: `g1_brain/tests/phone/__init__.py`
- Create: `g1_brain/tests/phone/conftest.py`

- [ ] **Step 1: Create directories + empty init files**

```bash
mkdir -p ~/unitree/unitree-notes/g1_brain/g1_brain/phone
mkdir -p ~/unitree/unitree-notes/g1_brain/tests/phone
touch ~/unitree/unitree-notes/g1_brain/g1_brain/phone/__init__.py
touch ~/unitree/unitree-notes/g1_brain/tests/phone/__init__.py
```

- [ ] **Step 2: Create test conftest with a shared tmp-env fixture**

Write `g1_brain/tests/phone/conftest.py`:

```python
"""Shared fixtures for phone bridge tests.

Phone tests must NEVER hit the real Twilio API or OpenAI Realtime —
they use mocks throughout. This conftest provides a fixture that
populates required env vars with safe dummy values.
"""
from __future__ import annotations

import os

import pytest


@pytest.fixture
def phone_env(monkeypatch):
    """Set every env var TwilioConfig + PhoneConfig require to a dummy."""
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "0" * 32)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "dummy-auth-token")
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SK" + "0" * 32)
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "dummy-api-secret")
    monkeypatch.setenv("TWILIO_FROM_NUMBER", "+14155550100")
    monkeypatch.setenv("PUBLIC_BRIDGE_URL", "wss://example.invalid/twilio")
    monkeypatch.setenv("PHONE_ALLOWED_CALLERS", "+14155550199")
    yield
```

- [ ] **Step 3: Verify pytest discovers**

```bash
cd ~/unitree/unitree-notes/g1_brain && pytest tests/phone/ -v 2>&1 | tail
```

Expected: `no tests ran in ... s` (no tests yet, but pytest finds the dir).

- [ ] **Step 4: Commit**

```bash
git add g1_brain/g1_brain/phone/__init__.py g1_brain/tests/phone/
git commit -m "feat(g1_brain/phone): empty package skeleton + test conftest

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 1 — Pure-Python foundation

### Task 1: phone/config.py (env-loaded Pydantic config)

**Files:**
- Create: `g1_brain/g1_brain/phone/config.py`
- Create: `g1_brain/tests/phone/test_config.py`

- [ ] **Step 1: Write failing test**

`g1_brain/tests/phone/test_config.py`:

```python
"""Tests for phone.config — env loading + validation."""
from __future__ import annotations

import pytest

from g1_brain.phone.config import (
    PhoneConfig,
    TwilioConfig,
    load_from_env,
    PhoneConfigError,
)


def test_load_from_env_with_all_required(phone_env):
    twilio_cfg, phone_cfg = load_from_env()
    assert twilio_cfg.account_sid.startswith("AC")
    assert twilio_cfg.from_number == "+14155550100"
    assert twilio_cfg.auth_token.get_secret_value() == "dummy-auth-token"
    assert phone_cfg.public_bridge_url == "wss://example.invalid/twilio"
    assert phone_cfg.allowed_callers == ["+14155550199"]


def test_load_from_env_missing_required_raises(monkeypatch):
    # No env vars at all
    for k in (
        "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_API_KEY_SID",
        "TWILIO_API_KEY_SECRET", "TWILIO_FROM_NUMBER",
        "PUBLIC_BRIDGE_URL", "PHONE_ALLOWED_CALLERS",
    ):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(PhoneConfigError) as exc:
        load_from_env()
    assert "TWILIO_ACCOUNT_SID" in str(exc.value)


def test_allowed_callers_parses_comma_list(phone_env, monkeypatch):
    monkeypatch.setenv("PHONE_ALLOWED_CALLERS", "+1234,+5678 , +9999")
    _, phone_cfg = load_from_env()
    assert phone_cfg.allowed_callers == ["+1234", "+5678", "+9999"]


def test_public_bridge_url_rejects_non_wss(phone_env, monkeypatch):
    monkeypatch.setenv("PUBLIC_BRIDGE_URL", "http://example/twilio")
    with pytest.raises(PhoneConfigError):
        load_from_env()


def test_phone_config_defaults(phone_env):
    _, phone_cfg = load_from_env()
    assert phone_cfg.bind_host == "127.0.0.1"   # important — tunnel-only
    assert phone_cfg.bind_port == 8787
    assert phone_cfg.call_idle_timeout_s == 30.0
    assert phone_cfg.tool_timeout_s == 5.0
    assert phone_cfg.realtime_model == "gpt-realtime"
    assert phone_cfg.realtime_voice == "alloy"
```

- [ ] **Step 2: Run test, expect ImportError**

```bash
cd ~/unitree/unitree-notes/g1_brain && pytest tests/phone/test_config.py -v 2>&1 | tail
```

Expected: collection error / `ModuleNotFoundError: No module named 'g1_brain.phone.config'`.

- [ ] **Step 3: Write implementation**

`g1_brain/g1_brain/phone/config.py`:

```python
"""Pydantic-validated config for the Twilio phone bridge.

Source of truth for Twilio credentials, public bridge URL, allowed-caller
whitelist. Failure mode is loud: missing env vars → PhoneConfigError at
boot (not at first call).
"""
from __future__ import annotations

import os
from typing import List, Tuple

from pydantic import BaseModel, Field, SecretStr, field_validator


class PhoneConfigError(RuntimeError):
    """Raised when phone bridge config is incomplete or invalid."""


class TwilioConfig(BaseModel):
    account_sid: str = Field(..., min_length=2)
    auth_token: SecretStr
    api_key_sid: str = Field(..., min_length=2)
    api_key_secret: SecretStr
    from_number: str = Field(..., pattern=r"^\+\d{8,15}$")


class PhoneConfig(BaseModel):
    public_bridge_url: str
    allowed_callers: List[str]
    bind_host: str = "127.0.0.1"
    bind_port: int = 8787
    call_idle_timeout_s: float = 30.0
    tool_timeout_s: float = 5.0
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "alloy"
    greeting: str = "Hi, this is Sparky. What would you like me to do?"

    @field_validator("public_bridge_url")
    @classmethod
    def _wss_only(cls, v: str) -> str:
        if not v.startswith("wss://"):
            raise ValueError("public_bridge_url must be wss://...")
        return v

    @field_validator("allowed_callers")
    @classmethod
    def _non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("allowed_callers must be non-empty")
        for entry in v:
            if not entry.startswith("+"):
                raise ValueError(f"allowed_callers entries must be E.164 (+...): {entry}")
        return v


_REQUIRED = [
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_API_KEY_SID",
    "TWILIO_API_KEY_SECRET",
    "TWILIO_FROM_NUMBER",
    "PUBLIC_BRIDGE_URL",
    "PHONE_ALLOWED_CALLERS",
]


def load_from_env() -> Tuple[TwilioConfig, PhoneConfig]:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise PhoneConfigError(f"missing env vars: {', '.join(missing)}")

    callers = [
        c.strip()
        for c in os.environ["PHONE_ALLOWED_CALLERS"].split(",")
        if c.strip()
    ]

    try:
        twilio_cfg = TwilioConfig(
            account_sid=os.environ["TWILIO_ACCOUNT_SID"],
            auth_token=os.environ["TWILIO_AUTH_TOKEN"],
            api_key_sid=os.environ["TWILIO_API_KEY_SID"],
            api_key_secret=os.environ["TWILIO_API_KEY_SECRET"],
            from_number=os.environ["TWILIO_FROM_NUMBER"],
        )
        phone_cfg = PhoneConfig(
            public_bridge_url=os.environ["PUBLIC_BRIDGE_URL"],
            allowed_callers=callers,
        )
    except Exception as e:
        raise PhoneConfigError(str(e)) from e

    return twilio_cfg, phone_cfg
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pytest tests/phone/test_config.py -v 2>&1 | tail
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/config.py g1_brain/tests/phone/test_config.py
git commit -m "feat(g1_brain/phone): config — env-loaded TwilioConfig + PhoneConfig

Fail-closed at boot if any required env var missing. bind_host defaults
to 127.0.0.1 because the public path is via reverse tunnel only.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: phone/audio_codec.py (μ-law ↔ PCM resampling)

**Files:**
- Create: `g1_brain/g1_brain/phone/audio_codec.py`
- Create: `g1_brain/tests/phone/test_audio_codec.py`

- [ ] **Step 1: Write failing tests**

`g1_brain/tests/phone/test_audio_codec.py`:

```python
"""Tests for phone.audio_codec — μ-law/8k ⇄ PCM16/24k transcoding."""
from __future__ import annotations

import base64
import math

import numpy as np
import pytest

from g1_brain.phone.audio_codec import (
    mulaw8k_to_pcm24k,
    pcm24k_to_mulaw8k,
    StreamingResampler,
)


def _sine_pcm16(freq_hz: float, sample_rate: int, duration_s: float) -> bytes:
    n = int(sample_rate * duration_s)
    t = np.arange(n) / sample_rate
    sig = (0.5 * np.sin(2 * math.pi * freq_hz * t) * 32767).astype(np.int16)
    return sig.tobytes()


def _frame_sizes_in_per_20ms_mulaw() -> int:
    # μ-law 8k mono: 8000 samples/s × 1 byte × 0.020 s = 160 B
    return 160


def _frame_sizes_pcm24k_per_20ms_bytes() -> int:
    # PCM16 24k mono: 24000 × 2 × 0.020 = 960 B
    return 960


def test_mulaw8k_to_pcm24k_frame_size():
    # 160 B μ-law → 960 B PCM16-24k per 20 ms
    fake_payload = base64.b64encode(b"\x7f" * 160).decode()
    out = mulaw8k_to_pcm24k(fake_payload)
    assert len(out) == _frame_sizes_pcm24k_per_20ms_bytes()


def test_pcm24k_to_mulaw8k_frame_size():
    # 960 B PCM → 160 B μ-law per 20 ms
    pcm = _sine_pcm16(1000.0, 24000, 0.020)
    assert len(pcm) == 960
    out_b64 = pcm24k_to_mulaw8k(pcm)
    out = base64.b64decode(out_b64)
    assert len(out) == 160


def test_round_trip_1khz_sine_low_distortion():
    """1 kHz sine pcm24k → μlaw8k → pcm24k preserves the tone."""
    pcm_in = _sine_pcm16(1000.0, 24000, 0.5)  # 500 ms
    mu_b64 = pcm24k_to_mulaw8k(pcm_in)
    pcm_out = mulaw8k_to_pcm24k(mu_b64)

    in_arr = np.frombuffer(pcm_in, dtype=np.int16).astype(np.float64)
    out_arr = np.frombuffer(pcm_out, dtype=np.int16).astype(np.float64)

    # Crop to equal length (resampling may emit a sample off at the tails)
    n = min(len(in_arr), len(out_arr))
    in_arr, out_arr = in_arr[:n], out_arr[:n]

    # Energy retained within an order of magnitude
    e_in = float(np.mean(in_arr ** 2))
    e_out = float(np.mean(out_arr ** 2))
    assert e_out > 0.1 * e_in   # μ-law SNR ~38 dB; resampling loses a touch


def test_streaming_resampler_pcm24k_partial_frames():
    """StreamingResampler must hold residual when input < whole frame."""
    rs = StreamingResampler()
    # feed half a 20 ms frame at 24k = 480 B
    pcm_half = b"\x00" * 480
    frames = list(rs.feed_pcm24k(pcm_half))
    # Whole frames out should be 0; resampler retains residual
    total_mulaw = sum(len(base64.b64decode(f)) for f in frames)
    assert total_mulaw < 160   # less than one whole 20 ms μ-law frame
    # Feed the other half — total should now be >= one full frame
    frames2 = list(rs.feed_pcm24k(pcm_half))
    total_mulaw += sum(len(base64.b64decode(f)) for f in frames2)
    assert total_mulaw >= 160


def test_streaming_resampler_pcm24k_big_chunk():
    """Big chunk → many whole μ-law frames, residual <160 B."""
    rs = StreamingResampler()
    # 250 ms PCM at 24k = 12 000 B
    pcm = _sine_pcm16(440.0, 24000, 0.250)
    frames = list(rs.feed_pcm24k(pcm))
    total_mulaw = sum(len(base64.b64decode(f)) for f in frames)
    # ~250 ms / 20 ms = 12.5 frames; expect 12 whole emitted, half buffered
    assert 11 * 160 <= total_mulaw <= 13 * 160


def test_streaming_resampler_mulaw_inbound():
    """Inbound side: feed 20 ms μ-law, get 960 B PCM24k out."""
    rs = StreamingResampler()
    mu_b64 = base64.b64encode(b"\x7f" * 160).decode()
    chunks = list(rs.feed_mulaw8k(mu_b64))
    total = sum(len(c) for c in chunks)
    assert total == 960
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/phone/test_audio_codec.py -v 2>&1 | tail
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/audio_codec.py`:

```python
"""Audio codec bridge between Twilio Media Streams and OpenAI Realtime.

Twilio side:  G.711 μ-law, 8 kHz, mono, 160 B per 20 ms frame, base64-encoded
              inside `media` events.
OpenAI side:  PCM16 LE, 24 kHz, mono, base64 inside input_audio_buffer.append
              and response.output_audio.delta events.

Resampling uses scipy.signal.resample_poly (up=3, down=1 or up=1, down=3 —
integer ratios both ways).

`StreamingResampler` is a stateful wrapper that buffers residual samples
across calls, so we can hand it OpenAI's arbitrarily-chunked output deltas
and get whole-frame μ-law back to feed Twilio.
"""
from __future__ import annotations

import audioop
import base64
from typing import Iterator

import numpy as np
from scipy.signal import resample_poly


_MULAW_FRAME_BYTES = 160          # 8000 Hz × 1 byte × 20 ms
_PCM24K_FRAME_BYTES = 960         # 24000 Hz × 2 bytes × 20 ms
_PCM8K_FRAME_BYTES = 320          # 8000 Hz × 2 bytes × 20 ms


def mulaw8k_to_pcm24k(payload_b64: str) -> bytes:
    """Decode base64 μ-law 8k → bytes PCM16-LE 24k (3x upsample).

    Input typically 160 B μ-law (20 ms) → 960 B PCM (still 20 ms wall).
    """
    raw_mulaw = base64.b64decode(payload_b64)
    pcm8k = audioop.ulaw2lin(raw_mulaw, 2)          # 2 bytes/sample
    arr8k = np.frombuffer(pcm8k, dtype=np.int16)
    arr24k = resample_poly(arr8k, up=3, down=1).astype(np.int16)
    return arr24k.tobytes()


def pcm24k_to_mulaw8k(pcm: bytes) -> str:
    """Encode bytes PCM16-LE 24k → base64 μ-law 8k (3x downsample).

    pcm must be a whole number of int16 samples (even length).
    Caller's responsibility to chunk for 20 ms framing; this is stateless.
    """
    arr24k = np.frombuffer(pcm, dtype=np.int16)
    arr8k = resample_poly(arr24k, up=1, down=3).astype(np.int16)
    pcm8k = arr8k.tobytes()
    raw_mulaw = audioop.lin2ulaw(pcm8k, 2)
    return base64.b64encode(raw_mulaw).decode("ascii")


class StreamingResampler:
    """Stateful bidirectional resampler that retains < 1 frame of residual.

    Use one instance per call (it holds per-direction byte buffers).

    Outbound side (PCM24k → μ-law/8k):
      feed_pcm24k(pcm) yields zero or more base64 μ-law strings, each
      exactly 160 B (20 ms). Residual samples (< 960 B) are held until the
      next call. Useful because OpenAI deltas are arbitrarily sized.

    Inbound side (μ-law/8k → PCM24k):
      feed_mulaw8k(payload_b64) yields zero or more bytes chunks; in
      practice each Twilio `media` event is exactly one 20 ms frame, so
      each call yields exactly one 960 B chunk. Symmetric for safety.
    """

    def __init__(self) -> None:
        self._pcm_buf = bytearray()
        self._mulaw_buf = bytearray()

    # ---- outbound (us → Twilio) -----------------------------------------

    def feed_pcm24k(self, pcm: bytes) -> Iterator[str]:
        self._pcm_buf.extend(pcm)
        while len(self._pcm_buf) >= _PCM24K_FRAME_BYTES:
            chunk = bytes(self._pcm_buf[:_PCM24K_FRAME_BYTES])
            del self._pcm_buf[:_PCM24K_FRAME_BYTES]
            yield pcm24k_to_mulaw8k(chunk)

    # ---- inbound (Twilio → us) ------------------------------------------

    def feed_mulaw8k(self, payload_b64: str) -> Iterator[bytes]:
        raw = base64.b64decode(payload_b64)
        self._mulaw_buf.extend(raw)
        while len(self._mulaw_buf) >= _MULAW_FRAME_BYTES:
            frame = bytes(self._mulaw_buf[:_MULAW_FRAME_BYTES])
            del self._mulaw_buf[:_MULAW_FRAME_BYTES]
            yield mulaw8k_to_pcm24k(base64.b64encode(frame).decode("ascii"))

    # ---- maintenance ----------------------------------------------------

    def reset(self) -> None:
        self._pcm_buf.clear()
        self._mulaw_buf.clear()
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_audio_codec.py -v 2>&1 | tail
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/audio_codec.py g1_brain/tests/phone/test_audio_codec.py
git commit -m "feat(g1_brain/phone): audio codec — μ-law/8k ⇄ PCM16/24k

Stateless helpers for single-frame conversion plus StreamingResampler
that holds <1 frame of residual so we can feed it OpenAI's arbitrarily-
sized output deltas and emit whole 20ms μ-law frames to Twilio.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: phone/voice_lease.py (cross-process mutex)

**Files:**
- Create: `g1_brain/g1_brain/phone/voice_lease.py`
- Create: `g1_brain/tests/phone/test_voice_lease.py`

- [ ] **Step 1: Failing tests**

`g1_brain/tests/phone/test_voice_lease.py`:

```python
"""Tests for phone.voice_lease — cross-process LOCAL_MIC | PHONE mutex."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from g1_brain.phone.voice_lease import VoiceLeaseManager, LeaseHolder


@pytest.fixture
def lease_path(tmp_path) -> Path:
    return tmp_path / "voice_lease.json"


def test_initial_state_is_local_mic(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    holder = mgr.current_holder()
    assert holder is None or holder.name == LeaseHolder.LOCAL_MIC


def test_acquire_phone_succeeds_when_idle(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True
    h = mgr.current_holder()
    assert h.name == LeaseHolder.PHONE
    assert h.owner == "call-1"


def test_acquire_phone_fails_when_phone_already_held_by_other(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    # second process, same lease file
    mgr2 = VoiceLeaseManager(lease_path)
    assert mgr2.acquire(LeaseHolder.PHONE, owner="call-2") is False


def test_acquire_phone_idempotent_for_same_owner(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True
    assert mgr.acquire(LeaseHolder.PHONE, owner="call-1") is True


def test_release_only_by_owner(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    # foreign release: no-op
    mgr.release(LeaseHolder.PHONE, owner="someone-else")
    assert mgr.current_holder().name == LeaseHolder.PHONE
    # legitimate release
    mgr.release(LeaseHolder.PHONE, owner="call-1")
    holder = mgr.current_holder()
    assert holder is None or holder.name == LeaseHolder.LOCAL_MIC


def test_stale_lease_is_reclaimable(lease_path):
    mgr = VoiceLeaseManager(lease_path, stale_after_s=0.0)
    mgr.acquire(LeaseHolder.PHONE, owner="dead-call")
    time.sleep(0.01)
    mgr2 = VoiceLeaseManager(lease_path, stale_after_s=0.0)
    assert mgr2.acquire(LeaseHolder.PHONE, owner="new-call") is True


def test_acquire_local_mic_after_phone_release(lease_path):
    mgr = VoiceLeaseManager(lease_path)
    mgr.acquire(LeaseHolder.PHONE, owner="call-1")
    mgr.release(LeaseHolder.PHONE, owner="call-1")
    assert mgr.acquire(LeaseHolder.LOCAL_MIC, owner="va-demo-1") is True
    assert mgr.current_holder().name == LeaseHolder.LOCAL_MIC
```

- [ ] **Step 2: Run, expect ImportError**

```bash
pytest tests/phone/test_voice_lease.py -v 2>&1 | tail
```

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/voice_lease.py`:

```python
"""Cross-process voice lease.

Two named slots — LOCAL_MIC and PHONE — protected by an fcntl.flock'd
JSON file at /tmp/g1_brain_voice_lease (default). Both the long-running
g1_brain process and any va-demo process can read/write safely.

Why a file: cheapest correct cross-process mutex with no extra service.
fcntl.flock is advisory but every process that touches the file uses
this class, so it's effectively mandatory in practice.

Default file path: /tmp/g1_brain_voice_lease (overridable for tests).
"""
from __future__ import annotations

import enum
import fcntl
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEFAULT_LEASE_PATH = Path("/tmp/g1_brain_voice_lease")


class LeaseHolder(str, enum.Enum):
    LOCAL_MIC = "LOCAL_MIC"
    PHONE = "PHONE"


@dataclass(frozen=True)
class LeaseRecord:
    name: LeaseHolder
    owner: str
    since: float

    def as_dict(self) -> dict:
        return {"holder": self.name.value, "owner": self.owner, "since": self.since}

    @classmethod
    def from_dict(cls, d: dict) -> "LeaseRecord":
        return cls(
            name=LeaseHolder(d["holder"]),
            owner=str(d["owner"]),
            since=float(d["since"]),
        )


class VoiceLeaseManager:
    """Atomic acquire/release of {LOCAL_MIC | PHONE} backed by a lock file."""

    def __init__(
        self,
        path: Path = DEFAULT_LEASE_PATH,
        stale_after_s: float = 3600.0,
    ) -> None:
        self._path = Path(path)
        self._stale_after_s = stale_after_s
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def acquire(self, name: LeaseHolder, owner: str) -> bool:
        with self._locked() as f:
            existing = self._read(f)
            if existing is None:
                self._write(f, LeaseRecord(name=name, owner=owner, since=time.time()))
                return True
            if existing.name == name and existing.owner == owner:
                return True
            # different holder OR different owner of same slot:
            # only steal if stale
            if time.time() - existing.since > self._stale_after_s:
                self._write(f, LeaseRecord(name=name, owner=owner, since=time.time()))
                return True
            # If we're trying to acquire the OTHER slot, that's allowed
            # (the slots represent who's transmitting; LOCAL_MIC can claim
            # while PHONE is held only if PHONE is stale, which we just
            # checked above). Reject.
            return False

    def release(self, name: LeaseHolder, owner: str) -> None:
        with self._locked() as f:
            existing = self._read(f)
            if existing is None:
                return
            if existing.name != name or existing.owner != owner:
                return  # someone else owns it; do nothing
            self._erase(f)

    def current_holder(self) -> Optional[LeaseRecord]:
        with self._locked() as f:
            return self._read(f)

    # ---- internals ------------------------------------------------------

    def _locked(self):
        return _LockedFile(self._path)

    @staticmethod
    def _read(f) -> Optional[LeaseRecord]:
        f.seek(0)
        raw = f.read()
        if not raw.strip():
            return None
        try:
            return LeaseRecord.from_dict(json.loads(raw))
        except Exception:
            return None

    @staticmethod
    def _write(f, rec: LeaseRecord) -> None:
        f.seek(0)
        f.truncate()
        f.write(json.dumps(rec.as_dict()))
        f.flush()
        os.fsync(f.fileno())

    @staticmethod
    def _erase(f) -> None:
        f.seek(0)
        f.truncate()
        f.flush()
        os.fsync(f.fileno())


class _LockedFile:
    """Context manager: open lease file r+ with exclusive flock."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._f = None

    def __enter__(self):
        # open r+, creating if needed
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT, 0o644)
        self._f = os.fdopen(fd, "r+")
        fcntl.flock(self._f.fileno(), fcntl.LOCK_EX)
        return self._f

    def __exit__(self, exc_type, exc, tb):
        try:
            fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        finally:
            self._f.close()
            self._f = None
```

- [ ] **Step 4: Run, expect PASS**

```bash
pytest tests/phone/test_voice_lease.py -v 2>&1 | tail
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/voice_lease.py g1_brain/tests/phone/test_voice_lease.py
git commit -m "feat(g1_brain/phone): voice_lease — cross-process LOCAL_MIC|PHONE mutex

File-backed (fcntl.flock'd JSON). Cheapest correct mutex between the
long-running g1_brain and any va-demo process without adding a service.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: phone/tunnel_health.py (Twilio HMAC + /healthz)

**Files:**
- Create: `g1_brain/g1_brain/phone/tunnel_health.py`
- Create: `g1_brain/tests/phone/test_tunnel_health.py`

- [ ] **Step 1: Failing tests**

`g1_brain/tests/phone/test_tunnel_health.py`:

```python
"""Tests for phone.tunnel_health — Twilio HMAC + healthz payload."""
from __future__ import annotations

import base64
import hashlib
import hmac

import pytest

from g1_brain.phone.tunnel_health import validate_twilio_signature, build_healthz_payload


# Reference vector: build a signature locally then verify it round-trips.
# Twilio's algorithm: signature = b64(HMAC-SHA1(URL + sorted(k+v) for k,v in params, key=AuthToken))


def _make_sig(url: str, params: dict[str, str], auth_token: str) -> str:
    data = url
    for k in sorted(params):
        data += k + params[k]
    mac = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(mac).decode()


def test_signature_round_trip_with_params():
    url = "https://example.com/twilio"
    params = {"From": "+1234", "To": "+5678", "CallSid": "CA00"}
    token = "test-token"
    sig = _make_sig(url, params, token)
    assert validate_twilio_signature(url, params, sig, token)


def test_signature_with_empty_params():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "tok")
    assert validate_twilio_signature(url, {}, sig, "tok")


def test_signature_rejects_tampered_url():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "tok")
    assert not validate_twilio_signature(url + "/x", {}, sig, "tok")


def test_signature_rejects_tampered_param():
    url = "https://example.com/twilio"
    params = {"From": "+1234"}
    sig = _make_sig(url, params, "tok")
    assert not validate_twilio_signature(url, {"From": "+9999"}, sig, "tok")


def test_signature_rejects_wrong_token():
    url = "https://example.com/twilio"
    sig = _make_sig(url, {}, "right-token")
    assert not validate_twilio_signature(url, {}, sig, "wrong-token")


def test_healthz_payload_shape():
    p = build_healthz_payload(version="1.0", calls_active=2)
    assert p["ok"] is True
    assert p["calls_active"] == 2
    assert p["version"] == "1.0"
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/tunnel_health.py`:

```python
"""Twilio signature validation + /healthz payload helpers.

Reference: https://www.twilio.com/docs/usage/security#validating-requests
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from typing import Mapping


def validate_twilio_signature(
    full_url: str,
    post_params: Mapping[str, str],
    header_signature: str,
    auth_token: str,
) -> bool:
    """Constant-time-compare an X-Twilio-Signature header.

    Algorithm: signed_string = URL + concat(sorted(key + value)) for params;
    HMAC-SHA1(signed_string, auth_token); base64 encode; compare.
    """
    data = full_url
    for k in sorted(post_params):
        data += k + post_params[k]
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, header_signature)


def build_healthz_payload(*, version: str, calls_active: int) -> dict:
    """Stable JSON shape for the /healthz route."""
    return {
        "ok": True,
        "version": version,
        "calls_active": calls_active,
    }
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_tunnel_health.py -v 2>&1 | tail
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/tunnel_health.py g1_brain/tests/phone/test_tunnel_health.py
git commit -m "feat(g1_brain/phone): tunnel_health — Twilio signature + /healthz

HMAC-SHA1 over URL + sorted(k+v) params, constant-time compare.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — Twilio surface

### Task 5: phone/twilio_dialer.py (REST dial + TwiML + hangup + dry_run)

**Files:**
- Create: `g1_brain/g1_brain/phone/twilio_dialer.py`
- Create: `g1_brain/tests/phone/test_twilio_dialer.py`

- [ ] **Step 1: Failing tests**

`g1_brain/tests/phone/test_twilio_dialer.py`:

```python
"""Tests for phone.twilio_dialer — REST + TwiML, all network mocked."""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from g1_brain.phone.config import TwilioConfig
from g1_brain.phone.twilio_dialer import TwilioDialer, TwilioDialError


@pytest.fixture
def cfg():
    return TwilioConfig(
        account_sid="AC" + "0" * 32,
        auth_token="dummy",
        api_key_sid="SK" + "0" * 32,
        api_key_secret="secret",
        from_number="+14155550100",
    )


def test_build_twiml_includes_url_and_parameter(cfg):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    xml = d.build_twiml(brain_session_id="abc-123")
    assert "<Connect>" in xml
    assert '<Stream url="wss://h/twilio">' in xml
    assert '<Parameter name="brain_session_id" value="abc-123"/>' in xml


@pytest.mark.asyncio
async def test_dial_posts_to_calls_endpoint(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 201
    fake_resp.json = AsyncMock(return_value={"sid": "CA" + "1" * 32})

    captured = {}

    class _Ctx:
        async def __aenter__(self):
            return fake_resp
        async def __aexit__(self, *a):
            return False

    def fake_post(url, *, data, auth, **kwargs):
        captured["url"] = url
        captured["data"] = data
        captured["auth"] = auth
        return _Ctx()

    fake_session = MagicMock()
    fake_session.post = fake_post
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    sid = await d.dial("+14155550199")
    assert sid.startswith("CA")
    assert "Accounts/AC" in captured["url"]
    assert "Calls.json" in captured["url"]
    assert captured["data"]["To"] == "+14155550199"
    assert captured["data"]["From"] == "+14155550100"
    assert "<Stream url=" in captured["data"]["Twiml"]
    assert captured["auth"].login == cfg.api_key_sid
    assert captured["auth"].password == cfg.api_key_secret.get_secret_value()


@pytest.mark.asyncio
async def test_dial_raises_on_4xx(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 400
    fake_resp.text = AsyncMock(return_value="bad number")

    class _Ctx:
        async def __aenter__(self): return fake_resp
        async def __aexit__(self, *a): return False

    fake_session = MagicMock()
    fake_session.post = lambda *a, **k: _Ctx()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    with pytest.raises(TwilioDialError):
        await d.dial("+14155550199")


@pytest.mark.asyncio
async def test_dry_run_hits_accounts_endpoint(cfg, monkeypatch):
    d = TwilioDialer(cfg, public_bridge_url="wss://h/twilio")
    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.json = AsyncMock(return_value={"friendly_name": "test-account"})

    captured = {}
    class _Ctx:
        async def __aenter__(self): return fake_resp
        async def __aexit__(self, *a): return False
    def fake_get(url, *, auth, **kwargs):
        captured["url"] = url
        return _Ctx()
    fake_session = MagicMock()
    fake_session.get = fake_get
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("aiohttp.ClientSession", lambda *a, **k: fake_session)

    name = await d.dry_run()
    assert name == "test-account"
    assert captured["url"].endswith(f"Accounts/{cfg.account_sid}.json")
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/twilio_dialer.py`:

```python
"""Twilio REST + TwiML helpers for outbound dial.

We use the REST API directly via aiohttp rather than the synchronous
`twilio` SDK so we stay inside the asyncio loop. The official SDK is
used only for type names (not strictly required).
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

import aiohttp

from .config import TwilioConfig


log = logging.getLogger(__name__)


class TwilioDialError(RuntimeError):
    pass


_API_BASE = "https://api.twilio.com/2010-04-01"


class TwilioDialer:
    def __init__(self, cfg: TwilioConfig, public_bridge_url: str) -> None:
        self._cfg = cfg
        self._public_bridge_url = public_bridge_url

    def build_twiml(self, brain_session_id: str) -> str:
        # Note: <Stream> URL is inserted verbatim; caller must ensure it
        # has no XML-special chars (a wss:// URL never does).
        return (
            "<Response>"
            "<Connect>"
            f'<Stream url="{self._public_bridge_url}">'
            f'<Parameter name="brain_session_id" value="{brain_session_id}"/>'
            "</Stream>"
            "</Connect>"
            "</Response>"
        )

    async def dial(
        self, to: str, brain_session_id: Optional[str] = None
    ) -> str:
        """POST /Accounts/{sid}/Calls.json. Returns CallSid on success."""
        bsid = brain_session_id or str(uuid.uuid4())
        twiml = self.build_twiml(bsid)
        url = f"{_API_BASE}/Accounts/{self._cfg.account_sid}/Calls.json"
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        data = {
            "To": to,
            "From": self._cfg.from_number,
            "Twiml": twiml,
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise TwilioDialError(
                        f"dial({to}) failed {resp.status}: {text}"
                    )
                body = await resp.json()
                sid = body.get("sid")
                if not sid:
                    raise TwilioDialError(f"no sid in response: {body}")
                log.info("twilio.dial ok to=%s sid=%s", to, sid)
                return sid

    async def hangup(self, call_sid: str) -> None:
        """POST /Calls/{sid}.json Status=completed."""
        url = (
            f"{_API_BASE}/Accounts/{self._cfg.account_sid}"
            f"/Calls/{call_sid}.json"
        )
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={"Status": "completed"}, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    log.warning("twilio.hangup(%s) %s: %s", call_sid, resp.status, text)

    async def dry_run(self) -> str:
        """GET /Accounts/{sid}.json. Returns the account's friendly_name."""
        url = f"{_API_BASE}/Accounts/{self._cfg.account_sid}.json"
        auth = aiohttp.BasicAuth(
            self._cfg.api_key_sid, self._cfg.api_key_secret.get_secret_value()
        )
        async with aiohttp.ClientSession() as session:
            async with session.get(url, auth=auth) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise TwilioDialError(
                        f"dry_run failed {resp.status}: {text}"
                    )
                body = await resp.json()
                return str(body.get("friendly_name", "(unknown)"))
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_twilio_dialer.py -v 2>&1 | tail
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/twilio_dialer.py g1_brain/tests/phone/test_twilio_dialer.py
git commit -m "feat(g1_brain/phone): twilio_dialer — dial / hangup / dry_run + TwiML

Direct REST via aiohttp (stays in asyncio loop). API Key SID/Secret
for auth (rotatable; Auth Token kept only for signature validation).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: phone/twilio_transport.py (Media Streams WS adapter)

**Files:**
- Create: `g1_brain/g1_brain/phone/twilio_transport.py`
- Create: `g1_brain/tests/phone/test_twilio_transport.py`

- [ ] **Step 1: Failing tests**

`g1_brain/tests/phone/test_twilio_transport.py`:

```python
"""Tests for phone.twilio_transport — Twilio Media Streams protocol adapter.

We don't run a real Twilio. We pretend to be Twilio by feeding the
transport synthesized events through a FakeWS.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from g1_brain.phone.twilio_transport import (
    TwilioMediaStreamTransport,
    StartEvent,
)


class FakeWS:
    """Mimics the slice of aiohttp.WebSocketResponse the transport uses."""
    def __init__(self, inbound: list[str]):
        self._inbound = list(inbound)
        self.outbound: list[str] = []
        self.closed = False

    async def receive_json(self):
        if not self._inbound:
            # mimic ws.receive() returning a close
            raise asyncio.CancelledError()
        return json.loads(self._inbound.pop(0))

    async def send_str(self, s: str):
        self.outbound.append(s)

    async def close(self):
        self.closed = True


def _media_event(stream_sid: str, payload_b64: str) -> str:
    return json.dumps({
        "event": "media",
        "media": {"track": "inbound", "payload": payload_b64},
        "streamSid": stream_sid,
    })


@pytest.mark.asyncio
async def test_start_returns_parsed_start_event():
    start = {
        "event": "start",
        "streamSid": "MZ1",
        "start": {
            "streamSid": "MZ1", "callSid": "CA1",
            "tracks": ["inbound"],
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
            "customParameters": {"brain_session_id": "bsid-1"},
        },
    }
    inbound_event = {
        "event": "start", "start": start["start"], "streamSid": "MZ1",
    }
    # Twilio always sends "connected" first
    connected = {"event": "connected", "protocol": "Call", "version": "1.0.0"}
    ws = FakeWS([json.dumps(connected), json.dumps(inbound_event)])
    transport = TwilioMediaStreamTransport(ws)
    se = await transport.start()
    assert isinstance(se, StartEvent)
    assert se.stream_sid == "MZ1"
    assert se.call_sid == "CA1"
    assert se.brain_session_id == "bsid-1"
    assert se.from_number is None or se.from_number == ""  # may not be in customParameters


@pytest.mark.asyncio
async def test_iter_inbound_yields_pcm24k_chunks():
    # 160 B μ-law (20 ms) per frame, three frames
    mu = base64.b64encode(b"\x7f" * 160).decode()
    events = [
        json.dumps({"event": "connected"}),
        json.dumps({"event": "start", "streamSid": "MZ1",
                    "start": {"streamSid": "MZ1", "callSid": "CA1",
                              "tracks": ["inbound"],
                              "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
                              "customParameters": {"brain_session_id": "x"}}}),
        _media_event("MZ1", mu),
        _media_event("MZ1", mu),
        _media_event("MZ1", mu),
    ]
    ws = FakeWS(events)
    transport = TwilioMediaStreamTransport(ws)
    await transport.start()

    chunks = []
    async def collect():
        async for chunk in transport.iter_inbound_pcm24k():
            chunks.append(chunk)
    try:
        await asyncio.wait_for(collect(), timeout=0.5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        pass
    # 3 inbound frames × 960 B PCM24k each
    assert sum(len(c) for c in chunks) == 3 * 960


@pytest.mark.asyncio
async def test_send_outbound_pcm24k_emits_media_events():
    ws = FakeWS([])
    transport = TwilioMediaStreamTransport(ws)
    transport._stream_sid = "MZ1"   # bypass start for this test
    # 250 ms PCM24k = 12 000 B → ~12 frames of μ-law (160 B each)
    pcm = b"\x00\x10" * 6000  # 12 000 bytes
    await transport.send_outbound_pcm24k(pcm)
    # outbound events
    assert len(ws.outbound) >= 11
    for s in ws.outbound:
        evt = json.loads(s)
        assert evt["event"] == "media"
        assert evt["streamSid"] == "MZ1"
        assert "payload" in evt["media"]
        assert len(base64.b64decode(evt["media"]["payload"])) == 160


@pytest.mark.asyncio
async def test_clear_outbound_sends_clear_event():
    ws = FakeWS([])
    transport = TwilioMediaStreamTransport(ws)
    transport._stream_sid = "MZ1"
    await transport.clear_outbound()
    assert len(ws.outbound) == 1
    evt = json.loads(ws.outbound[0])
    assert evt == {"event": "clear", "streamSid": "MZ1"}
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/twilio_transport.py`:

```python
"""Twilio Media Streams WebSocket protocol adapter.

Wraps an aiohttp WebSocketResponse and presents:
  - await start() -> StartEvent      (after consuming connected + start)
  - async for chunk in iter_inbound_pcm24k(): ...
  - await send_outbound_pcm24k(pcm)
  - await clear_outbound()
  - await close()

Audio is transcoded through StreamingResampler — Twilio sees μ-law/8k,
the rest of the brain sees PCM16/24k.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from .audio_codec import StreamingResampler


log = logging.getLogger(__name__)


@dataclass
class StartEvent:
    stream_sid: str
    call_sid: str
    brain_session_id: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None


class TwilioMediaStreamTransport:
    """One instance per WS connection / one phone call."""

    def __init__(self, ws) -> None:
        self._ws = ws
        self._stream_sid: Optional[str] = None
        self._inbound_resampler = StreamingResampler()
        self._outbound_resampler = StreamingResampler()
        self._closed = False

    async def start(self) -> StartEvent:
        # The first two events from Twilio are 'connected' then 'start'.
        connected = await self._ws.receive_json()
        if connected.get("event") != "connected":
            raise RuntimeError(f"expected connected, got {connected!r}")
        start = await self._ws.receive_json()
        if start.get("event") != "start":
            raise RuntimeError(f"expected start, got {start!r}")
        s = start["start"]
        self._stream_sid = s["streamSid"]
        custom = s.get("customParameters") or {}
        return StartEvent(
            stream_sid=s["streamSid"],
            call_sid=s["callSid"],
            brain_session_id=custom.get("brain_session_id", ""),
            from_number=custom.get("from") or s.get("from"),
            to_number=custom.get("to") or s.get("to"),
        )

    async def iter_inbound_pcm24k(self) -> AsyncIterator[bytes]:
        """Yield PCM16-24k chunks decoded from Twilio media events.

        Terminates when Twilio sends 'stop' or the WS closes.
        """
        while not self._closed:
            try:
                evt = await self._ws.receive_json()
            except (asyncio.CancelledError, ConnectionResetError):
                return
            t = evt.get("event")
            if t == "media":
                payload = evt.get("media", {}).get("payload", "")
                for chunk in self._inbound_resampler.feed_mulaw8k(payload):
                    yield chunk
            elif t == "stop":
                log.info("twilio.stop received")
                return
            elif t == "mark":
                pass
            else:
                log.debug("twilio.event unknown: %s", t)

    async def send_outbound_pcm24k(self, pcm: bytes) -> None:
        if self._stream_sid is None:
            raise RuntimeError("transport.start() must be awaited first")
        for mu_b64 in self._outbound_resampler.feed_pcm24k(pcm):
            await self._ws.send_str(json.dumps({
                "event": "media",
                "streamSid": self._stream_sid,
                "media": {"payload": mu_b64},
            }))

    async def clear_outbound(self) -> None:
        if self._stream_sid is None:
            return
        await self._ws.send_str(json.dumps({
            "event": "clear",
            "streamSid": self._stream_sid,
        }))
        self._outbound_resampler.reset()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except Exception:
            pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_twilio_transport.py -v 2>&1 | tail
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/twilio_transport.py g1_brain/tests/phone/test_twilio_transport.py
git commit -m "feat(g1_brain/phone): twilio_transport — Media Streams WS adapter

Presents StreamingResampler-backed PCM24k I/O to the rest of the bridge;
Twilio sees raw μ-law/8k events.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — OpenAI Realtime over phone

### Task 7: prompts.py — PHONE_PREAMBLE

**Files:**
- Modify: `g1_brain/g1_brain/brain/prompts.py` (append)

- [ ] **Step 1: Read existing prompts**

```bash
sed -n '1,40p' g1_brain/g1_brain/brain/prompts.py
```

(read for context; we'll APPEND, not modify, to avoid touching production prompts)

- [ ] **Step 2: Append PHONE_PREAMBLE**

Add at end of `g1_brain/g1_brain/brain/prompts.py`:

```python


PHONE_CALL_PREAMBLE = """\
You are Sparky speaking to the operator over a regular phone call.

The operator cannot see the robot or the screen — only hear your voice. Whenever \
you act on a request, briefly describe what you are doing in plain spoken words \
("waving my right hand now"; "walking forward a step"; "stopping"). \

If a tool returns ok=false, speak the reason naturally — do not read JSON. \

If you decide the conversation is over (the operator says goodbye, or the call \
has been silent and they seem to have hung up implicitly), call the end_call tool \
to hang up cleanly.

Keep replies short. Phone audio quality is lower than a laptop microphone — \
prefer one or two sentences over paragraphs.
"""
```

- [ ] **Step 3: Quick smoke test**

```bash
python -c "from g1_brain.brain.prompts import PHONE_CALL_PREAMBLE; assert 'phone call' in PHONE_CALL_PREAMBLE.lower(); print('ok')"
```

Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add g1_brain/g1_brain/brain/prompts.py
git commit -m "feat(g1_brain/brain): PHONE_CALL_PREAMBLE for phone-session realtime

Prepended to the existing brain system prompt by PhoneRealtimeSession.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: phone/realtime_session.py — PhoneRealtimeSession

**Files:**
- Create: `g1_brain/g1_brain/phone/realtime_session.py`
- Create: `g1_brain/tests/phone/test_realtime_session.py`

This is the **largest** task in the plan. The class subclasses `BrainRealtimeAgent` (which itself subclasses va-demo's `RealtimeAgent`). We override:

1. The audio sink (write to transport instead of `self.speaker`)
2. The audio source (read from transport instead of `self.mic`)
3. The instructions resolver (prepend phone preamble)
4. The tool schemas (drop `start_phone_call`, add `end_call`)
5. `_execute_tool` for the new `end_call` tool

We reuse: tool dispatch, safety, plan tracking, response_id cancel tracking, conversation logging hooks, barge-in cleanup.

- [ ] **Step 1: Failing tests**

`g1_brain/tests/phone/test_realtime_session.py`:

```python
"""Tests for PhoneRealtimeSession — audio source/sink override + end_call tool.

We don't talk to real OpenAI Realtime. We construct the session with
a fake `mic` / `speaker` / `transport` and exercise the override
methods directly.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from g1_brain.phone.realtime_session import PhoneRealtimeSession, END_CALL_SCHEMA


def _make_session(*, transport=None, dialer=None, skill_server=None):
    transport = transport or MagicMock()
    dialer = dialer or MagicMock()
    skill_server = skill_server or MagicMock()
    skill_server.execute = AsyncMock(return_value={"ok": True, "summary": "x"})
    # We need to pass parent-required fields; use bare MagicMocks for the
    # speaker/mic since we override the loops that use them.
    return PhoneRealtimeSession(
        mic=MagicMock(),
        speaker=MagicMock(),
        camera=MagicMock(),
        skill_server=skill_server,
        scene_bus=MagicMock(),
        transport=transport,
        dialer=dialer,
        call_sid="CA00000000000000000000000000000000",
    )


def test_resolve_instructions_prepends_phone_preamble():
    s = _make_session()
    out = s._resolve_instructions()
    assert "phone call" in out.lower()
    # also contains base brain prompt (asserted by presence of any brain-specific phrase)
    assert "robot" in out.lower() or "sparky" in out.lower()


def test_resolve_tool_schemas_filters_start_phone_call_adds_end_call():
    s = _make_session()
    schemas = s._resolve_tool_schemas()
    names = [t.get("name") for t in schemas]
    assert "end_call" in names
    assert "start_phone_call" not in names


@pytest.mark.asyncio
async def test_execute_tool_end_call_invokes_dialer_hangup():
    dialer = MagicMock()
    dialer.hangup = AsyncMock()
    s = _make_session(dialer=dialer)
    s.call_sid = "CA" + "1" * 32
    result = await s._execute_tool("end_call", {}, call_id="cid")
    assert result["ok"] is True
    dialer.hangup.assert_awaited_once_with("CA" + "1" * 32)


@pytest.mark.asyncio
async def test_execute_tool_routes_other_tools_to_skill_server():
    s = _make_session()
    result = await s._execute_tool("gesture", {"name": "wave_right"}, call_id="cid")
    assert result["ok"] is True
    s.skill_server.execute.assert_awaited()


def test_end_call_schema_shape():
    assert END_CALL_SCHEMA["name"] == "end_call"
    assert END_CALL_SCHEMA["type"] == "function"
    assert "description" in END_CALL_SCHEMA
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/realtime_session.py`:

```python
"""PhoneRealtimeSession — BrainRealtimeAgent over a Twilio Media Streams call.

Inherits 95% of behaviour from BrainRealtimeAgent (which itself subclasses
va-demo's RealtimeAgent). We override only:

  - audio sink (response.output_audio.delta → transport, not self.speaker)
  - audio source (uplink reads from transport, not self.mic)
  - instructions (prepend PHONE_CALL_PREAMBLE)
  - tool schemas (drop start_phone_call, add end_call)
  - _execute_tool (handle end_call locally; everything else → super)
"""
from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..brain.realtime_agent import BrainRealtimeAgent
from ..brain.prompts import PHONE_CALL_PREAMBLE


log = logging.getLogger(__name__)


END_CALL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "name": "end_call",
    "description": (
        "Hang up the current phone call. Use after a clear goodbye or when "
        "the operator clearly wants to end the conversation."
    ),
    "parameters": {"type": "object", "properties": {}},
}


@dataclass
class PhoneRealtimeSession(BrainRealtimeAgent):
    """Realtime session whose audio I/O is a Twilio Media Stream."""

    # Required at construction. Defaulted to None for dataclass-extension safety.
    transport: Any = None         # TwilioMediaStreamTransport
    dialer: Any = None            # TwilioDialer (for end_call hangup)
    call_sid: str = ""

    # ----- prompts / tools ------------------------------------------------

    def _resolve_instructions(self) -> str:
        base = super()._resolve_instructions()
        return PHONE_CALL_PREAMBLE + "\n\n" + base

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        base = super()._resolve_tool_schemas()
        filtered = [s for s in base if s.get("name") != "start_phone_call"]
        return filtered + [END_CALL_SCHEMA]

    # ----- tool dispatch --------------------------------------------------

    async def _execute_tool(
        self, name: str, args: Dict[str, Any], *, call_id: str = ""
    ) -> Dict[str, Any]:
        if name == "end_call":
            if self.dialer is None or not self.call_sid:
                return {"ok": False, "reason": "no dialer or call_sid"}
            try:
                await self.dialer.hangup(self.call_sid)
                return {"ok": True, "summary": "call ending"}
            except Exception as e:  # noqa: BLE001
                return {"ok": False, "reason": f"hangup failed: {e!s}"}
        return await super()._execute_tool(name, args, call_id=call_id)

    # ----- audio sink override --------------------------------------------
    # Parent's _handle_event writes response audio to self.speaker.write().
    # We intercept BEFORE super by handling the event ourselves; for every
    # other event type we delegate to super.

    async def _handle_event(self, ws, evt: Dict[str, Any]) -> None:
        t = evt.get("type", "")
        if t == "response.output_audio.delta" and self.transport is not None:
            b64 = evt.get("delta", "")
            if b64:
                pcm = base64.b64decode(b64)
                try:
                    await self.transport.send_outbound_pcm24k(pcm)
                except Exception:
                    log.exception("transport.send_outbound_pcm24k raised")
            # Notify any listeners (parent does this too — keep parity)
            if self.on_response_audio_delta is not None:
                try:
                    self.on_response_audio_delta()
                except Exception:
                    log.exception("on_response_audio_delta raised")
            return
        if t == "input_audio_buffer.speech_started" and self.transport is not None:
            # Barge-in: flush queued outbound audio on Twilio side
            try:
                await self.transport.clear_outbound()
            except Exception:
                log.exception("transport.clear_outbound raised")
            # fall through to super for cancel handling
        await super()._handle_event(ws, evt)

    # ----- audio source override ------------------------------------------
    # Parent's uplink loop reads from self.mic.queue. We provide our own
    # uplink task that reads from the transport instead.

    async def _phone_uplink_loop(self, ws) -> None:
        """Forward Twilio inbound audio to OpenAI input_audio_buffer.append."""
        async for pcm24k in self.transport.iter_inbound_pcm24k():
            payload = base64.b64encode(pcm24k).decode("ascii")
            try:
                import json
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": payload,
                }))
            except Exception:
                log.exception("ws.send raised; ending uplink")
                return
```

**Note on the uplink loop wiring**: the parent class's `.run()` method starts its mic-reading task. To replace it with `_phone_uplink_loop`, `bridge_server.py` will explicitly call a custom run-helper (see Task 9). We do NOT modify `BrainRealtimeAgent.run` — we orchestrate from outside instead.

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_realtime_session.py -v 2>&1 | tail
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/realtime_session.py g1_brain/tests/phone/test_realtime_session.py
git commit -m "feat(g1_brain/phone): realtime_session — BrainRealtimeAgent over Twilio

Subclasses BrainRealtimeAgent, overrides only audio sink/source +
instructions + tool schema + end_call dispatch. All safety, plan
tracking, barge-in inherited untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — Bridge orchestration

### Task 9: phone/bridge_server.py (aiohttp WS app + per-call wiring)

**Files:**
- Create: `g1_brain/g1_brain/phone/bridge_server.py`
- Create: `g1_brain/tests/phone/test_bridge_server.py`

- [ ] **Step 1: Failing tests** (per-handler unit tests; integration test is live E2E in Phase 7)

`g1_brain/tests/phone/test_bridge_server.py`:

```python
"""Tests for phone.bridge_server — request validation + routing.

Full audio-loop integration tests live in test_realtime_session.py and
the live E2E.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from g1_brain.phone.bridge_server import build_app
from g1_brain.phone.config import PhoneConfig, TwilioConfig
from g1_brain.phone.voice_lease import VoiceLeaseManager


def _make_cfgs(tmp_path):
    twilio = TwilioConfig(
        account_sid="AC" + "0" * 32, auth_token="tok",
        api_key_sid="SK" + "0" * 32, api_key_secret="sec",
        from_number="+14155550100",
    )
    phone = PhoneConfig(
        public_bridge_url="wss://example/twilio",
        allowed_callers=["+61411706848"],
        bind_host="127.0.0.1", bind_port=0,   # 0 = OS-assigned
    )
    return twilio, phone


@pytest.fixture
def lease_path(tmp_path):
    return tmp_path / "lease.json"


@pytest.mark.asyncio
async def test_healthz_returns_ok(tmp_path, lease_path):
    twilio, phone = _make_cfgs(tmp_path)
    app = build_app(
        twilio_cfg=twilio, phone_cfg=phone,
        skill_server=MagicMock(), scene_bus=MagicMock(),
        dialer=MagicMock(),
        voice_lease=VoiceLeaseManager(lease_path),
        version="test",
    )
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            resp = await client.get("/healthz")
            assert resp.status == 200
            body = await resp.json()
            assert body["ok"] is True
            assert body["version"] == "test"
            assert body["calls_active"] == 0


@pytest.mark.asyncio
async def test_ws_rejects_bad_signature(tmp_path, lease_path):
    twilio, phone = _make_cfgs(tmp_path)
    app = build_app(
        twilio_cfg=twilio, phone_cfg=phone,
        skill_server=MagicMock(), scene_bus=MagicMock(),
        dialer=MagicMock(),
        voice_lease=VoiceLeaseManager(lease_path),
        version="test",
    )
    async with TestServer(app) as server:
        async with TestClient(server) as client:
            # WS upgrade without X-Twilio-Signature → reject
            resp = await client.get(
                "/twilio",
                headers={
                    "Upgrade": "websocket",
                    "Connection": "upgrade",
                    "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
                },
            )
            assert resp.status == 403
```

- [ ] **Step 2: Run, expect ImportError**

- [ ] **Step 3: Implement**

`g1_brain/g1_brain/phone/bridge_server.py`:

```python
"""aiohttp WebSocket server that bridges Twilio Media Streams ⇄ OpenAI Realtime.

Exposes:
  GET  /healthz          → JSON health payload
  GET  /twilio  (Upgrade)→ accept one phone session per connection
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from aiohttp import web, WSMsgType

from .config import PhoneConfig, TwilioConfig
from .realtime_session import PhoneRealtimeSession
from .tunnel_health import build_healthz_payload, validate_twilio_signature
from .twilio_transport import TwilioMediaStreamTransport
from .voice_lease import LeaseHolder, VoiceLeaseManager


log = logging.getLogger(__name__)


def build_app(
    *,
    twilio_cfg: TwilioConfig,
    phone_cfg: PhoneConfig,
    skill_server: Any,
    scene_bus: Any,
    dialer: Any,
    voice_lease: VoiceLeaseManager,
    version: str = "0.1.0",
) -> web.Application:
    app = web.Application()
    state = {
        "twilio_cfg": twilio_cfg,
        "phone_cfg": phone_cfg,
        "skill_server": skill_server,
        "scene_bus": scene_bus,
        "dialer": dialer,
        "voice_lease": voice_lease,
        "version": version,
        "calls_active": 0,
    }
    app["state"] = state

    app.router.add_get("/healthz", _healthz)
    app.router.add_get("/twilio", _twilio_ws)
    return app


async def _healthz(request: web.Request) -> web.Response:
    s = request.app["state"]
    return web.json_response(
        build_healthz_payload(version=s["version"], calls_active=s["calls_active"])
    )


async def _twilio_ws(request: web.Request) -> web.WebSocketResponse:
    state = request.app["state"]
    twilio_cfg: TwilioConfig = state["twilio_cfg"]
    phone_cfg: PhoneConfig = state["phone_cfg"]
    voice_lease: VoiceLeaseManager = state["voice_lease"]

    # 1. Validate Twilio signature on the WS UPGRADE request.
    sig = request.headers.get("X-Twilio-Signature", "")
    # For WS upgrades, Twilio signs URL only (no POST params).
    full_url = str(request.url)
    if not sig or not validate_twilio_signature(
        full_url, {}, sig, twilio_cfg.auth_token.get_secret_value()
    ):
        log.warning("phone: bad/missing X-Twilio-Signature from %s", request.remote)
        return web.Response(status=403, text="forbidden")

    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    transport = TwilioMediaStreamTransport(ws)
    owner = f"call-{uuid.uuid4()}"
    session = None

    try:
        # 2. Read start event (validates Twilio shape AND gives us caller info)
        start = await asyncio.wait_for(transport.start(), timeout=10.0)
        log.info("phone: start streamSid=%s callSid=%s bsid=%s from=%s",
                 start.stream_sid, start.call_sid, start.brain_session_id,
                 start.from_number)

        # 3. Caller-id allowlist
        if start.from_number and start.from_number not in phone_cfg.allowed_callers:
            log.warning("phone: caller %s not whitelisted", start.from_number)
            await ws.close()
            return ws

        # 4. Voice lease
        if not voice_lease.acquire(LeaseHolder.PHONE, owner=owner):
            log.warning("phone: voice lease busy")
            await ws.close()
            return ws

        state["calls_active"] += 1

        # 5. Build the realtime session
        session = PhoneRealtimeSession(
            mic=None,             # not used; we override uplink
            speaker=None,         # not used; we override sink
            camera=None,
            skill_server=state["skill_server"],
            scene_bus=state["scene_bus"],
            transport=transport,
            dialer=state["dialer"],
            call_sid=start.call_sid,
        )

        # 6. Run the session with our custom uplink + the parent's downlink.
        await _run_phone_session(session, phone_cfg)

    except asyncio.TimeoutError:
        log.warning("phone: start event timeout; closing")
    except Exception:
        log.exception("phone: session crashed")
    finally:
        state["calls_active"] = max(0, state["calls_active"] - 1)
        # Defensive: tell the robot to stop in case the model was mid-walk
        try:
            await state["skill_server"].execute("stop", {})
        except Exception:
            log.exception("phone: defensive stop() failed")
        voice_lease.release(LeaseHolder.PHONE, owner=owner)
        await transport.close()
    return ws


async def _run_phone_session(
    session: PhoneRealtimeSession, phone_cfg: PhoneConfig
) -> None:
    """Open OpenAI Realtime WS, run uplink + downlink loops, await one of them ending.

    We do NOT use BrainRealtimeAgent.run() (which would try to drive
    self.mic/self.speaker). Instead we replicate its connect step then
    spawn:
      - uplink:   PhoneRealtimeSession._phone_uplink_loop(ws)
      - downlink: a loop calling _handle_event for each ws.recv()
    """
    import json
    import os

    import websockets

    url = f"wss://api.openai.com/v1/realtime?model={phone_cfg.realtime_model}"
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    headers = [("Authorization", f"Bearer {api_key}")]
    async with websockets.connect(url, additional_headers=headers, max_size=16 * 1024 * 1024) as ws:
        # Send session.update
        session_update = {
            "type": "session.update",
            "session": {
                "type": "realtime",
                "model": phone_cfg.realtime_model,
                "voice": phone_cfg.realtime_voice,
                "instructions": session._resolve_instructions(),
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "gpt-4o-transcribe"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700,
                },
                "tools": session._resolve_tool_schemas(),
            },
        }
        await ws.send(json.dumps(session_update))

        # Kick the greeting via response.create with an inline assistant message.
        kick = {
            "type": "response.create",
            "response": {"instructions": phone_cfg.greeting},
        }
        await ws.send(json.dumps(kick))

        async def _downlink():
            try:
                async for raw in ws:
                    try:
                        evt = json.loads(raw)
                    except Exception:
                        continue
                    await session._handle_event(ws, evt)
            except Exception:
                log.exception("phone.downlink crashed")

        uplink_task = asyncio.create_task(session._phone_uplink_loop(ws))
        downlink_task = asyncio.create_task(_downlink())

        idle_task = asyncio.create_task(
            asyncio.sleep(phone_cfg.call_idle_timeout_s * 3)  # outer guard
        )
        done, pending = await asyncio.wait(
            {uplink_task, downlink_task, idle_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/phone/test_bridge_server.py -v 2>&1 | tail
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/phone/bridge_server.py g1_brain/tests/phone/test_bridge_server.py
git commit -m "feat(g1_brain/phone): bridge_server — aiohttp WS app for Twilio Media Streams

/healthz + /twilio routes. Validates Twilio signature, enforces
caller-id whitelist, acquires voice lease, runs PhoneRealtimeSession
with OpenAI Realtime over the call's audio.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: phone/call_me.py — CLI dialer

**Files:**
- Create: `g1_brain/g1_brain/phone/call_me.py`

- [ ] **Step 1: Implement** (no unit tests — it's a 30-line argparse wrapper; manual smoke is enough)

`g1_brain/g1_brain/phone/call_me.py`:

```python
"""CLI: dial the configured operator phone number through the running bridge.

Usage:
  python -m g1_brain.phone.call_me [--to +61...] [--dry-run]

Requires:
  - .env loaded (set -a; source .env; set +a) so PhoneConfig env vars resolve
  - The bridge is running (`agent_main.py --enable-phone`) so the call has
    somewhere to land

`--dry-run` skips dialing; instead verifies Twilio creds by GETting
/Accounts/{sid}.json.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .config import load_from_env, PhoneConfigError
from .twilio_dialer import TwilioDialer, TwilioDialError


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--to", default=None,
        help="E.164 number to dial; defaults to first PHONE_ALLOWED_CALLERS",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip dial; just verify Twilio creds via GET /Accounts/{sid}",
    )
    args = parser.parse_args(argv)

    try:
        twilio_cfg, phone_cfg = load_from_env()
    except PhoneConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    dialer = TwilioDialer(twilio_cfg, str(phone_cfg.public_bridge_url))

    if args.dry_run:
        try:
            name = await dialer.dry_run()
        except TwilioDialError as e:
            print(f"dry-run failed: {e}", file=sys.stderr)
            return 1
        print(f"Twilio credentials valid; account: {name}")
        return 0

    to = args.to or (phone_cfg.allowed_callers[0] if phone_cfg.allowed_callers else None)
    if not to:
        print("no --to and PHONE_ALLOWED_CALLERS is empty", file=sys.stderr)
        return 2

    try:
        sid = await dialer.dial(to)
    except TwilioDialError as e:
        print(f"dial failed: {e}", file=sys.stderr)
        return 1
    print(f"call placed; CallSid={sid}; To={to}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main(sys.argv[1:])))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke check (no network)**

```bash
python -m g1_brain.phone.call_me --help
```

Expected: argparse usage printed.

- [ ] **Step 3: Commit**

```bash
git add g1_brain/g1_brain/phone/call_me.py
git commit -m "feat(g1_brain/phone): call_me CLI — one-shot dialer + --dry-run

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 5 — Wire bridge into the brain runtime

### Task 11: skills — add start_phone_call

**Files:**
- Modify: `g1_brain/g1_brain/skills/skill_server.py` (add _skill_start_phone_call + dialer injection)
- Modify: `g1_brain/g1_brain/skills/tool_schemas.py` (add START_PHONE_CALL_SCHEMA, register in build_tool_schemas)

- [ ] **Step 1: Inspect tool_schemas current shape**

```bash
grep -nE "^def |START_PHONE|def build_tool_schemas" g1_brain/g1_brain/skills/tool_schemas.py | head
```

- [ ] **Step 2: Add schema** in `g1_brain/g1_brain/skills/tool_schemas.py` (find `build_tool_schemas`, add at end of the function before the return):

```python
START_PHONE_CALL_SCHEMA = {
    "type": "function",
    "name": "start_phone_call",
    "description": (
        "Place an outbound phone call so the operator can talk to Sparky "
        "from anywhere. Returns when the call is dialled (not when answered)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "E.164 number (e.g. +14155550199). If omitted, defaults to the configured operator number.",
            }
        },
    },
}
```

Then inside `build_tool_schemas(...)`, append `START_PHONE_CALL_SCHEMA` to the returned list IF a new kwarg `phone_enabled=False` is True. Modify the signature to accept it.

- [ ] **Step 3: Add `_skill_start_phone_call` to SkillServer**

In `g1_brain/g1_brain/skills/skill_server.py`, find the `__init__` and add two optional kwargs near the bottom:

```python
        dialer=None,
        default_phone_to: Optional[str] = None,
```

Save them as `self._dialer = dialer; self._default_phone_to = default_phone_to`.

Add a new method on `SkillServer`:

```python
    async def _skill_start_phone_call(
        self, *, to: Optional[str] = None, **_: object,
    ) -> Dict[str, Any]:
        if self._dialer is None:
            return {"ok": False, "skill": "start_phone_call",
                    "reason": "phone bridge not enabled"}
        dest = to or self._default_phone_to
        if not dest:
            return {"ok": False, "skill": "start_phone_call",
                    "reason": "no destination configured"}
        try:
            sid = await self._dialer.dial(dest)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "skill": "start_phone_call",
                    "reason": f"dial failed: {e!s}"}
        return {"ok": True, "skill": "start_phone_call",
                "summary": f"calling {dest}", "call_sid": sid}
```

- [ ] **Step 4: Test**

`g1_brain/tests/phone/test_skill_start_phone_call.py`:

```python
"""Test the start_phone_call skill on SkillServer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from g1_brain.skills.skill_server import SkillServer


def _make_server(*, dialer=None, default_to=None):
    return SkillServer(
        combo_ctl=MagicMock(),
        safety=MagicMock(validate=AsyncMock(return_value=(True, "", {}))),
        tts=MagicMock(), vision=MagicMock(),
        camera_hub=MagicMock(), scene_bus=MagicMock(), fsm=MagicMock(),
        sim=True,
        dialer=dialer,
        default_phone_to=default_to,
    )


@pytest.mark.asyncio
async def test_start_phone_call_no_dialer():
    server = _make_server(dialer=None)
    r = await server.execute("start_phone_call", {"to": "+1"})
    assert r["ok"] is False
    assert "phone bridge not enabled" in r["reason"]


@pytest.mark.asyncio
async def test_start_phone_call_uses_default_to():
    dialer = MagicMock(); dialer.dial = AsyncMock(return_value="CA1" + "0" * 31)
    server = _make_server(dialer=dialer, default_to="+14155550199")
    r = await server.execute("start_phone_call", {})
    assert r["ok"] is True
    dialer.dial.assert_awaited_once_with("+14155550199")


@pytest.mark.asyncio
async def test_start_phone_call_with_explicit_to():
    dialer = MagicMock(); dialer.dial = AsyncMock(return_value="CA2" + "0" * 31)
    server = _make_server(dialer=dialer, default_to="+1default")
    r = await server.execute("start_phone_call", {"to": "+14155550199"})
    assert r["ok"] is True
    dialer.dial.assert_awaited_once_with("+14155550199")
```

Run:

```bash
pytest tests/phone/test_skill_start_phone_call.py -v 2>&1 | tail
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/skills/skill_server.py g1_brain/g1_brain/skills/tool_schemas.py \
        g1_brain/tests/phone/test_skill_start_phone_call.py
git commit -m "feat(g1_brain/skills): start_phone_call skill

Local va-demo Realtime can call this to dial out via Twilio. When the
phone bridge is disabled (dialer=None at SkillServer construction),
returns a clear reason.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: agent_main.py — --enable-phone flag

**Files:**
- Modify: `g1_brain/g1_brain/apps/agent_main.py`

- [ ] **Step 1: Inspect arg-parsing**

```bash
grep -n "add_argument\|parser =" g1_brain/g1_brain/apps/agent_main.py | head -20
```

- [ ] **Step 2: Add `--enable-phone` flag** to the existing argparse block:

```python
    parser.add_argument(
        "--enable-phone", action="store_true",
        help="Mount Twilio bridge on phone.bind_port (requires TWILIO_* env vars)",
    )
```

- [ ] **Step 3: Wire bridge mount** at the appropriate place in `main()` (after SkillServer is built — search for `SkillServer(` to locate). Add:

```python
    bridge_task = None
    if args.enable_phone or cfg.get("phone", {}).get("enabled", False):
        from g1_brain.phone.config import load_from_env as _load_phone_env
        from g1_brain.phone.bridge_server import build_app as _build_bridge_app
        from g1_brain.phone.voice_lease import VoiceLeaseManager
        from g1_brain.phone.twilio_dialer import TwilioDialer
        from aiohttp import web as _web

        twilio_cfg, phone_cfg = _load_phone_env()
        # vision_gate must be enabled — fail-closed
        if not cfg.get("safety", {}).get("vision_gate", {}).get("enabled", False):
            raise RuntimeError(
                "phone bridge requires safety.vision_gate.enabled=true (fail-closed)"
            )
        dialer = TwilioDialer(twilio_cfg, str(phone_cfg.public_bridge_url))
        # late-wire dialer into the existing skill_server so start_phone_call works
        skill_server._dialer = dialer
        skill_server._default_phone_to = (
            phone_cfg.allowed_callers[0] if phone_cfg.allowed_callers else None
        )
        lease = VoiceLeaseManager()
        app = _build_bridge_app(
            twilio_cfg=twilio_cfg, phone_cfg=phone_cfg,
            skill_server=skill_server, scene_bus=scene_bus,
            dialer=dialer, voice_lease=lease,
            version="0.1.0",
        )
        runner = _web.AppRunner(app)
        await runner.setup()
        site = _web.TCPSite(runner, phone_cfg.bind_host, phone_cfg.bind_port)
        await site.start()
        log.info("phone bridge listening on %s:%d",
                 phone_cfg.bind_host, phone_cfg.bind_port)
```

(Note: place this in the async main; if main is sync today, the bridge mount must be moved inside an existing asyncio entry point. Inspect first and adapt.)

- [ ] **Step 4: Smoke test (no Twilio creds)**

```bash
cd ~/unitree/unitree-notes/g1_brain
python -c "import g1_brain.apps.agent_main as m; print('imports ok')"
```

Expected: `imports ok`.

- [ ] **Step 5: Commit**

```bash
git add g1_brain/g1_brain/apps/agent_main.py
git commit -m "feat(g1_brain/apps): --enable-phone flag mounts Twilio bridge

When enabled, late-wires the dialer onto skill_server so start_phone_call
works from the local Realtime path. Fails closed if vision_gate is
disabled in config.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: configs/g1_brain.yaml — phone: section

**Files:**
- Modify: `g1_brain/configs/g1_brain.yaml`

- [ ] **Step 1: Append `phone:` block at end of file**

```yaml

phone:
  enabled: false              # set true OR pass --enable-phone on agent_main
  bind_host: "127.0.0.1"      # public path is via reverse tunnel only
  bind_port: 8787
  call_idle_timeout_s: 30
  tool_timeout_s: 5.0
  realtime_model: "gpt-realtime"
  realtime_voice: "alloy"
  greeting: "Hi, this is Sparky. What would you like me to do?"
```

- [ ] **Step 2: yaml load smoke**

```bash
python -c "import yaml; print(yaml.safe_load(open('configs/g1_brain.yaml'))['phone']['bind_port'])"
```

Expected: `8787`.

- [ ] **Step 3: Commit**

```bash
git add g1_brain/configs/g1_brain.yaml
git commit -m "feat(g1_brain/configs): phone: section, off by default

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: .env.example — placeholders

**Files:**
- Create or modify: `g1_brain/.env.example`

- [ ] **Step 1: Inspect current .env.example if any**

```bash
ls g1_brain/.env.example 2>/dev/null && cat g1_brain/.env.example
```

- [ ] **Step 2: Append (or create with) the new lines**

```bash
cat >> g1_brain/.env.example <<'EOF'

# === Phone bridge (Twilio + reverse tunnel) ==========================
# Rotate after each demo if the values were ever shared in chat/email.
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx       # used for X-Twilio-Signature only
TWILIO_API_KEY_SID=SKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx     # used for REST basic auth
TWILIO_API_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+14155550100
PUBLIC_BRIDGE_URL=wss://twilio.openproduct.cn/twilio
PHONE_ALLOWED_CALLERS=+61411706848
EOF
```

- [ ] **Step 3: Commit**

```bash
git add g1_brain/.env.example
git commit -m "docs(g1_brain): .env.example — phone bridge env var template

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 6 — Tunnel completion (per VPS-agent runbook)

These steps complete the operator's WSL2 manual. Public-host side was already provisioned (`twilio.openproduct.cn` → nginx → reverse SSH tunnel listening on VPS `127.0.0.1:8787`). SSH key was saved + host keys pinned in earlier infra prep.

### Task 15: install autossh + manual tunnel smoke

**No files** — system install only.

- [ ] **Step 1: Install autossh**

```bash
sudo apt-get update && sudo apt-get install -y autossh
autossh -V
```

Expected: non-empty version (e.g. `autossh 1.4g`).

- [ ] **Step 2: Bring up the bridge in T1** (one shot, foreground for now)

In a new terminal:

```bash
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active
```

Expected: log shows `phone bridge listening on 127.0.0.1:8787`.

In another terminal:

```bash
ss -tln | grep 8787
```

Expected: `LISTEN 0 ... 127.0.0.1:8787`.

- [ ] **Step 3: Start manual reverse tunnel in T2**

```bash
ssh -i ~/.ssh/sparkytun_ed25519 \
    -o ExitOnForwardFailure=yes \
    -N -R 127.0.0.1:8787:127.0.0.1:8787 \
    sparkytun@15.204.242.207
```

Expected: silent cursor. Do not Ctrl-C.

- [ ] **Step 4: Verify external reachability**

From any external network:

```bash
curl -i https://twilio.openproduct.cn/healthz
```

Expected: `HTTP/2 200` + JSON `{"ok":true, "version":"0.1.0", "calls_active":0}`.

If 502 → check `ss -tln | grep 8787` again on WSL2; bridge process died.

- [ ] **Step 5: Once green, Ctrl-C the manual tunnel and stop the bridge.**

---

### Task 16: systemd-user unit (persistent tunnel)

**Files:**
- Create: `~/.config/systemd/user/sparkytun-tunnel.service`

- [ ] **Step 1: Confirm systemd is already active in WSL2**

(Already confirmed earlier: `ps -p 1 -o comm=` → `systemd`. If not, see operator's manual Step 5.1 to add `[boot]\nsystemd=true` to `/etc/wsl.conf` and `wsl --shutdown`.)

- [ ] **Step 2: Write unit**

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/sparkytun-tunnel.service <<'EOF'
[Unit]
Description=Sparky bridge reverse SSH tunnel to twilio.openproduct.cn (port 8787)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Restart=always
RestartSec=5

Environment=AUTOSSH_GATETIME=0
Environment=AUTOSSH_POLL=30

ExecStart=/usr/bin/autossh -M 0 -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o ExitOnForwardFailure=yes \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=%h/.ssh/known_hosts \
    -i %h/.ssh/sparkytun_ed25519 \
    -R 127.0.0.1:8787:127.0.0.1:8787 \
    sparkytun@15.204.242.207

[Install]
WantedBy=default.target
EOF
```

- [ ] **Step 3: Enable + start**

```bash
systemctl --user daemon-reload
systemctl --user enable sparkytun-tunnel
systemctl --user start sparkytun-tunnel
systemctl --user status sparkytun-tunnel --no-pager
```

Expected: `Active: active (running)` with `Tasks: 2` (autossh parent + ssh child).

- [ ] **Step 4: Enable user lingering (survive shell logout)**

```bash
sudo loginctl enable-linger $USER
```

- [ ] **Step 5: Verify reachability again**

```bash
# bring bridge back up
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active &
sleep 2
curl -i https://twilio.openproduct.cn/healthz
```

Expected: 200 again.

---

## Phase 7 — Live E2E verification (the done gate)

These steps are the verification protocol from `mcp_twilio_design.md` §15. Evidence captured to `/tmp/twilio_bridge_verify_<date>.log`.

Each step is GO / NO-GO; do not advance until the prior is green.

### Task 17: Step 1 — healthz external

- [ ] **Step 1: curl from a non-WSL2 network**

```bash
curl -i https://twilio.openproduct.cn/healthz
```

Expected: `HTTP/2 200` + `{"ok":true, ...}`.

Capture full response to verification log.

---

### Task 18: Step 2 — credentials dry run

- [ ] **Step 1: dry-run**

```bash
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.phone.call_me --dry-run
```

Expected: `Twilio credentials valid; account: <FriendlyName>`.

---

### Task 19: Step 3 — full system up

- [ ] **Step 1: T1 — sim**

```bash
conda activate agi
cd ~/unitree/unitree-notes/unitree_mujoco/simulate_python
python unitree_mujoco.py
# In viewer: press 7 (set down), 9 (release elastic band)
```

- [ ] **Step 2: T2 — estop listener**

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
python -m g1_brain.safety.estop_listener
```

- [ ] **Step 3: T3 — brain + bridge**

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.apps.agent_main --enable-phone --mode active
```

Wait for log:
- `combo policy active`
- `phone bridge listening on 127.0.0.1:8787`
- no errors about `safety.vision_gate.enabled`

---

### Task 20: Step 4 — outbound dial

- [ ] **Step 1: T4 — call_me**

```bash
conda activate agi
cd ~/unitree/unitree-notes/g1_brain
set -a; source .env; set +a
python -m g1_brain.phone.call_me
```

Expected within ~5 s:
- CLI prints `call placed; CallSid=CA...`
- Operator's phone (`+61411706848`) rings.

If phone does NOT ring in 15 s:
- Check Twilio console call log → status / failure reason
- Check `curl https://twilio.openproduct.cn/healthz` again
- Check T3 log for WS upgrade attempt + signature errors

---

### Task 21: Step 5 — audio bridge

- [ ] **Step 1: Operator picks up. Listens for greeting.**

Expected: clear audio "Hi, this is Sparky. What would you like me to do?" within ~2 s of answer.

- [ ] **Step 2: Operator says: "Say hello to me in French."**

Expected: model replies in French within ~2 s. No clicks, no robotic distortion, no echo.

Record measured latency to verification log.

---

### Task 22: Step 6 — robot moves on phone command

- [ ] **Step 1: Operator says: "Wave your right hand."**

Watch T3 log + MuJoCo viewer simultaneously. Expected sequence:

1. T3: `tool: gesture(name="wave_right")`
2. T3: `safety.validate(gesture, ...) → ok=True`
3. T3: `vision_risk_gate.review → SAFE`
4. T3: `dds.dispatched` or equivalent skill log
5. MuJoCo: G1 visibly waves right hand for ~1 s
6. Phone audio: model says "Done." or similar

- [ ] **Step 2: Operator says: "Stop and goodbye."**

Expected:
1. T3: `tool: end_call`
2. T3: `twilio.hangup CA... → 200` (or similar)
3. Phone: call ends
4. T3: `voice lease released`

- [ ] **Step 3: Capture screenshot of G1 mid-wave**

Save to `/tmp/twilio_bridge_verify_<date>_step6.png`. This is canonical evidence.

- [ ] **Step 4: Final commit — verification log**

```bash
mkdir -p ~/unitree/unitree-notes/docs/twilio-bridge-verify
cp /tmp/twilio_bridge_verify_<date>.log ~/unitree/unitree-notes/docs/twilio-bridge-verify/
cp /tmp/twilio_bridge_verify_<date>_step6.png ~/unitree/unitree-notes/docs/twilio-bridge-verify/
cd ~/unitree/unitree-notes
git add docs/twilio-bridge-verify/
git commit -m "verify(phone): six-step E2E recording — phone → robot waves

Sim G1 waved right hand on phone command. Evidence: log + screenshot.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 23 (optional, nice-to-have): Step 7 — voice trigger

Only run if Tasks 17–22 all green.

- [ ] **Step 1: T5 — local va-demo**

```bash
conda activate agi
cd ~/unitree/unitree-notes/va-demo
set -a; source .env; set +a
python -m va_demo.main --mode active
```

- [ ] **Step 2: Operator says (to laptop mic): "Hi Sparky, call me."**

Expected: wake-word trips → local Realtime calls `start_phone_call(to="+61411706848")` → phone rings → continue as Tasks 21–22.

---

## Self-review checklist (for the plan author)

- **Spec coverage**: every section of `mcp_twilio_design.md` maps to a task above:
  - §3 architecture → Tasks 9, 12 (bridge mount + topology)
  - §4 components → Tasks 1–10 (one per file)
  - §5 audio pipeline → Task 2
  - §6 Twilio integration → Tasks 5, 6, 15–22
  - §7 OpenAI Realtime → Task 8 (PhoneRealtimeSession + bridge_server's `_run_phone_session`)
  - §8 tool surface → Tasks 8 (filter+end_call), 11 (start_phone_call)
  - §9 safety → Tasks 4 (signature), 9 (caller-id), 12 (vision_gate fail-closed)
  - §10 concurrency → Task 3 + Task 12 (lease wired into bridge)
  - §11 lifecycle → Task 9 (bridge_server happy + finally paths)
  - §12 configuration → Tasks 1, 13, 14
  - §13 errors → Task 9 (idle, tool timeout, transport close)
  - §14 testing → Phase 1–4 unit tests
  - §15 verification → Phase 7 live E2E
  - §16–18 deployment / runbook → Phase 6 (tunnel) + verification logs
- **Placeholders**: no "TBD" / "TODO" / "implement later" remain.
- **Code completeness**: every code step shows the actual code to write.
- **Type consistency**: `SkillServer.execute(tool, args, *, call_id="")` signature matches what `BrainRealtimeAgent._execute_tool` expects (verified in conversation context). `PhoneRealtimeSession.transport` is `TwilioMediaStreamTransport` everywhere.
