from smartx.extraction import extract_document, split_requirements
from smartx.models import AgentResult
from smartx.understanding import UnderstandingService


class DocumentUnderstandingAgent:
    """Normalizes an uploaded source and preserves extraction provenance."""

    def run(self, file_name: str, data: bytes) -> AgentResult:
        text, metadata, provenance = extract_document(file_name, data)
        items = split_requirements(text, metadata)
        understanding = UnderstandingService().analyze(file_name, text, metadata, items)
        metadata = {**metadata, "understanding": understanding.to_dict()}
        return AgentResult(
            "document_understanding",
            confidence=understanding.confidence if text else 0.35,
            human_review_required=not bool(text) or bool(provenance.get("warnings")) or understanding.confidence < 0.75,
            artifacts={"content": text, "metadata": metadata, "provenance": provenance, "items": items, "understanding": understanding.to_dict()},
        )
