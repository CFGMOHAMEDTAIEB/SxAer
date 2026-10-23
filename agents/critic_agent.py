"""Typed critic with one bounded repair recommendation."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CriticOutput:
    status: str
    issues: list[dict[str, Any]] = field(default_factory=list)
    repair: dict[str, Any] | None = None
    confidence: float = 0.0
    human_review_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CriticAgent:
    def review(self, plan: dict[str, Any] | Any, artifact: dict[str, Any] | None = None, repair_count: int = 0) -> CriticOutput:
        plan_data = plan.to_dict() if hasattr(plan, "to_dict") else plan
        artifact = artifact or {}
        issues: list[dict[str, Any]] = []
        if not plan_data.get("steps"):
            issues.append({"code": "empty_plan", "message": "No executable steps were proposed.", "evidence": []})
        if not artifact.get("items") and artifact.get("document_type") == "requirement":
            issues.append({"code": "missing_requirements", "message": "Requirement artifact has no normalized items.", "evidence": artifact.get("provenance", [])})
        if issues and repair_count < 1:
            return CriticOutput("repair", issues, {"action": "re-run normalization", "max_cycles": 1}, 0.8, False)
        return CriticOutput("human_review" if issues else "accepted", issues, None, 0.65 if issues else 0.9, bool(issues))