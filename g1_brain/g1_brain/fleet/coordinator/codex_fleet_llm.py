"""CodexFleetLLM — plug the g1_brain *codex* brain into the FleetCommander.

FleetCommander expects an llm object with ``plan_fleet(nl, snapshot) -> dict``
(a FleetPlan). This adapter implements that by asking the codex brain
(`codex exec --json`, via memory.codex_client.CodexClient) to emit the plan as
JSON, then extracting the JSON object out of codex's reasoning+prose reply.

Defaults match the operator's standing codex setup (memory:
g1_brain_codex_high_priority_default) but tuned for the *live* fleet loop:
model gpt-5.5 (the account's working model — the codex default gpt-5.3-codex is
rejected on a ChatGPT plan), reasoning_effort=xhigh, service_tier=fast.

The codex call is async; plan_fleet bridges to it with ``asyncio.run`` because
the command center invokes FleetCommander.plan() inside a thread-pool executor
(no running loop on that thread). Sub-agents intentionally stay deterministic —
only the high-level NL->plan step goes through codex. If codex errors or returns
no parseable plan, this raises and FleetCommander falls back to its
deterministic planner, so the operator is never hard-blocked."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SYS = (
    "You are the commander of a small fleet of Unitree G1 humanoids. "
    "Given the operator command (any language) and the fleet snapshot "
    "(each robot's robot_id and x,y position in metres), output ONE JSON object "
    "for a FleetPlan and NOTHING else. Schema:\n"
    '{"summary": str (short, may be Chinese),\n'
    ' "coordination": {"type": "rendezvous"|"relay"|"patrol"|"none",\n'
    '                  "point": [x,y], "handoff_task": str|null,\n'
    '                  "handoff_from": robot_id|null, "handoff_to": robot_id|null},\n'
    ' "assignments": [{"robot_id": str, "role": str, "objective": str, "goal": [x,y]}],\n'
    ' "needs_clarification": str|null, "risk": "low"|"medium"|"high"}\n'
    "Rules: only use robot_ids present in the snapshot. For a rendezvous, set "
    "each robot's goal near the centroid of all robots, offset so they stop ~0.8 m "
    "apart (do NOT put two robots on the same point). For a relay, also fill "
    "handoff_from/handoff_to/handoff_task (default task 'patrol'). If the command "
    "is not a fleet maneuver you can carry out, set needs_clarification and leave "
    "assignments empty. Reply with raw JSON only — no markdown, no commentary."
)


_CHOREO_SYS = (
    "You are the commander of a fleet of Unitree G1 humanoids. Convert the "
    "operator's command (any language) into per-robot action sequences. Output "
    "ONE JSON object and NOTHING else:\n"
    '{"summary": "<short, may be Chinese>",\n'
    ' "ops": {"<robot_id>": [{"op": <name>, "args": {...}}, ...]}}\n'
    "Use ONLY these ops:\n"
    "  navigate {x,y}                  walk to a point (metres)\n"
    '  circle   {dir:"cw"|"ccw", seconds}   walk a small circle for N seconds\n'
    "  face     {x,y}                  turn in place to face a point\n"
    "  arms_up  {seconds}              raise both arms overhead and hold\n"
    "  hold     {seconds}              stand still for N seconds\n"
    "  patrol | idle | sleep | wake    posture only (no args)\n"
    "Rules: use only robot_ids present in the snapshot. Order each robot's ops; "
    "robots run their sequences concurrently and advance independently. For "
    "'face each other', set each robot's face target to the OTHER robot's final "
    "(x,y). For a side-by-side row, give nearby goals offset ~1.2 m along one "
    "axis. Reply with raw JSON only — no markdown, no commentary."
)


def extract_plan_json(text: str) -> dict:
    """Pull the first balanced top-level JSON object out of ``text``.

    codex (especially at high reasoning) may wrap the answer in prose or ```json
    fences and the plan itself nests objects/arrays, so a regex won't do: we scan
    for the first '{' and walk to its matching '}', honouring string literals and
    escapes. Raises ValueError if no parseable object is present."""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # not valid JSON; try the next '{'
        start = text.find("{", start + 1)
    raise ValueError(f"no JSON object found in codex reply: {text[:200]!r}")


def _default_client(workdir: Path, model: str, reasoning: str):
    from g1_brain.memory.codex_client import CodexClient
    return CodexClient(
        workdir=workdir,
        sandbox="read-only",
        reasoning_effort=reasoning,
        reasoning_summary="concise",
        service_tier="fast",
    ), model


class CodexFleetLLM:
    """FleetCommander-compatible llm backed by the codex brain.

    ``client`` is injectable for tests; in production it is a CodexClient. When
    constructed with the default client, ``model`` is passed per-call as the
    codex ``-m`` override (the default gpt-5.3-codex is not available on a
    ChatGPT plan)."""

    def __init__(self, *, client=None, model: str = "gpt-5.5",
                 reasoning: str = "xhigh", timeout_s: float = 90.0,
                 workdir: Optional[Path] = None):
        self._timeout_s = timeout_s
        if client is None:
            client, model = _default_client(
                workdir or Path.cwd(), model, reasoning)
        self._client = client
        self._model = model

    def is_available(self) -> bool:
        fn = getattr(self._client, "is_available", None)
        return bool(fn()) if fn else True

    def plan_fleet(self, nl: str, snapshot: dict) -> Optional[dict]:
        prompt = (f"{_SYS}\n\ncommand: {nl}\n"
                  f"snapshot: {json.dumps(snapshot, ensure_ascii=False)}")
        res = asyncio.run(self._exec(prompt))
        return extract_plan_json(res.text)

    def plan_choreography(self, nl: str, snapshot: dict) -> Optional[dict]:
        """Codex composes per-robot op sequences (the rich vocabulary). Returns
        {"summary", "ops": {rid: [{op,args}]}}."""
        prompt = (f"{_CHOREO_SYS}\n\ncommand: {nl}\n"
                  f"snapshot: {json.dumps(snapshot, ensure_ascii=False)}")
        res = asyncio.run(self._exec(prompt))
        return extract_plan_json(res.text)

    async def _exec(self, prompt: str):
        kw = {"timeout_s": self._timeout_s}
        if self._model:
            kw["model_override"] = self._model
        return await self._client.exec_once(prompt, **kw)

    # Sub-agents stay deterministic; never route op-expansion through codex.
    def plan_robot(self, robot_id, assignment, coordination):  # pragma: no cover
        return None
