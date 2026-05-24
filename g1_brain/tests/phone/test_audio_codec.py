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
