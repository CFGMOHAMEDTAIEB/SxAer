"""Editable, transparent profile rules for the Validation Workspace."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_RULES = {
    "generic": {"rules": [{"id": "GEN-001", "text": "Requirement uses verifiable normative wording.", "severity": "medium", "applicability": "requirement"}], "confidence_threshold": 0.75, "human_review_threshold": 0.75},
    "do178c": {"rules": [{"id": "DO178C-SAMPLE-001", "text": "Requirement has a verification method and objective evidence.", "severity": "high", "applicability": "requirement"}], "confidence_threshold": 0.8, "human_review_threshold": 0.8},
    "gt44": {"sample_rules": True, "rules": [{"id": "GT44-SAMPLE-001", "text": "Capture source and assurance context for review.", "severity": "medium", "applicability": "requirement"}], "confidence_threshold": 0.8, "human_review_threshold": 0.8},
}

class ProfileConfiguration:
    def __init__(self, path: str | Path = "configs/validation_profiles.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = dict(DEFAULT_RULES)
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass

    def get(self, profile: str) -> dict[str, Any]:
        return self.data.get(profile, self.data["generic"])

    def update(self, profile: str, value: dict[str, Any]) -> None:
        current = dict(self.data.get(profile, self.data["generic"]))
        current.update(value)
        if profile == "gt44":
            current["sample_rules"] = True
        self.data[profile] = current
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")

    def profiles(self) -> list[str]:
        return sorted(self.data)
