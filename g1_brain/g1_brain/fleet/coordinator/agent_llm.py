"""CoordinatorAgent — the optional LLM layer (parse NL + explain decisions).

Per the design (doc §6.4, §20.3) the LLM never decides dispatch: it only turns
operator natural language into a StructuredOp and explains decisions from real
evidence. A deterministic command grammar is ALWAYS available, so the system is
fully usable with no API key. Every parsed op is re-validated against the live
registry before the deterministic engine acts on it.

Wire an ``llm`` adapter (duck-typed: ``parse(nl)->dict|None`` and
``explain(prompt)->str``) to enable the LLM path; ``OpenAIChatLLM`` is a
best-effort adapter used by the app when OPENAI_API_KEY is present.
"""
from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)


@dataclass
class StructuredOp:
    kind: str           # dispatch | sleep | wake | takeover | status
    args: Dict


class CoordinatorAgent:
    def __init__(self, llm=None):
        self._llm = llm

    # ---- parse ----
    def parse(self, nl: str) -> Optional[StructuredOp]:
        if self._llm is not None:
            try:
                d = self._llm.parse(nl)
            except Exception:  # noqa: BLE001
                log.warning("llm parse failed; falling back to grammar", exc_info=True)
                d = None
            if d and d.get("kind"):
                return StructuredOp(kind=d["kind"], args=dict(d.get("args") or {}))
        return self._grammar_parse(nl)

    @staticmethod
    def _grammar_parse(nl: str) -> Optional[StructuredOp]:
        try:
            toks = shlex.split(nl.strip())
        except ValueError:
            return None
        if not toks:
            return None
        verb = toks[0].lower()
        if verb == "status":
            return StructuredOp("status", {})
        if verb == "dispatch":
            task = toks[1] if len(toks) > 1 else "patrol"
            target = "fleet"
            if "--to" in toks:
                i = toks.index("--to")
                if i + 1 < len(toks):
                    target = toks[i + 1]
            return StructuredOp("dispatch", {"task": task, "target": target})
        if verb in ("sleep", "wake") and len(toks) > 1:
            return StructuredOp(verb, {"robot": toks[1]})
        if verb == "takeover" and len(toks) > 2:
            return StructuredOp("takeover", {"from": toks[1], "to": toks[2]})
        return None

    # ---- validate (deterministic gate over any op, LLM or grammar) ----
    def validate(self, op: Optional[StructuredOp], registry) -> Tuple[bool, str]:
        if op is None:
            return False, "unparseable command"
        rids = {r["robot_id"] for r in registry.list_robots()}
        if op.kind in ("sleep", "wake"):
            r = op.args.get("robot")
            if r not in rids:
                return False, f"unknown robot {r!r}"
        if op.kind == "takeover":
            for who in (op.args.get("from"), op.args.get("to")):
                if who not in rids:
                    return False, f"unknown robot {who!r}"
        return True, "ok"

    # ---- explain ----
    def explain(self, *, decision: str, evidence: Dict) -> str:
        if self._llm is not None:
            try:
                prompt = (f"Explain this fleet dispatch decision in one sentence, "
                          f"citing the evidence. Decision: {decision}. "
                          f"Evidence: {evidence}.")
                return self._llm.explain(prompt)
            except Exception:  # noqa: BLE001
                log.warning("llm explain failed; using template", exc_info=True)
        parts = ", ".join(f"{k}={v}" for k, v in evidence.items())
        return f"{decision} (evidence: {parts})"


class OpenAIChatLLM:  # pragma: no cover - needs network/key
    """Best-effort OpenAI adapter. Returns None/raises are handled by the agent."""

    def __init__(self, *, model: str = "gpt-4o-mini", api_key: Optional[str] = None):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key) if api_key else OpenAI()
        self._model = model

    def parse(self, nl: str) -> Optional[dict]:
        import json
        sys = ("Convert the operator command into JSON with keys 'kind' "
               "(one of dispatch|sleep|wake|takeover|status) and 'args'. "
               "For sleep/wake: args.robot. For takeover: args.from,args.to. "
               "For dispatch: args.task,args.target. Reply with JSON only.")
        resp = self._client.chat.completions.create(
            model=self._model, temperature=0,
            response_format={"type": "json_object"},
            messages=[{"role": "system", "content": sys},
                      {"role": "user", "content": nl}])
        return json.loads(resp.choices[0].message.content)

    def explain(self, prompt: str) -> str:
        resp = self._client.chat.completions.create(
            model=self._model, temperature=0.2,
            messages=[{"role": "user", "content": prompt}])
        return resp.choices[0].message.content.strip()
