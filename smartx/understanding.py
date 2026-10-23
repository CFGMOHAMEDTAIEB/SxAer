"""Deterministic autonomous understanding primitives for uploaded artifacts."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class UnderstandingResult:
    classification: str
    structure: dict[str, Any] = field(default_factory=dict)
    profile_suggestion: dict[str, Any] = field(default_factory=dict)
    canonical_json: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UnderstandingService:
    """Classify, inspect, suggest a profile, and translate to canonical JSON."""

    def analyze(self, filename: str, text: str, metadata: dict[str, Any] | None = None, items: list[dict[str, Any]] | None = None) -> UnderstandingResult:
        metadata = metadata or {}
        items = items or []
        lower = text.lower()
        if metadata.get("artifact_type") and metadata["artifact_type"] != "unknown":
            classification = str(metadata["artifact_type"])
        elif re.search(r"\b(shall|must|should|required)\b", lower):
            classification = "requirement"
        elif re.search(r"\b(test|assert|verification)\b", lower):
            classification = "test"
        elif re.search(r"\b(void|class|struct|#include)\b", lower):
            classification = "code"
        else:
            classification = "unknown"
        headings = [line.strip().lstrip("# ") for line in text.splitlines() if re.match(r"^\s*#{1,6}\s+", line)]
        symbols = re.findall(r"\b(?:void|int|bool|float|class|struct)\s+([A-Za-z_]\w*)\s*(?:\(|\{)", text)
        sections = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        rationale = f"Detected {len(items)} requirement item(s), {len(headings)} heading(s), and {len(symbols)} code symbol(s)."
        profile = "do178c" if re.search(r"DO[- ]?178C|software level|verification method", text, re.I) else str(metadata.get("profile", "generic"))
        confidence = 0.9 if classification != "unknown" and (items or text.strip()) else 0.35
        evidence = [{"kind": "classification", "source": filename, "location": "content", "text": rationale}]
        canonical = {"document_type": classification, "title": filename.rsplit(".", 1)[0], "content": text, "items": items, "metadata": {"format": metadata.get("format"), "sections": sections, "headings": headings, "code_symbols": symbols}, "provenance": [{"source_name": filename}]}
        return UnderstandingResult(classification, {"sections": sections, "headings": headings, "paragraph_count": len(sections), "code_symbols": symbols}, {"profile": profile, "rationale": rationale, "evidence": evidence, "confidence": confidence}, canonical, confidence, evidence)

    @staticmethod
    def translate(result: UnderstandingResult) -> str:
        return json.dumps(result.canonical_json, indent=2, ensure_ascii=False, default=str)