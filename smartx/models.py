"""Small, serialisable domain models used by SmartX."""

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List


@dataclass
class Provenance:
    source_name: str = "unknown"
    source_type: str = "text"
    source_hash: str = ""
    page: int | None = None
    sheet: str | None = None
    cell: str | None = None
    paragraph: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    extraction_method: str = "standard-library"
    confidence: float = 0.0
    extractor: str = "standard-library"


@dataclass
class SmartXDocument:
    document_type: str = "requirement"
    title: str = "Untitled document"
    content: str = ""
    items: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    profile: str = "generic"
    confidence: float = 0.0
    human_review_required: bool = False
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentResult:
    agent: str
    status: str = "completed"
    confidence: float = 0.0
    human_review_required: bool = False
    findings: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)