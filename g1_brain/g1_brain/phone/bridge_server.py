"""aiohttp WebSocket server that bridges Twilio Media Streams to OpenAI Realtime.

Exposes:
  GET  /healthz          -> JSON health payload
  GET  /twilio  (Upgrade)-> accept one phone session per connection
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from aiohttp import web

from .config import PhoneConfig, TwilioConfig
from .realtime_session import PhoneRealtimeSession
from .tunnel_health import build_healthz_payload, validate_twilio_signature
from .twilio_transport import TwilioMediaStreamTransport, TwilioStreamClosed
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
    app.on_startup.append(_start_loop_lag_monitor)
    app.on_cleanup.append(_stop_loop_lag_monitor)
    return app


async def _loop_lag_monitor(interval: float = 0.5, warn_s: float = 0.5) -> None:
    """Log when the asyncio loop is starved.

    Twilio's media-stream WS handshake (and the ongoing media pump) must be
    serviced within a few seconds. The bridge shares this loop + the GIL with
    perception render bursts (~134 ms each on llvmpipe) and the realtime agent.
    If a scheduled 0.5 s wake-up returns late, the loop was blocked that long —
    which is exactly what makes Twilio time out (error 31901). This is the
    decisive evidence for loop-starvation vs. a slow tunnel.
    """
    loop = asyncio.get_event_loop()
    while True:
        t0 = loop.time()
        await asyncio.sleep(interval)
        lag = (loop.time() - t0) - interval
        if lag >= warn_s:
            log.warning(
                "phone: event-loop stalled %.2fs — Twilio media WS may miss "
                "its connect/keepalive window (cause of 31901 drops)", lag,
            )


async def _start_loop_lag_monitor(app: web.Application) -> None:
    app["_lag_task"] = asyncio.create_task(_loop_lag_monitor())


async def _stop_loop_lag_monitor(app: web.Application) -> None:
    task = app.get("_lag_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


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
    # Build the full URL from the configured public bridge URL so we always
    # sign against the canonical public-facing URL (not the aiohttp test URL,
    # which can have host:port that yarl rejects, and not the load-balanced
    # internal address which Twilio never sees).
    full_url = str(phone_cfg.public_bridge_url)
    if not sig or not validate_twilio_signature(
        full_url, {}, sig, twilio_cfg.auth_token.get_secret_value()
    ):
        log.warning("phone: bad/missing X-Twilio-Signature from %s", request.remote)
        return web.Response(status=403, text="forbidden")

    loop = asyncio.get_event_loop()
    t_accept = loop.time()
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    t_prepared = loop.time()
    # If prepare() itself took a while, the loop was busy before we even got
    # here — Twilio counts that against its connect timeout.
    log.info("phone: /twilio upgrade accepted; prepare() took %.3fs",
             t_prepared - t_accept)

    transport = TwilioMediaStreamTransport(ws)
    owner = f"call-{uuid.uuid4()}"
    session = None
    lease_acquired = False

    try:
        # 2. Read start event (validates Twilio shape + gives caller info)
        start = await asyncio.wait_for(transport.start(), timeout=10.0)
        log.info(
            "phone: start streamSid=%s callSid=%s bsid=%s from=%s "
            "(connected+start %.3fs after upgrade)",
            start.stream_sid, start.call_sid, start.brain_session_id,
            start.from_number, loop.time() - t_prepared,
        )

        # 3. Caller-id allowlist (only enforce if Twilio provided a From)
        if start.from_number and start.from_number not in phone_cfg.allowed_callers:
            log.warning("phone: caller %s not whitelisted", start.from_number)
            await ws.close()
            return ws

        # 4. Voice lease
        if not voice_lease.acquire(LeaseHolder.PHONE, owner=owner):
            log.warning("phone: voice lease busy")
            await ws.close()
            return ws
        lease_acquired = True

        state["calls_active"] += 1

        # 5. Resolve API key
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            log.error("phone: OPENAI_API_KEY not set")
            await ws.close()
            return ws

        session = _build_phone_session(
            api_key=api_key,
            phone_cfg=phone_cfg,
            skill_server=state["skill_server"],
            scene_bus=state["scene_bus"],
            dialer=state["dialer"],
            transport=transport,
            call_sid=start.call_sid,
        )

        # 6. Run session.run() — opens OpenAI WS, sends _session_update
        #    (which our subclass overrides to enable server VAD), spawns
        #    _uplink + _downlink (both flowing through our overrides).
        #    Also schedule a greeting kick once the WS is up.
        await _run_with_greeting(session, phone_cfg.greeting)

    except (asyncio.TimeoutError, TwilioStreamClosed) as e:
        # Not a crash: Twilio opened the media WS then dropped it before any
        # audio (almost always error 31901 — handshake serviced too late).
        # The call rings, answers, then drops at ~10 s with no audio.
        detail = "start event timeout" if isinstance(e, asyncio.TimeoutError) else str(e)
        log.warning(
            "phone: media stream dropped before audio (%s). Likely Twilio "
            "31901: the WS handshake wasn't serviced in time — check the "
            "'event-loop stalled' lines above and the tunnel RTT.", detail,
        )
    except Exception:
        log.exception("phone: session crashed")
    finally:
        state["calls_active"] = max(0, state["calls_active"] - 1)
        # Defensive: tell the robot to stop in case the model was mid-walk
        try:
            await state["skill_server"].execute("stop", {})
        except Exception:
            log.exception("phone: defensive stop() failed")
        if lease_acquired:
            voice_lease.release(LeaseHolder.PHONE, owner=owner)
        await transport.close()
    return ws


def _build_phone_session(
    *,
    api_key: str,
    phone_cfg: PhoneConfig,
    skill_server: Any,
    scene_bus: Any,
    dialer: Any,
    transport: Any,
    call_sid: str,
) -> PhoneRealtimeSession:
    """Construct PhoneRealtimeSession with parent's required dataclass fields.

    Parent (va-demo RealtimeAgent) requires concrete `mic`, `speaker`, `camera`,
    `vision`, `tts`, `skills`, `safety` fields. For phone mode we don't use
    mic/speaker (we override the audio loops), but the dataclass requires non-None
    values for many of them. We use minimal MagicMocks so construction succeeds
    and the override methods take over at runtime.
    """
    from unittest.mock import MagicMock
    return PhoneRealtimeSession(
        api_key=api_key,
        model=phone_cfg.realtime_model,
        voice=phone_cfg.realtime_voice,
        mic=MagicMock(),     # bypassed by _uplink override
        speaker=MagicMock(), # clear() is sync no-op; speaker not used in phone mode
        camera=skill_server.cam,
        vision=skill_server.vision,
        tts=skill_server.tts,
        skills=MagicMock(),  # not used; SkillServer.execute() is called directly
        safety=skill_server.safety,
        skill_server=skill_server,
        scene_bus=scene_bus,
        transport=transport,
        dialer=dialer,
        call_sid=call_sid,
        # Defense in depth: phone-side model must not be able to place a
        # recursive outbound call. The _resolve_tool_schemas filter in
        # PhoneRealtimeSession also removes start_phone_call from the list,
        # but passing False here ensures build_tool_schemas never adds it
        # in the first place.
        phone_enabled=False,
    )


async def _run_with_greeting(
    session: PhoneRealtimeSession, greeting: str
) -> None:
    """Run the session and kick a greeting response shortly after the WS opens.

    We can't easily hook into the parent's run() to send response.create
    AFTER _session_update completes, so we poll briefly until self._ws
    becomes non-None (parent sets it inside run()) then send via that WS.
    """
    async def _kick():
        # Wait for session._ws to become non-None (parent sets it inside run()).
        for _ in range(200):  # ~2s max
            if getattr(session, "_ws", None) is not None:
                break
            await asyncio.sleep(0.01)
        ws = getattr(session, "_ws", None)
        if ws is None:
            log.warning("phone: greeting skipped — no _ws after 2s")
            return
        try:
            await ws.send(json.dumps({
                "type": "response.create",
                "response": {"instructions": greeting},
            }))
        except Exception:
            log.exception("phone: greeting kick failed")

    kick_task = asyncio.create_task(_kick())
    try:
        await session.run()
    finally:
        kick_task.cancel()
        try:
            await kick_task
        except (asyncio.CancelledError, Exception):
            pass
