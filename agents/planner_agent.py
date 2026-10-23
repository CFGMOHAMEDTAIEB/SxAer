"""Typed deterministic planning agent with evidence and confidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class PlanStep:
    id: str
    action: str
    rationale: str
    evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


@dataclass
class PlanOutput:
    goal: str
    steps: list[PlanStep]
    route: str
    confidence: float
    human_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PlannerAgent:
    def plan(self, request: str, understanding: dict[str, Any] | None = None) -> PlanOutput:
        understanding = understanding or {}
        evidence = understanding.get("evidence", [])
        steps = [PlanStep("understand", "normalize and classify artifacts", "establish a canonical evidence-backed input", evidence, 0.9), PlanStep("validate", "check required fields and profile rules", "prevent incomplete artifacts from entering downstream analysis", evidence, 0.85), PlanStep("trace", "create only evidence-backed relationships", "avoid fabricated verification links", evidence, 0.85)]
        confidence = float(understanding.get("confidence", 0.75))
        return PlanOutput(request or "analyze uploaded artifacts", steps, "deterministic-reviewable", confidence, confidence < 0.75)