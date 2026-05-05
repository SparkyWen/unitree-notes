"""BrainRealtimeAgent — extends va_demo.realtime_agent.RealtimeAgent.

We do not modify va-demo. We subclass and override the three hooks:

- ``_resolve_instructions()`` returns the new brain prompt.
- ``_resolve_tool_schemas()`` returns the SkillServer's full tool list.
- ``_execute_tool()`` delegates everything to the SkillServer (which runs the
  SafetySupervisor internally).

We also add ``inject_perception_event()`` so the GestureAutoTrigger (in the
mock_imitation package) can inform the LLM that the user just made a
mirrorable hand sign, without forcing a specific action.

The va_demo package must be on sys.path before this module is imported. The
``apps/agent_main.py`` entry point is responsible for adding it (per the
design doc §1.4 "import not rewrite" contract).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from va_demo.realtime_agent import RealtimeAgent  # type: ignore

from ..scene_state.fusion import SceneStateBus
from .prompts import (
    REALTIME_SYSTEM_PROMPT_BRAIN,
    REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY,
)

log = logging.getLogger(__name__)


# Type-only; the concrete SkillServer class is built by the skills agent and
# must conform to:
#   class SkillServer:
#       async def execute(self, tool: str, args: dict) -> dict: ...
SkillServer = Any  # noqa: N816 — kept loose so we don't import the real class
                   # (avoids a circular import in the apps wiring layer).


@dataclass
class BrainRealtimeAgent(RealtimeAgent):
    """Slow Brain: va-demo's Realtime client wired to the new SkillServer."""

    # New required boundaries. Default to None so the dataclass can extend its
    # parent without breaking field-order rules; the apps wiring is expected to
    # always pass a real SkillServer + SceneStateBus.
    skill_server: Optional[SkillServer] = None
    scene_bus: Optional[SceneStateBus] = None
    mock_imitate_trigger: Optional[Callable[[str], Awaitable[None]]] = None

    def __post_init__(self):
        super().__post_init__()
        if self.skill_server is None:
            log.warning(
                "BrainRealtimeAgent created without skill_server; tool calls "
                "will all fail with ok=false. Wire one before calling run()."
            )

    # ------------------------------------------------------------------ hooks

    def _resolve_instructions(self) -> str:
        return (
            REALTIME_SYSTEM_PROMPT_BRAIN_VISION_ONLY
            if self.vision_only
            else REALTIME_SYSTEM_PROMPT_BRAIN
        )

    def _resolve_tool_schemas(self) -> List[Dict[str, Any]]:
        # Lazy import so `g1_brain.brain` can be imported in tests that don't
        # care about the skills package layout.
        from ..skills.tool_schemas import build_tool_schemas  # type: ignore

        return build_tool_schemas(sim=True, vision_only=self.vision_only)

    async def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Route every tool call to the SkillServer.

        We intentionally do NOT pre-validate here — the SkillServer runs its
        own SafetySupervisor pass internally (per the contract in
        skills/skill_server.py). Adding a second validation here would
        double-log and could disagree with the server-side decision.
        """
        if self.skill_server is None:
            return {"ok": False, "reason": "skill_server not wired"}
        try:
            return await self.skill_server.execute(name, args)
        except Exception as e:  # noqa: BLE001 — we want to surface anything
            log.exception("skill_server.execute(%s) raised", name)
            return {"ok": False, "reason": f"exception: {e!s}"}

    # ---------------------------------------------------- perception → brain

    async def inject_perception_event(self, event_text: str) -> None:
        """Push a synthetic conversation item so the brain hears about a
        perception event mid-turn.

        We wrap it as a ``conversation.item.create`` with role="system"
        (Realtime accepts system items inside the conversation). The brain
        decides on its own whether to respond — we deliberately do NOT issue a
        ``response.create``: the on-going Realtime session will pick the item
        up at its next response window. If the brain is idle and you want it
        to act immediately, the apps wiring can follow up with its own
        ``response.create`` send.
        """
        if self._ws is None:
            log.debug("inject_perception_event: no ws yet, dropping: %s", event_text)
            return
        evt = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "system",
                "content": [
                    {"type": "input_text", "text": event_text},
                ],
            },
        }
        try:
            await self._ws.send(json.dumps(evt))
        except Exception:  # noqa: BLE001
            log.exception("failed to inject perception event")
